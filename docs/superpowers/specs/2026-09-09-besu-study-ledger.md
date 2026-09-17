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

---

## Round 9 — SST geometry probe, and the F3 arithmetic will not transfer unchanged

**Tool.** `tools/besu-study/SstGeom.java`, the Besu port of the geth study's `sstgeom`. Same
version-matched `rocksdbjni-10.6.2.jar` as the compactor. It reads RocksDB's own table
properties via `getPropertiesOfAllTables(cf)` rather than sampling files, so the numbers are
exact and correctly CF-scoped, and it opens **read-only** so a store can be measured without
mutating it.

Column families are identified by **entry count**, not by guessing Besu's segment ids — the
counts come from `storage rocksdb usage` and are unmistakable. Validated against the HDD
archive (md3), deliberately not the live NVMe store, so the running suite's timings were not
perturbed.

**Result — state-actor store:**

| cf | entries | = | ssts | mean raw record | compressed bytes/block | phys÷log |
|---|---|---|---|---|---|---|
| 06 | 430,696,738 | ACCOUNT_INFO_STATE | 228 | 119.7 B | 16,696.6 | 0.513 |
| 07 | 134,442,676 | CODE_STORAGE | 714 | 398.1 B | 29,135.9 | 0.863 |
| 08 | 2,214,312,331 | ACCOUNT_STORAGE_STORAGE | 2,381 | 99.7 B | 32,217.4 | 0.716 |
| 09 | 3,625,461,648 | TRIE_BRANCH_STORAGE | 5,122 | 128.0 B | 29,636.7 | 0.734 |

Every entry count matches the inventory exactly, so the identification is sound. The physical
total also reconciles: 26,421,412,281 B of data for cf 06 against the 24 GiB `rocksdb usage`
reported.

### Why this matters, before the jochemnet arm lands

The geth residual ran on this chain: 58.3 B/entry → Snappy 0.991 → **3,467 vs 4,043 byte
blocks** → 1.85 vs 1.99 **4 KiB pages** per read → +7.6% pages against +11.9% measured bytes.
Two of those terms do not carry over:

- **Block size.** Besu's account blocks are **~16.7 KB compressed** (≈32 KB logical, ~272
  records each), not ~4 KB. A lookup fetches a far larger unit, so the page-quantisation step
  that made geth's arithmetic close cannot be reused as-is.
- **Compressibility.** cf 06 compresses to **0.513** of logical, against geth's 0.991 for the
  same logical state. Snappy on Besu's keyspace behaves nothing like Snappy on geth's.

That is not a problem for the study — it is the point of running it. F3 claims the residual is
a property of *the data*; if it reproduces on an engine whose block size is 4× larger and whose
compression ratio is half, the claim is strong. If the residual vanishes here, F3 was
Pebble-specific after all.

**One caution recorded now, before the numbers tempt anyone.** `mean raw record` here is
`(raw_key_size + raw_value_size) / entries` and so includes RocksDB's internal key bytes;
119.7 B is *not* comparable with geth's 58.3 B/entry, which counted the account record. The
comparable pair is physical size for the same logical state: 24 GiB (Besu cf 06) vs 23.38 GiB
(geth account snapshot). The like-for-like decomposition is Phase 5 work, against the jochemnet
arm, and must be done per store rather than across engines.

---

## Round 10 — Besu's instrumentation works, and the flat-read model transfers

**Why this round.** The geth study's appendix documented broken meters: cache counters frozen
at zero, `state_reads` that never moved, `execution_ms` negative on 176 of 1,218 blocks. Before
relying on any Besu counter, verify it moves under real load — the same discipline, applied
before rather than after.

**Counters found** (scraped from a live Besu on the throwaway store, names confirmed):

```
besu_blockchain_get_account_total
besu_blockchain_get_account_flat_database_total
besu_blockchain_get_account_missing_flat_database_total
besu_blockchain_get_storagevalue_flat_database_total
besu_blockchain_bonsai_cache_{hits,misses,requests,inserts}_total
```

**Verified live**, sampled from the running suite's own container mid-test:

| metric | value |
|---|---|
| `get_account_total` | 9,439 |
| `get_account_flat_database_total` | 9,423 |
| `get_account_missing_flat_database_total` | 1 |
| `bonsai_cache_hits / misses` | 7,303 / 62,547 |

**Two results.**

