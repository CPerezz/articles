# Nethermind state-DB divergence — benchmarkoor bloatnet runs

Why identical EEST bloatnet benchmarks reported a 17× throughput gap between two Nethermind
state databases: `jochemnet` (a mainnet shadowfork snapshot at block 24,402,727, plus a
7,736-block pre-run promoted into the golden image) and `state-actor` (synthetically generated
state). The gap is a placement artifact. Equalise placement and every category that reads state
returns to parity.

This is the third client in the series, after the geth and Besu studies in sibling folders.
Everything needed to reproduce or re-cut the analysis lives here.

## Preconditions

Neither of these is discussed in the article — it starts from a pair where both already hold —
but both have to be true before a run means anything, so they are recorded here for anyone
reproducing it.

**Both arms must read through the flat backend.** Nethermind picks its state backend at startup
by looking for a flat database. A generated store written without the flat layout is served as
`patricia (flat DB disabled)` while the snapshot is served as `flat (existing flat DB detected)`
— two different read paths, so nothing measured across such a pair compares the databases. The
study begins once the generated store has been rebuilt from a `state-actor` revision that writes
the flat layout, which relocates the trie into `flat/` and leaves `state/` at 160 KB. Nothing
measured before that point is quoted, and `gen_nethermind_state_db_report.py` asserts both arm
run ids so the page cannot be built from a pre-rebuild run.

**The Amsterdam EIP list must match the other clients.** geth and Besu activate Amsterdam by
name and take whatever their build considers Amsterdam to be; Nethermind activates exactly the
EIPs you enumerate. benchmarkoor ships two sets, and the shorter 9-EIP one makes
Nethermind compute a different block access list — every payload comes back `INVALID` with a BAL
hash mismatch. Use the `existing-snapshot` family's 14-EIP set, which adds
7997, 8037, 8038, 8246, 8282; that reproduces what the other two clients get for free.

## Layout

| Path | What |
|---|---|
| `nethermind-state-db-report.html` | The deliverable. Zero JS, single file. Only external fetches are the site's Google-Font stylesheets (degrades to system monospace offline). |
| `gen_nethermind_state_db_report.py` | Prose, computations, and HTML/SVG emission. Python 3 stdlib only. |
| `collect_nethermind.py` | Runs on the benchmark host: reduces four benchmarkoor result trees to `data/report_data.json`. |
| `report_svg.py` | Inline-SVG primitives (scales, axes, dots, lines, bands). Has its own self-check. |
| `crt_theme.py` | The site stylesheet, byte-identical to the sibling reports, kept in one place so the three cannot drift apart. |
| `data/report_data.json` | Every value the report renders. The only input to the generator. |
| `figures/fig_*.svg` | The seven charts as standalone files, site palette derived from `crt_theme.CSS` so a figure cannot disagree with how it renders in the page. |

## Regenerate

```
python3 gen_nethermind_state_db_report.py   # writes the html and the five svgs
python3 report_svg.py                       # primitive self-check, prints "report_svg selfcheck ok"
```

Paths resolve relative to the script, so the cwd does not matter. To re-derive the data, run
`collect_nethermind.py` on the benchmark host (it reads `/bench/results/nm-*`) and copy its
stdout over `data/report_data.json`.

## Reading the output

Expected stdout, all asserted: `headline factor: 17.1x`, `agreement: 12.8% -> 53.0%`,
five categories at parity after treatment, and a monotonic `code ladder`.

**The generator refuses to emit the page if the data stops supporting the prose.** The oracles in
`main()` cover the scope precondition (both arms on the flat backend, by run id), the headline
factor, per-category parity after treatment, the two pre-existing parity controls, the
random-key inversion the argument depends on, the amortisation shape (parity at low N,
saturation at high N), per-category dispersion (that `EXISTING_EOA` stays tight and that the
storage category stays wide), that the worst individual tests are still dominated by controls,
that DIFF_MAX remains the outlying column of the opcode grid, the monotonicity of the code
ladder, the two-term residual model, and the Besu reference figures quoted in the cross-client
table. Mutating any of those inputs makes generation fail rather than quietly print a
sentence the data no longer supports.

## Findings

- The 17× gap is **where the rows sit**, not what they contain. Only one arm runs a pre-run, and
  `promote_post_pre_runs: true` freezes the post-pre-run layout into the image every test is
  restored from, leaving the benchmark's keys as the newest versions in the youngest files.
- It is not caching. The harness drops the page cache between every test; the advantage is on
  disk, and the amortisation curve shows jochemnet's read volume *saturating* at 47 MB while
  state-actor's grows linearly to 404 MB over the same lookups.
- On keys sampled from each store's own account family, jochemnet is the **more expensive** store
  (2.51 vs 1.99 blocks per lookup). The inversion is what rules out "the generated store is
  simply worse".
- Merging the affected column families down and stripping the pre-run brings every state-reading
  category to parity: existing accounts within 2–3%, storage within 3%, ether transfers within
  2%, absent accounts within 10%. Tests agreeing within ±10% go from 12.8% to 53.0%.
- `EXISTING_CONTRACT_DIFF_MAX` is the one cell that stays out, at 1.55× bytes, and it is a code
  database effect: 45 GB on the generated store against 7.6 GB on the snapshot. The residual is
  monotonic in how much contract code the access mode touches. The geth study flagged the same
  cell without explaining it.
- What remains is a fixed ~179 MB per-test read on the generated store plus a ~10% proportional
  term, which is why tests that do no account work sit at 0.71 while tests reading gigabytes sit
  at parity. Client startup, trie placement and measurement-window asymmetry are all ruled out;
  the origin is not yet pinned to a column family.
- Category medians are not the whole story, so the page carries dispersion as well: the
  `EXISTING_EOA` middle half is 0.970–0.991 with 108/110 tests inside ±10% of parity, whereas
  the storage category sits on parity at 1.034 while ranging 0.549–2.094 with only 47/88 inside
  it. `fig_ratio_dots` plots every one of the 1,461 tests, before and after.
- The 12 individual tests furthest from parity are 11 controls plus one absent-account test —
  they read 1–8 MB on the snapshot against 68–174 MB on the generated store, which is the
  additive term rather than anything about account access.
- `fig_grid` reads by column, not by row: every opcode behaves the same, and only the DIFF_MAX
  and JUMPDEST modes stay off parity, which is what makes the effect attributable to code
  rather than to any opcode.
- Consequence, and the same one the sibling studies reach: comparing a promoted-after-pre-run
  snapshot against a store that never got one measures preparation, not access cost.
