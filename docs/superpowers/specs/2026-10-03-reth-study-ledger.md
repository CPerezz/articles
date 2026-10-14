# Reth state-DB study ledger

Fourth client in the series (geth, Besu, Nethermind before it). Same question: how far apart do
the jochemnet snapshot and a state-actor store run on the EEST bloatnet suite, and why. Method
rules carried over from the earlier studies: replica floor beside every comparison, split at one
second of measured time with class fixed from the first jochemnet run, pairs that share no run,
one named medium, and a boot-time rewrite check on every store.

## Round 0 - setup and gates (2026-10-03)

Plan from a proposer/critic debate (one each), adjudicated; executed as written except where noted.

**Host.** stateless-bloatnet-benchmarks (Teleport), AMD EPYC 9454P 48c/96t, 125 GB RAM.
md2 = 2x Samsung MZQL23T8 NVMe RAID1 (3.5 TB, the root filesystem); md3 = 2x Seagate 16 TB RAID0
(29 TB, /data). Freed for the study: the Besu schelk volumes on md2 (besu-joc virgin+scratch,
besu-sa4 virgin+scratch) and /sa-smoke. Nothing on md3 was deleted; /data/eth/*/mainnet and
perf-devnet-2 belong to others and were not touched.

**Medium.** Both scratches on md2 NVMe (every benchmark read), both virgins on md3 HDD (read only
by `schelk recover`/`restore`, written by `promote`). A third configuration in the series (Besu:
both on md2; geth: HDD overlays), so a reth ratio is not divisible against the earlier clients'
numbers without that caveat. Two schelk instances, two ramdisks (`brd rd_nr=2 rd_size=6 GiB`):

| instance | scratch | virgin | ramdisk | mount | dm-era |
|---|---|---|---|---|---|
| reth-joc | /schelk-vols/reth-joc-scratch.img 1900G (loop1) | /data/schelk-vols/reth-joc-virgin.img (loop2) | ram0 | /schelk-joc | reth_joc_era |
| reth-sa | /schelk-vols/reth-sa-scratch.img 711G (loop3) | /data/schelk-vols/reth-sa-virgin.img (loop0) | ram1 | /schelk-sa | reth_sa_era |

Gotcha: loop0, loop1 and loop3 kept a read-only flag from the Besu schelk virgins after detach
(`/sys/block/loopN/ro=1`), so `mkfs.ext4` on a fresh attach failed with "Operation not permitted
while setting up superblock". `blockdev --setrw` after attaching fixes it.

**Image.** `ethpandaops/reth:glamsterdam-devnet-7` pinned by digest
`sha256:dc8936043e0c327aae5aa18adb804c48ca290700ed1ca40ba589783c4d042a48` (reth 2.4.1-dev,
acf6e17, built 2026-08-11), the same devnet as the Nethermind and Besu runs and the jochemnet
payload release. It opens both stores; devnet-8 (2.5.2-dev, 7fddea4) was pulled but not needed.
benchmarkoor's default reth command (both arms identical): `node --full
--engine.disable-precompile-cache --debug.skip-genesis-validation` plus RPC/auth flags.

**Jochemnet store.** snapshots.ethpandaops.io/jochemnet/reth/24402727/snapshot.tar.zst,
1,020,907,172,580 bytes, 8-stream aria2c to md3 at ~103 MiB/s (2 h 37 m), exact-size checked.
Extracted into the scratch in 79.5 min: db/ 925 GB (MDBX, database.version 2), static_files/
558 GB (147 header, 102 receipt, 54 transaction segments; no sender segments, pruned), rocksdb/
5 MB, reth.toml with a full-node prune config (receipts and history distance 10064, bodies before
the merge). Logged storage settings: `storage_v2: false`, `pruning_mode="full"`. The tarball's
`_snapshot_eth_getBlockByNumber.json` says 24,350,000; the geth jochemnet snapshot carries the
identical file and the true head is 24,402,727 (hash 0x488010e5...), confirmed on boot. Promote
#1 copied 1,512.86 GB to the HDD virgin in 97 min.

**Pre-run (G5).** The 7,736-block bundle (24,402,728..24,410,463) replayed VALID in 17 min, then
benchmarkoor promoted (44 min). The restarted client sat at 24,410,457: six blocks short, because
reth persists in the background and SIGTERM after the 20 s settle did not flush them; the first
smoke test then got SYNCING. Fixed by resuming the replay with
`--engine.persistence-threshold=0 --engine.memory-block-buffer-target=0` on the pre-run config
only (6 blocks, promote 5 min). Head after: 24,410,463, hash 0x4525339a..., matching the bundle's
final forkchoice. Smoke test on the promoted store VALID. The baseline runs use the default
command, without those flags.

**State-actor store.** `ghcr.io/ethereum/state-actor-reth:main-005a19c` (the generator revision
of Nethermind v2: #139 and #141), the Nethermind v2 invocation with `--client=reth`: spec sha256
74dea7d1..., `--seed=42 --fork=osaka --gas-limit=1000000000 --target-size=350GB`. 8 h 41 min
(Nethermind: 4 h 21 min): EOAs at 27-59 k/s, contracts at ~560/s once warm, account trie at
413 k/s. 545 GB, 33 files: db/ 509 GB, rocksdb/ 228 KB, static_files/ 64 KB, chainspec.json.
State root 0x48d611bb..., identical to Nethermind v2, so the cross-client invariance holds and the
Nethermind-filled fixtures (sa-v2-full, 456 tests, 160M/240M) are reused. reth's generator does
not log the genesis hash; it is checked at boot instead.

**Common set (G7).** jochemnet 266 tests at 160M+240M, state-actor 456; all 266 jochemnet tests
are in the state-actor set (the other 190 are families the jochemnet payloads don't carry). Both
arms run with one filter that selects exactly those 266 (cfg/common-filter.txt on the host).

**Jochemnet boot (G2/G4).** RPC ready in 2 s. Promoted store, cold caches: 12.9 MB read and
1.7 MB written while booting, 0 MB read and 0.4 MB written in 60 idle seconds. No rewrite at boot.

**State-actor adoption.** The store was copied into an ext4 made on the HDD virgin (39 min,
545,461,073,814 bytes and 33 files verified), adopted with `schelk init-from` (scratch clone
55 min), never booted before. Boot gate: RPC ready in 3 s, head 0, genesis hash
0x0cb035288eb4..., the Nethermind v2 genesis exactly.

**A filesystem artifact caught at the gate.** That boot showed 75.8 MB written while booting and
1,732.8 MB in 60 idle seconds on the state-actor scratch, with reth's own `/proc/<pid>/io`
showing 0 MB written. It was ext4 lazy inode-table init on the fresh filesystem: every
`schelk restore` puts the virgin's un-zeroed group descriptors back, so it would have restarted
on every per-test mount and written in the background through every state-actor measurement
(and, while mounted, through jochemnet's). Fixed by mounting once with `init_itable=0`, letting
it finish (6,847 MB in under a minute), and promoting (6.38 GB). After the fix a fresh
restore+mount writes 0 MB in 60 s on both scratches; the jochemnet scratch never had the problem
(its virgin was created and promoted by schelk over hours of mounted time). Rule for the series:
check idle writes on a freshly mounted scratch, not only a booted client.

**Smoke (G6).** Three tests per arm at 160M (the sload-bloated test and the BALANCE
existing-EOA pair), 3/3 passed on each, no INVALID or SYNCING.

**Baseline launched.** `baseline2.sh` on the host: J1, S1, J2, S2 over the 266 common tests,
default reth command, a 1 s sampler of both scratch loops' `/sys/block/*/stat`
(`logs/io-1s.log`), and `reth_reduce.py` at the end (`results/baseline.json`: per class, pair A
and pair B, each store against itself; class fixed from J1). J1 started 2026-10-03 11:31 CEST. Pace: 12 tests in the first
6.5 min (~33 s per test, restore and restart included), so about 2.4 h per run and the four
runs done around 21:30 CEST.

**J1 restarted with a SIGKILL stop (15:46 CEST).** The first J1 reached 153/266 in 4 h: the tests
take about a second, but ten `schelk restore`s took 9-20 min each, all after CALL value_sent_1
tests. The 1 s sampler shows why: 6 MB written to the scratch during setup and measured block, then
~590 MB while the container stopped (reth flushes its in-memory blocks on SIGTERM), scattered
across MDBX, so the next restore reads ~150k random 64 KiB blocks from the HDD virgin. The flush
happens after the measured block and every test starts from a restored store, so it never touched
a measurement; it only cost time. Fix: `docker.io/benchlocal/reth:devnet7-sigkill`, the devnet-7
image by digest plus `STOPSIGNAL SIGKILL` (identical layers). Same heavy test: restore 1,189 s ->
12 s, throughput 13.37 -> 13.45 MGas/s. The partial run is kept as `results/j1-graceful-partial`;
all four baseline runs use the new image.

## Attribution dive (2026-10-04)

**Gas and access parity.** Same gas per test on both arms (to the unit), and the same number of
accessed accounts: 51,430 contracts or 52,237 EOA/absent addresses per BALANCE test at 160M
(counted from the calldata index ranges of the payload transactions). Every gap below is per
equal work.

**The two stores are different reth layouts.** `reth db settings get`: jochemnet has no
settings row (legacy v1: plain state tables keyed by address, used for reads; hashed tables kept
for the trie); state-actor is `storage_v2: true` (no plain tables; reads go to
HashedAccounts/HashedStorages keyed by keccak). The state-actor writer only produces v2.
Table stats (entries; leaf pages; branch pages):

| table | jochemnet | state-actor |
|---|---|---|
| PlainAccountState | 354.8M; 5.48M; 55k | empty |
| HashedAccounts | 354.8M; 8.19M; 123k | 430.7M; 11.70M; 243k |
| HashedStorages | 1.82B; 31.5M; 931k | 2.21B; 71.6M; 7.34M |
| AccountsTrie | 26.9M; 2.08M | 161.7M; 6.07M |
| StoragesTrie | 157M; 10.4M | 778M; 26.7M |
| Bytecodes | 2.44M codes, 22.6 GiB | 712k codes, 10 GiB |
| freelist | 246.8 GiB | 0.8 MiB |

**The ~50x family is sequential keys.** EEST's `SequentialAddressSource` walks EXISTING_EOA from
0x1000+i and NON_EXISTING_ACCOUNT from keccak("random")+i; sload/sstore_bloated walk consecutive
slots. On v1 those keys are neighbours in PlainAccountState/PlainStorageState, so 52k lookups
touch a few leaf pages; on v2 each key is hashed to a random leaf. Page-cache trace of the
measured block (bpftrace on `mm_filemap_add_to_page_cache`, mdbx.dat inode), jochemnet:
NON_EXISTING 347 pages, EXISTING_EOA 1,284, sload_bloated 170 -- for 52k accesses.

**benchmarkoor's disk_read counters are ~4x inflated here.** cgroup io.stat summed over every
device in the stack (dm-era, loop, md2, nvme). Page-cache truth for jochemnet BALANCE at 160M:
MINIMAL 84,488 pages = 1.64 per access (the B-tree model for PlainAccountState gives 1.65);
DIFF_MAX 473,960 = 9.2 per access (account 1.64 + 24 KiB code with jump table = ~7 overflow
pages + its leaf). Backing-file inserts equal mdbx inserts (+6%): no readahead amplification.
Reth reads code for every BAL account (`bal_prewarm_pool::warm_account`), so BALANCE on a
max-size contract pays the code read too.

## Read-path intervention (2026-10-05)

**Recovery.** The agent session driving the dive died on 2026-10-04 right after the S-arm forensic
trace (09:17 CEST); `exp.sh` had been run from the agent's SSH session and died with it. It was rerun
whole on 2026-10-05 from a root tmux (`reth-exp`), 14:22-15:48 CEST, every step exit 0. Long runs on
this host go in tmux from now on.

**The switch.** `docker.io/benchlocal/reth:devnet7-hashedreads` is reth acf6e17 (maxperf, devnet-7
base + STOPSIGNAL SIGKILL) plus `RETH_FORCE_HASHED_READS=1`, which makes `hashed_reads()` in
`providers/state/latest.rs` return true on a v1 store. Latest-state account and storage reads then go
to HashedAccounts/HashedStorages by keccak key, the same code path a v2 store uses; writes keep the v1
path. Runs on the J arm over the 66 tests at 160M (account_access overhead_baseline_False,
sload_bloated, sstore_bloated): `jh` (switch on) and `jc` (same image, switch off). jc against
the geometric mean of J1 and J2: median 1.003, so the source build matches the devnet-7 image.

Ratios are throughput (median per group); j = geomean(J1,J2), s = geomean(S1,S2).

| group (tests) | s/j | jh/jc | s/jh |
|---|---|---|---|
| non-CALL EOA / NON_EXISTING (16) | 0.015-0.024 | 0.014-0.025 | 0.929-0.948 |
| sload_bloated (2) | 0.023 | 0.016 | 1.202 |
| CALL EOA / NON_EXISTING (4) | 0.41-0.43 | 0.51-0.52 | 0.87-0.89 |
| sstore_bloated (4) | 0.450 | 0.502 | 1.038 |
| non-CALL MINIMAL / SAME_MAX (16) | 0.839-0.853 | 0.885-0.915 | 0.925-0.942 |
| CALL MINIMAL / SAME_MAX (4) | 0.918 | 1.052 | 0.875 |
| non-CALL DIFF_MAX / JUMPDEST (16) | 0.650-0.684 | 0.941-0.957 | 0.679-0.720 |
| CALL DIFF_MAX / JUMPDEST (4) | 0.761-0.766 | 1.061-1.062 | 0.715-0.716 |

By class (J1 >= 1 s): >= 1 s, 43 tests: s/j 0.840, jh/jc 0.945, s/jh 0.805. < 1 s, 23 tests: s/j
0.019, jh/jc 0.020, s/jh 0.939. **The ~50x family is entirely the read path**: on hashed reads the
jochemnet store is as slow as state-actor to within 6%. Over a second the read path is a small
part (jh/jc 0.945); most of the long-test gap is left after it, and it sits in the large-code
contracts (s/jh ~0.71). CALL to a contract runs ~5% *faster* on jochemnet with hashed reads (not
explained).

**Per-table pages (forensic set, 160M, value 0).** Distinct mdbx.dat pages per measured step
(`pcwin.py`), classified by `mdbxmap.py` (unmapped leaf/branch pages with 35-36-byte keys are the
nested dup subtrees of HashedStorages/PlainStorageState):

| test | fj (v1 reads) | fjh (hashed reads) | fs |
|---|---|---|---|
| BALANCE NON_EXISTING | 347 (0.23 s) | 95,798: HA 52.1k leaf + 43.4k branch (7.62 s) | 102,345: 52.1k + 50.1k (8.12 s) |
| BALANCE EXISTING_EOA | 1,284 (0.28 s) | 95,687 (7.60 s) | 102,341 (8.04 s) |
| BALANCE MINIMAL | 84,488: PAS 51.2k + 33.3k (6.82 s) | 94,086: HA 51.2k + 42.8k (7.56 s) | 100,692: 51.3k + 49.4k (7.99 s) |
| BALANCE DIFF_MAX | 473,960 (14.29 s) | 486,309 (14.99 s) | 465,022 (21.19 s) |
| sload_bloated slots False | 170 (0.22 s) | 96,052: dup 53.2k + 42.5k (7.57 s) | 84,138: 52.8k + 31.0k (6.53 s) |
| sload_bloated slots True | 743 (0.14 s) | 103,007 (7.96 s) | 84,041 (6.46 s) |

Every arm reads one leaf per access. The hashed arms differ in branch pages: state-actor's
HashedAccounts is one level deeper (height 6 vs 5) with 243k branch pages against 123k, branch fill
0.50 vs 0.69 and leaf fill 0.50 vs 0.59. That costs +6.6k branch pages per 51k lookups, which is the
~6% residual on account rows. [Hypothesis: uniform 0.50 fill is what sorted inserts without
MDBX_APPEND leave behind, since each split strands a half page.] On the bloated contract's storage it
goes the other way: state-actor's dup subtree has 31k branch pages to jochemnet's 42.5k, and
state-actor is faster (s/jh 1.20).

**DIFF_MAX: the residual is below mdbx.** state-actor reads *fewer* mdbx pages (465k vs 486k;
overflow pages equal at ~347k, Bytecodes leaves 16k vs 43k) and the same CPU (22-23 s), yet runs 21.2 s
against 15.0 s. The loop backing file takes 1,397,001 distinct page inserts for those 465,022 mdbx
pages (3.0x; jochemnet 1.06x on both read paths; no page inserted twice). Run lengths show why.
state-actor's code overflow runs are isolated, 35.5k runs of exactly 7 pages (codes stored in
code-hash order, scattered against the test's address-order access). jochemnet's accessed codes lie in long
contiguous runs (deployment order = access order). At the backing file each 7-page state-actor read
becomes a 31-page run (12.7k runs of exactly 31): readahead on the loop driver's buffered reads of the
backing image. mdbx.dat itself shows none (its runs are exactly the requested 7 pages).
benchmarkoor's disk_read: 15.1 GB vs 8.1 GB.

## Loop direct-io (2026-10-05)

**The rig.** Every scratch in this study is an ext4 on a loop device over an image file on md2, with
dm-era on top, and the loops ran buffered (`/sys/block/loopN/loop/dio` = 0, losetup's default). A
buffered loop reads its backing file through a second page cache, and that cache does its own
readahead.

**Setting it.** `LOOP_SET_DIRECT_IO` (ioctl 0x4C08) on loop1 and loop3 fails with EBUSY while
dm-era holds the loop, so it must be set with no scratch mapped. It then survives every schelk
restore and mount. util-linux 2.39's `losetup --direct-io=on <dev>` reported the EBUSY as "failed to
set up loop device" and still exited 0, so the first attempt ran a trace without DIO; it was stopped
within a minute and is kept as `*-aborted-busy`. `exp-dio.sh` sets DIO through the ioctl, prints the
state after every step and resets both loops to buffered on exit.

**Forensic set under DIO** (same binary on both arms, `devnet7-hashedreads`; J arm with hashed
reads). Seconds per measured step, buffered -> DIO:

| test | jochemnet, hashed reads | state-actor | mdbx pages (jh / s, DIO) |
|---|---|---|---|
| BALANCE DIFF_MAX | 14.99 -> **3.91** | 21.19 -> **3.87** | 489,435 / 477,009 |
| BALANCE MINIMAL | 7.56 -> **0.99** | 7.99 -> **1.03** | 94,401 / 100,911 |
| BALANCE EXISTING_EOA | 7.60 -> **0.94** | 8.04 -> **1.05** | 95,687 / 102,341 |
| BALANCE NON_EXISTING | 7.62 -> **1.02** | 8.12 -> **1.03** | 95,798 / 102,345 |
| sload_bloated slots False | 7.57 -> **0.98** | 6.53 -> **0.82** | 96,052 / 84,170 |
| sload_bloated slots True | 7.96 -> **0.93** | 6.46 -> **0.74** | 103,007 / 84,041 |

mdbx page counts are the same as under buffered loops, and the backing file takes no inserts. Every
test runs 5-8x faster on both arms, and the DIFF_MAX residual is gone (3.87 vs 3.91 s). Buffered,
~96k random pages took 7.6 s, about 79 µs a page, roughly one NVMe read at a time. [Inference:
the buffered loop worker reads the backing file synchronously, one request at a time, so reth's
parallel prewarm reads queue behind each other. With DIO the loop issues async direct reads in
parallel.] So **the buffered loop dominated every measured time in the baseline**: a test's time
tracked its mdbx page-miss count times a queue-depth-1 latency, plus backing readahead where the
layout set it off.

Consequences:
- The baseline's ratios (0.84 over a second, the 0.65-0.72 DIFF_MAX cells) mostly measure the
  rig. The study needs a DIO baseline, so `exp-dio2.sh` re-runs J1 S1 J2 S2 as dj1 ds1 dj2 ds2: same
  image and filter, DIO the only change.
- Every earlier client study in the series ran schelk on loop-backed images (geth/Besu
  `/schelk-vols/*.img`, Nethermind `nm-*.img`, Erigon loop3/4/6/8). [Not verified: their DIO state.
  The Erigon box was not reachable from this session; losetup defaults to buffered.]

**Timing set under DIO** (66 tests at 160M, xs = S arm, xjh = J arm with hashed reads, both on
`devnet7-hashedreads`; 66/66 passed each, 18:38-19:31 CEST). Buffered -> DIO time: state-actor
8.0x faster (median, range 5.0-8.9), jochemnet with hashed reads 7.8x (3.4-8.7).

| group (tests) | s/jh buffered | s/jh DIO | xs s | xjh s |
|---|---|---|---|---|
| non-CALL DIFF_MAX / JUMPDEST (16) | 0.710-0.715 | 1.038-1.039 | 3.87 | 3.99-4.00 |
| CALL DIFF_MAX / JUMPDEST (4) | 0.715-0.716 | 0.991-0.999 | 3.01-3.02 | 3.06-3.09 |
| non-CALL EOA / NON_EXISTING / MINIMAL / SAME_MAX (32) | 0.936-0.940 | 0.931-0.961 | 0.91-0.95 | 0.85-0.89 |
| CALL EOA / NON_EXISTING / MINIMAL / SAME_MAX (8) | 0.870-0.891 | 0.871-0.900 | 0.54-1.08 | 0.50-0.96 |
| sstore_bloated (4) | 1.038 | 1.048 | 0.73 | 0.88 |
| sload_bloated (2) | 1.202 | 1.250 | 0.71 | 0.88 |

Tests classed >= 1 s by J1 (43): s/jh 0.805 -> 0.977. Those under 1 s (23): 0.939 -> 0.937. The
large-code gap was the rig. The account-row residual (~6%, HashedAccounts depth and fill) and
CALL's ~11-13% survive DIO, so they belong to the stores. Under DIO most of these tests run under a
second, so the DIO baseline needs its one-second class re-fixed from a DIO jochemnet run (dj1),
not from J1.

**s/j under DIO** (xjc = J arm, v1 reads, same image, 66/66, 19:31-20:02 CEST). This is state-actor
against jochemnet as shipped, with the loop artifact removed:

| group (tests) | s/j buffered | s/j DIO | jh/jc DIO |
|---|---|---|---|
| non-CALL DIFF_MAX / JUMPDEST (16) | 0.672-0.678 | 1.025-1.032 | 0.978-0.995 |
| CALL DIFF_MAX / JUMPDEST (4) | 0.761-0.766 | 1.016-1.019 | 1.025-1.029 |
| non-CALL MINIMAL / SAME_MAX (16) | 0.843-0.847 | 0.862-0.870 | 0.909-0.916 |
| CALL MINIMAL / SAME_MAX (4) | 0.918 | 0.929-0.937 | 1.045-1.066 |
| sstore_bloated (4) | 0.450 | 0.556 | 0.606 |
| CALL EOA / NON_EXISTING (4) | 0.412-0.430 | 0.482-0.521 | 0.574-0.614 |
| sload_bloated (2) | 0.023 | 0.157 | 0.126 |
| non-CALL EOA / NON_EXISTING (16) | 0.017-0.019 | 0.127-0.132 | 0.136-0.139 |

Tests classed >= 1 s by J1 (43): s/j 0.840 -> 0.980. Under 1 s (23): 0.019 -> 0.146.

**Where the reth gap stands on the 66 tests.**
- Large-code contracts: at parity. Their 0.67-0.77 was backing-file readahead under buffered loops.
- The sequential-key family (EOA, NON_EXISTING, sload/sstore bloated): about 7x, from 55x. jochemnet
  keeps its v1 locality (a few hundred pages against ~96k). The buffered loop had made each random
  page ~8x costlier and so inflated the gap.
- Account rows on contracts (MINIMAL, SAME_MAX): 0.86-0.87, which is the read path (0.91) times
  state-actor's deeper, half-full HashedAccounts tree (s/jh 0.94-0.96).
- Nothing left is generated-vs-organic state content. The gaps come from reth's v1/v2 layout and
  from state-actor's B-tree fill.

**Ether transfers under DIO** (the 36 common tests, 160M+240M; xse 36/36, xjhe 198/198, xjce 36/36,
20:02-22:03 CEST). My first ether filter lacked the common set's `value_(160|240)M` clause, so the
J arm matched 198 jochemnet tests. xjhe was left to run (it covers all 36) and `cfg/xjce.yaml` was
narrowed before it started; only the 36 are scored. jochemnet buffered -> DIO: 8.2x faster.

| receivers (tests) | s/j buffered | s/j DIO | jh/jc DIO | s/jh DIO |
|---|---|---|---|---|
| all (36) | 0.930 | 1.017 | 1.140 | 0.878 |
| contract, delegated, self (28) | 0.85-0.99 | 0.96-1.04 | 1.08-1.21 | 0.81-0.96 |
| existent / non-existent EOA, amount 0 (4) | 0.84 | 0.885-0.891 | 1.006-1.025 | 0.869-0.879 |
| existent EOA, amount 1 (2) | 0.906 | 0.909 | 1.091 | 0.833 |
| non-existent EOA, amount 1 (2, 0.26-0.30 s) | 0.967 | 1.158 | 1.041 | 1.114 |

Over the family, state-actor and jochemnet are at parity under DIO (1.017; 0.930 buffered). Two
effects cancel. Hashed reads make jochemnet *faster* here (jh/jc 1.14), and state-actor's tree
shape costs about 12% (s/jh 0.878). The EOA-receiver cells keep ~10% against state-actor, where the
hashed path helps jochemnet least. [Hypothesis, not tested: on v1, reads go to Plain* while the
state-root job reads Hashed*, so a v1 block touches two tables' pages where v2 touches one. That
would also explain CALL to a contract running ~5% faster with hashed reads.]

## DIO baseline (started 2026-10-05 22:03)

`exp-dio2.sh` re-runs J1 S1 J2 S2 as dj1 ds1 dj2 ds2: same `devnet7-sigkill` image and
`cfg/common-filter.txt`, both scratch loops on DIO. tmux `reth-reduce` writes
`results/baseline-dio.json` when it finishes (`reth_reduce.py d`, class fixed from dj1; with no
prefix the reducer still reproduces `baseline.json` byte for byte).

**dj1: 266/266 passed, 22:03-00:01 CEST, no INVALID or SYNCING.** Per-family median time, J1
-> dj1 (account_access families pool their overhead_baseline controls):

| family (tests) | J1 s | dj1 s | speed-up |
|---|---|---|---|
| ether_transfers_onchain_receivers (36) | 13.30 | 1.80 | 8.20 |
| EXISTING_CONTRACT_SAME_MAX (40) | 0.94 | 0.16 | 4.47 |
| EXISTING_CONTRACT_MINIMAL (40) | 0.94 | 0.17 | 4.32 |
| sstore_bloated (8) | 0.90 | 0.20 | 3.72 |
| EXISTING_CONTRACT_JUMPDEST (40) | 1.98 | 0.56 | 2.38 |
| EXISTING_CONTRACT_DIFF_MAX (40) | 1.94 | 0.56 | 2.37 |
| EXISTING_EOA (20) | 0.20 | 0.16 | 1.22 |
| sload_bloated (4) | 0.14 | 0.14 | 1.09 |
| NON_EXISTING_ACCOUNT (20) | 0.15 | 0.14 | 1.07 |
| ext_account_query_warm (14) | 0.16 | 0.17 | 0.98 |
| sload_same_key_benchmark (4) | 0.02 | 0.02 | 0.96 |

Families that do no state I/O are unchanged (0.96-0.98), so DIO changes the cost of state reads, not
CPU. The more random pages a family reads on v1, the more it gains. jochemnet's EOA and NON_EXISTING
rows barely move: on v1 they read a few hundred pages. Class by dj1: 97 tests >= 1 s and 169 under,
against 123/143 by J1; 26 tests drop below a second. The DIO reduction fixes its class from dj1.

**All four runs 266/266** (ds1 00:01-01:24, dj2 01:24-03:22, ds2 03:22-04:46 CEST on 2026-10-06);
`EXP-DIO2-EXIT 0`, loops back to dio=0, `results/baseline-dio.json` written (class fixed from dj1).

| class (tests) | pair A (ds1/dj1) | pair B (ds2/dj2) | floor jochemnet | floor state-actor |
|---|---|---|---|---|
| >= 1 s (97) | **0.9998**, 76/97 in ±10% | **1.0013**, 76/97 | 0.994, 97/97 | 0.999, 97/97 |
| < 1 s (169) | 0.957, 52/169 | 0.983, 39/169 | 0.993, 118/169 | 0.999, 112/169 |

Buffered, the >= 1 s pairs were 0.842 / 0.840 with 28/123 inside ±10%. With the loop artifact
removed, **state-actor runs at parity with jochemnet over a second**. Cells left below the band:
- MINIMAL/SAME_MAX account rows: 0.81-0.90 (16 tests over 1 s).
- CALL EXISTING_EOA: 0.78.
- sstore_bloated: 0.94.
- Under a second, the sequential-address family: 0.11-0.16 (BALANCE/EXT*/DELEGATECALL/STATICCALL
  to EOA or absent accounts, sload/sstore_bloated), with CALL NON_EXISTING at 0.49-0.53.

