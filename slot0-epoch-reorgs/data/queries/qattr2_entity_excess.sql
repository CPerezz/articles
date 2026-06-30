-- qattr2_entity_excess.sql  ::  per-entity slot-0 orphan EXCESS over own baseline
-- Cluster : DS_CBT (mainnet.fct_block FINAL + fct_block_proposer_entity FINAL)
-- Run via : panda execute -> clickhouse.query_raw(DS_CBT, sql, {start,end,min_slot,max_slot})
-- Params  : start,end (DateTime); min_slot,max_slot (UInt32) -- both required (force_primary_key).
-- Output  : one row per entity (operator/pool), 'unknown' FIRST.
--
-- THE DEFENSIBLE CLIENT/OPERATOR CLAIM. Proposer CL client is unattributable (blockprint frozen
-- pre-Electra), so entity is the workhorse. Each entity's slot-0 orphan rate as EXCESS over its
-- OWN all-slot baseline (controls for entities that orphan more everywhere). 'unknown' is a
-- first-class row. Wilson CIs computed in Python (analyze.py), not here. Both table reads are
-- bounded CTEs so the scans satisfy force_primary_key.
WITH blocks AS (
  SELECT slot, slot_start_date_time, status
  FROM mainnet.fct_block FINAL
  WHERE slot BETWEEN {min_slot:UInt32} AND {max_slot:UInt32}
    AND slot_start_date_time >= {start:DateTime} AND slot_start_date_time < {end:DateTime}
),
ent AS (
  SELECT slot, slot_start_date_time, entity
  FROM mainnet.fct_block_proposer_entity FINAL
  WHERE slot BETWEEN {min_slot:UInt32} AND {max_slot:UInt32}
    AND slot_start_date_time >= {start:DateTime} AND slot_start_date_time < {end:DateTime}
),
per_entity AS (
  SELECT
    coalesce(e.entity, 'unknown')                              AS entity,
    countIf(modulo(b.slot, 32) = 0)                            AS slot0_blocks,
    countIf(modulo(b.slot, 32) = 0 AND b.status = 'orphaned')  AS slot0_orphaned,
    count()                                                    AS all_blocks,
    countIf(b.status = 'orphaned')                             AS all_orphaned
  FROM blocks b
  LEFT JOIN ent e
    ON b.slot = e.slot AND b.slot_start_date_time = e.slot_start_date_time
  GROUP BY entity
)
SELECT
  entity, slot0_blocks, slot0_orphaned, all_blocks, all_orphaned,
  round(slot0_orphaned / nullIf(slot0_blocks, 0), 6)  AS slot0_orphan_rate,
  round(all_orphaned   / nullIf(all_blocks,  0), 6)   AS baseline_orphan_rate,
  round(slot0_orphaned / nullIf(slot0_blocks, 0)
        - all_orphaned / nullIf(all_blocks, 0), 6)    AS slot0_excess
FROM per_entity
ORDER BY (entity = 'unknown') DESC, slot0_excess DESC;