1. **The meters are sound.** They are non-zero and advancing under real execution. Besu's
   instrumentation is materially better than what geth offered this study: account reads are
   counted directly and split by flat-database hit/miss, so **P5** ("accounts read are identical
   across arms") becomes a direct measurement rather than an inference.
2. **The flat-read model transfers.** 9,423 of 9,439 account reads — **99.83%** — are served
   from the flat database. The geth study's round 16 established that account reads are a single
   flat-snapshot read rather than an 8-node trie walk, and that this is why the cost is flat in
   state size rather than logarithmic. Bonsai behaves the same way. The objection that killed
   rounds 1/3/5/12 of the geth study (probes driving `eth_getProof` down the *trie* path, which
   the EVM never uses) would be the same mistake here, and is now pre-empted.

The high cold-miss ratio (62,547 misses to 7,303 hits) is the intended condition — the harness
drops caches between steps.

**Operational note for Phase 5.** `rollback_strategy: container-recreate` rotates the container
per test, and the counters reset with it. Sampling must happen inside a single test window;
scraping across tests silently yields a reset counter, not a delta.

---

## Round 11 — the jochemnet genesis, resolved rather than guessed

This was flagged as an open item in the plan: the geth jochemnet arm needed **no** genesis file,
because geth reads chain config from the datadir. Besu declares `GenesisFlag() == "--genesis-file="`,
so the arm needs one from somewhere.

**Eliminated first, by inspection:**
- Neither cached bundle ships a genesis: `find` over both `eest-url` trees returns nothing for
  `*genesis*` or `*chainspec*`.
- So benchmarkoor's fallback chain — `instance.Genesis` → `cfg.GenesisURLs[client]` →
  `GenesisProvider.GetGenesisPath(client)` — terminates empty, and Besu would boot against
  mainnet defaults and reject the datadir.
- Besu exposes no CLI fork-override flag (only `--genesis-file`, `--network`,
  `--genesis-state-hash-cache-enabled`), so the override cannot be passed as an argument.

**The answer comes from the fixtures themselves.** The jochemnet fixture config declares:

```
config = {'network': 'Amsterdam', 'chainid': '0x01'}
```

**Chain ID 1** — jochemnet is a mainnet shadowfork, so its genesis *is* mainnet's. The canonical
Besu mainnet genesis (`hyperledger/besu:config/src/main/resources/mainnet.json`, 868,938 B,
chainId 1, 8,893 alloc entries, forks through `osakaTime`/`bpo2Time`) is therefore the correct
file, and it is geth-format, which is what `ApplyForkOverrides` requires:

```go
for fork, ts := range overrides { cfg[fork+"Time"] = ts; inheritBlobSchedule(cfg, fork) }
```

So `genesis_fork_override: { amsterdam: 1769856769 }` becomes `amsterdamTime: 1769856769` —
the exact equivalent of the geth arm's `--override.amsterdam=1769856769`, same timestamp.

**Configs written:** `besu-jochemnet.yaml` (untreated), `besu-jochemnet-treated.yaml`
(identical but for `results_dir`; the treatment arrives via `BENCHMARKOOR_POST_PRERUN_CMD`), and
a `-smoke.yaml` carrying the same one-category filter that caught the BAL mismatch on the
state-actor arm.

**To verify at pilot time, not assumed:** that Besu computes the mainnet genesis hash from this
alloc and accepts the jochemnet datadir. `--genesis-state-hash-cache-enabled=true` is already in
Besu's benchmarkoor defaults, which should let it trust the stored hash rather than recompute.

---

## Round 12 — state-actor arm complete

```
Test execution completed  duration=22h3m31s  passed=1461  failed=0  total=1461
```

**Zero validation failures across the whole suite** — no `INVALID`, no `SYNCING`, nothing
retried. The payload-reuse decision holds at full scale: 1,461 geth-filled payloads executed on
Besu without a single rejection, once the client matched the devnet (round 8).

Results archived immediately to `/data/archive/besu-sa/results-besu-state-actor.tar.gz`
(934 MB) before the volumes were touched — the geth study's run-1 archive is the only reason
that study is still auditable, and the changeover destroys this arm's volumes.

**Data sanity, checked before committing another 44 h:**

| | |
|---|---|
| tests carrying metrics | 1461 / 1461 |
| MGas/s min / p25 / **median** / p75 / max | 7.63 / 13.88 / **16.51** / 26.34 / 630.65 |
| gas executed | 2.022 × 10¹¹ |
| disk read | 11,674 GB |

The spread is the expected shape — compute-bound categories at the top, state-bound at the
bottom — and every test produced resource counters, so `disk_read_bytes` is available per test.

**A methodological simplification this enables.** The geth study needed a separate `blockrun`
probe for the residual because its 16 h suite numbers were confounded by media (rounds 13/17/18,
NVMe vs HDD). Here both arms run on the same md2 NVMe with the harness's own flags, and
benchmarkoor already records `disk_read_bytes`, `cpu_usec` and IOPS per test. The bytes-per-read
comparison should therefore come straight from the suite data, with the standalone replay kept
only as a confirmation. Provisional until the jochemnet arm lands and account counts can be
compared.

**Timing note for Phase 5.** The state-actor store survives at `/data/sa-besu-archive/v1`
(HDD). The matched-media replay needs both stores on NVMe at once — 533 G + ~1.1 T = ~1.63 T
against 3.5 T, which fits comfortably once the schelk pairs are gone. That measurement is
scheduled after the jochemnet suites, not squeezed alongside them.

**Now running:** the changeover — teardown freed NVMe to 3.2 T, and the jochemnet pair is being
created.

---

## Round 13 — the jochemnet store is nothing like the generated one, and the census caught it

Changeover complete (`rc=0`): pair built, extracted, censused, promoted —
**1,094.61 GB promoted in 25m23s at 735.76 MB/s**. NVMe 706 G free.

**Pristine census, taken before any Besu process opened the store:**

| | jochemnet (as shipped) | state-actor (generated) |
|---|---|---|
| SST files | 6,695 | 8,450 |
| SST bytes | 382,863,226,174 | 572,008,650,893 |
| **blob files** | **26,018** | 1 |
| **blob bytes** | **760,163,958,951** | 322 |
| **WAL files** | **21** | 1 |
| **WAL bytes** | **1,258,464,804** | 156 |
| caches/ | 246 files, 5.9 GB | absent |

Three findings, in ascending order of importance.

### 1. My round-9 note was wrong, and would have corrupted the F3 arithmetic

Round 9 recorded "BlobDB remains irrelevant here" on the evidence of the state-actor store
(1 blob file, 322 bytes). On the jochemnet store, **two-thirds of the data lives in blob files**
— 760 GB of blobs against 383 GB of SSTs. `SstGeom` measures SST geometry only, so applying it
to jochemnet would have silently described a third of the store and produced a
bytes-per-record figure that looked authoritative and was meaningless.

Retracted. The Phase 5 arithmetic must account for blob storage on the jochemnet side, or
compare only like-for-like keyspaces.

### 2. A configuration confound that must be settled before any ratio is quoted

The two stores are not merely different data — they appear to be **differently configured
RocksDB instances**. The snapshot was written by a real Besu node with its own options;
state-actor wrote with its own. Key-value separation being on for one and effectively off for
the other is exactly the class of confound the geth study spent rounds 4, 12 and 14 eliminating
(LSM shape, cache size, byte-identical client config).

Until this is measured, **no cross-arm bytes-per-read ratio means anything**. The comparison to
make is `min_blob_size` and the rest of the two OPTIONS files, side by side. That is now a
blocking item for Phase 5, not an optional check.

### 3. The WAL — a 1.26 GB recency artifact, shipped inside the snapshot

**21 WAL files totalling 1,258,464,804 bytes.** This is the structural analogue of the geth
study's root cause, and it is **3.3× larger** than the 380.15 MiB pathdb journal that made
recently-touched accounts 23× faster there.

Besu logs `Processing WAL...` on open (round 2), so this is state that never reached an SST and
which gets replayed into memtables — served from RAM — on first boot. That is precisely the
mechanism the geth article describes, in a different engine.

This is now the leading candidate for **P2**, and the census exists only because the tooling
was ordered to take the file inventory *before* any `besu storage` subcommand could open the
store and replay it away. Had the inventory run in the obvious order, the evidence would have
been destroyed by the act of measuring.

**Not yet known, and deliberately not guessed:** trie-log count (requires opening the store),
and what the WAL looks like *after* the pre-runs and `promote` — which is the condition the
benchmark actually measures, and the exact place the geth study found its 380 MiB.

---

## Round 14 — jochemnet pilot: the genesis reasoning holds, after two Besu-specific repairs

The round-11 chain worked on the first attempt where it mattered:

```
Loading genesis file  source=/root/bench/besu-mainnet-genesis.json
Applied genesis fork-time overrides  forks=map[amsterdam:1769856769]
```

Two further failures, both in the genesis file rather than the reasoning, each fixed minimally:

1. **`Invalid enode URL syntax 'enr:-Iu4Q...'`** — Besu's `mainnet.json` carries
   `config.discovery` with 21 **ENR-format** bootnodes plus DNS, and Besu's enode parser
   rejects ENR. The harness runs `--p2p-enabled=false --discovery-enabled=false --max-peers=0`,
   so the whole section is dead weight that is nonetheless parsed. Removed `config.discovery`.
2. **`Unknown consensus mechanism defined`** — the `main`-branch `mainnet.json` no longer
   carries an `ethash` block, but this Besu (26.8-develop) still requires an explicit consensus
   marker to resolve the pre-merge protocol schedule. Added `"ethash": {}`;
   `terminalTotalDifficulty` was already present, so nothing about the merge changes.

**Result: `failed=0 passed=2 total=2`** in 1m19s.

That is the confirmation of round 11's reasoning, not merely a green run: Besu validates the
stored genesis against the supplied file, so a wrong genesis fails with *"Supplied genesis block
does not match chain data stored"*. It booted — therefore jochemnet's genesis really is
mainnet's, and chain ID 0x01 in the fixtures was telling the truth.

**Untreated jochemnet suite launched:**

```
Discovered EEST fixtures  count=1463
Loaded pre-run bundle steps  files=1
Pre-run bundle over the size limit  bytes=10,062,313,486
```

1,463 against the state-actor arm's 1,461 — the same two-test difference the geth study saw
between these bundles. The pre-run is a **10.06 GB** bundle; in the geth study it was the
pre-run that deployed the accounts whose trie changes stayed resident in the 380 MiB journal.

**Scheduled, not improvised:** after this suite completes, `schelk restore` reproduces the
*promoted post-pre-run* image, and the file census runs against it before the treated run
rebuilds it. That image is the exact condition the benchmark measures, and it is where the geth
study found its root cause. Censusing it mid-run is not an option — `besu storage` takes the
RocksDB LOCK and would break the suite.

---

## Round 15 — the blob confound dissolves, and it was never a configuration difference

Round 13 raised a blocking objection: jochemnet holds **760 GB in 26,018 blob files** while the
generated store holds **322 bytes in one**, so the two arms might be differently-configured
RocksDB instances, which would void every cross-arm byte ratio. Settled from the OPTIONS file
rather than argued (`tools/besu-study/cfopts.py`):

| cf | enable_blob_files | min_blob_size | compression | block_size |
|---|---|---|---|---|
| `01` | **true** | 100 | kLZ4 | 32768 |
| `5c6e` | **true** | 100 | kLZ4 | 32768 |
| `06` ACCOUNT_INFO_STATE | **false** | 0 | kLZ4 | 32768 |
| `07` CODE_STORAGE | **false** | 0 | kLZ4 | 32768 |
| `08` ACCOUNT_STORAGE_STORAGE | **false** | 0 | kLZ4 | 32768 |
| `09` TRIE_BRANCH_STORAGE | **false** | 0 | kLZ4 | 32768 |
| all other CFs | false | 0 | kLZ4 | 32768 |

**The four state column families are blob-free on both stores, with byte-identical settings.**
Key–value separation is enabled only on `01` and `5c6e`.

`01` is the blockchain segment — blocks, receipts, headers. Independent support: in the
generated store `01` holds **5 entries** (round 9), which is what a genesis-only synthetic store
should contain, and its blob total is 322 bytes.

**So the 760 GB of blobs is chain history, not state.** It is the exact analogue of the geth
study's jochemnet store carrying ~700 GiB of frozen chain in the ancient store against a
state-actor store that has no history at all — there recorded as 1.20 TiB / 6.12 B items versus
674.25 GiB / 6.40 B items. Same asymmetry, different mechanism name.

**Three consequences.**

1. **Round 13's blocking item is cleared.** Identical per-CF settings, so no configuration
   confound. Both stores are also opened by Besu with its own programmatically-constructed
   options regardless of what the OPTIONS file records — which is why the librocksdb 10.10
   file never broke Besu in the first place (round 1).
2. **The like-for-like comparison is CFs 06–09**, and any whole-store byte ratio is meaningless
   because one store carries mainnet history and the other carries none. This is the Besu
   restatement of the geth study's decision to compare account-snapshot keyspaces rather than
   `du`.
3. **Compression is LZ4, not Snappy.** The geth residual ran through Snappy ratios (0.849 vs
   0.991). Besu's state CFs use `kLZ4Compression` at `block_size=32768`. Both terms of the F3
   arithmetic — algorithm and block size — differ from geth, which is precisely what makes the
   P3/P4 test informative rather than a re-run.

**Correction to round 9.** It described `blob_files` as irrelevant on the evidence of the SA
store; round 13 called that wrong on the evidence of jochemnet's 760 GB. Both were half right:
blobs are irrelevant *to the state keyspaces on either store*, and dominant in *chain history*,
which only one store has. The operative rule for Phase 5 is to measure CFs 06–09 and ignore
whole-store totals.

---

## Round 16 — the cross-arm extractor, and two parsing traps

`tools/besu-study/extract_arms.py` pulls per-test metrics from each arm's results into one
comparable table. Two false starts, both worth recording because either would have produced a
plausible-looking wrong answer rather than an error.

**Trap 1 — result directory names are lossy.** They are truncated and hash-suffixed:

```
...-account_mode_AccountMode.EXISTING_CONTRACT_DIFF_MAX-overhead_base-10a14f08e594b0ba
```

The name stops mid-field and the `gas-value_160M` label is simply absent. Parsing the path
yields rows with no category — and, because the first version also overwrote the parsed `gas`
label with the measured `gas_used_total`, it produced **1,341 "categories"** from 1,461 tests:
one per test, each looking like a legitimate grouping. A silent wrong answer, not a crash.

**Trap 2 — the metrics are already in `result.json`.** `tests[<full pytest id>]["steps"]["test"]
["aggregated"]` carries `time_total`, `gas_used_total`, `gas_used_time_total` and
`resource_totals` directly. So the correct implementation reads one file per arm and walks no
directories at all. The `dir` field is empty for these entries, which is what made the
path-based approach look necessary in the first place.

**Validated against the completed state-actor arm** — 1,461 rows, **0 failed**, 1,100 in the
account-access family and 361 in other families (sload/storage/transaction-type tests, which
legitimately lack `opcode`/`account_mode`):

| dimension | values |
|---|---|
| gas sweep | 100, 120, … 300 M (11 points) |
| account modes | EXISTING_CONTRACT_{DIFF_MAX, JUMPDEST, MINIMAL, SAME_MAX}, EXISTING_EOA, NON_EXISTING_ACCOUNT |
| opcodes | BALANCE, CALL, CALLCODE, DELEGATECALL, EXTCODECOPY, EXTCODEHASH, EXTCODESIZE, STATICCALL |
| opcode × mode | 48 |

This is the geth study's experimental structure exactly — same sweep, same six modes, same
eight opcodes — which is the precondition for the two studies being comparable at all.

Slowest categories on the generated store, for orientation only (the comparison that matters
needs the jochemnet arm): `CALL/EXISTING_CONTRACT_JUMPDEST` 11.45 MGas/s,
`CALL/EXISTING_CONTRACT_DIFF_MAX` 11.55, `BALANCE/EXISTING_CONTRACT_JUMPDEST` 13.23.

`gas_used_time_total` is used rather than `time_total` so harness overhead is excluded, and the
`setup` step is kept separate rather than summed into the measurement.

---

## Round 17 — untreated arm complete, and P4 reproduces on a different storage engine

```
Test execution completed  duration=23h1m39s  passed=1463  failed=0  total=1463
```

Archived to `/data/archive/besu-joc/results-besu-jochemnet-untreated.tar.gz` (932 MB).

### The promoted post-pre-run image

`schelk restore` reproduces exactly what the benchmark measured. File census, taken before any
Besu process could open it:

| | as shipped | post-pre-run | Δ |
|---|---|---|---|
| SST bytes | 382,863,226,174 | 382,737,542,760 | −126 MB |
| blob bytes | 760,163,958,951 | 760,283,875,964 | +120 MB |
| **WAL bytes** | **1,258,464,804** | **1,329,617,075** | **+71 MB** |

**The promoted image carries a 1.24 GiB write-ahead log** — state that never reached an SST,
replayed into memtables on every test's boot. The geth study's root cause was a 380.15 MiB
pathdb journal in exactly this position. This is 3.3× larger.

### P4 — the residual mechanism reproduces, and closely

`SstGeom` on both stores, `ACCOUNT_INFO_STATE` (cf 06) — the flat account keyspace, the exact
analogue of the geth account snapshot the residual arithmetic ran on:

| | jochemnet | state-actor | ratio |
|---|---|---|---|
| entries | 365,626,139 | 430,696,738 | 1.178 |
| **phys ÷ log** | **0.438** | **0.513** | **1.171** |
| **compressed bytes/block** | **14,255.7** | **16,696.6** | **1.171** |
| SSTs | 305 | 228 | |

Against the published geth figures:

| | geth | besu |
|---|---|---|
| compression ratio, jochemnet vs generated | 0.849 → 0.991 = **1.167** | 0.438 → 0.513 = **1.171** |
| block size ratio | 3,467 → 4,043 B = **1.166** | 14,255.7 → 16,696.6 B = **1.171** |

**Different engine, different compression algorithm (LZ4 vs Snappy), 8× different block size
(32 KB vs 4 KB) — and generated state is less compressible by the same factor to three
significant figures.**

This is the strongest available evidence for F3 as stated in the geth article: the residual is a
property of *the data*, not of the storage engine. It was the falsifiable prediction registered
as P4 before any Besu measurement existed, and it holds.

Two cautions kept attached to the number: these are store-geometry ratios, not yet timings — the
timing comparison needs both arms' suite data analysed together; and `rec_B` (113.2 vs 119.7)
includes RocksDB internal key bytes, so it is *not* comparable with geth's 49.6/58.3 B/entry,
as recorded in round 9.

### Two self-inflicted findings

**I destroyed the WAL evidence on the scratch with my own diagnostics.** Running
`besu storage trie-log count` and `storage rocksdb usage` on the restored image opened RocksDB —
both commands then *failed*, one on `Cannot store generated private key` and one on
`You must provide the default column family` — but Besu had already logged `Processing WAL...`
and replayed it. A re-census afterwards showed `wal=1 (179 B)` where minutes earlier there had
been 20 files and 1.33 GB. Round 4 documented this exact hazard; I walked into it anyway. No
data lost — the census was taken first and the virgin volume is untouched — but the ordering
rule now has a second, harder statement: **run no Besu subcommand against a store whose WAL is
evidence, not even a read-only-looking one.**

`SstGeom` worked on the same store where both Besu subcommands failed, because it opens
read-only through the rocksdbjni jar directly.

**`kForce` dropped, with the measurement that justifies it.** On the 1.1 TB store, forcing
bottommost compaction ran **>2 h having moved only 6,688 → 5,864 SSTs** (382.5 → 367.4 GB) with
hours still to go — unaffordable inside a pre-run hook. The default still performs a full-range
compaction collapsing L0–L5 into the bottom level, which is the property the study tests. What
kForce adds is rewriting an already-compacted L6 to purge tombstones, irrelevant to read cost.
Recorded rather than silently changed.

### Treatment, and why it is now a true analogue

`Compact.java` now **flushes all column families before compacting**
(`db.flush(FlushOptions().setWaitForFlush(true), handles)`). Without it the 1.24 GiB WAL
residency would survive the treatment untouched, and the run would measure only the on-disk
shape — precisely the half-fix the geth study measured when it drained without compacting and
compacted without draining.

**Treated suite launched** with
`BENCHMARKOOR_POST_PRERUN_CMD='/home/CPerezz/rockscompact/rockscompact $DATADIR'`, 1,463
fixtures.

---

## Round 18 — untreated vs generated, with the contamination stated up front

`compare_arms.py` pairs the two completed arms on the **full identity** of each workload
(opcode, account_mode, gas, value_sent, overhead_baseline), so a ratio can never be formed
across different work.

**Workload control — exact:**

```
common workloads: 1100
gas: jochemnet 1.304e+11   state_actor 1.304e+11   ratio 1.000000
```

Identical gas to six decimal places across 1,100 paired measurements. Whatever the arms differ
by, it is not the work requested of them.

**Result:**

| | |
|---|---|
| throughput ratio (state-actor ÷ jochemnet), 48 categories | median **0.333**, min 0.110, max 0.518 |
| disk bytes read per gas | jochemnet 6.26, state-actor 60.96 — **9.74×** |

Extremes, both ends:

| opcode | account_mode | jochemnet | state-actor | ratio |
|---|---|---|---|---|
| EXTCODESIZE | NON_EXISTING_ACCOUNT | 150.70 | 16.59 | 0.110 |
| BALANCE | NON_EXISTING_ACCOUNT | 144.65 | 16.18 | 0.112 |
| CALL | EXISTING_CONTRACT_MINIMAL | 33.24 | 15.54 | 0.468 |
| CALL | NON_EXISTING_ACCOUNT | 163.92 | 84.95 | 0.518 |

### What this is not

**This is not the study's headline, and it must not be quoted as one.** The untreated jochemnet
arm is contaminated *by construction* — it is the arm carrying the **1.24 GiB WAL** and 5.9 GB of
`caches/` measured in round 17, i.e. exactly the recency artifact the geth study identified as
its root cause. A fast untreated arm is the expected symptom, not a finding.

The geth study's equivalent comparison ran 7.71× on its worst class before treatment and
collapsed to ~1.09× after. The Besu number to compare against that is the **treated** one, which
is running now.

### What it does establish

- **P5 holds.** Identical gas on identical payloads across both arms, so the arms are doing the
  same requested work and per-test ratios are meaningful.
- **P2 is strongly supported.** A 9.74× gap in bytes read per unit of gas is far too large to be
  explained by the stores' 18% difference in account count (365.6 M vs 430.7 M) or by the
  geometry of round 17. Something is serving jochemnet's reads without touching disk, and the
  WAL plus caches is the candidate already measured in place.
- The gap is **broad, not confined to one class** — every one of the 48 categories favours
  jochemnet, ranging 0.110 to 0.518. In the geth study the untreated anomaly was concentrated in
  DIFF_MAX; here it is everywhere, which is consistent with a WAL/memtable residency that is
  indifferent to account class rather than a diff-layer that tracks recently-written accounts.

**Held open until the treated arm lands:** how much of the 3× median survives flush + compaction.
That difference is the actual result, and it is the only number that answers P1 and P2.

---

## Round 19 — the treatment hook never fired, and why that was correct behaviour

The first treated run was launched with
`BENCHMARKOOR_POST_PRERUN_CMD='/home/CPerezz/rockscompact/rockscompact $DATADIR'` and produced
**no hook output at all**. Tests started anyway, which would have yielded a "treated" arm
identical to the untreated one — 23 h of data answering nothing.

Caught at 55/1463 by grepping the log for the tool's own output rather than assuming the hook
had run. The cause is in the log:

```
Datadir head matches the pre-run bundle  block=24410463  pre_runs_applied=true
Pre-run bundle already applied to this datadir; skipping the replay
```

The virgin volume already carried the post-pre-run state, because the **untreated** run promoted
it there (`promote_post_pre_runs: true`). With no pre-run phase to run, there was no
*post*-pre-run hook to fire. benchmarkoor behaved correctly; the experiment design assumed a
fresh snapshot per arm, as the geth study had.

The binary does support the hook — `BENCHMARKOOR_POST_PRERUN_CMD` appears in its strings, and
`ShouldPromotePostPreRuns` is in the symbol table. Nothing was broken except my sequencing.

**Fix, and why it is equivalent rather than a shortcut.** Re-extracting the snapshot to get a
virgin pre-pre-run image costs ~3 h. Instead the treatment was applied directly to the promoted
image:

1. `schelk restore` → scratch = virgin = post-pre-run, untreated
2. run the treatment on the mounted store
3. `schelk promote` → virgin = post-pre-run, **treated**
4. run the suite (pre-runs correctly skipped again)

That is exactly the geth study's compacted arm: pre-runs applied, then drain + compact, then
promote. The two Besu arms now differ **only** by the treatment, which is the cleaner
comparison — same pre-run execution, not merely an equivalent one.

Restored state verified byte-for-byte against round 17's census before treating:
`sst=6699 (382,737,542,760 B) wal=20 (1,329,617,075 B) blob=26083`.

### The treatment, measured

```
loaded OPTIONS: 17 column families
  flush (all cfs)     0.0s
  cf=01             414.4s      cf=06   313.6s
  cf=08            1477.3s      cf=07    90.4s
  cf=09            3103.8s      cf=0a    34.7s
total 5437.0s                   real 90m37s
```

| | before | after | Δ |
|---|---|---|---|
| SST files | 6,699 | 5,454 | −1,245 (−18.6%) |
| SST bytes | 382,737,542,760 | 360,320,146,324 | −22.4 GB (−5.9%) |
| **WAL bytes** | **1,329,617,075** | **23** | **−1.24 GiB** |
| blob files | 26,083 | 26,077 | −6 |

Promote: 5,797,073 blocks / 353.83 GB in 8m57s.

**An unexpected mechanical finding: `flush (all cfs)` returned in 0.0s.** The memtables were
already empty by the time the explicit flush ran, because RocksDB's *open* path recovers the WAL
and flushes the recovered data itself. So on Besu, **opening the store is the drain** — every
Besu boot already does what geth needed a purpose-built `drainjournal` tool to do.

That reframes P2 and is worth stating carefully before the treated numbers arrive. If the
untreated arm's advantage were pure WAL residency, it should not survive the first boot of each
test, since every test boots Besu fresh. The advantage measured in round 18 is therefore more
likely **LSM level placement** — the pre-run's recently-written accounts sit in a handful of
young, small SSTs, cheap to locate, whereas the generated store's accounts are spread across
8,450 files — than memtable residency as such. Compaction, not flushing, is the operative half
of this treatment, and the treated arm is the measurement that will decide it.

**Treated suite relaunched** against the treated golden image, 1,463 fixtures.

---

## Round 20 — all three arms complete; the pre-registered verdicts

```
state-actor  1461/1461 passed  22h03m31s
untreated    1463/1463 passed  23h01m39s
treated      1463/1463 passed  21h38m30s
```

Zero validation failures in any arm. All results archived. **1,100 workloads common to all
three**, with gas identical across arms to six significant figures
(`1.30409e+11` each) — the arms did the same work, measured.

### Headline

Per-category medians of per-workload ratios, split by account class because mixing them
produces a median that describes neither (the geth study made the same split on a different
class):

| comparison | family | n | min | **median** | max |
|---|---|---|---|---|---|
| **state_actor / treated** | EXISTING_* | 40 | 0.901 | **0.949** | 0.979 |
| | NON_EXISTING | 8 | 0.101 | 0.110 | 0.453 |
| **treated / untreated** | EXISTING_* | 40 | 0.167 | **0.581** | 0.734 |
| | NON_EXISTING | 8 | 1.014 | 1.076 | 1.090 |

Bytes read per unit gas: `state_actor/treated` **1.4498**, `treated/untreated` **6.7208**,
`state_actor/untreated` 9.7439.

### Verdicts on the pre-registration

**P1 — REFUTED, decisively.** Predicted the compaction spread would be *smaller* on Besu than
geth's 1.031–1.117 (median 1.091), on the reasoning that RocksDB auto-compacts aggressively.
Measured spread is **1.72×** (median 0.581), an order of magnitude larger than geth's 1.09×.
Treatment state matters far *more* on Besu, not less.

**P2 — CONFIRMED.** A large recency artifact exists in the promoted image. The untreated arm
runs 1.72× faster on every state-reading class while moving **6.7× fewer bytes**, and the
advantage disappears on treatment. Registered before any Besu measurement existed.

**P3 — CONFIRMED.** The residual survives on a different storage engine: after treatment,
state-actor is slower than the mainnet snapshot on **40 of 40** EXISTING categories,
median **5.4%** (1/0.949), range 2.1%–11.0%.

Against geth's published 1.031–1.117, median 1.091 — **9.1%** — across 13 categories. Same sign,
same order of magnitude, different engine, different compression algorithm, 8× different block
size.

**P4 — the mechanism reproduces, the quantitative prediction does not.** P4 predicted a
bytes-per-read ratio in **1.10–1.15**; measured **1.4498** bytes per gas. Recorded as a miss.

What *did* land within a fraction of a percent is the store-geometry chain of round 17:
compression ratio 0.438→0.513 = **1.171** and block size 14,256→16,697 B = **1.171**, against
geth's **1.167** and **1.166**. So the *mechanism* — generated state is less compressible, so a
block holds fewer records and a read moves more bytes — transfers exactly; the step from
geometry to observed bytes-per-gas does not, and the prediction was made on the latter.

**P5 — CONFIRMED on work, not yet on reads.** Gas is identical across arms to six significant
figures on all 1,100 shared workloads. Account-read *counts* were not captured: benchmarkoor
does not scrape Besu's metrics endpoint, and round 10 verified the counters exist and advance
but reset per container. The claim rests on gas identity, which is strong but not the same
statement.

### The NON_EXISTING class does not measure the same thing on both stores

Eight categories sit far outside the band, worst at `value_sent=0`:

| account_mode | value_sent | treated | state-actor | ratio |
|---|---|---|---|---|
| NON_EXISTING | 0 | 145.66 | 16.28 | 0.113 |
| NON_EXISTING | 1 | 230.73 | 103.01 | 0.484 |
| every EXISTING_* | 0 and 1 | — | — | 0.904–0.982 |

**The treatment leaves this class alone** — `treated/untreated` is 1.014–1.090 for NON_EXISTING
while every other class moves by 1.4–6×. So its cost is insensitive to LSM shape, which is the
signature of a lookup that is rejected by a bloom filter without reading a block.

The most likely reading is therefore that these addresses are genuinely absent from the mainnet
snapshot and **not absent from the generated store** — state-actor fills 430.7 M synthetic
accounts, and a "non-existing" probe address that the fill happens to occupy becomes a real
read. If so the class is not comparing like with like, and it belongs in the article as a
caveat about generated state rather than as a performance finding.

**Stated as a hypothesis, not a conclusion** — confirming it requires resolving the fixtures'
probe addresses and querying both stores directly, which has not been done.

### What this says about the geth article's claim

The geth study concluded that a ~10% floor between a generated state and a mainnet snapshot
"is not a defect in either one — it is what the two datasets are", and argued the mechanism is
record incompressibility rather than tree shape or engine behaviour.

On Besu that claim survives its strongest available test. A different storage engine, a
different compression algorithm and a 4× larger block reproduce the compression ratio to three
significant figures and leave a residual of the same sign and order. The headline number moves
(5.4% vs 9.1%), so the *magnitude* is engine-dependent; the *existence and cause* are not.

---

## Round 21 — divergence from plain jochemnet, bucketed

Reference: **jochemnet as shipped** (untreated). Measured against it: the same database after
flush+compaction, and the generated companion. Buckets follow the geth article's vocabulary,
since quoting one median over a bimodal population describes neither half.

| bucket | what it is | tests |
|---|---|---|
| `absent` | NON_EXISTING_ACCOUNT — absence lookups | 110 |
| `leaf-only` | BALANCE, or an EXISTING_EOA target — reads the account leaf, never code | 198 |
| `code-reading` | EXTCODE*/CALL-family into a contract — additionally reads the code blob | 792 |

**Per-test, |Δ| > 10% from plain jochemnet:**

| bucket | tests | treated | state-actor |
|---|---|---|---|
| absent | 110 | **27** | 110 |
| leaf-only | 198 | 155 | 157 |
| code-reading | 792 | 400 | 404 |
| **total** | **1100** | **582** | **671** |

**Per-bucket medians and bytes:**

| bucket | n | treated/joc | sa/joc | **sa/treated** | bytes tr/joc | bytes sa/joc |
|---|---|---|---|---|---|---|
| absent | 110 | **1.060** | 0.124 | **0.117** | 0.53 | 26.54 |
| leaf-only | 198 | 0.190 | 0.182 | **0.952** | 7.08 | 8.55 |
| code-reading | 792 | 0.702 | 0.692 | **0.958** | 6.95 | 9.18 |

### Three things this makes visible that the single median hid

**1. Treated jochemnet and state-actor are the same database, to within 5%.** `sa/treated` is
0.952 and 0.958 in the two buckets that actually read state. The plain arm is the outlier, not
the generated store. Every category in those buckets diverges from plain jochemnet, and almost
none diverge from *treated* jochemnet.

**2. The artifact's size depends on what the test reads.** Treatment costs `leaf-only`
**5.3×** (0.190) but `code-reading` only **1.4×** (0.702). A leaf read is one small record that
the hot set can hold entirely; a code read additionally pulls a code blob that was never hot.
The artifact accelerates exactly the part of the workload that fits in it.

**3. `absent` is untouched by treatment — 1.060 — and is where the two databases really
differ** (0.117, and **26.5× the bytes**). A lookup whose cost is insensitive to LSM shape is
one that never reads a block. Round 20's hypothesis stands: these addresses are absent from the
mainnet snapshot and evidently *not* absent from a store filled with 430.7 M synthetic accounts.
Note the treated arm reads **half** the bytes of the plain arm here (0.53) — fewer SSTs after
compaction means fewer bloom probes.

### Gas dependence — monotonic in every bucket

| bucket | 100 M | 300 M |
|---|---|---|
| absent, treated/joc | 1.037 | 1.116 |
| absent, sa/joc | 0.152 | 0.114 |
| leaf-only, treated/joc | 0.236 | 0.146 |
| code-reading, treated/joc | 0.702 | 0.600 |

The gap widens with the gas budget in every bucket. That is the signature of a **fixed-size hot
working set**: a bigger budget means more lookups per block, so a larger fraction fall outside
whatever the plain arm was serving from memory. It also explains why only 582 of 1,100 tests
cross the 10% line while every category median sits near 0.35 — the low-gas end of each sweep
is much closer to parity.

---

## Round 22 — what actually differs between plain and treated jochemnet

The two arms are the **same database at the same block**, same payloads, same client image, same
volume, same device, same flags; gas identical across arms to six significant figures. Exactly
two things were done to one of them: flush all column families, then full-range compaction.

### What changed, measured

| | plain | treated |
|---|---|---|
| WAL | 20 files, 1,329,617,075 B | 1 file, **23 B** |
| SST files | 6,699 | 5,454 |
| SST bytes | 382,737,542,760 | 360,320,146,324 |
| blob files | 26,083 | 26,077 |

Per column family (`SstGeom`):

| cf | | entries | SSTs | data bytes |
|---|---|---|---|---|
| 06 ACCOUNT_INFO_STATE | plain | 365,626,139 | 305 | 18,127,106,956 |
| | treated | 354,792,873 | 269 | 17,441,333,066 |
| 08 ACCOUNT_STORAGE | plain | 1,874,093,849 | 1,461 | 84,388,693,763 |
| | treated | 1,822,629,119 | 1,255 | 81,594,326,888 |
| 09 TRIE_BRANCH | plain | 3,098,085,111 | 4,301 | 235,047,482,585 |
| | treated | 3,012,961,752 | 3,351 | 216,634,162,687 |

Record shape is unchanged — cf 06 `rec_B` 113.2 both sides, `phys/log` 0.438 → 0.434. The
treated store is **smaller, in fewer files, with fewer entries**.

### The entry count is the tell

Compaction removed **10,833,266 entries from cf 06**, 51.5 M from cf 08 and 85.1 M from cf 09.
Those are obsolete *older/duplicate versions* of keys, purged when the levels merged.

The 10.06 GB pre-run wrote the accounts the benchmark then reads. In the plain store those
writes exist as the **newest versions sitting in young, small, top-of-tree SSTs**; a lookup for
one of them is satisfied near the top of the LSM and never descends. Compaction merges them into
the single bottom level, so the identical lookup now reads a 32 KB block out of a 360 GB sorted
run with no locality to its neighbours.

That is measured as **6.72× more bytes read for identical gas**, and it is the geth article's
sentence restated in RocksDB terms — there, `geth db compact` "merged those leaves into the same
cold strata as everybody else," taking BALANCE/DIFF_MAX from 272 to 18.5 MGas/s.

Which is why the treatment makes the database *slower* while making it *smaller*: it is not an
optimisation, it is the removal of an accident.

### Which arm is right

The treated one, on two independent grounds:

- it is the state a normally-operating node converges to, rather than the state a
  pre-run-then-snapshot fixture happens to freeze;
- it is the only one comparable with the generated store — `sa/treated` is 0.952 and 0.958,
  while `sa/plain` is 0.182 and 0.692.

The plain arm's speed is a property of **how the fixture was built**, not of the database.

---

## Round 23 — closing the four gaps: design, registered before results

The study so far cannot support a root-cause section at the geth article's standard. That
article found a physical object, explained it from source, and **decomposed its fix**:
380 → 272 (drain) → 18.5 MGas/s (compact). This study's treatment did flush and compaction
**together**, so drain and placement were never separated.

Four gaps, and the experiments that close them. Registered now so the predictions are on record.

### A — WAL drained, levels untouched

Round 19 established that RocksDB's *open* path recovers and flushes the WAL, so the explicit
flush returned in 0.0 s. That has a consequence nobody has tested: in the plain arm **every test
boots Besu fresh**, so the WAL is already drained at the start of every measurement. WAL
residency as such therefore cannot be the advantage — what it leaves behind can, namely the
pre-run's writes materialised as young, small, top-of-tree SSTs.

`Compact.java` gains a `flush-only` mode. Stages 3→4→5 share one extraction and differ *only* by
treatment, giving plain → drained → drained+compacted.

**Prediction: drained ≈ plain, and compaction supplies nearly all of the effect.** If instead
drained ≈ compacted, the mechanism is memtable residency and round 22's placement account is
wrong.

### B — the absent class, without deriving a single address

Round 21 left 110 tests (0.117 ratio, 26.5× bytes) resting on a hypothesis: that the
NON_EXISTING probe addresses exist in the generated store. Deriving CREATE2 probe addresses from
the fixtures is fiddly and error-prone.

It is also unnecessary. Besu already counts
`besu_blockchain_get_account_missing_flat_database_total` — flat-DB lookups that found nothing.
Run the same NON_EXISTING workload on both stores:

- jochemnet `missing ≈ total` and state-actor `missing ≈ 0` ⇒ the addresses **are** occupied in
  the generated store, and the class is not comparing like with like;
- both `missing ≈ total` ⇒ the hypothesis is wrong and the 26.5× needs another explanation.

Either way it is an answer, from instrumentation already verified in round 10.

*(The geth article listed this check — "eth_getCode probe over sampled CREATE2 addresses in both
databases, converts the existence argument from inference to direct evidence" — as a next step
it never performed.)*

### C — noise floor

One run per arm, no same-database control; geth's was 1.003. Stage 3 replays the pre-runs on a
fresh extraction and re-runs the plain arm, so comparing it against the original untreated run
on the shared 129 tests measures **whole-pipeline reproducibility** — extraction, pre-run replay,
promote and suite — which is a stronger control than a bare repeat.

### D — account reads

P5 rests on gas identity: what was *requested*, not what was *read*. `scrape_besu.py` samples
each container's counters at 2 s; `container-recreate` gives one container per test and resets
the counters with it, so each container's final values are that test's totals, and containers
zip positionally against the suite's execution order.

This is what lets the Besu article state geth's cleanest sentence — "same reads, more bytes" —
rather than the weaker "same gas".

### Scope

129 tests per arm (3 opcodes × 6 account modes × 3 gas points, 21 cells, both read families plus
the absent class), chosen because the effects under test are 1.4–5.3× and do not need the full
sweep. Five stages, ~15 h, sequential because the arms cannot be co-resident on 3.5 TB of NVMe.

---

## Round 24 — gap B answered: my hypothesis was wrong, and the real cause is better

Rounds 20 and 21 left the `absent` class (110 tests, ratio 0.117, 26.5× bytes) resting on a
hypothesis: that the NON_EXISTING probe addresses are occupied in the generated store, so the
class was not comparing like with like.

**Refuted.** Besu's own counters, same workload on both stores:

| store | NON_EXISTING miss ÷ total reads |
|---|---|
| jochemnet treated | 0.955 |
| state-actor | **0.999** |

The addresses are absent from **both** — the generated store's more cleanly than the snapshot's.
The hypothesis is dead. Yet state-actor moves **69× more bytes** to establish the same absences.

### The real cause: the generated store has no bloom filters

`SstGeom` extended to report `TableProperties.getFilterSize()` and the filter policy:

| cf | jochemnet | state-actor |
|---|---|---|
| 01 BLOCKCHAIN | 557,047,846 B `bloomfilter` | **0** `(none)` |
| 06 ACCOUNT_INFO_STATE | 460,372,287 B `bloomfilter` | **0** `(none)` |
| 07 CODE_STORAGE | 2,809,501 B `bloomfilter` | **0** `(none)` |
| 08 ACCOUNT_STORAGE | 2,344,277,759 B `bloomfilter` | **0** `(none)` |
| 09 TRIE_BRANCH | 3,945,343,735 B `bloomfilter` | **0** `(none)` |

jochemnet carries **~7.3 GB of bloom filters**. state-actor has **none at all** — the generator
writes its SSTs without a filter policy.

Without a filter, a lookup that will find nothing cannot be rejected: it must read index and
data blocks from any file whose key range covers the probe. With one, it is rejected outright.

### Why this splits the study cleanly rather than spoiling it

Bytes read, state-actor ÷ treated jochemnet, by bucket:

| bucket | bytes ratio |
|---|---|
| absent | **50.135** |
| leaf-only | **1.207** |
| code-reading | **1.320** |

A missing bloom filter costs **50×** on absence proofs and **1.2–1.3×** on reads that find their
key — because a lookup that succeeds was going to read that block anyway. So:

- **The `absent` anomaly is a generator defect, not a property of generated state.** It is
  actionable: state-actor should set a filter policy, or every absence-class measurement taken
  on its output is ~50× pessimistic. This is a tooling bug worth reporting upstream.
- **The existing-account residual survives untouched.** leaf-only at **1.207×** bytes sits within
  3% of the **1.171×** predicted from block geometry alone (round 17), which leaves little room
  for a bloom contribution and is a strong independent confirmation of the compressibility
  chain. geth's published figure was 1.119× bytes for 9.1% time; Besu's is 1.207× for ~5.4%.

`code-reading` is higher at 1.320×, and cf 07 says why: jochemnet's code records are large and
compressible (7,227 B, phys/log **0.423**) while state-actor's are small and nearly
incompressible (398 B, phys/log **0.863**) — unique bytecode per generated contract, exactly the
mechanism the geth article named.

### Correction to the record

Round 20 wrote "the most likely reading is therefore that these addresses are absent from the
mainnet snapshot and evidently *not* absent from the generated store." That was wrong, and it
was labelled a hypothesis precisely so it could be killed. It has been. The replacement is
better: a measured, one-line configuration defect with a 50× consequence.

---

## Round 25 — a self-inflicted failure worth recording

Stages 3–5 failed on the first attempt. Not a subtle failure, but one that produced *plausible
looking* runs rather than an obvious error:

```
ERRO | Instance failed error=creating container: statfs
      /schelk/snapshots/besu/jochemnet/24402727: no such file or directory
```

**Cause.** The orchestrator extracted the 1.1 TB snapshot into the mounted **scratch** volume and
went straight to the suite. But benchmarkoor opens every run with `schelk restore`, which resets
scratch from **virgin** — and virgin was the empty filesystem `init-new` had created minutes
earlier. The entire extraction was discarded before the first test ran.

Extraction must be followed by `promote`, so the extracted state *becomes* the baseline. Stage 2
did promote (after copying the state-actor store) and worked; stage 3 did not and did not.

**Aggravating factor, also mine.** The orchestrator wrote a per-stage marker but never *read*
one. Stages 4 and 5 ran happily against an empty datadir — `before: sst=0 walB=0`,
`no rocksdb at ...`, a promote that copied 64 KB in 52 ms — and recorded rc=1 each. Three
stages of nothing, all reported as completed work.

**Fixed:** `schelk promote` after extraction, and a `gate` function that refuses to start a
stage unless the previous one recorded `rc=0`.

**Cost:** ~85 minutes of extraction, plus the empty runs. No data lost — stages 1 and 2 were
already complete and archived, and the tarball is immutable.

**The transferable lesson** is the same one round 17 taught about the WAL, in a different guise:
in a schelk-backed pipeline, *the scratch volume is not the baseline*. Anything written there is
provisional until promoted, and every benchmarkoor run begins by discarding it.

---

## Round 26 — a second silent failure, and an accidental control

Stage 4 was supposed to be the WAL-drained, levels-untouched arm. Its own census says otherwise:

```
before  sst=6699 sstB=382741424540 walB=1224815535
after   sst=5454 sstB=360320142993 walB=23        <- a full compaction
total 5426.3s                                      <- 90 minutes of it
```

**Cause.** `rockscompact` hardcoded its java arguments:

```bash
java -cp .:rocksdbjni-10.6.2.jar Compact /db/database    # $2 silently discarded
```

`Compact.java` had gained a `flush-only` mode in round 23, but the wrapper never forwarded it.
Stage 4 therefore ran the full treatment, and stage 5 — operating on an already-compacted
store — finished its compaction in **0.4 s** and promoted 3.69 MB.

So gap A is still open, for the third time. The failures share a shape worth naming: **each one
produced a run that looked successful.** Round 25's empty datadir, this round's wrong treatment.
Neither raised an error; both had to be caught by reading the numbers.

**Fixed:** the wrapper now `shift`s and forwards `"$@"`. And stage 6 asserts its own
precondition rather than trusting it — flush-only must drain the WAL *and* leave the SST count
within 200 of where it started, or the stage refuses to run the suite at all. A full compaction
moves it by ~1,245, so the guard cannot miss a repeat of this bug.

### The accident is useful

Stages 4 and 5 are now two independent 129-test runs of the **same compacted state**, on the
same lineage, same device, same flags. That is a direct repeat — a better noise floor than the
cross-lineage control planned for gap C, because nothing differs between them at all.

### What stands

| arm | state | status |
|---|---|---|
| s1-treated | compacted (original lineage) | valid |
| s2-sa | state-actor | valid |
| s3-plain | plain, post-pre-run | valid |
| s4 "drained" | **compacted** (mislabelled) | valid as a compacted arm |
| s5-compacted | compacted, repeat of s4 | noise floor |
| s6-drained | flush-only — pending | gap A |

Also recorded: stage 3's post-pre-run census printed `sst=0` because `schelk promote` unmounts —
the round-17 trap again, cosmetic here. The real post-pre-run figures are stage 4's "before"
line, and the WAL came in at **1,224,815,535 B** against the first lineage's 1,329,617,075 B.
That ~8% spread across two independent pre-run replays is itself a datum: the shipped-WAL size
is not a constant.

---

## Round 27 — gap C answered, and a key bug caught by disagreement

The filtered arms first appeared to contradict the full suites: code-reading `compacted/plain`
came out at **1.009** where the 1,463-test suites gave **0.702**. Two candidate explanations —
the filtered method is invalid, or the comparison is wrong. Cross-checking identical test ids
settled it:

```
full MGas/s   filt MGas/s        test
      42.95         48.57        BALANCE / EXISTING_CONTRACT_...
     107.13        119.13
      18.02         18.03
gas: full=1.59525e+10 filtered=1.59525e+10  ratio=1.000000
```

Same tests, same gas exactly, throughput within 11–13%. So the runs were fine and the
comparison was wrong.

**The bug: my key omitted `overhead_baseline`.** Every workload exists twice —
`overhead_baseline_True` is the *control*, which performs no account-state work (the geth study
measured its controls at 33.06/33.80/32.94 ms, 2.6% spread). Keying on
(opcode, mode, gas, value_sent) silently collapsed each control/measurement pair to whichever
was inserted last, so half the comparisons were controls, which naturally sit at ~1.0.

With `baseline` in the key the count goes 72 → **120** and the disagreement vanishes:

| bucket | n | full | filtered |
|---|---|---|---|
| absent | 12 | 1.088 | 1.025 |
| leaf-only | 36 | **0.229** | **0.228** |
| code-reading | 72 | **0.670** | **0.679** |

The main analysis was never affected — `extract_arms.py` and `compare_arms.py` have always
carried `baseline` in the key, so rounds 18, 20 and 21 stand. Only the new filtered scripts had
the defect.

### Gap C — the noise floor, and it is very good

The two sides of that table are not a repeat. They are **two independent pipelines**: a
1,463-test suite on the first lineage, and a 129-test suite on a second lineage built from a
fresh 1.1 TB extraction and an independent pre-run replay, hours apart.

| bucket | agreement |
|---|---|
| leaf-only | **0.4%** |
| code-reading | **1.3%** |
| absent | 6% |

Whole-pipeline reproducibility of ~1% on the state-reading buckets. The geth study's comparable
control was a same-database 1.003. So the **5.4% residual is comfortably above noise**, and the
1.4–5.3× treatment effects are not remotely in question.

Corroborating: the extraction itself is deterministic — round 25's re-extract reproduced
`sst=6695 sstB=382863226174 walB=1258464804 blob=26018`, byte-identical to round 13.

---

## Round 28 — the purest noise floor: same state, two runs

Round 26's wrapper bug left stages 4 and 5 measuring the **identical compacted state** — same
lineage, same virgin, same device, same flags, 129 tests each, nothing differing. That accident
is the cleanest control the study has.

| bucket | n | throughput run2 ÷ run1 | bytes run2 ÷ run1 |
|---|---|---|---|
| absent | 12 | 0.991 | 1.000 |
| leaf-only | 36 | **1.002** | 0.992 |
| code-reading | 72 | **0.996** | 1.000 |

Gas identical across both (`4.96337e+09`).

**Run-to-run noise is 0.4–0.9% on throughput and ≤0.8% on bytes.** geth's comparable
same-database control was 1.003; this matches it.

Two consequences for how the results may be stated:

- The **5.4% residual** (state-actor vs treated jochemnet, 40/40 categories) is roughly 6–13×
  the noise floor. It is a measurement, not a wobble.
- The **1.4–5.3× treatment effects** are three orders of magnitude above it.

Combined with round 27's cross-pipeline agreement (0.4% leaf-only, 1.3% code-reading, across two
separate 1.1 TB extractions and pre-run replays), the study now has two independent noise
estimates at different scopes — run-level and pipeline-level — and they agree that anything
above ~1.5% is real.

