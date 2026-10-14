# reth state-DB divergence — benchmarkoor bloatnet runs

Why identical EEST bloatnet benchmarks reported a large throughput gap between two reth
databases: `jochemnet` (a mainnet shadowfork snapshot at block 24,402,727, converted to reth
storage v2) and `state-actor` (synthetically generated state). Six things made the gap: a
buffered loop device serving one read at a time, the snapshot's older storage layout, and four
things in how the store was generated — `HashedAccounts` written out of key order with trie rows
stored past alloy's rule, page fill left as whatever the writer happened to leave, a contract
storage shape nothing like mainnet's, and 21% more accounts than mainnet. Fixed by five
state-actor PRs (PR1-PR5) and a generation size matched to mainnet's account count, 153 of the
154 tests that run for half a second or more land within &plusmn;10%. Three refinements (PR6-PR8:
mainnet's storage tail, contract trie rows in address order, mainnet's account shape) make the
final store look more like mainnet without changing that share; over a second it lands 113 of 114
on each independent pair.

This is the fourth client in the series, after the geth, Besu and Nethermind studies in sibling
folders. Everything needed to reproduce or re-cut the analysis lives here.

## Preconditions

None of these is discussed in the article — it starts from a pair where both already hold — but
all have to be true before a run means anything, so they are recorded here for anyone
reproducing it.

**Both arms must run under loop direct-io.** Every scratch in this study is an ext4 filesystem on
a loop device over an image file, and losetup's default is a buffered loop: it reads its backing
file through a second page cache, on one worker that serves one request at a time, however many
the client issues in parallel. A buffered loop stays flat at ~13.7k IOPS from 4 to 64 concurrent
jobs; with direct-io (`LOOP_SET_DIRECT_IO`, set while nothing has the loop mapped) it reaches
~130k. Nothing measured on a buffered loop is quoted in this article — see finding 1.

**Jochemnet must be converted to storage v2.** As published, the snapshot is a legacy reth store
(v1): reads go to `PlainAccountState`/`PlainStorageState`, keyed by address, while the hashed
tables only feed the state root. state-actor's writer only produces v2 (`HashedAccounts` /
`HashedStorages`, keyed by keccak). Comparing an as-published v1 snapshot against a v2 generated
store measures the read path, not the stores — see finding 2. `reth db migrate-v2` clears the
plain tables and both tries; the pipeline rebuild that follows checks the new root against the
tip header.

**reth needs the BAL patch to fill its own fixtures.** benchmarkoor's filler calls
`testing_buildBlockV1`, a Geth-only RPC extension; stock reth 2.4.1-dev's `testing_buildBlockV1`
builds the block access list and then drops it (a V5 envelope with `ExecutionPayloadV3`), so
EEST's `engine_newPayloadV5` fails with "missing field blockAccessList". `build-reth-fill.sh`
patches two files to return the V6 envelope (`ExecutionPayloadV4`, BAL included) and builds reth
acf6e17 without default features, used only to fill fixtures for a new genesis (PR5 changes the
genesis, so cycle 2's fixtures were refilled by this reth, not the Nethermind filler the earlier
cycles reused). Every measurement still runs the stock `devnet7-sigkill` image.

**`--debug.skip-genesis-validation`.** Both arms boot with
`node --full --engine.disable-precompile-cache --debug.skip-genesis-validation` plus RPC/auth
flags — benchmarkoor's default reth command, identical on both arms.

## Layout

| Path | What |
|---|---|
| `reth-state-db-report.html` | The deliverable. Zero JS, single file. Only external fetches are the site's Google-Font stylesheets (degrades to system monospace offline). |
| `gen_reth_state_db_report.py` | Prose, computations, and HTML/SVG emission. Python 3 stdlib only. Refuses to run without `claims.C19` (cycle 2) and `claims.C20` (cycle 3, the final store) in the data. |
| `collect_reth.py` | Runs on the benchmark host: reduces the run registry into `data/report_data.json` (claims C1-C20 and verdicts). Do not run locally — it needs `/root/bench/reth` on the bench host. |
| `report_svg.py` | Inline-SVG primitives (scales, axes, dots, lines, bands). Has its own self-check. |
| `crt_theme.py` | The site stylesheet, byte-identical to the sibling reports, kept in one place so the four cannot drift apart. |
| `data/report_data.json` | Every value the report renders. The only input to the generator. |
| `figures/fig_*.svg` | The fourteen figures as standalone files, site palette derived from `crt_theme.CSS` so a figure cannot disagree with how it renders in the page. |

## Reproduce

