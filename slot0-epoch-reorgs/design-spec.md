# Design Spec — Slot-0 Epoch-Boundary Reorg Study & Article

- **Venue / type:** ethresear.ch-style post (first-person, expert audience), data-driven, with a
  reproducible pipeline in this repo. Companion to a research-chat discussion on the EPBS/Gloas
  attestation deadline.
- **Status:** pipeline built; data pending first live `panda` run. Pilots ship v0/PROVISIONAL.
- **Length / voice:** ~2800–3500 words, first-person, confident-but-cited, open-problem framing.
- **Source:** an Ethereum research discussion on the EPBS/Gloas attestation deadline (hypotheses stated
  un-attributed in the article and adjudicated on the data).

## 1. Goal & through-line

Charts of reorgs-by-position show them concentrated at the **first slot of an epoch (slot 0)**. The stakes: if that
cost is **fixable client engineering** at the epoch transition, the attestation deadline can drop **3s → 2s**
(reclaiming ~1s of execution every slot); if it is **structural** (a late/under-attested slot-31 parent,
relay timing games), 2s would entrench the orphan rate. The post decides — with layered confidence — which
of four hypotheses the data supports, and what that implies for 3s vs 2s.

## 2. Thesis (pre-register BOTH so the draft is data-driven, not pre-committed)

- **Primary:** the slot-0 reorg is dominated by **fixable client engineering and/or relay timing games**, so
  EPBS/Gloas can safely target 2s once those are addressed.
- **Fallback:** the cost is **structural** (late/under-attested slot-31 parent → missed precomputed epoch
  transition, spread across operators) → stay at 3s until the epoch-transition precompute is hardened.

## 3. Claims ledger (the accuracy contract)

**✅ Confirmed (verified against primary sources):**
- Xatu `meta_client_*` = the observing sentry, **not** the proposer's client.
- The slot-0 victim is the orphaned block (`fct_block.status='orphaned' AND slot%32==0`); `chain_reorg.slot`
  is the slot switched *to* (~`slot%32==1`).
- `propagation_slot_start_diff` is ms for block/attestation/libp2p, **slots** for `chain_reorg`.
- Proposer CL client is attributable **pre-Electra only** via Xatu's `beacon_block_classification`
  (blockprint, coverage through ~2025-05-07); post-Electra and EL client are unattributable. (The *public*
  blockprint API is frozen, but Xatu's ingested copy enabled the pre-Electra client ranking.)
- `mev_relay_*` data exists only from ~2024-09 → no full-24-month relay series.
- Spec: `get_proposer_head`/`is_epoch_boundary` protect slot 31 from honest reorg → slot 0 is the victim.

**⚠️ Corrected (vs the initial agent designs):** bin by victim slot not event slot; dedup sentries (don't
trust `FINAL` alone on raw); `proposer_payload_delivered` has no timing column; entity (not client) is the
attributable unit; report three effect metrics (normalized rate, gist `count_vs_avg`, pooled-rest RR).

**🔱 Distinctions to maintain:** orphaned vs missed; sentry vs proposer; entity (operator/pool) vs CL client;
RR/correlation vs causation; pilot (provisional) vs scale (powered).

**Supporting facts for color:** the known "second-slot-of-epoch reorgs from Prysm gossip delaying slot-0
propagation"; the Prysm DB issue (saving the large state >12s); the Jan-2026 mainnet reorg spike.

## 4. Section outline (word targets)

1. **TL;DR** (4 sentences).
2. **Intro / framing (~250w):** why epoch-boundary slots are special (slot-31 protection pushes the orphan
   to slot 0); the 2s-vs-3s stakes; the sentry-not-proposer caveat up front.
3. **Part 1 — The phenomenon (~500w)** [Fig 1]: slot 0 over-orphaned; confirm not a sentry artifact;
   orphaned vs missed; size it (normalized rate + gist `count_vs_avg` + pooled-rest RR).
4. **Part 2 — Four hypotheses, four lenses (~1100w):** 2a slot-31 parent late/under-attested [Fig 2];
   2b proposer CL client / DVT — **the documented gap** (blockprint; entity as workhorse) [Fig 3];
   2c relay & bid-return timing (1s deadline; collector-poll caveat); 2d forkchoice dump — flag dropped.
5. **Part 3 — Jan-2026 spike as a natural experiment (~600w)** [Fig 4]: one cause or many? Narrate as a
   case study (n≈2 mega-events; not load-bearing for the verdict).
6. **Part 4 — Verdict: 3s or 2s? (~500w):** apportion the causes (or state "cannot cleanly apportion");
   fixable-vs-structural; recommendation with confidence labels.
7. **Part 5 — Limits & open data gaps (~300w):** proposer client unattributable; no DVT resolution;
   forkchoice unavailable; pilot-vs-full; per-table floors; sentry coverage; the epoch-transition-compute null.
8. **Closing (~150w) + References.** (No acknowledgements / no names — hypotheses stated un-attributed.)

## 5. Figures (chart ← dataset)

| Figure | Dataset (query) |
|--------|-----------------|
| `fig_orphan_by_slot_position` (bar, slot 0 highlighted, Wilson bars) | `orphan_by_position` (q4) |
| `fig_slot31_lateness_vs_slot0_orphan` (slot-31 lateness distribution) | `slot31_lateness` (t3a) + `slot0_orphans` (q1) |
| `fig_entity_over_representation` (excess-over-baseline, CI) | `entity_excess` (qattr2) — replaces the impossible per-CL-client chart |
| `fig_jan2026_orphan_timeseries` (MAD bands) | `daily_orphan_series` |

## 6. Attribution

No personal names. The hypotheses from the originating discussion (four candidate causes; slot-31 protection
and its withholding corollary; the ~1s builder bid-return deadline; the slow-attester bound; the
gas-limit/sequencing trade-offs) are stated as un-attributed hypotheses and adjudicated on the data.

## 7. References (to populate during drafting)

consensus-specs `get_proposer_head` / fork-choice; ethPandaOps Xatu + xatu-data schema; sigp/blockprint +
the Electra-freeze note + accuracy study (arXiv 2409.15808); the Jan-2026 reorg-spike gist; Blocknative
late-block-reorg pieces; ethPandaOps Fusaka-blobs/votes + FCR-simulator posts.

## 8. Drafting guidelines

Lead with the phenomenon, then the hypotheses, then the verdict. Keep the sentry-vs-proposer and
blockprint-gap caveats visible (they shape what can be claimed). Mark provisional vs durable. Every number
links to `results.md` provenance. State all intuitions un-attributed; no personal names anywhere.
