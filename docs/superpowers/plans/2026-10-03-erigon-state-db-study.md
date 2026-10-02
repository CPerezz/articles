# Erigon state-DB study: setup and baseline plan

Adopted 2026-10-03 from a proposer/critic/adjudicator debate (plan mode). Scope: set the study up
end to end on the Nethermind bench host and produce baseline measurements for both arms. Analysis
and the article come later.

Deviations from the debate's text, decided while adopting it:
- The tarball's `_snapshot_eth_getBlockByNumber.json` reports block 24,350,000 (0x1738d30), the
  mainnet base the jochemnet chain was forked from, not the jochemnet head. G3 records it; the head
  (24,402,727) is asserted by the probe's `eth_blockNumber` (G5-joc), not by that file.
- Ledger and tools follow the series' layout: `docs/superpowers/specs/2026-10-03-erigon-study-ledger.md`
  and `tools/erigon-study/`, not `ledger/` and `tools/erigon/`.

## 0. Isolation and naming
- Articles worktree `articles-wt-erigon`, branch `erigon-state-db-study` from `origin/main`. Nothing is
  written to `articles-wt-specs`, `articles-wt-besu`, `articles-wt-nm-rewrite` or the benchmarkoor
  tree. A benchmarkoor patch, if needed, goes in worktree `benchmarkoor-wt-erigon` and installs as
  `/bench/erigon/tools/benchmarkoor-er`, never over `/usr/local/bin/benchmarkoor`.
- Box: schelk `er-joc` = `/dev/ram0`, `/schelk-er-joc`, `/var/lib/schelk/er-joc.json`, `er_joc_era`;
  `er-sa` = `/dev/ram1`, `/schelk-er-sa`, `/var/lib/schelk/er-sa.json`, `er_sa_era`. Dirs
  `/bench/erigon/{snapshots,cfg,logs,tools,probe}`; configs `/bench/cfg/er-*.yaml`; results
  `/bench/results/er-<arm>-<suite>-<YYYYMMDD>`; fixtures `/bench/fixtures/sa-v2-full/erigon`.
- Long jobs are detached scripts writing `.log` plus `.done`/`.fail`; they take `/bench/erigon/.busy`
  and refuse to start on foreign activity (`pgrep -f benchmarkoor`, `dmsetup ls`). Loop devices are
  discovered with `losetup -j`, never hard-coded. Bulk I/O runs under `nice -n 10 ionice -c2 -n7`.

## 1. Disk plan
A promote allocates the full virgin image, not the content (nm-joc-virgin: 1.6 T allocated for a
1.4 T extract). er-joc is a fixed 1.9 TB, er-sa 0.8 TB. The tarball stays on disk (resumable),
deleted after G3. A promote starts only if live free minus image size is at least 0.5 TB. Levers in
order: the NM v2 store (deleted once the reference hashes are recorded), then the tarball (after G3).
The state-actor store is generated directly into the er-sa scratch; no raw copy. ENOSPC during the
extract: tear down er-joc and re-init at 2.2 TB.

| step | used TB | free |
|---|---|---|
| NM images wiped, tarball complete, v2 deleted | 1.39 | 5.6 |
| er-joc 1.9 T + er-sa 0.8 T scratches | 4.09 | 2.9 |
| sa promote | 4.89 | 2.1 |
| tarball deleted after G3 | 3.85 | 3.15 |
| joc promote | 5.75 | 1.25 |

## 2. Preparation
1. G0 (`dmsetup ls` empty, no schelk mounts, loops only on NM images, no users), then wipe:
   `losetup -d` the four NM loops, move `nm-joc.json`/`nm-sa.json` to `/var/lib/schelk/retired/`,
   remove the four `nm-*.img`, leave removal notices.
2. Zero both ramdisks with `dd` (stale dm-era headers are a correctness risk). Watch dm-era metadata
   use; replan above 70%.
3. `setup-schelk.sh er-joc /dev/ram0 /schelk-er-joc 1900G`, then `er-sa /dev/ram1 /schelk-er-sa 800G`.
4. Reference values from the existing fill (`genesisBlockHeader.hash`, `.stateRoot`), agreeing with
   the NM ledger's v2 genesis `0x0cb03528…a68623` / root `0x48d611bb…d51b8`. Copy the fill to
   `/bench/fixtures/sa-v2-full/erigon`. Then delete `/bench/nm-store/v2`.
