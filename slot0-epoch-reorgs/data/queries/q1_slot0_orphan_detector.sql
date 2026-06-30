-- q1_slot0_orphan_detector.sql  ::  PRIMARY slot-0 detector + slot-31 parent context
-- Cluster : DS_CBT (mainnet.fct_block FINAL)
-- Run via : panda execute -> clickhouse.query_raw(DS_CBT, sql, {start,end,min_slot,max_slot})
-- Params  : start,end (DateTime); min_slot,max_slot (UInt32) -- BOTH required by force_primary_key
--           (CBT shards disagree on which of slot / slot_start_date_time is "the" key, so we
--           filter on both). The `blocks` CTE is widened by 1 slot / 12s on the low edge so the
--           slot-31 parent of a victim at min_slot is still in scope.
-- Output  : one row per ORPHANED slot-0, with its slot-31 parent carried alongside.
--
-- WHY: the slot-0 victim is the orphaned block (status='orphaned' AND slot%32==0) -- NOT
-- chain_reorg.slot. The slot-31 PARENT is the leading hypothesis (H2): carried on every row via
-- self-join (slot-1, slot_start_date_time-12), plus the ex-ante test (did slot-0 build on it?).
WITH blocks AS (
  SELECT slot, epoch, slot_start_date_time, proposer_index, block_root, parent_root, status,
         execution_payload_block_hash,
         execution_payload_blob_gas_used, block_total_bytes,
         execution_payload_transactions_count
  FROM mainnet.fct_block FINAL
  WHERE slot >= ({min_slot:UInt32} - 1) AND slot <= {max_slot:UInt32}
    AND slot_start_date_time >= ({start:DateTime} - INTERVAL 12 SECOND)
    AND slot_start_date_time < {end:DateTime}
)
SELECT
  s.slot,
  s.epoch,
  s.slot_start_date_time,
  s.proposer_index,
  toString(s.block_root)               AS block_root,
  toString(s.parent_root)              AS parent_root,
  toString(s.execution_payload_block_hash) AS exec_hash,         -- for relay hash-match (t3d)
  intDiv(coalesce(s.execution_payload_blob_gas_used, 0), 131072) AS blob_count,  -- 131072 = GAS_PER_BLOB (exact)
  s.block_total_bytes                  AS block_total_bytes,     -- beacon block payload bytes
  s.execution_payload_transactions_count AS tx_count,
  s.status                             AS slot0_status,          -- expect 'orphaned'
  p31.slot                             AS slot31,
  p31.par_status                       AS slot31_status,         -- canonical|orphaned (NULL => missed)
  toString(p31.par_block_root)         AS slot31_block_root,
  p31.par_proposer_index               AS slot31_proposer_index,
  (p31.par_block_root = s.parent_root) AS slot0_built_on_slot31  -- ex-ante test
FROM blocks s
LEFT JOIN (
  -- dedup contested slot-31 parents to ONE row per slot (prefer the canonical block) so a
  -- contested parent can't fan the victim out into duplicate rows. Aggregate aliases are
  -- NON-column names so the ClickHouse-26 analyzer doesn't read them as nested aggregates.
  SELECT slot, slot_start_date_time,
         argMax(block_root, status = 'canonical')     AS par_block_root,
         argMax(status, status = 'canonical')         AS par_status,
         argMax(proposer_index, status = 'canonical') AS par_proposer_index
  FROM blocks GROUP BY slot, slot_start_date_time
) p31
  ON p31.slot = s.slot - 1
 AND p31.slot_start_date_time = s.slot_start_date_time - 12
WHERE modulo(s.slot, 32) = 0
  AND s.status = 'orphaned'
  AND s.slot >= {min_slot:UInt32} AND s.slot <= {max_slot:UInt32}   -- victim strictly in window
ORDER BY s.slot;