`compare_filtered.py` was patched for the `overhead_baseline` key defect found in round 27
before these numbers were taken; the workload counts (36 and 72 rather than 24 and 36) confirm
the fix is active.

---

## Round 29 — gap A answered: the WAL is irrelevant, placement is everything

All six stages complete, 129 tests each, zero failures. 120 workloads common to all arms, gas
identical across every arm to six significant figures (`1.41525e+10`).

### The precondition, which is already half the answer

```
before  sst=6699 walB=1224816684
flush (all cfs)  0.0s
after   sst=6699 walB=23
PRECONDITION OK: WAL drained, SST count moved by 0
```

**1.22 GB of WAL became 23 bytes in three seconds and added no SSTs.** Had it held unflushed
state, RocksDB's recovery would have flushed it into new L0 files. The subsequent `promote`
copied 69 MB in 171 ms — physically a near-no-op.

So the shipped WAL is **obsolete**, not unflushed: its contents were already in SSTs, and
RocksDB simply had not garbage-collected the log.

### The three-point decomposition

Reference = plain, same lineage, same device, same flags:

| bucket | n | **drained** | **compacted** | state-actor |
|---|---|---|---|---|
| absent | 12 | 0.992 | 1.025 | 0.128 |
| leaf-only | 36 | **0.996** | **0.228** | 0.223 |
| code-reading | 72 | **0.990** | **0.679** | 0.675 |

