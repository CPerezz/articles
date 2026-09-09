# Besu state-DB divergence study — plan

Repeat the geth state-DB study on Besu: same chain, same fixtures, same generator
config, different client and different storage engine (RocksDB/Bonsai vs Pebble/pathdb).

Status: **plan, not started.** Written 2026-09-09 against verified facts (§2).

---

## 1. Why this is not a re-run

The geth study produced three results. They have very different transfer odds, and
that asymmetry is the whole point of doing Besu:

| # | geth finding | transfers to Besu? |
|---|---|---|
| F1 | 7× divergence root-caused to **pathdb journal residency** — 380.15 MiB / 4,248 diff layers baked into the promoted image, serving the last 4,248 blocks' accounts from RAM for all 1,463 tests | **Mechanism is geth-only.** The *class* — "a promoted snapshot bakes in whatever the client held in memory" — is universal. Besu's candidates are RocksDB WAL/memtables, Bonsai trie logs, `caches/logBloom-*.cache` |
| F2 | Fix: drain the journal, then compact. `BALANCE/DIFF_MAX@160M` 380 → 272 (drain) → 18.5 MGas/s (compact), against state-actor's 16.5 | Analogue exists and is **shipped**: `besu storage trie-log prune` + a RocksDB manual compaction (§2.3) |
| F3 | Residual ~10%: generated state is **incompressible by construction**. 31.3% vs 19.2% code-bearing accounts → 58.3 vs 49.6 B/entry → Snappy 0.991 vs 0.849 → blocks 4,043 vs 3,467 B → 1.99 vs 1.85 pages/read → measured +11.9% bytes, +10.7% time | **This is the crown jewel and it is engine-independent by hypothesis.** Different LSM, different compression config, same data. If it reproduces, F3 is a property of generated state. If it does not, F3 was Pebble-specific |

So the study inverts the geth one. There we spent 18 rounds eliminating hypotheses
blind. Here we know what to look for, so the mechanism work is **front-loaded into
short controlled experiments** (10-second block replays, not 16-hour suites), and the
full suites become confirmation and headline data rather than discovery.

---

## 2. Verified facts (checked 2026-09-09, not assumed)

### 2.1 Inputs exist
- `https://snapshots.ethpandaops.io/jochemnet/besu/24402727/snapshot.tar.zst` → HTTP 200,
  **1,003,259,660,471 bytes** (1.003 TB), `last-modified: 2026-04-27`. Same block height
  as the geth snapshot, whose tarball was 1,005,176,229,978 B.
- Tarball top level is a **`--data-path` root**, not a chaindata dir:
  `VERSION_METADATA.json`, `DATABASE_METADATA.json`, `fastsync/`, `caches/logBloom-*.cache`
  (25.6 MB each, many). Mount shape therefore differs from geth: schelk volume → `/data`
  directly (`besuSpec.DataDir() == "/data"`, `--data-path=/data`).
- `caches/logBloom-*.cache` and `fastsync/` are themselves recency artifacts of the
  producing node. Inventory them before the first run; they are F1-class suspects.

### 2.2 state-actor supports Besu natively
- `pkg/builder/state_actor.go` passes `--client=<client>`; `const gethDBSuffix = "/geth/chaindata"`
  with the comment *"Other clients use the datadir root as-is"* — so for Besu, `--db=` is
  the datadir root.
- `pkg/client/besu.go` carries `--genesis-state-hash-cache-enabled=true` with the comment:
  *"Required to boot a state-actor snapshot: state-actor writes synthetic state (and the
  genesis state root) directly into RocksDB and emits an empty chainspec alloc."*
  state-actor writes Bonsai/RocksDB directly. No conversion needed.
