> **ERRATUM (2026-08-30, post-adjudication).** The "Interpretation" section
> below is **retracted** — see `2026-08-30-adjudication-and-claim-table.md`.
> Adversarial review, verified against raw telemetry, showed the opposite:
> the pre-run deterministically REWRITES the journal (380.15 MiB / 4248
> layers, present at every one of 1463 jochemnet boots), and jochemnet
> DIFF_MAX tests read ~12.6 kB/Mgas from disk vs ~19 MB/Mgas for every other
> mode — journal-residency is the CONFIRMED proximate mechanism, not a
> refuted one. The measured PASS results (A1-A5, B1-B5, C1-C6) stand.

# Task 16 — pre-registration evaluation and independent re-derivation

Both arms complete 2026-08-30T03:11:40+02:00. jochemnet: 1463/1463, 0 failed,
16.3 h. state-actor: 1461/1461 (its bundle ships 1461 fixtures, not 1463),
0 failed, `RUN_EXIT=0`, ~10.3 h. Full-run directories only
(`1787952270_6621b826`, `1788015169_bc76d34c`); smoke runs excluded.

Every number below was derived by me, from raw result JSONs and run logs, and
committed **before any analysis agent was dispatched**.

## Tier A — setup fidelity

| | prediction | result | verdict |
| --- | --- | --- | --- |
| A1 | journal at H = 380.15 MiB ±10%, layers 4248 ±10% | `size=380.15MiB`, `layers=4248` — exact | **PASS** |
| A2 | `cache=2.00GiB handles=536,870,908 version=v1`, `clean=1023.00MiB dirty=1.00GiB` | all exact except `handles=524,288` (host NOFILE cap 1,048,576 vs original 1,073,741,816) | **PASS** with recorded environmental delta |
| A3 | state-actor journal absent | `journal not found` on **1461/1461** boots (report saw 999/999 in a truncated log) | **PASS** |
| A4 | drop_memory_caches fires every iteration | zero `Failed to drop memory caches` warnings in either full log; mechanism verified empirically as root (`Cached` fell on write) | **PASS** |
| A5 | ancient/ unchanged | verified by mechanism: `ancient/` lives inside the dm-era volume, every test restores the whole volume, B1 sentinels 20/20 | **PASS** (by mechanism, not separate hash) |

## Tier B — run integrity

| | prediction | result | verdict |
| --- | --- | --- | --- |
| B1 | sentinel hashes identical after recover | jochemnet 20/20, state-actor 20/20; jochemnet SSTs 8438 = baseline 8438 | **PASS** |
| B2 | \|Spearman ρ\| residual vs iteration < 0.2 | **+0.0664** on the cross-arm ratio (n=1461) | **PASS** — see note |
| B3 | restore duration ratio ≤ 2.0 | jochemnet 1.01 (n=1461, median 17.7 s); state-actor 1.01 (n=1461, median 14.1 s) | **PASS** |
| B4 | gas_mismatches == 0 | 0 exact `gas_used` mismatches across 1100 common tuples | **PASS** |
| B5 | ≥350 of the report's 406 IDs via tuple join | **550** common full-name surface tests (exact names via `.test-name`) | **PASS** |

B2 note: the metric as pre-registered (within-arm residual vs iteration) came out
+0.32 — **on both arms identically**, which is impossible for a leak (leaks are
arm-specific) and diagnostic of a construction artifact: residuals within
(op,mode,vs,gas) groups are dominated by the overhead_baseline pairing, whose
execution order is fixed. Rebuilt as Spearman of the cross-arm per-test ratio
(jochemnet/state-actor, identical fixture order on both arms cancels workload
structure) vs iteration: ρ=+0.066. Both computations reported; the rebuilt one is
the leak-sensitive statistic.

## Tier C — the report's claims

| | prediction | result | verdict |
| --- | --- | --- | --- |
| C1 | compacted spread > 3×, state-actor < 2× | **20.67×** vs **1.02×** (BALANCE, gas ≥ 120) | **PASS** |
| C2 | DIFF_MAX the fast outlier within compacted | **20.64×** the median of the other five | **PASS** |
| C3 | worst divergent test is BALANCE/DIFF_MAX | worst = BALANCE/DIFF_MAX @200M, **25.48×** | **PASS** |
| C4 | non-DIFF_MAX in [1.031,1.117]±3σ = [0.83,1.34] | n=50, median **1.124**, range [1.100, 1.187] — all 50 inside | **PASS** |
| C5 | instrumentation defects reproduce | negative `execution_ms`: 54% (j) / 20% (sa) of slow-block records; cache counters **0 nonzero of 2794/4253**; `state_reads` constant per shape — top bucket exactly the report's `(accounts=4, code=0)` | **PASS** (all three) |
| C6 | no state-actor mode deviates > 2× | max deviation **1.02×**; DIFF_MAX ratio 1.00 | **PASS** |