bytes read:

| bucket | drained | compacted | state-actor |
|---|---|---|---|
| absent | 1.026 | 0.654 | 16.943 |
| leaf-only | 1.020 | 6.700 | 8.324 |
| code-reading | 1.017 | 5.259 | 6.772 |

**Draining the WAL does nothing.** 0.996 and 0.990 on throughput, 1.020 and 1.017 on bytes —
all inside the 0.4–0.9% noise floor of round 28. **Compaction supplies the entire effect.**

Prediction from round 23, registered before the measurement: *"drained ≈ plain, and compaction
supplies nearly all of the effect."* Confirmed, with the drained arm indistinguishable from
plain rather than merely close.

### Where this differs from geth, and why that is interesting

geth's decomposition was **380 → 272 (drain) → 18.5 (compact)**: the journal drain accounted for
a real, if minority, share. Besu's is **0% drain, 100% compaction** — because the two artifacts
are not the same thing:

- geth's 380.15 MiB pathdb journal genuinely held **unflushed diff layers**, reloaded into memory
  on every boot. Draining it moved data that was otherwise served from RAM.
- Besu's 1.22 GB WAL holds **nothing that is not already on disk**. It is a log awaiting
  collection. Draining it frees a file and changes no read path.

Both snapshots ship a large recency artifact in the same structural position, and in Besu's case
the file is a red herring. The actual mechanism is that the pre-run's writes land in a handful
of young SSTs — the extraction has 6,695 and the post-pre-run store 6,699, so **the benchmark's
entire working set lives in about four files out of six thousand** — which a lookup reaches
before descending. Compaction merges those four into the 5,454-file bottom level and the
advantage disappears.

