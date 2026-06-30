-- q5_chain_reorg_corroboration.sql  ::  chain_reorg event corroboration (SECONDARY)
-- Cluster : DS_RAW (beacon_api_eth_v1_events_chain_reorg)
-- Run via : panda execute -> clickhouse.query_raw(DS_RAW, sql, {"start":..., "end":...})
-- Params  : start, end (DateTime, UTC)
-- Output  : one row per logical reorg (deduped by old/new head), victim slot recovered.
--
-- CORROBORATION ONLY. Recover the orphaned (victim) slot from old_head_block, NOT from
-- chain_reorg.slot (which is the slot the node switched TO -- typically slot%32==1 for a
-- slot-0 orphaning; binning chain_reorg.slot%32 mislocates the phenomenon).
--
-- UNIT WARNING (U4): propagation_slot_start_diff is in SLOTS for chain_reorg (NOT ms). Do not
-- apply the ms deadline filter here. depth UNITS UNVERIFIED (U5) -> recover victim via
-- old_head_block, never via slot-depth arithmetic, until depth is validated on known boundaries.
-- NB: an orphaned old_head is not canonical, so it may be absent from canonical_beacon_block;
-- resolve old_head_block -> slot via mainnet.fct_block (retains orphans) host-side too.
WITH reorg_dedup AS (
  SELECT old_head_block, new_head_block,
         any(slot)                        AS event_slot,
         max(depth)                       AS depth,
         min(propagation_slot_start_diff) AS first_obs_slot_diff,  -- SLOTS, not ms
         uniqExact(meta_client_name)      AS sentry_count
  FROM beacon_api_eth_v1_events_chain_reorg
  WHERE meta_network_name = 'mainnet'
    AND slot_start_date_time >= {start:DateTime} AND slot_start_date_time < {end:DateTime}
  GROUP BY old_head_block, new_head_block
),
canon AS (
  SELECT slot, argMax(block_root, updated_date_time) AS block_root
  FROM canonical_beacon_block
  WHERE meta_network_name = 'mainnet'
    AND slot_start_date_time >= {start:DateTime} AND slot_start_date_time < {end:DateTime}
  GROUP BY slot
)
SELECT
  r.event_slot,
  r.depth,
  toString(r.old_head_block)  AS old_head_block,
  toString(r.new_head_block)  AS new_head_block,
  r.sentry_count,
  r.first_obs_slot_diff,
  cb.slot                     AS orphaned_slot,                 -- victim (canonical recovery only)
  modulo(cb.slot, 32)         AS orphaned_pos_in_epoch
FROM reorg_dedup r
LEFT JOIN canon cb ON cb.block_root = r.old_head_block
ORDER BY r.event_slot;
