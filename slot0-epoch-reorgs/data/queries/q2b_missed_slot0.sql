-- q2b_missed_slot0.sql  ::  MISSED slot-0 (proposer-absent: no block at all), reported SEPARATELY
-- Cluster : DS_CBT (mainnet.fct_block FINAL)
-- Run via : panda execute -> clickhouse.query_raw(DS_CBT, sql, {start,end,min_slot,max_slot})
-- Output  : one row per slot-0 with NO fct_block row (neither canonical nor orphaned) = missed.
--
-- REWRITE: the old RAW anti-join (duty MINUS canonical_beacon_block) returned empty every run — a
-- LEFT JOIN miss fills with the column default, not NULL, and the duty/canonical slot domains
-- misaligned. Robust approach: generate the slot-0 CALENDAR (every epoch boundary in range) and
-- anti-join the CBT `fct_block` slot set (which has a row for every canonical AND orphaned block).
-- A slot-0 absent from fct_block produced no block at all = missed. (Orphaned slot-0s ARE in
-- fct_block with status='orphaned', so they are correctly NOT counted here.)
WITH
  toUInt32(intDiv({min_slot:UInt32} + 31, 32) * 32) AS first0,         -- first slot-0 >= min_slot
  present AS (
    SELECT DISTINCT slot FROM mainnet.fct_block FINAL
    WHERE slot BETWEEN {min_slot:UInt32} AND {max_slot:UInt32}
      AND slot_start_date_time >= {start:DateTime} AND slot_start_date_time < {end:DateTime}
      AND modulo(slot, 32) = 0
  )
SELECT (first0 + number * 32) AS slot
FROM numbers(intDiv({max_slot:UInt32} - first0, 32) + 1)
WHERE slot <= {max_slot:UInt32}
  AND slot NOT IN (SELECT slot FROM present)
ORDER BY slot;
