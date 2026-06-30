-- q_blob_by_position.sql  ::  avg blob load by position-in-epoch (tests the rollup/Arbitrum clustering claim)
-- Cluster : DS_CBT (mainnet.fct_block FINAL)
-- Run via : panda execute -> clickhouse.query_raw(DS_CBT, sql, {start,end,min_slot,max_slot})
-- Output  : 32 rows, one per slot%32.
--
-- WHY: a reviewer asked whether rollups cluster blobs by epoch position (e.g. Arbitrum allegedly
-- sending blobs away from slot 0, ~slot 20-22). This measures avg blob count by position for
-- CANONICAL blocks (the realized chain) and, separately, for ORPHANED blocks, so we can test the
-- "slot 0 carries more/fewer blobs" hypothesis directly instead of relying on folklore.
-- 131072 = GAS_PER_BLOB, so blob_gas_used/131072 is the exact integer blob count.
-- Emits raw counts + SUMS (not averages) so per-month results combine by summation across the
-- host-side monthly windowing the scale run uses; averages are computed downstream.
SELECT
  modulo(slot, 32)                AS position_in_epoch,
  count()                          AS total_slots,
  countIf(status = 'canonical')    AS n_canonical,
  countIf(status = 'orphaned')     AS n_orphaned,
  sumIf(intDiv(coalesce(execution_payload_blob_gas_used, 0), 131072), status = 'canonical') AS sum_blobs_canonical,
  sumIf(intDiv(coalesce(execution_payload_blob_gas_used, 0), 131072), status = 'orphaned')  AS sum_blobs_orphaned,
  sumIf(toUInt64(coalesce(block_total_bytes, 0)), status = 'canonical')                     AS sum_bytes_canonical
FROM mainnet.fct_block FINAL
WHERE slot BETWEEN {min_slot:UInt32} AND {max_slot:UInt32}        -- force_primary_key: need slot
  AND slot_start_date_time >= {start:DateTime} AND slot_start_date_time < {end:DateTime}  -- ...and sdt
GROUP BY position_in_epoch
ORDER BY position_in_epoch;
