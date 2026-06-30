# Methodology — Slot-0 Epoch-Boundary Reorg Study

*The reproducible **how**. Question: are Ethereum reorgs at the first slot of an epoch (slot 0,
`slot % 32 == 0`) caused by **fixable client engineering** at the epoch transition — which would let
the EPBS/Gloas attestation deadline drop **3s → 2s**, reclaiming ~1s of execution every slot — or by
**structural** factors (a late/under-attested slot-31 parent, relay timing games, slow attesters)?*

> **Status: pipeline built, data pending live run.** Every datasource name, parameter-binding form,
> CBT `mainnet.*` exposure, `propagation_slot_start_diff` unit, and `chain_reorg.depth` semantic is
> **confirmed on the first live run** (§7). Names here are *defaults-from-discovery*, never hardcoded.

## 0. Four correctness facts (read before any SQL)

1. **`meta_client_*` is the observing Xatu *sentry*, never the proposer's client.** Every `default.*`
   events row is one sentry (gossip: one per peer per sentry). Dedup (`GROUP BY`/`argMax`/`uniqExact`)
   or counts inflate by fleet size. **Proposer CL/EL client is not in Xatu.**
2. **The slot-0 victim is the orphaned block** (`fct_block.status='orphaned' AND slot%32==0`), recovered
   from `old_head_block` for the `chain_reorg` cross-check — **not** `chain_reorg.slot` (the slot the node
   switched *to*, typically `slot%32==1`). Binning `chain_reorg.slot%32` mislocates the whole phenomenon.
3. **MISSED ≠ ORPHANED.** Orphaned = block built then dropped (the hypothesis). Missed = proposer absent
   (no block). Reported separately; missed is **not** cross-validated against `chain_reorg`.
4. **The leading hypothesis (H2) is about the slot-31 *parent*.** Every timing/attribution query carries
   slot-31 context (`slot - 1`, joined on `slot_start_date_time - 12`), or H2 is untestable.

Two cluster facts that gate syntax:
- **DS_RAW** (raw Xatu, `default.*`): single DB, `WHERE meta_network_name='mainnet'`, dedup via aggregation.
- **DS_CBT** (refined CBT): `FROM mainnet.<table> FINAL`, no network column. **No cross-cluster joins** —
  run two `panda execute` calls, reconcile host-side on `(slot, block_root)`.

Hard-won live corrections (see decision-log §3–§8):
- **CBT `force_primary_key`**: every CBT query must filter on **both** `slot` (a `BETWEEN` range) **and**
  `slot_start_date_time` — the cluster's shards disagree on which is the key, so both are required. Self-joins
  (slot-31 parent) read from a widened bounded CTE so each scan is independently key-satisfied.
- **Int params**: stringify before binding (the client `%g`-formats ints and corrupts large values).
- **CH-26 analyzer**: never alias an aggregate to a column name used in the same `WHERE` (`AS sdt`, not
  `AS slot_start_date_time`). Alias every projected `alias.col` (`o.slot AS slot`).
- **No distributed×distributed joins** (`distributed_product_mode='deny'`): resolve the small side first and
  pass it as a local `values()` list (this is why `t3b` takes pre-resolved parent roots).
- **One session per run** (the proxy caps at 50 sandbox sessions); **chunk target lists** to ~250 (a huge
  `sdt IN (...)` list overflows the sandbox script-staging arg limit at scale).

## 1. Access & runner

`panda` hosted proxy only (`panda-proxy.ethpandaops.io`). One-time host setup (Docker must be running):

```bash
panda upgrade && panda init && panda auth login && panda auth status
panda datasources --type clickhouse --json     # sanity check the names exist
```

The pipeline lives in this folder's `data/`:
- **`runner.py`** — transport. `panda execute --file <body>` runs in-sandbox Python calling
  `clickhouse.query_raw(ds, sql, params)` (native `{name:Type}` binding; `query_raw` preserves
  hash/UInt256 precision). Results return via a stdout **sentinel envelope**. `probe()` resolves
  `DS_RAW`/`DS_CBT` at runtime and writes `datasources.json`; `run_windows()` does host-side monthly
  windowing for the scale-out.
- **`extract.py`** — reads `queries/*.sql`, runs window-parametrized queries with native binding, and for
  the RAW timing layer builds a validated ClickHouse `values(...)` target list from the CBT-derived
  orphaned slot-0 set (`str.replace` on `{…_targets}`, leaving native `{start:DateTime}` intact). Writes
  one JSON per query.