5. Pull `ethpandaops/erigon:glamsterdam-devnet-7` and `ghcr.io/ethereum/state-actor-erigon:main-005a19c`,
   record digests and revisions, never pull mid-study.
6. Configs `/bench/cfg/{er-joc-A,er-joc-B,er-sa-A,er-sa-B}.yaml` from the NM ones and the canonical
   benchmarkoor-tests context: both arms `--exec.no-merge=true --exec.no-prune=true
   --exec.no-background-maintenance --experimental.parallel-commitment`, bootstrap_fcu
   {120, 30s}, retry_new_payloads_syncing_state {240, 30s}; joc `--override.amsterdam=1769856769`,
   sa `--override.amsterdam=1`. A configs: pre_runs + `promote_post_pre_runs: true` + a two-test
   filter. B configs: no pre_runs, no promote, `regex:(160M|240M)`.

## 3. jochemnet arm
G1 size + `zstd -t` -> G2 er-joc mounted, free >= 1.7 TB -> extract into the scratch with a listing
-> G3 (tar rc 0, entry count, `mdbx.dat` apparent size 572,455,387,136, `du`, remove a stale
`mdbx.lck`) -> delete the tarball -> promote, remount -> probe G5-joc on the scratch (clean start,
`eth_chainId` 0x1, `eth_blockNumber` 24,402,727, amsterdamTime 1769856769 in the chain-config log,
cold-open time) -> stop, restore, remount.

## 4. state-actor arm
`main-005a19c`, same spec, `--client=erigon --target-size=350GB --seed=42 --fork=osaka
--gas-limit=1000000000`, generated directly into the mounted er-sa scratch. G4: writer rc 0,
genesis hash and state root equal the reference, `chainspec.json` present. Promote, remount, probe
G5-sa (no format refusal, chain config with amsterdamTime 1 under the override, block-0 hash and
root equal the reference, known entities readable). Fixture reuse iff the genesis hash equals the
fill's. If the writer's format is unreadable by the devnet-7 image, or the override does not apply
to the DB-stored chain config, the sa arm is blocked and escalated upstream; jochemnet proceeds
alone.

## 5. Baseline shape
266 tests (`regex:(160M|240M)`) per arm. Suite A = pre_runs + promote + two tests (the smoke test,
with fixture accounts present). B1, B2 = 266 tests from the identical promoted store. Order,
strictly serial: A-joc, A-sa, B1-joc, B1-sa, B2-joc, B2-sa. Ratio from the B1 pair, B2 the
replication, replica floor = per-arm per-test |B1-B2|; a test's ratio is reportable only if the
between-arm difference exceeds both arms' replica deltas for that test.

## 6. Gates
- A-joc: projected pre-run over 6 h at 15 min -> stop and investigate.
- A pass: pre-run completes, head = 24,410,463 (joc), promote logged and remounted, both tests VALID,
  hashes match fixtures, gas_used identical across arms, intended flags in the container cmdline.
- G6 before B1: clean Erigon shutdown in the pre-run container log; no tmp/zero-length files under
  `snapshots/` after restore; dm-era metadata recorded.
- Per-test overhead t: <= 68 s run all four B suites; 68-120 s run B1 then decide; > 120 s stop.
- Watchdog marks a stall after 3.5 h without a completed test; never an automatic kill; never
  `kill -9`; dm-era wedge -> `full-recover` of that instance while the other is idle.

## 7. Record
Ledger append-only with commands, rc, sizes, hashes, digests, loop/ramdisk mapping, decisions,
result ids, durations, retry counts, cold-open times and floor numbers. The box is the source of
truth; scripts and configs are copied into `tools/erigon-study/` with sha256 at each phase boundary.
Commit per phase on `erigon-state-db-study`; no pushes to main.

## 8. Timeline
Prep T+0-2; sa generation T+1.5-6.5 (off the critical path); download done T+3.5, extract 1-3 h,
joc promote and probe -> T+8-9; suite A both arms T+9-13; B1/B2 both arms T+13-24. 24-30 h,
re-estimated after G5-sa and after suite A.
