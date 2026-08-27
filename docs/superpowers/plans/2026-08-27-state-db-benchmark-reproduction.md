# State-DB Benchmark Reproduction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the EEST repricing suite (1463 fixtures) against two geth databases — the compacted jochemnet snapshot and a regenerated state-actor snapshot — and determine whether the tests that diverged most in the published report diverge most here.

**Architecture:** Five gated phases on one remote host. Each snapshot is placed on a schelk block-level volume (pristine *virgin* + writable *scratch*, dm-era tracking changed blocks) so benchmarkoor can roll the database back between every test. Snapshots are processed sequentially because both volumes cannot fit on NVMe at once and because concurrent runs would contaminate timings. Analysis is pre-registered before any full run.

**Tech Stack:** Go 1.24.11 (cross-compile only), benchmarkoor `1e0b9d4`, schelk 0.1.0, podman 4.9.3, geth `v1.17.6-unstable-4d92c8e0`, ext4 on loopback, dm-era, Teleport `tsh`, zellij.

**Spec:** `docs/superpowers/specs/2026-08-27-state-db-benchmark-reproduction-design.md`

## Global Constraints

- Host is `stateless-bloatnet-benchmarks`, reached only via `tsh ssh`. Available logins: `root`, `devops`, `CPerezz`, `debian`. **All operational work uses `root`** — required independently by schelk, rootful podman, and writing `/proc/sys/vm/drop_caches`.
- **Never** mount or write the virgin or scratch devices outside schelk.
- `source_dir` MUST be under the schelk `mount_point` or benchmarkoor refuses to start.
- Fixtures, results, fixture cache and pre-run bundles MUST live outside `/schelk` — `schelk restore` resets everything under the mount between every test.
- benchmarkoor binary MUST be commit `1e0b9d4`. The prebuilt `~/benchmarkoor/bin/benchmarkoor` (`9b8a5d8`) lacks `promote_post_pre_runs` and runner `PreRuns` entirely and MUST NOT be used.
- `AMSTERDAM_ACTIVATION_TS` is `1769856769` for jochemnet and literal `1` for state-actor. A wrong value executes the wrong fork rules and produces valid-looking wrong numbers.
- Every long-running command runs detached under zellij on the host, logged untruncated. The original runs' logs truncated at exactly 10 MB and cost the ability to confirm their duration.
- Never modify `/Users/random_anon/dev/benchmarkoor` working tree — it is an upstream checkout with the user's untracked `CLAUDE.md`.
- Absolute MGas/s is NOT comparable to the report (different host). Only structural claims are in scope.

---

## File Structure

| Path | Responsibility |
| --- | --- |
| `/tmp/bmk-1e0b9d4/` (workstation) | throwaway git worktree used only to cross-compile |
| `/usr/local/bin/benchmarkoor` (host) | the `1e0b9d4` binary |
| `/root/bench/findings.md` (host) | Task 2 source-reading verdicts; consumed by Tasks 10-12 |
| `/root/bench/jochemnet.yaml` (host) | merged runner config, jochemnet arm |
| `/root/bench/state-actor.yaml` (host) | merged runner config, state-actor arm |
| `/root/bench/sentinels.txt` (host) | fixed sentinel file list + baseline sha256 |
| `/schelk-vols/*.img` (host, on `/`) | loopback backing files for virgin/scratch |
| `/ancient-store/jochemnet/24402727/chain` (host, on `/`) | hoisted chain freezer, bind-mounted read-only |
| `/sa-store/` (host, on `/`) | state-actor datadir while the jochemnet arm runs |
| `/data/bench-results/<arm>/` (host, HDD) | benchmarkoor results, off-mount |
| `/data/archive/` (host, HDD) | pristine + promoted virgin archives |
| `docs/superpowers/specs/2026-08-27-...-preregistration.md` (articles repo) | pre-registered predictions, committed before any run |

---

## Task 1: Cross-compile benchmarkoor at `1e0b9d4`

**Files:**
- Create: `/tmp/bmk-1e0b9d4/` (workstation worktree, deleted in step 5)
- Create: `/usr/local/bin/benchmarkoor` (host)

**Interfaces:**
- Produces: a linux/amd64 binary on the host whose `version` subcommand reports `1e0b9d4`. Every later task invokes it as `benchmarkoor`.

- [ ] **Step 1: Create a throwaway worktree at the exact commit**

```bash
cd /Users/random_anon/dev/benchmarkoor
git worktree add --detach /tmp/bmk-1e0b9d4 1e0b9d4
```

Expected: `HEAD is now at 1e0b9d4 fix: reachable replay anchor (#307)`

- [ ] **Step 2: Cross-compile**

```bash
cd /tmp/bmk-1e0b9d4
GOOS=linux GOARCH=amd64 CGO_ENABLED=0 go build -o /tmp/benchmarkoor-linux-amd64 ./cmd/benchmarkoor
file /tmp/benchmarkoor-linux-amd64
```

Expected: `ELF 64-bit LSB executable, x86-64`. If the build fails on a missing module, run `go mod download` first.

- [ ] **Step 3: Ship it**

```bash
tsh scp /tmp/benchmarkoor-linux-amd64 root@stateless-bloatnet-benchmarks:/usr/local/bin/benchmarkoor
tsh ssh root@stateless-bloatnet-benchmarks 'chmod +x /usr/local/bin/benchmarkoor'
```

