# Results — Slot-0 Epoch-Boundary Reorg Study

Numbers + dataset index. Method: `methodology.md`. Pivots: `decision-log.md`.
All figures regenerate from the JSON via `data/plot.py --label scale` (written to `figures/`).

> **Scope.** Mainnet, **2024-09-01 → 2026-06-01** (~21 months, aligned to the `mev_relay_*` history
> floor so every signal is present). **142,021 epoch boundaries** (slot-0 slots). Proposer **CL client is
> attributable pre-Electra only** (blockprint via Xatu, frozen ~2025-05-07); operator **entity** is the
> attributable unit post-Electra. Pilots A (10k slots) and B (Jan-2026, 215k slots) agree directionally.

## 1. The phenomenon — slot 0 is orphaned ~7× the rest

| Position | Orphan rate | n (orphaned / slots) |
|---|---|---|
| **slot 0** | **1.169%** (Wilson 95% 1.11–1.23) | 1,660 / 142,021 |
| slot 1 | 0.343% (~2.1× rest) | 489 / 142,694 |
| all other positions (pooled) | 0.164% | 7,254 / 4,431,585 |
| **slot 31** (least-orphaned) | **0.085%** (~0.43× avg) | 121 / 142,878 |

**slot-0 vs pooled-rest: risk ratio 7.1, Fisher exact p ≈ 0** (`< 1e-300`). slot 1 is elevated (the
"second-slot" spillover) but an order of magnitude below slot 0; slot 31 is the *least*-orphaned position,
consistent with its fork-choice protection. [`figures/fig_orphan_by_slot_position_scale`] Headline RR is
period-dependent (13.3 over Jan-2026 alone; 7.1 over 21 months is representative). Excluding the single
network-wide incident on 2026-03-31 (§4) *raises* the RR to **8.87** (it is conservative for the claim).
Separately, slot-0 proposers *miss* their slot (no block at all) **1,536 times = 1.08%** — a distinct
failure, reported apart from orphaning.

## 2. Mechanism — the slot-0 block's own lateness (not the parent)

| Cohort | block first-seen p50 (p2p) | by 3s / by 4s | p90 |
|---|---|---|---|
| **orphaned** slot-0 (victims, n=1,660) | **4,418 ms** | 3.5% / **18.8%** | 7,526 ms |
| **canonical** slot-0 (survivors, n=4,272 sample) | **2,148 ms** | 84% / 94% | 3,352 ms |

Mann-Whitney (orphaned later): **p ≈ 0**; the gap holds **within every half-year era** (victims ~4.3–4.6s vs
survivors ~1.9–2.3s throughout — not a secular-trend artifact). Case-control logistic, orphaned ~
log10(first-seen) + relay-delivered + era, winsorizing >12s outliers: **OR ≈ 8.1 per doubling of first-seen**
(≈5.5 per +1sd), and **relay-delivered OR ≈ 0.15** (protective; see §3). The ECDF
[`figures/fig_propagation_orphaned_vs_canonical_scale`] shows survivors mostly under 3s while victims pile up
around and past the 4s deadline.

## 3. The four hypotheses

- **H1 — proposer client/operator.** Two separable, temporally-disjoint signals:
  - **Operator (entity), full window.** upbit: **303 / 979 slot-0 blocks orphaned (31%, +30pp over its own
    1.07% baseline) = 18.3% of all 1,660 slot-0 orphans** (97% locally built); stakefish 101/1,286 (7.9%),
    blockdaemon_lido 32/566 (5.7%), abyss_finance 45/1,760 (2.6%). The **largest single bucket is `unknown`
    (407 = 24.5%)** → operator concentration is a *lower bound*. [`figures/fig_entity_over_representation_scale`]
  - **CL client (blockprint, pre-Electra only, 2024-09→2025-05-07; 342 attributed + 29 unattributed of 371
    orphans).** Orphan rate by client (Wilson 95%): **Nimbus 1.75% [1.35,2.26]** — robustly worst (Fisher
    p≈3e-19 vs Lighthouse, p≈3e-8 vs Prysm); Teku 0.70% [0.57,0.86]; Prysm 0.68% [0.58,0.81]; Lodestar 0.87% (n=5,
    uninformative); **Lighthouse 0.29% [0.23,0.38] and Grandine 0.35% [0.10,1.27] are statistically tied**
    (Fisher p=0.69). By volume Prysm (135) + Teku (88) = 223/371 (~58% of proposers).
    [`figures/fig_client_orphan_rate_scale`]
  - **Disentangled:** 371 client-attributed orphans from **371 distinct validators** across many deposit
    cohorts (Nimbus 57→27 buckets, Prysm 135→95) → client-population effect, not one operator; operator
    outliers are **post-Electra** (where blockprint is dark) → the two cannot confound.
