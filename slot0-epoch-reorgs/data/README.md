# slot-0 epoch-boundary reorg study — data pipeline

Reproducible extraction of ethPandaOps Xatu data (via the `panda` hosted proxy) for the slot-0
reorg study. See `../../../slot0-reorg-methodology.md` for the full method and the first-run gate.

## Files

| File | Purpose |
|------|---------|
| `runner.py` | transport: `panda execute` + native binding + sentinel stdout + datasource resolution + host-side windowing |
| `extract.py` | orchestrator: runs `queries/*.sql`, builds target lists from the orphan set, writes `*.json` |
| `analyze.py` | stats (Wilson CIs, Fisher/chi2 + RR, entity excess, daily MAD) → `summary_<label>.json` |
| `plot.py` | 4 figures → `../../slot0/fig_*.{png,svg}` |
| `queries/*.sql` | the verified ClickHouse queries (source of truth; native `{name:Type}` binding) |
| `datasources.json` | written by the probe: resolved `DS_RAW`/`DS_CBT` + capability report |

## Run order

```bash
# 0. host shell, once (needs Docker running):
panda upgrade && panda init && panda auth login

# 1. capability gate — resolves datasource names, checks param binding + CBT exposure + sandbox libs
python3 extract.py --probe

# 2. a window (Pilot B example):
python3 extract.py --window 2026-01-01 2026-02-01 --label janspike
python3 analyze.py --label janspike
python3 plot.py    --label janspike

# 3. scale-out (monthly host-side windows):
python3 extract.py --scale 2024-09-01 2026-06-01
```

## Dataset naming

`<query>_<label>.json` — e.g. `orphan_by_position_janspike.json` (q4), `slot0_orphans_janspike.json`
(q1), `entity_excess_janspike.json` (qattr2), `daily_orphan_series_janspike.json`,
`slot31_attest_support_janspike_dl{2000,3000,4000,12000}.json` (deadline sweep). `summary_<label>.json`
holds the computed statistics.

## Provenance discipline (per repo convention)

Each published number must trace to: the source query file, the window `[start, end)`, the dedup rule, the
dataset's **actual covered range** (per-table history floors differ — relay only from ~2024-09), and the
`panda`/Xatu snapshot date. Pilots are **v0/PROVISIONAL** until the scale run supersedes them.

## Known to confirm on first live run

Datasource names (U1), param binding (U2), CBT `mainnet.*` exposure (U3), `propagation_slot_start_diff`
units (U4: ms vs slots), `chain_reorg.depth` (U5), `FINAL` acceptance (U7), relay timing columns (U8/U9),
UInt256 `value` as string (U10), sandbox stats libs (U14). The probe checks U1–U3 + U14 automatically.