**Same binary.** The experiment image (acf6e17 source build) matches the published devnet-7 image
under DIO on the 66 tests: xjc / geomean(dj1,dj2) median 1.001, 59/66 inside ±10% (dj2/dj1 on the
same tests: 58/66); xs / geomean(ds1,ds2) 0.996, 66/66. So the intervention runs and the DIO baseline
can be compared directly.

Next: verification plan `docs/superpowers/plans/2026-10-06-reth-gap-verification.md`.

## Verification campaign (2026-10-06)

The plan was approved in Plannotator, and Anon approved gate B (backing readahead off) and gate C
(repack, with a backup first). The driver is `verify.sh` in tmux `reth-verify`, from 15:18 CEST. It
runs phases 1 -> 2 -> 3, with step markers in `logs/verify.done/` and output in `logs/verify.out`.
After every run it checks the discovered test count, the exit code, the pass count and the DIO state.

**Filters checked offline against both arms' full fixture lists** (J 1,463 tests, S 438): T2 14/14,
F160 66/66, FE 36/36, FF 6/6.

**Repack tool** `repack/repack` (Go with mdbx-go v0.40.1, the library state-actor's writer uses,
built in `golang:1.25-bookworm`). It copies a table to a temp table with `cursor.Append`, clears
it, appends it back, and compares a sha256 over every (k, v) before and after.

**Toy test, 2M random 32-byte keys with 40-byte values, same libmdbx:**

| insert order, call | leaf pages | branch pages |
|---|---|---|
| sorted, `Put` | 40,817 | 432 |
| sorted, `Append` | 40,817 | 432 |
| random, `Put` | 79,889-80,014 | 1,639-1,657 |
| random `Put` table after repack | 40,817 | 432 |

The contents hash was identical before and after both repacks. **This contradicts the C7 hypothesis
as worded.** In this libmdbx, sorted-order `Put` packs exactly like `Append`. Only out-of-order
inserts leave leaves half full (~51%). So state-actor's 0.50 HashedAccounts fill means its account
writes did not arrive in key order; `tx.Put` itself is not the cause. The desk check (D2) has to
find the actual order the writer feeds. C7 becomes: "HashedAccounts is written out of key order".

**Incident, xs2 (2026-10-06 ~13:19:30-13:21:00 UTC).** I ran a D5 audit grep (`grep -rIl` over
`/root/bench` and `/home/CPerezz`, which holds several GB of logs) during xs2. It read from md2, the
same RAID that holds the scratch images, until the session timed out after 90 s. It overlaps xs2's
BALANCE 160M tests that started between 13:19:28 and 13:20:51 (about five). Check them against xs
and the floor; re-run them only if they fall outside it. Rule for the campaign: no I/O-heavy
commands on the host while a run is measuring. Copy the data off, or wait for a gap.
The traces for A1 were then copied off by `tar` over ssh: 280 MB read from md2 over 120 s
(13:2x UTC), also during xs2, about 2 MB/s. Noted, not expected to matter.

