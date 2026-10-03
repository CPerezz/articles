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