That is round 22's placement account, now isolated rather than inferred.

### Against the honest baseline

Reference = compacted:

| bucket | n | state-actor | plain | drained |
|---|---|---|---|---|
| absent | 12 | 0.122 | 0.975 | 0.957 |
| leaf-only | 36 | **0.951** | 4.386 | 4.308 |
| code-reading | 72 | **0.970** | 1.742 | 1.670 |
| *bytes* leaf-only | | 1.242 | 0.149 | 0.152 |
| *bytes* code-reading | | 1.288 | 0.190 | 0.193 |

The residual on this 120-workload subset is **4.9%** (leaf-only) and **3.0%** (code-reading),
against the full 1,100-workload suite's 5.4% — consistent, and 5–12× the noise floor. Bytes
1.242 and 1.288 bracket the 1.171 predicted from block geometry.

### Corrections this forces

Rounds 13 and 17 described the WAL as "state that never reached an SST, replayed into memtables
and served from RAM," and called it "the structural analogue of the geth root cause, 3.3×
larger." **The size was right and the interpretation was wrong.** It is inert. The correction
matters for the article: the striking 1.24 GiB number is not the cause of anything, and saying
so would have been the study's most quotable error.

---

## Round 30 — final re-evaluation of every pre-registered claim

### Evidence inventory

| | |
|---|---|
| full suites | 3 arms × ~1,462 tests, 0 failures, **1,100** common workloads |
| filtered suites | 6 arms × 129 tests, 0 failures, **120** common workloads |
| gas identity | exact to 6 s.f. in every comparison (`1.30409e+11`, `1.41525e+10`) |
| noise floor, same state | **0.4–0.9%** throughput, ≤0.8% bytes (s4 vs s5) |
| noise floor, whole pipeline | **0.4%** leaf-only, **1.3%** code-reading (full vs filtered, separate extractions) |
| store censuses | 3 pristine (byte-identical), 2 post-pre-run, drained, compacted |
| SST geometry | all three stores, including filter size and policy |
| read counters | per-test, two arms |

### Verdicts

**P1 — compaction spread smaller on Besu than geth. REFUTED, decisively.**
Predicted smaller than geth's 1.031–1.117 (median 1.091). Measured, against the compacted
baseline: plain is **4.386×** faster on leaf-only and **1.742×** on code-reading. Treatment state
matters roughly 40× more on Besu than on geth, not less. The reasoning behind the prediction —
"RocksDB auto-compacts aggressively" — was simply wrong for a store that arrives pre-built.

**P2 — a recency artifact exists in the promoted image. CONFIRMED; my named mechanism REFUTED.**
The artifact is real and large: plain runs 1.74–4.39× faster while moving 5.3–6.7× fewer bytes,
and it vanishes on treatment. But rounds 13 and 17 ranked "RocksDB WAL/memtable at shutdown" as
the leading candidate and called the 1.24 GiB WAL "the structural analogue of the geth root
cause." Round 29 killed that: draining the WAL yields **0.996 / 0.990**, inside the noise floor.
The WAL is obsolete, not unflushed. The mechanism is **LSM level placement** — the pre-run adds
four SSTs (6,695 → 6,699) and the benchmark's whole working set lives in them.

**P3 — the residual reproduces on a different engine. CONFIRMED.**
40 of 40 full-suite EXISTING categories favour the snapshot; median **5.4%** (range 2.1–11.0%).
Filtered subset: 4.9% leaf-only, 3.0% code-reading. Against a 0.4–0.9% noise floor, i.e. 5–12×.
geth published 9.1%. Same sign, same order, different engine, different compression algorithm,
8× different block size.

**P4 — bytes-per-read in 1.10–1.15. MISSED on magnitude; mechanism CONFIRMED to three digits.**
Measured sa ÷ treated: leaf-only **1.207** (full) / **1.242** (filtered), code-reading **1.320** /
**1.288**. The prediction was low. What did land is the geometry chain:

| | geth | besu |
|---|---|---|
| compression ratio, snapshot → generated | 0.849 → 0.991 = **1.167** | 0.438 → 0.513 = **1.171** |
| block size ratio | 3,467 → 4,043 B = **1.166** | 14,256 → 16,697 B = **1.171** |

and the measured leaf-only byte ratio (1.207–1.242) brackets that 1.171 within 3–6%. So the
*mechanism* transfers precisely; my arithmetic from geometry to observed bytes did not, and the
prediction was stated on the latter.

**P5 — identical reads across arms. HALF CONFIRMED.**
Gas is identical to six significant figures on all 1,100 and all 120 workloads, so the arms were
asked for identical work — certain. Read *counts* were collected this round but the absolute
values are unreliable: the scraper samples at 2 s and short tests are truncated, producing
implausible figures (64 reads against 3.4 GB). The *ratio* `missing ÷ total` is sound, being
taken within one sample, and it is what answered gap B. "Same reads, more bytes" remains
unproven; "same requested work, more bytes" is established.

### Transfer of the geth article's three findings

| | transfers? |
|---|---|
| **F1** journal residency as root cause | **Mechanism does not.** Besu's analogous file is inert. The *class* does: a promoted snapshot freezes the producing pipeline's LSM shape |
| **F2** drain + compact as the fix | **Half.** Compaction is the whole effect; the drain is a measured no-op |
| **F3** incompressible records → more bytes → more time | **Yes**, geometry to three significant figures, magnitude 5.4% vs 9.1% |

### Findings that were not pre-registered

1. **state-actor writes its SSTs with no bloom filter** — `filter_B = 0`, `policy = (none)` on
   every column family, against jochemnet's **7.3 GB** of filters. Costs **50×** bytes on
   absence proofs and 1.2–1.3× on lookups that find their key. A one-line configuration defect
   with a 50× consequence; worth reporting upstream.
2. The absent-class hypothesis (probe addresses occupied in the generated store) is **refuted**:
   `missing ÷ total` is 0.999 on state-actor against 0.955 on jochemnet.
3. The shipped 1.24 GiB WAL is **obsolete**, not unflushed.
4. Extraction is **deterministic** — three independent extractions produced byte-identical
   censuses (`sst=6695 sstB=382863226174 walB=1258464804 blob=26018`).
5. The post-pre-run WAL size is **not** constant: 1.225 GB vs 1.330 GB across two replays.
6. Code records differ in kind: jochemnet 7,227 B at phys/log **0.423**; state-actor 398 B at
   **0.863** — unique bytecode per generated contract.
7. state-actor is **deterministic across clients**: same state root as the geth store, item
   counts 6,404,913,395 vs 6,404,913,405.

### Still open, and to be stated as such

- Why the residual is 5.4% on Besu against 9.1% on geth.
- P4's magnitude gap: 1.21–1.32 measured against 1.171 geometric and 1.10–1.15 predicted.
- How much of the 1.2–1.3× byte ratio on found keys is bloom-filter absence rather than
  compressibility. Not separated.
- Absolute account-read counts (scraper truncation).
- The 5.9 GB `caches/` directory, never examined.

### Article readiness

All four gaps are closed. The root-cause section now has an isolated mechanism, a falsification
that landed (the drain does nothing), a three-point decomposition, two independent noise floors,
and a headline correction. The remaining work is writing, not measuring.

---

## Round 31 - the article is written and live

`besu-state-db-divergence/besu-state-db-report.html`, live at
<https://cperezz.github.io/articles/besu-state-db-divergence/besu-state-db-report.html>,
shipped on `main` at `eb3d2b2`. The Geth article gained the client name in its title
(`8d6e6b8`) so the two read as a series; that diff is the two title lines and the landing card.

**Headline: 8x.** `state_actor / plain` on the absent class, 0.124 -> 8.09x, floored to 8 as
Geth's 7.71 was floored to 7.

**The structure the article ended up with.** The decomposition is cleaner than the one I went
in with, because the two artifacts land on *different classes of read*:

| class | plain / compacted | state-actor / compacted | artifact |
|---|---|---|---|
| absent | 0.94x - no advantage | 8.5x | the generated store has no bloom filters |
| leaf-only | 5.26x faster as shipped | 0.952 | LSM placement of the pre-run's writes |
| code-reading | 1.54x faster as shipped | 0.958 | same |

So the 8x in the title is almost entirely the *bloom* defect, and the placement artifact - the
one that parallels Geth's journal - shows up on the classes that find their key. Writing it
forced that separation; the ledger had the numbers but had not stated it.

**Two claims I had to weaken or fix while writing.**

1. "The pre-run's rows sit in L0" was not measured - the shipped snapshot already had 22 L0
   files, so the four new ones cannot be identified by level alone. The article leads with what
   *is* measured: the compaction removed 10,833,266 cf06 entries, and a merge can only drop an
   entry that was an obsolete older version of a key. That proves the pre-run wrote newer
   versions above older ones. Level placement is then the mechanism, stated as such.
2. "The generated store reports `trieLog count: 0`" was never a Besu subcommand output - those
   failed in round 22. Replaced with the measurement: cf0a holds no files at all in the
   generated store, 2.8 MB in the snapshot.

**One derivation was wrong in my own tooling.** Summing `reads_missing / reads` across tests
gave a miss ratio of **1.003** - impossible. The counters are per-container samples, so the
sound aggregate is the ratio of per-test medians, which reproduces round 24's 0.955 / 0.999
exactly. `readmetrics.py` had it right; my first pass at the article did not.

**Geometry, re-measured on the compacted store** (`SstGeom`, cf06): `phys/log` 0.434 -> 0.513 =
**1.182x**, compressed bytes/block 14,147 -> 16,697 = **1.180x**. Geth published 1.167 / 1.166.
Within 1.3% on a different engine, different compression algorithm, 8x the block size.

**Provenance.** Every number in the prose is derived from `data/report_data.json` by
`gen_besu_state_db_report.py`; nothing is typed into the text. Fourteen oracles fail the build
if the data stops supporting a sentence - gas identity per arm, the drain being inert, the
same-state repeat being a noise floor, L0 empty after compaction, every cf losing entries,
filters present on the snapshot and absent on the generated store, and the direction of each
leg of the geometry chain. Raw evidence ships alongside: `levels.log`, `geom_jochemnet.txt`,
`geom_state_actor.txt`.

**Still open, and stated in the article as such:** why the residual is 5.1% on Besu and 9.1% on
Geth; how much of the 1.2-1.3x byte penalty on found keys is filter absence rather than record
geometry; the unexamined 5.9 GB of `caches/`; and whether the placement advantage is purely
level position or partly block-cache residency.

---

## Round 32 - correction: control rows were pooled into every category median