**Decision (xs2 kept).** xs2 finished 66/66. Replica floor xs2/xs on the five tests whose measured step
started inside the grep window: 1.007, 0.926 (BALANCE MINIMAL), 0.984, 1.052, 0.962, all within ±10%.
The other 61 tests: median 0.999, range 0.939-1.088, 61/61 within ±10%. Only BALANCE MINIMAL sits a
little below the rest's minimum, so pair B's BALANCE MINIMAL cell carries that caveat. No re-run.

**A1 (C4), on the buffered DIFF_MAX traces.** Code overflow (`large`) pages first touched in the
measured step, with Spearman ρ between first-touch time and page index:

| trace | code pages | ρ | contiguous runs | mean run |
|---|---|---|---|---|
| fj (J, v1 reads) | 343,396 | -0.005 | 2,317 | 148 pages |
| fjh (J, hashed reads) | 345,801 | -0.005 | 2,010 | 172 pages |
| fs (S) | 347,759 | **0.973** | 42,019 | 8.3 pages |

Account leaves are touched in random order on every arm (ρ -0.001 to 0.025). **The prediction failed
and C4 is rewritten.** jochemnet's accessed code is *not* in access order. It sits in long contiguous
blocks (~21 max-size contracts each) that the test visits in random order. state-actor's accessed
code is one contract per isolated run, visited in page order: its writer laid code out in the order
the test reads it, but with unread code in between. The readahead account of C3 fits better than
before. On jochemnet, the backing file's over-fetch lands inside the block the test reads anyway
(backing/mdbx 1.06). On state-actor, each 7-page run is read front to back and looks sequential, so
readahead runs past its end into code nothing reads (12.7k backing runs of exactly 31 pages; 3.0x).
New C4: "jochemnet's accessed code is contiguous on disk, state-actor's is one isolated run per
contract". E2.3 tests whether readahead is the step that turns this into time.

### Phase 0: desk checks (2026-10-06)

Scout report kept at `agent://DeskChecks` (session-local); the citations the article needs are
copied here.

