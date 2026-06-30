# Decision Log — Slot-0 Epoch-Boundary Reorg Study

Chronological record of *why* each pivot happened. Pairs with `methodology.md` (the how)
and `results.md` (the numbers). Many entries are corrections forced by contact with the
live cluster — the synthesis design was right on intent and wrong on several specifics.

## §1. Attribution had to be re-scoped: blockprint is dead post-Electra
The original aim was "which CL client causes slot-0 reorgs." Verification found the public blockprint
API frozen at epoch 364031 (pre-Electra), all-zeros after, fine-grained endpoints 401. **Proposer CL
client is unattributable for any current window.** Pivot: lead with operator **entity** attribution
(CBT `fct_block_proposer_entity`) and treat the CL-client gap as a published finding, not a query.

## §2. The victim slot is the orphaned block, not `chain_reorg.slot`
A `chain_reorg` event fires at the slot the node switched *to* (≈ slot%32==1 for a slot-0 orphaning).
Binning `chain_reorg.slot % 32` would have put the entire phenomenon in the wrong bucket. Pivot: the
primary detector is CBT `fct_block.status='orphaned' AND slot%32==0`; `chain_reorg` is corroboration,
and the victim is recovered from `old_head_block`.

## §3. CBT `force_primary_key`: must filter on BOTH slot and slot_start_date_time
The synthesis said "filter on `slot_start_date_time` (the ORDER BY)." The live refined cluster rejects
that with `force_primary_key` (Code 277) — and different shards reported different keys
(`(slot, block_root)` vs `(slot_start_date_time, block_root)`). Empirically, only filtering on **both**
`slot` and `slot_start_date_time` passes on all shards. Pivot: every CBT query carries a `slot BETWEEN`
range plus the `slot_start_date_time` range; self-joins (slot-31 parent) use a widened bounded CTE so
each scan is independently key-satisfied. (Found by Pilot A; would have failed the whole CBT track.)

## §4. Integer query parameters were silently corrupted
`clickhouse.query_raw(..., {"min_slot": 14609598})` reached the server as `1.4609598e+07` (the client
formats numerics with `%g`) → `BAD_QUERY_PARAMETER`. Pivot: the runner stringifies all int params before
binding, so they pass verbatim. (ClickHouse HTTP params are strings anyway.)

## §5. ClickHouse-26 analyzer: `agg() AS <col>` collides with `<col>` in WHERE
`any(slot_start_date_time) AS slot_start_date_time` + a `WHERE slot_start_date_time …` in the same
SELECT raised `ILLEGAL_AGGREGATION`. Pivot: alias aggregates to non-column names (`AS sdt`, etc.).

## §6. TSV NULLs and column-qualifier leakage
`query_raw` returns TabSeparated strings; NULL is the literal `\N`, and `alias.col` under multi-table
joins is named `o.col` in the output. Pivot: the runner normalizes `\N`→null; the stats/plot helpers
cast strings safely; and SELECTs alias every projected column (`o.slot AS slot`).