- [ ] **Step 4: Verify the version — this is the gate**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'benchmarkoor version'
```

Expected: output contains `1e0b9d4`. There is no `--version` flag (see commit `fcca6d2`); the `version` subcommand is correct. If it reports `9b8a5d8`, the wrong binary is on PATH — check `command -v benchmarkoor` and that `~/benchmarkoor/bin` is not shadowing `/usr/local/bin`.

- [ ] **Step 5: Remove the worktree**

```bash
cd /Users/random_anon/dev/benchmarkoor && git worktree remove /tmp/bmk-1e0b9d4
```

---

## Task 2: Read six load-bearing behaviours out of the source

Reading requires no toolchain. Each answer changes a decision in a later task, so record all six before proceeding.

**Files:**
- Create: `/root/bench/findings.md` (host)
- Read: `/tmp/bmk-1e0b9d4` is gone; read from the workstation checkout at `1e0b9d4` via `git show`

**Interfaces:**
- Produces: `findings.md` with six verdicts. Task 10 reads verdict 6 to decide whether the Phase 2/3 config split is needed; Task 14 reads verdict 2.

- [ ] **Step 1: Answer verdict 6 first — it has the largest downstream effect**

```bash
cd /Users/random_anon/dev/benchmarkoor
git show 93e70fc --stat
git show 93e70fc -- pkg/runner/ | head -120
```

Question: does the runner skip the per-test pre-run replay once the baseline already carries it? Read the code, not the commit subject.

- [ ] **Step 2: Answer the remaining five**

```bash
git grep -n 'PromotePostPreRuns\|promote_post_pre_runs' 1e0b9d4 -- pkg/
git grep -n 'ExtraMounts' 1e0b9d4 -- pkg/runner/
git grep -n 'LiveReporting\|live_reporting' 1e0b9d4 -- pkg/config/ pkg/livereport/
```

1. Is pre-run execution gated by config, or unconditional per invocation?
2. Does promote fire when there are **zero** `pre_runs` blocks? (If yes, the state-actor config must not carry the flag — a pointless ~600 G copy.)
3. Does promote fire after a **failed** pre-run? (Decides whether Task 11's assertion order is load-bearing.)
4. Exactly what is bind-mounted into the container, and in what order relative to `extra_mounts`? (Confirms the nested `ancient/chain` mount resolves.)
5. Does `live_reporting.enabled: false` fully disable it, or does it still construct a client with an empty token?

- [ ] **Step 3: Record the verdicts**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'mkdir -p /root/bench'
```

Write `/root/bench/findings.md` with one heading per verdict, each stating the answer, the file and line consulted, and the decision it unblocks.

- [ ] **Step 4: Commit the findings to the articles repo**

```bash
cd /tmp/articles-spec
git add docs/superpowers/specs/ && git commit --no-gpg-sign -m "spec: record benchmarkoor source-reading verdicts"
```

---

## Task 3: Install podman and prepare the container runtime

**Files:**
- Modify: host system packages

**Interfaces:**
- Produces: working rootful `podman`, a `benchmarkoor` network, and the geth image pre-pulled so Task 11's timings do not include a first pull.

- [ ] **Step 1: Install**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'apt-get update -qq && apt-get install -y podman'
```

- [ ] **Step 2: Verify version and rootful operation**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'podman --version && podman info --format "{{.Host.Security.Rootless}}"'
```

Expected: `podman version 4.9.3`, and `false` for rootless.

- [ ] **Step 3: Create the network the config names**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'podman network create benchmarkoor 2>/dev/null; podman network ls'
```

Expected: a `benchmarkoor` network is listed.

- [ ] **Step 4: Pre-pull the geth image**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'podman pull ghcr.io/jochem-brouwer/go-ethereum:glamsterdam-devnet-7-blobpool-fix'
```

Expected: pull succeeds. This is the exact image the original runs used.

- [ ] **Step 5: Null-route the live-reporting ingest host**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'grep -q benchmarkoor-api /etc/hosts || echo "127.0.0.1 benchmarkoor-api.core.ethpandaops.io" >> /etc/hosts'
```

Belt-and-braces against per-test retry jitter. Remove this in Task 18.

---

## Task 4: Clear stale schelk state and measure sizing

**Files:**
- Modify: `/var/lib/schelk/state.json` (archived then removed)

**Interfaces:**
- Produces: a clean schelk slate, and two measured numbers — ext4 overhead ratio and the dm-era metadata estimate — consumed by Task 7's volume sizing.

- [ ] **Step 1: Archive and remove the orphaned state**

The current state references `/dev/loop0` and `/dev/loop1`, which have no backing files (`losetup -a` is empty), and `mount_point=/data/schelk`. benchmarkoor reads `mount_point` from this file, so a stale entry fails confusingly rather than loudly.

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'mkdir -p /root/bench && cp /var/lib/schelk/state.json /root/bench/state.json.orphaned-$(date +%s) && rm /var/lib/schelk/state.json && schelk status'
```

Expected: `schelk status` reports no configuration / missing state.

- [ ] **Step 2: Measure ext4 overhead on a small loop file**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'set -e
mkdir -p /schelk-vols
fallocate -l 10G /schelk-vols/probe.img
L=$(losetup --find --show /schelk-vols/probe.img)
mkfs.ext4 -q -m 0 $L
mkdir -p /mnt/probe && mount $L /mnt/probe
df -B1 --output=size,avail /mnt/probe | tail -1
umount /mnt/probe && losetup -d $L && rm /schelk-vols/probe.img'
```

Record `avail / size`. Expected roughly 0.97-0.98 with `-m 0`. Multiply the datadir size by `1 / ratio` and add slack when sizing in Task 7.

- [ ] **Step 3: Estimate dm-era metadata and check the ramdisk**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'echo "ram0 bytes: $(blockdev --getsize64 /dev/ram0)"; echo "blocks in 500G at 4096: $((500*1024*1024*1024/4096))"'
```

500 G at 4096 granularity is ~131 M blocks. Record the ram0 size (currently `brd rd_size=6291456` KiB = 6 GiB). The authoritative check is schelk's own runtime validation at Task 7 step 6 — this step exists so a failure there is diagnosable rather than surprising.

