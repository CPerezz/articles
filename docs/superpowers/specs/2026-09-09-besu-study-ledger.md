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

---

## Round 3 — fork activation for the runner, and the arm configs

**Why this round exists.** Round 20 of the geth study was lost to a fork-activation mismatch
(`--override.amsterdam=1` on one arm vs `1769856769` on the other). Besu has **no
`--override.amsterdam` flag at all** — its fork schedule lives in the genesis file — so the
equivalent had to be located before writing configs, not after a failed run.

**Found.** `pkg/config/config.go` defines `genesis_fork_override` on **`ClientInstance`**, the
runner's per-instance struct, not just on builder targets. The comment on the builder copy
confirms the intent: it patches genesis at filler boot *"identically to the runner"*.

Mapping, arm for arm:

| | geth (published study) | besu |
|---|---|---|
| state-actor arm | `--override.amsterdam=1` | `genesis_fork_override: { amsterdam: 1 }` |
| jochemnet arm | `--override.amsterdam=1769856769` | `genesis_fork_override: { amsterdam: 1769856769 }` |

The state-actor value must be `1`, not the jochemnet timestamp: state-actor synthesises genesis
at `--fork=osaka` (confirmed in the boot log: `milestones: [Osaka:0]`) with `timestamp=0`, so
Amsterdam is activated on top at 1 — exactly what the geth arm did.

**Configs drafted:** `tools/besu-study/config.besu-{state-actor,jochemnet}.yaml`, derived from
`/root/bench/{state-actor,jochemnet}.yaml` and changed only where Besu forces it: `datadirs.besu`
with the datadir **root** as source (geth used `.../geth/chaindata`), the fork override above, and
`BESU_OPTS="-Xms8g -Xmx8g -XX:+AlwaysPreTouch"` from the upstream besu target. Fixtures are
deliberately **unchanged** — still the geth-filled bundles, including
`pre-runs/geth/pre_run_bundle`.

One arm file covers both jochemnet runs; untreated vs treated differs only by `results_dir` and
whether `BENCHMARKOOR_POST_PRERUN_CMD` is exported, keeping the two runs otherwise identical.

**Open item, flagged not guessed.** The geth jochemnet arm needed no genesis file — geth reads
chain config from the datadir. Besu's spec declares `GenesisFlag() == "--genesis-file="`, so the
jochemnet arm needs one from somewhere: the snapshot, `client.config.genesis`, or the fixtures.
Resolve by inspecting the extracted tarball; do not assume. (The state-actor arm has no such
problem — the generator emits `besu-chainspec.json` beside the store.)

---

## Round 4 — operational tooling

`tools/besu-study/rockscompact` — one-word wrapper so the pre-run hook stays readable.