## §7. `t3b` (parent attestation) rewritten — distributed-join denial
The first `t3b` joined two distributed tables (attestations × canonical) in subqueries →
`distributed_product_mode='deny'` (Code 288). Since q1 already yields each parent's canonical root, the
canonical join is unnecessary. Pivot: a single distributed table (`events_attestation`) INNER-JOINed to
a **local `values()`** of parent roots, with `uniqExactIf` giving the whole 2/3/4s deadline sweep in one
pass. Self-contained, fast, and a cleaner metric (fraction of a parent's voters reached by Ns).

## §8. Session leak → reuse one session per run
Each `panda execute` spawns a sandbox session; ~50 accumulated across pilots/tests and hit the proxy's
50-session cap (Pilot B's `t3c`/`t3d` failed on it, not on query cost — `t3a` had already proven a
31-day scan is tractable). Pivot: the runner creates and reuses **one** session per extract and destroys
it at the end. (Also added: the extract is resilient — one failing query logs and skips, never aborts
the run.)

## §9. Pilot A vs Pilot B scoping
Pilot A (~10k slots) was deliberately treated as plumbing-only (≈6 orphaned slot-0s — underpowered);
its job was to exercise every query/join/transport. Pilot B (Jan-2026, 215k slots, ~100 orphaned
slot-0s) was the first powered read. Both shipped before any conclusion, mirroring the geth study's
v0/provisional discipline.

## §10. Closing the deferred gaps before scaling (per review)
Five items were closed on the cheap Jan window before committing to the 21-month pull: (a) `t3b` rewrite
(§7); (b) a **canonical slot-0 comparison cohort** (sampled) so propagation/relay claims are A/B, not
absolute; (c) the relay **baseline** — orphaned vs canonical delivered-fraction; (d) `upbit` sanity
(48 events / 23 days / parent-independent — real); (e) **sdt-IN bounding** of the timing scans so they
run as single fast full-range queries at scale (no monthly windowing needed). Figures are now
label-suffixed so pilot and scale outputs coexist.

## §11. Scale window aligned to the relay floor
Per-table history floors differ (`fct_block` 2020-12, `events_chain_reorg` 2023-03, `events_attestation`
2023-06, `mev_relay_*` ~2024-09). To keep every signal — including relay — present across the whole
study, the scale window is **2024-09 → 2026-06** (~21 months). The base-rate (CBT-only) could extend
further back if a relay-free chart is wanted; noted as an optional extension.

## §12. Adversarial review caught an inverted relay conclusion (the biggest fix)
A multi-agent review (re-verified by hand) found the relay metric was driven by `no_relay_delivery`, which a
ClickHouse LEFT JOIN miss fills with the default `0` (not NULL) — so it read 100% for both cohorts and the
article wrongly claimed "relay is universal, not the discriminator." Truth: orphaned slot-0s are **37.8%
relay-delivered vs 88.7%** for survivors → **~62% locally built**. The bug also silently *dropped* the relay
covariate from the headline logistic (zero variance), so "OR controlling for relay" controlled for nothing.
Pivot: compute delivery from `relays_delivered` (and fix the SQL column to `empty(relays_delivered)`); refit
the logistic with relay retained; reframe H4 — relay-delivery is *protective*, local building is the slow path
(the bid-return-deadline concern run forward).

## §13. Logistic hardening: winsorize + era covariate + interpretable unit
Physically-impossible >12 s "first-seen" outliers (root-collisions) inflated the standardization sd ~2.6× and
biased the per-sd OR toward null. Pivot: winsorize first-seen at one slot (12 s) before standardizing, add an
era (month) covariate for the temporal confound (the canonical cohort is time-uniform; orphans skew late), and
report the lateness effect **per doubling** (scale-free) — OR ≈ 8.1/doubling, with relay OR ≈ 0.15.

## §14. Two more correctness fixes + missed-slot repair
- "victims ~5% by 4 s" used `api_p50`; the plotted column is `p2p_p50`, where victims are **18.8% by 4 s** —
  corrected, and the deadline-separation claim softened.
- "no spike" omitted **2026-03-31** (24.6% slot-0) — but that day was **network-wide** (23.2% all-slot), so it
  is named as an incident, not slot-0-specific; excluding it raises the RR to 8.87.
- `missed_slot0` was empty every run (a RAW anti-join that never fired). Pivot: a **CBT slot-0 calendar
  anti-join** against `fct_block` → **1,536 missed (1.08%)**, a real number.
- Per-client rates got **Wilson CIs** + robustness (Nimbus robustly worst; Lighthouse/Grandine tied,
  p=0.69; 29/371 orphans unattributed disclosed); the slot-31 self-join was deduped to the canonical parent.

## §15. Consolidation + de-attribution
All artifacts moved into a single self-contained `slot0-epoch-reorgs/` folder (`data/`, `figures/`, the
article + companion docs), separate from the unrelated geth-benchmark `assets/`. The article was restructured
around **un-attributed hypotheses** (each stated then supported/dismantled on the data) with **all personal
names removed** — no acknowledgements anywhere.

## §16. Post-Electra client attribution is structurally unobtainable (researched, not assumed)
Pushed on "can we get the proposer's client post-Electra from somewhere else?" — researched Rated, beaconcha.in,
ethseer/MigaLabs, etherscan, clientdiversity.org, and self-hosting blockprint. Verdict: **no**, and for a
structural reason worth stating in the article. blockprint fingerprints a client by its attestation packing;
**EIP-7549 (shipped in the same Electra fork whose reorgs we study, 2025-05-07) collapsed that signal**
(~1,366 → ~22 attestations behind a supermajority), so the fingerprint is destroyed at the source. blockprint
was abandoned/archived ("no longer accurate post-Electra"); every downstream is frozen-blockprint, network-wide
aggregate, or graffiti-only; no source exposes a per-proposer client field. Pivot: keep client attribution
**pre-Electra-only**, frame the gap as a *consequence of Electra*, and **explicitly reject importing
operator-level client mixes** (our post-Electra orphan set is operator-concentrated, so a mix would fabricate
the operator→client confound the pre-Electra analysis was built to avoid). The "fixable engineering" verdict is
made to rest on **client-independent** evidence (operator concentration + local-build path + survivor/victim
gap) plus the pre-Electra client existence-proof. A MigaLabs inquiry is outstanding as a possible future update.

## §17. Final revision: ethresear.ch reframe + 3 substance fixes
- **#1 first-seen is sentry-PoV:** justified in-text — same fleet observes victims and survivors, and first-seen
  is a `min` across sentries, so the *relative* gap is apples-to-apples even though absolute times are PoV-dependent.
- **#2 survivors at risk under a 2s cut:** quantified — ~61% of surviving slot-0 blocks are first-seen after 2s
  (32% after 2.5s, 16% after 3s); added a 2.5s point to the ECDF so the numbers are reproducible from summary.
- **#4 voice:** the post was rewritten from procedural ("I queried X") into an ethresear.ch argument
  (problem → reasoning → conclusion → recommendation); the "how" lives in methodology/results/decision-log.

## §18. Reframed around the Glamsterdam deadline decision; graffiti checked and closed
- **Motivation made the spine:** intro + verdict + closing now frame the work as informing where Glamsterdam
  sets the attestation deadline (ePBS turns it into a parameter; current 4s = SECONDS_PER_SLOT/3); the dial is
  a throughput lever (~8% of slot per second; tied to the ~200M gas target).
- **Read-through fixes:** quantified the scaling benefit (the gas-limit lever); added the magnitude/"so what"
  (the slot-0 *excess* is ~1,428 blocks = 0.031% of all blocks, ~1 in 3,200 — tiny in aggregate but the
  binding worst-case constraint); flagged the at-risk %s as an **upper bound** on new orphans (margin loss,
  not casualties); promoted **upbit** to the TL;DR; named the fix targets (upbit/ops + Nimbus pre-Electra) and
  the **bid-return deadline** as a second lever; trimmed the defensive client passage; de-duplicated the
  closing; scoped the missed-slot note; added prior-work positioning.
- **Graffiti investigated (per request) and CLOSED.** Not a viable post-Electra client source: (1) **not in
  Xatu ClickHouse** at all (`system.columns` works — 5,943 cols — none match `%graffiti%`; block-body table
  is sparse); (2) the explorer that retains orphaned blocks (Dora/beaconcha) is **auth-gated** (HTTP 401);
  (3) even via a beacon node, **canonical APIs don't serve orphaned blocks** (the victims' graffiti is
  unreachable), the heavy-orphaning **operators blank/override graffiti**, and it'd need an archival node +
  per-proposer historical lookups at scale. So graffiti sees neither the victims nor the operators that
  matter. Recorded as another checked-and-closed avenue alongside the blockprint downstreams.

