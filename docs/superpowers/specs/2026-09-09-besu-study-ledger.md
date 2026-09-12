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
