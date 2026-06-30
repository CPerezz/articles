-- q_daily_orphan_series.sql  ::  daily orphan series (slot-0 vs all), for the time-series figure
-- Cluster : DS_CBT (mainnet.fct_block FINAL)
-- Run via : panda execute -> clickhouse.query_raw(DS_CBT, sql, {"start":..., "end":...})
-- Params  : start, end (DateTime, UTC)
-- Output  : one row per UTC day: slot-0 orphan counts/totals + overall counts/totals.
--
-- Feeds fig_jan2026_orphan_timeseries + the natural-experiment analysis (§5d). Per-day Wilson
-- bands + MAD anomaly detection are computed in Python. NOTE the spikes behave as ~2 mega-events;
-- power the steady-state elevation, narrate the spikes (R-stat-2).
SELECT
  toDate(slot_start_date_time)                                AS day,
  countIf(modulo(slot, 32) = 0)                               AS slot0_total,
  countIf(modulo(slot, 32) = 0 AND status = 'orphaned')       AS slot0_orphaned,
  count()                                                      AS all_total,
  countIf(status = 'orphaned')                                AS all_orphaned
FROM mainnet.fct_block FINAL
WHERE slot BETWEEN {min_slot:UInt32} AND {max_slot:UInt32}          -- force_primary_key: need slot
  AND slot_start_date_time >= {start:DateTime} AND slot_start_date_time < {end:DateTime}  -- ...and sdt
GROUP BY day
ORDER BY day;
