# Reth state-DB study: verify the gap explanations, collect the article's data

Ledger: `docs/superpowers/specs/2026-10-03-reth-study-ledger.md`. Host: stateless-bloatnet-benchmarks,
`/root/bench/reth`. Untracked, like the ledger.

## Goal

Every explanation the article will give for the state-actor vs jochemnet gap either rests on an
intervention or is checked by one, with a replica floor beside every ratio. All quoted numbers come
from one collector into one `report_data.json`. Claims already settled by an intervention get data
collection only. Claims that are inference get the cheapest experiment that could falsify them.

**Outcome (2026-10-06, run 15:18-20:55 CEST; gates B and C approved).** Every phase ran; all 14
claims are supported by the final collection (`articles-wt-reth-article/reth-state-db-divergence/
data/report_data.json`). Two claims were reworded by their own checks before the run:
- C4: jochemnet's code is contiguous on disk but read in random order (A1), not in access order.
- C7: the cause is out-of-key-order inserts. libmdbx packs sorted `Put` fully (D4 and the toy test).
Two predictions missed:
- Repacked account rows reached parity with jochemnet as shipped, not ~0.91.
- Ether stayed at sr/jh 0.93, held back by the trie tables (C10).
The claim -> evidence table is in the ledger's "Verification campaign" section.

## Where the study stands (2026-10-06)

- DIO baseline, 266 tests, two independent pairs, class from dj1. Over a second (97 tests):
  **0.9998 / 1.0013**, 76/97 inside ±10%, floors 97/97. Buffered it was 0.842 / 0.840.
- Under a second, the sequential-address family is still 0.11-0.16. Over a second, MINIMAL/SAME_MAX
  account rows are 0.81-0.90 and CALL EXISTING_EOA is 0.78.
- The experiment image (acf6e17 source build, read switch `RETH_FORCE_HASHED_READS`) matches the
  published image under DIO: xjc/dj median 1.001, 59/66 inside ±10% (dj floor 58/66).

## Claim register

Status: **V** = settled by an intervention, needs collection only. **I** = inference or single run,
needs the listed check.

| id | claim the article makes | evidence now | status | check |
|---|---|---|---|---|
| C1 | Buffered loop devices under the schelk scratches dominated the baseline. With loop direct-io the same tests run 2-8x faster with the same mdbx page counts; families with no state reads do not move. | buffered vs DIO, same binary and fixtures; forensic traces; DIO baseline pairs | V | collect |
| C2 | Mechanism: a buffered loop serves backing reads one at a time (synchronous reads in its worker); DIO submits them async. | arithmetic only (~79 µs a page) | I | D1, E2.1, E2.2 |
| C3 | The large-code gap (0.67-0.77 buffered) was backing-file readahead on state-actor's isolated 7-page code runs. | backing/mdbx pages 3.0x vs 1.06x; 7-page runs became 31-page runs; parity under DIO | V effect, I mechanism | D1, E2.3 (gate B) |
| C4 | jochemnet's accessed code is contiguous in access order (deployment order); state-actor's is scattered (writer order). | run-length histograms | I | A1, D2 |
| C5 | The sequential-address family is reth's v1 (Plain*, address keys) vs v2 (Hashed*, keccak keys) read path meeting EEST's sequential addresses. | read switch jh/jc (buffered and DIO); per-table pages | V, one DIO run | E1.1, D3 |
| C6 | The account-row residual is the read path (~0.91) times state-actor's tree shape (~0.94: HashedAccounts height 6 vs 5, fill 0.50). | one decomposition; "shape → time" inferred | I | E1.1, A2, E3 (gate C) |
| C7 | The half fill comes from state-actor writing HashedAccounts in sorted order with `tx.Put`, not `cursor.Append`, so pages split in the middle. | comment on state-actor `main`: "Uses tx.Put (not cursor.Append)" | I | D2, D4, E3 |
| C8 | Ether transfers reach parity (1.017) because two effects cancel: hashed reads speed jochemnet up (jh/jc 1.14) and state-actor's shape costs ~12% (s/jh 0.878). | single runs | I | E1.2, E1.3 |
| C9 | Hashed reads speed jochemnet up on transfers and CALL-to-contract because v1 reads Plain* for execution and Hashed* for the state root, touching two tables' pages. | hypothesis | I | E1.3 |
| C10 | CALL EXISTING_EOA keeps 0.78 (s/jh 0.87 under DIO). Unexplained; candidate: state-actor's AccountsTrie is 6x larger (161.7M vs 26.9M entries). | none | I | E1.3 |
| C11 | state-actor is faster on sload/sstore_bloated on the same read path (s/jh 1.20-1.25): its storage dup subtree has fewer branch pages (31k vs 42.5k). | one trace | I | E1.1, E1.3 |
| C12 | Method: source build equals the published image; benchmarkoor's disk counters (summed over the device stack) are not quoted; page-cache traces are the I/O truth. | measured | V | collect |
| C13 | DIO baseline headline (above). | independent pairs, floors | V | collect |
| C14 | Earlier studies in the series also ran buffered loops. | Besu scripts on this host attach with `losetup --find --show` and no `--direct-io` | I | D5 |

