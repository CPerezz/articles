-- qattr1_entity_victim_parent.sql  ::  orphaned slot-0 set with entity for victim AND parent
-- Cluster : DS_CBT (mainnet.fct_block FINAL + fct_block_proposer_entity FINAL)
-- Run via : panda execute -> clickhouse.query_raw(DS_CBT, sql, {start,end,min_slot,max_slot})
-- Params  : start,end (DateTime); min_slot,max_slot (UInt32) -- both required (force_primary_key).
-- Output  : one row per orphaned slot-0, with slot-0 entity AND slot-31 parent entity.
--
-- WHY BOTH: H2 is about the PARENT, so we attribute the slot-31 entity too. entity = staking
-- pool/operator, NOT CL client. Each table read is a bounded CTE (widened by 1 slot / 12s) so
-- every scan satisfies force_primary_key on both clusters' shard keys.
WITH blocks AS (
  SELECT slot, epoch, slot_start_date_time, proposer_index, block_root, parent_root, status
  FROM mainnet.fct_block FINAL
  WHERE slot >= ({min_slot:UInt32} - 1) AND slot <= {max_slot:UInt32}
    AND slot_start_date_time >= ({start:DateTime} - INTERVAL 12 SECOND)
    AND slot_start_date_time < {end:DateTime}
),
ent AS (
  SELECT slot, slot_start_date_time, entity
  FROM mainnet.fct_block_proposer_entity FINAL
  WHERE slot >= ({min_slot:UInt32} - 1) AND slot <= {max_slot:UInt32}
    AND slot_start_date_time >= ({start:DateTime} - INTERVAL 12 SECOND)
    AND slot_start_date_time < {end:DateTime}
)
SELECT
  o.slot AS slot, o.epoch AS epoch, o.slot_start_date_time AS slot_start_date_time,
  o.proposer_index AS proposer_index,
  toString(o.block_root)            AS block_root,
  toString(o.parent_root)           AS parent_root,
  coalesce(e.entity, 'unknown')     AS slot0_entity,
  p31.proposer_index                AS slot31_proposer_index,
  p31.status                        AS slot31_status,
  coalesce(e31.entity, 'unknown')   AS slot31_entity
FROM blocks o
LEFT JOIN ent e
  ON o.slot = e.slot AND o.slot_start_date_time = e.slot_start_date_time
LEFT JOIN (
  -- dedup contested slot-31 parents to one row per slot (prefer canonical)
  SELECT slot, slot_start_date_time,
         argMax(status, status = 'canonical')         AS status,
         argMax(proposer_index, status = 'canonical') AS proposer_index
  FROM blocks GROUP BY slot, slot_start_date_time
) p31
  ON p31.slot = o.slot - 1 AND p31.slot_start_date_time = o.slot_start_date_time - 12
LEFT JOIN ent e31
  ON e31.slot = o.slot - 1 AND e31.slot_start_date_time = o.slot_start_date_time - 12
WHERE o.status = 'orphaned' AND modulo(o.slot, 32) = 0
  AND o.slot >= {min_slot:UInt32} AND o.slot <= {max_slot:UInt32}
ORDER BY o.slot;