- **H2 — late/withheld slot-31 parent.** **Refuted.** Parent first-seen median **1,704 ms** (9% >3s, 1% >4s);
  **97% of orphaned slot-0s built on their slot-31 parent**. The withholding-exploit signature is small: only
  **~2%** (33/1,660) sat on an *orphaned* slot-31 parent. [`figures/fig_slot31_lateness_vs_slot0_orphan_scale`]
- **H3 — forkchoice dump at reorg.** Dropped: no per-node fork-choice snapshot table in Xatu.
- **H4 — relay / local build.** **Inverts the original framing.** Orphaned slot-0s are **37.8% relay-delivered
  (628/1,659)** vs canonical **88.7% (3,789/4,272)** → orphaned blocks are **~62% locally built** vs ~11%.
  Relay-delivery is *protective* (logistic OR ≈ 0.15); local block-building at the busy epoch transition is
  the slow path. [`figures/fig_relay_localbuild_scale`] (Operator confound: upbit 97% local, binance 87%, but
  stakefish/blockdaemon_lido only ~37% — local build is dominant, not the sole route.)
- **H5 — slow attesters bound the deadline.** **Supported.** Of a slot-31 block's eventual head-voters, a
  median of only **~29% are observed by 3s, ~47% by 4s** — a long attester tail the deadline must wait for.
  [`figures/fig_slow_attesters_scale`]
- **H6 — blob-heavy blocks (reviewer).** **Supported; mechanism, not structural.** Orphaned slot-0s carry more
  blobs: median **5 vs 4**, **≥9 blobs 17% vs 9%** (MWU p≈1e-20) — yet are *smaller* in beacon bytes (90 vs 114
  KB), so the burden is the blob **sidecars**, not block size. Locally-built orphans blob-heaviest (≥9: 19% vs
  relay 13%). Logistic + `blob_count_z`: lateness OR unchanged (8.07/doubling), blob OR **1.04/blob** → acts
  through propagation lateness. **Blob-by-position FLAT** (slot0 3.70 ≈ cross-pos mean 3.72) → refutes
  rollup-clustering folklore. [`figures/fig_blob_compare_scale`, `fig_blob_by_position_scale`]
- **Build-path confound (reviewer, Nimbus).** Pre-Electra, **build path dominates**: every client orphans
  ~5–10× more locally-built than relay-delivered (Nimbus 3.6%/1.5%, LH 1.5%/0.08%). Nimbus self-builds at the
  same ~14% as others and is worst in **both** strata (vs LH local Fisher p≈5e-3; vs Prysm local p≈0.20, small
  n) → not a build-path artifact. `summary`/`client_attribution_scale.build_path_confound`.
  [`figures/fig_client_buildpath_scale`]
- **Relay-delay (reviewer "~1s artificial").** Over-stated: among survivors, relay-delivered are only ~**190ms**
  later (median) than locally-built; low-blob blocks 42% vs 39% by 2s. `summary.relay_delay_canonical`.
- **Blocks are growing:** avg slot-0 beacon block **106→170 KB (+60%)** by half-year, rising with the reorg
  rate. `summary.blob_size_trend`. [`figures/fig_blob_size_trend_scale`]