- [ ] **Step 4: Record uptime**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'uptime -s'
```

Note the boot time in `findings.md`. If the host reboots while schelk is mounted, dm-era metadata on ram0 is lost and only `schelk full-recover` is safe — never `recover`.

---

## Task 5: Download fixtures, static anchor check, fork gate (GATE 0)

**Files:**
- Create: `/data/fixtures/jochemnet.tar.gz`, `/data/fixtures/state-actor.tar.gz`

**Interfaces:**
- Produces: both fixture bundles on disk plus a schema description consumed by Task 17's join-key parsing. **This task is a gate: a fork-timestamp mismatch stops the plan.**

- [ ] **Step 1: Download both bundles**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'set -e; mkdir -p /data/fixtures && cd /data/fixtures
wget -c -O jochemnet.tar.gz https://github.com/ethpandaops/benchmarkoor-tests/releases/download/eest-payloads-jochemnet-v1-amsterdam-stateful-d9ad55b3-20260807-000744/eest-payloads-jochemnet-v1-amsterdam-stateful-geth.tar.gz
wget -c -O state-actor.tar.gz https://github.com/ethpandaops/benchmarkoor-tests/releases/download/eest-payloads-state-actor-v1-amsterdam-stateful-2282c757-20260722-144218/eest-payloads-state-actor-v1-amsterdam-stateful-geth.tar.gz
ls -l'
```

- [ ] **Step 2: Enumerate the actual fixture schema before assuming anchor fields**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'cd /data/fixtures && mkdir -p peek && tar tzf jochemnet.tar.gz | head -20 && tar xzf jochemnet.tar.gz -C peek --wildcards "*/blockchain_tests_stateful_engine/*" --strip-components=0 2>/dev/null | true; find peek -name "*.json" | head -3'
```

Then read one fixture and list its top-level keys. Do not assume a `newPayload`/`parentHash` shape — record what is actually there.

- [ ] **Step 3: Confirm the pre-run bundle is inside the jochemnet artifact**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'tar tzf /data/fixtures/jochemnet.tar.gz | grep -c "pre-runs/geth/pre_run_bundle"'
```

Expected: non-zero. The config's `pre_runs.fixtures_subdir` points here, and resolving it requires benchmarkoor `135f30c` (#296) — present at `1e0b9d4`, absent from the prebuilt binary.

- [ ] **Step 4: Static anchor check, jochemnet — an integrity check**

The head is known to be block 24402727 and the fixtures are labelled `block: "24402727"`. Compare the fixtures' anchor field (whatever step 2 revealed) against the datadir head. A mismatch means the compaction corrupted something: re-extract the tarball, re-compact, re-check.

- [ ] **Step 5: Static anchor check, state-actor — early warning only**

Compare the bundle's pre-state root / genesis state root against our generated head `0x5b305cc0f85f9ffaf5eca1e72cfe0c82f92e14f121aed163cc4c0e784aa3b6e7`. Bundle `2282c757` predates our regeneration, so a mismatch is *expected* and is not a stop — the decisive gate is dynamic, at Task 15. Record the result either way.

- [ ] **Step 6: Fork-timestamp gate — HARD STOP**

Extract the payload timestamps from one fixture in each bundle. Confirm:
- jochemnet payload timestamps are **at or after** `1769856769`
- state-actor payload timestamps are at or after `1`

If jochemnet's timestamps sit below `1769856769`, the blocks would execute under pre-amsterdam rules and every number produced would be plausible and wrong. **Stop and re-plan.**

---

## Task 6: Write and commit the pre-registration

**Files:**
- Create: `docs/superpowers/specs/2026-08-27-state-db-benchmark-preregistration.md` (articles repo worktree `/tmp/articles-spec`)

**Interfaces:**
- Produces: the committed prediction set that Task 17 evaluates verbatim. Must be committed **before** any benchmark runs; a prediction written afterwards is not a prediction.

- [ ] **Step 1: Copy the three prediction tiers out of the spec**

Copy Tier A (A1-A5), Tier B (B1-B5), Tier C (C1-C6), the "Explicitly ruled out" list, and the interpretation asymmetry from the spec's "Pre-registered predictions" section into the new file, verbatim.

- [ ] **Step 2: Fill in the sentinel set concretely**

Sentinel files, fixed once and reused for both arms: `CURRENT`, `MANIFEST-*`, `OPTIONS-*`, `triedb/merkle.journal`, and the 20 largest `.sst` files at baseline. Their baseline sha256 values get written to `/root/bench/sentinels.txt` in Task 8; this file records the *rule*.

- [ ] **Step 3: State the sigma rule for C4**

C4's band is the report's `[1.031, 1.117]` widened by ±3σ, where σ is measured at Task 11 step 8 from 3-5 repeats of one non-DIFF_MAX fixture. Record that the rule is fixed now and only the numeric value of σ is filled in later.

- [ ] **Step 4: Commit**

```bash
cd /tmp/articles-spec
git add docs/superpowers/specs/2026-08-27-state-db-benchmark-preregistration.md
git commit --no-gpg-sign -m "spec: pre-register predictions before any benchmark run"
git log --oneline -1
```

---

## Task 7: Relocate both datadirs out of `/schelk` and build the jochemnet volume

**Files:**
- Move: `/schelk/state-actor` → `/sa-store`
- Move: `.../chaindata/ancient/chain` → `/ancient-store/jochemnet/24402727/chain`
- Create: `/schelk-vols/jochemnet-virgin.img`, `/schelk-vols/jochemnet-scratch.img`

**Interfaces:**
- Produces: a schelk mount at `/schelk` whose filesystem root contains `snapshots/geth/jochemnet/24402727/geth/...`, so that `source_dir=/schelk/snapshots/geth/jochemnet/24402727` resolves. Task 10's config depends on this exact layout.

- [ ] **Step 1: Move state-actor out of the shadow path**

Mounting schelk at `/schelk` hides every plain directory beneath it. Both moves are renames on one filesystem — instant, no copying.

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'set -e; mkdir -p /sa-store && mv /schelk/state-actor /sa-store/ && ls /sa-store/state-actor/v1/geth/geth/'
```

Expected: `chaindata` listed.

- [ ] **Step 2: Hoist the chain freezer**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'set -e
A=/schelk/snapshots/geth/jochemnet/24402727/geth/chaindata/ancient
mkdir -p /ancient-store/jochemnet/24402727
mv $A/chain /ancient-store/jochemnet/24402727/chain
mkdir -p $A/chain
du -sh /ancient-store/jochemnet/24402727/chain $A/state
du -sh /schelk/snapshots/geth/jochemnet/24402727'
```