Anon asked whether the Besu divergent cases had all been brought within 10%. Checking rather
than answering from memory turned up a real defect in my own analysis, shipped live.

**The mistake.** Every EEST workload exists twice: once doing the account-state work, and once
as an `overhead_baseline` control that runs the same loop and deliberately touches no state.
Measured: control rows read a median **1.9 MB**, measurement rows **8.6 GB**, a factor of 4,600.
`ex_cat`, `sa_vs_comp`, `comp_t` and the verdict rows were all computed over both halves
pooled. For the 32 code-reading categories the split is exactly **11 control rows to 11
measurement rows**, so every median landed halfway between the measured value and the control's
~1.01.

This is the same class of error round 27 caught in `compare_filtered.py`, where a missing
`overhead_baseline` key collapsed each control/measurement pair. There the controls replaced the
measurements; here they diluted them. Both times the symptom was a result that looked better
than it was.

**What it hid.**

| | pooled | measurement rows only |
|---|---|---|
| compaction effect, code-reading | 0.679 | **0.166** (1.5x -> 6.2x) |
| compaction effect, leaf-only | 0.228 | **0.165** |
| state-actor / compacted, code-reading | 0.958 | **0.913** |
| categories inside +/-10% after treatment | 40 / 48 | **24 / 48** |
| worst existing category | 9.9% | **19.0%** |

**So the answer to the question is no, and it never was.** The corrected structure is three
groups, and it is a better result than the flattered one:

| group | n | after treatment | cause |
|---|---|---|---|
| code shared or absent (EOA, MINIMAL, SAME_MAX) | 24 | **5.2%** off parity | store geometry |
| distinct contract per access (DIFF_MAX, JUMPDEST) | 16 | **17.7%** off parity | unique, incompressible code records |
| absence proofs (NON_EXISTING) | 8 | **9.1x** apart | generated store has no bloom filters |

The second group is the same pair geth flagged (`BALANCE/DIFF_MAX`) and Nethermind devotes a
section to. Round 24's cf07 geometry already explains the ordering: state-actor's code records
average 398 B at `phys/log` 0.863, jochemnet's 7,671 B at 0.371. Order the classes by how much
unique contract code they touch and you have ordered the residual.

**The headline is unchanged at 8x** - the absence categories have no control rows, so that
number was never contaminated.

**Guards added**, because a control that is never asserted is not a control: every control
category must sit within 5% of parity, and neither half of the treatment may move it by more
than 5%. Measured 1.018-1.019, moved 0.5% by the drain and 1.0% by the compaction. Both tables
in the article now carry a control row, and the 660/440 split is stated in the opening
paragraph.

**Correction on the record:** rounds 20, 29 and 30 recorded "40 of 40 EXISTING categories within
the band, median 5.4%". Superseded 2026-09-16: that was 24 of 40 within the band on measurement
rows, with 16 at 17.7%. The claim that every existing class converges was pooling, not physics.

---

## Round 33 - regenerated from latest main: two of three cleared, one did not

### The premise was wrong, and in a useful direction

No PRs were filed. `ethereum/state-actor` has two open PRs, #109 (July) and #21 (April), neither
related; nothing from CPerezz since 2026-09-01, nothing in forks, no branch newer than main.

But two of the three fixes were already on `main`:

- **`11389bc` `fix(besu): align generated RocksDB configuration (#133)`, 2026-08-04.** "Besu Bloom
  filters are now enabled on every column family... full Bloom filter at 10 bits/key, matching
  Besu", with a `TestEveryColumnFamilyHasBloomFilter` guard. It fixes the exact defect round 24
  found: `bf := NewBloomFilter(10)` was reused across CF table options and `SetFilterPolicy`
  takes ownership of the native policy, so every CF after the first silently got none.
- **`70f14ee` `Add configurable-sized contract templates (#114)`, 2026-08-26.**

Our store was generated 2026-09-09 from `e4cb205-dirty`, a dirty WIP tree not even a valid object
in the repo today. **The filter defect we wrote up for upstream had been fixed a month before we
measured it.** We benchmarked a stale build. That is ours, not theirs.

### What was built

Branch `besu-residual-integration` = `origin/main` (70f14ee) + `754e8db`, which sets
`DefaultEOAFlavors().HasDelegation` from 0.30 to 0.0003. The 0.30 was documented as
"mainnet-shaped" and is not: mainnet designators are 4.2% of 2,416,222 code records, about 101,500
against 354,792,873 accounts, or 0.03%. The arithmetic closed exactly beforehand: 0.30 x ~430M
autofilled accounts = ~129M, against 134.4M cf07 records at 94.6% designators.

Regenerated with the same spec, seed 42, fork osaka, gas-limit 1e9, target 350GB. 10h31m,
exit 0. `accounts_created` 422,329,889 + `contracts_created` 8,366,849 = 430,696,738, identical to
v1's account total; contracts 16x fewer. New state root `0x2efb7792...`, DB 524 GB on disk.

### Verdict, measured on the store

| | v1 (what the article measured) | v2 | mainnet snapshot |
|---|---|---|---|
| filter policy, every CF | `(none)`, 0 B | **bloomfilter, 10.00 bits/key** | bloomfilter, 10.00 bits/key |
| 23-byte 7702 designators in cf07 | 94.6% | **3.4%** | 4.2% |
| plain-EOA share | 68.6% | **98.1%** | 80.8% |
| cf06 phys/log | 0.513 | **0.422** | 0.434 |
| cf06 compressed B/block | 16,697 | **13,755** | 14,147 |
| account block, modelled | 9,249 B | **4,860 B** | 5,590 B |
| cf07 entries | 134,442,676 | **7,916,852** | 2,416,222 |
| cf07 phys/log | 0.863 | **0.840** | 0.371 |
| code-read block, modelled | 10,718 B | **11,105 B** | 5,912 B |
| code-block co-tenants | 32.5 x 352 B | **2.2 x 5,613 B** | 2.4 x 7,298 B |

**P-bloom - CLEARED.** Filters on every column family at exactly 10 bits/key, matching Besu. The
8.5x absence class has no mechanism left.

**P-account - CLEARED, and over-corrected.** cf06 now compresses *better* than the snapshot
(0.422 vs 0.434) and its blocks are smaller (13,755 vs 14,147). The reason is worth naming: the
delegation fix took the contract share to 1.94% where mainnet is 19.2%, so this arm now
under-represents contracts instead of over-representing delegations. Parity by accident, from the
other side.

**P-code - NOT CLEARED.** The modelled block a distinct-contract read fetches went 10,718 ->
11,105 B against the snapshot's 5,912: unchanged, 1.88x. The co-tenant *count* now matches mainnet
(2.2 against 2.4), but the co-tenants are unique incompressible ~5.6 KB contracts (cf07 phys/log
0.840) where mainnet's are ~7.3 KB contracts that compress to 0.449. This was the prediction made
before launching, and it held.

So the remaining dig is exactly PR 3, bytecode **reuse**: mainnet serves 68.1M contract accounts
from 2.42M distinct bytecodes, about 28 per blob; v2 serves 8.37M from 7.92M, about 1.06 per blob.
Fixing size without fixing reuse leaves the code block where it was.

### Two operational lessons

1. An attached `docker run` launched over `tsh ssh` died at 16m25s with rc=137 and no kernel OOM,
   no systemd-oomd, no cgroup limit and no error output: the container's lifetime was tied to the
   SSH session. `docker run -d` under dockerd survived 10.5 h. Generation belongs to the daemon,
   not to a login session.
2. `TMPDIR` is not honoured for the streamsort spill; it went to the container's `/tmp`, on the
   root device, and reached 176 GB in one hour while `du` of the DB showed 44 GB. Bind-mounting
   `/tmp` onto the 9 TB array fixed it and cost wall time (10.5 h against v1's 4.9 h, spill moved
   from NVMe to HDD). Mount the spill explicitly; do not trust the variable.

### Still open

The throughput re-run. NVMe is now at 96% (145 GB free) and the SA arm's expected path
`/schelk/state-actor/v1/besu` no longer exists, since the 1.4 T schelk volume is 81% full with the
jochemnet snapshot. Device parity, both arms on md2 NVMe, is a controlled variable. Plan: only the
state-actor arm needs re-running, compared against the archived treated-jochemnet results, valid
within the measured 0.2-1.3% pipeline reproducibility. That frees `besu-joc-scratch.img` (1.4 T,
restorable from virgin) to make room for a v2 volume on NVMe.

---

## Round 34 - consolidation, and the fixed/slope fit that changes every target

### Where the gap stands (v1 throughput, the only throughput data that exists)

660 measurement rows against the compacted snapshot: **341 inside +/-10% (51.7%), 319 outside**.
Per category: **24 of 48 inside**. The 319 failures are entirely two classes, and a third never
fails:

| class | cats | workloads outside | median ratio |
|---|---|---|---|
| absent (NON_EXISTING) | 8 | 110 of 110 (100%) | 0.110 -> 9.07x |
| distinct-code (DIFF_MAX, JUMPDEST) | 16 | 209 of 220 (95%) | 0.823 -> 1.21x |
| shared/no-code (EOA, MINIMAL, SAME_MAX) | 24 | **0 of 330** | 0.948 |
| control | - | 7 of 440 | 1.019 |

Gas drift: shared flat 0.95 -> 0.94; distinct-code 0.85 -> 0.79; absent 0.15 -> 0.10.

### A0: fit t = f + v*G per category, and the drift dissolves into a slope

A pure per-read block-cost model predicts a flat ratio, so the drift needed explaining. Fitting
wall time against gas used over the 11 budgets, per category, per arm:

| class | n | f_ref (s) | f_syn (s) | f_syn - f_ref | v_ref/v_syn |
|---|---|---|---|---|---|
| shared/no-code | 24 | 1.327 | 1.210 | -0.117 | **0.933** |
| distinct-code | 16 | 2.605 | 1.685 | **-0.919** | **0.761** |
| absent | 8 | 0.473 | 1.200 | +0.727 | **0.076** |
| control | 32 | 0.136 | 0.137 | **+0.001** | **1.019** |

**The drift is a fixed-term artefact, and fitting it out makes every gap bigger, not smaller.**
The synthetic arm carries a *smaller* fixed cost on the two existing-account classes (-0.92 s on
distinct-code), which flatters it at low budgets; as the budget grows the slope shows through.
Corrected per-gas penalties: shared **6.7%** (not 5.2%), distinct-code **31%** (not 21%), absent
**13.2x** (not 9.07x). Single-budget ratios understate all three.

**And the 1.9% control offset is not a fixed-term artefact.** The control's fixed terms match to
1 ms (0.136 vs 0.137 s) while its *slope* ratio is 1.019. So the synthetic arm is genuinely 1.9%
faster per unit gas on work that touches no account state. That is a real floor, not a startup
cost, and it cannot be fitted away. The plan-debate pre-registered the opposite ("the drift is a
fixed-term artefact, the 1.9% floor is retired"); the fit falsifies half of that. Most likely
cause is the one asymmetry already on the record: the two arms run *different EEST payload bundle
builds* (`eest-payloads-jochemnet-v1-...d9ad55b3-20260807` against
`...state-actor-v1-...2282c757-20260722`), so the control tests are not the same transactions.
Aligning the bundles is now a prerequisite for claiming anything under ~2%.

### Consequence for targets

Every class target moves from "median ratio" to "slope ratio with the fixed term reported and
subtracted", and a throughput ratio quoted at a single gas budget is not meaningful without its
budget. This is a methodology correction that belongs upstream alongside the
measurement/control-pooling one.

### Space reclaimed

`besu-joc-scratch.img` (1.4 TB, the compacted-jochemnet scratch) unmounted, dm-era torn down,
loop detached, file re-created sparse. NVMe **145 GB -> 1.6 TB** free. The virgin image is
untouched and still attached, so the scratch is re-derivable with `schelk full-recover` plus a
90-minute recompaction. Docker build cache, stopped containers, inactive volumes and the two
stale generator images: another 22 GB. The old v1 store was *kept*: it is 533 GB on the HDD array
which has 9 TB free, so deleting it would not have helped the device that was tight, and it is
the only copy of the store the published article measured.

### v3 is generating

All three fixes are upstream: #133 (bloom on every CF, 10 bits/key), **#137** (delegation 0.30 ->
0.02 *and* designators from a fixed 256-target pool, so the values repeat), **#138** (every
contract draws one of NumContracts/32 slices of an embedded OZ ERC20 runtime, i.e. ~32 accounts
per distinct bytecode against mainnet's 28.2; manifest gained `distinct_bytecodes`). #137
supersedes our local 0.0003 one-liner, which only made designators rare rather than shared.
Built `state-actor-besu:main-95e5a10` from `origin/main` and launched v3 detached under dockerd
with `/tmp` bind-mounted to the HDD array. v2 is kept, so the three stores isolate each fix.

---

## Round 35 - the absence class, measured rather than predicted

Anon asked whether the bloom fix had already settled the non-existing class, since round 34's
table still showed it 9.07x slow. It had, at the mechanism level; the table was v1's throughput,
which is the only throughput data that exists. Framing error on my part: those are historical
numbers, not status.

So the mechanism was measured directly instead of waiting for a 22 h arm. `MissCost.java` opens a
store read-only with its own OPTIONS, looks up 20,000 keys of the store's own cf06 key shape
(32 bytes, verified from the store) that are absent, and reads RocksDB's own statistics.
`BLOOM_FILTER_USEFUL` counts filter rejections that skipped a block, so a store with no filter
cannot increment it.

| | v1 (no filters) | v2 (filters) | snapshot (filters) |
|---|---|---|---|
| BLOOM_FILTER_USEFUL per lookup | **0.000** | **0.990** | 3.518 |
| **data-block reads per absent lookup** | **1.002** | **0.010** | **0.038** |
| filter false positives | - | 200 (1.0%) | 750 (3.75%) |
| wall per lookup (different devices, not comparable) | 11.9 us | 2.6 us | 3.8 us |

