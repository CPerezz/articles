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

**D results (2026-10-06 06:19 UTC).** All four suites rc 0, 0 failures: joc D1/D2 266 tests in
2 h 40 min each, sa D1/D2 456 tests in 1 h 54 min each (2 h 22 min buffered). Loops still at
dio=1 at the end. `collect_erigon.py '*' D` gives 266 tests, 0 gas mismatches
(`/bench/erigon/baseline-D.json`, sha256 `03db801a…cf79`). Classes come from D's jochemnet
times: 55 tests over a second (121 under buffered loops).

| over a second | buffered B1 / B2 | direct I/O D1 / D2 |
|---|---|---|
| newPayload, all | 0.314 / 0.318 | 0.727 / 0.715 |
| call, distinct contract | 0.275 | 0.991 / 1.012 |
| call, jumpdest scan | 0.206 | 1.051 / 1.072 |
| ether transfer | 0.339 | 0.554 / 0.562 (22/22 beyond the floor) |
| whole block, all | 0.835 / 0.841 | 2.816 / 2.884 |
| replica floor, sa / joc | 121 / 119 of 121 | 55 / 46 of 55 |

- Under a second the floors are still 48-58% (whole block 58-73%), so the short-tests rule stands.
- Shown under a second: contract-account reads and plain calls 0.35-0.47, controls 1.30, absent
  accounts 1.05.
- Jochemnet alone, buffered/direct time per category (B1 vs D1): newPayload 1.6-7.4x faster under
  direct I/O over a second, forkchoiceUpdated 0.96-1.03x. The commit is CPU work; the loop never
  touched it.
- Reading: once the rig stops serialising reads, code loading is at parity. Account lookups and
  transfers stay about 2x slower on state-actor, and the commit, untouched by the rig, dominates
  jochemnet's whole block.

**Correction to round 9's "disk_read_bytes = physical traffic under readahead":** benchmarkoor
sums `rbytes` over every device in the container's `io.stat` (`pkg/stats/cgroup_reader.go:121`),
so the same bytes count once per layer (dm-era, loop, md2, nvme members). That's about 4x even
under direct I/O (the state-actor account read: traced 0.47 GB, counted ~2.2 GB). Buffered loops
added backing readahead on top (4-12x in B). Ratios between arms hold; absolute GB don't.

**Article** (`5f5cf18`): part 1 and finding 1 now run on the D series. Title "How can two Erigon
databases holding the same state be 2x slower and 3x faster?". The B series is kept under
`baseline_buffered` for the README errata. 29 oracles, 29/29 mutations caught, style gate (median
13), browser clean.

## Round 11 - the worst case is state-actor's layout; jochemnet is the store to fix (2026-10-06)

