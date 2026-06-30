-- t3a_slot31_lateness.sql  ::  slot-31 parent block lateness for each orphaned slot-0
-- Cluster : DS_RAW
-- Run via : panda execute -> clickhouse.query_raw(DS_RAW, sql, {"start":..., "end":...})
-- Params  : start, end (DateTime); {slot31_targets} = host-injected VALUES of (slot,root)
--           built by extract.py from q1 output (validated ints/0x-hex, NOT user input):
--           values('slot UInt32, root String', (7400000,'0x..'), ...)
-- Output  : one row per slot-31 parent: api/p2p first-seen + median, observer counts.
--
-- CORRECTED: join on BLOCK ROOT (not slot alone) so a contested slot doesn't blend the late
-- losing block with the on-time winner. Dedup per (block, meta_client_name) via argMin over
-- updated_date_time to neutralize sentry restarts, then min/median across sentries.
-- UNIT: propagation_slot_start_diff = MILLISECONDS. PREFERRED ALT when CBT is up:
-- mainnet.fct_block_first_seen_by_node.seen_slot_start_diff (maintained dedup) -- see t3a_cbt note.
WITH targets AS (
  SELECT slot, root FROM {slot31_targets}
),
api AS (
  SELECT eb.slot,
         min(eb.first_diff)                AS api_first_seen_ms,
         quantileExact(0.5)(eb.first_diff) AS api_median_ms,
         uniqExact(eb.meta_client_name)    AS n_sentries
  FROM (
    SELECT slot, block, meta_client_name,
           argMin(propagation_slot_start_diff, updated_date_time) AS first_diff
    FROM beacon_api_eth_v1_events_block
    WHERE meta_network_name = 'mainnet'
      AND slot_start_date_time >= {start:DateTime} AND slot_start_date_time < {end:DateTime}
      AND slot_start_date_time IN ({sdt_set})
    GROUP BY slot, block, meta_client_name
  ) eb
  INNER JOIN targets t ON t.slot = eb.slot AND t.root = eb.block
  GROUP BY eb.slot
),
p2p AS (
  SELECT lg.slot,
         min(lg.first_diff)                AS p2p_first_seen_ms,
         quantileExact(0.5)(lg.first_diff) AS p2p_median_ms,
         uniqExact(lg.peer_id_unique_key)  AS n_peers
  FROM (
    SELECT slot, block, peer_id_unique_key,
           min(propagation_slot_start_diff) AS first_diff
    FROM libp2p_gossipsub_beacon_block
    WHERE meta_network_name = 'mainnet'
      AND slot_start_date_time >= {start:DateTime} AND slot_start_date_time < {end:DateTime}
      AND slot_start_date_time IN ({sdt_set})
    GROUP BY slot, block, peer_id_unique_key
  ) lg
  INNER JOIN targets t ON t.slot = lg.slot AND t.root = lg.block
  GROUP BY lg.slot
)
SELECT
  t.slot AS slot, t.root AS root,
  a.api_first_seen_ms, a.api_median_ms, a.n_sentries,
  l.p2p_first_seen_ms, l.p2p_median_ms, l.n_peers,
  least(coalesce(a.api_first_seen_ms, 4294967295),
        coalesce(l.p2p_first_seen_ms, 4294967295)) AS earliest_first_seen_ms
FROM targets t
LEFT JOIN api a ON a.slot = t.slot
LEFT JOIN p2p l ON l.slot = t.slot
ORDER BY t.slot;