Expected: `700G` chain, `6.0G` state, and the datadir now ~385 G. The empty `$A/chain` directory left behind is the mountpoint Task 10's `extra_mounts` targets.

- [ ] **Step 3: Create the virgin loop file**

Size from Task 4 step 2's measured overhead; 500 G gives ~115 G internal slack over 385 G of content.

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'set -e
fallocate -l 500G /schelk-vols/jochemnet-virgin.img
V=$(losetup --find --show /schelk-vols/jochemnet-virgin.img)
echo "virgin=$V"
mkfs.ext4 -q -m 0 -L jochemnet-virgin $V
mkdir -p /mnt/virgin && mount $V /mnt/virgin
df -h /mnt/virgin'
```

- [ ] **Step 4: Populate the virgin, mirroring the `/schelk`-relative path**

The volume root becomes `/schelk`, so the interior path must be `snapshots/geth/jochemnet/24402727/`.

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'set -e
mkdir -p /mnt/virgin/snapshots/geth/jochemnet
rsync -aHAX --numeric-ids --info=progress2 \
  /schelk/snapshots/geth/jochemnet/24402727/ \
  /mnt/virgin/snapshots/geth/jochemnet/24402727/
du -sh /mnt/virgin/snapshots/geth/jochemnet/24402727'
```

Expected: ~385 G. Run this under zellij — it is tens of minutes.

- [ ] **Step 5: Verify the copy, then unmount**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'set -e
D=/mnt/virgin/snapshots/geth/jochemnet/24402727/geth
md5sum $D/triedb/merkle.journal
test -d $D/chaindata/ancient/chain && echo "chain mountpoint present"
test -d $D/chaindata/ancient/state && echo "state freezer inside volume"
umount /mnt/virgin'
```

Expected: md5 `5663fcb106f4d2bb42e4009a9ed0efa0`, both directory checks print. **Do not proceed if the md5 differs.**

- [ ] **Step 6: Delete the original and create the scratch — the irreversible step**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'set -e
rm -rf /schelk/snapshots/geth/jochemnet/24402727
df -h /
fallocate -l 500G /schelk-vols/jochemnet-scratch.img
S=$(losetup --find --show /schelk-vols/jochemnet-scratch.img)
echo "scratch=$S"
df -h /'
```

Expected: free space rises ~385 G after the delete, then falls ~500 G. Roughly 1.1 T free at the end.

- [ ] **Step 7: Initialise schelk**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'set -e
losetup -a
schelk init-from --virgin /dev/loopN --scratch /dev/loopM --ramdisk /dev/ram0 \
  --mount-point /schelk --fstype ext4 --dm-era-name jochemnet_era \
  --state-path /var/lib/schelk/state.json -y'
```

Substitute the actual loop devices printed in steps 3 and 6. `init-from` adopts the pre-populated virgin and copies it to scratch — this is where a too-small ramdisk surfaces. If schelk rejects the ramdisk, `modprobe -r brd && modprobe brd rd_size=<larger>`, or raise `--granularity` to `65536`.

- [ ] **Step 8: Confirm the mount and the resolvable source_dir**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'schelk status; ls /schelk/snapshots/geth/jochemnet/24402727/geth/'
```

Expected: `mount_point: /schelk`, mounted yes, and the geth datadir contents listed.

---

## Task 8: Record the baseline and archive the pristine virgin

**Files:**
- Create: `/root/bench/sentinels.txt`, `/data/archive/jochemnet-virgin-pristine.img.zst`

**Interfaces:**
- Produces: baseline sentinel hashes consumed by prediction B1 at Tasks 11/12, and the only cheap route back after Task 11's irreversible promote.