**Every absent lookup on v1 read a data block; 99% of them on v2 are rejected by the filter
without touching one.** A 100x reduction in the operation that cost the class 50.1x the bytes.
The 1.0% false-positive rate is what 10 bits/key gives.

Two details worth keeping. The snapshot consults a filter **3.5 times per lookup** because this
measurement is against the *uncompacted* virgin, where a lookup descends several files and each
one rejects; v2 is a single sorted run, so one check suffices. That also explains its higher
aggregate false-positive count, ~1% per check over 3.5 checks. Compacted to a single run, the
snapshot's figures should converge on v2's, so the expectation for the benchmark is **parity or
marginally better for the synthetic store**, not merely improvement.

The absence class therefore has no mechanism left to explain. It stays listed as unmeasured *in
throughput* until an arm runs, but the store-level gate for it is closed.

Measured on the virgin by mounting `/dev/loop0` with `-o ro,noload`, so no journal replay and no
writes; unmounted afterwards and the image verified unchanged.

---

## Round 36 - #138 over-corrects: one runtime tiled is not a code population

Answered without waiting for v3, because #138's effect is a property of the bytes it emits.

### What #138 actually does

`internal/autofill/code_pool.go`:

```go
func poolCode(j int, s Sampler) ([]byte, common.Hash) {
	src := templates.ERC20RuntimeBytecode          // 1,723 bytes, one OZ v5 runtime
	code := make([]byte, s.Draw(...))              // truncated normal, mean 5,120 B, [1 KiB, 24 KiB]
	for n := copy(code, src[j%len(src):]); n < len(code); {
		n += copy(code[n:], src)                   // tile the same runtime
	}
	...
}
```

`DistinctBytecodes = numContracts / 32`, matching `MainnetAccountsPerDistinctBytecode = 32`.

So the count is right (32 per blob against mainnet's 28.2) and the mean size is right (5,079 B
replicated against a fixture-corrected mainnet 5,265 B). **The content is not.** The source
runtime is 1,723 bytes and the mean code size is 5,120, so every blob is the same runtime tiled
about three times, rotated by `j`. Blobs are therefore self-similar internally *and* to each
other.

### Measured, by replicating poolCode and compressing its output

| | individual record | packed into a 32 KiB block |
|---|---|---|
| #138 pool, deflate | **0.2165** | **0.1060** |
| #138 pool, LZ4 -1 | **0.260** | **0.119** |
| mainnet, records >=1 KiB, deflate (n=4,000) | **0.443** | 0.329 (derived) |
| v2 (unique random), deflate | ~1.00 | 0.955 |
| mainnet cf07 phys/log, RocksDB's own LZ4 | - | **0.371** |

**#138's bytecode is about 2x too compressible individually and about 3x too compressible when
packed.** Modelled cost of the data block a distinct-contract read fetches (additive model,
calibrated to within 14-26% on the snapshot and v2, understating both):

