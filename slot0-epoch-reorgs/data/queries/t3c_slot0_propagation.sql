-- t3c_slot0_propagation.sql  ::  propagation shape of each orphaned slot-0 block
-- Cluster : DS_RAW
-- Run via : panda execute -> clickhouse.query_raw(DS_RAW, sql, {start,end} + {slot0_targets})
-- Params  : start, end (DateTime); {slot0_targets} = host-injected VALUES of (slot0, root) from q1.
-- Output  : one row per orphaned slot-0: api/p2p min + p25/p50/p75/p90, observer counts.
--
-- Join on the ORPHANED root (not slot) so the distribution is the LOSING block's -- the thing
-- that propagated too slowly to survive. UNIT: propagation_slot_start_diff = MILLISECONDS.
WITH targets AS (
  SELECT slot, root FROM {slot0_targets}
)
SELECT
  t.slot AS slot, t.root AS root,
  a.api_min, a.api_q[1] AS api_p25, a.api_q[2] AS api_p50, a.api_q[3] AS api_p75, a.api_q[4] AS api_p90, a.n_sentries,
  p.p2p_min, p.p2p_q[1] AS p2p_p25, p.p2p_q[2] AS p2p_p50, p.p2p_q[3] AS p2p_p75, p.p2p_q[4] AS p2p_p90, p.n_peers
FROM targets t
LEFT JOIN (
  SELECT slot, block,
         min(propagation_slot_start_diff)                              AS api_min,
         quantilesExact(0.25, 0.5, 0.75, 0.9)(propagation_slot_start_diff) AS api_q,
         uniqExact(meta_client_name)                                   AS n_sentries
  FROM beacon_api_eth_v1_events_block
  WHERE meta_network_name = 'mainnet'
    AND slot_start_date_time >= {start:DateTime} AND slot_start_date_time < {end:DateTime}
    AND slot_start_date_time IN ({sdt_set})
  GROUP BY slot, block
) a ON a.slot = t.slot AND a.block = t.root
LEFT JOIN (
  SELECT slot, block,
         min(propagation_slot_start_diff)                              AS p2p_min,
         quantilesExact(0.25, 0.5, 0.75, 0.9)(propagation_slot_start_diff) AS p2p_q,
         uniqExact(peer_id_unique_key)                                 AS n_peers
  FROM libp2p_gossipsub_beacon_block
  WHERE meta_network_name = 'mainnet'
    AND slot_start_date_time >= {start:DateTime} AND slot_start_date_time < {end:DateTime}
    AND slot_start_date_time IN ({sdt_set})
  GROUP BY slot, block
) p ON p.slot = t.slot AND p.block = t.root
ORDER BY t.slot;
