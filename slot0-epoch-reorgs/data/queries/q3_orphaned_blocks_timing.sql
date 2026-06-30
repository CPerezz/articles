-- q3_orphaned_blocks_timing.sql  ::  explicit orphaned-block list + first-seen timing (RAW)
-- Cluster : DS_RAW
-- Run via : panda execute -> clickhouse.query_raw(DS_RAW, sql, {"start":..., "end":...})
-- Params  : start, end (DateTime, UTC)
-- Output  : one row per (slot, orphaned_root) seen by >=1 observer but != canonical root.
--
-- Independent (raw) orphan list with earliest-seen timing + observer breadth. Cross-check the
-- slot set against the CBT orphan set host-side (Q6 reconciliation). UNIT: propagation_slot_
-- start_diff is MILLISECONDS here (events_block/libp2p). gossip root column = `block`.
WITH canon AS (
  SELECT slot, argMax(block_root, updated_date_time) AS canon_root
  FROM canonical_beacon_block
  WHERE meta_network_name = 'mainnet'
    AND slot_start_date_time >= {start:DateTime} AND slot_start_date_time < {end:DateTime}
  GROUP BY slot
),
seen AS (
  SELECT slot, block AS root,
         min(propagation_slot_start_diff) AS first_seen_ms_diff,
         uniqExact(meta_client_name)      AS observers
  FROM beacon_api_eth_v1_events_block
  WHERE meta_network_name = 'mainnet'
    AND slot_start_date_time >= {start:DateTime} AND slot_start_date_time < {end:DateTime}
  GROUP BY slot, block
  UNION ALL
  SELECT slot, block AS root,
         min(propagation_slot_start_diff) AS first_seen_ms_diff,
         uniqExact(peer_id_unique_key)    AS observers
  FROM libp2p_gossipsub_beacon_block
  WHERE meta_network_name = 'mainnet'
    AND slot_start_date_time >= {start:DateTime} AND slot_start_date_time < {end:DateTime}
  GROUP BY slot, block
),
seen_agg AS (
  SELECT slot, root,
         min(first_seen_ms_diff) AS first_seen_ms_diff,
         sum(observers)          AS observers
  FROM seen GROUP BY slot, root
)
SELECT
  sa.slot,
  modulo(sa.slot, 32)        AS position_in_epoch,
  toString(sa.root)          AS orphaned_root,
  toString(c.canon_root)     AS canonical_root,
  sa.first_seen_ms_diff,
  sa.observers
FROM seen_agg sa
LEFT JOIN canon c ON c.slot = sa.slot
WHERE sa.root != coalesce(c.canon_root, '') AND sa.root != ''
ORDER BY sa.slot;
