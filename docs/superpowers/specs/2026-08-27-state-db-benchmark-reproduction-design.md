# Reproducing the state-DB performance divergence with benchmarkoor + schelk

Date: 2026-08-27
Status: approved design, pending implementation plan
Host: `stateless-bloatnet-benchmarks` (via Teleport)

## Goal

Re-run the EEST repricing suite on two geth databases — the compacted jochemnet
snapshot and a regenerated state-actor snapshot — and determine whether the tests
that diverged most in `state-db-perf-divergence/state-db-perf-report.html` are the
same tests that diverge most here. If the setup change alone provokes a different
result, stop and re-plan rather than interpret.

This pass reproduces the report's *structure*, not its absolute numbers. It also
deliberately reproduces one of the report's own known confounds (different fixture
bundles per arm) rather than fixing it; removing that confound is the expected
follow-up.

## Verified starting state

Every fact in this section was confirmed by direct inspection, not assumed.

### Host

- Ubuntu 24.04.4 LTS. `sudo` NOPASSWD available.
- `/` = md2, RAID1 over 2x 3.5 TB NVMe. 3.5 TB total, 1.8 TB used, 1.6 TB free.
- `/data` = md3, RAID0 over 2x 14.6 TB HDD. 29 TB, 9.6 TB free. Holds the
  1,005,176,229,978-byte jochemnet tarball.
- No spare block devices, no free partitions, no LVM. schelk volumes must be
  loopback files.
- Present: `dmsetup`, `era_invalidate`, `mkfs.ext4`, docker 29.4.2, schelk 0.1.0
  (93522c7), `/dev/ram0` with `brd rd_size=6291456` KiB (6 GiB).
- Missing: **podman** (apt candidate `4.9.3+ds1-1ubuntu0.2`), `go`, `cargo`.

### Data on disk

- `/schelk` is a **plain directory on `/`**, not a mount.
  - `/schelk/snapshots/geth/jochemnet/24402727/geth/` — 1.1 TB. Compacted today
    with `geth db compact` (LSM 411 G -> 378 G, SSTs 13,333 -> 9,184, all levels
    collapsed to L6). Splits into chaindata LSM 378 G, `ancient/chain` 700 G,
    `ancient/state` 6.0 G, `triedb/merkle.journal` 278,500,441 B
    (md5 `5663fcb106f4d2bb42e4009a9ed0efa0`).
  - `/schelk/state-actor/v1/geth/geth/chaindata` — 553 G, `ancient/` is 40 K
    (empty). Generated today: 422,456,696 accounts, 1,878,617,248 storage slots,
    state root `0x5b305cc0f85f9ffaf5eca1e72cfe0c82f92e14f121aed163cc4c0e784aa3b6e7`,
    genesis included, no journal. Built from state-actor `e4cb2058` with **31
    modified files** (dirty tree), spec md5 `8bc1dd3a48f886a50e70e6fce30df39a`,
    seed 42.
- The **uncompacted arm no longer exists** — it was compacted in place by operator
  ruling. The tarball is the only route back.

### schelk

Model: pristine **virgin** device, writable **scratch** device, dm-era metadata on
a ramdisk tracking changed blocks; `recover` restores only those blocks. Virgin and
scratch must be different block devices of **equal size**. All operational commands
need root. Parallel instances need unique `--dm-era-name` and `--state-path`. After
a reboot while mounted, only `full-recover` is safe.

Current state file is **stale**: `virgin=/dev/loop0`, `scratch=/dev/loop1`,
`mount_point=/data/schelk`, but `losetup -a` is empty and `/data/schelk` is an empty
root-owned directory. The original runs used `mount_point=/schelk`.

### benchmarkoor

- `pkg/datadir/schelk.go`: `Prepare()` requires `source_dir` under the state file's
  `mount_point`, runs `schelk restore -y`, verifies the mount. `Cleanup()` runs
  `schelk recover -y`. With `rollback_strategy: container-recreate` this happens
  **per iteration**.