## §19. Opus reviewer panel (5 lenses + adversarial fact-check) → 7 verified fixes
A multi-agent panel (skeptic / client-eng / statistician / fact-checker / editor, each with a verifier that
re-checked findings vs the JSON + web) flagged a set of over-claims; all were **re-verified by hand against the
data** before applying. Confirmed and fixed:
- **Slow-attesters mis-scoped (critical).** The 29%/47% is `parent_attestation` over the orphan cohort's
  **slot-31 parents** (n=1642), from **unaggregated** attestations (t3b: "a participation PROXY, not the full
  committee") — the article had generalized it to "a block's eventual voters." Reframed with full provenance +
  distinguished from the block-first-seen dial numbers.
- **Fisher overstatement.** "p<1e-18 vs every higher-volume client" was false — stored pairwise are
  nimbus-vs-lighthouse **3.0e-19** and nimbus-vs-prysm **2.8e-8** (Teku not computed). Corrected in article +
  results.md + findings.md.
- **Rising rate.** "steady ~0.9%/day" hid a near-tripling: half-year slot-0 = **0.58→0.83→1.43→1.73%**,
  all-slot ~flat. Added `half_year_trend` to analyze.py (reproducible from summary), reframed the time-series
  section, and recommend calibrating the dial to the current regime.
- **Bid-return lever dropped.** Bid columns are unreliable (collector-poll, dropped at analyze.py:177) and the
  direction is arguable (a tighter cutoff could *increase* local fallback) — removed the "lower the bid-return
  deadline" recommendation; the supported lever is relay coverage + faster local-build fallback.
- **Mechanism demoted to hypothesis.** Committee/RANDAO shuffling is already precomputed via lookahead; re-aimed
  at epoch-transition state-processing/state-root + the local build-and-publish path; "could not be measured."
- **Claims calibrated.** "settles the structural question" → "inconsistent with a *uniform* structural toll";
  "fixable" → "strongly indicated" with the relay-delivered residual flagged; Nimbus carries its
  build-path/noisy-classifier hedge into the recommendation; pre→post-ePBS framed as a conservative upper bound
  (bottleneck is consensus-side, which ePBS doesn't decouple).
- **Presentation.** 8 figures embedded as real `![caption](…png)` images (were bold path tokens that render as
  literal text on Discourse); TL;DR restructured verdict-first + bullets; date label 2026-06 → **2026-05**.
- **Rejected (panel pre-filtered; concurred):** OR-per-doubling "not a risk multiplier" (OR≈RR at 1.2% base),
  EIP-7732 deadline-attribution (defensible via the spec preset bundle), 97% parent denominator (nit), title
  (taste). Panel confirmed ~30-40 headline numbers reproduce exactly; Fisher was the only outright error.

## §20. Three explanatory figures added (the post was all data-charts, no diagrams)
The 8 existing figures were all data plots; the post is about *timing within a slot* and a *fork-choice
handoff between slots*, both described only in prose. Added (plot.py + embedded, renumbered to 11 figures):
- **fig_slot_anatomy** (Fig 1) — schematic of the 12s slot with the 2/3/4s candidate deadlines and where
  surviving (median 2.1s) vs orphaned (4.4s) blocks land (p10–p90 bands from the propagation JSON). The
  one-glance thesis.
- **fig_epoch_boundary** (Fig 3) — schematic of why slot 0 pays: slot 31 protected → slot 0 late → slot 1
  builds on 31, orphaning slot 0.
- **fig_half_year_trend** (Fig 10) — slot-0 vs all-slot orphan rate by half-year (the rising-rate finding),
  from `summary.half_year_trend`.
Also corrected three stale on-figure captions to match the panel fixes: the Fisher overstatement in
`fig_client_orphan_rate`, the slow-attester provenance in `fig_slow_attesters`, and "steady ~0.9%" in
`fig_timeseries`.

## §21. Reviewer feedback integrated (blobs, build-path confound, growing-blocks, ePBS levers)
The originating researchers reviewed the post; their points were scoped by a read-only agent swarm and every
claim hand-verified before use (incl. a live blob preview + the EIP-8146/7872 pages read directly).
**New data:** widened `q1`/`q_canon` for `blob_count` (= `execution_payload_blob_gas_used`/131072) +
`block_total_bytes` from `fct_block` (NOT `fct_block_blob_count`, whose status is broken); new
`q_blob_by_position.sql`; re-extracted q1/canon/blob-by-position over 21mo via **direct `panda clickhouse
query` CLI** (the sandbox `panda execute` choked on the old `q1` agg-alias shadow under CH-26 — fixed by
renaming the `argMax(... ) AS status/block_root/proposer_index` parent aliases to `par_*`; the sandbox itself
works). New analyze.py: `blob_compare`, `blob_size_trend`, `relay_delay_canonical`, `blob_by_position`, +
`blob_count_z` covariate in the logistic. New `client_attribution.py` build-path split (relay map from
`mev_relay_proposer_payload_delivered`). 4 new figures (blob_compare, blob_by_position, blob_size_trend,
client_buildpath) → 15 total.
**Findings (all hand-verified, gate PASS):** (1) **orphaned slot-0 carry more blobs** — median 5 vs 4, ≥9
blobs 17% vs 9% (MWU p≈1e-20), yet SMALLER in beacon bytes (90 vs 114 KB) → it's the blob *sidecars* (DA), not
block size; locally-built orphans blob-heaviest. (2) **blob-by-position is FLAT** (slot0 3.70 ≈ cross-pos 3.72)
→ refutes the "rollups cluster blobs at slot 0 / Arbitrum slot-20-22" folklore (data, not assertion). (3)
**logistic**: lateness OR unchanged (8.07/doubling); blob adds small independent OR 1.04/blob → blobs act
mostly *through* propagation lateness. (4) **relay-delay corrects the reviewer**: among survivors relay is only
~190ms later than local (not ~1s); low-blob modestly faster (42% vs 39% by 2s) → the solid 2s lever is ePBS
shrinking the block, not the relay-second. (5) **Nimbus confound test**: build-path dominates (local ~5–10×
relay for every client); Nimbus self-builds at the same 14% as others and stays worst in BOTH strata (vs LH
local p≈5e-3) → not a build-path artifact, but operator-mix/blockprint-error still apply. (6) **growing blocks**
(bytes 106→170 KB, +60%) track the rising reorg rate and *increase* the ePBS relief — pro-thesis.
**Article:** new "it's the blobs" hypothesis section; 2s recalibrated as current-regime worst-case; Nimbus
confound resolved in-text; growing-blocks tied to the trend; levers added (EIP-7872 max-blobs, EIP-8146 BAL
deadline, no-fork coordinated release); facts corrected (relay "~1s" → ~190ms median; BAL-deadline = EIP-8146
not 7928; no "90%"). 4,689 words, numeric gate ALL PASS (17 new checks), 0 names, figs 1–15 resolve.