- **`plot.py` / `analyze.py`** — figures and statistics from the JSON.

Run order: `python3 extract.py --probe` (the gate) → `--window START END --label <name>`.

## 2. The query set (source of truth: `data/queries/*.sql`)

| File | Cluster | Role |
|------|---------|------|
| `q4_orphan_by_position.sql` | CBT | **Headline**: orphan rate by `slot%32`, normalized + gist `count_vs_avg` |
| `q1_slot0_orphan_detector.sql` | CBT | **Primary** slot-0 orphan set + slot-31 parent context (feeds timing/relay) |
| `qattr1_entity_victim_parent.sql` | CBT | entity for victim **and** parent |
| `qattr2_entity_excess.sql` | CBT | **Defensible claim**: per-entity slot-0 orphan excess over own baseline |
| `q2_raw_reconstruction.sql` | RAW | raw proposed/missed/orphaned re-derivation (coverage check) |
| `q2b_missed_slot0.sql` | RAW | missed slot-0 (proposer-absent), reported separately |
| `q3_orphaned_blocks_timing.sql` | RAW | explicit orphaned-block list + first-seen timing |
| `q5_chain_reorg_corroboration.sql` | RAW | `chain_reorg` corroboration; victim via `old_head_block` |
| `t3a_slot31_lateness.sql` | RAW | slot-31 block lateness (join on **root**, ms units) |
| `t3b_slot31_attestation_support.sql` | RAW | slot-31 attestation support vs baseline (deadline sweep 2/3/4/12s) |
| `t3c_slot0_propagation.sql` | RAW | slot-0 (losing block) propagation distribution |
| `t3d_relay_bid_timing.sql` | RAW | relay delivery + bid timing, slot 31 **and** slot 0 |

**Reconciliation (Q6, host-side):** join the CBT orphan set, the raw orphan set (q3), and the reorg-victim
set (q5) on `slot`; report agreement as **coverage**, not independent confirmation (they share inputs).

## 3. Attribution — the layered model

- **Primary = clean Xatu timing/relay** (the 3s→2s verdict rests here).
- **Secondary = blockprint** proposer CL client — available **pre-Electra only**. The *public* API
  (`api.blockprint.sigp.io`) is frozen, but Xatu ingests blockprint into RAW `beacon_block_classification`
  (`best_guess_single` + `client_probability_*`), which covers mainnet through **~2025-05-07** (Electra
  floor). `client_attribution.py` joins orphaned slot-0s to their proposer's modal client over that slice
  (n=371) and disentangles client from operator (entity labels are post-Electra only; the client signal is
  spread across 371 distinct validators / many deposit cohorts → not an operator artifact). The post-Electra
  gap is **structural, not tooling**: EIP-7549 (in the Electra fork) collapsed blockprint's attestation
  fingerprint (~1,366 → ~22), the tool was abandoned, and Rated/beaconcha.in/ethseer-MigaLabs/etherscan/
  clientdiversity.org are all frozen-blockprint / network-aggregate / graffiti-only. **Graffiti was checked
  too and closed**: not in Xatu at all (`system.columns` has zero graffiti columns); the explorer retaining
  orphaned blocks (Dora) is auth-gated; and canonical beacon APIs don't serve orphaned blocks while big
  operators blank graffiti — so it sees neither the victims nor the operators that matter. Operator client mixes
  are **deliberately not imputed** (the orphan set is operator-concentrated → it would fabricate the
  operator→client confound). A MigaLabs inquiry is open as a possible future update.
- **Tertiary = entity/operator** via CBT `fct_block_proposer_entity` (the workhorse; populated for orphaned
  *and* missed because it derives from proposer duties; **post-Electra labeling**). `entity` = pool/operator,
  **not** CL client; DVT may be folded into a pool name (inspect distinct values).
- **Blob / block-size layer (reviewer-driven):** per-block `blob_count` = `execution_payload_blob_gas_used` ÷
  131072 (GAS_PER_BLOB) and `block_total_bytes`, read directly off CBT `fct_block` (carries them for orphaned
  blocks too) by widening `q1`/`q_canon` — **not** `fct_block_blob_count`, whose `status` column is broken
  (mislabels canonical vs orphaned; verified). `q_blob_by_position` aggregates avg blobs by `slot%32 × status`.
  Build-path split = relay map from `mev_relay_proposer_payload_delivered` (full pre-Electra coverage).
  *Operational note:* the in-sandbox `panda execute` path requires the CH-26 analyzer, which rejects
  aggregate-aliased-to-column-name (`argMax(x, …) AS status`); the slot-31 parent dedup aliases were renamed
  `par_*` to fix it. A targeted re-pull of `q1`/`q_canon`/`q_blob_by_position` ran via direct `panda clickhouse
  query` (monthly windows; comment-strip the SQL — a leading `--` is parsed as a CLI flag).