**Correction (Anon).** Round 9's "only the generator can move" and the proposal to make state-actor
write the tested state as an unfrozen step had the direction backwards. These benchmarks measure
the WORST case for a state read. In Erigon that's a key whose only copy is in the oldest, largest
frozen file: miss MDBX, pass every newer file, read from the bottom file. state-actor is that
(empty MDBX, everything in its one step-0 file set). Jochemnet isn't: the pre-run's accounts are in
MDBX, read first (traced 99-100%). It's the series' finding 1 again (Nethermind: pre-run keys in the
newest SST files; Besu: newest versions of their keys). So the fix moves jochemnet's tested state to
the bottom and out of MDBX. Moving state-actor into MDBX would turn the generated store into the
best case. *(superseded: round 9 "Only the generator can move" and round 10's next-step option 1.)*

Also caused by the same thing: jochemnet's 4-12 s commit, into a 584 GB MDBX. A running node's
MDBX holds about its newest step.

**Constraint:** Erigon won't freeze an unfinished step (round 9), so its own tools can't do it. It
takes a rewrite of jochemnet's files. Two read-only scouts were sent out, on erigon at `5f62f4ed`
and state-actor at `005a19c` (trees exported to /tmp at the exact commits so line numbers hold):
ways to put step-2099 values into the bottom file, commitment key-referencing, salt, boot checks,
reuse of state-actor's erigon file writer.

**Article** (`articles-wt-erigon-article`): finding 1 now ends on this framing. Jochemnet measures
the best case, state-actor the worst, and the store to fix is jochemnet.

## Round 12 - jochemnet rebuilt as a fully merged node (2026-10-06, launched 10:4x UTC)

**Target layout (the worst case, = state-actor's):** one `[0,1)` file set per state domain
(accounts, storage, code, commitment) holding every key's latest value at the head, and no state in
MDBX. A tested key's only copy is then in the bottom (only) file. This is the series' "compact into
the bottom level" in Erigon's terms.

**Why a new step size.** Erigon never freezes an unfinished step (round 9), and the head is 85% into
step 2099. `compactlatest inspect` on the untreated image gives:
- exec progress 24,410,463, commitment state at block 24,410,463, txNum 3,281,022,285, equal to
  that block's last txNum;
- files end at 3,279,687,500 (= 2099 x 1,562,500).

So step_size := 3,281,022,286 makes `[0,1)` end exactly at the head. It's the same construction
state-actor uses (its genesis block is padded to fill step 0). The stock `snapshots step-rebase`
can't do it: it only scales by divisors or multiples of 1,562,500, and `--keep-blocks` resets exec
(`cmd/utils/app/step_cmd.go`).

**Tool** (`tools/erigon-study/compactlatest/`, built against erigon `5f62f4ed` with mdbx-go v0.43.0;
`go vet` clean). It's one new file in `db/state` plus a driver. Everything else is erigon's own code:
- reads via `AggregatorRoTx.DebugRangeLatest` (MDBX + every file, newest wins; deleted keys dropped
  as in a merge to step 0, `merge.go:506`);
- commitment branches re-read through `AggregatorRoTx.GetLatest`, which expands shortened-key
  references. The jochemnet commitment files are v1.1 with ranges of 2 steps or more, so they are
  referenced (`CommitmentBranchReferenced`). The new file is written plain; a one-step file is never
  read as referenced (`DefaultKeyReferencingMinSteps = 2`), the same as state-actor's;
- written with each domain's configured compression (storage keys, code values, commitment keys,
  accounts none), as erigon's merge writes big files. `buildFileRange` builds .bt/.kvei/.kvi with the
  datadir's salt;
- each file is read back through the domain's own reader, and its stream sha256 and key count must
  match what was written;
- `reset` = `rawdbreset.ResetExec` (clears every state, history and II table), then execution
  progress := head;
- then `mdbx_copy -c`. Receipt-domain, history, idx and accessor files are removed (old step size;
  state-actor has none; block execution doesn't read them).

**Checks** (`compact-joc.sh`), all fail-fast before the promote:
1. Samples: every 1,000,000th key per domain, plus every 1,000th MDBX-resident account, storage
   and code key (the pre-run's and the shadowfork's).
2. `rpc-sample.py`: balance, nonce and `eth_getProof` per account; `eth_getStorageAt` and
   `eth_getProof` per slot; `eth_getCode`. Answered on the untreated layout and on the new one, the
   two outputs must be byte-identical. `eth_getProof` walks the commitment trie, so this checks trie
   paths, not just values.
3. `inspect` on the new layout: step size, files end and state txNum all agree with the head.
4. After the promote: smoke pair F1 2/2 (newPayload re-checks the state root), then trace T1.

**Predictions (written before the results):**
- Trace T1: jochemnet's newPayload reads come from the files at least 95% (was 99-100% from MDBX),
  the account read from account files and indexes.
- forkchoiceUpdated: jochemnet's commit drops from 4.3-11.9 s to under 1 s (MDBX shrinks from 584 GB
  to its non-state tables).
- Then two fresh pairs on direct-I/O loops (E1, E2): over a second, the newPayload ratio goes from
  0.72 to 0.85-1.15; ether transfers from 0.55 to 0.8-1.2; whole block from 2.8 to 0.8-1.25.
- If newPayload stays below 0.8 with the layouts matched, what's left is in how the two stores were
  built: state-actor's own file writer (pinned to erigon 3.4.2) against erigon's.

**Round 12 results (2026-10-06 10:38-23:03 UTC).** `compact-joc.sh` finished rc 0, and every gate
passed.
- **Compact** (9 h 05 min, read-only on the untreated image): accounts 354,792,873 keys (12.9 GB
  .kv), storage 1,822,629,119 (77.0 GB), code 68,023,550 (16.0 GB), commitment 786,799,699
  (218.3 GB). Each file was read back and its stream hash matched.
- **Reset** (`ResetExec`, 2 h 54 min): every state, history and II table is at 0 rows.
- **Swap:** 123 domain, 45 history, 81 idx and 126 accessor files deleted; 12 staged files copied
  in; erigondb.toml step_size = 3,281,022,286.
- **`mdbx_copy -c`** took mdbx.dat from 586.26 GB to 7.52 GB in 44 s. That's left from reorg
  tables and blocks after the frozen block files; state-actor's is 4.3 GB.
- **`inspect`:** exec progress, commitment state block and every file end agree with the head
  (24,410,463 / txNum 3,281,022,285).
- **RPC equivalence:** 339,329 samples, answers byte-identical on the old and new layouts.
  - That's balances, nonces, storage, code and `eth_getProof` account and storage trie paths.
  - 799 MDBX-resident accounts and 335,750 MDBX-resident slots are included, i.e. the pre-run's
    and the shadowfork's state.
- **Promote** done. Smoke F1: 2/2, 0 validation failures (newPayload re-checks the state root).

**Trace T1** (same four tests, rebuilt jochemnet, against the round 9 state-actor trace):

| test, newPayload | page reads, from where | state-actor (T0) |
|---|---|---|
| account read | 0.44 GB, account indexes 51% / files 49% | 0.47 GB, 53% / 47% |
| jumpdest call | 0.76 GB, code 42%, accounts 58% | 2.20 GB, code 78% |
| ether transfer | 0.62 GB, commitment 79%, accounts 20% | 0.64 GB, 80% / 20% |
| storage write | 0.11 GB, commitment 91% | 0.11 GB, 91% |

- 0% of jochemnet's newPayload page reads now come from MDBX (was 99-100%). Prediction met
  (>= 95% from files).
- Account read, transfer and storage write now read the same bytes from the same files on both
  stores, within 7%.
- The jumpdest call reads a third of state-actor's code bytes. That's code content (mainnet
  bytecode vs the generator's), not tier.

**Prediction missed: the commit.** The transfer's forkchoiceUpdated still takes 3.48 s (11.0 s
before; the account read 0.02 s, was 3.44 s). It now reads 1.49 GB from MDBX, against state-actor's
0.07 GB. MDBX holds no state tables now, so the reads must be non-state tables. It's not explained
yet; the E pairs measure it across all tests, then a trace of which MDBX tables FCU reads.

**E chain** (`chain-B.sh joc:E1 sa:E1 joc:E2 sa:E2`, direct-I/O loops) launched 23:04. The
`after-compact.sh` watcher never fired: `compact-joc.sh` wrote its marker only after its own smoke
and trace ran. It was killed and the chain started by hand.

**The commit tail, explained (2026-10-06 23:20 UTC).** Erigon's own timing line splits FCU into
`flush+commit` and `prune`:
- D1 (untreated): `flush+commit` 10-14 ms on most tests, 4 s on a few, `prune` 4 s.
- E1 (rebuilt): `flush+commit` 3-17 ms, `prune` 3 s on each container's first FCU, ~250 µs after.

So the multi-second FCU was mostly never the state commit. It's `runForkchoicePrune`
(`execution/execmodule/forkchoice.go:871-895`). On a fresh process it calls `CodeStore.Evict`
(`execution/cache/code_store.go:120`, on by default: `USE_CODE_STORE`, `common/dbg/experiments.go:137`),
which seeds its size by summing all of `TblCodeCache` once.
- The rebuilt jochemnet still holds a real mainnet code cache: 143,219 entries, ~1.25 GB, 302,526
  overflow pages. It isn't a state table, so ResetExec leaves it alone.
- state-actor's MDBX has no CodeCache rows at all.
- benchmarkoor recreates the container for every test, so jochemnet pays the full table scan on every
  test and state-actor never does. That's the 1.49 GB the transfer's FCU read from MDBX in T1.

It's the same kind of confound as the state tier: what one store carries that the other doesn't.
It's also a confound of the harness: each test boots a fresh client. The next step empties
jochemnet's CodeCache, so both stores start from an empty one; the clean fix keeps the client
unchanged. Not applied yet, so that E1/E2 measure the rebuild alone.

**E1, jochemnet side (2026-10-07 02:30 UTC; preliminary, against state-actor's D1).**
Rebuilt jochemnet ran 266/266 in 3 h 26 min (2 h 40 min untreated). Medians, newPayload ratio
state-actor/jochemnet, untreated D1 -> rebuilt E1:
- Account reads (under a second, contract accounts): 0.35-0.47 -> 0.89-1.00. EOA reads 1.12 -> 1.18.
- Plain calls (minimal, reused contract): 0.46 -> 0.93-0.96.
- Ether transfers: 0.55 -> 0.93 (over a second), 0.53 -> 0.96 (under).
- Storage slot over a second: 0.70 -> 0.98. Absent accounts 1.05 -> 0.99.
- **Code calls over a second flipped: distinct contract 0.99 -> 0.54, jumpdest 1.05 -> 0.66.** The
  rebuilt jochemnet runs them in 2.1-2.4 s against state-actor's 3.8-3.9 s. Trace T1: jochemnet's
  jumpdest call read 0.76 GB of pages, state-actor's 2.20 GB, most of it code files. On those tests
  the two stores now differ in code content and layout, not tier. Open: mainnet code (shared,
  deduplicated, smaller) against the generator's code pool. That is the series' Nethermind finding
  4 ("a contract's code block is shared with whatever the generator packed next to it") in Erigon.
- FCU: jochemnet 3.3-11.9 s -> 20-110 ms on most rows; ether transfers still 3.4 s (CodeCache seed
  scan; the G pairs test it). state-actor 7-695 ms.

These ratios use state-actor's D1 run, so they share no denominator with a fresh pair; E1/E2 and
G1/G2 are the measurements.

**Pair E1 (2026-10-07 04:25 UTC; floors wait for E2).** 266 tests, 0 gas mismatches. Classes from
the rebuilt jochemnet's own times: 110 tests over a second (it is slower now), 156 under.
- Over a second: newPayload **0.90**, whole block **0.95** (D: 0.73 / 2.82).
  - Account rows 0.87-0.98; plain calls 0.94-0.95; storage 0.98; ether transfers 0.93.
  - Code calls into distinct max-size contracts 0.56 (distinct) and 0.64 (jumpdest).
  - Transfers' whole block 1.90: the CodeCache scan, see the G pairs.
- FCU over a second now 20-110 ms on both stores except the transfers (jochemnet 3.46 s, state-actor
  0.63 s).

**The code-call gap is a generator artifact: state-actor's code file has no dictionary.** The tested
contracts are byte-identical on both stores: state-actor's `max_diff_pre_amsterdam` and
`unique_jumpdest_pre_amsterdam` patterns reproduce EEST's `StopJumpdestInitcode` and
`JochemnetPredeployContractInitcode` at the same CREATE2 addresses (state-actor `docs/SPEC.md:137-142`).
The two code files' seg headers, decoded per erigon's `db/seg/decompress.go:273-310`:

| code .kv | size | words | pattern dict |
|---|---|---|---|
| jochemnet, rebuilt by erigon's compressor | 16.0 GB | 136,047,100 (68.0 M keys) | 675,844 B |
| state-actor, its own writer | 49.6 GB | 33,373,490 (16.7 M keys) | 0 B |

state-actor's `internal/erigon/seg` is a pure-Go port that implements only the no-pattern path
(`compressor.go:20-50`: "pattern-cover compression (CompressKeys/CompressVals) is not implemented
in v1"). Erigon writes the code domain with `CompressVals` (`statecfg/state_schema.go:251`), whose
dictionary collapses the JUMPDEST filler. So a state-actor test contract costs its full 24 KB of
pages, and jochemnet's a fraction of that. That fits T1 (jumpdest call: 1.72 GB of code pages
against 0.32 GB). It's the series' Nethermind finding 4 again: the generator's code layout, not
state. Fixing it belongs in state-actor (pattern compression) or a re-encode of its store through
erigon's compressor. Deferred to Anon's re-evaluation; not part of the worst-case baseline fix.

**E series complete (2026-10-07 09:47 UTC)**, `/bench/erigon/baseline-E.json` sha256 `d82aa1f8…3f2f`.
The rebuilt jochemnet (worst-case layout) against the same state-actor store, direct-I/O loops, two
independent pairs. All four suites rc 0; 266 tests, 0 gas mismatches. Classes come from E's
jochemnet: 110 tests over a second, 156 under.

| over a second | pair 1 | pair 2 | floor sa / joc (in ±10%) |
|---|---|---|---|
| newPayload, all (110) | 0.901 | 0.924 | 95 / 97 of 110 |
| account rows, contract (16) | 0.87-0.98 | 0.88-1.05 | |
| calls: EOA / minimal / reused contract | 0.94 / 0.94 / 0.95 | 0.96 / 0.97 / 0.92 | |
| call, distinct contract (14) | 0.561 | 0.549 | 14/14 beyond the floor |
| call, jumpdest scan (14) | 0.640 | 0.639 | 14/14 beyond the floor |
| ether transfer (34) | 0.927 | 0.954 | |
| storage slot (2) | 0.977 | 0.987 | |
| whole block, all | 0.947 | 0.967 | |
| whole block, ether transfer | 1.90 | 1.83 | FCU 3.46 s vs 0.63 s |

Under a second (156, floors 87 and 78 = 56% and 50%): controls 1.38 / 1.41, warm query 1.21 / 1.57,
absent account 1.05 / 1.00.

**Reading.** With the layouts matched, everything that reads state lands at 0.87-0.98 except:
1. calls into distinct max-size contracts (0.55-0.64), explained by state-actor's dictionary-less
   code file;
2. the transfers' whole block, from jochemnet's carried code cache (G pairs).

Against the predictions: newPayload over a second 0.85-1.15 met (0.90 / 0.92). Ether transfers
0.8-1.2 met (0.93 / 0.95). Whole block 0.8-1.25 met overall (0.95 / 0.97), missed on the transfers
(1.90). The code calls came in below the range.

**G chain** (`clear-codecache-joc.sh`): TblCodeCache 143,219 -> 0 rows, promoted 09:4x, smoke S2,
then G1/G2 (~10.7 h).

*Correction to the E1 note above:* T1's jumpdest call read 1.73 GB of code pages on state-actor (code
files 1.71 + code indexes 0.03) against 0.32 GB on jochemnet (0.24 + 0.08), 5.4x; not 1.72 vs 0.32.

**Correction to "the commit tail, explained" (2026-10-07).** That note read the first timing lines of
`container.log` and concluded the multi-second FCU "was mostly never the state commit". Wrong for the
measured block. `collect_fcu.py` (article folder; copy in `tools/erigon-study/`) maps every
`Timings: Forkchoice` line to its test through benchmarkoor's per-test timestamps, all 266 tests
mapped (`/bench/erigon/fcu-DE.json`, sha256 `f7b558fe…96ce`):
- Every test's first FCU on jochemnet pays the CodeCache seed scan (`prune` 4 s untreated, 3 s
  rebuilt). Most tests have 2-3 FCUs, so the scan lands on a setup block, outside the measurement.
