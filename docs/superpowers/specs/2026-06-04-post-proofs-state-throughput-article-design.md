# Article Design Spec — Post-Proofs State & Throughput

- **Date:** 2026-06-04
- **Venue:** ethresear.ch (Discourse forum; supports Markdown, uploaded images, code blocks; no native Mermaid rendering)
- **Type:** Vision + open-problem research post
- **Status:** Structure approved; pending spec review before drafting
- **Source:** `prompt.md` (author's raw dictation, transcription-corrected)

---

## 1. Goal & framing

A first-person research/vision post arguing that **mandatory execution proofs (L1 zkEVM) will collapse Ethereum's node taxonomy**, concentrating state into a few builders and professional RPC/archive operators, and that this forces (and enables) a re-architecture of how clients manage state. The article ties **state resilience** and **chain throughput** together through a single lever — making state's hot/cold structure explicit and economically priced — and ends on the **open problem** of how to price cold-state access without locking users out, posed for community feedback.

**Chosen framing:** vision + open problem (NOT a formal mechanism proposal). Existing EIPs (8188, 8057, 8038, 8037) are cited as *related work being built on*, not competitors.

## 2. Audience, venue, voice, length

- **Audience:** Ethereum core devs, EF researchers, sophisticated client/infra engineers. Expert — but define a term in a half-sentence when precision helps; do not over-explain basics.
- **Voice:** First person ("I expect…", "I'm convinced the direction is right, unsure of the mechanism"). Confident but cited. Hedge only where genuinely uncertain.
- **Attribution:** Credit **Toni Wahrstätter** explicitly in the open-problem section (the proof-discount discussion came out of conversations with him).
- **Length:** Long-form, ~2500–3500 words.
- **Open ending:** Pose the open problem crisply, sketch 2–3 candidate directions, then explicitly leave it open as a call for feedback.
- **Title candidates (author to pick / riff):** (1) *After the Proofs: State Resilience and Throughput in Ethereum's Post-zkEVM Node Ecosystem*; (2) *Who Keeps the State? Client Architecture and Scaling After Mandatory Proofs*; (3) *Marrying Throughput and State Management for the Nodes That Survive zkEVM*.

## 3. Thesis / through-line

> Mandatory proofs remove the need to hold state or re-execute in order to attest. That dissolves the incentive sustaining ~11–14k state-bearing nodes, **concentrating** state into a few builders + professional RPC/archive operators. Concentration creates two coupled problems — **resilience** (can ordinary users still reach their own state?) and **throughput** (how do the remaining heavy nodes scale?). One lever addresses both: make state's **hot/cold structure explicit and priced** (EIP-8188 + long-horizon cold-access repricing), which lets clients re-tier storage and lets builders safely push gas limits higher. The missing piece is the **access-discount mechanism** (user-supplied storage proofs) — directionally right, mechanically unsolved.

**Survives-skimming rule:** every section ends with a sentence that hands off to the next.

## 4. Claims ledger (accuracy contract for the draft)

The draft MUST honor these. Citations in §7.

### ✅ Confirmed — state with confidence
- FOCIL (EIP-7805) includers need only **account-level data (nonce/balance)** to build inclusion lists — no full state / no execution. A partial-state node suffices. FOCIL is the **Hegota** consensus-layer headliner (moved out of Glamsterdam).
- ePBS (EIP-7732) makes the **builder** construct *and execute* the payload; proposer only picks a bid; a Payload-Timeliness Committee attests. Heavy-builder / light-validator. ePBS is a **Glamsterdam** headliner.
- Erigon: flat files, staged sync, BitTorrent snapshot distribution (the Downloader), and split components/data across disks & machines. Good model for "multi-machine archive/RPC."
- Portal Network is the decentralized history/state serving layer (History network most mature; State network next priority, still in development).
- Stateless + executionless verification (verify a proof, don't re-execute) is the accurate end-state per ethereum.org statelessness roadmap.

### ⚠️ Corrected — old claim → corrected claim
- **Cold-state stat (UPDATED — Han's xatu-analysis is now the empirical core):** the author's ~~"80% of state goes cold in 30 days"~~ was a *real* statistic, **mislabeled**: it is ~80–88% of storage-**write gas** concentrated in the warm set, **not** 80% of state. Precise, source-backed framing (Ng, `xatu-analysis/state_access/REPORT.md`, static snapshot @ block 24,870,000 — **re-verify against the live repo at draft time, it updates**):
  - Storage slots **cold by trailing window**: 1d → **99.90% cold**; **30d → 97.04% cold (only 2.96% hot)**; 90d → 91.97% cold; 180d → 84.38% cold.
  - At a **30-day window the hot ~3% of slots absorb ~84.8% of storage-update gas → ~29× concentration**; the warm tier has captured **~80–88% of update gas every week post-Merge** (matured to a steady regime by 2024).
  - By write count at 30d: ~**10.2% of account writes** and ~**28.9% of storage writes** hit the cold tier (slot *creations* `0→nonzero` are always cold-priced).
  - **Han concludes ~30 days is the *efficient* Active-window** — higher W inflates the warm set for negligible extra coverage. So the 30-day cutoff is the *recommended* setting, not an error.
  - Live state @ snapshot: **~379.6M accounts, ~1.55B storage slots** → 30-day hot slot set ≈ 3% × 1.55B ≈ **~46M slots ≈ a few GB**.
  - Complementary long-horizon framings: EF "~80% of state untouched >1yr"; "Not All State Is Equal" ~63% of slots write-once. (State-fraction-by-age vs gas-concentration-by-window are different lenses on the same concentration — present both, don't conflate.)
  - **Caveat: writes only** (SSTORE `nonzero→nonzero`); **read concentration is unmeasured** — name this gap explicitly when arguing for cold-*access* (read) repricing.
  - Framing: the cutoff is a tunable knob **with a data-backed recommended setting (~30 days)**; lead with the **~29× gas-concentration** hook. "Small hot tier on fast storage, hottest slots RAM-plausible" — do NOT claim *all* hot state fits in RAM.
- **EIP-8188:** ~~"just marks last-write time; only an RLP change; harmless; ~1–2 GB; consensus team"~~ → title is **"State Tiering by Write Age"**; it adds `last_written_period` to account/slot RLP **and reprices writes** (Active vs Inactive tier; writes to Inactive cost more; **reads unchanged**); **~3.4 GB** overhead by its own estimate (~0.36 GB accounts + ~3.0 GB slots); authors are **EF research / execution-layer** (Wei Han Ng, Guillaume Ballet, Maria Silva, Gary Rong, Amirul Ashraf) — *not* "the consensus team"; it is a consensus-breaking gas change (don't call it "harmless," call it "low-risk relative to full state expiry"). Targeted at **Hegota**.
- **Node count:** ~~"~13,000 full nodes back up state"~~ → **~11–14k discoverable execution-layer nodes** (Etherscan ~11.9k; early-2026 ~14.3k), **mostly pruned, not archive/state-backups**.
- **"Validators have no incentive to hold state, no penalty"** → true for **attesters** post-mandatory-proofs only; **builders/proposers still need full state** (to build + prove); verifiers still need the **proof + public inputs + data availability** (a proof does not make data available); and this is a **future** regime, not today.

### 🔱 Distinctions to maintain (or a commenter will pounce)
- **ePBS ≠ mandatory proofs.** Separate tracks (ePBS = Glamsterdam/EIP-7732; mandatory proofs = zkEVM roadmap, currently *optional* via EIP-8025, mandatory is years out). They point the same way (heavy builder, light validator) but must be attributed separately.
- **History ≠ state.** History expiry (EIP-4444) + Portal History largely handle *history*; **state** resilience is the hard, separate problem this article is actually about.
- **Your idea vs EIP-8057.** EIP-8057 ("Inter-Block Temporal Locality Gas Discounts," **declined for Glamsterdam**) is a *short-horizon* recency discount (decays over ~32 blocks ≈ caching). The article's idea is the *~30-day write-age window* (≈ storage tiering, per Han's efficient operating point) — same "recently-touched is cheaper" intuition, but ~6,500× longer and aimed at disk-tiering, not block-level caching. Cite 8057, distinguish the horizon, argue the ~30-day version is what unlocks the re-architecture.

### Supporting facts (for color / grounding)
- zkEVM real-time proving targets: proof ≤10s for P99 of blocks; <$100k capex; ≤10kW; proof <300 KiB; 128-bit security (100-bit min at launch). Roadmap tiers: **optional → adoption → mandatory** (mandatory lets gas limits rise; enables native zk-rollups via an `EXECUTE` precompile).
- Gas limit history: 30M→36M (Feb 2025), 36M→45M (~Jul 2025), 45M→60M (late 2025, pre-Fusaka). **Current ≈ 60M.** Public discussion eyes 100M+ (aspirations cited to ~150–200M).
- **Gas-limit ↔ warm-set coupling (Han):** raising the gas limit *inflates* the warm (active) set a tiering scheme must keep cheap — BUT empirically the warm set grows **sub-proportionally**: access intensity fell ~29% (9.74 → 7.99 → 6.94 slots per million gas at W=30d, 2023→2024→2026), i.e. each gas increment buys diminishing extra warm state. Use this as an honest tension in Part 2d, not a hidden weakness.
- Glamsterdam (consensus "Gloas" + execution "Amsterdam"): headliners ePBS (7732) + Block-Level Access Lists (7928) + gas-repricing workstream (meta EIP-8007). Timing slipping toward H2 2026. Repricing EIPs: **8037 "State Creation Gas Cost Increase" (scheduled/SFI)**, **8038 "State-access gas cost update" (considered/CFI)**, **7904 "Compute Gas Cost Increase" (CFI)**.
- Hegota: post-Glamsterdam fork, late 2026 / 2027; framed as censorship-resistance + cleanup/hardening; FOCIL headliner; EIP-8188 aimed here.

## 5. Section-by-section outline

**TL;DR** (4 sentences): proofs collapse the node taxonomy → state concentrates → two coupled problems (resilience, throughput) → one lever (explicit, priced hot/cold state) → access-discount is the open problem.

**Intro / thesis (~250w).** Mandatory proofs are coming (optional→adoption→mandatory; cite zkEVM roadmap, real-time-proving targets, EIP-8025 as today's optional step; flag mandatory is years out). State the thesis (§3). Promise the open problem at the end.

**Part 1 — The node taxonomy after mandatory proofs (~900w).**
1. *Trigger:* stateless + executionless verification — attesters verify a proof, shed hardware, no penalty. **Caveat:** attester path only; builders/proposers still need state; verifiers need proof + public inputs + DA.
2. *zkEVM/stateless validators* — the big migration of stake.
3. *RPC & archive nodes* — **more** important: higher gas limits pile on load + state growth; must re-execute fast enough to hold tip, scale horizontally (Erigon model), get smarter about state layout. ← hook into Part 2.
4. *Full nodes* — fade to a rare entity (re-execute/serve state when unneeded; niche = solo/unsophisticated builders).
5. *Partial-stateful nodes* — proliferating replacement; natural home for FOCIL includers (account data only); censorship-resistance counterweight to concentration.
6. *Consequence:* client teams specialize per role; state concentrates → sets up Part 2's tension.
- 🖼️ Figure A (AI): before/after node taxonomy.

**Part 2 — Marrying throughput & state management (~1100w).**
- *Reframe:* chain preservation = solving state growth, the last big pre-ossification problem. Two coupled needs:
- **2a. Resilience layer** — decentralized, deliberately-slow-but-resilient cold-state serving fallback (Portal State network, Erigon torrents). **Distinguish history from state.** Imperative: as simple as possible or it never ships.
- **2b. Enabling signal — EIP-8188** (State Tiering by Write Age, Hegota): `last_written_period` in RLP + write repricing by tier; ~3.4 GB overhead; the protocol-level hot/cold signal clients need.
- **2c. Signal → throughput — cold-*access* repricing on a ~30-day window:** Han's xatu-analysis is the empirical core: at a **30-day window only ~3% of storage slots are hot, yet absorb ~85% of storage-update gas (~29× concentration)**; the warm tier has captured ~80–88% of update gas every week post-Merge; Han argues **~30 days is the efficient active-window**. So pricing access by write-age on a ~30-day window — **still vastly longer than EIP-8057's ~32-block (~6 min) caching horizon** — lets clients tier storage: keep the small (~few-GB) warm set on fast media, push the cold ~97% to cheap disk / other machines over fast links. **Caveat: Han measures writes; read concentration is unmeasured — name the gap.** Position vs EIP-8057 (short-horizon recency discount, declined for Glamsterdam), EIP-8038 (flat cold-access bump, CFI), EIP-8037 (state-creation cost, scheduled). **[Han's charts + the by-window table slot in here.]**
- **2d. Why this buys throughput:** post-proofs only the **builder** or the **RPC** can be "crashed"; chain stalls only if the builder can't produce block+proof. Guarantee builders worst-case cold access is expensive ⇒ they optimize the hot path with confidence ⇒ bigger blocks ⇒ higher gas limits. (ePBS makes the builder heavy; **ePBS ≠ mandatory proofs**. BAL/7928 = complementary hot-path tooling.) **Honest tension (Han):** higher gas limits inflate the warm set clients must keep fast — but the warm set grows sub-proportionally (access intensity fell ~29%, 2023→2026), so each increment buys diminishing extra warm state. Surface this, don't bury it.
- 🖼️ Figure B (AI): hot/cold storage-tiering architecture.

**Part 3 — Open problem: pricing cold access without locking people out (~700w).**
1. *Hazard:* too high → strand legitimate old state ("$50 in an old wallet" case); too low → reopen DoS surface.
2. *Natural fix:* transactor attaches a **storage proof**; node verifies vs state root, skips the cold fetch (builder and RPC).
3. *The catch (open problem):* a **consensus-recognized discount** requires consensus to agree the proof was supplied ⇒ proofs ride in tx + block ⇒ many cold-touching txs ⇒ proof/block bloat & propagation cost (acute under MPT, better under binary tree EIP-7864). The builder you just optimized now eats proof propagation.
4. *Candidate directions (sketched, unsolved):* (a) proof aggregation / recursive SNARK-of-proofs → one succinct proof per block; (b) fold into BAL (7928) so the witness is already in the block format; (c) cheaper witnesses post-binary-tree (7864); (d) a proof **DA sidecar** (blob-like) so proofs don't bloat the execution block; (e) discount only when avoided-fetch cost > proof-propagation cost. **Credit Toni Wahrstätter.**
5. *Close:* convinced of the direction, unsure of the mechanism — call for feedback.
- 🖼️ Figure C (AI): block carrying cold-access proofs + the bloat tradeoff.

**Closing (~150w)** + **References** (all EIPs/sources, §7).

## 6. Figures

**User-supplied:** the cold-state data charts from Wei Han Ng's "Not All State Is Equal" (write-once slot %, activity-span distributions). Slot in **Part 2c**.

**AI-generated concept figures.** Note: text/image models garble embedded labels — keep AI images *conceptual*, add precise labels in post (or build the structural version in a diagram tool). Style for all three: clean schematic/technical illustration, flat vector, limited palette, **warm/amber = hot state, cool/blue = cold state**, white or dark background, minimal text, isometric or top-down.

- **Figure A — Node taxonomy, before → after mandatory proofs.**
  Prompt: *"Clean flat-vector technical diagram, two panels side by side labeled 'before' and 'after'. Left panel: a large dense uniform cloud of many small identical server icons (representing thousands of full nodes), plus a few server-stack clusters. Right panel: a vast field of tiny faint featureless dots (stateless validators) in cool blue, a few large prominent glowing amber server towers (builders, each holding a bright core), one cluster of tall server stacks (RPC/archive), and a scattering of medium half-filled nodes (partial-stateful). Subtle migration arrows from the left cloud toward the tiny-dots field. Isometric, muted palette, lots of negative space, no readable text."* Add labels afterward.

- **Figure B — Hot/cold storage tiering inside a heavy node.**
  Prompt: *"Clean flat-vector isometric illustration of a single high-performance server. At its center, a small bright glowing amber cube labeled-by-color as 'hot' sitting on a fast chip/RAM module, tightly coupled to a CPU/EVM execution unit. Surrounding it at a distance, a large dim blue archive of stacked disk drives (cheap storage), connected to the hot core by a thin fast network link. Visual contrast: small + bright + close (hot) vs large + dim + far (cold). Technical, schematic, minimal text, dark background, amber-and-blue palette."* Add labels afterward.

- **Figure C — Block carrying cold-access proofs (bloat tradeoff).**
  Prompt: *"Clean flat-vector technical illustration comparing two blocks. Left: a small tidy rectangular block containing a few transaction rows, light and compact. Right: the same block visibly bloated and heavy, each cold-touching transaction dragging an attached chunky 'proof' brick, the block straining/oversized, with network-propagation strain lines radiating outward. Convey 'proofs make blocks heavy.' Isometric, amber transactions, blue proof bricks, minimal text, white background."* Add labels afterward.

## 7. References (with URLs)

**Proofs / statelessness / zkEVM**
- Real-time proving (EF, Jul 2025): https://blog.ethereum.org/en/2025/07/10/realtime-proving
- L1 zkEVM roadmap 2026 (EthMagicians): https://ethereum-magicians.org/t/l1-zkevm-roadmap-2026-integrating-zkevm-proofs-into-ethereums-core-protocol/27595
- EF zkEVM site: https://zkevm.ethereum.foundation/
- Statelessness roadmap: https://ethereum.org/roadmap/statelessness/

**Forks / scheduling**
- EIP-7773 Glamsterdam hardfork meta: https://eips.ethereum.org/EIPS/eip-7773
- ethereum.org Glamsterdam: https://ethereum.org/roadmap/glamsterdam/
- EF Checkpoint #9 (Apr 2026): https://blog.ethereum.org/2026/04/10/checkpoint-9
- EF Checkpoint #8 (Jan 2026): https://blog.ethereum.org/en/2026/01/20/checkpoint-8
- Hegota naming (The Block): https://www.theblock.co/post/383275/ethereum-developers-name-post-glamsterdam-upgrade-hegota-as-2026-roadmap-takes-shape
- FOCIL → Hegota (DL News): https://www.dlnews.com/articles/defi/ethereum-devs-confirm-focil-proposal-for-hegota-upgrade/

**EIPs**
- EIP-7732 ePBS: https://eips.ethereum.org/EIPS/eip-7732
- EIP-7805 FOCIL: https://eips.ethereum.org/EIPS/eip-7805
- EIP-7928 Block-Level Access Lists: https://eips.ethereum.org/EIPS/eip-7928
- EIP-8007 Glamsterdam Gas Repricings (meta): https://eips.ethereum.org/EIPS/eip-8007
- EIP-8037 State Creation Gas Cost Increase: https://eips.ethereum.org/EIPS/eip-8037
- EIP-8038 State-access gas cost update: https://eips.ethereum.org/EIPS/eip-8038
- EIP-7904 Compute Gas Cost Increase: https://eips.ethereum.org/EIPS/eip-7904
- EIP-8057 Inter-Block Temporal Locality Gas Discounts: https://eips.ethereum.org/EIPS/eip-8057
- EIP-8188 State Tiering by Write Age: https://eips.ethereum.org/EIPS/eip-8188
- EIP-7736 Leaf-level state expiry: https://eips.ethereum.org/EIPS/eip-7736
- EIP-7864 Unified binary tree: https://eips.ethereum.org/EIPS/eip-7864
- EIP-8025 optional execution proofs (verify exact title/number at draft time): https://eips.ethereum.org/EIPS/eip-8025

**State data**
- EF "Future of State" (Dec 2025): https://blog.ethereum.org/en/2025/12/16/future-of-state
- Ng, "Not All State Is Equal" (Sep 2025): https://ethereum-magicians.org/t/not-all-state-is-equal/25508
- Ng, xatu-analysis state-access REPORT (hot/cold by window; gas concentration; writes-only): https://github.com/weiihann/xatu-analysis/blob/main/state_access/REPORT.md
- ACDE #237 (Hegota / EIP-8188 coverage): https://christinedkim.substack.com/p/acde-237

**Infra**
- Erigon — why: https://docs.erigon.tech/get-started/readme/why-using-erigon
- Erigon — Downloader (torrents): https://docs.erigon.tech/fundamentals/modules/downloader
- Erigon — multiple instances: https://docs.erigon.tech/fundamentals/multiple-instances
- Portal Network overview: https://ethportal.net/overview
- Node trackers: https://etherscan.io/nodetracker , https://ethernodes.org/

## 8. Drafting guidelines

- Open with TL;DR; end with References (linked).
- First person; confident-but-cited; hedge only on genuine unknowns.
- Honor the Claims Ledger (§4) exactly — especially the corrected stats and the three distinctions.
- Treat the hot/cold cutoff as a tunable knob with a **data-backed recommended setting (~30 days, per Han)**; lead with the **~29× gas-concentration** hook, not a fraction-of-state number.
- When arguing cold-*access* (read) repricing, explicitly note Han's data is **writes-only**; read concentration is unmeasured (a data gap worth naming, not hiding).
- Credit Toni Wahrstätter in Part 3.
- Link EIPs inline on first mention.
- Keep figures conceptual; mark `[Figure A/B/C]` and `[Han's chart]` placeholders in the draft.
- Target 2500–3500 words.