## 4. Statistics (scipy/numpy — statsmodels & sklearn absent locally)

- Per-position orphan rate, **Wilson** 95% CIs (rates ~0.1–1% → Wald invalid). slot 0 & slot 1
  pre-registered primary contrasts; 2..31 exploratory under BH-FDR.
- slot-0 vs pooled-rest: `fisher_exact` + `chi2_contingency`; risk ratio with delta-method log-RR CI.
- Report **three** effect metrics: normalized `orphan_rate`, gist `count_vs_avg`, pooled-rest RR.
- Per-entity over-representation = **excess over own baseline** (`qattr2`), Wilson CI in Python.
- **Scale-only** logistic `orphaned ~ is_slot0 * covariates` (day-clustered SEs via scipy MLE + bootstrap).
  The verdict must **survive** adjustment for the central alternative null — **epoch-transition compute
  load** (RANDAO reshuffle + just-applied transition) — plus slot-31 lateness, MEV-Boost-vs-local, blob load.

## 5. Pilot → scale staging

| Stage | Window | ~slot-0 events | Powers |
|-------|--------|----------------|--------|
| Pilot A | most-recent ~10k slots | ~2–7 orphans | pipeline validation only (underpowered) |
| Pilot B | Jan-2026 spike (`2026-01-01..2026-02-01`) | ~150 orphans | base-rate (a), time-series (d) |
| Scale | 12–24 months (heterogeneous floors) | thousands | per-entity (b), multivariable (c) |

**Per-table history floors** (stamp each dataset's true covered range): `fct_block`/`canonical_beacon_block`/
`events_block`/`libp2p` 2020-12; `events_chain_reorg` 2023-03; `events_attestation` 2023-06; **`mev_relay_*`
~2024-09** (so a full 24-month *relay* / H4 series does not exist — window H4 to its floor).

## 6. Outputs

`slot0-reorg-results.md` (numbers + dataset index w/ ranges) · `slot0-reorg-decision-log.md` (why each pivot)
· `slot0-reorg-findings.md` (ethresear.ch companion + claims ledger) · `is-slot-0-reorg-cost-fixable.md`
(article) · `figures/fig_*.{png,svg}` (8 figures). Pilots ship under a **v0/PROVISIONAL**
banner, superseded by the scale run.

## 7. First-live-run gate (must pass before any number is trusted)

Run `python3 extract.py --probe`, then verify:
- **U1 names** resolved from `list_datasources()`; runner fails loudly if `DS_RAW` absent.
- **U2 param binding** `{x:UInt32}/{"x":7}` → 7 (probe asserts this).
- **U3 CBT exposure** `SHOW TABLES FROM mainnet` lists `fct_block`, `fct_block_proposer_entity`,
  `fct_block_first_seen_by_node`, `canonical_beacon_elaborated_attestation`, `fct_block_mev`,
  `fct_block_blob_count`, `dim_validator_pubkey` (else hand-roll the CBT track from raw).
- **U4 units** confirm via `panda schema <table>`: ms for `events_block`/`events_attestation`/`libp2p`,
  **slots** for `events_chain_reorg`.
- **U5 `chain_reorg.depth`** validate against a few known Jan-2026 boundaries before any `slot−depth` math.
- **U7 `FINAL`** accepted on raw tables (use `FINAL` *and* aggregate — `FINAL` alone won't dedup sentries).
- **U8/U9** `proposer_payload_delivered` has no timing column; `bid_trace` timing = collector poll.
- **U10** `value` UInt256 → string → Decimal in Python.
- **U14** confirm scipy/numpy inside the sandbox before any server-side fit.
- **Smoke:** probe + `q4` over a 1-day window returns a sane 32-row distribution with slot 0 elevated.

## 8. Origin

The hypotheses tested here (the four candidate causes, the slot-31 fork-choice protection and its
withholding corollary, the ~1s builder bid-return deadline, the slow-attester bound, and the
gas-limit/sequencing trade-offs) come from an Ethereum research discussion on the EPBS/Gloas attestation
deadline. They are stated in the article as un-attributed hypotheses and adjudicated on the data.
