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
| `collect_classes.py` | Runs on the benchmark host: splits every test at one second and emits the class summaries, per-category membership, the family x mode taxonomy inside the long class, and the same summary at 0.5/1/2 s. |
| `collect_bottommost.py` | Runs on the benchmark host: folds the bottommost-compaction rounds (idle I/O, boot compaction reasons, the settled-store re-measurement and the per-CF attribution) into `data/report_data.json` under `bottommost`. |
| `report_svg.py` | Inline-SVG primitives (scales, axes, dots, lines, bands). Has its own self-check. |
| `crt_theme.py` | The site stylesheet, byte-identical to the sibling reports, kept in one place so the three cannot drift apart. |
| `data/report_data.json` | Every value the report renders. The only input to the generator. |
| `figures/fig_*.svg` | The thirteen charts as standalone files, site palette derived from `crt_theme.CSS` so a figure cannot disagree with how it renders in the page. |

- The carry-over ceiling: `container-recreate` restarts the client per test, so setup starts
  fully cold and anything the measured step gets free must have been put in the client's memory
  by setup - bounded by setup's reads (31.5 MB) plus its writes (0.0 MB, the control payload
  changes no state). Against a 104.5 MB gap that caps cache carry-over at 30%, independent of
  which cache holds the bytes. The harness flush itself is correct: `executor.go` drops between
  setup and test with a `sync` first, so the page cache is genuinely cold.
- Experiment B1 re-ran the 266-test subset on both arms with the flat DB block cache cut
  1 GiB -> 8 MiB (`collect_b1.py` folds the result into `data/report_data.json` under
  `cache_experiment`). The pre-registered prediction - control moving to 0.85-0.95 - was
  falsified: control moved +3.0% to 0.707 and every account category moved under 0.9%. Cache
  carry-over is therefore eliminated as the cause of the control gap, and the parity result is
  shown to survive a 128x cache reduction.

- **Second mechanism, found by intervention: the JIT.** The harness restarts the client per
  test, and state-actor's fixtures spend the process's first ~240 ms on an empty
  fork-activation block while jochemnet's spend it executing 535k gas of EVM work. So
  jochemnet's interpreter is promoted to optimised code before its measured block and
  state-actor's is not. Per-thread CPU sampling (`/proc`, 0.5 s) shows the .NET tiering thread
  taking a third to a half of all measured-step CPU on *both* arms. Equalising it with
  `DOTNET_TieredCompilation=0` moves the control tests 0.726 -> 1.143, DIFF_MAX
  code-exec 0.642 -> 0.944 (jochemnet *slows* 9.7 -> 13.6 s), and the
  sub-second categories run 5-6x faster on both arms. `collect_jit.py` folds all of it into
  `data/report_data.json` under `jit_experiment`.
