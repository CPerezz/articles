# Findings — Are Slot-0 Epoch-Boundary Reorgs a Fixable Cost?

*Companion note to the article `is-slot-0-reorg-cost-fixable.md`. The sharp claim, the evidence, and the
honest scope. Data: mainnet 2024-09 → 2026-06 (21 months, 142,021 epoch boundaries) via ethPandaOps Xatu.*

## The claim

**The slot-0 (epoch-boundary) reorg is not a structural protocol cost — it is dominated by a slow slot-0
*block*, disproportionately one built *locally* (not via a relay), concentrated in specific operators and
clients, and therefore fixable engineering.** Across 21 months, the first slot of an epoch is orphaned
**7.1×** more often than other slots (1.17% vs 0.16%, n=1,660). The cause is **not** a late parent (the
slot-31 parent is on time and 97% of victims built on it). The discriminators are: the slot-0 block's **own**
late propagation (victims first seen ~4.4s vs ~2.1s for survivors); being **locally built** rather than
relay-delivered (~62% of victims vs ~11% of survivors); and operator/client concentration (one operator is
18% of all slot-0 orphans by itself).

## What this means for 3s → 2s

The deadline debate framed slot-0 reorgs as a reason to stay conservative; the data says they are mostly
fixable. **But a naive deadline cut would backfire**, so sequencing is the point. Even among slot-0 blocks
that *survive* today, only ~39% are first seen by 2s — a 2s deadline applied now would threaten roughly half
of today's survivors. And the deadline is partly owed to slow attesters (median ~29% of a block's voters in
by 3s), independent of proposer speed. **So: fix the slow epoch-transition / local-build path first, then
bring the deadline down** (plausibly a later fork — Glamsterdam's gas-limit step is already large).

## Claims ledger (accuracy contract)

**✅ Confirmed by the data**
- slot 0 orphaned 7.1× the pooled rest (1.17% vs 0.16%, Fisher p ≈ 0, n=1,660); slot 1 ~2.1×; slot 31 the
  *least*-orphaned (0.085%, consistent with its fork-choice protection).
- Orphaned slot-0 blocks are seen far later than survivors (4.4s vs 2.1s, MWU p ≈ 0; gap holds within every
  era). Logistic (relay + era controlled, winsorized): **OR ≈ 8.1 per doubling of first-seen** (≈5.5/sd).
- Orphaned slot-0s are disproportionately **locally built** — 37.8% relay-delivered vs 88.7% for survivors;
  relay-delivery is *protective* (OR ≈ 0.15).
- Slot-31 parent on time (median 1.7s; 97% built on it) → late-parent mechanism refuted; the withholding
  exploit is ~2% (small).
- A few operators dominate: upbit 31% of *its* slot-0 (= 18% of all orphans, 97% local), then stakefish,
  blockdaemon_lido, abyss_finance — though the largest single bucket (24.5%) is unattributed.
- **CL client (pre-Electra only, 342 attributed of 371):** **Nimbus robustly worst** (1.75%, Fisher
  p≈3e-19 vs Lighthouse, p≈3e-8 vs Prysm); **Lighthouse (0.29%) and Grandine (0.35%) statistically tied** (p=0.69);
  Lodestar (n=5) uninformative; Prysm+Teku dominate by volume (223/371). Client signal is from 371 distinct
  validators across many cohorts — not the (post-Electra) operator outliers; the two are temporally disjoint.
- Slow-attester tail: only ~29% of a block's voters in by 3s, ~47% by 4s.
- **Blobs (reviewer hypothesis): orphaned slot-0s carry more blobs** — median **5 vs 4**, **≥9 blobs 17% vs
  9%** (MWU p≈1e-20); yet *smaller* in beacon bytes (90 vs 114 KB) → the burden is the blob **sidecars** (DA),
  not block size. Locally-built orphans are blob-heaviest (≥9: 19% vs relay 13%). In the logistic, lateness OR
  is unchanged (8.07/doubling) and blob adds a small independent OR (1.04/blob) → blobs act *through*
  propagation lateness. **Blob-by-position is FLAT** (slot0 3.70 ≈ cross-pos 3.72) → refutes "rollups cluster
  blobs at slot 0 / Arbitrum avoids slot 0."
- **Build-path is the dominant axis (Nimbus confound test):** pre-Electra, *every* client orphans ~5–10× more
  locally-built than relay-delivered (Nimbus 3.6%/1.5%, Lighthouse 1.5%/0.08%). Nimbus self-builds at the same
  ~14% as others and stays worst in **both** strata (vs LH local p≈5e-3) → its signal is **not** a build-path
  artifact (operator-mix/blockprint error still apply).
- **Blocks are growing:** avg slot-0 beacon block 106→170 KB (+60%) over the window, rising *with* the slot-0
  reorg rate — and ePBS removes exactly that growing data (payload/blobs/BAL) from the attestation-relevant block.

**⚠️ Corrected / nuanced**
- Headline ratio is period-dependent (13.3× Jan-2026, 7.1× over 21 months — quote 7.1).
- The one real spike, 2026-03-31 (24.6% slot-0), is a **network-wide incident** (23.2% all-slot), not
  slot-0-specific; excluding it raises the RR to 8.87. Underneath, the slot-0 rate is **rising** (by half-year
  0.58% → 0.83% → 1.43% → 1.73%, all-slot ~flat), so calibrate to the current regime, not the pooled rate.
- "Relay timing games cause it" → reversed: relay delivery is protective; it's the *local-build fallback* that
  is slow (which is exactly the bid-return-deadline concern run forward).
- "Lower the deadline because slot-0 reorgs are unavoidable" → reversed: avoidable; fix production first.
- "The relay adds ~1 artificial second" (reviewer) → **over-stated by the data**: among *survivors*,
  relay-delivered slot-0s are only ~**190ms** later at the median than locally-built (not ~1s); the solid 2s
  lever is ePBS shrinking the attestation-relevant block, not removing a relay-second. The 2s at-risk shares
  are the *current* big-block regime → measure 2s post-ePBS, don't assume it now.

**🔱 Distinctions maintained**
- orphaned (built then dropped, 1.17%) vs missed (no block, 1.08%); operator **entity** vs **CL client**;
  correlation/case-control vs causation; victim slot (`status='orphaned'`) vs the `chain_reorg` event slot;
  relay-delivered vs locally-built.

**🚫 Could not determine (open data gaps)**
- **Proposer CL client post-Electra — structurally, not just for lack of tooling.** blockprint fingerprints a
  client by its attestation packing; **EIP-7549 (shipped in the same Electra fork whose reorgs we study)
  collapsed that signal (~1,366 → ~22 attestations behind a supermajority)**, so the fingerprint is destroyed
  at the source. blockprint was abandoned/archived; Rated/beaconcha.in/ethseer-MigaLabs/etherscan/
  clientdiversity.org are all frozen-blockprint, network-aggregate, or graffiti-only — none exposes a
  per-proposer client. Graffiti was also checked and closed: not in Xatu (`system.columns` has no graffiti
  column), the explorer retaining orphaned blocks is auth-gated, and canonical APIs don't serve orphaned
  blocks while big operators blank graffiti — so it sees neither the victims nor the operators that matter. We do **not** impute operator-level client mixes (the post-Electra orphan set is
  operator-concentrated, so it would fabricate the operator→client confound). A MigaLabs inquiry is open as a
  possible future update. **Note the verdict does not need it:** "fixable engineering" rests on
  client-independent evidence (operator concentration + local-build + survivor/victim gap) plus the
  pre-Electra client result; the gap costs us *which client* today, not *whether* it's engineering.
- EL client unattributable; DVT not separable; slot-31 *attestation* baseline absent; no fork-choice
  snapshots; epoch-transition compute not directly controlled; proposer geography not in Xatu.