## Phase 0: desk checks (no box time; runs in parallel with phase 1)

Each check ends as a ledger citation (repo, commit, file:line). A mismatch rewrites the claim before
any article text.
- **D1** Linux v6.8 `drivers/block/loop.c`: `lo_rw_aio` only when `use_dio`; buffered reads go
  through `lo_read_simple` synchronously inside the per-blkcg worker. `mm/readahead.c`:
  `ra_pages == 0` reads only the requested pages, and `ra_pages` is copied into the file at open,
  which is why E2.3 must reattach the loops.
- **D2** state-actor @005a19c `client/reth`: how `data_writer_cgo.go` inserts HashedAccounts (Put
  vs Append, the caller's ordering, e.g. a stream sort by hashed key), and the insert order of
  `bytecode_writer_cgo.go`.
- **D3** EEST @d9ad55b3 (`~/eest-d9ad55b3` on the host): `SequentialAddressSource`, the bloated-slot
  walk. reth @acf6e17: `providers/state/latest.rs` read paths; `bal_prewarm_pool::warm_account`
  reads code for every BAL account.
- **D4** The libmdbx version reth acf6e17 vendors: the split point on a non-append insert at the
  right edge vs with `MDBX_APPEND`.
- **D5** Loop audit: every `losetup` on this host (scripts, root history) for the geth and Besu
  studies. The Nethermind/Erigon box (157.180.2.180) needs Anon's key touch: read
  `/sys/block/loop*/loop/dio` and that box's attach scripts.

## Phase 1: replicas and mapped traces (DIO, `devnet7-hashedreads`, ~3 h, tmux `reth-v1`)

| step | runs | tests | purpose |
|---|---|---|---|
| 1.1 | xs2, xjh2, xjc2 | 66 (160M set) | second independent pair for s/jh, jh/jc, s/j; floors xs2/xs, xjh2/xjh, xjc2/xjc |
| 1.2 | xse2, xjhe2, xjce2 | 36 common ether (filter carries `value_(160\|240)M`) | the same for the ether family |
| 1.3 | t2jc, t2jh, t2s (`trace-run.sh` + `pcwin.py` + `mdbxmap.py`) | T2, 14 tests at 160M | per-table pages for C6 and C8-C11 |

T2 (value_sent_0 and overhead_baseline_False unless noted): BALANCE MINIMAL, SAME_MAX, EXISTING_EOA,
DIFF_MAX; CALL EXISTING_EOA v0 and v1; CALL NON_EXISTING; CALL MINIMAL; sload_bloated
existing_slots_False; one sstore_bloated; ether transfers to contract, existent, nonexistent and
self (amount 0). `mdbxmap.py` gets the table list explicitly: PlainAccountState HashedAccounts
Bytecodes AccountsTrie PlainStorageState HashedStorages StoragesTrie.

Predictions and falsifiers:
- 1.1/1.2: each floor at least 58/66 (36: at least 32/36) inside ±10%; pair-B cell medians within
  ±0.03 of pair A. A miss reopens the single-run numbers in the ledger.
- C9: on transfers and CALL-to-contract, t2jc touches PlainAccountState leaves (about one per access)
  *plus* HashedAccounts pages; t2jh touches HashedAccounts only. Falsified if t2jc pages <= t2jh.
- C10: CALL EOA's extra pages on t2s vs t2jh sit in AccountsTrie or HashedAccounts branch pages.
  If pages are equal the residual is CPU; that needs a profiler, which is outside this plan.
- C11: t2s sload pages below t2jh's, in dup-subtree branch pages.

Analyses on phase-1 data (local, no box time):
- **A1 (C4)**: Spearman ρ between first-touch time and page index for `large` pages in the
  DIFF_MAX window of the existing fj/fjh/fs traces. Prediction: J > 0.9, S ≈ 0.
- **A2 (C6)**: µs per mdbx page (time from the untraced replicas, pages from the T2 traces) on each
  arm. Prediction: equal across arms within the floor, so the page ratio predicts the time ratio
  within ±3%. Falsified if state-actor pays more per page.

## Phase 2: the rig mechanism (~45 min, plus 25 min under gate B)

- **E2.1 (C2) loop microbenchmark.** Uses a throwaway loop, not schelk's. Fill a 64 GiB file on md2
  (written, not fallocated: unwritten extents read as zeros without I/O). Random 4 KiB reads with
  fio: `psync` numjobs 1/4/16/64 and `libaio` iodepth 1/16/64. Targets: the loop buffered, the loop
  with DIO, and the raw file with O_DIRECT. Drop caches before each buffered point; detach and delete
  afterwards. Prediction: buffered IOPS stay flat (≈ 1/latency, ~12-13k) as concurrency grows, while
  loop-DIO and raw scale at least 10x by 16 jobs.
- **E2.2 (C2) in situ.** BALANCE MINIMAL and EXISTING_EOA on J with hashed reads, buffered then DIO.
  Record `iostat -x -y 1` on nvme0n1, nvme1n1, md2 and loop1, and `/sys/block/loop1/inflight` every
  100 ms. Prediction: NVMe queue depth about 1 at ~12k r/s buffered; far above 1 under DIO.
- **E2.3 (C3) backing readahead off [gate B].** Buffered loops. With no scratch mapped: detach loop1
  and loop3, set `blockdev --setra 0 /dev/md2`, reattach the same devices to the same images, and set
  md2 back to 256 right away (seconds; the loops keep ra 0 from their open). Check the ro flags and
  dio=0. Trace the forensic set as ra-s and ra-jh, then reattach normally. Prediction: on state-actor
  DIFF_MAX, backing/mdbx pages fall from 3.0 to ~1.0 and DIFF_MAX s/jh rises to MINIMAL's ~0.94, while
  times stay buffered-slow. Falsified if the ratio stays near 3.

## Phase 3: tree-fill intervention [gate C] (~7 h, overnight)

1. **Backup.** `cp --sparse=always` the state-actor virgin (516 GB allocated; md3 has 4.5 TB free).
   Check: allocated size and sha256 of the first and last GiB. Last resort: regenerate (8 h 41 min).
2. **Repack tool.** Go with mdbx-go, the library state-actor's writer uses, built in a golang
   container on the host. Order:
   1. sha256 over HashedAccounts (k, v) plus the entry count.
   2. `cursor.Append` into a temp table, 1M entries per transaction.
   3. Clear HashedAccounts.
   4. Append back in key order.
   5. Drop the temp table.
   6. Hash again; it must equal step 1.
   7. Print height, branch and leaf pages, and fill before and after.
   Rejected: `mdbx_copy -c`, which renumbers pages without merging their contents. Space: the
   repacked table is ~25 GB, and the scratch filesystem has ~150 GB free.
3. **Gate.** Boot the repacked scratch: head 0, genesis 0x0cb03528…, stateRoot 0x48d611bb…, idle-write
   check, smoke 3/3.
4. **Promote**, recording the GB copied and the time taken.
5. **Runs** (DIO, `devnet7-hashedreads`): xsr and xsr2 (66 tests), xser and xser2 (ether 36),
   t2sr (T2 trace).
6. **Predictions.**
   - HashedAccounts leaf fill 0.50 -> at least 0.9, height possibly 6 -> 5.
   - BALANCE MINIMAL pages 100.9k -> at most 94k.
   - s/jh: account rows 0.94 -> ~1.0; the sequential family 0.93 -> ~1.0; ether 0.878 -> ~1.0.
   - s/j: MINIMAL/SAME_MAX 0.86 -> ~0.91, so the read path alone remains.
   - Falsified if fill rises and times don't move.
7. **Afterwards** (Anon's call, not automatic): keep the repacked store as a third arm, or copy the
   backup back and re-clone the scratch (`schelk full-recover`, ~1 h).

## Phase 4: data collection for the article (~2 h, local)

- Article work tree `articles-wt-reth-article` (branch `reth-state-db-article` from `origin/main`),
  folder `reth-state-db-divergence/`, as for Erigon. `collect_reth.py` lives only there.
- `collect_reth.py extract` runs on the host (`tsh ssh … 'sudo -n python3 - extract' <
  collect_reth.py`) over a fixed run registry. It writes `data/host-extract.json`:
  - per run: id, arm, image and digest, config sha256, filter, start and end, loop dio state,
    pass/fail/INVALID counts;
  - per test: key, gas, newPayload ns, FCU ns, class from dj1, category;
  - per trace window: step seconds, mdbx pages by table and kind, backing pages, run-length
    histogram;
  - fio JSON, iostat summaries, repack stats.
  Raw traces stay on the host; `data/manifest.json` records their sizes and sha256.
- `collect_reth.py build` writes `data/report_data.json`: every number the article quotes, keyed
  by claim id, each with value, floor, n, source runs, prediction and verdict.
- The build fails unless: pass counts match the registry; there are 0 INVALID/SYNCING; each run's
  DIO state matches its registry entry; classes come from dj1; every quoted ratio has its replica
  floor; and every claim has a verdict.
- Run registry, reused: j1 s1 j2 s2, jc jh, fj fjh fs, xfs xfjh, xs xjh xjc, xse xjhe xjce, dj1 ds1
  dj2 ds2, plus `naccess.py` (accesses per test) and the db stats in `probe/`. New: phases 1-3.
- Per phase: a ledger section, the project file's state, the vault session log. At the end, a
  claim -> evidence table in the ledger, which becomes the article's method section.

## Run hygiene

- Every driver runs in a root tmux. One benchmark at a time (schelk holds a global lock).
- Set DIO only through the ioctl, with no scratch mapped. An EXIT trap restores dio=0. The driver
  prints the dio state after every run and aborts if it doesn't match.
- Before trusting a run, check the "Discovered EEST fixtures count=N" line; abort if N is not the
  expected count (the 198-test ether filter of 2026-10-05).
- Stop runs by PID. Never use `pkill -f` with a pattern that matches the driver's own command line.
- Teleport tokens last 12 h, so long phases must not depend on the session; results are read after
  a `tsh login`.

## Not doing

- Converting jochemnet to v2 or state-actor to v1: the read switch stands in for it, and
  state-actor's writer can't produce v1.
- Repacking HashedStorages or AccountsTrie.
- CPU profiling. If C10 turns out to be CPU, it stays an open question.
- 240M variants of the interventions.
- Re-measuring earlier clients (D5 audits their loops only).
- Changing benchmarkoor. A DIO switch for schelk loops is an upstream suggestion, noted only.

## Decisions for Anon

- **A.** Approve phases 0, 1, 2.1, 2.2 and 4: no store changes, ~4 h of box time.
- **B (gate B).** E2.3: reattach the scratch loops with backing readahead off (md2's readahead
  changes for seconds). Recommended: it is the only clean test of C3's mechanism.
- **C (gate C).** Phase 3: back up the state-actor virgin, repack HashedAccounts, promote; afterwards
  keep or restore. Recommended: it is the only intervention behind C6 and C7.
- **D (outside this plan).** What D5's answer means for the published Nethermind and Besu articles.

## Order and timing

Day 1: phase 0 (agent) runs alongside phase 1 (box, ~3 h); then phase 2 (~1 h with gate B). Phase 1
goes first because it changes nothing and its floors are needed by every later comparison. Phase 2
comes next because E2.3 detaches the loops. Phase 3 runs overnight under gate C (backup, repack,
runs). Day 2: phase 4.