- **Third mechanism, also killed by intervention: the store made the client rewrite it.** Boot
  the client on state-actor, drop caches, issue *zero* queries, and its own `/proc/<pid>/io`
  shows 1,962 MB read in 60 s against jochemnet's 0, on `rocksdb:low`, with every thread at 0%
  CPU. The event log gives the reason: 14 jobs at boot, all `StateNodes`, all
  `BottommostFiles` — RocksDB rewriting bottom-level files to zero their sequence numbers. The
  generator's finishing `CompactRange` ran with the default
  `bottommost_level_compaction=kIfHaveCompactionFilter` and no filter configured, so RocksDB
  *moved* the flushed L0 files into the empty bottom level instead of rewriting them: flat tree,
  `pending-compaction-bytes = 0`, every file still carrying `largest_seqno != 0`. Since the
  harness restarts the client per test, the job restarted for all 1,463 tests and never
  finished. Forcing the bottommost rewrite (`StateNodes` 603→207 files in 422 s,
  `StorageNodes` 1,211→1,126 in 2,114 s) takes the idle client to 0 MB and 0 jobs. Fixed
  upstream in [state-actor#139](https://github.com/ethereum/state-actor/pull/139), which
  repairs the same call in the Besu, ethrex and reth writers too. **It moved DIFF_MAX
  code-exec by +0.007**, against a replica-to-replica swing of 0.005 on the same cell.
- **Two smaller store defects, same family, found earlier.** The generator's finishing
  `CompactRange` also left state-actor's Account CF at L3:92 (23.7 GB) and both arms' code
  databases compaction-pending; RocksDB writes manual-compaction output into the deepest level
  that already holds files unless given `change_level` plus a target level. Settling them
  changed throughput by nothing measurable.
- **Per-CF read attribution, re-measured on the settled store** (`collect_bottommost.py` ->
  `bottommost`). Every read volume collected before the fix was inflated in proportion to test
  duration, because a ~33 MB/s background scan deposits more bytes into a longer window and the
  distinct-contract tests are the longest. Re-run quiet: non-code access is byte-for-byte alike
  (19.3 MB from `flat/Account` against jochemnet's 16.2 MB across its whole datadir, trie
  families 0.0 MB down from 689), while a distinct maximum-size contract per access costs
  2,821 MB against 1,671 MB over six matched pairs per arm — 1.69× the bytes, essentially all
  of it the code database, with `flat/Account` flat (−1.0 MB) and the trie families still at
  zero (−0.1 MB).
- **Reproducibility floor, measured at last.** Same store, same config, twice:
  100/133 tests within +/-10% overall, 39% for tests under 0.2 s against
  97% for tests over 5 s (`collect_noise.py` -> `noise`). An earlier version of the page
  ranked the twelve most divergent tests; all twelve ran under 0.2 s, so that table ranked
  noise and is gone.

## Regenerate

```
python3 gen_nethermind_state_db_report.py   # writes the html and the thirteen svgs
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
ladder, the two-term residual model, the Besu reference figures quoted in the cross-client
table, the duration classification (that the two classes separate, that the short class does
not beat its own replica floor, that the long class is at parity, that the conclusion survives
moving the boundary to 0.5 s and 2 s, that the four noise categories stay wholly sub-second, that
the storage category keeps straddling the line, and that the account-row/code-loading split still
localises the residual), the block-tenancy cross-check (that the sibling study's simulation
and its DIFF_MAX cell point the same way) and the closing figure (that the residual pair are the
only cells below 0.97 and every other cell is inside the band), and the bottommost-compaction result (that the idle client read the store, that
settling it silenced the client, that the reason field still says `BottommostFiles`, that
the flat read path stays byte-identical across the arms, and that settling did *not* move
DIFF_MAX or JUMPDEST - the section is written around that null result, so a future run in
which it does move must fail the build rather than keep the prose). Mutating any of those inputs makes generation fail rather than quietly print a
sentence the data no longer supports.

## Findings

- **Two populations, and only one of them can carry a claim.** Split every test at one second
  (membership fixed once from the reference arm, so rows do not change population between
  columns): 676 tests under, 785 over. After treatment the short class sits at 0.767 with 18%
  inside +/-10%, against a floor of 49% when the *same* store is measured twice - it does not
  beat its own noise. The long class sits at 0.978 with 83% inside, floor 97%. Every
  category still far from parity is wholly short: CONTROL (440 tests, 0.12 s, 0.708), sload_same_key
  (0.812), warm query (0.896), absent account (0.904). The boundary is not doing the work - the long
  class reads 0.979/0.978/0.977 at 0.5/1/2 s - and the storage category, which straddles it, reads 1.468 below a
  second and 1.007 above it on the same pair of stores.
- **The residual has a mechanism: block tenancy.** Both writers key code by hash (verified in
  the generator), so a contract's neighbours in a data block are random, and what differs is
  who they are: the snapshot holds 2.4M code entries averaging 7.6 KB, the generated store 134M
  averaging 358 B, almost all 23-byte stubs. The Besu study's block-packing simulation on each
  store's own records puts the block that must be read to fetch one fixture contract at
  10,718 bytes on the generated store against 5,912 on the snapshot (1.81x per fetch, the stubs do not
  compress), bracketing the 1.69x marginal measured here; the same cell on Besu reads 0.831
  against 0.944 for the reused contract. The isolated cold probe measures one block and cannot
  see it. Decisive test: rebuild the generated code CF with large values isolated in their own
  blocks and re-run the cell. Folded into `data/report_data.json` under
  `measured.besu_cross_check`, derived from the sibling study's data at collect time.
- **Where it stands.** Every long-class cell after all four findings, `classes.final_cells`:
  12 of 12 inside +/-10%; DIFF_MAX code-exec 0.938 and JUMPDEST code-exec 0.943 reproduce to
  within 0.01 across three runs of the same configuration.
- **Inside the long class the residual is one square.** Opcodes that only read the account row
  (BALANCE, EXTCODEHASH) are at 0.971-0.977 under every access mode, reading at most 1.06x the
  bytes. Opcodes that load the callee's code match them while the contract is reused (0.980), fall
  to 0.926 when the code is scanned for jump destinations, and to 0.642 when every access touches a
  distinct maximum-size contract - where they read 1.48x the bytes. Throughput tracks bytes.

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
- `EXISTING_CONTRACT_DIFF_MAX` is the one cell that stays out, and it localises to a single
  square of a 2×2: opcodes that **load the callee's code** against a **different contract each
  access** sit at 0.640, while the same opcodes reusing one contract are at 0.983 and the two
  opcodes that only read the account row (BALANCE, EXTCODEHASH) are at 0.97. So it is neither
  distinctness on its own nor the account row.
- **The code-database explanation for that cell is refuted**, and the article says so. Reading
  code is cheaper on the generated store at every granularity we can measure: 10,513 B/196 µs
  against 14,208 B/346 µs for a cold random lookup, 4,186 B/read against 9,705 for a cold sweep
  of 3,000 distinct maximum-size contracts, and the two stores hold the same number of
  maximum-size contracts (442 vs 433 per 400k accounts). The cell is reported as open.
- What remains is a fixed ~179 MB per-test read on the generated store plus a ~10% proportional
  term, which is why tests that do no account work sit at 0.71 while tests reading gigabytes sit
  at parity. Part of it is a **harness defect**: the page cache is dropped between the setup and
  measured steps but the client is not restarted, so Nethermind's own RocksDB block cache carries
  over. The arms invert across the steps — jochemnet reads 31.5 MB in setup and 1.8 MB when
  measured, state-actor 9.4 MB then 96.1 MB. Diagnosed, not fixed: every number here still
  carries it. Client startup, trie placement and measurement-window asymmetry are ruled out.
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