`tools/besu-study/besu-inventory.sh <datadir> <genesis> <label>` — the per-store "before"
snapshot, validated end to end. Emits, in one file: trie-log count; `rocksdb usage` per column
family (keys, total, SST bytes, **blob bytes**); a physical file census (sst/blob/**wal** counts
and bytes); and an SST size histogram.

Two of those go beyond what the geth study could measure. Blob bytes are a BlobDB concept Pebble
has no equivalent of. WAL bytes matter because `Processing WAL...` on open (round 2) is the
leading P2 candidate — the Besu analogue of geth's journal reload — so the WAL census must be
taken *before* Besu ever opens a store, or the evidence is destroyed by the act of measuring it.

**Consequence for the pipeline:** the untreated jochemnet inventory must be taken with the file
census only (no `besu storage` subcommand, since those open the store and replay/clear the WAL).
The `besu`-driven half of the inventory is safe to run afterwards.

---

## Round 5 — volume layout and arm sequencing

`schelk init-new --virgin <img> --scratch <img> --ramdisk <path> --mount-point <path>` creates
the ext4 golden image and clones it to scratch; the store is then populated on the mounted
scratch and frozen with `promote`. The geth study's instance was `/schelk-vols/jochemnet-{virgin,
scratch}.img` → dm-era `jochemnet_era2` → `/schelk`.

**The constraint, computed before committing to a layout.** NVMe is 3.5 T total:

| | size | note |
|---|---|---|
| jochemnet virgin + scratch | ~2.4 T | two copies, sized to the extracted snapshot |
| state-actor store | ~0.55 T | geth's equivalent was 551 G |
| state-actor virgin + scratch | ~1.1 T | needed only while that arm runs |

All three arms cannot be resident at once (2.4 + 1.1 + 0.55 = 4.05 T > 3.5 T). Sequencing,
which also preserves the matched-media rule that round 20 of the geth study established:

1. Archive the generated state-actor store to HDD (~550 G, cheap against 11 T free).
2. Build the jochemnet schelk pair, extract into it, promote. Run **untreated** then **treated**.
3. Tear down the jochemnet pair; restore the state-actor store to NVMe; build its schelk pair;
   run that arm.

Every arm is therefore measured on md2 NVMe, never the HDD array — the failure that invalidated
rounds 13/17/18 of the geth study (8× readahead difference, 2048 vs 256 KB).

**Still unknown, and it sizes the images:** the extracted footprint of the Besu snapshot. The
tarball is 1.003 TB zstd-compressed; geth's equivalent expanded to ~1.2 T. Size the images from
the measured extract, not from a guess.

---

## Round 6 — inputs landed; the state-actor store is bit-for-bit the same state as geth's

**Download.** Completed and verified (`rc=0`: byte count equals `Content-Length`
1,003,259,660,471, then `zstd -t` clean).

It failed once first, and the failure is worth recording: wget died at 72% with
`Connection closed at byte 724134002688. Giving up.` (exit 4). Over a ~4-hour transfer the far
end *will* drop the connection — the resumed run logged `(try: 7)`. Retry policy is mandatory,
not optional: `--tries=0 --retry-connrefused --waitretry=10 --timeout=60 --read-timeout=120`,
with `-c` doing the resuming. Six further drops were absorbed silently.

(`zstd -l` to pre-measure the extracted size was abandoned — it scans the whole archive when
the frame header carries no content size. Sparse schelk images make the measurement
unnecessary anyway.)

**Generation.** `rc=0` in **4 h 54 m**, **533 G** — against geth's 5 h 12 m and 553 G. The two
arms are the same size to within 4%, which is itself a useful control.

Pristine census, taken before any Besu process opened the store:

| | |
|---|---|
| SST files | 8,447 (572,008,647,022 bytes) |
| blob files | 1 (322 bytes) |
| **WAL** | 1 file, **0 bytes** |

The empty WAL matters: the generated store carries **no unflushed state**, exactly as geth's
SA store carried no journal. Whatever P2 turns up on the jochemnet arm, the generated arm has
no recency artifact to confound it. BlobDB is also effectively unused at 322 bytes, so the F3
arithmetic can stay in SST geometry after all — the round-0 worry does not bite.

Provenance is embedded in the store itself (`state-actor-manifest.json`): `version
e4cb205-dirty`, `vcs_revision e4cb20588f3aac3ae7b6313c4cad5fe5b4135772`, `vcs_modified true`,
and the full argv.

### The anchor assertion — and an unexpectedly strong result

```
genesis hash  : 0xa9e61c12051aeda72581c40b1718fa76b80c0b5cc5f7b7ebe96e0b6d9669491b
payload anchor: 0xa9e61c12051aeda72581c40b1718fa76b80c0b5cc5f7b7ebe96e0b6d9669491b   MATCH
stateRoot     : 0x5b305cc0f85f9ffaf5eca1e72cfe0c82f92e14f121aed163cc4c0e784aa3b6e7
```

The genesis hash equals the `snapshotBlockHash` the cached payloads expect, so **the
geth-filled payloads drive the Besu arm unchanged** — the reuse claim is now measured, not
argued.

The stronger result is the state root: `0x5b305cc0…b6e7` is the **same value the geth
state-actor store reported** in its `db inspect` output. state-actor produced *the same logical
state* for two different clients from `--seed=42`. The two studies are therefore a genuine
controlled comparison — identical state, identical payloads, two storage engines — which is
precisely the design F3 needs to be tested rather than assumed.

**Phase 1 complete.** Next: archive the store to HDD, build the jochemnet schelk pair, extract,
promote (Phase 2 → 3).

---

## Round 7 — the state-actor arm is mounted, and the first cross-engine number

**Volume built.** `schelk init-new --granularity 65536 --dm-era-name besu_sa_era` on two 640 G
sparse images, mirroring the geth study's parameters (recovered from the stale
`/var/lib/schelk/state.json`: `/dev/ram0` for dm-era metadata, 64 KiB granularity, mount at
`/schelk`). Store copied in and verified byte-exact against the source —
**572,069,603,242 bytes, 8,467 files** on both sides — then promoted:

```
Blocks promoted: 8824533   Bytes copied: 538.61 GB   12m 53.80s   712.76 MB/s
```

dm-era tracked only the changed blocks, so promote moved 538 GB rather than the full 640 G.

**Two operational traps hit, both now fixed in the tooling.**

1. **`schelk promote` unmounts the scratch volume.** `/schelk/...` silently reverts to an empty
   directory on the root filesystem. The inventory script then reported `sst files: 0`,
   `wal bytes: 0` and let `docker -v` create `/genesis.json` as a *directory*. An inventory full
   of zeros is worse than no inventory, so `besu-inventory.sh` now hard-fails unless
   `$DATADIR/database` exists and `$GENESIS` is a regular file.
2. The failed run also left stray dirs under the mountpoint, which would have been shadowed
   after remounting and quietly wasted root-filesystem space. Removed.

**Inventory — `/schelk/state-actor/v1/besu`:**

| Column family | Keys | Size |
|---|---|---|
| ACCOUNT_INFO_STATE | 430,696,738 | 24 GiB |
| CODE_STORAGE | 134,442,676 | 43 GiB |
| ACCOUNT_STORAGE_STORAGE | 2,214,312,331 | 147 GiB |
| TRIE_BRANCH_STORAGE | 3,625,461,648 | 317 GiB |
| VARIABLES | 2 | 2 KiB |
| **total** | **6,404,913,395** | **532 GiB** |

trie logs 0. SSTs 8,450 (572,008,650,893 B), mean 64.6 MB, 8,127 of them in the 32–80 MB band.
Blob 322 B — BlobDB remains irrelevant here.

### The result worth stopping on

geth's state-actor store held **6,404,913,405 items in 674.25 GiB**. Besu's holds
**6,404,913,395 items in 532 GiB**.

The item counts differ by **10 out of 6.4 billion** — independent confirmation, from a
completely different code path than the state root, that state-actor produced the same logical
state for both clients. Yet Besu stores it in **21% less space**.

`ACCOUNT_INFO_STATE` is the sharper comparison, because it is the exact analogue of the geth
account snapshot the residual arithmetic ran on:

| | entries | size | B/entry |
|---|---|---|---|
| geth state-actor (account snapshot) | 430.7 M | 23.38 GiB | 58.3 |
| **besu state-actor (ACCOUNT_INFO_STATE)** | **430,696,738** | **24 GiB** | **≈59.8** |

Within ~2.5% across two storage engines. That is the first evidence for P4: the *record shape*
is a property of the data, not of the engine — which is exactly what F3 claims and what the
jochemnet arm must now be measured against (geth's jochemnet figure was 49.6 B/entry).

Treat 59.8 as provisional: `rocksdb usage` rounds to whole GiB. A precise figure needs the
`snapstat` port, which is Phase 5 work.

**Now running:** the source store is being archived to `/data/sa-besu-archive` (HDD) so the NVMe
copy can be freed for the jochemnet pair later; the SA volumes must be destroyed to make room,
and regenerating costs ~5 h.

---

## Round 8 — the pilot gate earns its cost immediately

**First attempt: 2 failed, 0 passed.** Not a typo-class failure — the chain wiring was correct
and the block was rejected on consensus grounds:

```
Invalid new payload: number: 1, parentHash: 0xa9e61c12...9491b   (our genesis — correct)
status: INVALID, validationError: Block access list hash mismatch
  calculated: 0xb1d04db6fc05f7f1f213667b2d0e3d6a0b8797d5c03130178168d16a5037fc64
  header:     0xbc207ccae7a10569a317cc3678a2b0b4e29ed0be27d40222833b60cbd26f4e98
```

Everything downstream then reported `SYNCING`, because the head was invalid — the same
signature that cost a day in the geth study, from a completely different cause.

**Cause: wrong image, and it was my error.** I lifted `ethpandaops/besu:bal-devnet-7` from the
upstream *state-actor build* config, where the image only ever has to **write state**. It never
has to execute a glamsterdam block. The tags tell the story:

| tag | published | |
|---|---|---|
| `besu:bal-devnet-7` | **2026-07-03** | a BAL-specific proof-of-concept devnet |
| `besu:glamsterdam-devnet-7` | **2026-08-13** | the pairing for the geth arm's `glamsterdam-devnet-7` build |

Two months apart, and a different EIP-7928 revision — so Besu computed a BAL the geth-filled
payload's header did not declare.

**Fix:** `image: docker.io/ethpandaops/besu:glamsterdam-devnet-7`.

**Second attempt: `failed=0 passed=2 total=2`** in 1m35s, no `INVALID`, no `SYNCING`.

Real execution, not merely a non-failure — from `test.result-aggregated.json`:

| | |
|---|---|
| gas_used_total | 159,998,116 (the 160M-gas category) |
| time_total | 20.76 s |
| disk_read_bytes | 17,063,342,080 |
| disk_read_iops | 872,412 |
| cpu_usec | 28,972,729 |

**Two things this settles.**

1. *The payload-reuse claim now holds end to end.* geth-filled payloads execute on Besu and
   produce VALID blocks — but only against a client of the matching devnet. Payloads are
   client-agnostic; they are **not** devnet-agnostic, and the BAL hash is what enforces that.
2. *The gate was worth its ~10 minutes.* This failure is invisible to config review — the YAML
   was correct, the store was correct, the payloads were correct. Only executing a block
   surfaces it. Committing 16 h to the suite first would have produced a run of 1,400 `SYNCING`
   failures.

An early cross-client data point, offered as observation not finding: 159,998,116 gas in
20.751 s ≈ **7.7 MGas/s** on BALANCE/DIFF_MAX@160M, against geth's ~16.5 MGas/s for the same
category post-fix. Single cold measurement, not a median — do not quote it.