- The 36 ether-transfer tests have one FCU: their measured block is the container's first, so they
  carry the scan. That's E's transfer FCU (3.46 s: commit 0.70 s + prune 3 s).
- The measured block's `flush+commit` on untreated jochemnet (D): median 3 s (4 s on calls and absent
  accounts, 7 s on transfers). After the rebuild (E): 12-65 ms. So D's multi-second FCU *was* the
  state commit into the untreated database, and the rebuild fixed it. state-actor: 6 ms.

Consequence: the article's part 1 sentence "Erigon writes the block's state ... that call takes 3.4
to 11.4 s" stands. The G pairs (cache cleared) should move only the transfers' FCU, to about their
commit (0.7 s, state-actor 0.63 s).

**Predictions for the G pairs (written 2026-10-07 10:02 UTC, G1 running since 09:51).** Jochemnet's
TblCodeCache emptied (143,219 -> 0 rows), nothing else changed; smoke S2 2/2.
1. First-FCU `prune` on jochemnet drops from 3 s to under 10 ms on every test (state-actor: ~0.1 ms).
   If it doesn't, the 3 s isn't the seed scan, and the CodeCache reading is wrong.
2. The transfers' measured FCU drops from 3.46 s to 0.5-1.0 s (their commit, 0.70 s on E), and their
   whole-block ratio from 1.90 to 0.85-1.10.
