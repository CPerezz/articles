# Erigon state-DB study: execution ledger

Append-only. The box (`ubuntu@157.180.2.180`, "gas-repricing") is the source of truth; scripts and
configs under `tools/erigon-study/` are copies of what runs from `/bench/erigon/tools` and
`/bench/cfg`. Plan: `docs/superpowers/plans/2026-10-03-erigon-state-db-study.md`.

## Round 0 - host preparation (2026-10-02 22:20 UTC onward)

**Isolation.** Worktree `articles-wt-erigon`, branch `erigon-state-db-study` from `origin/main`
(`bc34cde`). Another session is active in the other articles worktrees; nothing here writes there.
On the box: schelk instances `er-joc` (`/dev/ram0`, `/schelk-er-joc`, 1900G) and `er-sa`
(`/dev/ram1`, `/schelk-er-sa`, 800G), dirs `/bench/erigon/*`, configs `/bench/cfg/er-*.yaml`.

**What existed.** 7.0 TB md2 NVMe at `/`, 1.1 TB free. Nethermind data: four schelk images
(nm-joc 1.6 TB x2, nm-sa 640 GB x2), `/bench/nm-store/v1` (523 GB, superseded) and `v2`
(472 GB). No suite running, no dm devices, last use 2026-09-25 (nm-13810 runs).

**Removed (Anon authorised wiping Nethermind data as needed).** `/bench/nm-store/v1`; the four
`nm-*.img` after detaching loop9/10/4/8. Their schelk state files are kept in
`/var/lib/schelk/retired/` (they name loops that no longer exist); notice in
`/bench/schelk-vols/NM-IMAGES-REMOVED-2026-10-03.txt`. Free after: 5.9 TB. `v2` stays until the
reference hashes below are recorded in this ledger (now done) and the fill is copied.

**Snapshot.** `https://snapshots.ethpandaops.io/jochemnet/erigon/24402727/snapshot.tar.zst`,
1,038,829,525,851 B (Last-Modified 2026-04-28). Head of the tarball: `_snapshot_eth_getBlockByNumber.json`
reports block 24,350,000 (0x1738d30), the mainnet fork base, and `chaindata/mdbx.dat` is
572,455,387,136 B. Download by `eg-fetch-joc.sh` (wget -c, Nethermind's retry policy, then size
and `zstd -t`) started 22:30; ~80-100 MB/s alone.

**Images (rootful podman).**
- `docker.io/ethpandaops/erigon:glamsterdam-devnet-7`: id `2e208c1e…`, digest
  `sha256:4023a007fe974301277fdcae8446e4c1c491dfefc92c762a81b70aaadb32d535`, built 2026-08-26,
  `erigon version 3.7.0-dev-5f62f4ed`, runs as uid 1000. Has `--override.amsterdam`,
  `--exec.no-merge`, `--exec.no-background-maintenance`, `--experimental.parallel-commitment`.
- `ghcr.io/ethereum/state-actor-erigon:main-005a19c`: id `f7eb453d…`, digest
  `sha256:ae9ca8c94d37d1a83ec48fce8c68f507abfc855c0270044a09269d1626d6e6ba`, revision
  `005a19c67534b7383a352acd65b9b06b2f81d58e` (the Nethermind v2 generator).
- benchmarkoor `dev` (no commit stamp; supports `method: schelk`), schelk 0.1.0 (93522c7).