- `config.state-actor-eest.full.amsterdam.stateful.yaml` header: *"geth, nethermind, ethrex,
  reth and besu are enabled by default — each client needs its OWN multi-hundred-GB snapshot."*
  Its besu target:
  ```yaml
  - id: besu
    client: besu
    image: ethpandaops/besu:bal-devnet-7
    genesis_fork_override: { amsterdam: 1 }
    environment: { BESU_OPTS: "-Xms8g -Xmx8g -XX:+AlwaysPreTouch" }
    extra_args: [--p2p-enabled=true, --Xplugin-rocksdb-high-spec-enabled=true, ...]
  ```
- **Amsterdam activation differs by client**: geth/erigon `--override.amsterdam`, besu/reth/ethrex
  `genesis_fork_override`, nethermind `genesis_eip_override`. Getting this wrong is exactly the
  round-20 bug (`--override.amsterdam=1` vs `1769856769`) that cost a day. Pin it in Phase 2.

### 2.3 Besu's treatment tooling
- `besu storage trie-log count | prune | export | import` — **shipped**. `prune` removes trie
  log layers below the retention limit including orphans. This is the structural analogue of
  the `drainjournal` tool we had to write for geth.
- `--bonsai-historical-block-limit` (default **512**), `--bonsai-limit-trie-logs-enabled`,
  `--bonsai-trie-logs-pruning-window-size`, `--bonsai-cache-enabled` — the retention knobs.
- `besu storage rocksdb` has only `usage` and `x-stats`. **There is no `besu db compact`.**
  No `ldb`/`sst_dump` in the image or on the host.
  → **Compaction path (decided):** a ~30-line JVM tool run against
  `/opt/besu/lib/rocksdbjni-10.6.2.jar` — the exact jar Besu links — that lists column
  families, opens the closed DB, and calls `compactRange()` on each. Version-matched by
  construction; no format skew, no new dependency, no cgo.
  Rejected: building `ldb` from RocksDB source (version skew against 10.6.2, an hour of
  toolchain work); a Go/grocksdb tool (same skew plus cgo).

### 2.4 Payloads: already in hand, client-agnostic
**Nothing to fill and nothing to download.** The payloads are benchmarkoor's input, not a
per-client artifact, and the two cached bundles on the box (16 G total) are the complete
input for the Besu runs too.

The `geth` in the asset name and the path is the **filler** that produced the payloads, not
the client under test. The run config names the path literally:
```yaml
source:
  eest_fixtures:
    fixtures_url:    .../eest-payloads-state-actor-v1-amsterdam-stateful-geth.tar.gz
    fixtures_subdir: benchmarkoor-build-artifacts/eest-payloads/geth/blockchain_tests_stateful_engine
```
`fixtures_subdir` is not derived from the client — it is a literal, and the upstream config
labels the same knob `EEST_FIXTURES_RUNNER_SOURCE: geth   # which filler's fixtures the runner
replays`. Both lines carry over to the Besu configs verbatim, pointing at the same two cached
bundles: `eest-url/6142626aac06abc4` (jochemnet arm) and `eest-url/3cf555c593bcb136`
(state-actor arm).