| store | modelled block | vs snapshot's measured 5,912 B |
|---|---|---|
| v1 (measured) | 10,718 B | 1.81x |
| v2 (measured) | 11,105 B | 1.88x |
| **v3 (#138, modelled)** | **~1,046 B** | **~0.18x** |

### Verdict and pre-registered prediction for v3

#138 does not close the distinct-code class; it **flips the sign**. Expect the class to go from
0.82 (18% slower) to *faster* than the snapshot, still outside +/-10% but on the other side, and
expect cf07 phys/log to land near 0.12-0.26 against mainnet's 0.371. This is pre-registered
before v3 is probed.

The code's own comment anticipated exactly this: "ponytail: one real contract sliced at rotating
offsets, not a corpus. Upgrade to a small corpus if a benchmark shows it over-compresses." It
over-compresses.

### The fix, with the target numbers

A **corpus**, not one runtime: draw from N distinct real runtimes at mainnet frequency. Mainnet's
own population, from its cf07 (41,486 records sampled), is heavy-tailed with distinct spikes that
are the duplicated proxies and tokens: 216 B x 2,223, 23 B x 1,734 (7702 designators), 77 B x
1,038, 22,142 B x 964, 1,359 B x 828, 173 B x 778, 45 B x 635. Acceptance targets for the corpus:

- individual record deflate ~0.443 (mainnet, >=1 KiB)
- cf07 phys/log ~0.371 (RocksDB LZ4, CF-wide)
- mean record ~5,265 B and accounts per blob ~28 (both already met by #138)
- modelled fixture block 5,912 B +/- 12%

### A separate finding, and it is about the fixtures, not the generator

The 24,576-byte `max_diff` fixture contracts deflate to **0.011 on the mainnet store too**
(n=4,000). So the fixture's own code is unrealistically compressible on *both* arms: the
distinct-code class has never measured "reading realistic contract code", it has measured the
cost of the block padding around a near-free record. That is an EEST fixture-realism issue,
independent of state-actor, and it caps how much realism the generator side can buy.

---

## Round 37 - probed #138, and the prediction was right in direction and wrong in size

### Probing the live v3 store failed, for a reason worth recording

v3 is 14% through phase 1, so `cf06`/`cf07` are still in the generator's memtable and WAL. A
read-only RocksDB open in another process sees SSTs only, so both column families read as empty
while `cf08`/`cf09` (already flushed, 333 M and 461 M entries) read fine. Separately, every probe
that discovers column families via `OptionsUtil.loadLatestOptions` fails outright on a
state-actor store: it writes OPTIONS with librocksdb 10.10 and Besu's 10.6.2 rejects
`max_manifest_space_amp_pct` until Besu reopens the store and rewrites the file - which needs the
write lock the generator holds.

Fix, archived as `tools/besu-study/LiveGeom.java`: `RocksDB.listColumnFamilies` needs no OPTIONS
file and table properties live inside each SST, so plain `ColumnFamilyOptions` suffice. Works on
a live store, takes no lock, writes nothing. This supersedes the boot-Besu-first dance that
rounds 30-36 used.

### The measurement, on a 4 GB store built from `state-actor-besu:main-95e5a10`

| metric | v1 | v2 | **#138** | mainnet | #138 vs target |
|---|---|---|---|---|---|
| `cf07` phys/log, RocksDB LZ4 | 0.863 | 0.840 | **0.056** | 0.371 | **0.15x** |
| pooled record deflate, >=1 KiB | - | ~1.00 | **0.2147** | 0.443 | 0.48x |
| packed 32 KiB block deflate | - | 0.955 | **0.1116** | 0.329 | 0.34x |
| `cf06` phys/log | 0.513 | 0.422 | **0.447** | 0.434 | 1.03x |

Round 36 predicted individual deflate 0.2165 and packed 0.1060 from a replication of `poolCode`;
measured 0.2147 and 0.1116. The replication was exact. **What it underestimated is the CF-wide
figure: predicted 0.12-0.26, measured 0.056.** The reason is cross-record redundancy - every pool
entry is a rotation of the same 1,723-byte source, so LZ4 compresses entries against each other
inside a data block, not merely within an entry. **6.6x too compressible, not 2-3x.**

`cf06` at 0.447 vs mainnet 0.434 is parity, 3% on the expensive side. Round 35's worry that #137
over-corrected the account class (0.422, cheaper than mainnet) is resolved: #138's pooled code
brought it back across the line. That class is done.

### An anomaly that resolved benignly

The smoke store reports 180,692 `contracts_created` but only 2,882 records in `cf07`, which looks
like the pool collapsing under rotation collisions. It is not: the manifest records
`num_contracts = 83,886` and `distinct_bytecodes = 2,621`, exactly 83,886/32. The pool governs
autofill contracts only; the other ~96,806 contracts are spec-loaded templates carrying their own
code. **Realised reuse is 32.0 accounts per distinct bytecode against mainnet's 28.2 - correct.**
So #138 got reuse and size right and only content wrong, which is a much smaller fix than round
36 implied.

### Hand-off written

`docs/superpowers/specs/2026-09-17-state-actor-corpus-prompt.md` (191 lines, self-contained,
every figure fact-checked against `report_data.json` and the probes). Three hard gates - pooled
record deflate 0.39-0.50, packed block 0.28-0.38, `cf07` phys/log 0.31-0.43 - plus three
invariants to preserve, and the lower-tail size-histogram gap explicitly deferred.

Design note handed over: prefix real corpus members, never tile, because tiling is the defect.
The interesting question asked of the implementer is whether hitting the CF-wide gate needs more
corpus members than the per-record gate does - that answers whether mainnet's code
compressibility is within-contract or across-contract redundancy, which this study never
established.

### Status of the three classes

| class | mechanism | store-level gate | throughput |
|---|---|---|---|
| absent (8 cats) | filters - closed | 0.010 vs 1.002 block reads | unmeasured, expect parity |
| shared/no-code (24 cats) | account entropy - closed | `cf06` 0.447 vs 0.434 | unmeasured, expect parity |
| distinct-code (16 cats) | code content - **open, PR pending** | `cf07` 0.056 vs 0.371 | v1 0.761 per-gas slope |

v3 keeps generating (~8 h left). It is now a store built with known-wrong code content, so it
measures the absent and account classes only. Do not spend a 22 h arm on it; the ~3 h subset is
the right instrument, and the full arm waits for the corpus PR.

---

## Round 38 - enumerating the diff, and a framing error of mine that it exposes

Anon asked for the full list of what still differs and where. Enumerated all 48 categories from
`report_data.json` (660 measurement rows + 440 control rows, `state_actor` vs `compacted`).

### The framing error

Rounds 32-37 reported "24 of 48 categories inside +/-10%", which reads as "half the suite is
clean". It is not what the data says:

- **0 of 660 measurement rows is faster than the snapshot.** Max ratio 0.984.
- **0 of 48 category medians is at parity.** Best is `CALLCODE/EXISTING_EOA` at 0.960, i.e. 4.1%
  slower; control-normalised, 6.1% slower.
- The control arm sits at **1.019** - state-actor is 1.9% *faster* on work touching no account
  state. So the parity line for measurement rows is 1.019, not 1.000, and every category is below
  it.

The +/-10% band was adopted as the acceptance gate for the *generator*, and it is fine for that.
But quoted as a description of the study it hides a uniform 6-8% floor under the whole suite.
Corrected statement: **every category reading account state is slower on the synthetic store; the
suite splits into three bands, not into pass and fail.**

| class | cats | rows | outside +/-10% | median | control-normalised | penalty | mechanism |
|---|---|---|---|---|---|---|---|
| absent | 8 | 110 | 110 | 0.117 | 0.115 | 770% | CLOSED (#133) |
| distinct-code | 16 | 220 | 209 | 0.828 | 0.813 | 23.1% | **OPEN** |
| shared/no-code | 24 | 330 | 0 | 0.947 | 0.930 | 7.6% | CLOSED (#137/#138) |

### Two taxonomy defects in my own class split

1. **`CALL/NON_EXISTING_ACCOUNT` with `value_sent=1` is not an absence proof.** Split by
   `value_sent`: 0.119 (range 0.110-0.156) at `value_sent=0`, **0.765** (0.751-0.777) at
   `value_sent=1`. Sending ether to an account that does not exist *creates* it - a write path.
   So the absent class is really 99 pure-read rows at 0.099-0.156 plus 11 write-path rows at
   0.765, and the class median of 0.117 is a blend of two mechanisms.
2. **The 11 distinct-code rows that "land inside the band" are all `value_sent=1` `CALL` rows** at
   0.901-0.916. They pass on write-path dilution, not because the read is clean. There is no gas
   budget or opcode at which a distinct-contract read is at parity.

### A property of the residual that rules out the fixed-cost model

Median ratio by gas budget, 100M -> 300M:

| class | 100M | 200M | 300M |
|---|---|---|---|
| absent | 0.147 | 0.112 | 0.099 |
| distinct-code | 0.852 | 0.823 | 0.790 |
| shared/no-code | 0.952 | 0.947 | 0.940 |
| **control** | **1.021** | **1.020** | **1.020** |

The gap **widens monotonically with the gas budget** in all three measurement classes while the
control stays flat to within 1%. A constant per-read penalty predicts a flat ratio; a constant
per-block overhead predicts the ratio *improving* with gas. Neither fits. The penalty per read
grows with the number of reads in the block, which is a working-set effect, and it means any
single-number summary of the residual is budget-dependent. Round 34's `t = f + v*G` fit reached
the same conclusion from the other direction.

### Scope caveat that applies to this whole table

Every throughput figure above was measured on **v1** (`state_actor_source: e4cb205-dirty`),
generated before #133, #137 and #138 existed. Store-level gates now say 32 of the 48 categories
(absent 8, shared/no-code 24) have had their mechanism removed. **None of them has been
re-measured.** This table is the last measured diff, not the current one. The only category group
whose mechanism is still open is distinct-code: 16 categories, 220 workloads, median 0.828.

---

## Round 39 - v2 confirmed: the distinct-code diff is still there, measured at the block layer

Anon asked to re-run the one remaining class against v2 and confirm the diff persists. The
throughput run is blocked (below); the mechanism is now measured model-free, which answers the
question the run was meant to answer.

### v2 gates as the right isolation store

`LiveGeom` on `/sa-besu/v2`:

| metric | v2 | snapshot | reading |
|---|---|---|---|
| `cf06` phys/log | **0.433** | 0.434 | account class at parity - closed |
| filters, every CF | present, 10.0 bits/key | present | absence class closed (#133) |
| `cf07` phys/log | **0.841** | 0.371 | **code class fully open** |
| pooled record deflate >=1 KiB | **1.0021** | 0.443 | pure random - no #138, as intended |

So v2 is the first store where the code class is isolated: the other two mechanisms are gone and
this one is untouched. v3 would have been the wrong instrument - #138's over-compressed code
(round 37) contaminates exactly this class. v3 was therefore killed and its 480 GB reclaimed.

### The measurement

`tools/besu-study/CodeReadCost.java`. The `EXISTING_CONTRACT_DIFF_MAX` population is 150,000
contracts of exactly 24,576 bytes, and both stores derive from the same state-actor spec
(hash `74dea7d1...`), so selecting `cf07` values of that exact length selects the same contracts
in both. Two-phase: sample keys, drop the host page cache, then read. Disk bytes from
`/proc/self/io read_bytes`, 4 GB block cache on both arms so the block counter is first-touch
rather than thrash.

| per cold code read | **v2** | snapshot (as published) |
|---|---|---|
| **DISK bytes** | **17,724 B** | **901 B** |
| data blocks, first touch | 0.983 | 0.532 |
| block bytes, uncompressed | 39,005 B | 25,627 B |
| wall | 231.9 us | 56.0 us |

The co-tenants are the whole story: the block is 39,005 B on v2 against 25,627 B on the snapshot,
and the 13,378 B of difference is v2's incompressible neighbours. The fixture contract itself
deflates to 0.011 on **both** stores, so it contributes nothing either way - exactly the
"block co-tenancy, not code compressibility" conclusion of round 36, now measured on a real read
instead of modelled by `BlockSim`.

**Two failed probe designs, recorded so they are not repeated.** (1) Single-process: collecting
the key sample warms precisely the blocks the read loop then reads, so both stores reported an
identical 380,928 disk bytes - JVM startup only. (2) Default 8 MB block cache: 14.4 data blocks
per read, which measures cache thrash, not the store. Both numbers were discarded.

### Honest scaling of the result

19.7x is against the **as-published** snapshot, and that arm flatters itself: the fixture blobs
were deployed by pre-runs, so in an uncompacted store they cluster in the newest SSTs - visible
as 0.532 blocks per read, i.e. sampled fixtures sharing blocks. The article's reference arm is the
**compacted** snapshot, whose code block `BlockSim` put at 5,912 B. Against that reference v2 is
**~3.0x the disk bytes per distinct-contract code read**. Either way the mechanism is present and
large, and 3.0x on bytes is the right order to produce the measured 17-21% throughput penalty.

### Why the throughput run is blocked: fixtures are pinned to store lineage

Provisioned v2 into a schelk virgin/scratch pair with the same dm-era rollback the archived
`s2-sa` arm used (method-identical, so no confound), then ran a 2-test gate. It failed
`passed=0 total=2`: `engine_newPayload` returns SYNCING.

Cause, confirmed by hashes: an EEST payload bundle pins `snapshotBlockHash` and `startBlockHash`.
The state-actor bundle demands `0x4525339a...`; v2's genesis is `0x223a49bd...`. Same spec hash
gives the same *addresses*, but v2's state root is `0x2efb7792...` against v1's `0x5b305cc0...`,
so the genesis block hash differs and every payload's `parentHash` misses.

**This is a structural cost of the whole programme, not a v2 quirk: every regenerated store needs
a freshly built EEST payload bundle.** It applies to v3, and it will apply to the corpus-fix store
that PR validation depends on. No state-actor bundle matching v2 exists upstream (a newer
*jochemnet* stateful bundle, `e269bb44-20260916`, was published yesterday).

For a real throughput arm, two prerequisites, in this order:
1. Build an EEST payload bundle against v2's genesis `0x223a49bd...`. Transactions are identical
   to the v1 bundle - the addresses did not move - so only block headers need refilling.
2. Re-derive the compacted snapshot arm: `schelk full-recover` (~90 min) + `rockscompact`
   (~91 min). Needs 1,122 GB; only 388 GB is free, so `/sa-besu/v2` must be deleted first - safe,
   its content now lives in the schelk virgin.

Then the 129-test filter, two arms, about 2.6 h each.

### Host state left behind

- `/schelk/state-actor/v1/besu` = v2, promoted, dm-era `besu_sa2_era`, 388 GB free.
- `/var/lib/schelk/state.json` now binds the **v2** pair. The old jochemnet binding is kept as
  `state.json.jochemnet-stale` with a README: it names `/dev/loop1` as its scratch, but loop1 is
  now the v2 virgin, so restoring that file as-is would destroy v2. The jochemnet virgin
  (1,122 GB, loop0, the only copy of the snapshot store) is intact and re-adoptable via
  `schelk init-from --virgin /dev/loop0`.
- `run-stages.sh` `teardown()` does `rm -f /schelk-vols/*.img`. Never call it while the jochemnet
  virgin matters.

---

## Round 40 - yes, the payloads are rebuildable: benchmarkoor has a first-class hook, with one hard constraint

Anon asked whether the payloads can be rebuilt and whether benchmarkoor has a hook. Both yes, and
I had it wrong in round 39.

### Correction to round 39

I wrote that benchmarkoor "cannot build payloads (no `getPayload`/`payloadAttributes` anywhere)".
That was the wrong probe. benchmarkoor does not build blocks itself; it *orchestrates* a filler.
The installed binary has the command:

```
benchmarkoor build   Build datadirs and fixtures declared under the builder.* config blocks
  - builder.state_actor    materialises pre-populated client datadirs by invoking state-actor
  - builder.pre_runs       advances a snapshot datadir and persists the result
  - builder.eest_payloads  generates stateful EEST benchmark fixtures by running fill-stateful
                           against a filler client booted on a snapshot
```

with `--limit-eest-payload-target`, `--force`, `--rebuild-on-diff`. Builds are decoupled from
`benchmarkoor run` by design: they write artifacts that a later run consumes through its normal
test-source provider. The consuming side already exists too -
`tests.source.eest_fixtures.local_fixtures_dir` (and `local_fixtures_tarball`), so replaying
locally filled fixtures needs no code change at all.

### How the anchor problem solves itself

Round 39's blocker was that a bundle pins `snapshotBlockHash`. It turns out nothing pins it in
config: `pkg/builder/eest_payloads.go` boots the filler on the store, calls
`eth_getBlockByNumber("latest", false)` (`pkg/builder/rpc.go`), and passes the result as
`--snapshot-block=<hash>`. Upstream documents why it is a hash and not `latest`: a reorg between
session start and fixture write would silently re-anchor the fixture. So the pipeline adapts to
whatever store you point it at - v2's `0x223a49bd...` included. The pin is an output, not an input.

The resulting invocation (from `buildFillArgs`):

```
uv run fill-stateful -v \
  --rpc-endpoint=http://<filler>:<rpc> --engine-endpoint=http://<filler>:<engine> \
  --engine-jwt-secret-file=/jwt/jwtsecret \
  --fork=amsterdam --snapshot-block=<hash queried live> --output=/out \
  --gas-benchmark-values=100,120,140,160,180,200,220,240,260,280,300 \
  tests/benchmark/stateful/bloatnet -m repricing
```

### The hard constraint: the filler must be geth

`fill-stateful` replaces fill's t8n backend with `ClientBackend`
(`packages/testing/src/execution_testing/client_clis/client_backend.py`), which builds each block
with **`testing_buildBlockV1`** - a Geth-only RPC extension - and advances the chain with
`engine_newPayloadVX`/`engine_forkchoiceUpdatedVX`. Besu, Nethermind, Erigon and Reth appear only
in secondary paths (opcode-trace and debug-rewind fallbacks); upstream states the only
production-ready backend is `ethpandaops/geth:master`. There is no JSON `pre` alloc path for these
fixtures - the pre-state *is* the store.

So **every store needs a geth twin to be fillable.** That is affordable because the generator is
client-independent: v1's geth and besu stores shared state root `0x5b305cc0...`, and the
`eest-payloads/geth/` bundle drove the Besu arm successfully. One geth twin, one fill, one bundle,
usable for every client under test.

### Cost to do it for v2, and why we should not

1. Rebuild the host state-actor binary from v2's source (`70f14ee` + `754e8db`) - minutes. The
   host binary defaults to `-client geth`, so the geth path needs no container.
2. Generate the geth twin: ~650 GB, ~10 h. Needs `/sa-besu/v2` deleted first (525 GB, safe - its
   content is in the schelk virgin); 388 GB free today, 913 GB after.
3. Pull `ethpandaops/geth:master`, boot it on the twin, fill at eest ref
   `d9ad55b33b7018e194a63cd167411dbb80f410e3` - the exact ref in the fixtures' `_info.url`, so the
   test ids stay identical to the archived arms and the comparison holds. ~1-3 h.
4. Re-derive the compacted snapshot arm: 1,122 GB, ~3 h. Only fits after the throwaway geth twin
   is deleted.
5. Two arms x 129 tests, ~2.6 h each.

About 20 h of exclusive device time. **Do not spend it on v2.** v2's mechanism is already measured
without any of this (round 39: 3.0x the disk bytes and 4.1x the wall per distinct-contract code
read). The store that actually needs a throughput arm is the corpus-fix store, and it pays the
identical 20 h. Rebuild once, for the store that decides the PR.

Recorded as a prerequisite in `2026-09-17-state-actor-corpus-prompt.md`: whoever regenerates a
store for validation must produce the geth twin too, or the store cannot be benchmarked at all.

---

## Round 41 - article brought to current status, and two pooled-control bugs it surfaced

Plan adjudicated by debate (plan mode, 2 rounds). Phase 1 of that plan is done and published.

### The attribution the debate forced me to check, and got right

I briefed the debaters that `cf06` 0.433 was the #137/#138 result measured on v2. The critic
demanded that be verified rather than inferred. It was wrong. `git merge-base --is-ancestor`
settles it: v2's base is `70f14ee` (#114), and **neither `c0e1162` (#137) nor `95e5a10` (#138)
is an ancestor of the v2 branch**. v2's only delta is my own `754e8db`, which dropped the
delegation *rate* to 0.03% rather than making designators repeat. So:

- v2's `cf06` 0.433 is my one-liner's number, not the PRs'.
- The PRs' store-level evidence is the 4 GB build from `main-95e5a10`: `cf06` **0.447**,
  reuse **32.0** per bytecode.
- #137 is the better fix and supersedes mine: it keeps mainnet's delegation rate and pools the
  designators, where I had merely made them rare.

The article states 0.447 and attributes it to the 4 GB build. Every store-level number in the new
prose carries the store it was measured on.

### Two bugs found, same root cause, both published wrong until today

1. **Besu, per-workload agreement.** The prose read "per workload rather than per category, 0%
   becomes 31%". `wl_after` counts over the 660 measurement rows but divided by `len(common)` =
   1,100, i.e. the control rows were back in the denominator. Correct figure **52%**. Round 32
   excluded controls from every category median and missed this one statistic.
2. **Nethermind, cross-client table.** It carried frozen besu literals
   (`besu_sa_over_plain 0.288`, `besu_sa_over_compacted 0.962`, bytes `2.916`/`1.124`, 108 cells)
   under a comment claiming they were computed from besu's data file. They were computed over a
   108-cell set that **pooled the controls in**. The controls sit at parity and read ~0.1x the
   bytes, so pooling them pulled besu toward agreement: published **0.962x** against a measured
   **0.908x**, and **2.92x** the bytes against **10.06x**. Now derived live from
   `besu-state-db-divergence/data/report_data.json` at collect time, controls excluded, with an
   assert that fails if anyone freezes it again.

Both are the same mistake in two articles: a control designed to prove the harness is honest,
averaged into the thing it was controlling for.

### Provenance error I published and then fixed

The new prose cited 17,724 disk bytes per cold code read as "the generated store", but that was
measured on the v2 rebuild, while every other number in the article comes from v1. Re-measured on
v1: **17,597 bytes** against the snapshot's 901, with v2's 17,724 kept as corroboration that the
figure is not an accident of one build. 0.7% apart, so the mechanism is identical in both. Wall
time dropped from the claim: v1 now lives on the HDD array and the snapshot on NVMe, so 232 us
against 56 us was measuring the device.

### What the article now says

New or rewritten: the #133 own-goal (merged 2026-08-04, our store generated 2026-09-09 from
`e4cb205-dirty`, **36 days** stale) with the absent-lookup mechanism measured at 1.002 -> 0.010
blocks; the #137+#138 outcome on account records; the #138 over-correction on distinct code
(`cf07` 0.056 against 0.371, 6.6x); a "Where this stands" table of three mechanisms and three
states; and the gas-budget gradient, which rules out both a fixed per-read and a fixed per-block
cost. The +/-10% band no longer reads as "half the suite is clean": 0 of 48 categories reach
parity, 0 of 660 workloads beat the snapshot, and the closest category is 5.7% slow once the
control offset is taken as the true zero.

New oracles, each one guarding a sentence: no dash may reach the page (entity or literal); no
measurement workload may beat the snapshot; no category may reach parity; the gradient must be
non-increasing per class and flat within 0.02 for the control; the nethermind besu reference must
be a controls-excluded derivation over at least 40 cells.

Numeric non-regression versus the previous build: **exactly one token removed, `31`**, and 66
added, all in the new sections. No unrelated computed value moved.

Published `b37978e`, both articles live and byte-identical. The user had pushed three nethermind
commits mid-flight; their work was taken wholesale and my correction re-applied on top of it.

### One plan step dropped

The plan called for archiving v2 to HDD (~500 GB, 5-7 h) before wiping it, because wiping makes
its measurements unreproducible. That is no longer true: the only published number that came from
v2 has been re-measured on v1, which is already archived at `/data/sa-besu-archive/v1`. v2 is a
diagnostic store from a superseded tree with no payload bundle and no geth twin, so nothing can
ever be benchmarked on it. Skipping the archive, and recording that as a decision rather than an
omission.

### Safety rails in place before any disk work

`/dev/loop0` (jochemnet virgin, 1,122 GB, the only copy of the snapshot store) set read-only via
`blockdev --setro`, verified. The stale schelk state file renamed to
`state.json.jochemnet-stale.DO-NOT-RESTORE.loop-ids-wrong` and chmod 000, because it names
`/dev/loop1` as its scratch and loop1 is now a live volume. `run-stages.sh` chmod 000 and replaced
by `run-stages-v3.sh` with `teardown()` deleted, that function being `rm -f /schelk-vols/*.img`.
