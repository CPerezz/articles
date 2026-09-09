# Besu state-DB study — execution ledger

One entry per round: what was attempted, what happened, what it means. Failures and
retractions stay in, per the geth study's convention.

Plan: `docs/superpowers/plans/2026-09-09-besu-state-db-study.md`.

---

## Round 0 — environment prepared, generator validated

**2026-09-09.** Phase 0 (teardown) complete, Phase 1 (inputs) running.

### Teardown

Keep-set inventory recorded first, at `/root/bench/keepset-before-besu.txt`:

| kept | files | bytes |
|---|---|---|
| `eest-url/3cf555c593bcb136` (state-actor payloads) | 75 | 2,947,954,846 |
| `eest-url/6142626aac06abc4` (jochemnet payloads) | 74 | 13,020,033,671 |
| `/data/fixtures` | — | 2,172,012,351 |
| `/data/bench-results` | — | 10,975,142,088 |
| `/data/archive/run1` | — | 2,931,577,103 |

Deleted: the three NVMe loop images (`jochemnet-virgin`, `jochemnet-scratch`, `sa-nvme`,
3.0 T), both frozen archives (`jochemnet-virgin-{pristine,promoted}.img.zst`, 1.8 T),
`/data/sa-store` (551 G), and the geth snapshot tarball (937 G). The volumes were live, so
the order was `umount` → `dmsetup remove jochemnet_era2` → `losetup -d` → delete.

Result: **NVMe 219 G → 3.2 T free; HDD 7.2 T → 11 T free.**

Untouched, and confirmed as *not ours*: `/data/eth` (17 T), `/data/allhot-src-parked`,
`/data/CPerezz-preserved`, and `/data/tmp/benchmarkoor-overlay-geth-allcold-hdd-*` — the last
of these turned out to be **four live overlay mounts** whose lowerdir is
`/data/eth/geth/geth-snapshots/jochemnet-24402727/allcold-datadir`. Deleting them would have
broken a running study.

### Three defects found in the generator path

The plan predicted Phase 1b was mechanical. It was not. Each of these would have surfaced
hours into an unattended job:

1. **The host `state-actor` binary cannot write Besu**, despite advertising it.
   `--help` lists `-client geth|nethermind|besu|reth|ethrex|erigon`; running it gives
   `client/besu: requires the cgo_besu build tag and librocksdb. --client=besu is Docker-only`.
   Flag inspection passes, execution fails. Only running it reveals this.