- **D1 confirmed (C2, C3).**
  - Buffered loop reads are a blocking `vfs_iter_read` inside the loop worker
    ([loop.c L276-300](https://github.com/torvalds/linux/blob/v6.8/drivers/block/loop.c#L276-L300)).
  - A worker drains its command list one at a time
    ([L1930-1961](https://github.com/torvalds/linux/blob/v6.8/drivers/block/loop.c#L1930-L1961)).
    There is one worker per blkcg
    ([L827-899](https://github.com/torvalds/linux/blob/v6.8/drivers/block/loop.c#L827-L899)).
  - DIO goes through async `lo_rw_aio` (`ki_complete`,
    [L390-457](https://github.com/torvalds/linux/blob/v6.8/drivers/block/loop.c#L390-L457)), and
    `use_aio = lo->use_dio` ([L1857](https://github.com/torvalds/linux/blob/v6.8/drivers/block/loop.c#L1853-L1859)).
  - `ra_pages == 0` reads only the requested page
    ([readahead.c L669-694](https://github.com/torvalds/linux/blob/v6.8/mm/readahead.c#L669-L694)).
    `file_ra_state_init` copies the bdi's `ra_pages` at open
    ([L146-152](https://github.com/torvalds/linux/blob/v6.8/mm/readahead.c#L146-L152), called from
    [open.c L972](https://github.com/torvalds/linux/blob/v6.8/fs/open.c#L972)).
- **D2 confirmed, and it settles C7.**
  - state-actor writes HashedAccounts with `txn.Put` in **generation order**: alloc order, then PRNG
    draws ([run_cgo.go L96-163](https://github.com/ethereum/state-actor/blob/005a19c/client/reth/run_cgo.go#L96-L163);
    [data_writer_cgo.go L24-54](https://github.com/ethereum/state-actor/blob/005a19c/client/reth/data_writer_cgo.go#L24-L54)).
  - The same accounts *are* stream-sorted by hash, but only to build AccountsTrie, after the
    HashedAccounts rows are committed
    ([run_cgo.go L80-86, L220-256](https://github.com/ethereum/state-actor/blob/005a19c/client/reth/run_cgo.go#L220-L256)).
  - Bytecodes go in PRNG draw order with `Put`
    ([bytecode_writer_cgo.go L128-144](https://github.com/ethereum/state-actor/blob/005a19c/client/reth/bytecode_writer_cgo.go#L128-L144)).
  - HashedStorages go entity by entity in PreAlloc order, with slots keccak-sorted inside each entity
    ([spec_storage_streaming_cgo.go L349-375](https://github.com/ethereum/state-actor/blob/005a19c/client/reth/spec_storage_streaming_cgo.go#L349-L375)).
- **D3 confirmed (C5).**
  - The jochemnet payloads come from ethereum/execution-specs
    [d9ad55b3](https://github.com/ethereum/execution-specs/commit/d9ad55b3).
  - `SequentialAddressSource` uses `EXISTING_EOA_BASE = 0x1000` and `NON_EXISTING_BASE =
    keccak256(b"random")`, increment 1
    ([account_creator.py L31-36, L252-277, L348-361](https://github.com/ethereum/execution-specs/blob/d9ad55b3/tests/benchmark/helper/account_creator.py#L252-L277)).
  - sload/sstore_bloated walk slots 0..N linearly
    ([test_sload.py L239-291](https://github.com/ethereum/execution-specs/blob/d9ad55b3/tests/benchmark/stateful/bloatnet/test_sload.py#L239-L291),
    [test_sstore.py L40-90](https://github.com/ethereum/execution-specs/blob/d9ad55b3/tests/benchmark/stateful/bloatnet/test_sstore.py#L40-L90)).
  - reth acf6e17 branches account and storage reads on `use_hashed_state()`
    ([latest.rs L73-82, L274-291](https://github.com/paradigmxyz/reth/blob/acf6e17/crates/storage/provider/src/providers/state/latest.rs#L73-L82)).
  - The BAL prewarm warms every BAL account and fetches its bytecode
    ([prewarm.rs L405-429](https://github.com/paradigmxyz/reth/blob/acf6e17/crates/engine/tree/src/tree/payload_processor/prewarm.rs#L405-L429),
    [bal_prewarm_pool.rs L158-172](https://github.com/paradigmxyz/reth/blob/acf6e17/crates/engine/tree/src/tree/payload_processor/bal_prewarm_pool.rs#L158-L172)).
- **D4: the "~50% unless Append" premise is contradicted; the toy test agrees.**
  - libmdbx chooses the split point by insert position since v0.10.0
    ([af9b7b56](https://github.com/isar/libmdbx/commit/af9b7b560505684249b76730997f9e00614b8113):
    "APPEND-flags no longer affect choosing the page split point"). A key landing at the right edge
    gets an append-style split; only inserts strictly inside the range split in the middle.
  - Vendored versions: reth 0.13.12, mdbx-go (state-actor) 0.14.2.
  - The exact `page_split` body at the pinned commits could not be fetched (the 1.5 MB amalgamation
    is over the fetch limit). The commit diff, the ChangeLog and the toy measurement stand in.
- **New C7 (confirmed by source and toy):** state-actor inserts HashedAccounts in generation order,
  which is random relative to keccak key order. Every insert lands inside the key range and splits a
  page in the middle, which leaves ~50% fill. The fix is in the writer: feed HashedAccounts from the
  hash-sorted stream it already builds for the trie.
- **D5 (this host).** 19 of 195 study scripts call `losetup` (geth and Besu studies), e.g.
  `losetup --find --show /schelk-vols/besu-joc-scratch.img`. None set direct-io or touch `loop/dio`,
  and root's shell history has no losetup. So, as recorded, the geth and Besu studies ran buffered
  loops. The Nethermind/Erigon box (157.180.2.180) is still unchecked; it needs Anon's key touch.

### Phase 1: replicas and mapped traces (15:18-17:54 CEST)

All nine runs passed, with the discovered count, passes and DIO confirmed after each: xs2, xjh2, xjc2
66/66; xse2, xjhe2, xjce2 36/36; t2jc, t2jh, t2s 14/14. Maps t2j (J store) and t2s (S store) were
written before the S store changes in phase 3. Numbers from `collect_reth.py --partial` on a local
mirror.

| set (DIO) | s/j A / B | jh/jc A / B | s/jh A / B | floors s, jh, jc |
|---|---|---|---|---|
| 160M, dj1 class >= 1 s (23) | 1.026 / 1.010 | 0.994 / 0.980 | 1.035 / 1.034 | 0.999, 0.997, 1.002 |
| 160M, < 1 s (43) | 0.185 / 0.260 | 0.197 / 0.219 | 0.942 / 0.946 | 0.999, 1.005, 1.008 |
| ether, 36 | 1.017 / 1.008 | 1.140 / 1.131 | 0.878 / 0.874 | 36, 35, 36 of 36 in ±10% |

Pair B reproduces pair A, so C5 and C8 now rest on two independent pairs.

**Hashed reads speed jochemnet up only on blocks that change state.** On 160M cells, jh/jc is:
- 1.08-1.21 for CALL value_sent_1 to contracts;
- 1.05-1.09 for sstore write_new_value;
- 1.13-1.14 for ether transfers;
- 0.88-0.98 for the value_sent_0 rows.

**C9 confirmed by pages** (T2, ether transfer to contract, amount 0):
- t2jc reads PlainAccountState (21.2k leaf + 18.0k branch) for execution *and* HashedAccounts (14.9k
  + 12.0k) for the state root.
- t2jh needs one table for both (25.5k + 21.2k), so 117k pages instead of 136k: jh/jc 1.17 by
  pages, 1.14 measured.

**C10 explained.** CALL EXISTING_EOA, value_sent_1 (the only CALL EOA cell under 0.85 over a second):
- t2s touches 135k pages against t2jh's 107k: AccountsTrie branch pages 20.1k vs 10.8k, plus 12.5k
  pages the mapper labels `other`.
- s/jh from pages 0.795, measured 0.816.
- The state-root update after 52k balance changes walks state-actor's AccountsTrie, which is 6x larger
  (161.7M entries vs 26.9M).
- New open question: why state-actor's writer stores 6x the AccountsTrie entries.

**C11 confirmed.** sload_bloated: t2s 84.1k pages (dup subtree 52.8k leaf + 31.0k branch) against
t2jh's 96.1k (53.2k + 42.5k); s/jh 1.21 measured, 1.14 by pages.

**A2 (C6) confirmed.** Under DIO, µs per mdbx page is the same on all three setups for every T2 test
(BALANCE MINIMAL 9.55 / 9.46 / 9.76 µs; EXISTING_EOA 9.04 jh / 8.86 s). Page count predicts the time
ratio on account rows: s/jh by pages 0.935, measured 0.907-0.957. The account-row residual is extra
HashedAccounts branch pages, 49.5k vs 42.9k per 51.3k leaves.

### Phase 2: the loop mechanism (17:54-18:15 CEST)

**E2.1 fio (C2 confirmed).** Random 4 KiB reads from a throwaway loop over a 64 GiB file on md2:

| target | psync 1 | 4 | 16 | 64 | libaio qd 1 | 16 | 64 |
|---|---|---|---|---|---|---|---|
| loop, buffered | 11.4k | **13.7k** | **13.7k** | **13.7k** | 10.5k | 13.6k | 13.6k |
| loop, DIO | 11.5k | 40.9k | 127k | 130k | 10.7k | 115k | 119k |
| raw file, O_DIRECT | 13.8k | 54.4k | 212k | 763k | 11.9k | 95.3k | 94.7k |

(IOPS; buffered mean latency 87 -> 292 -> 1,171 -> 4,684 µs as jobs go 1 -> 64.) The buffered loop
serves one read at a time, whatever the concurrency above it.

**E2.2 in situ (C2 confirmed).** J with hashed reads, BALANCE MINIMAL and EXISTING_EOA:
- Buffered: loop1 holds 127 requests in flight (aqu-sz 127.5), while the NVMe RAID1 serves ~13.4k
  reads/s from one mirror at queue depth 0.84.
- DIO: ~48k reads/s across both mirrors.
- Step time 7.3 s -> 1.0 s.

**E2.3 backing readahead off (C3 confirmed).** Buffered loops, re-attached while md2 readahead was 0.
`losetup` printed "loop3 … busy" on both re-attaches and exited 0, but dmesg shows both loops attached
at 18:06:48 and 18:16:29, and the data shows readahead was off on both arms:

| test | ras vs fs: backing/mdbx | rajh vs fjh: backing/mdbx | s/jh: readahead on -> off |
|---|---|---|---|
| BALANCE DIFF_MAX | 3.00 -> **1.001** | 1.06 -> 1.000 | **0.707 -> 1.022** |
| BALANCE MINIMAL | 1.00 -> 1.004 | 1.02 -> 1.002 | 0.946 -> 0.945 |

Still buffered, turning readahead off removes the large-code gap. DIFF_MAX gets slower on both arms
(J 15.0 -> 36.5 s, S 21.2 -> 35.8 s). Behind a serialized loop, readahead turns 7 page reads into one,
so it helps both arms. It helps jochemnet more because the extra pages it fetches are all used (C4).

**Why state-actor's AccountsTrie is 6x larger (C10 follow-up, desk check).**
- state-actor's trie builder runs in "full emissions" mode. It stores a BranchNodeCompact row for
  every branch whose RLP is >= 32 bytes: `shouldEmit := storeInDbTrie || (b.fullEmissions && isHashed)`
  ([hash_builder.go L137-144, L175-183, L407-408](https://github.com/ethereum/state-actor/blob/005a19c/internal/reth/hash_builder.go#L400-L408)).
  The account trie builder chooses it whenever an emitter is given
  ([state_root.go L101-114](https://github.com/ethereum/state-actor/blob/005a19c/client/reth/state_root.go#L101-L114)).
- alloy_trie (reth's own writer) stores a row only when `hash_mask | tree_mask != 0`
  ([L55-56](https://github.com/ethereum/state-actor/blob/005a19c/internal/reth/hash_builder.go#L53-L57),
  citing alloy hash_builder/mod.rs:429-457). That skips the bottom branches, whose children are all
  leaves.
- Those bottom rows are the difference: 161.7M entries against 26.9M. A state-root update after many
  balance changes reads them (2x AccountsTrie branch pages on CALL EOA with value).
- On jochemnet the walker rebuilds bottom branches from HashedAccounts leaves that the block has
  already read.
- Writer-side fix: emit with alloy's rule. [Not tested: whether reth's walker then still avoids the
  300 s full walk the comment warns about. The upper rows would still be present.]

### Phase 3: repack (from 18:15 CEST)

**Backup** `/data/schelk-vols/reth-sa-virgin.pre-repack.img`: 711 GB apparent, 507 GB allocated,
52 min. Sizes match the original, and the sha256 of the first and last GiB match.

**Repack started 19:07.** HashedAccounts before: depth 6, 243,311 branch and 11,698,671 leaf pages,
430,696,738 entries.

**Known difference: mdbx geometry.** The tool opened the env with `SetGeometry(-1, -1, 1 TiB,
1 GiB, -1, -1)`, and libmdbx persisted that. Stored geometry went from
`l3-n133169152-u2147483648/s0-g1048576` (state-actor's: 8 TiB upper, 4 GiB growth, no shrink) to
`l64-…-u268435456/s524288-g262144` (1 TiB upper, 1 GiB growth, 2 GiB shrink threshold).
- reth re-applies its own geometry when it opens the store read-write (8 TiB, 4 GiB growth, shrink
  0), so runtime behaviour matches the original.
- The repacked virgin costs one meta-page write at each boot, outside the measured step.
- Fix for any reuse: pass -1 for every geometry field on an existing DB.

**Repack done** (19:07-19:36, 28 min). Contents sha256 `c1710919…2ff0` is identical before and after,
over 430,696,738 entries.

| HashedAccounts | before | after |
|---|---|---|
| depth | 6 | **5** |
| branch pages | 243,311 | **62,420** |
| leaf pages | 11,698,671 | **5,929,695** |
| branch / leaf fill (mdbxmap) | 0.498 / 0.501 | **0.981 / 0.993** |

State-actor's tree is now denser than jochemnet's (height 5, 123k branch / 8.19M leaf, fill
0.69 / 0.59).

**Promote** copied 1,048,945 blocks (64.02 GB) in 3 min 16 s.

**Gate** (published image, repacked scratch): RPC in 3 s, head 0. Genesis 0x0cb03528… and state
root 0x48d611bb… are unchanged. Boot wrote 2.4 MB (the geometry meta, [inference]); 0.3 MB in
60 idle seconds. Then `schelk recover` dropped the boot's writes.

**Running from 19:41:** xsr, xsr2 (66), xser, xser2 (36), t2sr plus its map, all under DIO.
Prediction: HashedAccounts pages per account-row lookup fall below jochemnet's; s/jh on account rows
goes to >= 1.0, s/j on MINIMAL/SAME_MAX goes to ~0.91 (read path only), ether s/jh to ~1.0.

**Phase 3 runs** (19:41-20:55): xsr, xsr2 66/66; xser, xser2 36/36; t2sr 14/14 and its map, all under
DIO. `VERIFY-DONE` 20:55, exit 0. The trap left loops at dio=0, md2 readahead at 256 kB, nothing
mapped.

Outcome against the predictions (sr = repacked state-actor):

| cells | s/jh -> sr/jh (A / B) | s/j -> sr/j vs jochemnet as shipped (A / B) | prediction |
|---|---|---|---|
| account rows MINIMAL/SAME_MAX v0 (16) | 0.96 / 0.94 -> **1.117 / 1.105** | 0.867 -> **1.003 / 1.006** | sr/jh >= 1.0 met; sr/j ~0.91 missed (parity instead) |
| sequential EOA/NON_EXISTING v0 (16) | 0.93 -> 1.108 / 1.115 | 0.13 -> 0.155 / 0.160 | met |
| large code DIFF_MAX/JUMPDEST v0 (16) | 1.04 -> 1.077 / 1.086 | 1.031 -> 1.068 / 1.062 | (no prediction) |
| CALL EXISTING_EOA value 1 (1) | 0.82 -> 0.858 / 0.837 | 0.785 -> 0.819 / 0.801 | |
| sload_bloated (2) | 1.25 / 1.21 -> 1.226 / 1.222 | unchanged (sr/s 0.98 / 1.01) | control: storage not repacked |
| ether, 36 | 0.878 / 0.874 -> **0.928 / 0.931** | 1.017 / 1.008 -> 1.065 / 1.061 | sr/jh ~1.0 **missed** |
| 160M, dj1 class >= 1 s (23) | 1.035 -> 1.073 / 1.074 | 1.026 / 1.010 -> 1.064 / 1.052, 23/23 in ±10% | |

Floors: sr 0.998 (>= 1 s), 1.001 (ether).

**Account rows.** The repacked tree is denser than jochemnet's own HashedAccounts (BALANCE MINIMAL:
86.7k pages against 94.1k on jh, 100.7k before). It gains back the v2 read-path penalty (jh/jc 0.91),
and account rows reach parity with jochemnet as shipped. My "read path only, ~0.91" prediction was
wrong because I assumed repacking could at best reach jochemnet's fill.

**Where the rest of the state-changing gap is.** Ether and CALL with value keep 7-18% after the
repack. The T2 tables put it in the state-root trie tables:
- CALL EOA value 1: HashedAccounts 27.1k pages (sr) vs 30.0k (jh), but AccountsTrie 59.6k vs 46.2k,
  plus 12.5k pages only state-actor touches.
- Ether to contract: HashedAccounts 43.0k vs 46.7k; AccountsTrie 54.1k vs 42.2k; plus 11.0k.
- Those extra pages are mostly leaves with 64-byte keys next to StoragesTrie pages ([inference] the
  nested pages of state-actor's StoragesTrie). That table is half full too (branch 0.50, leaf 0.24 in
  `t2s.map.log`).
- So the residual is the C10 mechanism: full-emission trie rows, written out of order. Ether's ~1.0
  prediction missed for that reason.

**What is left of the gap after the HashedAccounts fix:**
1. The v1/v2 read layout on sequential keys (sub-second, ~6.5x). state-actor can only write v2.
2. The trie tables on state-changing blocks (CALL with value to EOAs, 0.80-0.82).
Neither is generated-vs-organic state content.

### Final collection and verdicts (2026-10-06 20:58)

`collect_reth.py` (article folder, `articles-wt-reth-article/reth-state-db-divergence/`) ran on the
host and wrote `data/report_data.json`.
- 39 runs in the registry, 0 failed checks: counts, passes, and DIO mode per run from the driver
  logs (pre-DIO runs by timestamp).
- Both baselines recomputed and equal to the saved reductions.
- Images by id: hashedreads `26a39b78…`, sigkill `d36b6656…`. Kernel 6.8.0-111-generic.

Every claim has an oracle; all 14 are **supported**, with C4 and C7 as rewritten this campaign:

| claim (as the article may state it) | evidence | verdict |
|---|---|---|
| C1 Buffered loops dominated the baseline; DIO speeds state-reading families 2.4-8.7x, leaves no-state families within ±10%, and leaves mdbx page counts unchanged (≤2.6%) | buffered vs DIO, same stores and binary | supported |
| C2 A buffered loop serves one backing read at a time | fio flat at 13.7k IOPS from 4 to 64 jobs (DIO 9.3x at 16); in situ loop queue 127 vs NVMe queue 0.85 | supported |
| C3 The large-code gap was backing readahead | readahead off: S backing/mdbx 3.00 -> 1.001, DIFF_MAX s/jh 0.707 -> 1.022, still buffered | supported (intervention) |
| C4 jochemnet's accessed code is contiguous on disk (runs of 148-172 pages, read in random order, ρ -0.005); state-actor's is one isolated run per contract (8.3 pages), read in page order (ρ 0.973) | A1 on traces | supported (rewritten) |
| C5 The sequential family is the v1/v2 read path | jh/jc 0.139 / 0.143; s/jh 0.93 / 0.95, two pairs | supported (intervention) |
| C6 The account-row residual is HashedAccounts page count from fill | equal µs/page (1.03); repack: sr/jh 1.12 / 1.10, sr/j 1.00 / 1.01 | supported (intervention) |
| C7 state-actor writes HashedAccounts out of key order, so pages split in the middle (fill 0.50); libmdbx packs sorted inserts fully | source (generation order, `tx.Put`); toy 40,817 vs 79,846 leaves; repack 0.50 -> 0.99, same hash | supported (rewritten) |
| C8 Ether parity is two effects cancelling | s/j 1.017 / 1.008; jh/jc 1.140 / 1.131; s/jh 0.878 / 0.874 | supported |
| C9 v1 touches Plain* and Hashed* on state-changing blocks | t2jc Plain 39.2k + Hashed 26.8k; t2jh Plain 0; 136k vs 117k pages | supported |
| C10 State-changing blocks pay for state-actor's full-emission AccountsTrie | AccountsTrie branch pages 1.86x; source `fullEmissions` | supported |
| C11 state-actor's storage dup subtree is shallower | 84.1k vs 96.1k pages; s/jh 1.25 / 1.21 | supported |
| C12 Method: source build = published image; benchmarkoor disk_read ≈ 4.0x page-cache bytes | xjc/dj 1.001; 3.99x | supported |
| C13 Over a second, DIO baseline 0.9998 / 1.0013 (floors 97/97); buffered 0.842 / 0.840 | independent pairs | supported |
| C14 The geth/Besu studies on this host attached loops without direct-io | 19 scripts call losetup, none set DIO | supported (this host only) |

**State left on the host.**
- The state-actor virgin is now the **repacked** store.
- The original is at `/data/schelk-vols/reth-sa-virgin.pre-repack.img` (507 GB). Keeping or
  restoring it is Anon's call.
- `repack/main.go` now keeps an existing DB's geometry (-1 everywhere); rebuilt and toy-tested
  (`logs/repack-toy.log`).

## v2 jochemnet and the state-actor fixes (from 2026-10-06 22:05)

Plan: `docs/superpowers/plans/2026-10-06-reth-v2-state-actor-prs.md`, approved by Anon.

**Why v2.** Since reth 2.0 (April 2026) new databases use storage v2 by default; existing v1
databases keep v1 ([reth.rs/run/storage](https://reth.rs/run/storage/)). The jochemnet snapshot is
v1, i.e. legacy; state-actor writes v2. `reth db migrate-v2` is in our image (2.4.1-dev, acf6e17).

**Stage 1 (box, running).** `v2.sh` (tmux `reth-v2`) plus `jbackup.sh` (tmux `reth-jbak`):
- v1 virgin backed up to md3.
- `migrate-v2 --chain mainnet` on the J scratch: started 22:05; the log shows "Starting v1 → v2
  storage migration, tip 24410463".
- The original state-actor store back as the S virgin (`init-from`).
- Promote v2 J, gate, then the DIO baseline vj1 vs1 vj2 vs2.

**PRs (local, uncommitted).** state-actor `origin/main` = 005a19c, the store's own commit.
- **PR1** `reth-hashed-accounts-key-order` (worktree `state-actor-wt-hashed-order`):
  - The sorter value is framed as `[len][compact HashedAccounts row][RLP]`; phase 2 `Append`s the
    compact row in AddrHash order while the trie builder gets the RLP unchanged.
  - `WriteEOAs` becomes archive-only; `WriteContracts` keeps every table but HashedAccounts.
  - New test `TestRunCgoHashedAccountsSortedAppend` checks content, order and byte totals against an
    independent reconstruction.
- **PR2** `reth-trie-rows-alloy-rule` (worktree `state-actor-wt-trie-rows`):
  - Removes `fullEmissions`; a row is stored iff `tree_mask | hash_mask != 0`. Doc comments fixed
    (the "alloy emits zero rows" premise, and the claimed lexicographic emission order: it is
    post-order).
  - New test `TestHashBuilderEmissions_MatchesIndependentRecount` (1 to 50,000 keys plus extension
    cases) and a post-order test.
  - 50,000 random keys: 16,638 rows -> 4,716, root unchanged.
- **Combined** `reth-layout-fixes` (worktree `state-actor-wt-layout-fixes`) applies cleanly. Both
  packages pass the cgo suite in the repo's builder image, including `TestRethGoldenStateRoot`.

**Small end-to-end check** (builder image, 1 GB target, seed 42, no spec):

| | main | fixes |
|---|---|---|
| state root | 0x20a19dfe…66f7e | identical |
| HashedAccounts sha256 (1,227,138 entries) | 4be50b9a…81bf | identical |
| HashedAccounts leaf / branch pages | 33,272 / 700 | 16,880 / 179 |
| AccountsTrie rows / leaf pages | 441,257 / 17,371 | 96,198 / 8,720 |
| datadir | 2.3 GB | 1.2 GB |

Not yet checked: that reth runs blocks on a store with the reduced trie rows. The at-scale smoke and
re-bench are that test.

**Host automation, one chain.** tmux `reth-v2` runs stage 1 (`v2.sh`). tmux `reth-fix` runs
`stage2.sh`, which waits for `STAGE1-DONE`, then:
1. builds `localhost/state-actor-reth:layout-fixes` from `state-actor-fix/` (the combined branch,
   cached RocksDB layer from main);
2. drops the S scratch image (the original store stays as a virgin file on md3);
3. regenerates with the 005a19c arguments into `/sa-gen-fix`, with a 100 GB guard on md2;
4. aborts unless the state root is 0x48d611bb… and the HashedAccounts content hash equals the
   original store's (`repack -hash`, `c1710919…2ff0`);
5. copies into a new ext4 virgin `reth-sa-fix-virgin.img` on md3 (hash re-checked, byte totals
   equal), adopts it with `init-from`, gates it, smoke;
6. re-bench fj1 fs1 fj2 fs2 (266, DIO) -> `results/baseline-fix.json`; T2 traces t2jv / t2sf, mapped.

**Repack tool** gained a read-only `-hash` mode.

**Collector** (`collect_reth.py`):
- registry: the new runs plus both driver logs;
- baselines `v` (v2) and `f` (fix), each checked against its saved reduction;
- C15: the D set (outside 1.1x on the same side in both pairs, both floors in band);
- C16: per-D-test before and after, verdict fixed / improved / unchanged / worse, and regressions
  outside D;
- C17: tree stats original vs fixed vs v2 jochemnet, plus generation and migration logs.

**PR state.**
- Both branches build, and `go test ./...` passes. CHANGELOG entries added.
- Uncommitted: the repo signs commits (`commit.gpgsign=true`), which needs Anon's key touch.

**What `reth db migrate-v2` does (acf6e17, `crates/cli/commands/src/db/migrate_v2.rs`), and the
changes it forced (2026-10-07 00:20):**
- Phases: changesets and receipts -> static files; TransactionHashNumbers, AccountsHistory and
  StoragesHistory -> RocksDB; flip to v2; **clear** AccountChangeSets/StorageChangeSets,
  TransactionSenders, Plain*, AccountsTrie, StoragesTrie, and reset SenderRecovery, MerkleExecute
  and MerkleUnwind to 0; compact MDBX into `db_compact` and swap.
  - It ends with "restart the node and let it run the pipeline". Without that, a migrated store
    has no trie rows.
  - At startup reth's `check_pipeline_consistency` sees stages behind Headers and backfills to the
    tip; `--debug.terminate` exits afterwards.
  - The **rebuild** is therefore one `reth node … --debug.terminate` run. Its MerkleExecute stage
    checks the rebuilt root against the tip header.
  - So the v2 jochemnet's trie tables are reth-built from scratch: the store a migrated node really
    has.
- Compaction space: the compacted copy is ~197 GB (HashedAccounts ~34, HashedStorages ~133,
  Bytecodes ~24, small tables), on a scratch with 177 GB free for non-root. reth runs as root and
  ext4 reserves 5% for uid 0 (102 GB), so root has 294 GB. It fits.
- The step ran slowly: `TransactionHashNumbers` (277 GiB, 3.23B rows) took over 2 h, because the J
  loop was buffered during the migration (~10k IOPS random reads). DIO can't be set while dm-era
  holds the loop.

**Driver change.**
- `v2.sh` would have promoted the store without the rebuild. A running bash script can't be edited
  safely, so `logs/v2.done/jbackup` was made a directory: `[ -f ]` is false, and `touch` on it
  still succeeds. That parks v2.sh in its promote wait loop.
- `v2b.sh` (tmux `reth-v2b`, chain A) waits for migrate, srestore and the v1 backup, then stops
  v2.sh and runs: rebuild, promote J, gate J (checkpoints at the tip, v2, idle writes), smoke, the
  baseline vj1 vs1 vj2 vs2, reduce, `STAGE1`.
- `stage2b.sh` (tmux `reth-fix`, chain B) runs the fix build, generation, content and hash checks,
  and the copy to the virgin **now**, during the migration and rebuild, when nothing is measured.
  The generation guard is at 50 GB of md2 free; md2 has 568 GB free and the fix store is expected
  at ~430-470 GB peak.
- Chain A doesn't start any measurement until chain B's virgin copy is done (or chain B ended).
  Chain B doesn't touch the S scratch or run anything until `STAGE1`.
- This saves ~9 h against the plan's order, with the same no-overlap rule for measurements.
- PR1 cost to keep in mind: the streamsort entries (colocated with the datadir on md2) now also
  carry each account's compact HashedAccounts row, +~40 B × 430M ≈ +17 GB transient. Peak
  estimate ~450-490 GB against 568 GB free and the 50 GB guard.

**Stage 1 results (2026-10-07).**
- `migrate-v2`: exit 0 in 3 h 50 min (22:05-01:55).
  - Changesets 571,577 + 20,133, receipts and TransactionHashNumbers (3.23B rows, the 2 h+ step)
    moved.
  - Tables cleared; SenderRecovery, MerkleExecute and MerkleUnwind reset to 0.
  - MDBX compacted and swapped. J scratch: 1,607 -> 883 GB used.
- The original state-actor store was back as the S virgin and re-cloned by 02:44 (`init-from`).
  HashedAccounts had 11,698,671 leaf pages, i.e. the original 005a19c store, not the repack.
- v1 backup `reth-joc-virgin.v1.img` done (sizes equal, first and last GiB hashes equal).
- **Rebuild** (02:44-03:58, `reth node … --debug.terminate`):
  - The pipeline started from the consistency check, as read in the source.
  - SenderRecovery took 0 s (pre-merge bodies pruned, nothing to recover).
  - MerkleExecute was a clean rebuild over **2,177,421,992 entities** (accounts + slots) and
    finished, so the root matches the tip header.
  - Every checkpoint is at 24,410,463 and the store is `storage_v2: true`.
  - The rebuild was slow for the same reason as the migration: loop1 buffered, ~10.8k random 4 KiB
    reads/s.
- **Promote** 6,127,591 blocks / 374 GB in 24 m 47 s. **Gate**: 0 MB of idle writes on a fresh
  mount; checkpoints and settings survived the promote.

**Fixed store generated (chain B, 00:39-04:41).**
- `localhost/state-actor-reth:layout-fixes` (the combined branch, built on the host) with the 005a19c
  arguments: exit 0 in **3 h 59 min**, against the original 8 h 38 min, while md2 was shared with
  the migration and rebuild.
- 423,356,706 accounts + 7,340,032 contracts. **State root 0x48d611bb… identical.**
- **HashedAccounts content hash identical** (`c1710919…2ff0`, 430,696,738 entries).
- 431 GB, against 545 GB. md2's low point was 110 GB free (gen 465.6 GB with the sorter).

| table (mdbxmap) | original 005a19c | fixed | ratio |
|---|---|---|---|
| HashedAccounts | h6, 243,311 br / 11,698,671 lf, fill 0.50 / 0.50 | **h5, 62,420 / 5,929,695, fill 0.98 / 0.99** | pages 0.51x |
| AccountsTrie | h5, 80,853 / 6,069,768, fill 0.81 / 0.52 | **h5, 33,198 / 2,869,676, fill 0.94 / 0.57** | pages 0.47x |
| StoragesTrie | h5, 6,498,994 / 26,675,658, fill 0.50 / 0.24 | **h5, 2,188,495 / 12,582,207, fill 0.50 / 0.29** | pages 0.45x |
| HashedStorages | h5, 7,339,821 / 71,614,130, fill 0.50 / 0.27 | h5, 7,339,848 / 71,614,355 | unchanged (out of scope) |
| Bytecodes | 423 / 20,167 + 2,600,857 overflow | identical | unchanged |

The fixed HashedAccounts matches the in-place repack exactly (same page counts). The trie tables
halve in pages. Their rows are still `Put` in post-order, so leaf fill stays ~0.3-0.6; row counts
are to be read on the adopted store. The virgin copy (`mkvirgin`) started 04:45.

**Baseline started 05:18** (chain A, after the fix virgin was verified: copy hash and byte totals
equal; `/sa-gen-fix` removed, md2 back to 565 GB free).

**v2 jochemnet smoke (6 tests, DIO)** against the earlier DIO runs, measured-step seconds:

| test | vjsmoke (v2) | dj1 (v1) | xjh (v1 + forced hashed reads) | xs (state-actor) |
|---|---|---|---|---|
| BALANCE DIFF_MAX | 3.823 | 3.727 | 3.757 | 3.728 |
| BALANCE MINIMAL | 0.859 | 0.810 | 0.880 | 0.947 |
| BALANCE EXISTING_EOA | 0.847 | 0.117 | 0.860 | 0.929 |
| BALANCE NON_EXISTING | 0.842 | 0.114 | 0.873 | 0.902 |
| sload_bloated slots False | 0.837 | 0.138 | 0.870 | 0.703 |
| sload_bloated slots True | 0.864 | 0.104 | 0.899 | 0.712 |

The read switch was a faithful stand-in: real v2 jochemnet lands on the forced-hashed-reads times
within ~4%. The ~7x sequential-address gap belonged to the snapshot's legacy layout. Against v2, the
account rows sit at ~0.91 (tree shape, PR1's target), and state-actor is faster on bloated storage.
Many cells will sit close to the 1/1.1 = 0.909 edge of D, so D is read from both pairs, not one.

**v2 baseline (vj1 05:18, vs1, vj2, vs2 -> 12:06; all 266/266, DIO;
`results/baseline-v2.json`, class from vj1).**

| class | pair A | pair B | in ±10% | floor jochemnet | floor state-actor |
|---|---|---|---|---|---|
| >= 1 s (114) | **0.919** | **0.921** | 66 / 64 | 114/114 | 113/114 |
| < 1 s (152) | 0.975 | 0.984 | 48 / 61 | 99/152 | 97/152 |

Against v1 jochemnet under DIO the >= 1 s pairs were at parity (0.9998 / 1.0013), because v1 paid
for the Plain + Hashed double read on state-changing blocks (C9). v2 jochemnet doesn't. Against the
layout reth uses today, the original state-actor store is ~8% slower over a second.

**D = 83 of 266** (both pairs outside 1.1x on the same side, both floors inside ±10%): 45 over a
second, 38 under. state-actor is slower on 67 and faster on 16.

Exact counts from the collector (C15); the first version of this table was eyeballed.

| D cells (state-actor / v2 jochemnet, medians A / B) | tests | before | expected owner |
|---|---|---|---|
| sstore_bloated write_new_value_True | 4 | 0.761 / 0.764 | HashedStorages (untouched) + StoragesTrie (PR2) |
| ether transfers | 28 | 0.835 / 0.835 | PR2 (state-root trie rows) + PR1 |
| CALL / CALLCODE with value 1 | 16 | 0.855 / 0.842 | PR2 + PR1 |
| account rows, EOA / non-existing, value 0 | 10 | 0.892 / 0.891 | PR1 (HashedAccounts depth) |
| contract SAME_MAX, value 0 | 8 | 0.905 / 0.903 | PR1 |
| contract MINIMAL / JUMPDEST / DIFF_MAX, value 0 (sub-second) | 8 | 1.00-1.39 | code loading; noise-prone |
| ext_account_query_warm | 2 | 1.014 / 1.063 | noise-prone |
| sload / sstore_bloated without writes | 7 | 1.17-1.23 (state-actor faster) | HashedStorages dup subtrees (C11); untouched |

Collector fix: the DIO check now also reads `logs/v2b.out`, where chain A logged its runs.

**Fixed store adopted (chain B, 12:07-13:08).**
- Old S scratch dropped (md2 back to 1,274 GB free). Fixed virgin attached as loop0, new scratch
  fallocated as loop3, `init-from` clone in 53 min.
- Gate: HashedAccounts content hash on the scratch = `c1710919…2ff0`; 0 MB idle writes.
- **Smoke 6/6 passed**: reth runs newPayload on a store holding only alloy-rule trie rows, with no
  full-walk fallback. That settles the worry in state-actor's old comment.

| smoke test (single run, seconds) | fixed | original vs1 / vs2 | v2 jochemnet vj1 / vj2 | original / fixed | jochemnet / fixed |
|---|---|---|---|---|---|
| BALANCE DIFF_MAX | 3.666 | 3.819 / 3.759 | 3.871 / 3.664 | 1.034 | 1.027 |
| BALANCE MINIMAL | 0.815 | 0.942 / 0.939 | 0.838 / 0.854 | 1.153 | 1.038 |
| BALANCE EXISTING_EOA | 0.767 | 0.896 / 0.923 | 0.830 / 0.835 | 1.186 | 1.085 |
| BALANCE NON_EXISTING | 0.787 | 0.935 / 0.898 | 0.814 / 0.807 | 1.164 | 1.030 |
| sload_bloated slots False | 0.727 | 0.738 / 0.727 | 0.810 / 0.822 | 1.008 | 1.122 |
| sload_bloated slots True | 0.701 | 0.711 / 0.704 | 0.828 / 0.866 | 1.009 | 1.208 |

**Re-bench (fj1 13:08 -> fs2 19:44, then T2 t2jv/t2sf and maps to 19:59; all 266/266 and 14/14,
DIO checked per run; `FIX-EXIT 0`; `results/baseline-fix.json`).**

| class | original store (vs/vj) A / B | fixed store (fs/fj) A / B | in ±10% A/B before -> after | floors fixed j / s |
|---|---|---|---|---|
| >= 1 s (114) | 0.919 / 0.921 | **1.068 / 1.077** | 66/64 -> **84/82** | 114 / 114 |
| < 1 s (152) | 0.975 / 0.984 | 1.085 / 1.073 | 48/61 -> 68/72 | 110 / 97 |

**D verdicts (C16):** 47 fixed (both pairs in band), 16 improved, 17 unchanged, 3 worse.

| D group | n | before A / B | after A / B | verdicts |
|---|---|---|---|---|
| sstore_bloated write | 4 | 0.761 / 0.764 | 0.828 / 0.817 | 3 improved, 1 unchanged |
| ether transfers | 28 | 0.835 / 0.835 | **0.973 / 0.967** | **25 fixed**, 3 improved |
| CALL / CALLCODE value 1 | 16 | 0.855 / 0.842 | **1.017 / 0.988** | **11 fixed**, 5 improved |
| account rows EOA / non-existing | 10 | 0.892 / 0.891 | 1.082 / 1.093 | 4 fixed, 1 improved, 5 unchanged (flipped side) |
| contract SAME_MAX | 8 | 0.905 / 0.903 | 1.089 / 1.085 | 4 fixed, 4 unchanged (flipped side) |
| contract MINIMAL / JUMPDEST / DIFF_MAX (< 1 s) | 8 | 1.00-1.39 | 0.79-1.16 | 2 fixed, 4 improved, 2 worse (pairs disagree: 1.32 / 0.83, 0.80 / 1.29) |
| ext_account_query_warm | 2 | 1.014 / 1.063 | 0.970 / 0.908 | 1 fixed, 1 unchanged |
| sstore no-write / sload_bloated | 7 | 1.17-1.23 | 1.19-1.22 | 6 unchanged, 1 worse (1.12 -> 1.16-1.20) |

Outside D, 6 tests left the band in both pairs. All six are now state-actor faster (1.11-1.25):
BALANCE MINIMAL, DELEGATECALL DIFF_MAX, EXTCODESIZE JUMPDEST/EOA, STATICCALL JUMPDEST (value 0), and
one transfer to non-existent accounts.

**Why it overshoots: the fixed HashedAccounts is denser than any organic store** (C17,
`mdbxmap`):

| table, leaf pages / leaf fill / branch fill | v1 jochemnet (organic) | v2 jochemnet (migrated + rebuilt) | fixed state-actor |
|---|---|---|---|
| HashedAccounts | 8,194,914 / 0.59 / 0.69 | 8,194,914 / 0.58 / 0.69 (compaction kept pages) | 5,929,695 / **0.99 / 0.98** |
| AccountsTrie | 2,082,851 / 0.55 / 0.52 | 1,360,613 / **0.97 / 0.98** (MerkleExecute rebuild) | 2,869,676 / 0.57 / 0.94 |
| StoragesTrie | 10,367,535 / 0.68 / 0.57 | 6,849,633 / 0.77 / 0.98 (rebuild) | 12,582,207 / 0.29 / 0.50 |
| HashedStorages | 31,465,057 / 0.68 / 0.71 | same | 71,614,355 / 0.27 / 0.50 (untouched) |

T2 traces (distinct mdbx pages per measured step, timing from the 266-test runs):
- **Account reads** (BALANCE/CALL value 0):
  - Pages: fixed 86.3-87.9k, v2 jochemnet 93.7-95.4k, original 100.2-102.2k. All of the
    difference is in HashedAccounts.
  - Time: fixed 0.78-0.85 s, v2 jochemnet 0.83-0.92 s.
  - jv/sf ratio: 1.084-1.088 in pages against 1.05-1.10 in time. **Pages predict the time**, as in
    C5/C6.
- **Transfers and CALL value 1:**
  - Pages: fixed 116.9-128.4k, v2 jochemnet 104.3-114.6k, original 135.1-148.7k.
  - Time ratio 0.93-1.007: parity on time with 8-11% more pages.
  - The extra pages are AccountsTrie (47-56k against 40-48k): jochemnet's trie was rebuilt dense by
    the migration, whereas the fixed store's has organic fill (0.57, like v1's 0.55).
  - Fewer HashedStorages/StoragesTrie pages on the fixed store partly offset them.

**Verdict.**
- The two PRs remove the gap they target. Transfers and value-carrying CALLs are at parity:
  41 of the 44 D cells in those groups are fixed and 3 improved.
- Account-row cells crossed parity, ending ~8% on the fast side.
- That residual isn't a layout bug: sequential `Append` packs HashedAccounts to 0.99, while real
  nodes sit at 0.58-0.59.
- Storage cells are out of scope (HashedStorages, PR3) and stayed where they were.

**Candidate follow-up (not done, needs Anon's call).**
- Target organic fill in PR1: set `MDBX_opt_split_reserve`, which is exposed by our libmdbx
  (mdbx-go v0.40.1 `mdbx.h`). It reserves page space when splitting along the edge on ordered
  inserts. 0 = dense, max 32768 = half-page split.
- ~0.4 × 65536 ≈ 26,000 should land at a leaf fill of ~0.6.
- Unverified: whether the option applies to `MDBX_APPEND` puts. A 1 GB local run settles it in
  minutes.
- Cost: one more generation, copy, adopt and re-bench cycle, ~13 h.

**By family and duration class (2026-10-07).**
- Class membership is fixed from vj1 (>= 1 s: 114, < 1 s: 152) and used for both before and after.
- "In band" = both pairs within ±10%.
- `account_access` is split by account mode, with value 1 (CALL/CALLCODE only) and the
  `overhead_baseline_True` controls kept apart.

| >= 1 s family | n | before A / B | after A / B | in band before -> after |
|---|---|---|---|---|
| ether transfers (9 receiver cases) | 34 | 0.82-0.92 | 0.94-1.04 | 4 -> 31 |
| CALL/CALLCODE value, EOA / MINIMAL / SAME_MAX | 3 | 0.76-0.79 | 0.89-0.93 | 0 -> 0 |
| CALL/CALLCODE value, DIFF_MAX / JUMPDEST | 8 | 0.94-0.97 | 1.03-1.04 | 4 -> 8 |
| account reads EOA / NON_EXISTING / SAME_MAX / MINIMAL | 32 | 0.90-0.93 | 1.08-1.11 | 8 -> 9 |
| account reads DIFF_MAX / JUMPDEST (~4.7 s, code-heavy) | 32 | 1.02-1.04 | 1.09-1.10 | **31 -> 17** |
| sstore_bloated write | 1 | 0.73 | 0.83 | 0 -> 0 |
| sload / sstore_bloated no-write | 4 | 1.17-1.21 | 1.18-1.21 | 0 -> 0 |
| total | 114 | | | 47 -> 65 |

| < 1 s family | n | before A / B | after A / B | in band before -> after |
|---|---|---|---|---|
| CALL/CALLCODE value (EOA / MINIMAL / SAME_MAX / NON_EXISTING) | 13 | 0.82-0.90 | 0.99-1.11 | 0 -> 8 |
| account reads EOA / NON_EXISTING / SAME_MAX / MINIMAL | 32 | 0.90-0.91 | 1.06-1.09 | 4 -> 25 |
| sstore_bloated write | 3 | 0.77-0.78 | 0.80-0.83 | 0 -> 0 |
| sload / sstore_bloated no-write | 4 | 1.13-1.18 | 1.17-1.21 | 0 -> 0 |
| ether transfers to non-existent | 2 | 1.05-1.07 | 1.26-1.27 | 1 -> 0 |
| ext_account_query_warm | 14 | 1.07-1.09 | 1.02 | 2 -> 6 |
| sload_same_key | 4 | 0.98-1.08 | 0.96-1.03 | 1 -> 3 |
| overhead controls (~0.06 s) | 80 | 1.06-1.18 | 1.03-1.25 | 9 -> 5 (noise-limited) |
| total | 152 | | | 17 -> 47 |

The code-heavy account reads were at parity before and are now at the +10% edge: the same density
shift, on tests whose time is mostly code loading. Their loss of band (31 -> 17) is the main cost
of the overshoot in the >= 1 s class.

## Root causes per family (2026-10-08, research + debate)

Five read-only research agents covered reth acf6e175, both libmdbx copies, the state-actor writer,
host page attribution and EEST semantics. Their reports are `local://rc-*.md`, summarized in the
plan `plans/2026-10-08-reth-layout-root-causes.md`.

**No geth-journal analogue in reth.**
- Every cross-block cache is in-process: execution cache, preserved sparse trie, the per-block
  storage-root map, ChangesetCache.
- RocksDB history is write-only on the hot path; static files are read only by BLOCKHASH; there are
  no persisted trie changesets.
- The env is identical for both stores (libmdbx 0.13.12, WriteMap, MADV_RANDOM, 4 KiB pages).
- The two arms replay byte-identical workloads: 266 BALs decoded, 0 mismatches.

**libmdbx.**
- state-actor links mdbx-go v0.40.1 = libmdbx 0.14.2; reth vendors 0.13.12.
- `prefer_waf_insteadof_balance` defaults to true in 0.14.2 and false in 0.13.12. Random-insert
  fill is 0.505 vs 0.661, which partly explains the original store's 0.50.
- Fill follows key order: sorted Put is byte-identical to APPEND.
- `MDBX_opt_split_reserve` (0.14.2 only, enum 21) is a smooth dial: r=0 -> 0.99, 16384 -> 0.74,
  24576 -> 0.61, 32768 -> 0.51. It acts on leaf and branch together and on nested trees.
- Both options are plain env fields read at split time, with no txn guard
  (mdbx.c:10009-10073). They can be switched per table phase.
- `mdbx_dbi_stat` already counts nested dupsort pages.

**Per-table facts** (host, read-only):
- J v1 and J v2 HashedAccounts have the same leaf count (8,194,914): the compacting copy preserves
  pages.
- Bytes per entry, J vs S: HashedAccounts 44 vs 45; HashedStorages main 197 vs 81 (S's keys are
  N_TREE records); StoragesTrie 301 vs 226.
- The bloated contract `0x87a6…be04` (the same rows in both stores, StoragesTrie 25,758,807):

  | nested tree | J | S fixed |
  |---|---|---|
  | HashedStorages: height, leaf / branch pages, leaf / branch fill | h5, 5.54M / 103.6k, 0.72 / 0.61 | h5, 3.81M / 43.8k, 0.99 / 0.98 |
  | StoragesTrie: height, leaf / branch pages, leaf / branch fill | h7, 1.28M / 90.9k, 0.97 / 0.90 | h8, 2.34M / 257.1k, 0.53 / 0.82 |

- Per-contract storage size: S p10/p50/p90 = 141/254/368 slots, 98% nested. J has p50 = 1 and
  97.8% inline (<= 28 slots), while 0.07% of contracts hold 52.7% of all slots. Autofill's
  truncated normal (plan.go:106-120) is not mainnet-shaped.
- T2 attribution reaches 99.98% (J) / 96-100% (S). S's write-heavy tests carry 13.7-17.4k
  "other" pages: nested leaves of autofill storage with 64-byte items, inside the in-use region.
  - Stale tail refuted: 0 of those pages are >= geo.next, and S's file has no holes.
  - Sibling storage-root recomputation is confirmed in reth's code: roots are never stored, there
    is no EOA shortcut, and reth walks the leaves where rows are missing.
  - A lowest-branch sample of the modified accounts attributes 0.7-0.9% of those pages directly
    (ceiling ~25-37%). Ancestor-level siblings are still to be counted (plan step 0).

**Causes per family:**
- **Account reads** (1.07-1.10): HashedAccounts too dense, 0.99 vs 0.59. A distinct-page model
  reproduces the traces (J 94k, S 86.5k).
- **Code-heavy reads** (1.09): the same cause, plus J's larger Bytecodes B-tree (+3% for S).
- **CALL with value / transfers** (0.90-0.95 / 0.945-1.04):
  - AccountsTrie in post-order at 0.57 vs J's rebuilt 0.97;
  - plus nested-storage walks of mid-size autofill contracts, amplified by random subkey order.
- **sstore write** (0.81-0.83): the bloated contract's StoragesTrie nested tree, sparse and one
  level taller.
- **sload / no-op sstore** (1.19-1.20): the bloated contract's HashedStorages nested tree, too
  dense.

**Plan, debated:**
- PR3: key-ordered writes for tries, autofill subkeys and Bytecodes. Root-preserving.
- PR4: `--fill-profile fresh|migrated|aged`; prefer_waf=false always; split_reserve per phase.
  Default `fresh`; the benchmark uses `migrated`.
- One regeneration with PR3+PR4.
- PR5 (mainnet-shaped autofill storage, root-changing) only if cycle 1 misses acceptance:
  - every >= 0.5 s family median in band;
  - >= 80% of >= 0.5 s tests in band.

## Cycle 1: PR3 + PR4 (2026-10-08)

**Branch.** `reth-fill-control` (worktree `~/dev/state-actor-wt-fill`, uncommitted), staged tree
`1ba27c2c`.
- **PR3**, key-ordered writes: `trieGroupWriter` buffers AccountsTrie rows per 2-nibble prefix and
  flushes them sorted. StoragesTrie rows are sorted per entity and per contract. Autofill
  HashedStorages slots go in keccak(slot) order.
- **PR4**, page fill: `--mdbx-fill-profile fresh|migrated|aged` plus `--mdbx-fill` overrides.
  `prefer_waf_insteadof_balance=0` always, read back. `split_reserve` is switched per table on the
  writing thread. The realised profile is recorded in the manifest.
- Non-cgo and cgo suites pass. The 4 failing scripts/* also fail on origin/main.

**Local verification** (1 GB, seed 42), builds T12 / T123 / fresh / migrated:
- All four keep state root 0x20a19dfe… and identical content hashes in all five tables.
- AccountsTrie leaf fill 0.525 -> 0.962 (h4 -> h3, 8,720 -> 4,671 leaves).
- HashedAccounts at `migrated`: 0.591.
- Autofill nested HashedStorages: 0.527 (T12), 0.891 (PR3), 0.715 (`migrated`).
- Scaled bloated contract (2M slots), T12 -> `migrated`:
  - HashedStorages nested 0.992 -> 0.725;
  - StoragesTrie nested 0.58 h6 13,082 leaves -> 0.960 h5 7,911 leaves.
- A second `migrated` run is identical in hashes and pages. Generation time 57 s -> 36 s.

**Step 0 (host, `rc/fillgate.py` on both virgins).**

| measure | J | S fixed (PR1+2) |
|---|---|---|
| mid-size (29-4000-slot) contracts, nested HashedStorages leaf fill, mean / page-weighted | 0.725 / 0.786 | 0.531 / 0.518 |
| HashedStorages main tree only: leaves, leaf fill | 2.02M, 0.67 | 0.63M, 0.27 |
| StoragesTrie main tree only: leaves, leaf fill | 0.12M, 0.77 | 1.89M, 0.29 |
| bloated HashedStorages nested leaf fill, uniform sample | 0.682 | 0.993 |
| Bytecodes: entries, leaf / branch / large pages | 2.44M, 229k / 3.5k / 5.69M | 0.71M, 20k / 423 / 2.60M |

- The catalog leaf/branch counts of a DUPSORT table include its nested trees. §9's
  distinct-key estimate is superseded: J has ~28.9M accounts with storage, S ~10.1M.
- The bloated-contract J figure of 0.724 used earlier was a descent sample. Matching J's 5.54M
  leaves needs fill 0.683.

**Decision: `migrated` HashedStorages = 0.70.** It is one env-wide value: J's bloated contract is
at 0.68 and its mid-size contracts at 0.72-0.79. Bloated leaves come out ~2.4% fewer than J's,
and mid-size within 0.03.

**Noise** (|ln(A/B)| between the two pairs, >= 0.5 s): median 0.015-0.020, p90 0.043-0.049.

**Host gates.** `rc/gatecheck.py` plus `cfg/g-fill-targets.json`:
- HashedAccounts 0.56-0.62; AccountsTrie >= 0.93;
- bloated HashedStorages nested h5, 0.67-0.73;
- bloated StoragesTrie nested h <= 7, >= 0.93;
- mid-size nested 0.63-0.77;
- bloated item counts equal.

Checked against existing data: it fails the S-fixed store on the six metrics this cycle moves,
and passes J on all fill metrics.

**Incident.** The S scratch lost its dm-era device. A read-only mount of the S virgin
(`/mnt/rc-sf`, from the step-0 agent) overlapped the reference-hash job, and `schelk recover`
then failed ("Incremental recovery is not possible").
- Fix: unmounted; `schelk full-recover` runs inside `sfix-hash.sh`.
- `repack` gained DupSort flags on open (it got MDBX_INCOMPATIBLE on HashedStorages/StoragesTrie).
- Rule: never mount a virgin while its schelk scratch is in use.

**Launched 15:08.**
- tmux `rc-hash`: full-recover + the five reference hashes -> `logs/sfix-tables-hash.ref`.
- tmux `reth-g` (`stage3.sh`): build, gen (`--mdbx-fill-profile=migrated`), gen-check (content
  identity + fill gate), mkvirgin, adopt, gate, smoke, T3 traces (21 tests) and maps, stop at
  `T3-DONE`.
- `stage3.sh bench` then runs gj1 gs1 gj2 gs2.

**Generation and gen-check (2026-10-08, 15:08-21:12).**
- Build ok. Generation took 3 h 48 min with `--mdbx-fill-profile=migrated`, sharing md2 with the
  full-recover and hash job. State root 0x48d611bb… is identical.
- Store size 366.9 GB (PR1+PR2 431 GB, original 545 GB).
- All five content hashes equal the S-fixed reference (`logs/sfix-tables-hash.ref`):
  - HashedAccounts c1710919…, 430,696,738;
  - AccountsTrie 865f13d2…, 32,156,059;
  - HashedStorages 35688803…, 2,214,906,890;
  - StoragesTrie 87e6247b…, 173,951,381;
  - Bytecodes 0f6b2867…, 712,413.

| fill gate | J | S fixed (PR1+2) | S g (PR1-4, migrated) |
|---|---|---|---|
| HashedAccounts leaf fill / leaves | 0.583 / 8.19M | 0.993 / 5.93M | **0.591 / 9.96M** |
| AccountsTrie leaf fill / leaves | 0.966 / 1.36M | 0.567 / 2.87M | **0.965 / 1.68M** |
| bloated HashedStorages nested: height, leaf fill | h5, 0.682 | h5, 0.993 | **h5, 0.711** |
| bloated StoragesTrie nested: height, leaf fill | h7, 0.968 | h8, 0.533 | **h7, 0.969** |
| mid-size HashedStorages nested leaf fill | 0.725 | 0.531 | **0.703** |
| HashedStorages main tree leaf fill (not gated) | 0.670 | 0.272 | 0.292 |
| StoragesTrie main tree leaf fill (not gated) | 0.767 | 0.285 | 0.310 |

The main trees stay sparse even with prefer_waf=false.
- [INFERENCE] Each contract's dups first grow as an inline subpage in the main leaf (up to ~2 KB,
  splitting it), then collapse to a 48-byte N_TREE record at 28 items, which leaves the leaf
  mostly empty.
- S's main tree still has about a third of J's leaves (0.63M vs 2.02M), because S has fewer
  accounts with storage, so it is not a slow-side term.

**Adopt, smoke, trace preview (21:12-22:41).**
- Virgin `reth-sa-g-virgin.img` copied and verified. The S-fixed scratch was dropped (its virgin
  stays on md3). Adopted in 35 min; 0 MB idle writes; smoke 6/6.
- T3 traces 21/21 on both arms, but the page tracer recorded nothing (see the incident below).
- Timing preview from those single traced runs (S g / J, throughput):

| test | PR1+PR2 store (2-pair geomean) | S g (one trace each) |
|---|---|---|
| BALANCE / CALL value 0, EOA / MINIMAL / SAME_MAX / NON_EXISTING | 1.05-1.10 | 0.94-1.02 |
| BALANCE / CALL on DIFF_MAX / JUMPDEST | 1.06-1.09 | 1.03-1.07 |
| CALL value 1 (EOA / MINIMAL / SAME_MAX) | 0.92-0.93 | 0.94-0.96 |
| sload 160M / 240M, sstore no-write | 1.13-1.17 | 0.98-1.02 |
| transfers (4 cases) | 0.97-1.01 | 0.98-1.02 |
| sstore write (0.18 s) | 0.87 | 0.93 |

**Incident: ops maintenance at 21:50-21:54.**
- User `devops` ran Ansible: `apt-get dist-upgrade` (libc6, systemd, python3.12, docker, kernel
  6.8.0-146 installed), then `autoremove --purge`, which removed bpftrace, bpfcc and linux-tools.
- The running kernel (6.8.0-111) and podman 4.9.3 are unchanged. All gj/gs runs come after the
  upgrade, so the comparison stays within one environment.
- `/var/run/reboot-required` has been set since 21:53. A reboot mid-run would kill it and the
  dm-era state; the host was last rebooted May 5.
- bpftrace was reinstalled (marked manual) and the tracepoint verified. The traces re-run after
  the bench.

**Bench launched 22:47.** tmux `reth-g`: `stage3.sh bench` (gj1 gs1 gj2 gs2, 266 each, DIO;
reduce -> `results/baseline-g.json`), then the T3 traces, maps and `t3classify.sh` again.

**Cycle 1 result (bench 22:47-05:19; all four runs 266/266, DIO checked; collector C18, 0
failed checks; `results/baseline-g.json`).** **Accepted, so cycle 2 (PR5) is not triggered.**
(superseded 2026-10-09: Anon asked for cycle 2 anyway, to aim at every >= 0.5 s test in band; see
"Cycle 2" below.)

| >= 0.5 s tests (154) | original | PR1+2 | PR1-4 `migrated` |
|---|---|---|---|
| per-test geomean in ±10% | 46.1% | 77.3% | **97.4%** |
| >= 1 s class median, pair A / B (114 tests) | 0.919 / 0.921 | 1.068 / 1.077 | **0.994 / 1.000** (110/112 per pair in band) |
| floors (jochemnet / state-actor) | 114 / 113 | 114 / 114 | 114 / 114 |

| family (>= 0.5 s), median of per-test geomean | n | original | PR1+2 | PR1-4 | robust (each pair in band) |
|---|---|---|---|---|---|
| account reads | 64 | 0.90-0.91 | 1.08-1.09 | **0.951** | yes |
| account reads + value (CALL/CALLCODE) | 6 | 0.78-0.79 | 0.91-0.93 | **0.943** | yes |
| code-heavy reads | 32 | 1.034 | 1.090 | **1.057** | yes |
| code-heavy reads + value | 8 | 0.958 | 1.034 | **1.014** | yes |
| ether transfers | 34 | 0.839 | 0.978 | **0.994** | yes |
| sload_bloated | 4 | 1.16-1.19 | 1.19 | **1.072** | yes |
| sstore no-write | 4 | 1.17-1.19 | 1.20 | **1.063** | yes |
| sstore write | 2 | 0.73-0.77 | 0.81-0.83 | **1.047** | yes |

Below 0.5 s, only the transfers to non-existent accounts (2 tests, 0.28 s) fall outside
[0.8, 1.25], at 1.27. The overhead controls moved 1.14 -> 1.07.

**Trace attribution** (T3, 21 tests per arm, `rc/classify3.py`; pages J / S g):

| family | pages | where |
|---|---|---|
| account reads | 94.1k / 98.7k | all HashedAccounts. +4.9% = S's 21% more accounts at matched fill (model said 98-100k). Bench 0.951 |
| code-heavy reads | 488k / 471k | Bytecodes leaf+branch 46.6k / 15.2k (J's 3x larger code table), overflow equal. Bench 1.057 |
| CALL value 1 | 104k / 113k | AccountsTrie 44.2k / 46.5k (was 51.6k); HashedStorages main 23.2k / 18.8k; StoragesTrie main 5.8k / 3.0k; other (nested autofill walks) 0.9-1.1k / 11.4-12.4k (was 15.6k) |
| transfers | 114k / 123k | same structure (other 0.7k / 10.9-13.8k). Time is less page-bound: pages 0.92, bench 0.994 |
| sload / no-op sstore | 96.0k / 94.0k (bloated nested) | was 83.7k. Pages 1.02, bench 1.06-1.07 |
| sstore write | 18.2k / 17.9k | StoragesTrie nested 13.0k / 12.9k (was 18.3k). Bench 1.04-1.05 |

**Residuals left, all in band:**
- account count (+21%);
- the Bytecodes population;
- autofill storage shape (every contract nested at ~256 slots vs mainnet's p50 = 1): PR5
  territory.

sload stays ~7% fast with only 2% fewer pages. [INFERENCE] The rest is denser nested branches
(0.71 vs 0.61) or the physical layout of sequentially written leaves; not chased (< 10%, stop rule).

**PR chain prepared, not signed.**
- `/tmp/rc-tools/commit-prs.sh` signs 5 commits from the measured trees:
  - PR1 `1d584e6f` and PR2 `412548d0`, each on 005a19c;
  - PR2' `fda9634c` stacked on PR1 (the CHANGELOG conflict resolved), then PR3 `d6e46fdf`, then
    PR4 `1ba27c2c`.
- It updates the branches `reth-hashed-accounts-key-order`, `reth-trie-rows-alloy-rule`,
  `reth-key-ordered-writes` and `reth-fill-control`.
- Upstream main is still 005a19c (ls-remote 2026-10-09).
- PR bodies are drafted with the tables above. It needs Anon: 5 key touches, then the push and
  `gh pr create --draft`.

## Cycle 2: PR5 + J's account count (2026-10-09)

**Ask.** Anon: re-run with PR5 on top and try for 100%. Delete the original store image (done:
`/data/schelk-vols/reth-sa-virgin.img`, checked unattached and unreferenced; `/data` 2006 GB free).

**What cycle 1 left out of band** (per-test geomean, >= 0.5 s; C18 `out_of_band`):

| test | geomean | pairs | cause / what cycle 2 changes |
|---|---|---|---|
| EXTCODEHASH NON_EXISTING 240M | 0.904 | 0.893 / 0.916 | HashedAccounts lookups, S +21% accounts -> J's count |
| transfer diff_to_contract 240M | 0.897 | both out | sibling storage-root walks of nested autofill contracts -> PR5 |
| sstore existing_True no-write 160M / 240M | 1.104 / 1.114 | both out | bloated contract only (same rows both stores): S's tree denser -> HashedStorages fill 0.67 |

**PR5 (`reth-storage-model`, worktree `~/dev/state-actor-wt-storage`, tree `d031319a` on PR4
`1ba27c2c`, uncommitted).**
- `--storage-model=normal|mainnet`. `mainnet` draws each contract's slot count (28-entry small
  CDF + 97 log-spaced tail knots to 2^24) and each value's significant length (32-entry CDF)
  from the exact J walk (`rc/jwalk.py`, bloated contract excluded). Contract count =
  storage budget / 140 B per slot / mean 53.821 slots, taken out of the account budget, so the
  total account count is the same under both models. Manifest records it; `reproduce` restores it.
- Tests: `go test ./...` and the cgo suite (`sa-builder:local`, `-tags cgo_reth`) pass. CHANGELOG
  and README updated.
- 1 GB, seed 42: two runs give root `0x327081…7fce`; **geth writes the same root**. Normal model
  for contrast: `0x20a19d…6f7e`.

| 1 GB storage shape (exact walk) | J (exact, full) | S mainnet 1 GB | S normal 1 GB |
|---|---|---|---|
| slots per storage account p50 / p90 / p99 | 1 / 10 / 154 | 1 / 10 / 152 | 256 / 365 / 455 |
| one slot / <= 28 / 29-4000 (account share) | 0.550 / 0.971 / 0.028 | 0.550 / 0.971 / 0.028 | 0 / 0.002 / 0.998 |
| 20-byte values | 0.498 | 0.493 | 0 |

`rc/distgate.py` bounds these on the generated store and the account total (+-0.1% of J's
354,792,873); the normal model fails 7 of its bounds.

**Sizing.** J's HashedAccounts holds 354,792,873 accounts (`probe/joc-stats.txt`); the spec adds
1,200,012. `--target-size=295061MB` gives 353,593,006 autofill accounts (28,742,858 contracts),
354,793,018 in total (+145). Autofill slots come out at ~1.547B vs J's 1.487B (+4%): the fixed
20/70 split cannot match both, and accounts are the measured term. (The earlier `289GB` candidate
double-counted the spec's accounts, superseded.)

**HashedStorages fill 0.67** (`--mdbx-fill=HashedStorages=0.67` on top of `migrated`). The bloated
contract's tree was the only difference left on the sload/sstore families: S g leaf 0.711 / branch
0.71 vs J 0.682 / 0.61 (same method), and those families ran 5-11% fast. Cycle 1 landed 0.011
above the setting, so 0.67 targets J's 0.68. Gate tightened to [0.66, 0.70].

**HashedStorages main tree, a residual.** On 1 GB mainnet-model stores, main-tree leaves per
storage account vs the HashedStorages fill setting:

| setting | 0.55 | 0.60 | 0.65 | 0.70 | 0.75 | 0.80 | 0.85 | J |
|---|---|---|---|---|---|---|---|---|
| leaves / account | 0.0876 | 0.0878 | 0.0888 | 0.0908 | 0.0929 | 0.0963 | 0.1007 | 0.0802 |

- Denser settings give more leaves: each contract's dups are inserted one by one and grow its inline
  sub-page in place, so a small reserve forces more splits.
- libmdbx's sub-page defaults are identical in reth's 0.13.12 and mdbx-go's 0.14 (limit 100%, room
  threshold 0, reserve prereq 42%, reserve limit 4.2%); only merge_threshold differs (25% vs 33%),
  which only deletes use.
- [INFERENCE] J's remaining density is its insertion history; no generator setting reaches it.

**Fixtures refilled by reth.** The genesis changes, so S's fixtures must be refilled.
- benchmarkoor's builder refuses reth as a fill-stateful filler.
- Stock acf6e17's `testing_buildBlockV1` builds the BAL and then drops it (V5 envelope with
  ExecutionPayloadV3), so EEST's `engine_newPayloadV5` fails ("missing field blockAccessList").
- `build-reth-fill.sh` patches 2 files to return the V6 envelope (ExecutionPayloadV4 with the BAL)
  and builds acf6e17 without default features (the JIT needs LLVM 22 and does not change EVM
  results): image `localhost/reth-fill:acf6e17-bal`, used only to fill. Every measurement keeps
  `devnet7-sigkill`.
- `refill.sh` replays the nethermind fill's recorded invocation (EEST 13b79138, gas 160,240,
  stubs filtered to `bloated_eoa_10GB`).
- Trial on S g: 2/2 filled; `rc/fxcmp.py` finds them shape-identical to the nethermind fixtures
  (gas used, tx count, BAL bytes, newPayload version per payload); benchmarkoor smoke on S g 2/2
  passed.
- A full refill on S g (`/data/fixtures/sa-g-reth`) runs alongside, to compare every common test
  with the nethermind fill.

**Root check by reth.** `reth db repair-trie --dry-run` rebuilds every account and storage trie node
from the hashed tables and compares each with the stored node, root included.
- Read-write opens run genesis init, which rejects the store (the chainspec has no alloc).
- A read-only open cannot add the BAL column family this RocksDB lacks, so RocksDB is moved aside
  (repair-trie reads only MDBX).
- Read-only still writes `reth.toml` and RocksDB dirs, so the check runs on the restored scratch.
- 1 GB test: 0 inconsistencies in 9 s.

**Driver** `stage4.sh` (tmux `rc-stage4`, `logs/stage4.out`, markers `logs/h.done/`), relaunched
10:16 CEST. Steps:
1. build `localhost/state-actor-reth:storage-model` from `state-actor-storage/` (= tree d031319a);
2. gen into `/sa-gen-h`;
3. gen-check: table hashes (the new reference), fillgate + gatecheck, jwalk + distgate;
4. mkvirgin `reth-sa-h-virgin.img`;
5. drop the S g scratch, after the refill;
6. adopt;
7. gate-s;
8. rootcheck;
9. refill `/data/fixtures/sa-h-reth`;
10. hsmoke;
11. t3sh trace, map and classify (J's t3jg reused: same store, same binary);
12. hj1 hs1 hj2 hs2, 266 each, DIO;
13. `reth_reduce.py h`.

The collector gains C19 (four-store progression, acceptance on h, out-of-band list, storage shape,
T3 pages). A partial collection leaves every existing claim unchanged.

**Generation (10:31-14:24, 3 h 50 min).** Root `0x4a688484…6ef79f`; 326,050,160 EOAs +
28,742,858 contracts = 354,793,018 accounts (planned 354,793,018; J 354,792,873); 232 GB (cycle 1:
367 GB). Phases: spec storage, EOAs, contracts at 2.1-2.5k/s (≈113k slots/s, like cycle 1's per-slot
rate), account trie at 367k accounts/s. Memory available stayed at 90-91 GB.
**gen-check (14:24-15:38), every gate passed.**
- Rows: HashedAccounts 354,793,018; AccountsTrie 26,908,769 (J 26.9M; cycle 1 32.2M); HashedStorages
  1,809,225,187 (J 1,822,629,119); StoragesTrie 153,793,392 (J 157.4M); Bytecodes 1,476,799.
- Fill (gatecheck): HashedAccounts leaf 0.591; AccountsTrie 0.968; bloated HashedStorages h5, leaf
  **0.677** (J 0.682, cycle 1 0.711); bloated StoragesTrie h7, 0.969; mid-size HashedStorages 0.674
  (J 0.725). Main trees: HashedStorages leaf 0.601 h5, StoragesTrie 0.434 h4.
- Shape (distgate, J / new): storage accounts 25,166,498 / 28,892,859; p50 / p90 / p99 / p99.9
  1 / 10 / 154 / 4670 vs 1 / 10 / 153 / 4675; one slot 0.550 / 0.552; <= 28 0.971 / 0.971;
  29-4000 0.0277 / 0.0275; 20-byte values 0.498 / 0.499; main-tree leaves per storage account
  0.0802 / 0.0892 (+11%, the accepted residual).
- mkvirgin 15:38-15:53 (copy verified), S g scratch dropped (md2 1264 GB free), adopt 15:53-16:15,
  gate-s 0 MB idle writes.
- rootcheck 16:21-18:00: `reth db repair-trie --dry-run` exit 0 in 98 min, **0 inconsistencies**
  (every account and storage trie node, root included).

**Wipe (17:00, Anon: "whatever snapshot or reth backup … not gonna be used anymore, just wipe it").**
Checked unattached, unmounted, not in any schelk state and not open, then deleted:
`reth-joc-virgin.v1.img` (the v1 jochemnet backup from before migrate-v2), `reth-sa-virgin.repacked.img`,
`reth-sa-fix-virgin.img`, `/data/fixtures/refill-trial-g`, `fixtures/sa-v2-full` (the nethermind fill
of the deleted stores' genesis) and the empty `/data/spill-reth`. `/data` 1774 -> 4202 GB free.
`mkcfg.py`'s default S fixtures are now `/data/fixtures/sa-h-reth`. Kept until the cycle-2 bench passes:
`reth-sa-g-virgin.img` and `/data/fixtures/sa-g-reth`. Pre-reth fixtures (July-September, other
clients' studies) untouched.

**Pipeline after the gates.** Refill 18:00-18:27: 456 filled, 0 unexpected failures (the same 112
stub-dependent failures as every fill), shape-identical to the S g reth fill on 450/456 tests (the 6
differ in BAL bytes only). hsmoke 6/6; t3sh 21/21, mapped and classified. Bench hj1 18:39, hs1
20:39, hj2 21:51, hs2 23:51-01:03 (10-10): 266/266 each, DIO checked; `results/baseline-h.json`.
Then the cycle-1 store went: `reth-sa-g-virgin.img` and `/data/fixtures/sa-g-reth` wiped (10-11
08:55). Only `reth-joc-virgin.img` (J) and `reth-sa-h-virgin.img` (S) remain; `/data` 4544 GB free.

**Cycle 2 result (collector C19, 0 failed checks, all 14 verdicts supported).** Accepted.

| >= 0.5 s tests (154) | original | PR1+2 | PR1-4 | PR1-5 |
|---|---|---|---|---|
| per-test geomean in ±10% | 46.1% | 77.3% | 97.4% | **99.4%** (153) |
| >= 1 s class median, pair A / B | 0.919 / 0.921 | 1.068 / 1.077 | 0.994 / 1.000 | **1.0175 / 1.0168**, 114/114 each |
| floors (jochemnet / state-actor), >= 1 s | 114 / 113 | 114 / 114 | 114 / 114 | 114 / 114 (1.0014 / 1.0005) |

| family (>= 0.5 s), median of per-test geomean | n | PR1-4 | PR1-5 | robust |
|---|---|---|---|---|
| account reads | 64 | 0.951 | **0.970** | yes |
| account reads + value | 6 | 0.943 | **0.983** | yes |
| code-heavy reads | 32 | 1.057 | **1.034** | yes |
| code-heavy reads + value | 8 | 1.014 | **1.020** | yes |
| ether transfers | 34 | 0.994 | **1.033** | yes |
| sload_bloated | 4 | 1.072 | **1.054** | yes |
| sstore no-write | 4 | 1.063 | **1.046** | yes |
| sstore write | 2 | 1.047 | **1.034** | yes |

**The mechanism, from the T3 traces** (pages per test, J / S g / S h):
- CALL value 1 to EOA: total 104,272 / 113,408 / 109,425; "other" (nested-storage walks) 1,113 /
  12,382 / **1,313**.
- transfer diff_to_contract: total 114,142 / 122,988 / 118,975; other 716 / 10,862 / **1,077**.
- Account reads 94.8k / 99.4k / 97.8k: the account-count match took out about two thirds of the
  HashedAccounts excess (0.951 -> 0.970).

**Still out (1 of 154):** sstore_bloated existing_slots_True write_new_value_False 160M (J 0.85 s),
1.107 (pairs 1.119 / 1.095; floors J 1.016, S 0.994). It reads only the bloated contract (same rows
in both stores). The fill correction (0.711 -> 0.677) moved its 240M twin and the sload family (1.072 ->
1.054) but left it where it was (1.104 -> 1.107). Under the plan's stop rule (two regenerations, don't
chase < 3%), it stays a known difference. [INFERENCE] What remains is the bloated tree's physical
layout (sequentially written leaves), not fill.
- Over a second state-actor now leans 1.7% fast (from 0.6% slow); below the 3% rule.
- Below 0.5 s only the transfers to non-existent accounts stay outside [0.8, 1.25] (1.30).

**Article.** First version in `articles-wt-reth-article/reth-state-db-divergence/`
(`gen_reth_state_db_report.py`, 11 figures, README; branch fast-forwarded to main `246de7f`, all
uncommitted). Rendered from the C19 data; `build_site.py` builds with the new card.

**PR chain.** PR5 body written (`/tmp/rc-tools/pr-bodies.md`). `commit-prs.sh pr5` signs all six
commits (PR1, PR2, PR2', PR3, PR4, PR5); `open-prs.sh pr5` pushes to the fork and opens drafts.
Upstream main still 005a19c (= #141).

**Article review (10-11, with Anon).** Fixes against the results:
- the account count is credited to sizing, not PR5;
- the sub-0.5 s caveat now states the measured fact (no self-reproduction) instead of a boot claim;
- the EOA-sibling sentence no longer contradicts itself;
- reader-facing wording, with no "the plan" and no build note;
- the residual bullet names its 240M twin that came back into band (1.114 -> in band);
- the Bytecodes bullet says which way that family leans (3% fast).
- Title moved to the series form.
- Published data scrubbed of host details (provenance host/root dropped, C14 script basenames).
- Narrow screens: tables scroll in their own box, captions below.
- Staged in `articles-wt-reth-article`.

**PRs opened (10-11, Anon's key).** `commit-prs.sh pr5` signed six commits (subkey
`62045F34B97177DD`; each tree checked against the benchmarked one):
- PR1 `27115b26` (tree 1d584e6f) and PR2 `feb184a1` (412548d0), each on 005a19c;
- PR2' `7ac00e1b` on PR1, PR3 `40842e61` (d6e46fdf), PR4 `198d285d` (1ba27c2c), PR5 `dcd77290`
  (d031319a).

`open-prs.sh pr5` pushed the branches to CPerezz/state-actor and opened **drafts** against
ethereum/state-actor main:
- #143 PR1, #144 PR2;
- #145 PR3 (3 commits), #146 PR4 (4), #147 PR5 (5).

GitHub verifies the signatures. Nothing is merged.

**Article rewrite (10-11, Anon: less text, more figures, like the setcodefrom and FCR+EEZ articles;
no MDBX option names or PR internals).**
- 3221 -> 1313 words (912 prose, 401 captions); 11 -> 13 figures; 4 tables -> 0.
- Each section is now: figure, then a few sentences of mechanism. Numbers live in the captions, and
  prose doesn't repeat them.
- New figures: the six-cause map (Figure 2) and share-in-band per store (Figure 12).
- The fill-dial axis is "room left free when it splits"; the trie diagram drops the
  post-order/key-order labels.
- The collector adds `C19.rootcheck_inconsistencies` (0, from `logs/h-rootcheck.log`), so "nothing
  to repair" is data-backed. Restaged: 23 files.

**Review round 2 (10-13, Anon).** Article: finding 1 in plain language, finding 2 leads with "jochemnet
v1, state-actor v2", "why the shape matters" as a list, the overshoot line deleted (1343 words).

**StoragesTrie gap, explained.**
- Whole table: J 6.85M leaf pages vs PR1-5 6.89M, the same size. The difference is the top-level
  (per-contract) tree: J 115.5k leaves at fill 0.77 vs PR1-5 238k at fill 0.43.
- 238k/115.5k = 2.06: about 1.77 from fill and 1.15 from PR1-5's 15% more storage accounts.
- Cause: `contracts_writer_cgo.go:81-90` writes each contract's StoragesTrie rows at generation
  time, sorted within the contract (PR3) but in random address order across contracts. That gives
  mid-page splits. J's tries were rebuilt by reth's pipeline in address order.
- Cost: PR1-5 reads 7.2-8.6k StoragesTrie top-level pages per value-transfer test vs J 5.3-6.3k,
  2.1k more on average. PR5's cut of about 10k sub-tree walk pages outweighs it.
- Fix: write StoragesTrie in address order (a spill-and-sort pass, or a key-ordered rebuild like
  reth's). Not chased: the affected families are in band. A candidate PR6.

**PR5's tail (Anon: "not future-proof? obsolete at 1 TB?").** From the exact J walk (bloated
contract excluded):
- The body is stable: 97.1% of contracts hold <= 28 slots but only 4.8% of slots.
- Above about 10^4 slots the tail is a power law: log-log CCDF slope 0.95-1.17 from 10^4 to
  3x10^6, MLE alpha 1.005 at xmin 10^4. Contracts above 10^5 slots hold 54% of all slots.
- The 2^24 cap removes 4 contracts (17.1M, 20.7M, 21.4M, 141.1M slots) holding 13.5% of slots.
  PR5 sizes the contract count from the capped mean (53.8 vs 59.1), so it makes 9.8% more
  contracts instead. With the +4% budget, that gives the measured +15% storage accounts.
- At scale: an alpha ~1 tail makes the largest contracts grow roughly with the contract count. A
  fixed table capped at 2^24 can't follow, so the error grows with the target size, in the tail.
- Benchmark results are unaffected by this: they depend on the body (siblings in the account trie).
- Article: a "largest contracts" line added under What's left (data: `C19.storage_shape.*.over_2_24`).

**Lost:** macOS `/tmp` cleanup removed `/tmp/rc-tools`. All runtime scripts live on the host; the PR
bodies are in the session dir. `commit-prs.sh` and `open-prs.sh` are gone; they were already run.

**PRs merged (10-12, by Anon):** #143-#147, upstream main `1c4aa321`. The scale-free storage rework
therefore becomes a new branch `autofill-storage-tail` on main (worktree `~/dev/state-actor-wt-tail`).

**Account shape (10-13; `rc/acctsize.py`, `rc/acctkind.py`; 200k uniform account descents and 20k
code-bearing rows per store; restored scratches, recovered after).**

| | jochemnet | state-actor (PR1-5) |
|---|---|---|
| account value bytes, mean | 12.22 | 15.02 |
| rows with a code hash | 19.1% | 9.9% |
| EOA value bytes, mean | 6.83 | 11.80 |
| nonce median / p99 | 1 / 73 | 497 / 990 |
| balance median / p90 | 0 / 0.0058 ETH | 392 / 878 ETH |
| zero-balance rows (all / code-bearing) | 50.4% / 97.8% | 9.6% / 4.7% |
| code-bearing: storage-less contracts / with storage / 7702 | 61.9% / 35.6% / 2.6% | 1.6% / 80.3% / 18.1% |
| contract code row size median (p90) | 65 B (1,151 B) | 5,824 B (8,400 B) |
| sampled coded accounts per distinct code hash (top code share) | 9.4 (21.9%) | 1.2 (0.5%) |

- Cause: `entitygen` draws EOA balances as Intn(1000) x 1e18 wei (about 9 bytes) and nonces Intn(1000)
  (bumped to >= 1). Contracts get Intn(100) ETH and nonce Intn(1000). EIP-7702 delegation is a 2%
  floor (mainnet about 0.5% of accounts). There are no storage-less contracts.
- So state-actor's rows are 2.8 B bigger on average even though mainnet has twice the 32-byte
  code-hash rows. Same count and fill, +5.2% bytes per row, +3.9% leaves, +3.3% pages on account
  reads (0.970).
- [INFERENCE] Matching nonce/balance and adding mainnet's storage-less proxy population (about 12% of
  accounts, few distinct codes) brings the row distribution, and with it account reads, to parity.

**Exact account walk of jochemnet (10-13, `scripts/storage-calibration -accounts-only`, PR C tool, 10m41s
on the restored J scratch, recovered after).** 354,792,873 rows:

| class | rows | share | nonce bytes, mean | balance bytes, mean | zero balance |
|---|---|---|---|---|---|
| EOA | 286,786,583 | 80.83% | 0.95 | 3.88 | 39.2% |
| contract, no storage | 41,715,769 | 11.76% | 1.00 | 0.00 | 99.9% |
| contract with storage | 24,574,214 | 6.93% | 1.00 | 0.24 | 96.4% |
| 7702 delegation | 1,124,023 | 0.32% | 1.04 | 2.56 | 60.4% |
| delegation with storage | 591,626 | 0.17% | 1.02 | 0.55 | 82.5% |
| EOA with storage | 658 | 0.00% | | | |

- The exact mean value is 12.25 bytes; the 200k sample said 12.22. Storage accounts total 25,166,498,
  which equals the jwalk count.
- Five rows carry keccak("") as code hash with no Bytecodes row; the tool counts them as EOAs.
- Storage-less contracts run 613,998 distinct codes. The top code covers 35% of those accounts, the
  top 10 cover 81% and the top 1024 cover 98.3%. Top codes are mostly 45-byte EIP-1167 clones (a few
  21-22 bytes); the remaining codes have a median length of 7,948 bytes.
- This calibration is embedded as `accounts` in `internal/autofill/calibration/mainnet.json` (PR C);
  the storage part is byte-identical to PR A's.

## Cycle 3: storage tail + StoragesTrie order + account model (2026-10-13)

Plan `docs/superpowers/plans/2026-10-13-reth-study-finalize.md`, approved without annotations.
Driver `/root/bench/reth/stage5.sh` (markers in `logs/k.done/`, run ids k*), started 14:45 in tmux
`stage5`.
- Image `localhost/state-actor-reth:final`: main `1c4aa321` + A + B + C. Combined tree `a604d832`
  (one trivial conflict in `run_cgo.go`, resolved: B's signature with C's message). Unsigned PR
  trees: A `489a2b68`, B `94f03689`, C `545ff664` (A+C).
- Flags: same target (295061MB) and seed as cycle 2, plus `--account-model=mainnet`
  (`cfg/k-fill-args`).
- Plan log: 326,478,492 EOAs + 27,114,401 body contracts + 113 giants (534,870,145 planned slots).

**Generation:** 217 min. Phase 0 (spec storage + giants) 46 min; StoragesTrie drain 4 min.
Root `0x828b72e293be275f376e4c9e7758bb8c8ac37071705053b1d85d537c874c255e`. 257 GB (cycle 2: 232 GB).

**Gates (all ok, 19:49):**
- Rows: HashedAccounts 354,793,018 (as cycle 2), HashedStorages 1,875,381,155, StoragesTrie
  159,789,788, Bytecodes 1,812,256.
- Fill:
  - HashedAccounts 0.591;
  - AccountsTrie 0.968;
  - bloated HashedStorages h5 0.677;
  - bloated StoragesTrie h7 0.969;
  - mid-size HashedStorages 0.678;
  - **StoragesTrie main tree 0.771 (J 0.767; cycle 2 0.434)**, so B closes that gap;
  - HashedStorages main tree 0.607 (J 0.670, informational).
- Storage shape vs J:
  - storage accounts 27,264,515 vs 25,166,498 (+8.3%);
  - slots 1.875B vs 1.823B (+2.9%);
  - p50 1 / p90 10 / p99 152 / p999 4,634 (J 1/10/154/4,670);
  - accounts above 2^24 slots 7 (J 5), largest 335,545,083, the test contract;
  - main-tree leaves per storage account 0.0891 (J 0.0802; the known residual).
- Account shape (200k / 20k samples), vs J:
  - value bytes 12.39 vs 12.22 (cycle 2: 15.02);
  - rows with code 19.6% vs 19.1%;
  - storage-less contracts 11.7% vs 11.8%;
  - delegations 0.33% vs 0.32%;
  - contracts with storage 7.6% vs 6.8%;
  - nonce-length TVD 0.0001, balance-length TVD 0.005.
- Why there are 8% more storage accounts: at J's account count the 20/10/70 split gives 2.9% more
  slots than J, and the tail formula puts 34.6% of slots in giants (J 37.0%), so the body needs more
  contracts. The account gate bounds this share at ±1.5 points and labels it storage-budget driven.

**Run (after the 21:03 Teleport re-login):**
- reth `repair-trie --dry-run`: 0 inconsistencies in 99 min.
- Refill: 456 filled, 0 unexpected failures. 450/456 have the same shape as cycle 2's fixtures; the
  6 others differ by one BAL byte, with the same gas and tx counts.
- ksmoke 6/6, t3sk 21/21. kj1 started 23:09.

**T3 pages, J / cycle 2 (h) / cycle 3 (k), thousands per test (the same traced tests):**

| family (n) | HashedAccounts | StoragesTrie top tree | total |
|---|---|---|---|
| account reads (7) | 81.0 / 83.7 / 83.3 | 0 | 81.3 / 83.9 / 83.5 |
| account reads +value (3) | 30.0 / 31.5 / 31.1 | 5.8 / 8.0 / 6.1 | 104.1 / 109.0 / 106.5 |
| code-heavy (3) | 94.1 / 97.1 / 96.6 | 0 | 493.4 / 479.8 / 487.8 |
| ether transfers (4) | 43.3 / 45.1 / 44.7 | 5.5 / 7.6 / 5.9 | 114.3 / 119.2 / 117.0 |
| sload / sstore bloated (2+2) | 0.1 | 0 | 115.8 / 114.7 / 114.7, 57.2 / 56.6 / 56.6 |

- **B works as predicted:** the StoragesTrie top tree on value-transfer tests fell from 8.0k to
  6.1k pages (J 5.8k).
- **C barely moves account reads, and the cause was misattributed.**
  - Each account-read test touches one HashedAccounts leaf per accessed account: 51.5k leaves in
    all three stores (mean over the 6 traced account-read tests), because the accesses are sparse
    against 8M+ leaves. Row size and leaf count therefore don't matter here.
  - The whole gap is branch pages touched (same mean): J 43.0k, h 46.1k, k 45.7k.
  - k has fewer leaves than J (8,120,593 vs 8,194,914) but 15.6% more branch pages (142,466 vs
    123,254). J holds about 66.5 leaves per branch page, k about 57. k's branch fill is measured at
    0.590 (the split reserve that targets leaf fill applies to branches too), so J's is about 0.69
    [estimate: 0.590 x 66.5/57.0; J's branch fill was never mapped].
  - The earlier inference ("bigger rows -> +3.3% pages") is superseded 2026-10-14: the lever is
    HashedAccounts branch fill, not row size.
- Code-heavy totals moved toward J (479.8k -> 487.8k, J 493.4k), presumably through the larger
  Bytecodes population [INFERENCE].

**Pair A only (kj1 2h00, ks1 1h12; both 266/266 under DIO), per-family medians, h -> k:**
- \>= 0.5 s tests in band: 152/154 on pair A in both cycles.
- Over a second:
  - account reads 0.977 -> 0.970 (unmoved, as the traces predicted);
  - account reads +value 0.983 -> 1.002;
  - code-heavy 1.038 -> 1.017;
  - code-heavy +value 1.017 -> 1.010;
  - ether transfers 1.034 -> 1.041 (B makes S read fewer pages, so it runs a bit faster);
  - sload 1.055 -> 1.053; sstore no-write 1.037 -> 1.032; sstore write 1.028 -> 0.996.
- Out of band on pair A: sload_bloated existing 240M 1.124 and sstore no-write 160M 1.100. Both
  read only the bloated test contract.

## Cycle 3 result (2026-10-14)

Run: kj2 2h00, ks2 1h12, all four runs 266/266 under DIO. STAGE5-DONE 05:35, and the scratches were
left unmapped. Collector C20: 0 failed checks.

| family (>= 0.5 s) | n | cycle 2 (h) | cycle 3 (k) |
|---|---|---|---|
| account reads | 64 | 0.970 | 0.976 |
| account reads +value | 6 | 0.983 | 1.002 |
| code-heavy reads | 32 | 1.034 | 1.019 |
| code-heavy reads +value | 8 | 1.020 | 1.002 |
| ether transfers | 34 | 1.033 | 1.040 |
| sload_bloated | 4 | 1.054 | 1.046 |
| sstore no-write | 4 | 1.046 | 1.046 |
| sstore write | 2 | 1.034 | 1.021 |

- 153/154 gated tests in band, as in cycle 2. Accepted, and every family robust.
- Over a second: 113/114 on each pair (medians 1.0161 / 1.0127). J's floor is 114/114 over a
  second and 105/152 under (cycle 2: 102/152). Ether transfers below 0.5 s are still flagged.
- Out of band: sload_bloated existing 240M, 1.112 (pairs 1.124 / 1.099). Cycle 2's sstore no-write
  160M is back in band. Both read only the bloated test contract, whose rows are identical across
  stores; which test sits just outside the band moves between regenerations.
- Plan acceptance:
  - \>= 153/154 and every family robust: met;
  - no family more than 2% further from parity: met (transfers +0.7%);
  - account reads within ±2% of 1.00: **not met** (0.976).
- Attribution (stop rule): the traces show account reads touch the same 51.5k leaf pages in every
  store. The remaining gap is HashedAccounts branch pages: 15.6% more of them at 0.59 branch fill vs
  jochemnet's estimated ~0.69. That is a fill-control limit (one reserve for leaves and branches),
  not account shape. **No cycle 4** (plan).
- What moved toward parity: code-heavy (both), +value, sstore write, sload. The StoragesTrie order
  fix explains +value (traced 8.0k -> 6.1k top-tree pages, J 5.8k).

## Close-out (2026-10-14)

- PRs signed and opened as drafts: ethereum/state-actor #150 (A, storage tail), #151 (B, StoragesTrie
  order) and #152 (C, account model, stacked on #150). Commits `5d0f715`, `28cdd8a`, `1722acf`, all
  verified.
- Article committed (`cf6448f`) and pushed as branch `reth-state-db-article`; it is not on `main`
  yet, so it is not published. It includes `data/report_data.json`: the C1-C20 collection, 0 failed
  checks.
- This ledger, the plans and the host tools (`docs/superpowers/reth-host-tools/`) are on branch
  `reth-study-ledger`.
- Host wiped on Anon's instruction, after those uploads:
  - every reth store and scratch, the S fixtures, `/root/bench/reth` and the study images;
  - second pass, same day: schelk reth states, the 951 GB jochemnet reth download, every reth
    image and volume, and `/data/eth/reth` (Feb-2026 snapshots, deleted after an explicit ask).
  - No reth data remains on the host, and raw run results exist only as `report_data.json`.
