-- t3b_slot31_attestation_support.sql  ::  slot-31 parent attestation timing (self-contained)
-- Cluster : DS_RAW (beacon_api_eth_v1_events_attestation only -> single distributed table)
-- Run via : panda execute -> clickhouse.query_raw(DS_RAW, sql, {start,end})
-- Params  : start,end (DateTime); {parent_roots} = host values(slot,root) of slot-31 parents;
--           {sdt_set} = host IN-list of those parents' slot_start_date_times (seek bound).
-- Output  : one row per slot-31 parent: distinct attesters who voted FOR that parent's root,
--           cumulative by deadline (2/3/4s) and total.
--
-- REWRITE (was a distributed canon x attestation join -> denied by distributed_product_mode).
-- Now: we already KNOW each parent's canonical root (from q1), so no canonical join is needed.
-- Single distributed table INNER JOINed to a LOCAL values() list = allowed. uniqExactIf gives the
-- whole deadline sweep in ONE pass (no per-deadline loop). Interpretation: v3000/v_all = fraction
-- of the parent's eventual head-voters that had voted by 3s -> a low fraction means the parent was
-- attested slowly (H2's under-attestation aspect). attesting_validator_index is non-null only for
-- single (unaggregated) attestations -> this is a participation PROXY, not the full committee.
SELECT
  a.slot AS slot,
  uniqExactIf(a.attesting_validator_index, a.propagation_slot_start_diff < 2000) AS voters_2s,
  uniqExactIf(a.attesting_validator_index, a.propagation_slot_start_diff < 3000) AS voters_3s,
  uniqExactIf(a.attesting_validator_index, a.propagation_slot_start_diff < 4000) AS voters_4s,
  uniqExact(a.attesting_validator_index)                                          AS voters_all
FROM beacon_api_eth_v1_events_attestation a
INNER JOIN {parent_roots} t ON t.slot = a.slot AND t.root = a.beacon_block_root
WHERE a.meta_network_name = 'mainnet'
  AND a.attesting_validator_index IS NOT NULL
  AND a.slot_start_date_time >= {start:DateTime} AND a.slot_start_date_time < {end:DateTime}
  AND a.slot_start_date_time IN ({sdt_set})
GROUP BY a.slot
ORDER BY a.slot;