3. Nothing else moves beyond pair noise: newPayload over a second 0.87-0.95; distinct-contract and
   jumpdest calls 0.53-0.67 (T1: their code reads never touch MDBX, so the cache isn't on the path).

**G series complete (2026-10-07 20:09 UTC):** rebuilt jochemnet with TblCodeCache emptied, against the
same state-actor store. `/bench/erigon/baseline-G.json` sha256 `0e592c40…b5e8`, FCU split
`/bench/erigon/fcu-G.json` sha256 `cb6bab69…12d`. All four suites green; 266 tests; 0 gas
mismatches; 110 over a second.

| over a second | G pair 1 | G pair 2 | E pair 1 / 2 |
|---|---|---|---|
| newPayload, all (110) | 0.927 | 0.919 | 0.901 / 0.924 |
| whole block, all | 0.942 | 0.946 | 0.947 / 0.967 |
| ether transfer, whole block | 1.032 | 1.034 | 1.90 / 1.83 |
| call, distinct contract | 0.641 | 0.650 | 0.561 / 0.549 |
| call, jumpdest scan | 0.633 | 0.648 | 0.640 / 0.638 |
| inside +-10% / sa floor / joc floor | 63 / 97 / 94 of 110 | | 50 / 95 / 97 |

Transfers' FCU 906 ms (state-actor 677 ms): commit 0.72 s, prune 0.4 ms. Under a second: floors
83 / 71 of 156; controls 1.34 / 1.42.

Predictions:
1. First-FCU prune under 10 ms on every test: **met** (max 2 ms; was 3 s). The 3 s was the seed scan.
2. Transfers' FCU 0.5-1.0 s and whole block 0.85-1.10: **met** (0.91 s; 1.03 / 1.03).
3. Nothing else moves: **missed on one row.** The distinct-contract call went 0.56 -> 0.64 in both
   pairs (+0.08 / +0.10; the pairs agree within 0.012). Pair 1 shows why: jochemnet's throughput on
   that row fell 9.1%, state-actor's 2.1%. The cache was serving some of those contracts' code; the
   pre-run deployed them, and `PutByHash` caches code on the deploy path. The jumpdest call didn't
   move (T1: its code came from the files). No other row moved more than 0.05 in both pairs.

So with jochemnet at the worst case on both counts (state in the bottom file, empty code cache):
over a second newPayload 0.92-0.93, whole block 0.94-0.95, and the only rows beyond the floor are
the two distinct-code calls at 0.63-0.65 (state-actor's dictionary-less code file, untested).

## Round 14 - the distinct-code rows (2026-10-07 22:1x UTC, predictions before results)

After G, the only rows over a second beyond the floor are calls into distinct maximum-size contracts:
`code-exec DIFF_MAX` 0.64 / 0.65 and `code-exec JUMPDEST` 0.63 / 0.65 (state-actor slower). Anon asked
for another inspection round, root cause first, then the article, then the state-actor fix.

**Read path (erigon 5f62f4ed).** `SharedDomains.getCode` (`db/state/execctx/domain_shared.go:1537`)
resolves addr -> codeHash, then tries the state cache and the `CodeStore` (memory 256 MB, then
`TblCodeCache`), both keyed by code hash, and only on a miss reads `CodeDomain` by address from the
files. A reused contract (one code hash) is read from disk once per process; every distinct contract
is read from the code `.kv` on every first call. That's why `SAME_MAX` (reused) sits at parity and
only the distinct rows don't. `Domain.dataReader` (`db/state/domain.go:1669`) reads values with the
domain's configured compression (`CompressVals` for code) whatever the file was written with; a file
without patterns decodes the same, so state-actor's raw file is read through the same `Getter.Next`.

**Hypothesis.** state-actor's code `.kv` stores every value raw (its seg port has no pattern path; 0 B
dictionary), so each 24,576-byte fixture contract costs its full 24 KB, 6-7 pages, per call. Erigon's
writer compresses code values against a pattern dictionary (`CompressVals`), and the fixtures are
24 KB of one filler byte, so on jochemnet the same contract is a few hundred bytes in one page. Before
the rebuild (D) jochemnet read these contracts raw from MDBX, which is why D sat at parity.

**Instruments.**
1. `compactlatest codespan` (new): walks a code `.kv` in key order through erigon's reader and records,
   per value, its encoded size and the 4 KB pages that reading the key and value touches; groups the
   24,576-byte values by first four bytes and the offset of the contract's own address; writes one
   line per such value (address, group, span, pages, value hash) for a cross-store join.
   `codespan.sh R14` runs it on jochemnet's promoted code file (staging copy) and state-actor's raw
   store copy. Read-only, no scratch involved.
2. `compactlatest recode-code` (new): `RecodeDomain` reuses `compactDomain` (DebugRangeLatest ->
   erigon's compressor with the domain's own `CompressCfg` and `CompressVals` -> `buildFileRange(0,1)`
   with accessors -> read-back hash). Only the encoding changes.

**Predictions** (written before codespan finished; scored below when results are in):
1. Every 24,576-byte value in both files is one of three fixture patterns; the distinct ones
   (`max_diff`, `unique_jumpdest`) carry their own address. For every address in both stores the value
   hashes are identical: same bytecode on both sides.
2. state-actor: each distinct fixture value is 24,576 B + a few bytes of framing on disk; reading key
   and value touches 7 pages (6-8). jochemnet: <= 512 B, 1-2 pages.
3. Pages per distinct fixture, state-actor / jochemnet, lands within +-30% of T1's code-page ratio
   (1.73 / 0.32 GB = 5.4x).
4. Recode: stream hash of the new file = codespan's of the old one; eth_getCode samples (background
   and fixture contracts) byte-identical before and after; smoke 2/2. The fixture values shrink to
   <= 512 B; the file shrinks to under 60% of 49.6 GB (background code is windows of real mainnet
   contracts, which Erigon's own notes put at ~4x on mainnet).
5. Trace T2 (both stores in their final state): state-actor's code-file pages on the jumpdest call
   within +-25% of jochemnet's.
6. H pairs (jochemnet unchanged since G; state-actor recoded): over a second the distinct-contract and
   jumpdest calls land in 0.90-1.10 in both pairs; no other row over a second moves more than 0.05 in
   both pairs against G; the all-rows median stays in 0.90-1.00. Rows beyond the floor: none.

**codespan R14 (2026-10-07 22:13 UTC, ~2 min per file)**, `/bench/erigon/compact/codespan-{joc,sa}-R14.{json,tsv}`.

| code .kv | file | keys | values raw -> on disk | pattern dict |
|---|---|---|---|---|
| jochemnet (Erigon's writer) | 16.03 GB | 68,023,550 | 45.42 GB -> 14.60 GB (3.1x) | 675,844 B |
| state-actor (its own writer) | 49.58 GB | 16,686,745 | 49.20 GB -> 49.23 GB | 0 B |

The 24,576-byte fixture contracts, by pattern (first four bytes @ offset of the contract's own address):

| pattern | test row | jochemnet: n, bytes on disk, pages (key + value) | state-actor: n, bytes, pages |
|---|---|---|---|
| `615fff56@44` (PUSH2 0x5fff JUMP) | jumpdest call | 135,000, 197-199 B, 1.054 | 150,000, 24,577 B, 7.005 |
| `00000000@12` (STOP, padding) | distinct-contract call | 100,000, 201-203 B, 1.055 | 150,000, 24,577 B, 7.005 |
| `005b5b5b@-1` (STOP, JUMPDESTs) | reused-contract call | 100,000, 173 B, 1.047 | 150,000, 24,577 B, 7.005 |

Every jochemnet fixture address exists on state-actor, and all 335,000 values hash identically
(state-actor has 15,000 / 50,000 / 50,000 more that no test reaches). The reused contracts share one
code hash on both stores, so the code cache serves all but the first call; the other two are a new
code hash per call.

Scored:
1. **Met for the fixtures** (identical bytes, address embedded as predicted). Not for "every
   24,576-byte value": jochemnet also holds 1,595 real mainnet contracts of exactly that size, raw or
   barely compressible (PNG data, Solidity), in 1,217 other groups.
2. **Met.** state-actor 24,577 B (one byte of framing), exactly 7 pages per value; jochemnet 197-203 B,
   1 page (2 on 5%).
3. **Met.** 7.005 / 1.054 = 6.6x pages per distinct contract, +23% on T1's 5.4x (code files plus
   their indexes); T1's code files alone were 1.705 / 0.236 = 7.2x.

The recode (`recode-sa.sh`) launched 22:15 UTC: restore, cmp against the raw copy, recode, old/new
eth_getCode answers, promote, smoke S3, traces T2 (both stores, the four plus a distinct-contract call),
then `chain-B.sh joc:H1 sa:H1 joc:H2 sa:H2`.

**The state-actor fix (2026-10-08 00:0x UTC)**, worktree `state-actor-wt-erigon-compress`, branch
`erigon-domain-compression`, commit `a379c85` on upstream main `005a19c` (local, not pushed).
- `snap.WriteDomain` encodes and re-reads each `.kv` through a `KVCodec` on `snap.Settings`. nil keeps
  state-actor's pure-Go seg (snap stays free of the erigontech/erigon import; untagged tests unchanged).
- New `internal/erigon/erigonseg` (`cgo_erigon_commitment`): Erigon's `seg.Compressor` with
  `statecfg.DomainCompressCfg` (one worker, deterministic) and each domain's `statecfg.Schema`
  compression (code values; storage and commitment keys; accounts raw); Erigon's `seg.Reader` for the
  accessor pass, yielding key offsets in Getter coordinates. `client/erigon/snapshot_cgo.go` injects it.
  The accessor builders are unchanged.
- Scope: the fix covers storage and commitment keys too, which state-actor also wrote raw. The traced
  storage write and transfer read within 3-6% of jochemnet's bytes, so those never left the band.
- Test `TestCodecErigonReadsBack` (tagged): three domains through `snap.Writer`, read back with only
  Erigon's code: its btindex finds every key at the schema's compression, and each word kind is
  compressed iff the schema says so. Built in the box's builder image (`Dockerfile.erigon --target
  builder`, erigon `14273f79a6`): passes; 5/5 mutations caught (key offset +1, code raw, storage
  CompressVals, storage raw, accounts CompressVals).
- Full image `localhost/sa-erigon:compress` building for `e2e-sa-compress.sh`: same small store from
  the published and the fixed image, same root, same code stream, same eth_getCode/getProof answers.

**State-actor fix, end to end (2026-10-08 00:10-00:13 UTC, `e2e-sa-compress.sh`)**: the baseline spec
with every count cut to 3,000, `--target-size=256MB --seed=42`, generated by the published image
(`main-005a19c`) and by `localhost/sa-erigon:compress` (branch `a379c85`):
- Same state root `0x91bdd69f…012e`; the code file's (key, value) stream hashes the same, 29,289 entries.
- Code `.kv` 251.3 MB -> 18.8 MB (dictionary 0 -> 125,228 B); the 9,000 test contracts 24,577 B ->
  196-229 B, ~94% in one page. Storage 117.1 -> 91.6 MB and commitment 178.1 -> 167.5 MB (keys
  compressed); accounts byte-for-byte the same size (raw in both).
- 9,494 answers through the benchmark's erigon (9,000 eth_getCode of test contracts, 430 EOA
  balance/nonce/getProof, 64 storage slots) byte-identical between the two stores; every test
  contract came back 24,576 bytes.
- Cost: generation 7 s -> 1 min 54 s on this store. Erigon's dictionary build runs one worker per
  domain (kept for determinism); domains are written concurrently. jochemnet's rebuild took
  2.3-3.6 h per domain at full size with the same settings, so expect a few hours on a 500 GB store.

**The recode (2026-10-07 22:22 -> 2026-10-08 04:31 UTC, `recode-sa.sh`).** Erigon's compressor ran 6 h 05 min
(one worker: collection 4 h 34 min, dictionary 2 min, encode 1 h 26 min). Results:
- State-actor's code `.kv` 49.58 GB -> 16.74 GB, dictionary 0 -> 2,869,359 B. Same (key, value) stream
  (sha256 `fb27d189…8e54`, 16,686,745 entries) before and after, checked on the staged file and again
  on the swapped one.
- Test contracts on disk: distinct 177-180 B, jumpdest 173-176 B, reused 149 B; 1.04-1.05 pages per
  read (jochemnet's own file: 201-203 / 197-199 / 173 B, 1.05).
- 4,837 eth_getCode answers (3,337 every-5,000th key, 1,500 test contracts) byte-identical on the old
  and new layouts. Promoted; smoke S3 2/2, 0 validation failures.
- `/bench/erigon/compact/codespan-sa-recoded.json` sha256 `43b1cad2…02ce`, `recode-sa-report.json`
  `4d43da2e…aeb0`.

Prediction 4: **met** (stream hash, answers, smoke; test contracts <= 512 B; file 33.8% of the old,
under 60%). T2 traces running, then the H pairs (~11 h).

**Round 14 results (2026-10-08).**
- T2 traces (`/bench/erigon/step0-T2.json` sha256 `9043f656…c56e`): both stores read only files; every
  per-test newPayload total within 6.7% (account read 0.444/0.472 GB, jumpdest call 0.762/0.813,
  distinct call 0.760/0.811, storage write 0.112/0.115, transfer 0.620/0.644, joc/sa). Code files on
  the jumpdest call: 0.237 vs 0.317 GB (was 5x in T1). Prediction 5: **met**.
- H pairs (`/bench/erigon/baseline-H.json` sha256 `ee145b9c…35f3`, 266 tests, 0 gas mismatches, four
  fresh runs): over a second, newPayload **0.971 / 0.960**, in band **93 / 88** of 110; replica floors
  90 (sa) and 94 (joc). Whole block 0.991 / 0.981, 87 in band. Distinct-contract call **0.979 / 0.957**
  (G 0.641 / 0.650), jumpdest call **0.964 / 0.956** (G 0.633 / 0.648). Rows over a second outside
  the band in both pairs: D 9, E 3, G 2, **H 0**.
- Prediction 6: **partly met.** The code calls landed at 0.96-0.98, inside 0.90-1.10. But two other
  rows moved more than 0.05 in both pairs: account reads (BALANCE/EXTCODEHASH) of distinct contracts
  1.007 -> 0.933 and of jumpdest contracts 0.867 -> 0.951, opposite directions. They read no code;
  their four-test replica floors hold 1-3 of 4 within ±10%, so the move is inside their noise, not a
  re-encode effect. The prediction's "no other row moving" was too strict for four-test rows.
- Root cause of the code-call gap, closed: state-actor's Erigon `.kv` writer has no dictionary path,
  so a 24,576-byte test contract costs 7 pages per uncached code read where Erigon's own writer costs
  1. Re-encoding the same content with Erigon's compressor removes the gap.
- Side finding: jochemnet's 1,595 real (non-test) 24,576-byte contracts take a median 24,578 B,
  7 pages, in its compressed file. The test contracts compress ~120x because they're one repeated
  opcode, so the distinct-code rows price a cheap code read. Fixture realism, not a store issue
  (same as the Besu ledger's 0.011 deflate ratio on mainnet).

## Round 15 - the two residuals (2026-10-08, predictions before any run)

Plan: `docs/superpowers/plans/2026-10-08-erigon-round-15-residuals.md`. Article before the round:
`19bee3f` (adds `fig_steps`, `fig_residuals`, `fig_nostate`).

**Residuals after H.** Over a second state-actor leans 3-4% slow (0.971 / 0.960 vs floor centres
0.99 / 1.00; 15/17 and 19/22 misses low; 2-7% more pages on every T2 test). Under a second the 98
no-state tests (controls, warm queries, one-slot reloads) run 1.20-1.42x faster on state-actor, floors
centred 0.96-1.02; jochemnet ~16 ms more per block (median), 1.20-1.30 untreated. The 4-test account
rows are floor-limited (state-actor twice: medians 0.86-1.10, 8/16 inside).

**Evidence before running anything:** benchmarkoor's read counter, controls: jochemnet 5.1 MB per
newPayload, state-actor 0.08 MB (both gas levels; 3.8 MB untreated). One control in joc-H1 / sa-H1:
`Handling new payload` logged 30 ms / 3 ms after the request; execution 29.8 / 39.9 ms. Source:
`getQuickPayloadStatusIfPossible` -> `GetHeaderByHash(new hash)` -> `BlockReader.HeaderByHash`
(`block_reader.go:568`) sweeps every headers segment on an MDBX miss; jochemnet has 65 (136 MB of
.idx), state-actor 0.

**Predictions:**
1. Phase split over H's logs: on the no-state tests, jochemnet's before-handling time exceeds
   state-actor's by 10-30 ms at the median in both pairs, and that difference is >= 80% of their
   newPayload gap. Over a second the before-handling difference is the same 10-30 ms, and
   state-actor's execution phase is 2-6% longer than jochemnet's at the median.
2. Probe: a cold `eth_getBlockByHash(random hash)` costs 10-40 ms on jochemnet and < 3 ms on
   state-actor; warm < 2 ms on both; jochemnet's cold lookup reads >= 200 pages, >= 80% of them from
   headers `.idx`/`.seg`.
3. Trace T3: jochemnet's before-handling slice of each no-state newPayload reads >= 200 pages, >= 80%
   from headers files; state-actor's < 50 pages.
4. e2e cross-check: re-encoded storage and commitment of the small `old` store hash like the fixed
   generator's `new` files; byte-identical (55%).
5. Recode (option B): storage .kv 181 -> 120-175 GB, commitment 282 -> 230-280 GB; stream hashes
   equal; sample answers identical; smoke 2/2.
6. T4: state-actor's extra pages on the storage write and the transfer fall from +2.4% / +3.9% to
   <= +1.5%; the account read stays at +5-7%.
7. I pairs: the over-a-second median rises 0.005-0.02 in both pairs; transfers and storage slot move
   toward 1.00; no other row over a second moves by more than its pair-to-pair spread; the
   sub-second no-state offset stays within 5 ms of 16 ms.

**Round 15, point 1 results (2026-10-09; scored 2026-10-11).** Anon approved the plan, option B and
the deletions (2026-10-09).
- **Phase split** (`collect_np_phases.py` over H's benchmarkoor logs, `/bench/erigon/np-phases-H.json`
  sha256 `eea86cd3…528b`; every test in all four runs has both phases). The log's "Running setup
  step" starts the next test's own setup block, so a step's window ends there; the first version
  mixed the setup block into the previous test and was discarded. Per test: *before* = request start
  to `[NewPayload] Handling new payload`; *exec* = `[5/5 Execution] parallel done in=`; *rest* = the
  remainder (1.5-7 ms).
  - No-state tests (98): before 16.2 ms on jochemnet, 1.7-1.8 ms on state-actor, paired difference
    14.4 ms in both pairs; total newPayload difference 16.1 / 16.8 ms, so 86-89% of it is before
    Erigon starts on the block. Execution: state-actor 7% *shorter* (sa/joc 0.931 / 0.930).
  - Over a second (110): the before phase is 200-370 ms on both (decoding and checking the payload;
    shared CPU work), jochemnet's 17.4 / 16.9 ms longer (paired). Execution: state-actor 6.4% / 6.8%
    longer (sa/joc 1.064 / 1.068). Ratios without the before phase: over a second 0.940 / 0.941
    (newPayload 0.971 / 0.960); execution only 0.940 / 0.936. Under a second 1.001 / 1.042
    (newPayload 1.215 / 1.260); no-state rows 0.94-1.05 (newPayload 1.20-1.42).
  - Prediction 1: **mostly met** (before difference 14.4 ms no-state, 17 ms over a second, 86-89%
    of the no-state gap); its last clause **missed narrowly**: state-actor's execution is 6.4-6.8%
    longer over a second, not 2-6%. So the over-a-second lean is larger in execution than the
    headline shows: the shared ~250 ms before phase dilutes it and jochemnet's +17 ms offsets it.
- **Probe** (`probe-hash.sh`, 20 random unknown hashes per store, `eth_getBlockByHash`, which reaches
  `BlockReader.HeaderNumber` -> `HeaderByHash`; `/bench/erigon/probe-hash.json` sha256
  `6a095508…bf7b`): jochemnet cold 18.7 ms and 0.64 MB read (block files 506 KB, MDBX 170 KB, medians),
  warm 1.08 ms and nothing read; state-actor cold 1.24 ms, warm 1.04 ms, nothing read either way.
  Prediction 2: **partly met** (cold 10-40 / < 3 ms, warm < 2 ms: met; >= 200 pages and >= 80% from
  headers files: missed, ~155 pages, ~79% from block files with MDBX the rest; per-file attribution
  pending).
- First probe attempts failed on script bugs (jochemnet's datadir path; a scratch left mounted after a
  failure made the next arm's dm-device check fail); fixed (per-arm datadir, unmount on every exit).
- Trace T3 ran on both stores (6/6 passed each, 2026-10-09 15:14-15:21 UTC); collection pending:
  the bench box's SSH agent (YubiKey via gpg-agent) refused to sign on 2026-10-11.
