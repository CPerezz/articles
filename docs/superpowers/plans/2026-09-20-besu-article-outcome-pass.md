# Besu article: surface the outcome, add the bookend figure, cut the obsolete hedges

## Why

The rerun is done and every prediction held. But the article still reads as a diagnosis that
happens to have an appendix. Measured, not asserted:

- 5,769 words, 8 figures.
- The payoff, `Where this stands` (574w), is an **h3 buried under `The residual`**, reached after
  roughly 4,900 words, and it is the only major section with **no figure**.
- Two sections now hedge questions the rerun answered.

So this pass makes the article shorter, not longer, and moves the interesting part forward.

## What changes

### 1. Add one figure: the bookend

A 48-category dumbbell, **v1 to v3**, log scale, parity band. Same visual grammar as the opening
`ratio_dots` and the existing `verdict` dumbbell, so it reads as the closing bracket on figure 1.
Lands in the outcome section, which has no figure today.

It must not be captioned "everything aligned", because that is not what happened. 32 of 48
categories converge into the band; the 16 distinct-code categories **shoot past it** to 1.461.
Two fixes landing and one overcorrecting, visible in one glance, is both the honest picture and
the more interesting one.

### 2. Promote the outcome

`Where this stands`: h3 to **h2**, lifted out of `The residual`. No new words. The payoff stops
being a footnote to a subsection.

### 3. Cut about 350 words

- **Delete `What this does not separate`** (189w). It hedges that part of the code-class penalty
  "may also be filter absence rather than the record geometry of the next section". The rerun
  separates them: absence went to 1.002 while the code classes moved independently. One clause in
  the outcome carries what is left.
- **Shrink `The same experiment on two clients`** from 246w to about 80w. Cross-client
  determinism is no longer an argument to make. The twin proved it: identical state roots at
  350 GB, and a geth-filled payload bundle drove the Besu arm. State it, stop arguing it.

### 4. Add one sentence

The open item: the corpus fix, now carrying throughput evidence (1.461, climbing monotonically
1.364 to 1.512 across the eleven budgets) rather than a store-level model.

## What does not change

- **The h1 keeps its 8x.** It is the question the article answers, and a title that spoils its
  own answer is weaker. `build_site.py` also guards the landing card's factor against the
  report's `<h1>`, so the two move together or not at all. Not moving them.
- **The body stays.** The WAL and pre-run investigation (1,123w, 3 figures) is the evidence chain
  every other number rests on. It earns its length.
- No new data. `report_data.json` already carries the `status.v3` block.

## Verification

- `python3 gen_besu_state_db_report.py` passes every oracle, including the v3 ones added in the
  last pass (canary within 0.013 and flat within 0.02, absence at parity, distinct-code inverted
  and its inversion growing with the budget, 660/440 grid, zero failing executions).
- New figure written as a standalone SVG, fetch-free, and rendering dark on its own.
- Numeric non-regression: extract every number from the entity-decoded page and diff the multiset
  against the current build. Expect removals only from the deleted hedge section; expect no
  unrelated computed value to move.
- No dash reaches the page: the generator already asserts on U+2014, U+2013, `&mdash;`, `&ndash;`.
- Word count drops by roughly 350.
- Published to `main`, then every asset verified byte-identical live with `curl`.

## Risks

- The new figure has 48 rows on a log scale with two dots each. The existing `verdict` chart is
  the same shape and fits, so the risk is crowding rather than correctness; if it cramps, drop to
  the 16 distinct-code plus 8 absence categories and say so in the caption.
- Deleting a section renumbers figure captions and TOC anchors. Expected, and the non-regression
  check is numeric rather than byte-level for exactly this reason.
- `collect_nethermind.py` has twice re-frozen the Besu reference it is supposed to derive. Not in
  scope here, but if that file is touched again in the same window, the generator assert added
  last pass should fail the build rather than publish a stale figure.
