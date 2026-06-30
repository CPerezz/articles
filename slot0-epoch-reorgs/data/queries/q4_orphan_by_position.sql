-- q4_orphan_by_position.sql  ::  HEADLINE chart (the "Toni chart")
-- Cluster : DS_CBT (mainnet.fct_block FINAL)
-- Run via : panda execute -> clickhouse.query_raw(DS_CBT, sql, {"start":..., "end":...})
-- Params  : start, end  (DateTime, UTC, [start, end))
-- Output  : 32 rows, one per position_in_epoch.
--
-- WHAT IT MEASURES: orphan rate by VICTIM slot%32, denominator-normalized so slot 0's rate
-- is comparable across positions. Emits BOTH this study's normalized orphan_rate AND the
-- Jan-2026 gist's count_vs_avg metric (count at pos / mean count over all 32 positions),
-- so the "~1.7x" anchor is reproduced on its own terms. The pooled-rest risk ratio is a
-- THIRD number computed in Python (§5a) — report all three; they are not equal.
--
-- VERIFY ON FIRST RUN: U3 fct_block exposed in mainnet.*; status domain == {canonical,orphaned}
-- (NO 'missed' here — missed lives in fct_block_proposal_status_daily, see q2b). CBT ORDER BY
-- is slot_start_date_time, so we filter on it (not a slot range); modulo() only for bucketing.
WITH per_pos AS (
  SELECT modulo(slot, 32)              AS pos,
         count()                        AS total_slots,
         countIf(status = 'orphaned')   AS orphaned
  FROM mainnet.fct_block FINAL
  WHERE slot BETWEEN {min_slot:UInt32} AND {max_slot:UInt32}        -- force_primary_key: need slot
    AND slot_start_date_time >= {start:DateTime} AND slot_start_date_time < {end:DateTime}  -- ...and sdt
  GROUP BY pos
),
g AS (SELECT avg(orphaned) AS mean_orphaned_per_pos FROM per_pos)
SELECT
  p.pos                                            AS position_in_epoch,
  p.total_slots,
  p.orphaned,
  round(p.orphaned / p.total_slots, 6)             AS orphan_rate,    -- normalized (this study)
  round(p.orphaned / g.mean_orphaned_per_pos, 4)   AS count_vs_avg    -- gist 1.7x anchor metric
FROM per_pos p CROSS JOIN g
ORDER BY p.pos;
