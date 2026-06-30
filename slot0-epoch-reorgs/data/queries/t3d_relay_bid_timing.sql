-- t3d_relay_bid_timing.sql  ::  relay involvement + bid timing, slot 31 AND slot 0
-- Cluster : DS_RAW (mev_relay_bid_trace + mev_relay_proposer_payload_delivered)
-- Run via : panda execute -> clickhouse.query_raw(DS_RAW, sql, {start,end} + {relay_targets})
-- Params  : start, end (DateTime); {relay_targets} = host-injected VALUES of
--           (slot UInt32, kind String, exec_hash String) for BOTH slot31 and slot0,
--           each carrying its OWN execution_payload_block_hash (do NOT share hashes).
-- Output  : one row per target slot: relays delivering/bidding, bid timing, value.
--
-- AVAILABILITY: mev_relay_* only from ~2024-09 -> H4 cannot extend to a full 24mo (window it).
-- SEMANTICS (verify on first run, U8/U9): proposer_payload_delivered has NO timing column AND
-- no event_date_time -> delivery timing UNAVAILABLE (do not proxy it). bid_trace
-- requested_at_slot_time/response_at_slot_time = Xatu COLLECTOR poll wallclock (partitioned by
-- wallclock_request_slot), NOT per-builder latency; timestamp_ms = relay-reported builder submit.
-- value is UInt256 -> arrives as STRING; cast to Decimal in Python (U10).
WITH targets AS (
  SELECT slot, kind, exec_hash FROM {relay_targets}
),
delivered AS (
  SELECT slot,
         groupUniqArray(relay_name) AS relays_delivered,
         any(block_hash)            AS delivered_block_hash,
         max(value)                 AS delivered_value
  FROM mev_relay_proposer_payload_delivered
  WHERE meta_network_name = 'mainnet'
    AND slot_start_date_time >= {start:DateTime} AND slot_start_date_time < {end:DateTime}
    AND slot_start_date_time IN ({sdt_set})
  GROUP BY slot
),
bids AS (
  SELECT slot,
         count()                              AS n_bids,
         uniqExact(relay_name)                AS n_relays_bidding,
         groupUniqArray(relay_name)           AS relays_bidding,
         min(response_at_slot_time)           AS earliest_bid_response_ms,  -- collector-observed
         quantileExact(0.5)(response_at_slot_time) AS median_bid_response_ms,
         max(value)                           AS max_bid_value,
         min(timestamp_ms)                    AS earliest_builder_submit_ms -- relay-reported
  FROM mev_relay_bid_trace
  WHERE meta_network_name = 'mainnet'
    AND slot_start_date_time >= {start:DateTime} AND slot_start_date_time < {end:DateTime}
    AND slot_start_date_time IN ({sdt_set})
  GROUP BY slot
)
SELECT
  t.slot AS slot, t.kind AS kind,
  (d.delivered_block_hash IS NOT NULL AND t.exec_hash != ''
   AND d.delivered_block_hash = t.exec_hash)              AS delivered_matches_target,
  d.relays_delivered,
  toString(d.delivered_value)                             AS delivered_value,
  b.n_bids, b.n_relays_bidding, b.relays_bidding,
  b.earliest_bid_response_ms, b.median_bid_response_ms,
  toString(b.max_bid_value)                               AS max_bid_value,
  b.earliest_builder_submit_ms,
  -- CORRECTED: a LEFT JOIN miss fills d.slot with the default 0 (not NULL) unless join_use_nulls=1,
  -- so `d.slot IS NULL` never fired. Use the delivered-relay array emptiness instead.
  empty(d.relays_delivered)                              AS no_relay_delivery
FROM targets t
LEFT JOIN delivered d ON d.slot = t.slot
LEFT JOIN bids b      ON b.slot = t.slot
ORDER BY t.kind, t.slot;