2. **The operator's working tree cannot build the image.** `go.mod` is dirty with
   `replace github.com/erigontech/erigon => /home/CPerezz/erigon-14273`, a host path invisible
   to the build context, so `go mod download` dies. Neither the `require` nor the `replace` is
   in `HEAD`.
   Resolution: build from a **copy** of the tree (never mutate the operator's 31 files of WIP)
   with `go.mod`/`go.sum` reverted to `HEAD`. Justified by inspection — all 31 dirty files are
   erigon WIP (`client/erigon`, `internal/erigon/*`, `internal/streamsort`); **zero besu or
   rocksdb files are modified**, so the Besu writer is identical either way. Copy differs from
   the operator tree by exactly one file (`go.mod`), and still reports `VERSION=e4cb205-dirty`,
   `REVISION=e4cb20588f3aac3ae7b6313c4cad5fe5b4135772` — matching the geth baseline's recorded
   provenance.

3. **`make smoke-besu` is stale.** It passes `--inject-accounts`, a flag this binary does not
   have (exit 2, usage dump). Its validator is stale too: step 5 calls `eth_sendTransaction`,
   which Besu rejects outright — *"Use eth_sendRawTransaction"* — so steps 4–6 cannot pass on
   any build. Not chased; the target is not our dependency.

### Generator validated anyway

Ran the generation directly, then upstream's validator for the parts that still work:

```
$ docker run --rm -v /tmp/sa-besu-smoke:/data state-actor-besu:latest \
    --client=besu --db=/data --target-size=4MB --seed=42 --chain-id=1337
Total Time: 408ms   Accounts: 3298   Contracts: 1500   Slots: 19566
State Root: 0x5d64c1eb9f0bc3a54b2cc64555c4502642bef3092f6e8d2d38f34d1f9c1f394d
```
```
[1/6] Booting hyperledger/besu:25.11.0 ...   RPC up
[2/6] chainId=0x539 (expected 0x539)   block=0x0 (expected 0x0)
[3/6] Genesis state root match ...   MATCH
```

**Besu independently recomputes the state root state-actor wrote.** That is the gate.

Layout produced — `database/` (RocksDB), `besu-chainspec.json`, `DATABASE_METADATA.json`,
`state-actor-manifest.json`. Two observations worth carrying forward:
- `--db` is confirmed as the **datadir root** for Besu (geth took `.../geth/chaindata`).
- The store contains **`.blob` files**: RocksDB BlobDB key–value separation is enabled.
  Pebble has no equivalent. This is a live variable for the F3 residual arithmetic, which on
  geth ran through SST block geometry alone — on Besu, large values may not live in the SST at
  all. Any port of `sstgeom` must account for blob files or it will measure the wrong bytes.

### Running

- **1a** — snapshot download, `/root/bench/fetch-besu.sh` → `/data/snapshots/besu/`. Verifies
  against `Content-Length` 1,003,259,660,471 then `zstd -t`. ~90 MB/s.
- **1b** — real generation, `/home/CPerezz/gen-sa-besu.sh`, image
  `sha256:42f68d6a61389f16e04cbceb83e886791730a1a54d7c9f9ba6c42ea6a67a649a`, mirroring the geth
  baseline: `--target-size=350GB --spec=state-actor-spec-baseline.yaml --seed=42 --fork=osaka
  --gas-limit=1000000000`, no `--chain-id` (default 1337, as geth had). Confirmed at start:
  `Synthesized genesis: fork=osaka chainID=1337 gasLimit=1000000000 timestamp=0 extraData=0B`.

**Next:** on completion, assert the generated store's genesis state root equals the anchor in
the cached state-actor payload bundle (`eest-url/3cf555c593bcb136`). That is the check which
proves the geth-filled payloads drive the Besu arm unchanged.

---

## Round 1 — the compaction tool, and a version skew nobody would have predicted

**Hypothesis.** Besu ships no `geth db compact` equivalent, so a full offline compaction needs
a custom tool. Linking Besu's own `rocksdbjni-10.6.2.jar` and loading the store's own OPTIONS
file should make it exactly faithful.

**Test.** `tools/besu-study/Compact.java` — ~50 lines: `OptionsUtil.loadLatestOptions` →
`RocksDB.open` with every column family → `compactRange(cf, null, null)` with
`BottommostLevelCompaction.kForce` → close. Compiled in `eclipse-temurin:21-jdk` against the
jar extracted from `ethpandaops/besu:bal-devnet-7`.

Two design points, both load-bearing:
- **Load OPTIONS, never guess.** These stores use BlobDB (`.blob` files). Opening with default
  options would rewrite blob-separated values back into SSTs during compaction — a physical
  layout change Besu never intended, which would corrupt the exact measurement the study
  exists to make.
- **`kForce`.** Without it RocksDB skips the bottommost level when it thinks it is already
  compacted, so "compacted" would silently mean different things on different stores.

**Result — works, but only on a store Besu has opened.** On a freshly generated store:
```
org.rocksdb.RocksDBException: Extra option not recognized: max_manifest_space_amp_pct
```

**Verdict — version skew between the generator and the client.** state-actor's image links
**librocksdb 10.10**; Besu ships **rocksdbjni 10.6.2**. The generator writes an OPTIONS file
with 10.10-only keys that 10.6.2 refuses to parse. Proven by the OPTIONS sequence on one store:

| file | written by | has `max_manifest_space_amp_pct` |
|---|---|---|
| `OPTIONS-000007` | state-actor (10.10) | yes |
| `OPTIONS-000021` | Besu 25.11.0, on first open | no |

After Besu's first open the tool loads cleanly and compacts all 16 column families
(`default`, `01`, `03`, `04`, `06`–`11` — Besu names them with single binary bytes, so the
tool hex-encodes them).

Note this does **not** affect Besu itself: it opens with explicitly-constructed options rather
than by reading the OPTIONS file, which is why the generated store boots and matches its state
root regardless. Only an external reader trips over it.

**Consequence for the pipeline:** compaction must run *after* Besu has opened the store — which
the real sequence does anyway, since the treatment happens after the pre-runs. The tool now
exits 3 with the remedy spelled out rather than a raw RocksDB stack trace.

**Also recorded:** the generator container runs as root, so generated stores are root-owned.

---

## Round 2 — the inventory and treatment commands, validated

**Hypothesis.** Besu's shipped `storage` subcommands can supply both halves of the geth
protocol: `trie-log prune` as the journal-drain analogue, and something equivalent to
`geth db inspect` for the side-by-side store table.

**Test.** Both commands against a generated store.

**First attempt failed**, informatively:
```
InvalidConfigurationException: Supplied genesis block does not match chain data stored in /data
```
The `storage` subcommands recompute the genesis state root from the chainspec alloc, and
state-actor emits an **empty** alloc. `--genesis-state-hash-cache-enabled=true` is therefore
mandatory for every offline command, not just for booting — exactly the case `pkg/client/besu.go`
documents. Any script that omits it fails at the last step of a long run.

**Result.** Both work.

`storage trie-log count` on a generated store:
```
trieLog count: 0   (canonical 0, fork 0, orphaned 0)
```
A generator writes state, not history — so the state-actor arm carries **no trie logs at all**,
precisely mirroring the geth SA store carrying no journal. The treatment is a no-op on that arm
and only bites the jochemnet arm, which is the same asymmetry the geth study had.

`storage rocksdb usage` — the `geth db inspect` analogue, and better, because the column
families are named and keys are counted separately from bytes:

| Column Family | Keys | Total Size |
|---|---|---|
| ACCOUNT_INFO_STATE | 4,798 | 294 KiB |
| CODE_STORAGE | 1,500 | 545 KiB |
| ACCOUNT_STORAGE_STORAGE | 19,566 | 1 MiB |
| TRIE_BRANCH_STORAGE | 33,332 | 3 MiB |
| VARIABLES | 1 | 1 KiB |

It also reports **Blob Files Size** per family, which the geth study had no equivalent of.

**Why this matters for P4.** The geth residual arithmetic ran
`bytes ÷ entries → B/entry → compression → block size → pages`. `ACCOUNT_INFO_STATE` gives
keys and bytes for the flat account keyspace directly, so the Besu B/entry figure (geth: 49.6
vs 58.3) is a one-command measurement per store rather than the custom `snapstat` scan the geth
study needed.

**Boot-log observations worth carrying into P2/P3**, all from a single open:
- `versionedStorageFormat=BaseVersionedStorageFormat{format=BONSAI, version=3}`
- `Processing WAL...` — RocksDB replays its write-ahead log on open. This is the closest
  structural analogue to geth's journal reload and is now the leading P2 candidate.
- `Flat db mode found FULL` — reads serve from the flat keyspace, not the trie, so the geth
  finding that account reads are one flat read (not an 8-node trie walk) should carry over.
- `DB mode with code stored using code hash enabled = true` — relevant to F3: contract code is
  keyed by hash, and 32-byte hashes were the incompressible records that drove the geth residual.
