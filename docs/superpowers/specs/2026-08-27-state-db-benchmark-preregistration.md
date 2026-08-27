# Pre-registered predictions — state-DB benchmark reproduction

Committed **before any benchmark run**. Task 16 evaluates this file verbatim before
any narrative is written. A prediction added after data exists is not a prediction.

Spec: `2026-08-27-state-db-benchmark-reproduction-design.md`
Plan: `../plans/2026-08-27-state-db-benchmark-reproduction.md`

## Preconditions already verified (Task 5, GATE 0 — PASS)

These are recorded as facts, not predictions, because they were established before
any run:

- **state-actor arm anchors.** The bundled `state-actor-manifest.json` inside the
  `2282c757` fixtures reports `state_root
  0x5b305cc0f85f9ffaf5eca1e72cfe0c82f92e14f121aed163cc4c0e784aa3b6e7`,
  422,456,696 accounts, 8,240,042 contracts, 1,878,617,248 storage slots, and
  `spec.sha256 74dea7d1…`. Our regenerated DB matches **every one of those values**,
  and the bundled spec YAML is byte-identical to ours (`md5 8bc1dd3a…`). Build
  provenance differs (theirs `7bfb6f4b`, `vcs_modified: false`, go1.25.12; ours
  `e4cb2058-dirty`, go1.25.7) — state-equivalent, build-divergent.
- **Fork gates pass.** jochemnet fixtures: `network: Amsterdam`, first payload
  timestamp 1,769,949,600 ≥ `AMSTERDAM_ACTIVATION_TS` 1,769,856,769. state-actor
  fixtures: `network: Amsterdam`, first payload timestamp 25 ≥ 1.
- **Fixture anchor fields** are `snapshotBlockNumber` / `snapshotBlockHash`.
  jochemnet expects block 24,410,463 (`0x4525339a…`), 7,736 blocks ahead of the
  snapshot's 24,402,727 — that gap is the pre-run bundle's advancement and is
  verified at run time by `verifyPreRunBundleHead`, not statically. state-actor
  expects block 0, genesis hash `0xa9e61c12…`.
- **Fill parameters** (`fixtures.ini`): `--fork=amsterdam`,
  `--gas-benchmark-values=100,120,140,160,180,200,220,240,260,280,300`,
  `-m repricing`, `--snapshot-block=0x4525339a…`, filled 2026-08-07.

## Tier A — setup fidelity, evaluated before any benchmark completes

- **A1** Journal at the promoted head H = **380.15 MiB ± 10%**, **layers 4248 ± 10%**.
  The report published both. The shipped journal is 265.6 MiB
  (`md5 5663fcb106f4d2bb42e4009a9ed0efa0`); 380.15 − 265.6 = 114.5 MiB is the growth
  a pre-run of this size should add. Highest-value check in the plan: it tests setup
  equivalence against a published number ~30 minutes in rather than 18 hours in.
- **A2** geth logs `cache=2.00GiB handles=536,870,908 version=v1` and
  `clean=1023.00MiB dirty=1.00GiB`.
- **A3** state-actor arm: journal absent (`journal not found`, 999/999).
- **A4** `drop_memory_caches` observed firing on **every** iteration.
- **A5** `ancient/` content unchanged across the run.

## Tier B — run integrity; a failure invalidates that arm's dataset outright

- **B1** Sentinel file hashes identical after `recover` at tests #1, #100 and last.
  **Sentinel set**, fixed once at baseline and reused unchanged within an arm:
  `CURRENT`, `MANIFEST-*`, `OPTIONS-*`, `triedb/merkle.journal` (jochemnet only),
  and the 20 largest `.sst` files at baseline, recorded by path and sha256 in
  `/root/bench/sentinels.txt` (jochemnet, 24 entries) and
  `/root/bench/sa-sentinels.txt` (state-actor, 23 entries).
- **B2** |Spearman ρ| between per-test residual and iteration index < 0.2.
- **B3** `recover` duration shows no monotonic growth beyond 2× first-decile to
  last-decile.
- **B4** `gas_mismatches == 0`.
- **B5** ≥ 350 of the report's 406 test IDs recovered via the tuple join key
  `(opcode, account_mode, gas, value_sent, overhead_baseline)` parsed from test
  names — never fuzzy string matching.

## Tier C — the report's claims

C1 and C2 are **within-arm**, so they are immune to both confounds that damage
everything else: the different fixture bundles and the different host.

- **C1** Compacted's µs-per-lookup spread across the six account modes greatly
  exceeds state-actor's. Report: 7.2× vs 1.1×. Predict **compacted > 3×,
  state-actor < 2×**.
- **C2** Within compacted, DIFF_MAX is the fast outlier (report: 2.1 µs vs ~14 µs
  for the other five). Predict **DIFF_MAX < 0.5× the median of the other five**.
- **C3** The worst cross-arm divergent test is a **BALANCE/DIFF_MAX**
  parameterisation — identity only, not magnitude.
- **C4** The 13 non-DIFF_MAX categories cluster in a narrow cross-arm band. Report:
  [1.031, 1.117]. Band = that interval widened by **±3σ**, where σ is measured at
  the smoke from 3-5 repeats of one non-DIFF_MAX fixture. **The rule is fixed now;
  only the numeric value of σ is filled in later.** Directional and confounded.
- **C5** Instrumentation defects reproduce: negative `timing.execution_ms` on
  value-transfer blocks, and constant `state_reads`/`state_writes` per block shape.
  Same geth build, so these should reappear; bundle-independent.
- **C6** No state-actor account mode deviates from that arm's own median by > 2×.

## Explicitly ruled out

Absolute MGas/s comparisons. The 7.71× and 12.1× magnitudes as *reproductions*.
Every uncompacted-arm claim (c/u drift 0.237-1.220, the compacted-faster set, the
7.1× spread) — that arm was compacted in place and no longer exists. The vs1 SA
separation 8.07-10.57× as a reproduction rather than a generalization test. The
33/92/50 bucket counts as exact figures.

## Interpretation asymmetry

Four independent changes — the journal being consumed and rewritten by the pre-run,
the L6 collapse from our compaction, the different fixture bundle, and the different
host — all push toward *less* divergence.

- If DIFF_MAX divergence **shrinks**: causally uninterpretable. Too many confounds
  point that way; attributing it to any one would be storytelling.
- If it **persists at full magnitude** despite all four: meaningfully weakens
  journal-provenance as the sole root cause.

Only one outcome carries information. Which one is fixed here, in advance.