```
python3 gen_reth_state_db_report.py         # writes the html and the fourteen svgs
python3 report_svg.py                       # primitive self-check, prints "report_svg selfcheck ok"
```

Paths resolve relative to the script by default; `--data PATH` and `--out DIR` point it at a
different data file or output directory (used to render a throwaway copy without touching this
folder). To re-derive the data, run `collect_reth.py` on the bench host:

```
tsh ssh CPerezz@stateless-bloatnet-benchmarks 'sudo -n python3 -' < collect_reth.py > data/report_data.json
```

The collector fails its own exit code (non-zero) if any registry check fails, and the generator
separately refuses to emit the page if `claims.C19` (cycle 2, PR1-PR5) or `claims.C20` (cycle 3,
the final store with PR1-PR8) is missing or incomplete.

## Reading the output

Expected stdout, all asserted: `headline factor: <N>x` (the sequential-account family under
buffered loops, the gap finding 2 explains), the share of tests at 0.5 s or more that land in band
per store (original, PR1+2, PR1-4, PR1-5, PR1-8), whether the final store's acceptance bar is met,
and the count of tests still out of band.

**The generator refuses to emit the page if the data stops supporting the prose.** Every claim
the page states as fact (C1-C14) has an oracle in `collect_reth.py`; `main()` asserts all of them
are `"supported"` before writing anything. A further set of inline assertions pins each finding's
before/after direction (PR1's tree denser than jochemnet's, cycle 1's acceptance, the toy test's
order-not-call result, and so on) against the collected data, so a regression in the measurements
or a stale claim fails generation with the assertion's message rather than a silently wrong page.

## Findings

1. **The loop device served one read at a time.** Buffered, a loop stays flat at ~13.7k IOPS
   regardless of concurrency; direct-io removes the ceiling. Readahead on the buffered backing
   file made the large-code gap look like a store property — it wasn't.
2. **jochemnet read plain state; state-actor stores read hashed state.** EEST's sequential
   address and slot walks are cheap on a table keyed by address and expensive on one keyed by a
   hash. The comparison is only fair once jochemnet is converted to the same v2 layout.
3. **HashedAccounts was written in random order, and the tries stored rows reth never stores.**
   Random-order inserts split libmdbx pages mid-range, halving leaf fill and adding a level
   (PR1). The hash builder's "full emissions" mode stored a row for every branch, where
   `alloy_trie` — and reth's own writers — store one only if `tree_mask | hash_mask != 0` (PR2).
4. **Page fill is a dial, and a generated store's pages are not organic.** `libmdbx` 0.14's
   `prefer_waf_insteadof_balance` default and `MDBX_opt_split_reserve` let the writer target a
   real node's fill instead of packing every table dense (PR3 key-ordered writes, PR4 fill
   profiles). Cycle 1 (PR1-4) reaches 97.4% of the gated tests in band.
5. **The generated contracts had the wrong storage shape.** Autofill gave every contract ~254
   slots; mainnet is 55% one-slot contracts, 97% at or under the inline limit of 28. A modified
   account's siblings need their storage root recomputed, cheap for an inline contract and a full
   nested-tree walk for an autofill one. PR5 draws slot counts and value lengths from jochemnet's
   exact storage shape and matches its account count. Cycle 2 (PR1-5) reaches 99.4% (153/154);
   the walk pages fell from ~11-12k to ~1.1-1.3k per test, against jochemnet's 0.7-1.1k.

Then three refinements, none a cause of the gap (cycle 3, PR1-8, 153/154 again): PR6 draws the
largest contracts from mainnet's power law with no cap; PR7 writes each contract's trie rows in
address order, filling StoragesTrie's top-level tree like jochemnet's; PR8 gives accounts
mainnet's nonces, balances and code-only contracts. Account reads barely move, because a read
touches one row page per account whatever the row size; what still differs is the account
index, whose pages jochemnet keeps fuller.

## Method and errata

Ratios are state-actor throughput divided by jochemnet's, in MGas/s: 1.00 is parity, below 1
means the generated store is slower. The in-band test is &plusmn;10%, `[0.909, 1.1]`. Every test
is classed once, from the first jochemnet run's measured step time (&ge; 1 s, 0.5&ndash;1 s,
&lt; 0.5 s); only the first two classes are gated, and the third is shown but not counted, because
on this harness it mostly measures client boot, not the store. Every comparison is reported
beside a replica floor — the same store measured against itself — so a reader can see the best
any pair of runs here could do.

Benchmark results on this series move 10-20% with page-fill history alone, so any number here
should be read together with the fill profile that produced it (`fresh`, `migrated` or `aged`;
all three cycles use `migrated`, PR4's match for a store converted from v1).
