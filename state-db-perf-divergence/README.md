# State-DB performance divergence — benchmarkoor bloatnet runs

Why identical EEST bloatnet benchmarks report different MGas/s on three geth databases:
`compacted` and `uncompacted` (the same jochemnet mainnet shadowfork snapshot, with and
without manual pebble compaction) and `state-actor` (synthetically generated state).

Everything needed to reproduce or re-cut the analysis lives in this folder.

## Layout

| Path | What |
|---|---|
| `state-db-perf-report.html` | The deliverable. Zero JS, single file. Only external fetches are the site's Google-Font stylesheets (degrades to system monospace offline). |
| `gen_state_db_report.py` | Parser, computations, and HTML/SVG/JSON emission. Python 3 stdlib only. |
| `report_svg.py` | Inline-SVG primitives (scales, axes, dots, lines, bands). Has its own self-check. |
| `data/benchmarkoor_*.log` | The three raw benchmarkoor run logs — the original inputs. |
| `data/db_inspect_*.txt` | Raw `geth db inspect` of both stores. The state-actor store is byte-identical to the one its benchmark ran on; the jochemnet store was inspected after the fix, so ~380 MiB of trie state sits in the key-value store rather than the journal file. |
| `data/drained_verdict.json` | The verdict run: the same 32 cells on the original jochemnet baseline, on the drained + compacted one, and on state-actor. Provenance embedded. |
| `collect_verdict.py` | Collector that produced `drained_verdict.json` on the bench host. |
| `data/report_data.json` | Every computed value the report renders, for reuse in prose. |
| `figures/fig_*.svg` | The five charts as standalone files, site palette inlined (dark-only, no external fetches). |
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

The investigation is closed. Root cause: **journal residency**, not a property of either
database.

- Geth keeps its most recent trie writes in memory and saves them to
  `triedb/merkle.journal` at shutdown. The pre-run's last 4,248 blocks never reached disk,
  and the pipeline handed that journal back to every test.
- EEST deploys receiver classes in order, and DIFF_MAX goes last — entirely inside that
  window. So DIFF_MAX account reads were served from RAM (0.0 MB of disk per 150 cold
  reads) while every sibling class paid megabytes. Delete the journal and those accounts
  stop existing.
- Draining the journal into the disk layer and compacting the store collapses the anomaly:
  BALANCE/DIFF_MAX at 160M gas goes 380 → 272 (drain) → 18.5 MGas/s (compact), against
  state-actor's 16.5. The MINIMAL control does not move.
- No missing state in `state-actor`: value_sent=1 gas pricing separates existing from
  non-existing accounts by 8.1–10.6x inside that database itself.
- Consequence: a replayed-snapshot baseline measures how recently state was written about
  as much as it measures intrinsic access cost. Generated state (state-actor) has no such
  recency gradient, which is why it is the sound basis for worst-case benchmarks.
