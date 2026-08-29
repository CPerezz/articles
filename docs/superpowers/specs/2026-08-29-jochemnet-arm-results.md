# jochemnet arm — completed run, within-arm results

Run finished 2026-08-29T15:48:57+02:00. **1463/1463 tests, 1465 result files, zero
failures.** 16.3 h at 40.1 s/test.

Methodology as ruled by the original operator: the baseline was compacted **once
after the pre-runs** (`geth db compact`, 9,346 -> 8,438 SSTs) and promoted; there
was **no per-test compaction** (verified: occurrences of "Compacted chain
database" in the run log = 0).

## Run integrity (Tier B)

| check | result |
| --- | --- |
| B1 sentinels after the run | **20/20 OK, 0 FAILED** |
| SST count vs baseline | 8,438 vs 8,438 — datadir returned exactly to H |
| B3 restore drift | median 17.7 s, first decile 17.7 s -> last decile 17.8 s, **ratio 1.01** (needs <= 2.0) |
| failures | 0 |

`recover` never leaked, so the dataset is trustworthy by the pre-registered
criteria.

## Within-arm results (C1, C2)

MGas/s medians, `value_sent=0`, `overhead_baseline` variants pooled (benchmarkoor
truncates the result directory name, so that flag is unrecoverable from it; the
pooling is applied identically to every mode, so comparisons stay like-for-like).

### BALANCE

| gas | NON_EXISTING | EOA | MINIMAL | SAME_MAX | JUMPDEST | DIFF_MAX |
| --- | --- | --- | --- | --- | --- | --- |
| 100 | 17.0 | 17.2 | 101.2 | 105.9 | 106.1 | 101.7 |
| 160 | 18.5 | 18.3 | 18.6 | 18.4 | 18.7 | **395.1** |
| 200 | 19.0 | 19.0 | 19.2 | 18.9 | 19.0 | **430.9** |
| 300 | 19.9 | 19.9 | 19.7 | 21.0 | 19.8 | **405.2** |

- DIFF_MAX / median(other five), median across gas: **20.5x**
- within-arm spread: **11.7x**

### CALL and CALLCODE, against the report's published figures

| | ours | report |
| --- | --- | --- |
| CALL / DIFF_MAX | **1.45x** | 1.55x |
| CALLCODE / DIFF_MAX | **1.45x** | 1.49x |
| CALL within-arm spread | 2.72x | — |
| CALLCODE within-arm spread | 2.56x | — |

## Verdict on C1 and C2

Both **reproduce**. These are the two predictions immune to the bundle and host
confounds because they are within-arm, which is why the pre-registration hung the
verdict on them.

The material finding: the DIFF_MAX anomaly **survives compaction**. The baseline
was compacted once after the pre-runs, so the anomaly cannot be explained by
setup-payload writes leaving those accounts in shallow LSM levels. That
hypothesis is largely excluded.

## New observations not in the report

1. **The 100 Mgas row is discontinuous.** At 100 M, MINIMAL/SAME_MAX/JUMPDEST run
   85-110 MGas/s and DIFF_MAX only 101.7; from 120 M upward the other modes
   collapse to ~18 and DIFF_MAX jumps to 325-431. Something about the smallest gas
   budget changes the regime.
2. **CALL/CALLCODE JUMPDEST is anomalously slow** — 11-12 MGas/s against ~19 for
   its peers, consistently at every gas value above 100 M. The report did not
   flag this.

## Caveats held

- MGas/s, not the report's µs-per-lookup: the 20.5x is not directly comparable to
  its 6.7x within-arm figure.
- The headline 7.71x is **cross-arm** and needs the state-actor arm.
- 1,102 of 1,463 results carry an `account_mode`; the remainder are tests without
  one (ether_transfers, sstore, and similar).
