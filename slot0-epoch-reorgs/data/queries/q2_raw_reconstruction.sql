-- q2_raw_reconstruction.sql  ::  RAW re-derivation of proposed/missed/orphaned (coverage check)
-- Cluster : DS_RAW (default.* with WHERE meta_network_name='mainnet')
-- Run via : panda execute -> clickhouse.query_raw(DS_RAW, sql, {"start":..., "end":...})
-- Params  : start, end (DateTime, UTC)
-- Output  : one row per duty slot, with raw status + any orphaned roots seen.
--
-- ROLE: NOT independent ground truth -- a CBT timing-and-coverage completeness check (the CBT
-- 'orphaned' status derives from the same canonical+seen inputs). Disagreement => ingestion/
-- coverage skew, not orphan-logic error. Shared blind spot: an orphan dropped before any sentry
-- gossiped it is invisible to both tracks.
--
-- DEDUP: canonical via argMax(updated_date_time); duty from the CANONICAL duty table
-- (full history, no 2024-04-03 floor); seen = events_block UNION libp2p gossip. meta_client_*
-- is the SENTRY -> never grouped on. block root column is `block` in both events tables.
WITH canon AS (
  SELECT slot, argMax(block_root, updated_date_time) AS canon_root,
         any(epoch) AS epoch
  FROM canonical_beacon_block
  WHERE meta_network_name = 'mainnet'
    AND slot_start_date_time >= {start:DateTime} AND slot_start_date_time < {end:DateTime}
  GROUP BY slot
),
duty AS (
  SELECT slot, any(proposer_validator_index) AS pidx, any(proposer_pubkey) AS ppk
  FROM canonical_beacon_proposer_duty
  WHERE meta_network_name = 'mainnet'
    AND slot_start_date_time >= {start:DateTime} AND slot_start_date_time < {end:DateTime}
  GROUP BY slot
),
seen AS (
  SELECT DISTINCT slot, block AS root FROM beacon_api_eth_v1_events_block
    WHERE meta_network_name = 'mainnet'
      AND slot_start_date_time >= {start:DateTime} AND slot_start_date_time < {end:DateTime}
  UNION DISTINCT
  SELECT DISTINCT slot, block AS root FROM libp2p_gossipsub_beacon_block
    WHERE meta_network_name = 'mainnet'
      AND slot_start_date_time >= {start:DateTime} AND slot_start_date_time < {end:DateTime}
)
SELECT
  d.slot,
  modulo(d.slot, 32)                              AS position_in_epoch,
  d.pidx                                          AS proposer_validator_index,
  toString(c.canon_root)                          AS canonical_root,
  if(c.canon_root != '' AND c.canon_root IS NOT NULL, 'proposed', 'missed') AS slot_status_raw,
  arrayFilter(x -> x != coalesce(c.canon_root, '') AND x != '',
              groupArray(DISTINCT s.root))        AS orphaned_roots
FROM duty d
LEFT JOIN canon c ON c.slot = d.slot
LEFT JOIN seen   s ON s.slot = d.slot
GROUP BY d.slot, d.pidx, c.canon_root
ORDER BY d.slot;