## 4. Time series

Daily slot-0 orphan rate: median **0.90%**. The one unambiguous event is **2026-03-31 at 24.6% slot-0 — but
that day's all-slot rate was 23.2%, a network-wide incident, not slot-0-specific**; excluding it raises the
RR (§1). MAD also flags ~Poisson-noise days; only 2026-03-31 (and to a lesser extent 2025-12-04) are real.
Underneath the noise the slot-0 rate is **rising**, not steady: by half-year it climbs **0.58% (2024-H2) →
0.83% → 1.43% → 1.73% (2026-H1)** while all-slot stays ~0.15–0.29% (`summary.half_year_trend`) — so the dial
should be calibrated to the current ~1.7% regime, not the pooled 1.17%. [`figures/fig_jan2026_orphan_timeseries_scale`]

## 5. Dataset index (`data/*_scale.json`)

| Dataset | Rows | Query | Covered range |
|---|---|---|---|
| orphan_by_position | 32 | q4 (CBT) | 2024-09→2026-06 |
| slot0_orphans | 1,660 | q1 (CBT) | 2024-09→2026-06 |
| entity_victim_parent | 1,660 | qattr1 (CBT) | 2024-09→2026-06 |
| entity_excess | 1,077 | qattr2 (CBT) | 2024-09→2026-06 |
| daily_orphan_series | 638 | q_daily (CBT) | 2024-09→2026-06 |
| missed_slot0 | **1,536** | q2b (CBT calendar anti-join) | 2024-09→2026-06 |
| canon_slot0 | 4,272 | q_canon_slot0 (CBT, ~3% sample; now carries blob_count + block_total_bytes) | 2024-09→2026-06 |
| blob_by_position | 32 | q_blob_by_position (CBT, avg blobs by slot%32 × status) | 2024-09→2026-06 |
| slot31_lateness | 1,657 | t3a (RAW) | 2024-09→2026-06 |
| slot31_attest_support | 1,642 | t3b (RAW) | 2024-09→2026-06 |
| slot0_propagation (+_canon) | 1,660 / 4,272 | t3c (RAW) | 2024-09→2026-06 |
| relay_bid_timing (+_canon) | 3,320 / 4,272 | t3d (RAW) | 2024-09→2026-06 |
| client_attribution | 342 attr + 29 unattr / 54,989 canon | client_attribution.py (blockprint) | **2024-09→2025-05-07** |
| summary | — | analyze.py | — |

Coverage queries `q3`/`q5` were validated in the pilots and skipped at scale (`--lean`). A per-output
`manifest.json` records expected-vs-actual target counts so a chunk-skip cannot silently undercount.

## 6. Caveats

Proposer CL client attributable **pre-Electra only** — and the post-Electra gap is *structural*: **EIP-7549
(in the Electra fork itself) collapsed blockprint's attestation fingerprint (~1,366 → ~22)**, blockprint is
abandoned, and all downstream sources are frozen/aggregate/graffiti-only (we do not impute operator client
mixes — it would fabricate the operator→client confound). The "fixable engineering" verdict rests on
client-independent evidence (operator concentration + local-build + survivor/victim gap) + the pre-Electra
client result. DVT not separable from its pool label. `entity` = pool/operator, not CL client; ~24.5% of orphans are unattributed.
Reorg-detection is sentry-client-dependent. blockprint is a probabilistic classifier (~5–10% error,
concentrated in minority clients) → small-n client rates are directional. The canonical cohort is a
time-stratified 3% sample (the gap holds within era). `t3b` is the orphan-parent cohort without a clean
normal-slot baseline. first-seen is the *earliest* sentry observation (a `min`) — a proposer-side publish
proxy, not attester reception. The mechanism is descriptive + case-control logistic (not randomized);
"lateness → orphaning" is partly definitional, but the survivor/victim split, the relay/local-build split,
and the operator/client concentration localize it to *fixable production speed*, not a structural slot-0 cost.