- [ ] **Step 1: Record the sentinel set and its baseline hashes**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'set -e
D=/schelk/snapshots/geth/jochemnet/24402727/geth
{ ls $D/chaindata/CURRENT $D/chaindata/MANIFEST-* $D/chaindata/OPTIONS-* $D/triedb/merkle.journal
  ls -S $D/chaindata/*.sst | head -20; } > /root/bench/sentinel-paths.txt
xargs sha256sum < /root/bench/sentinel-paths.txt > /root/bench/sentinels.txt
wc -l /root/bench/sentinels.txt'
```

Expected: 24 lines.

- [ ] **Step 2: Record the LSM baseline**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'D=/schelk/snapshots/geth/jochemnet/24402727/geth
ls $D/chaindata/*.sst | wc -l
stat -c "%n %s" $D/triedb/merkle.journal'
```

Expected: 9184 SSTs, journal 278500441 bytes. This is the post-compaction, pre-pre-run state.

- [ ] **Step 3: Archive the pristine virgin to HDD**

`promote` in Task 11 overwrites the virgin irreversibly, and the original directory was deleted in Task 7 step 6. The alternative recovery path is re-extract plus re-compact, which yields a different LSM shape and silently becomes a new variable.

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'set -e; mkdir -p /data/archive
zstd -T0 -3 /schelk-vols/jochemnet-virgin.img -o /data/archive/jochemnet-virgin-pristine.img.zst
ls -l /data/archive/'
```

Run under zellij. **Do not run Task 11 until this completes.**

---

## Task 9: Compose the jochemnet config

**Files:**
- Create: `/root/bench/jochemnet.yaml`

**Interfaces:**
- Produces: the merged runner config. Task 13's state-actor config is derived from this one by the differences listed in the spec's Configuration section.

- [ ] **Step 1: Write the config**

```yaml
global:
  log_level: info
  env:
    GETH_SNAPSHOT_DIR: /schelk/snapshots/geth/jochemnet/24402727
    GETH_GENESIS: https://gist.githubusercontent.com/jochem-brouwer/9cc7e180fbef1c7c388c0a12f7fd778c/raw/3f10decdd1b0cc0604d21901944ffa08bfe94581/gistfile1.json
    AMSTERDAM_ACTIVATION_TS: "1769856769"

runner:
  client_logs_to_stdout: true
  docker_network: benchmarkoor
  cleanup_on_start: true
  container_runtime: podman
  live_reporting:
    enabled: false
  benchmark:
    results_dir: /data/bench-results/jochemnet
    generate_results_index: true
    generate_suite_stats: true
    tests:
      metadata:
        labels:
          name: jochemnet-glamsterdam-devnet-7-stateful
          block: "24402727"
          test-type: stateful
          context: repricing
          fork: amsterdam
          data-disk-type: schelk
      source:
        eest_fixtures:
          fixtures_url: https://github.com/ethpandaops/benchmarkoor-tests/releases/download/eest-payloads-jochemnet-v1-amsterdam-stateful-d9ad55b3-20260807-000744/eest-payloads-jochemnet-v1-amsterdam-stateful-geth.tar.gz
          fixtures_subdir: benchmarkoor-build-artifacts/eest-payloads/geth/blockchain_tests_stateful_engine
          pre_runs:
            fixtures_subdir: benchmarkoor-build-artifacts/pre-runs/geth/pre_run_bundle
  client:
    config:
      rollback_strategy: container-recreate
      drop_memory_caches: "steps"
      genesis:
        geth: ${GETH_GENESIS}
    datadirs:
      geth:
        source_dir: ${GETH_SNAPSHOT_DIR}
        method: schelk
        schelk_options:
          promote_post_pre_runs: true
  instances:
    - id: geth-bal-full
      client: geth
      metadata:
        labels:
          bal-mode: full
      image: ghcr.io/jochem-brouwer/go-ethereum:glamsterdam-devnet-7-blobpool-fix
      extra_args:
        - --engine.maxreorgdepth=1024
        - --override.amsterdam=${AMSTERDAM_ACTIVATION_TS}
        - --debug.logslowblock=0
      extra_mounts:
        - source: /ancient-store/jochemnet/24402727/chain
          target: /data/geth/chaindata/ancient/chain
          read_only: true
```

- [ ] **Step 2: Verify it parses**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'benchmarkoor run --config /root/bench/jochemnet.yaml --help 2>&1 | head -5'
```

If benchmarkoor exposes a validate or dry-run flag (check `benchmarkoor run --help`), use it. Otherwise the parse is exercised for real at Task 10.

---

## Task 10: jochemnet setup + smoke (GATE 2)

**Files:**
- Modify: `/root/bench/jochemnet.yaml` (add `tests.filter`)
- Create: `/data/bench-results/jochemnet/`

**Interfaces:**
- Produces: the promoted baseline head **H**, the σ value for prediction C4, and the A1 journal measurement. Task 12 runs against H.

- [ ] **Step 1: Decide the config shape from Task 2 verdict 6**

If `93e70fc` (#298) skips the per-test replay once the baseline carries it, Tasks 10 and 12 share this one config and differ only by `tests.filter` — preferred, fewer deviations. If not, Task 12 must remove the `pre_runs` block and set `promote_post_pre_runs: false`. Record which branch was taken.

- [ ] **Step 2: Add a five-fixture filter**

Add under `runner.benchmark.tests`:

```yaml
      filter: "test_account_access and BALANCE and EXISTING_CONTRACT_DIFF_MAX"
```

Confirm the count is small before running: this filter targets the report's headline category, so the smoke exercises the exact tests the analysis cares about.

- [ ] **Step 3: Run the smoke under zellij**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'export XDG_RUNTIME_DIR=/run/user/0
zellij attach --create-background jochemnet-smoke
zellij --session jochemnet-smoke action new-pane --name smoke -- \
  bash -c "benchmarkoor run --config /root/bench/jochemnet.yaml 2>&1 | tee /root/bench/smoke-jochemnet-$(date +%Y%m%d-%H%M%S).log"'
```

- [ ] **Step 4: Assert pre-run success BEFORE accepting H**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'L=$(ls -t /root/bench/smoke-jochemnet-*.log | head -1); grep -iE "pre.?run|promote" $L | head -20'
```

Expected: pre-run replay completes, then a promote. If the pre-run failed but promote fired anyway, H is broken — restore from `/data/archive/jochemnet-virgin-pristine.img.zst` and stop.

- [ ] **Step 5: Measure the journal at H — prediction A1**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'D=/schelk/snapshots/geth/jochemnet/24402727/geth
stat -c "%s bytes" $D/triedb/merkle.journal; md5sum $D/triedb/merkle.journal
L=$(ls -t /root/bench/smoke-jochemnet-*.log | head -1); grep -iE "journal|layers" $L | head -10'
```

Expected: ~380.15 MiB (398,600,000 bytes ±10%) and layers ≈ 4248 ±10%, differing from the shipped `5663fcb1…`. **This is the highest-value check in the plan** — it tests setup equivalence against a number the report published, before 18 hours are spent. A large miss means the setups diverge; stop and re-plan.

- [ ] **Step 6: Assert the remaining smoke conditions**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'L=$(ls -t /root/bench/smoke-jochemnet-*.log | head -1)
echo "drop_caches:"; grep -ic "drop.*cache" $L
echo "live-report attempts:"; grep -ic "benchmarkoor-api\|live_report" $L
echo "recover cycles:"; grep -ic "schelk recover" $L
echo "cache config:"; grep -m1 "Allocated cache and file handles" $L
echo "trie caches:"; grep -m1 "Allocated trie memory caches" $L'
```

Expected: drop-cache lines present per iteration (A4); zero live-report attempts; ≥2 recover cycles; `cache=2.00GiB handles=536,870,908 version=v1` and `clean=1023.00MiB dirty=1.00GiB` (A2).

- [ ] **Step 7: Verify the read-only ancient mount held (A5)**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'find /ancient-store/jochemnet/24402727/chain -newermt "-2 hours" | head'
```

Expected: no output. If geth failed to boot because the freezer was read-only, set `read_only: false` in the config, re-run, and hash the directory before/after instead.

- [ ] **Step 8: Sentinel check after a recover (seeds B1)**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'sha256sum -c /root/bench/sentinels.txt 2>&1 | grep -c OK'
```

Expected: 24. Any FAILED line means `recover` is leaky — **stop**, because leaky recover produces drift indistinguishable from signal.

- [ ] **Step 9: Measure σ for prediction C4**

Re-run the smoke 3-5 times with a filter selecting one non-DIFF_MAX fixture. Record the per-run MGas/s and compute the standard deviation. Write σ into the pre-registration file and commit.

---

## Task 11: jochemnet full run

**Files:**
- Modify: `/root/bench/jochemnet.yaml` (remove `tests.filter`; apply the Task 10 step 1 branch)
- Create: `/data/bench-results/jochemnet/` results

**Interfaces:**
- Produces: 1463 test results consumed by Tasks 16-17.

- [ ] **Step 1: Remove the filter and apply the choreography branch**

Delete the `filter:` line. If Task 2 verdict 6 said #298 does **not** cover the double-replay case, also delete the `pre_runs:` block and set `promote_post_pre_runs: false`.

- [ ] **Step 2: Launch detached**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'export XDG_RUNTIME_DIR=/run/user/0
zellij attach --create-background jochemnet-full
zellij --session jochemnet-full action new-pane --name full -- \
  bash -c "benchmarkoor run --config /root/bench/jochemnet.yaml 2>&1 | tee /root/bench/full-jochemnet-$(date +%Y%m%d-%H%M%S).log"'
```

Expected duration ~10 h at the measured 25.1 s/test.

- [ ] **Step 3: Confirm the fixture count**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'grep -m1 "Discovered EEST fixtures" /root/bench/full-jochemnet-*.log'
```

Expected: `count=1463`.

- [ ] **Step 4: Sentinel check at test #100 (B1)**

Once iteration 100 appears in the log, re-run the `sha256sum -c` from Task 10 step 8. Expected: 24 OK.

- [ ] **Step 5: Monitor recover duration (B3)**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'grep -oE "schelk recover.*" /root/bench/full-jochemnet-*.log | tail -5'
```

Watch for monotonic growth beyond 2× first-decile to last-decile.

- [ ] **Step 6: Final sentinel check and results verification**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'sha256sum -c /root/bench/sentinels.txt | grep -c OK
ls /data/bench-results/jochemnet/ | head
find /data/bench-results/jochemnet -name "*.json" | wc -l'
```

Expected: 24 OK, and a results tree with roughly 1463 per-test entries.

---

## Task 12: Archive, tear down, and reset the ramdisk

**Files:**
- Create: `/data/archive/jochemnet-virgin-promoted.img.zst`
- Delete: `/schelk-vols/jochemnet-*.img`

**Interfaces:**
- Produces: free NVMe for the state-actor volume, plus a warm re-runnable jochemnet baseline at H.

- [ ] **Step 1: Archive the promoted virgin**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'zstd -T0 -3 /schelk-vols/jochemnet-virgin.img -o /data/archive/jochemnet-virgin-promoted.img.zst && ls -l /data/archive/'
```

Re-extract plus re-compact would produce a different LSM shape, so this archive is the only way to re-run jochemnet on the same baseline.

- [ ] **Step 2: Unmount and detach**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'set -e
schelk recover -y || true
umount /schelk || true
losetup -D
losetup -a
rm -f /schelk-vols/jochemnet-virgin.img /schelk-vols/jochemnet-scratch.img
df -h /'
```

Expected: `losetup -a` empty, ~1 T freed.

- [ ] **Step 3: Zero the ramdisk**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'blkdiscard /dev/ram0 2>/dev/null || dd if=/dev/zero of=/dev/ram0 bs=1M status=none; echo zeroed'
```

Sequential dm-era reuse over residual metadata is undefined per schelk's own documentation.

- [ ] **Step 4: Clear the schelk state for a fresh instance**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'mv /var/lib/schelk/state.json /root/bench/state.json.jochemnet && schelk status'
```

---

## Task 13: Build the state-actor volume and config

**Files:**
- Create: `/schelk-vols/sa-virgin.img`, `/schelk-vols/sa-scratch.img`, `/root/bench/state-actor.yaml`

**Interfaces:**
- Produces: a schelk mount whose root contains `state-actor/v1/geth/...`, so `source_dir=/schelk/state-actor/v1/geth` resolves.

- [ ] **Step 1: Build the volumes**

state-actor's freezer is 40 K, so the Option 2 split does not apply — the whole 553 G datadir goes inside a 700 G volume.

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'set -e
fallocate -l 700G /schelk-vols/sa-virgin.img
V=$(losetup --find --show /schelk-vols/sa-virgin.img); echo "virgin=$V"
mkfs.ext4 -q -m 0 -L sa-virgin $V
mkdir -p /mnt/virgin && mount $V /mnt/virgin
mkdir -p /mnt/virgin/state-actor/v1
rsync -aHAX --numeric-ids --info=progress2 /sa-store/state-actor/v1/geth/ /mnt/virgin/state-actor/v1/geth/
du -sh /mnt/virgin/state-actor/v1/geth
umount /mnt/virgin
fallocate -l 700G /schelk-vols/sa-scratch.img
S=$(losetup --find --show /schelk-vols/sa-scratch.img); echo "scratch=$S"'
```

Expected: ~553 G copied. Run under zellij.

- [ ] **Step 2: Initialise schelk with a fresh dm-era name**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'schelk init-from --virgin /dev/loopN --scratch /dev/loopM --ramdisk /dev/ram0 --mount-point /schelk --fstype ext4 --dm-era-name sa_era --state-path /var/lib/schelk/state.json -y
schelk status; ls /schelk/state-actor/v1/geth/geth/'
```

- [ ] **Step 3: Write the state-actor config**

Write `/root/bench/state-actor.yaml` in full. Note what is *absent* versus the
jochemnet config: no `GETH_GENESIS` and no `client.config.genesis` block (geth
reads chain config from the datadir — the generation log recorded "Genesis:
included, ready to use without geth init"), no `AMSTERDAM_ACTIVATION_TS` (the
fork is scheduled by a literal `1`), no `schelk_options` (with zero `pre_runs`,
per Task 2 verdict 2, it would at best waste a ~600 G copy), no `pre_runs`, and
no `extra_mounts` (this freezer is 40 K).

```yaml
global:
  log_level: info
  env:
    STATE_ACTOR_DIR: /schelk/state-actor/v1/geth

runner:
  client_logs_to_stdout: true
  docker_network: benchmarkoor
  cleanup_on_start: true
  container_runtime: podman
  live_reporting:
    enabled: false
  benchmark:
    results_dir: /data/bench-results/state-actor
    generate_results_index: true
    generate_suite_stats: true
    tests:
      metadata:
        labels:
          name: state-actor-glamsterdam-devnet-7-stateful
          block: "0"
          test-type: stateful
          context: repricing
          fork: amsterdam
          data-disk-type: schelk
      source:
        eest_fixtures:
          fixtures_url: https://github.com/ethpandaops/benchmarkoor-tests/releases/download/eest-payloads-state-actor-v1-amsterdam-stateful-2282c757-20260722-144218/eest-payloads-state-actor-v1-amsterdam-stateful-geth.tar.gz
          fixtures_subdir: benchmarkoor-build-artifacts/eest-payloads/geth/blockchain_tests_stateful_engine
  client:
    config:
      rollback_strategy: container-recreate
      drop_memory_caches: "steps"
    datadirs:
      geth:
        source_dir: ${STATE_ACTOR_DIR}
        method: schelk
  instances:
    - id: geth-bal-full
      client: geth
      metadata:
        labels:
          bal-mode: full
      image: ghcr.io/jochem-brouwer/go-ethereum:glamsterdam-devnet-7-blobpool-fix
      extra_args:
        - --engine.maxreorgdepth=1024
        - --override.amsterdam=1
        - --debug.logslowblock=0
```

- [ ] **Step 4: Rebuild the sentinel list for this arm**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'set -e
D=/schelk/state-actor/v1/geth/geth
{ ls $D/chaindata/CURRENT $D/chaindata/MANIFEST-* $D/chaindata/OPTIONS-*; ls -S $D/chaindata/*.sst | head -20; } > /root/bench/sa-sentinel-paths.txt
xargs sha256sum < /root/bench/sa-sentinel-paths.txt > /root/bench/sa-sentinels.txt
wc -l /root/bench/sa-sentinels.txt'
```

There is no journal on this arm, so the set is 23 files.

---

## Task 14: state-actor smoke — the decisive anchor gate (GATE 4)

**Files:**
- Modify: `/root/bench/state-actor.yaml` (add `tests.filter`)

**Interfaces:**
- Produces: the pass/fail verdict on whether the released `2282c757` fixtures anchor to our regenerated database. **A failure stops this arm only — the jochemnet dataset from Task 11 stays valid.**

- [ ] **Step 1: Add the same five-fixture filter and run**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'export XDG_RUNTIME_DIR=/run/user/0
zellij attach --create-background sa-smoke
zellij --session sa-smoke action new-pane --name smoke -- \
  bash -c "benchmarkoor run --config /root/bench/state-actor.yaml 2>&1 | tee /root/bench/smoke-sa-$(date +%Y%m%d-%H%M%S).log"'
```

- [ ] **Step 2: THE GATE — did the first payload get accepted?**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'L=$(ls -t /root/bench/smoke-sa-*.log | head -1)
grep -iE "newPayload|VALID|INVALID|status" $L | head -20'
```

Expected: payloads return `VALID`. If they return `INVALID` or the client rejects the anchor, the fixtures do not match our regenerated DB — **stop the state-actor arm, record the evidence, and report**. Fixture regeneration is explicitly out of scope for this pass.

- [ ] **Step 3: Assert A3 — no journal on this arm**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'L=$(ls -t /root/bench/smoke-sa-*.log | head -1); grep -i "journal" $L | head -5; ls /schelk/state-actor/v1/geth/geth/triedb/ 2>&1'
```

Expected: `journal not found` in the log, matching the report's 999/999.

- [ ] **Step 4: Repeat the Task 10 assertions**

drop_caches firing, zero live-report attempts, ≥2 recover cycles, sentinel check against `/root/bench/sa-sentinels.txt` returning 23 OK, and 3-5 repeats for this arm's own σ.

---

## Task 15: state-actor full run

**Files:**
- Modify: `/root/bench/state-actor.yaml` (remove filter)

- [ ] **Step 1: Remove the filter and launch detached**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'export XDG_RUNTIME_DIR=/run/user/0
zellij attach --create-background sa-full
zellij --session sa-full action new-pane --name full -- \
  bash -c "benchmarkoor run --config /root/bench/state-actor.yaml 2>&1 | tee /root/bench/full-sa-$(date +%Y%m%d-%H%M%S).log"'
```

Expected ~8 h at the measured 18.6 s/test.

- [ ] **Step 2: Sentinel checks at #1, #100, last (B1)**

Same command as Task 11 step 4 against `/root/bench/sa-sentinels.txt`. Expected 23 OK each time.

- [ ] **Step 3: Verify completion**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'grep -m1 "Discovered EEST fixtures" /root/bench/full-sa-*.log
find /data/bench-results/state-actor -name "*.json" | wc -l'
```

Expected: `count=1463` and a comparable number of result files. Note commit `65c967f` (#300) makes a run that benchmarked nothing exit non-zero, so a silent empty run is already guarded.

---

## Task 16: Evaluate the pre-registration and re-derive independently

**Files:**
- Create: `/tmp/articles-spec/docs/superpowers/specs/2026-08-27-state-db-benchmark-results.md`

**Interfaces:**
- Produces: the verified numbers that Task 17's agents are checked against. **Runs before any agent is dispatched.**

- [ ] **Step 1: Pull both result trees to the workstation**

```bash
tsh scp -r root@stateless-bloatnet-benchmarks:/data/bench-results /tmp/bench-results
tsh scp -r root@stateless-bloatnet-benchmarks:/root/bench /tmp/bench-logs
```

- [ ] **Step 2: Evaluate Tier A and Tier B verbatim**

Walk A1-A5 and B1-B5 from the pre-registration file, marking each pass/fail with its evidence. **A Tier B failure invalidates that arm's dataset outright** — record it and exclude the arm rather than interpreting it.

- [ ] **Step 3: Re-derive the headline quantities directly**

Compute from raw results, without any agent involvement:
- the six µs-per-lookup values per arm (one per account mode)
- each arm's within-arm spread (max ÷ min across the six modes)
- per-category cross-arm ratios (state-actor ÷ compacted)
- the worst-15 list by ratio
- test-population counts and the `gas_mismatches` total
- journal size and layer count from the geth logs

Join on the tuple `(opcode, account_mode, gas, value_sent, overhead_baseline)` parsed from test names — never fuzzy string matching (B5).

- [ ] **Step 4: Evaluate Tier C**

C1 (compacted spread > 3×, state-actor < 2×), C2 (compacted DIFF_MAX < 0.5× the median of the other five modes), C3 (worst divergent test is a BALANCE/DIFF_MAX parameterisation), C4 (13 non-DIFF_MAX categories inside the σ-widened band), C5 (negative `timing.execution_ms`, constant `state_reads`/`state_writes`), C6 (no state-actor mode deviates > 2× from its own median).

- [ ] **Step 5: Commit the derivation before dispatching agents**

```bash
cd /tmp/articles-spec && git add docs/superpowers/specs/ && git commit --no-gpg-sign -m "results: pre-registration evaluation and independent re-derivation"
```

Committing first means the agents cannot influence the baseline they are checked against.

---

## Task 17: Three-agent analysis and adjudication

**Files:**
- Modify: `docs/superpowers/specs/2026-08-27-state-db-benchmark-results.md`

**Interfaces:**
- Produces: the final claim-by-claim table. Consumes Task 16's derivation as the adjudication reference.

- [ ] **Step 1: Dispatch Recompute-A and Recompute-B in one batch**

Both receive: raw results JSON, geth logs, harness logs, the pre-registration file, and the tuple join-key spec. Neither receives the report's numbers or conclusions — withholding expected values is what stops them reverse-engineering 7.71× out of noise. B must use a different implementation path from A and must not see A's output. Dispatch as separate tasks in one batch with no shared channel.

Target quantities for both: per-test MGas/s and µs-per-lookup aggregated by the tuple; within-arm spread per arm; per-category cross-arm ratio; worst-N by ratio; test-population counts. Each must state its method.

- [ ] **Step 2: Dispatch Adversary-C**

C receives the report's full conclusions plus the new data, briefed to falsify journal-provenance as the root cause **and** to attack our own methodology — leaky recover, fork mis-scheduling, cache warmth, the bundle confound, loop-device effects.

- [ ] **Step 3: Adjudicate**

Where A and B agree **and** match Task 16's derivation, accept the number. Where any two disagree, go to the raw data and resolve it personally — the disagreement is the signal that something is being parsed or filtered differently. Apply the same treatment to C: an adversarial agent fabricates as confidently as an agreeable one.

- [ ] **Step 4: Write the claim table**

One row per report claim: *reproduced* / *not reproduced* / *not checkable*, with the pre-registration verdict and the evidence. Apply the pre-registered interpretation asymmetry — a **shrinking** DIFF_MAX divergence is causally uninterpretable because four confounds all push that way; **persistence at full magnitude** meaningfully weakens journal-provenance as sole cause.

- [ ] **Step 5: Restore the host and commit**

```bash
tsh ssh root@stateless-bloatnet-benchmarks 'sed -i "/benchmarkoor-api.core.ethpandaops.io/d" /etc/hosts'
cd /tmp/articles-spec && git add -A && git commit --no-gpg-sign -m "results: three-agent analysis, adjudication, and claim table"
```

- [ ] **Step 6: Re-plan the follow-up**

The obvious first candidate is the report's own flagged next step — rerunning state-actor on bundle `6142626aac06abc4` to remove the payload confound this pass deliberately reproduced — plus narrowing to `test_account_access` as agreed.

---

## Self-Review

**Spec coverage.** Phase 0 → Tasks 1-5; pre-registration → Task 6; Phase 1 → Tasks 7-8; Phase 2 → Tasks 9-10; Phase 3 → Task 11; Phase 4 → Tasks 12-15; Phase 5 → Tasks 16-17. The spec's five overrides all appear in Task 9's config; the Option 2 freezer split appears in Task 7 step 2 and Task 9's `extra_mounts`; the two archives appear in Tasks 8 and 12; ram0 zeroing in Task 12 step 3.

**Placeholder scan.** No TBD/TODO. Two deliberate substitutions remain and are called out in place: the loop device names in Tasks 7 and 13 (`/dev/loopN`, `/dev/loopM`) must be read from the `losetup --find --show` output printed a step earlier, and σ in Task 10 step 9 is measured, not guessed.

**Type consistency.** `source_dir` is `/schelk/snapshots/geth/jochemnet/24402727` in Tasks 7, 9, 10; `/schelk/state-actor/v1/geth` in Tasks 13-15. Sentinel files split into `/root/bench/sentinels.txt` (24 entries, jochemnet, includes the journal) and `/root/bench/sa-sentinels.txt` (23 entries, state-actor, no journal) — the counts differ deliberately and each task references the correct one. `AMSTERDAM_ACTIVATION_TS` is `1769856769` only in the jochemnet config and is deleted, not overridden, in Task 13.