One assertion this does impose, in Phase 1b: the generated Besu state-actor store must
anchor to the **same** state root the payloads expect. state-actor is deterministic across
clients for a given seed — the upstream config asserts it for another pair (*"the
geth/nethermind genesis state roots match"*) — so `--seed=42` plus the same spec should
reproduce the geth anchor exactly. A mismatch means the seed or spec drifted, and it must
fail loudly at generation time rather than as a confusing `INVALID` mid-suite.

### 2.5 Space and hardware
| mount | dev | size | free now | after teardown |
|---|---|---|---|---|
| `/` | md2 (NVMe) | 3.5 T | 219 G | **~3.2 T** |
| `/data` | md3 (HDD) | 29 T | 7.2 T | ~10.5 T |

Occupying NVMe today: `jochemnet-virgin.img` 1.2 T, `jochemnet-scratch.img` 1.2 T,
`sa-nvme.img` 600 G = 3.0 T. Besu needs the same three (~3.0 T) → **teardown is a hard
prerequisite, and the arms still cannot all be resident at once.** Sequence as before.

Hard constraint carried over from the geth study: **every timing comparison runs on md2
(NVMe), both arms, same device.** The HDD array has 8× different readahead (2048 vs 256 KB)
and cross-stack measurement is what invalidated rounds 13/17/18.

---

## 3. Decisions

**D1 — compaction protocol. Mirror geth: compact once, after the pre-runs, before promote.**
The request said "compact prior to every test payload"; the geth study did *not* do that.
The record is `BENCHMARKOOR_POST_PRERUN_CMD='drainjournal --datadir $DATADIR && geth db compact
--datadir $DATADIR'`, run once between "pre-runs complete, client stopped, fs synced" and
`schelk promote` — 9,346 → 8,438 SSTs, once. Per-test compaction would add ~24 s × ~1,460
tests ≈ 10 h per arm and, worse, would make the Besu numbers non-comparable with the published
geth ones. Taking the conservative option: identical protocol. Say the word and the per-test
variant is a one-line hook change.

**D2 — teardown scope.** Wipe geth run artifacts; keep evidence and inputs.

| delete | size | why safe |
|---|---|---|
| `/schelk-vols/{jochemnet-virgin,jochemnet-scratch,sa-nvme}.img` | 3.0 T | required for space; rebuildable from tarball + generator |
| `/data/archive/jochemnet-virgin-{pristine,promoted}.img.zst` | 1.8 T | frozen images, rebuildable |
| `/data/sa-store` | 551 G | geth SA store, regenerable (seed 42) |
| `/data/snapshots/jochemnet/snapshot-24402727.tar.zst` | 937 G | re-downloadable; URL + expected bytes recorded in the article |

| keep | size | why |
|---|---|---|
| `/root/.cache/benchmarkoor/eest-url/*` | 16 G | **the complete payload input for the Besu runs** (§2.4) |
| `/data/fixtures` | 2.1 G | payloads |
| `/data/bench-results`, `/data/archive/run1` | 14 G | **raw evidence behind a published article.** Deleting it to save 14 G of 10 T would be indefensible |
| `/root/bench/*.yaml`, benchmarkoor binary | — | templates for the Besu configs |
| `/data/eth` (17 T), `/data/allhot-src-parked`, `/data/CPerezz-preserved` | — | not ours |
| `/data/tmp/benchmarkoor-overlay-geth-allcold-hdd-*` | 2.3 T | **flagged, not deleted** — dated 2026-06-30, a different study. Confirm with the operator |

**D3 — deliverable.** A companion article in a new `besu-state-db-divergence/` folder with its
own generator, copy-adapted from `gen_state_db_report.py`. Not a generalised two-client
generator: the shapes genuinely differ (RocksDB CF/level metrics vs pebble; trie logs vs
journal), and one-shot report generators are the wrong place to grow an abstraction.
*Skipped: generalising the generator — add when a third client happens.*

---

## 4. Pre-registration (write before data, per the geth study's §preregistration)

Committed **before** the first suite runs. Each gets a verdict in the ledger, retractions included.

- **P1 — compaction spread is smaller on Besu than geth.** geth: 13 non-DIFF_MAX categories
  1.031–1.117× (median 1.091) compacted-vs-uncompacted. RocksDB auto-compacts more
  aggressively than Pebble did here (geth's virgin store carried 9,346 SSTs). Predict Besu's
  spread < geth's.
- **P2 — a recency artifact exists in the promoted Besu image.** Some outlier class analogous
  to `DIFF_MAX` (geth: 7.71× on BALANCE, 23× on the worst cell). Sources ranked: trie logs
  (512-block default retention) > RocksDB WAL/memtable at shutdown > `caches/logBloom-*`.
  Magnitude unpredicted.
- **P3 — the residual reproduces.** state-actor ~10% slower than jochemnet on matched NVMe
  after treatment, driven by record entropy, not tree depth or cache.
- **P4 — quantitative F3 transfer.** Predict bytes-per-account-read ratio in **1.10–1.15**
  (geth measured 1.119) and the same arithmetic chain: entries/block and physical/logical
  measured *before* the timing run, block-size ratio predicting the byte ratio to within
  the geth study's own error (predicted +18.4% vs measured +17.1% at the analogous step).
- **P5 — accounts read are identical across arms** (geth: 51,565 vs 51,562, ±0.006%).
  If Besu's arms differ in read *count*, the whole residual framing is wrong for Besu and
  P3/P4 are void.

---

## 5. Phases

### Phase 0 — teardown (1 h)
Execute D2. Verify: `/` free ≥ 3.0 T; payload caches and `bench-results` intact
(`sha256sum` the two eest-url trees before and after); `git status` clean in all article
worktrees. **Gate:** no Besu work starts until free space is confirmed.

### Phase 1 — inputs (long, parallel, unattended)
1a. **Download + extract** the Besu snapshot to HDD, then place on NVMe. Reuse the geth
`fetch-jochemnet.sh` shape: `wget -c` (resumable), keep the tarball, `zstd -d` as the
integrity check (upstream ships no `.sha256`), log phase markers. ~6 h.
1b. **Generate the Besu state-actor store.** Three sub-steps, because the obvious one-liner
does not work.

**1b-i — the host binary cannot write Besu.** Verified by running it (2026-09-09):
```
$ /home/CPerezz/bin/state-actor --db=… --client=besu --target-size=1GB …
Failed to populate Besu DB: client/besu: requires the cgo_besu build tag and librocksdb.
--client=besu is Docker-only — build with `docker build -f Dockerfile.besu .`
```
The binary that produced the geth baseline advertises `-client` values
`geth|nethermind|besu|reth|ethrex|erigon`, but the Besu writer is a cgo build linked against
librocksdb and is shipped only as an image. `--fork` support is identical for both clients
(`osaka`, `prague`), so `--fork=osaka` mirrors cleanly.

**1b-ii — build the image from the same source state as the geth store.** `make docker-besu`
in `/home/CPerezz/state-actor`, which is at commit `e4cb205` **with 31 uncommitted files** —
the exact tree the geth baseline binary was built from, recorded in
`state-actor-build-provenance.diff`. Building from a clean checkout instead would mean the two
stores were produced by two different generators, which quietly undermines every cross-arm
claim in the study. Record the image digest next to the geth binary's provenance.
*Toolchain note:* the Makefile targets call `docker`; this box runs **podman**. Alias or
transcribe the commands.

**1b-iii — gate on upstream's own reproducer before spending hours.**
`make smoke-besu TARGET_SIZE=4MB` generates a small store, boots `hyperledger/besu` against it,
sends 100 dev-mode transactions and runs `validate-big-db-besu.sh`. Minutes, and it fails fast
if the cgo writer is broken on this host.

Then the real generation, mirroring the geth invocation — note `--db` is the **datadir root**
for Besu (§2.2), which is also how upstream's own smoke target invokes it:
```
podman run -v <store>:/data -v <spec>:/spec.yaml:ro state-actor-besu:latest \
  --client=besu --db=/data --target-size=350GB --spec=/spec.yaml \
  --seed=42 --fork=osaka --gas-limit=1000000000
```
Run as the invoking user so the output datadir is not root-owned. Unknown runtime; geth took 5.5 h.

**Acceptance:** store boots under Besu, `eth_blockNumber` answers, and its genesis state root
**equals the anchor in the cached state-actor payload bundle** (§2.4). Check this the moment
generation finishes — it is ten minutes of work that de-risks the whole state-actor arm.

### Phase 2 — harness (4 h)
- Build the RocksDB compactor (§2.3); verify on a throwaway copy that SST count and level
  distribution move, and that Besu still boots after.
- Wire `BENCHMARKOOR_POST_PRERUN_CMD='besu storage trie-log prune --data-path=$DATADIR && rocksdb-compact $DATADIR'`
  (the hook from ethpandaops/benchmarkoor#315 is client-agnostic — it takes a shell command
  with `$DATADIR` — so no benchmarkoor change is needed).
- Pin the client config **once**, and use it for every probe from here on. The single most
  expensive lesson of the geth study was that rounds 1–19 all measured a configuration the
  benchmark never ran. Required: `genesis_fork_override: { amsterdam: 1 }`, the harness's own
  cache/JVM flags, the **setup block**, the **pre-run block**, and a **startup forkchoice**
  if the store has no head marker.
- Take the "before" inventory on both stores: `besu storage rocksdb usage`, `storage trie-log count`,
  SST inventory per level, `caches/` contents. This is the Besu analogue of `geth db inspect`
  and it is the side-by-side table the article opens with.

### Phase 3 — pilot (3 h) — **hard gate before spending 48 h**
Run a handful of tests per arm end to end. Assert:
- all three arms boot, execute the real block, and return `VALID` (not `SYNCING`/`INVALID`);
- accounts-read counters are non-zero and equal across arms (P5's precondition);
- the treatment measurably changes the store (trie-log count → 0, SST count drops).
Any failure here is a config bug, and it is 100× cheaper to find now.

### Phase 4 — the three suites (~48 h, unattended)
`besu-jochemnet-virgin`, `besu-jochemnet-treated`, `besu-state-actor`. Same fixtures, same
host, same NVMe device, three runs each where variance matters. Archive raw results
immediately (the geth run-1 archive is why we can still audit that study).

### Phase 5 — mechanism experiments (4 h) — short, targeted, from the pre-registration
Ports of the geth tools, all already written and all fast:
- `blockrun.py` — replay one real benchmark block per store, matched media, page cache
  dropped, three runs. Yields wall / accounts / disk bytes per arm. **This is the P3/P4 test
  and it takes 10 seconds per measurement, not 16 hours.**
- `snapstat` — account-record shape (mean bytes, code-bearing %) per store.
- `sstgeom` — real SST block geometry (compressed bytes/block, records/block, physical÷logical),
  reading RocksDB SST properties instead of pebble's.
Each round: hypothesis, test, result, verdict — one commit each, into
`docs/superpowers/specs/2026-09-XX-besu-residual-ledger.md`.

### Phase 6 — article (8 h)
`besu-state-db-divergence/` + generator + committed data JSON + fetch-free SVGs, same gates:
oracle count, zero JS, self-check, live verification. The comparison table against the geth
findings is the payload; write the conclusion after Phase 5, never before.

---

## 6. Risks

| risk | likelihood | mitigation |
|---|---|---|
| state-actor's besu store anchors to a different state root than the payloads | low | deterministic for a fixed seed; asserted at Phase 1b acceptance, ten minutes after generation |
| state-actor's besu writer is cgo/Docker-only and less trodden than geth's | **confirmed, mitigated** | host binary cannot write Besu at all (§1b-i); image build + `make smoke-besu` gate it in minutes, before the 6–12 h run |
| Besu store built from a different generator source than the geth store | medium | build from `e4cb205` + the 31 dirty files, per `state-actor-build-provenance.diff`; record the image digest |
| No `besu db compact` → custom tool | **resolved** | version-matched JNI tool, §2.3 |
| NVMe cannot hold all three arms | certain | sequence arms; rebuild volumes between them, as in the geth study |
| Besu has no journal-equivalent and P2 is null | real, and fine | a null P2 is a *result*: it isolates F1 as geth-specific and strengthens F3's engine-independence |
| Fork-activation mechanism differs (`genesis_fork_override`) | high if unpinned | Phase 2 pins it; Phase 3 catches it |

**Budget:** ~4–5 days wall clock, most of it unattended (6 h download, 6–12 h generation,
48 h suites). Attended work is roughly 20 h.

---

## 7. Acceptance

Done when: three Besu arms measured on matched NVMe with the harness's own configuration;
P1–P5 each carry a verdict backed by a committed measurement, retractions included; the
mechanism question ("does the incompressible-records finding survive a different storage
engine?") is answered either way with data; and the companion article is live with every
number generated from committed data.
