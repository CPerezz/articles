# State-DB performance divergence — benchmarkoor bloatnet runs

Why identical EEST bloatnet benchmarks report different MGas/s on three geth databases:
`compacted` and `uncompacted` (the same jochemnet mainnet shadowfork snapshot, with and
without manual pebble compaction) and `state-actor` (synthetically generated state).

Everything needed to reproduce or re-cut the analysis lives in this folder.

## Layout

| Path | What |
|---|---|
| `state-db-perf-report.html` | The deliverable. Self-contained, zero JS, opens offline. |
| `gen_state_db_report.py` | Parser, computations, and HTML/SVG/JSON emission. Python 3 stdlib only. |
| `report_svg.py` | Inline-SVG primitives (scales, axes, dots, lines, bands). Has its own self-check. |
| `data/benchmarkoor_*.log` | The three raw benchmarkoor run logs — the only inputs. |
| `data/report_data.json` | Every computed value the report renders, for reuse in prose. |
| `figures/fig_*.svg` | The four charts as standalone files, palette and dark-mode inlined. |
| `decision-log.md` | Ledger of the review passes: findings, rulings, and what each one cost. |

## Regenerate

```
python3 gen_state_db_report.py      # writes the html, the four svgs, and report_data.json
python3 report_svg.py               # primitive self-check, prints "report_svg selfcheck ok"
```

Paths resolve relative to the script, so the cwd does not matter.

## Reading the output

Expected stdout, all asserted: `common tests: 406`, `gas mismatches: 0`,
`baseline/clean/vs1: 165/175/66`, `buckets diffmax/flat/other: 33/92/50 of 175`,
`agreement: 13 categories 1.031-1.117x (median 1.091)`.

**The 12 `WARN oracle mismatch vs1_call_slope` lines are expected and correct.** They record
that the original investigation's oracle for four value_sent=1 rows was ~2x off; the logs are
unambiguous, so the report renders the computed value and the WARN preserves the discrepancy
instead of hiding it. A 13th WARN means something actually regressed.

## Findings

- No missing state in `state-actor`: value_sent=1 gas pricing separates existing from
  non-existing accounts by 8.1–10.6x inside that database itself.
- Outside the DIFF_MAX account class, `compacted` and `state-actor` agree to within
  1.03–1.12x across all 13 remaining categories.
- The one real divergence is DIFF_MAX account-leaf reads, which jochemnet serves at ~2 µs
  against ~14 µs for its own other classes. It survives compaction, which cannot touch RAM —
  a memory-residency signature, inferred rather than measured.
- Consequence: the benchmark currently measures how recently state was written about as much
  as it measures intrinsic access cost.
