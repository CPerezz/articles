-- q_canon_slot0.sql  ::  CANONICAL slot-0 blocks (the comparison cohort), sampled
-- Cluster : DS_CBT (mainnet.fct_block FINAL)
-- Run via : panda execute -> clickhouse.query_raw(DS_CBT, sql, {start,end,min_slot,max_slot})
-- Output  : a ~3% deterministic sample of canonical slot-0 blocks (root + exec hash + sdt).
--
-- WHY: to compare the orphaned slot-0 cohort against slot-0 blocks that SURVIVED -- so we can
-- show that orphaning is explained by the block's own lateness / relay path, not by being slot-0
-- per se. Sampled via cityHash64(slot)%32==0 to keep the downstream sdt-IN target list bounded
-- (~3% -> hundreds at pilot scale, ~thousands at full scale).
SELECT
  slot,
  slot_start_date_time,
  toString(block_root)                  AS block_root,
  toString(execution_payload_block_hash) AS exec_hash,
  proposer_index,
  intDiv(coalesce(execution_payload_blob_gas_used, 0), 131072) AS blob_count,  -- 131072 = GAS_PER_BLOB
  block_total_bytes                     AS block_total_bytes,
  execution_payload_transactions_count  AS tx_count
FROM mainnet.fct_block FINAL
WHERE slot BETWEEN {min_slot:UInt32} AND {max_slot:UInt32}
  AND slot_start_date_time >= {start:DateTime} AND slot_start_date_time < {end:DateTime}
  AND modulo(slot, 32) = 0
  AND status = 'canonical'
  AND modulo(cityHash64(slot), 32) = 0      -- ~3% deterministic sample
ORDER BY slot;