**Reference values for the state-actor arm** (Nethermind v2 manifest and the fill's pre_run file):
genesis `0x0cb035288eb4e257f34f3d570ed4f43f9d2fc45c09f19db6c0392f60f4a68623`, state root
`0x48d611bb839188317e983453705b31e1420b2c4416675f98d776ad8e130d51b8`, chain id 1337, spec sha256
`74dea7d1de9d869d87ddcabf52912cada6d48cb1eb295819d322aef51c3f7194` (= `~/state-actor-spec-baseline.yaml`,
checked). The Erigon store must reproduce both hashes for the fill to apply.

**jochemnet genesis.** The canonical gist saved as `/bench/erigon/cfg/jochemnet-genesis.json`,
sha256 `998008d3…ab42e`: chainId 1, amsterdamTime 1769856767, osakaTime 1764798551. The
canonical override is `--override.amsterdam=1769856769`.

**Deviation from the plan.** The state-actor arm has no pre-run (as on Nethermind: the spec
pre-deploys the fixture accounts; `nm-sa-fin1` ran with `pre_run_steps=0`), so its suite A is
just the two smoke tests, without a promote.

**Contention observed.** `schelk init-new` clones the whole virgin image to scratch (1.9 TB at
0.4-1.3 GB/s); while it ran, the single-stream download fell from ~90 MB/s to ~8-18 MB/s although
a parallel range read still got 69 MB/s. Left to finish; the clone is ~1-1.5 h.

**schelk instances built** (`setup-er-schelk.sh`, 22:51-23:22 UTC): ramdisks zeroed with `dd`
(sized to the device; plain `dd` to the end returns ENOSPC); `er-joc` virgin/scratch on
loop3/loop4, `/dev/ram0`, `er_joc_era`, 1.9T fs; `er-sa` on loop6/loop8, `/dev/ram1`,
`er_sa_era`, 787G fs. Clones ran at ~1.5 GB/s; rootfs 3.0T used / 3.7T free afterwards (both
scratches fully allocated). The NM v2 store was removed after the reference values above were
recorded and the fill copied to `/bench/fixtures/sa-v2-full/erigon` (identical, `diff -rq`).

**state-actor generation started** 23:23 UTC (`gen-sa.sh`, directly into `/schelk-er-sa/erigon`,
rootful podman, nice/ionice). The writer reports the same composition as the Nethermind v2 store
(422,156,694 auto-fill EOAs, 7,340,032 contracts, chain id 1337, osaka, gas limit 1e9). Pipelines
queued behind markers: `extract-joc.sh` (G1 -> extract -> G3 -> delete tarball -> disk gate ->
promote -> probe) and `promote-sa.sh` (G4 -> disk gate -> promote -> probe). schelk operations in
both are serialised by `flock /bench/erigon/.schelk.lock`.

## Round 1 - jochemnet snapshot: download, extract, probe (2026-10-03 00:00-04:00 UTC)

**Download.** 1,038,829,525,851 B, `zstd -t` OK at 03:04 UTC. Eight server-side disconnects were
resumed by `wget -c` with `206 Partial Content`; the ninth reconnect (01:16) got `200 OK`, on which
`wget -c` re-reads the stream from byte 0 and discards it up to the local length (660 GB, ~1.7 h of
waste). Killed the fetch script and wget (no `.done` written), restarted it: `206` again, done at
02:45. Rule: on a `200 OK` in the fetch log, restart rather than wait.

**Extract** 03:05-03:40 UTC into the mounted er-joc scratch (~630 MB/s), 173 entries, tar rc 0,
`chaindata/mdbx.dat` apparent size matches. Tarball deleted after G3, as the plan said.

**Incident: the promote did not happen.** `extract-joc.sh` ran tar after `cd` into the mount, so its
own shell held `/schelk-er-joc` busy: `schelk promote` failed to unmount ("target is busy", listing
the script's PID), the script did not check the promote's exit code, the virgin stayed at 1.1 GB
allocated, and the probe then ran on the unpromoted scratch. The probe's closing `schelk restore`
failed for the same reason, so the scratch kept the probe's writes (one idle 16 s erigon boot, clean
shutdown in its log). Since the tarball was already deleted, the extract was not redone: the promoted
image is the extract plus that boot, and suite A's pre-run boots and writes the same store before its
own promote anyway. Fixed in the scripts: tar runs in a subshell, every script `cd /` first,
promote and restore exit codes are checked, and the tarball is deleted only after a successful
promote. Promote re-run by hand at ~04:00 UTC.

**Probe (G5-joc), on the scratch.** Erigon 3.7.0-dev boots the extract with the bench flag set
and answers RPC; `eth_blockNumber` 24,402,727, head hash
`0x488010e5acf359838e53d5908b1c3cb166ddc7b84c04e3f14463a95c249a5ba8`, state root
`0xec649dff…0160`. Chain config logged as `{ChainID: 1, …, Glamsterdam: 2026-01-31 10:52:49 UTC}`
= 1769856769, i.e. `--override.amsterdam` applies to the DB-stored config. Block 0 is not served
(`--prune.mode=full`). No index rebuild lines. The tarball's own metadata file names block
24,350,000, the fork base, as expected.

**state-actor generation, mid-run.** Accounts done at 01:24 UTC (60k/s); contracts at 54% by 03:23
(~280/s, store 331 GB). Projected store ~550-650 GB against a 787 GB volume: watched.

## Round 2 - suite A on jochemnet: the pre-run is commit-bound (2026-10-03 04:09 UTC onward)

**Promote** (by hand, 03:45-04:09): 1,436.65 GB of changed blocks copied in 24 min (1,022 MB/s);
virgin now 1.5 TB allocated; rootfs 2.4 TB free.

**Suite A launched** 04:09 (`run-suite.sh joc A A`, config sha256 `c60f7803…`): schelk restore,
erigon boot, then the 7,736-block pre-run (15,472 calls) before the promote and the two tests.

**Gate tripped: pre-run ETA 14 h** (plan limit 6 h). Every `engine_newPayloadV5` takes 50-75 ms;
every `engine_forkchoiceUpdatedV3` takes 5-6 s. Erigon's own log: `Timings: Forkchoice
flush+commit=4s` per block. Investigation:
- Pausing the state-actor generator (`podman pause`) for 150 s cut FCU from ~5.5 s to ~3.7 s, so
  the generator's I/O costs ~30% but is not the cause. Unpaused.
- fsync through the schelk stack is not slow: a 4 KB write+fsync takes 8-9 ms on `/schelk-er-joc`
  against 5-7 ms on the host fs.
- During commits the jochemnet device writes 5.5 MB/s at 2% busy and reads 0.2 MB/s, while the
  erigon process sits at ~99% of one core: the commit is single-thread CPU work inside erigon/MDBX
  on a 572 GB `mdbx.dat`, not I/O.

**Decision: let it run** (~12.5 h). No flag in this image makes the commit asynchronous
(`--fcu.background.commit` is absent; only `--fcu.timeout` and `--fcu.background.prune`), and the
pre-run's output is a state, so its wall time does not touch the measurement. The state-actor arm
proceeds meanwhile; suite A on state-actor and the B chain follow, serially.

**Measurement note for the analysis.** benchmarkoor's throughput uses `gas_used_time_total`, which
is newPayload time only (checked on `nm-joc-fin1`: it equals `method_stats.times.engine_newPayloadV5`;
FCU time is recorded separately). On erigon the per-block flush and commit happen in FCU, so the
collector must report FCU time per test beside newPayload throughput, or erigon's state-dependent
commit cost is invisible.

## Round 3 - state-actor generation moved off the scratch (2026-10-03 06:40 UTC)

**First run stopped by hand** at 06:40 after 7 h 17 min, 329.8 M of the ~335 M spec-storage slots
drained (`podman stop`; writer exit 2, no OOM or XFS errors). The writer was in place on the 787 GB
er-sa filesystem with 602 GB used and 146 GB free, all of it stream-sort temp directories
(accounts/storage/code plus 16 commitment-input parts; one at 148 GB, sixteen at ~22 GB). In
state-actor `005a19c` (`client/erigon/snapshot_cgo.go`) the commitment-input stores are closed only
after the fold, and the fold's branch store and the accounts/storage/code `.kv` writes both land in
the same directory while every temp store is still on disk. The volume was filling at ~2 GB/min
with those phases still ahead, so ENOSPC was likely, not certain.

**Restart cost nothing on the critical path.** Suite A on jochemnet holds the box until ~16:15
and suites never overlap, so the state-actor store is not needed before then; a fresh run from
06:43 lands ~14:30.

**New procedure** (`gen-sa-rootfs.sh`): same image, spec, seed and flags, written to
`/bench/erigon/sa-store` on the rootfs (2.4 TB free), checked (writer exit 0, manifest
`result.state_root` = `0x48d611bb…51b8`, no stream-sort dirs left), then `cp -a` into the scratch
with byte and file counts compared. The genesis-hash log check of `gen-sa.sh` was wrong for this
writer: only the Nethermind writer prints `genesis hash =`; the erigon one does not, so that check
would have failed a good run. The probe's block 0 is the genesis check now.

**`promote-sa.sh` now waits for an idle box** (no `.busy`, no benchmarkoor process) and holds
`.busy` during promote and probe: schelk calls on both instances share one global lock, so an
er-sa promote during the jochemnet suite could fail the suite's own schelk call.

## Round 4 - suite A on jochemnet passes the gate (2026-10-03 14:13 UTC)

**Pre-run:** 15,472/15,472 calls succeeded in 10 h 0 min (04:10-14:10). Head 24,410,463
(`0x4525339a…2c4e`), as expected. FCU per block: p50 4.3 s, mean 4.5 s, max 10.0 s; newPayload
p50 55 ms. `mdbx.dat` grew from 572.46 GB to 584.40 GB.

**Promote** 14:10:19-14:11:34 after a graceful stop (`Got interrupt, shutting down`); client
restarted on the new baseline. After the suite the snapshot tree has no temp or zero-length files
except `chaindata/mdbx.lck`, which is normal.

**Smoke tests:** both succeeded, 0 failures, at the expected gas.

| test | gas | newPayload | FCU |
|---|---|---|---|
| BALANCE / EXISTING_EOA / NO_CACHE 160M | 159,998,626 | 0.416 s | 4.056 s |
| ether transfers, diff_to_existent 240M | 240,000,000 | 5.885 s | 13.844 s |

On jochemnet the commit in FCU costs 2-10x the execution that benchmarkoor's throughput measures.
So FCU has to be reported beside newPayload. The collector's prefix match covers the
`engine_forkchoiceUpdatedV4` used by the tests (the pre-run uses V3).

**Per-test overhead:** the two tests took 1 min 6 s in total (~33 s each, including container
recreate and `schelk recover`), under the 68 s limit, so the full B chain runs.

**Fix:** benchmarkoor leaves the volume unmounted when a suite ends, and `run-suite.sh` refused to
start on an unmounted volume, so every B suite would have failed at once. benchmarkoor's own
`schelk restore` mounts ("ensure baseline + mounted"), so the check is gone.

**Held:** the B chain waits for the state-actor generator, which is still running on the same NVMe
(storage and commitment domains). A suite that overlapped it would measure the generator's I/O.

## Round 5 - state-actor store generated, promoted, probed (2026-10-04 02:42 UTC)

**Generation on the rootfs** took 19 h 42 min (06:43 Oct 3 to 02:24 Oct 4) and the writer exited
0. Phase times from the writer:
- `WriteDomain` accounts: 26 min.
- code: 1 h 28 min.
- storage: 3 h 46 min.
- fold: 2 h 38 min.
- `WriteCommitment`: 11 h 37 min, the critical path.

The finished store is 509 GB in 25 files (the 350 GB target counts the state, not erigon's
files), against the ~600 GB of temp files that ruled out generating in place. The manifest state
root is `0x48d611bb…51b8`.

**Copy** into the scratch 02:25-02:31: 545,623,174,078 B and 25 files on both sides.
**Promote** in 9 min 45 s; virgin now 795 GB allocated.

**Probe G5-sa:**
- RPC up; head 0.
- Block 0 hash `0x0cb03528…8623` and state root `0x48d611bb…51b8`, both equal to the
  reference (the Nethermind v2 store), with chain id 1337. So the 160M/240M fill applies unchanged.
- The EIP-8282 system contract has code and `0x1000` holds 1 ETH.
- No errors or index rebuilds.
- Clean stop in 1 s; restore copied back 75 blocks (4.7 MB).

The raw store stays at `/bench/erigon/sa-store` (rootfs 1.1 TB free) as a fallback for the
virgin image.

## Round 6 - suite A on state-actor, B chain launched (2026-10-04 06:27 UTC)

**Suite A on state-actor:** 2/2 passed, 55.6 s for both tests, rc 0. The gas matches jochemnet
test for test (159,998,626 and 240,000,000).

Single smoke runs, so these values are not measurements:

| test | arm | newPayload | FCU |
|---|---|---|---|
| BALANCE 160M | jochemnet | 0.416 s | 4.056 s |
| BALANCE 160M | state-actor | 0.481 s | 0.021 s |
| ether 240M | jochemnet | 5.885 s | 13.844 s |
| ether 240M | state-actor | 14.519 s | 0.645 s |

So FCU differs by one to two orders of magnitude between the arms. That supports collecting FCU
per test in B.

**B chain** (`chain-B.sh`: joc B1, sa B1, joc B2, sa B2) launched at 06:29 on an otherwise idle
box (the generator was done and no other container was running).

## Round 7 - B chain done; the baseline (2026-10-04 16:28 UTC, collected 2026-10-05)

**Runs:** four suites, all rc 0, 0 failures and 0 validation failures, serial on an idle box.

| suite | tests | duration | window (Oct 4) |
|---|---|---|---|
| joc B1 | 266 | 2 h 35 min | 06:29-09:06 |
| sa B1 | 456 | 2 h 22 min | 09:06-11:28 |
| joc B2 | 266 | 2 h 35 min | 11:28-14:05 |
| sa B2 | 456 | 2 h 22 min | 14:05-16:28 |

The 190 state-actor-only tests come from the larger state-actor fill (98 `ext_account_query_warm`,
32 `sstore_variants`, …). They are outside the intersection, as on Nethermind. Population: 266
tests, 0 gas mismatches. The class at 1 s on the jochemnet arm puts 121 tests at or above 1 s and
145 below. Output: `/bench/erigon/baseline-20261004.json` (sha256 `2e8554c8…33c9`).

**Collector extended** (`collect_baseline.py`):
- A second view over newPayload+FCU time (`a_total`, `b_total`), with its own replica floors and
  `reportable_total`.
- FCU ms summaries per row.
- Ratios are now time ratios (same gas on both arms). Every pre-existing per-test field
  is unchanged against the first run of the collector.

Ratio = state-actor throughput / jochemnet throughput; below 1 means state-actor is slower.

**Over 1 s, newPayload (benchmarkoor's metric):**
- Pair 1 is 0.314 and pair 2 is 0.318, against replica floors of 0.996 (jochemnet, 119/121
  within 10%) and 0.996 (state-actor, 121/121).
- 120/121 tests are beyond the floor; both pairs fall on the same side of 1 for all 121.
- So on erigon the generated store executes the same blocks ~3.2x slower. This is the opposite of
  Nethermind, where the pair ratio was 1.012.

**Over 1 s, newPayload+FCU:** pair 1 0.835 and pair 2 0.841, floors 0.997 and 0.994;
115/121 beyond the floor. The categories split:

| category (>= 1 s) | n | newPayload | +FCU | FCU ms joc / sa |
|---|---|---|---|---|
| code-exec JUMPDEST | 16 | 0.206 | 0.380 | 4,409 / 103 |
| code-exec DIFF_MAX | 16 | 0.275 | 0.446 | 4,430 / 96 |
| account row (4 modes) | 16 | 0.26-0.28 | 0.77-0.81 | 3,380-3,500 / 15-19 |
| code-exec MINIMAL / SAME_MAX | 29 | 0.30-0.31 | 0.84 | 4,410-4,460 / 69-86 |
| ether transfer | 36 | 0.339 | 1.072 | 11,777 / 638 |
| storage slot | 4 | 0.718 | 1.653 | 4,705 / 286 |

**Under 1 s** the FCU commit dominates the jochemnet arm. newPayload+FCU ratios run 7-14x in
state-actor's favour for absent-account, account-row and storage-slot tests: their jochemnet FCU is
~3.4 s and their execution is milliseconds. The 80 controls (no state work) show newPayload 1.30
(pair 2: 1.35), 49/80 beyond the floor; their FCU is ~8 ms on both arms. So a fixed per-block
newPayload cost is ~30% higher on jochemnet; cause not investigated.

**Mechanism, from benchmarkoor's per-method resource counters** (B1, medians, >= 1 s):
- On account-row tests, state-actor's newPayload reads 2.30 GiB in ~470 k IOPS. jochemnet reads
  0.31 GiB in ~80 k IOPS. CPU is 2-4 s against 1.6-2.1 s.
- Code-exec JUMPDEST/DIFF_MAX tests read 25.4 GiB against 6.6-9.9 GiB.
- The stores differ by tier: state-actor's erigon writer puts all state in frozen snapshot files
  (4.1 GB `chaindata`, 505 GB `snapshots`). Jochemnet holds 534 GB in MDBX `chaindata` beside
  873 GB of `snapshots`.
- With page caches dropped before each step, lookups in frozen, compressed domain files cost far
  more I/O than in MDBX. Inference only; not checked against erigon's read path. The same tier
  split explains FCU: jochemnet commits into a 584 GB MDBX (0.04-0.73 GiB written, 3.4-11.8 s),
  state-actor into a 4 GB one (<= 0.19 GiB, 15-640 ms).

**Reading for the study:** on erigon, "generated vs snapshot" is mostly "frozen-file tier vs MDBX
tier". A store that matched jochemnet would need the tested state in MDBX, or jochemnet's MDBX
state merged into files. Throughput must be stated per metric: newPayload alone favours jochemnet
3.2x; the whole block (newPayload+FCU) is closer and swings by category.

## Round 8 - article part 1; next experiments proposed (2026-10-05)

**Article worktree:** `articles-wt-erigon-article`, branch `erigon-state-db-article` from
`origin/main` (`bc34cde`), folder `erigon-state-db-divergence/`, commit `0c4ade9`. It uses the
Nethermind page's shape and helpers (`report_svg.py`, `crt_theme.py` byte-identical to main).
- Part 1 only: 733 words, 3 figures (newPayload overview, whole-block overview on the same axis,
  replica floor by duration), 1 table.
- 21 oracles, each mutation-tested (21/21 caught by their own message). Three of them caught false
  sentences in the first draft, fixed in the prose:
  - The "every existing-state test is slower" threshold.
  - "Commit outweighs execution" as the flip rule; it is "commit saved > extra execution".
  - "Absent-account lookups": over a second those tests are value-carrying CALLs.
- Style gate: sentence median 13, 0 em-dashes, 22 contractions/1k.
- Browser: no SVG text overflow, table fits, no NaN/undefined.

**Collector moved** to the article folder as `collect_erigon.py` (removed here). It adds per-test
newPayload read bytes and reproduces round 7's per-test values exactly.

**New fact from the client's own log:** at boot jochemnet reports
`[snapshots:history] ... first_history_idx_in_db=24349407`, frozen steps up to 2099 (~block 24.34M).
Every block after that, the shadowfork's and the 7,736 pre-run blocks, is in MDBX.

**Proposed next (not run; waiting for Anon), with predictions written before running:**
1. Step 0, diagnostics, store unchanged:
   - (a) Tier inventory per store: domain file step ranges and sizes, MDBX table sizes.
   - (b) Per-file read attribution for 4 tests per arm (account row, jumpdest call, ether
     transfer, storage), from a manual erigon boot: drop caches, replay the test's payloads, then
     page-cache residency per file (`fincore`).
   - Prediction: on jochemnet >= 80% of newPayload bytes come from `mdbx.dat`; on state-actor >= 80%
     from the accounts/code domain files and their indexes. If both arms read mostly files, the
     tier hypothesis is wrong and step 1 is off.
2. Step 1, fold jochemnet's database into files (Erigon's equivalent of the series' compaction):
   - Boot the promoted image without `--exec.no-merge/--exec.no-prune/--exec.no-background-maintenance`
     until every complete step is collated, merged and pruned.
   - Compact MDBX, verify head 24,410,463 and its state root, promote.
   - Run two fresh pairs (C1, C2) on the same 266 tests.
   - Prediction: jochemnet's newPayload slows on account and call tests; its FCU drops from
     3.4-11.8 s to under 1 s. Over a second, the newPayload ratio moves from 0.31 into 0.8-1.2, and
     the whole-block median into 0.9-1.1.
   - If jochemnet's reads move to files but the ratio stays below 0.5, the next suspect is
     state-actor's file layout (one step-0 file per domain, its index types).
   - Risk: the last, partial step can't be frozen, so if the pre-run's writes sit in it, step 1
     leaves them in MDBX. Step 0a answers that first.
   - The promote is one-way: rebuilding the untreated image means a re-download and the 10 h
     pre-run, unless the 509 GB raw state-actor copy is deleted to make room for a backup.

## Round 9 - step 0 confirms the tier split; step 1 can't exist (2026-10-05 20:36-21:05 UTC)

Anon approved step 0 and step 1, and asked for the decision to be written up in the article.

**Erigon facts, read at `5f62f4ed`** (the research agent first quoted line numbers from the
`binary-trie` working tree; every line below was re-located with `git grep` at the commit):
- `--exec.no-background-maintenance` stops all file building (`db/state/aggregator.go:2233`).
  Its help text: "NOT an operational setting" (`cmd/utils/flags.go:1220`).
- Reads: MDBX first (`db/state/domain.go:1854`), then files on a miss (`:1867`), newest first
  (`:1492`), with an existence-filter check per file (`:1499`).
- `erigon snapshots retire` (`cmd/utils/app/snapshots_cmd.go:3435`) builds files (`:3542`),
  prunes (`:3549`) and merges.
- An unfinished step is never frozen (`aggregator.go:2309`).
- `mdbx_copy -c` recipe: `cmd/integration/Readme.md:153`. mdbx-go is pinned at v0.43.0. The
  image ships only `erigon`, with no MDBX tools.

**Step 0 (`trace-tests.sh` + article `collect_trace.py`, tag T0).**
- Method: four tests per arm (BALANCE account read, jumpdest-scan call, ether transfer, sstore),
  all 4/4 passed. The kernel event `filemap:mm_filemap_add_to_page_cache` was filtered to the
  device-mapper major (252), and each call window was taken from benchmarkoor's
  `RPC call completed` lines. No events lost: 0 overruns, all 4,583,951 events read.
- Prediction met. On jochemnet, newPayload's page reads were 99-100% from `mdbx.dat` on all four
  tests. On state-actor, 0% came from the database:
  - account read: account indexes 53%, account files 47%;
  - jumpdest call: code files 77%;
  - ether transfer: commitment 80%;
  - sstore: commitment 91%.
  - forkchoiceUpdated read only the database on both.
- Inventory: jochemnet has 5 domain files per domain, frozen through step 2099 (124 domain files);
  state-actor has one file per domain, covering step 0-1.
- Two harness facts found along the way:
  - The schelk loop devices run without direct I/O (`DIO 0`; loop readahead 128 KB, md2 2 MB).
    benchmarkoor's `disk_read_bytes` is the physical traffic under that stack, 4-12x the pages
    the client asked for (0.08 vs 0.32 GB on the jochemnet account read; 2.20 vs 27.28 GB on the
    state-actor jumpdest call). Both arms share the stack.
  - `ext4lazyinit` on the scratch mounts is a read-only bitmap prefetch (~170 MB a run). Inode
    tables are zeroed (15,200/15,201 and 6,400/6,401 groups). It falls outside the test windows.
- Tracer fixes during the run:
  - The dm minor changes with every schelk restore, so the filter is the dm major.
  - The tracer leaves its arm unmounted (`schelk recover`), so the other arm's trace sees one dm
    device.

**Step 1 (`fold-joc.sh`): Erigon refused, correctly.**
- `erigon snapshots retire` ran in 17 s, rc 0. It froze block files up to 24,410,000 but built no
  state file: 124 domain files before and after, and MDBX grew to 586.26 GB.
- I stopped the compaction container (the copy wouldn't have fit, and was pointless). The script
  failed before the promote, as designed: the virgin image is unchanged, and the C chain never
  started.
- Why (counted over RPC on the promoted image, `step_size = 1562500` in `erigondb.toml`):
  - Blocks 24,349,407-24,410,463: 61,057 blocks, 1,212,682 transactions. That is 1,334,796
    txNums, 0.854 of one step.
  - Shadowfork: 53,321 blocks, 911,267 txs (17.1 per block). Pre-run: 7,736 blocks, 301,415 txs.
  - Mainnet 24,300,000-24,349,406: 340.3 txs per block, so a step fills in about 4,565 blocks
    (~15 h).

**Correction (supersedes round 8's step 1 rationale and the first draft of finding 1,
`b6e0a54`).** The benchmark's flags don't cause jochemnet's tiering. Everything after block
24,349,407 is one unfinished step, which any erigon node at this head keeps in MDBX. Jochemnet's
benchmark state is "new" to Erigon and state-actor's is "old". The snapshot can't be moved:
filling the step means adding blocks the fixtures weren't built on. Only the generated store can
move, if state-actor writes the tested state as a recent, unfrozen step. The article's finding 1
was rewritten on these facts (`e9ff7b7`): 31 oracles, all mutation-caught.

**Box state:** idle, no dm devices; jochemnet virgin = untreated post-pre-run image;
`/bench/erigon/sa-store` kept.

## Round 10 - the baseline again, with the scratch loops on direct I/O (2026-10-05 21:04 UTC)

**Why:** the reth study (same series, other host) found today that buffered schelk loop devices
dominated its times. Random reads were served about one at a time, ~79 µs a page; under
`LOOP_SET_DIRECT_IO` both arms ran 5-8x faster with unchanged page counts, and gaps closed. Its open
question asked whether the Erigon scratches were buffered. They were: `DIO 0` on loop4 (er-joc
scratch) and loop8 (er-sa scratch), checked in round 9. So B1/B2's time ratios mix store effects
with loop serialization, and the arm doing more random file reads (state-actor) likely pays more.
That last part is an inference until D lands.

**Setup:**
- `losetup --direct-io=on` on loop4 and loop8 with no dm device mapped; sysfs `loop/dio` = 1 on
  both, still 1 after benchmarkoor's first schelk restore.
- Virgins (loop3, loop6) stay buffered; they are only read during restores.
- md2: logical block 512, physical 4096; loop logical block 512.

**Run:** `chain-B.sh joc:D1 sa:D1 joc:D2 sa:D2`. Same config, image and 266 tests as B; only the
loop mode differs. `collect_erigon.py <day> D` collects it; the B series still reproduces
byte-for-byte.

**Early sign:** jochemnet's forkchoiceUpdated is still ~3.4 s per block on the first tests. That
fits the round 2 observation that the commit is single-thread CPU, not I/O.
