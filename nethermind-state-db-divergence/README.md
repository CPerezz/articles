# Nethermind state-DB divergence — benchmarkoor bloatnet runs

Why identical EEST bloatnet benchmarks reported a 17× throughput gap between two Nethermind
state databases: `jochemnet` (a mainnet shadowfork snapshot at block 24,402,727, plus a
7,736-block pre-run promoted into the golden image) and `state-actor` (synthetically generated
state). Five mechanisms, each fixed and measured on its own. With all five fixed, tests over a
second sit at 1.012 (122 of 144 within ±10%, against 138 when one store is measured twice);
tests under a second can't be read at any store shape.

This is the third client in the series, after the geth and Besu studies in sibling folders.
Everything needed to reproduce or re-cut the analysis lives here. The page was rewritten
around the five findings; the long version, with every round, is at `af41b3f` in git history,
and what it carried beyond the short one is kept below under [Study history](#study-history).

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
| `gen_nethermind_state_db_report.py` | Prose, computations, oracles, and HTML/SVG emission. Python 3 stdlib only. |
| `collect_nethermind.py` | Runs on the benchmark host: reduces the first four benchmarkoor result trees (the 1,461-test sweep before and after compacting the pre-run) to `data/report_data.json`. |
| `collect_classes.py` | Splits every test at one second and emits the class summaries, per-category membership, the family × mode taxonomy inside the long class, and the same summary at 0.5/1/2 s. Under `classes`. |
| `collect_noise.py` | The same store measured twice: the reproducibility floor. Under `noise`. |
| `collect_b1.py` | Experiment B1, the flat DB block cache cut 1 GiB → 8 MiB on both arms. Under `cache_experiment`. |
| `collect_jit.py` | The tiered-JIT A/B, the parallel-execution ablation and the per-thread CPU profiles (Finding 2). Under `jit_experiment`. |
| `collect_bottommost.py` | The bottommost-compaction rounds: idle I/O, boot compaction reasons, the settled-store re-measurement and the per-CF attribution (Finding 3). Under `bottommost`. |
| `collect_v2.py` | Round 66 (top-of-trie packing, its two-direction swap, file-number provenance) and round 67 (the store regenerated with #141's pool, its fixtures, the long-class re-measurement). Under `topnodes` and `v2`. |
| `sstprops.py` | Reads every SST's table properties straight from the file footer (no RocksDB needed): column family, entries, data blocks, bytes per block, filter size, compression, creation time, writing host. |
| `collect_r68.py` | Re-measures the tests still outside ±10% as a fresh same-session pair with per-column pread accounting. Under `outliers`. |
| `collect_storage.py` | Rounds 69-73: the two storage columns' level shapes before and after their compactions, the sstore cells at four stages with their per-column reads, the absent-account transfer's per-thread CPU, and the two warming ablations (Finding 5 and what's left). Under `storage`. |
| `collect_final.py` | The final pair (whole suite at 160M/240M, one session, state-actor twice) per duration class, per category, and every test outside the band in both runs. Under `final`. |
| `collect_waterfall.py` | The same 266 test ids through every stage, by family and duration class, with membership fixed from the final jochemnet run. Under `waterfall`. |
| `report_svg.py` | Inline-SVG primitives (scales, axes, dots, lines, bands). Has its own self-check. |
| `crt_theme.py` | The site stylesheet, byte-identical to the sibling reports, kept in one place so the three cannot drift apart. |
| `data/report_data.json` | Every value the report renders. The only input to the generator. |
| `figures/fig_*.svg` | The eleven charts as standalone files, site palette derived from `crt_theme.CSS` so a figure cannot disagree with how it renders in the page. |

Every `collect_*.py` runs on the benchmark host against `/bench/results/nm-*` and prints JSON
to stdout; merge it into `data/report_data.json` under the key named above.

## Regenerate

```
python3 gen_nethermind_state_db_report.py   # writes the html and the eleven svgs
python3 report_svg.py                       # primitive self-check, prints "report_svg selfcheck ok"
```

Paths resolve relative to the script, so the cwd does not matter.

## Reading the output

Expected stdout:

```
headline factor: 17.1x
long class: baseline 0.175 -> final 1.012 (122/144 in band)
short class: baseline 0.790 -> final 1.150 (40/122 in band)
```

**The generator refuses to emit the page if the data stops supporting the prose.** The oracles
in `main()` hold, in page order: the scope (both arms on the flat backend, by run id); the
headline factor and the sweep's before/after agreement; the waterfall's integrity (membership
matches the final pair's classes, write families carry no intermediate stage, the code-pool stage
covers no short class); the baseline's shape (account and code families far below parity,
storage at it); each finding's isolated before/after, including the null results the prose is
written around (bottommost compaction and parallel execution moved nothing toward parity); the
final pair (long class at parity and under its own floor, short class not reproducing, outliers
concentrated in the pool overshoot); and the two remaining items (the overshoot, and the
absent-account CPU gap surviving both warming ablations). Each oracle was mutation-tested: change
the one input it guards and generation fails.

## Findings

1. **The snapshot's pre-run was baked into its baseline.** Only one arm runs a pre-run, and
   `promote_post_pre_runs: true` freezes its result into the image every test restores from, so
   the benchmark's accounts are the newest versions in the youngest files. Placement, not
   content: on keys sampled from each store's own contents jochemnet is the *more* expensive
   store (10.26 vs 3.44 blocks per trie-node lookup), and its read volume saturates (47 MB for
   50,000 lookups at 0.23 blocks each, against 404 MB at 1.97). Compacting it: account reads
   0.058 → 0.977, reused/small code 0.066 → 0.981, agreement within ±10% over the 1,461-test
   sweep 12.8% → 53.0%. `before`, `after`, `measured.random_keys`, `measured.amortisation`.
2. **The client restarts for every test, and the stores warm it up differently.** The .NET
   tiering thread is ~70% of jochemnet's measured-step CPU and 34-50% of state-actor's;
   jochemnet's setup block is heavy EVM work (31 MB read, against 9 MB), so its interpreter is
   promoted before the measured block. `DOTNET_TieredCompilation=0` on both arms: controls
   0.726 → 1.143, distinct-contract code 0.642 → 0.944. Turning off parallel execution moved the
   controls the other way (0.556). The real fix is a discarded burn-in block in the harness.
   `jit_experiment`.
3. **The generated store made the client rewrite it on every boot.** The generator's finishing
   `CompactRange` ran with no compaction filter, so RocksDB *moved* files into the bottom level
   with their sequence numbers set; every boot restarted 14 `BottommostFiles` jobs on
   `StateNodes`, 1,962 MB read by an idle client in 60 s. Fixed upstream in
   [state-actor#139](https://github.com/ethereum/state-actor/pull/139). It moved distinct-contract
   code by +0.007, inside the replica swing. `bottommost`.
4. **What shares a code block with the contract being read.** Code is keyed by hash, so a
   fixture contract's block neighbours are random: real mainnet contracts on the snapshot (median
   45 B), the filler pool's 23-byte stubs on the generated store, which don't compress. 2,165 vs
   1,603 B per fetch, 1.50 vs 1.35 pages. Repacked with a 64-byte block: DIFF_MAX 0.938 → 1.008,
   JUMPDEST 0.943 → 1.015, reused control 1.000 → 0.996. Fixed in the generator by
   [state-actor#141](https://github.com/ethereum/state-actor/pull/141); regenerated, the two
   cells read 1.05-1.10. Besu shows the same shape (0.83 vs 0.94). `intervention_blocks`, `v2`.
5. **Two storage columns nobody had compacted.** `Flat/Storage` sat in 807 files over six
   levels, `Flat/StorageNodes` in 1,961 over five, against one level each on the generated
   store; an absent key must be refused by every level. Compacting them: storing to an absent
   slot 2.03/2.14 → 1.15/1.22 → 0.94/1.12, storage-trie reads equalised, the overwrite control
   unmoved. `storage`.

**Final pair (R74).** Long class 1.012 / 1.014, 122 and 121 of 144 within ±10%, floor 138.
Short class 1.150 / 1.149, 40 and 33 of 122, floor 50. 19 long tests miss in both runs: 14 are
the pool overshoot, 5 transfers with read-identical traces. `final`, `waterfall`.

**What's left.**
- #141 keeps a 1 KiB floor on pool record size, so on Nethermind's 4 KB code block a fixture
  contract starts a block of its own more often than on mainnet: distinct-contract code at
  1.09-1.10 in state-actor's favour. Fix: draw record sizes from mainnet's distribution.
- The absent-account transfer: identical reads, 2.14 vs 1.23 CPU-seconds in managed thread-pool
  threads at 160M; neither `--Blocks.PreWarming=None` nor `--FlatDb.TrieWarmerWorkerCount=0`
  closes it. Next instrument is a profiler.
- Sub-second tests: 41% reproduce against themselves. Needs a burn-in block in the harness.
- Outside this study: v2's Account column sits at L3 with compaction-pending=1; benchmarkoor's
  podman fill-image naming bug (`pkg/builder/eest_payloads.go`).

Consequence, and the same one the sibling studies reach: comparing a promoted-after-pre-run
snapshot against a store that never got one measures preparation, not access cost.

## Study history

What the long version carried that the rewrite doesn't. Superseded positions are kept, marked,
so the reasoning survives.

**Our own contamination: the top-of-trie packing (round 66).** The snapshot read 630,531
top-of-trie node blocks against the generated store's 413,964 for the same 18 blocks of
transfers (Account and code reads identical). `probe-flat -mode shape` says both account tries
have the identical complete top (1,118,481 nodes) and the generated one is marginally *deeper*
(7.90 vs 7.82 nibbles to a leaf, 21% more accounts), so shape cannot make it read fewer nodes.
RocksDB's table properties say the top-of-trie column was packed 7 nodes to a 4 KB block on the
snapshot against 29 to a 16 KB block on the generated store — the client's option is 16000 — and
since top nodes are keyed by path in pre-order, a 16 KB block holds a level-4 node with its
sixteen children while a 4 KB block does not: 1.07 top-node reads per touched account against
0.73. Swapping the two layouts (2 s each, promoted) moved the transfer cell 1.074 → 1.014 over 94
test pairs and swapped the read counts with it. Provenance: `sstprops.py` and the file numbers
date the ten 4 KB files to round 13's read-write open, which transcribed the client's options for
the column it rebuilt (Account) and left the rest on RocksDB's defaults; the round-14 audit
checked two columns and missed it. The snapshot now carries the client's packing. This is why the
waterfall shows transfers and storage at baseline and final only. `topnodes`.

**Superseded explanations.**
- *The transfer cell as a migrated trie costing more to update*, then *as per-read cost on a
  mainnet-shaped trie* (superseded, round 66 and R68: the traces show identical reads on both
  stores; the residual was the packing above, then the denominator trap below).
- *The code database refuted as the DIFF_MAX explanation* (superseded, rounds 59-64: reading code
  is cheaper on the generated store at every *isolated* granularity — 10,513 B/196 µs against
  14,208 B/346 µs for a cold random lookup, 4,186 against 9,705 B per read for a cold sweep of
  3,000 distinct maximum-size contracts — but an isolated probe reads one block and cannot see
  who shares it. Finding 4).
- *A fixed ~179 MB per-test read plus a ~10% proportional term, partly Nethermind's block cache
  carrying over between setup and measured steps* (superseded: `container-recreate` restarts the
  client per test, which bounds carry-over at 30% of the control gap; B1 cut the block cache
  128× and the control moved +3.0% to 0.707, against a predicted 0.85-0.95. The control gap is
  the JIT, Finding 2).
- *A ranked table of the twelve most divergent tests* (superseded: all twelve ran under 0.2 s, so
  it ranked noise).

**Two smaller store defects, same family as Finding 3.** The generator's finishing `CompactRange`
also left state-actor's Account CF at L3:92 (23.7 GB) and both arms' code databases
compaction-pending; RocksDB writes manual-compaction output into the deepest level that already
holds files unless given `change_level` plus a target level. Settling them changed throughput by
nothing measurable. Forcing the bottommost rewrite took `StateNodes` 603 → 207 files in 422 s and
`StorageNodes` 1,211 → 1,126 in 2,114 s.

**Per-CF read attribution, re-measured on the settled store.** Every read volume collected before
Finding 3's fix was inflated in proportion to test duration, because a ~33 MB/s background scan
deposits more bytes into a longer window. Re-run quiet: non-code access is byte-for-byte alike
(19.3 MB from `flat/Account` against jochemnet's 16.2 MB across its whole datadir), while a
distinct maximum-size contract per access costs 2,821 MB against 1,671 MB over six matched pairs
per arm — 1.69× the bytes, essentially all of it the code database.

**The denominator trap (R68).** 27 of 142 long-class tests left the band in v2 run 1 and 23 in
run 2, but both runs divided by the *same* jochemnet run, so one slow jochemnet measurement made
a test "reproduce" in both. Re-running 20 of them as a fresh pair moved jochemnet by up to 29% on
a single test against 14% for state-actor: transfer-to-self 1.353 → 1.086, to an existing account
1.184 → 1.050. Two runs of one arm are one measurement of the ratio. `outliers`.

**Duration classes (round 57 on).** Split every test at one second, membership fixed from the
reference arm: in the 1,461-test sweep after Finding 1, the short class sat at 0.767 with 18%
inside ±10% against a floor of 49%; the long class at 0.978 with 83% inside, floor 97%. The
boundary is not doing the work — the long class reads 0.979/0.978/0.977 at 0.5/1/2 s — and the
storage category, which straddles it, read 1.468 below a second and 1.007 above it on the same
pair of stores. `classes`.

**The 2×2 inside the long class.** Opcodes that only read the account row (BALANCE, EXTCODEHASH)
were at 0.971-0.977 under every access mode; opcodes that load the callee's code matched them
while the contract was reused (0.980), fell to 0.926 when the code was scanned for jump
destinations, and to 0.642 when every access touched a distinct maximum-size contract — reading
1.48× the bytes. The syscall trace behind Finding 4: account rows byte-identical (49.5k preads of
4,068 / 4,060 B), 28% vs 14% of code reads in the 1-2 ms bucket, +149 µs per fetch, 13.24-13.48 s
against 14.10-14.49 s over five runs each.

**Absent-account transfer detail (R71, R73).** 148/148/149 MGas/s on the generated store against
98/105/100 on the snapshot over three repetitions; fixtures compositionally identical (1 block,
782 transactions, 204,600 gas each); 2.35 vs 1.31 CPU-seconds at 240M, plus 0.26 s of background
GC only on the snapshot. The test creates ~5,500 accounts per block and reads almost nothing.