- The prebuilt binary at `~/benchmarkoor/bin/benchmarkoor` is commit `9b8a5d8`,
  which is **53 commits OLDER** than the `1e0b9d4` the original runs used
  (`git merge-base --is-ancestor 9b8a5d8 1e0b9d4` passes). It is **unusable for
  this plan**: `promote_post_pre_runs` is absent from the tree entirely, runner
  `PreRuns` support is absent, and `fixtures_url` is only partially wired (1
  reference vs 5 at `1e0b9d4`). The jochemnet choreography cannot be expressed
  against it.
- **Build at `1e0b9d4`** by cross-compiling: `go.mod` declares `go 1.24.5` /
  `toolchain go1.24.11`, and the workstation has `go1.24.11 darwin/arm64`, so
  `GOOS=linux GOARCH=amd64 go build ./cmd/benchmarkoor` produces the binary
  without installing Go on the host or building in a container. Verify with the
  `version` subcommand (there is no `--version` flag — see `fcca6d2`).
- The 53-commit gap contains machinery this plan depends on: `135f30c` (#296)
  resolves the pre-run bundle inside the fixtures artifact, which is exactly how
  the jochemnet tarball ships it; `0e1856a` (#297) keeps the client alive after a
  container-recreate schelk promote; `93e70fc` (#298) skips the per-test pre-run
  replay once the baseline already carries it; `2137e47` (#306) verifies the
  datadir head for a bundle inside the fixtures artifact; `1e0b9d4` (#307) fixes
  the replay anchor. Also `65c967f` (#300): a run that benchmarked nothing must
  not exit 0 — a silent-failure guard worth having.
- `ClientInstance.ExtraMounts` (`extra_mounts: [{source,target,read_only}]`) exists,
  consumed at `pkg/runner/lifecycle.go:268`.
- `runner.benchmark.tests.filter` supports run-time fixture selection.

### Config chain (ethpandaops/benchmarkoor-tests @ 2a03b12)

| Layer | Key values |
| --- | --- |
| `configs/global.yaml` | `drop_memory_caches: "steps"`, `docker_network: benchmarkoor`, `client_logs_to_stdout: true`, live_reporting **enabled** to the ethpandaops API with `${API_INGEST_TOKEN}` |
| `configs/datadirs/jochemnet/v1/global.yaml` | `GETH_SNAPSHOT_DIR=/schelk/snapshots/geth/jochemnet/24402727`, `GETH_GENESIS=<gist URL>` |
| `configs/datadirs/state-actor/v1/global.yaml` | `STATE_DIR=/schelk/state-actor/v1` |
| `configs/datadirs/jochemnet/v1/runner.yaml` | geth: `method: schelk`, `schelk_options.promote_post_pre_runs: true` |
| `configs/datadirs/state-actor/v1/runner.yaml` | geth: `method: schelk`, no schelk_options, **no geth genesis entry** |
| `contexts/repricing/jochemnet/v1/glamsterdam-devnet-7/global.yaml` | `AMSTERDAM_ACTIVATION_TS="1769856769"` |
| `contexts/repricing/v1/glamsterdam-devnet-7/clients.yaml` | geth uses literal `--override.amsterdam=1` |
| both `clients.yaml` | instance `geth-bal-full`, image `ghcr.io/jochem-brouwer/go-ethereum:glamsterdam-devnet-7-blobpool-fix`, `--engine.maxreorgdepth=1024`, `--debug.logslowblock=0` |
| both `test-source.stateful.runner.yaml` | `container_runtime: podman`, `rollback_strategy: container-recreate`; jochemnet adds a `pre_runs` bundle |

Both `source_dir` values match our on-disk paths exactly.

### Evidence from the original runs

Their six logs are each truncated at exactly 10 MB.

- Ran as user `devops`, cache `/home/devops/.cache/benchmarkoor/eest-url/6142626aac06abc4`.
  That path does not exist on this host and `devops`' home here is untouched since
  Jun 12 — **the original runs were on a different machine**. Absolute MGas/s is
  therefore not reproducible.
- Container runtime was genuinely podman.
- `Discovered EEST fixtures count=1463`; `Running filtered instances filtered=1 total=8`.
- Measured per-test cost: compacted 406 contiguous iterations in 2h49m39s =
  **25.1 s/test**; state-actor 415 in 2h08m19s = **18.6 s/test**. Extrapolated full
  suite: ~10 h jochemnet, ~8 h state-actor.
- geth build: `Geth/v1.17.6-unstable-4d92c8e0-20260811`, identical to the binary we
  extracted and used for compaction.

## Decisions

1. **schelk layout A** — sequential, one snapshot at a time, virgin and scratch both
   on NVMe.
2. **Option 2 volume split** — `ancient/chain` (700 G, immutable) lives outside the
   schelk volume and is bind-mounted read-only; `ancient/state` (6 G, written every
   block under pathdb) stays inside so `recover` rolls it back. Applies to jochemnet
   only; state-actor's freezer is empty.
3. **Full 1463-fixture suite** on the first run of each arm. Only after confirming
   the divergence ranking do we filter to `test_account_access`.
4. **Analysis** — two independent recompute agents plus one adversarial agent, with
   independent re-derivation by the operator's assistant on top.
5. **Approach: static anchor checks first, then a smoke per arm, then the full pass.**

## Architecture

```
Phase 0  Preflight (non-destructive) ........... Gate 0
Phase 1  jochemnet volume construction
Phase 2  jochemnet setup+smoke (pre-run, promote, 5 fixtures) ... Gate 2
Phase 3  jochemnet full run, 1463 fixtures, ~10 h
Phase 4  teardown, state-actor volume, smoke ... Gate 4, then full run, ~8 h
Phase 5  pre-registration evaluation, then agents, then adjudication
```

jochemnet runs first deliberately: its fixtures are confirmed keyed to block
24402727, so a Phase 2 failure is attributable to our setup. By Phase 4 a smoke
failure is attributable to the fixtures — which is the open state-actor question.

### Phase 0 — Preflight

- Archive and remove the stale `/var/lib/schelk/state.json`.
- Install rootful podman; create the `benchmarkoor` network; verify the image pulls.
- **Cross-compile benchmarkoor at `1e0b9d4`** on the workstation
  (`GOOS=linux GOARCH=amd64`), scp it to the host, verify with the `version`
  subcommand. The prebuilt `9b8a5d8` binary is not a fallback — it lacks
  `promote_post_pre_runs` and runner `PreRuns` entirely.
- Read five behaviours out of the benchmarkoor source at `1e0b9d4` (reading needs
  no toolchain): whether pre-run execution is gated; whether promote fires with
  zero `pre_runs`; whether promote fires after a **failed** pre-run; exactly what
  is mounted into the container; how env expansion disables live reporting.
- **Read `93e70fc` (#298) specifically** — "skip the per-test pre-run replay once
  the baseline carries it". If it does what its subject says, the Phase 2/Phase 3
  config split below is unnecessary and upstream's config can be used verbatim,
  which is strictly more faithful. Confirm from the code, not the subject line;
  keep the split as the fallback.
- Download both fixture tarballs to `/data`.
- **Static anchor check**: enumerate the actual fixture schema, then compare each
  bundle's anchor fields against the corresponding DB head. jochemnet is an
  integrity check (head is known to match); state-actor is an early-warning signal
  only — its decisive gate is dynamic, at Phase 4.
- **Fork-timestamp gate (hard stop)**: confirm `--override.amsterdam=1769856769`
  (jochemnet) and `=1` (state-actor) against the fixtures' payload timestamps. A
  mismatch executes the wrong fork rules and yields valid-looking wrong numbers.
- Measure dm-era metadata size for a 500 G volume at 4096 granularity against
  ram0's 6 GiB. If it does not fit: raise `rd_size`, or raise granularity.
- Measure ext4 overhead with `mkfs.ext4 -m 0` on a test loop file before sizing.

### Phase 1 — jochemnet volume

Both relocations are renames on one filesystem: instant, no copying.

| Step | Action | `/` used | free |
| --- | --- | --- | --- |
| 1 | `mv /schelk/state-actor -> /sa-store` (out of the shadow path) | 1.80 T | 1.60 T |
| 2 | `mv .../ancient/chain -> /ancient-store/...` | 1.80 T | 1.60 T |
| 3 | create virgin loop file, 500 G | 2.29 T | 1.21 T |
| 4 | `mkfs.ext4 -m 0`, mount temporarily, copy 385 G in | 2.29 T | 1.21 T |
| 5 | verify copy, then delete the original datadir remnant | 1.90 T | 1.60 T |
| 6 | create scratch 500 G, `schelk init-from` | 2.40 T | 1.10 T |

Mounting schelk at `/schelk` shadows plain directories beneath it, which is why
step 1 must precede the mount. Step 5 is irreversible and happens only after the
copy is verified.

`schelk init-from --fstype ext4 --mount-point /schelk --ramdisk /dev/ram0`, with a
fresh `--dm-era-name` and `--state-path`. Confirm the new state file reports
`mount_point: /schelk`.

Record the baseline: SST count, level layout, journal size and md5.

### Phase 2 — jochemnet setup + smoke

The smoke **is** the setup pass. `Prepare()` restores scratch from virgin before
every iteration, so without `promote_post_pre_runs` the first iteration would
discard the pre-run's advancement and no fixture would anchor. Promote is therefore
enabled here, and the resulting head **H** becomes the baseline for the full run.

Config: merged single YAML, `pre_runs` present, `promote_post_pre_runs: true`,
`tests.filter` selecting ~5 fixtures.

**Conditional on Phase 0's reading of `93e70fc` (#298).** If the runner at
`1e0b9d4` already skips the per-test replay once the baseline carries it, then
Phase 2 and Phase 3 share one unmodified upstream config and differ only by
`tests.filter` — no `pre_runs` removal, no `promote_post_pre_runs` flip. That is
the preferred outcome: fewer deviations, and the double-replay hazard is handled
by the same code the original runs used. The split described in Phase 3 is the
fallback for the case where #298 does not cover it.

**Before the first promote, archive the pristine virgin to `/data`.** `promote`
overwrites the virgin irreversibly and the original directory is already gone; the
alternative recovery path is re-extract plus re-compact, which yields a different
LSM shape and thus a new variable.

Smoke assertions, all required before Phase 3:

1. Pre-run success asserted in the logs **before** H is accepted.
2. Journal at H captured — size, layer count, md5 (evaluates prediction A1).
3. `drop_memory_caches` observed firing per iteration.
4. Zero live-reporting traffic.
5. `recover` duration logged separately; at least two consecutive unattended cycles.
6. Sentinel-file hashes stable across a recover (seeds B1). **Sentinel set**, fixed
   once at Phase 1 baseline and reused unchanged for both arms: `CURRENT`,
   `MANIFEST-*`, `OPTIONS-*`, `triedb/merkle.journal`, and the 20 largest `.sst`
   files by size at baseline, recorded by path and sha256.
7. `ancient/chain` hash unchanged; `read_only: true` did not break boot.
8. 3-5 repeats of one fixture to measure sigma for prediction C4's band.
9. Per-test wall clock within sight of the original 25.1 s (diagnostic only).

### Phase 3 — jochemnet full run

1463 fixtures, `pre_runs` **removed** and `promote_post_pre_runs: false`, so every
iteration restores to H and the pre-run replay cannot double-apply. Detached
under zellij, as root, logs written untruncated. Sentinel hash at test #100.

### Phase 4 — state-actor

1. Archive the promoted jochemnet virgin (H) to `/data` — the only warm re-runnable
   baseline.
2. Tear down: unmount, delete loop files, **explicitly zero `/dev/ram0`** (sequential
   dm-era reuse over residual metadata is undefined).
3. Build 700 G virgin + scratch around the 553 G datadir at `/sa-store`. Option 2
   does not apply. Fresh dm-era name and state path.
4. Smoke, minus pre-runs. **This is the decisive dynamic anchor gate**: if the
   fixtures' first payload is rejected, stop the state-actor arm and report. The
   jochemnet dataset remains valid — the arms are independent.
5. Full 1463-fixture run, ~8 h.

### Phase 5 — analysis

Pre-registration evaluated first, verbatim, before any narrative. Then:

- **Recompute-A** and **Recompute-B**: raw results JSON, geth logs, harness logs,
  pre-registration, and the tuple join-key spec. **Not** given the report's numbers
  or conclusions. Separate invocations, no shared channel; B must use a different
  implementation path and may not see A's output.
- **Adversary-C**: the report's conclusions plus the new data, briefed to falsify
  journal-provenance as root cause and to attack our own methodology.
- **Independent re-derivation**: the six µs-per-lookup values per arm, each arm's
  within-arm spread, per-category cross-arm ratios, the worst-15 list, test
  population counts, and journal size/layers from the geth logs — computed directly
  from raw data before reading agent output. Agreement between A, B and that
  derivation accepts a number; any disagreement is adjudicated against raw data.
  C's claims receive the same treatment.

Deliverable: a table mapping each report claim to reproduced / not reproduced / not
checkable, with pre-registration verdicts, evidence, and C's surviving objections.

## Configuration

One merged YAML per arm rather than the five-file GitHub Actions assembly.

Differences between the arms:

| | jochemnet | state-actor |
| --- | --- | --- |
| `source_dir` | `/schelk/snapshots/geth/jochemnet/24402727` | `/schelk/state-actor/v1/geth` |
| `schelk_options` | `promote_post_pre_runs: true` (Phase 2 only) | absent |
| geth genesis | `GETH_GENESIS` gist URL | none, read from datadir |
| `--override.amsterdam` | `1769856769` | `1` |
| `pre_runs` | yes (Phase 2 only) | no |
| fixtures | `...d9ad55b3-20260807-000744` | `...2282c757-20260722-144218` |
| `extra_mounts` | ancient/chain, read-only | none |

Everything else identical: same image, `--engine.maxreorgdepth=1024`,
`--debug.logslowblock=0`, `rollback_strategy: container-recreate`,
`container_runtime: podman`, `drop_memory_caches: "steps"`.

Five deliberate overrides of upstream:

1. `live_reporting.enabled: false` — we hold no `API_INGEST_TOKEN`; left enabled it
   would publish our runs or inject per-test retry jitter. Ingest host also
   null-routed in `/etc/hosts` for the duration.
2. Instances reduced to `geth-bal-full` alone (upstream ships 8; the original runs
   filtered to 1 of 8).
3. `results_dir: /data/bench-results/<arm>` — must be off the schelk mount or
   `restore` destroys it between every test.
4. `extra_mounts` for jochemnet's `ancient/chain`.
5. `tests.filter` during smoke only.

The `extra_mounts` target nests inside benchmarkoor's own `/data` bind mount:

```yaml
extra_mounts:
  - source: /ancient-store/jochemnet/24402727/chain
    target: /data/geth/chaindata/ancient/chain
    read_only: true
```

An empty `ancient/chain` directory inside the volume serves as the mountpoint. No
`--datadir.ancient` flag is needed, so `extra_args` stay byte-identical to upstream.
`read_only: true` enforces the immutability assumption rather than asserting it: if
geth needs the chain freezer writable at boot, the smoke fails in minutes, and the
fallback is `read_only: false` plus before/after hashing.

Execution as **root** — required independently by schelk, rootful podman, and
writing `/proc/sys/vm/drop_caches`. Fixture cache lands at
`/root/.cache/benchmarkoor/eest-url/<hash>`, outside `/schelk`, so it survives
`restore`. Logs are written through `tee` untruncated; the originals' 10 MB
truncation cost the ability to confirm their duration, and geth's container logs are
primary evidence for Phase 5.

## Pre-registered predictions

Committed before the first full run.

### Tier A — setup fidelity, before any benchmark

- **A1** Journal at H = 380.15 MiB +/- 10%, layers 4248 +/- 10%. The report published
  both; the shipped journal is 265.6 MiB, and 380.15 - 265.6 = 114.5 MiB is the
  growth a pre-run of this size should add. Highest-value check in the plan: it tests
  setup equivalence against a published number, ~30 minutes in rather than 18 hours in.
- **A2** geth logs `cache=2.00GiB handles=536,870,908 version=v1` and
  `clean=1023.00MiB dirty=1.00GiB`.
- **A3** state-actor: journal absent (`journal not found`, 999/999).
- **A4** `drop_memory_caches` observed every iteration.
- **A5** `ancient/chain` hash unchanged.

### Tier B — run integrity; failure invalidates that arm

- **B1** Sentinel DB-file hashes identical after `recover` at tests #1, #100, last.
- **B2** |Spearman rho| between per-test residual and iteration index < 0.2.
- **B3** `recover` duration shows no monotonic growth beyond 2x first-decile to last.
- **B4** `gas_mismatches == 0`.
- **B5** >= 350 of the report's 406 test IDs recovered via the tuple join key
  `(opcode, account_mode, gas, value_sent, overhead_baseline)` — never fuzzy string
  matching.

### Tier C — report claims

C1 and C2 are **within-arm**, so they are immune to both the bundle and host
confounds:

- **C1** Compacted's µs-per-lookup spread across the six account modes greatly
  exceeds state-actor's. Report: 7.2x vs 1.1x. Predict compacted > 3x, state-actor
  < 2x.
- **C2** Within compacted, DIFF_MAX is the fast outlier (report: 2.1 µs vs ~14 µs).
  Predict DIFF_MAX < 0.5x the median of the other five modes.
- **C3** The worst cross-arm divergent test is a BALANCE/DIFF_MAX parameterisation —
  identity only, not magnitude.
- **C4** The 13 non-DIFF_MAX categories cluster in a narrow cross-arm band; report
  [1.031, 1.117], widened by +/-3 sigma from smoke-measured repeat variance.
  Directional and confounded.
- **C5** Instrumentation defects reproduce: negative `timing.execution_ms` on
  value-transfer blocks, constant `state_reads`/`state_writes` per block shape.
- **C6** No state-actor account mode deviates from that arm's median by more than 2x.

### Explicitly ruled out

Absolute MGas/s comparisons; the 7.71x and 12.1x magnitudes as reproductions; every
uncompacted-arm claim (c/u drift 0.237-1.220, the compacted-faster set, the 7.1x
spread) since that arm no longer exists; vs1 SA separation 8.07-10.57x as a
reproduction rather than a generalization test on a regenerated DB; and the 33/92/50
bucket counts as exact figures.

### Interpretation asymmetry

Four independent changes — the journal being consumed and rewritten by the pre-run,
the L6 collapse from our compaction, the different fixture bundle, and the different
host — all push toward *less* divergence. If DIFF_MAX divergence **shrinks**, that is
causally uninterpretable. If it **persists at full magnitude** despite all four, that
meaningfully weakens journal-provenance as the sole root cause. Only one outcome
carries information, and which one is fixed in advance.

## Risks

| Risk | Handling |
| --- | --- |
| `promote` destroys the pristine virgin | Archive the pristine virgin to `/data` before Phase 2 |
| Re-running the pre-run on an advanced chain fails | Phase 3 config removes `pre_runs` entirely |
| Mounting at `/schelk` shadows plain directories | Both datadirs relocated out first |
| `restore` wipes anything under the mount | Fixtures, results, cache, bundles all off-mount |
| dm-era metadata may not fit ram0 across 1463 cycles | Measured in Phase 0; levers are `rd_size` and granularity |
| `ancient/state` escaping rollback would cause silent drift | Kept inside the volume |
| Leaky recover indistinguishable from signal | B1 sentinel hashes at #1/#100/last |
| Wrong fork schedule yields valid-looking wrong numbers | Hard gate in Phase 0 |
| Prebuilt host binary silently lacks `promote_post_pre_runs` and `PreRuns` | Resolved: cross-compile `1e0b9d4`, the exact commit the original runs used; prebuilt `9b8a5d8` is not a fallback |
| Different host from the original runs | Absolute numbers ruled out; only structure claimed |
| state-actor built from a dirty tree | Its arm is a generalization test, never a reproduction |
| Different fixture bundle per arm | Reproduced deliberately; named in C4; the expected follow-up |
| Loop-device layer differs from a raw partition | Applied identically to both arms; decision recorded once |

## Out of scope

Rebuilding fixtures locally; rerunning state-actor on bundle `6142626aac06abc4`
(the expected follow-up); restoring the uncompacted arm; any change to the report's
prose. Follow-up is re-planned after Phase 5.