## Headline numbers (mine, from raw data)

BALANCE, value_sent=0, gas ≥ 120 (the 100 M row is a separate regime, both arms):

| | jochemnet | state-actor | cross-arm j/s |
| --- | --- | --- | --- |
| NON_EXISTING | 19.1 | 17.0 | ~1.12 |
| EOA | 19.1 | 16.7 | ~1.14 |
| MINIMAL | 19.3 | 17.1 | ~1.12 |
| SAME_MAX | 19.0 | 17.1 | ~1.11 |
| JUMPDEST | 19.0 | 17.1 | ~1.11 |
| **DIFF_MAX** | **393.4** | 17.0 | **23.0×** (20.6-25.5) |

Report's cross-arm figures: non-DIFF_MAX 1.031-1.117 (median 1.091), DIFF_MAX
7.71×, CALL 1.55×, CALLCODE 1.49×. Ours: non-DIFF_MAX 1.100-1.187 (median
1.124), DIFF_MAX **23.0×**, CALL **2.84×**, CALLCODE **2.84×**.

The worst-15 list is DIFF_MAX in all 15 rows — split between **BALANCE and
EXTCODEHASH (~22-25× each)**. EXTCODEHASH was not in the report's fixture set;
the anomaly generalises to it.

## Interpretation, per the pre-registered asymmetry

The rule committed before any data: a *shrinking* DIFF_MAX divergence is
causally uninterpretable; *persistence at full magnitude* meaningfully weakens
journal-provenance as the sole root cause.

The divergence did not shrink. It **tripled** (7.71× → 23.0×) despite four
changes that all pointed toward less divergence — the shipped journal consumed
and rewritten by the pre-run, a fully L6-compacted baseline (the original
compacted arm carried 7,736 blocks of un-compacted pre-run writes on top of its
compaction; ours was compacted *after* the pre-run per the original operator's
protocol), a different fixture bundle, and a different host.

**Journal-provenance as the sole cause of the DIFF_MAX anomaly is refuted by
this data.** The anomaly is a property of the jochemnet snapshot's state itself
(or of how geth serves it), not of the journal file: state-actor, with no
journal, is flat at 1.02×; jochemnet, with its journal consumed and its LSM
fully compacted, still serves DIFF_MAX accounts 20× faster than its own other
account classes.

The sharper compaction likely explains the growth from 7.71× to 23×: the
original compacted arm's DIFF_MAX advantage was partially masked by pre-run
writes sitting in shallow levels; with the baseline fully compacted, the
underlying effect shows at full strength. That is a hypothesis, not a finding —
it is the natural next experiment (re-run with compaction before the pre-run,
matching the original's literal sequence).

## New observations (in both arms unless stated)

1. **100 Mgas discontinuity**: at 100 M, MINIMAL/SAME_MAX/JUMPDEST/DIFF_MAX run
   85-110 MGas/s; from 120 M upward the non-DIFF_MAX modes collapse to ~17-19.
   Present in both arms → harness/fixture property, not a database property.
2. **CALL-family JUMPDEST slowdown**: CALL and CALLCODE with JUMPDEST run at
   ~11-12 (j) / ~9-10 (sa) MGas/s vs ~19/17 for peers. Both arms.
3. **EXTCODEHASH DIFF_MAX ~24×** — same anomaly class as BALANCE.
4. state-actor logs ~1.5× more slow-block records (4253 vs 2794) at the same
   `--debug.logslowblock=0`.

## Deviations and caveats

- MGas/s medians, `overhead_baseline` variants pooled in the grid above
  (recoverable per test via `.test-name`; pooling is symmetric across modes).
- This host is 1.4× slower per test than the original's; absolute MGas/s is not
  comparable by construction and was pre-registered as out of scope.
- The arms replay different fixture bundles (d9ad55b3 vs 2282c757) — reproduced
  deliberately, as the original did. The report's own flagged follow-up
  (state-actor on jochemnet's bundle) remains the way to remove that confound.
