# Besu state-DB divergence — state-actor vs a mainnet snapshot

Why three Besu databases holding the same state report throughput up to 9x apart on
identical EEST work: `plain` (the published Bonsai mainnet snapshot, jochemnet, as it
ships), `compacted` (the same snapshot flushed and fully compacted), and `state_actor`
(synthetically generated state). All three causes are artifacts of how the stores were built
and measured: the pre-run's rows sitting in the snapshot's youngest files, no bloom filters in
the generated store, and the generator's code pool.

This is the second client in the series, after the geth study and alongside the Nethermind
one in a sibling folder. Everything needed to reproduce or re-cut the analysis lives here.

## Layout

| Path | What |
|---|---|
| `besu-state-db-report.html` | The deliverable. Zero JS, single file. |
| `gen_besu_state_db_report.py` | Prose, computations, and HTML/SVG emission. Python 3 stdlib only. |
| `collect_besu.py` | Runs on the benchmark host: reduces the arms' result trees to `data/report_data.json`. |
| `report_svg.py` | Inline-SVG primitives (scales, axes, dots, lines, bands). |
| `data/report_data.json` | Every value the report renders. The only input to the generator. |
| `figures/fig_*.svg` | The seven charts as standalone files. |

## Regenerate

```
python3 gen_besu_state_db_report.py
```

Paths resolve relative to the script. The build fails rather than publish if the data
stops supporting a sentence the page states as fact; see the oracles in `main()`.

## Method and errata

The page states its findings and their fixes. This section holds the process history: the
dead ends, the probe bugs, and the corrections made along the way, in the order they
happened.

**The write-ahead log looked like the cause, and wasn't.** The published snapshot ships a
1.26 GB WAL, 21 files. That is exactly the shape of a benchmark artifact, so it was the
first thing tested. It's inert: its size varies between identical replays, draining it adds
no SST file (RocksDB's own open path had already recovered and flushed it before any test
ran), and measured end to end, draining changes nothing at all. Besu's decomposition is 0%
drain, 100% compaction, unlike geth's pathdb journal, which does carry a real share of the
effect on that client.

**What Besu's own logs and counters say.** Every arm boots with `Existing database at
/data. Metadata versionedStorageFormat=BaseVersionedStorageFormat{format=BONSAI,
version=3}. Processing WAL...`, boot-time boilerplate rather than evidence of work. The
line that matters is `Flat db mode found FULL`: account reads go to Bonsai's flat
keyspace, not down the trie, and the metrics agree 99.83% of account lookups are served
from it. That's the premise the whole root-cause argument rests on — an account lookup is
one key in one column family, so its cost is the cost of locating that key, not the depth
of a tree.

**What we ruled out first.** Both stores run byte-identical RocksDB settings on every
state column family (`compression=kLZ4Compression`, `block_size=32768`). The extraction is
deterministic across three independent unpacks. Trie logs are disabled on both, and the
generated store's cf0a (`TRIE_LOG_STORAGE`) is empty, while the snapshot's carries a
nonzero amount — an artifact of its history, not something either store's read path uses.
Whole-store totals are never comparable, because the snapshot carries around 760 GB of
chain history the generated store doesn't have, so every comparison in the article is
per column family.

**A generator bug found and fixed, moving nothing measurable.** The generator's closing
compaction ran with the default `bottommost_level_compaction=kIfHaveCompactionFilter` and
no filter configured, so RocksDB moved the flushed L0 files into the empty bottom level
instead of rewriting them: every file still carried a nonzero largest-seqno. Booting the
client on that store then triggered a background `BottommostFiles` job on every restart,
reading megabytes for zero queries. Fixed upstream in
[state-actor#139](https://github.com/ethereum/state-actor/pull/139), which repairs the
same call in the Besu, geth and Nethermind writers. It moved throughput by nothing
measurable; it was still worth fixing, because an idle background job on every client
restart is not a state the generator should ship.

**A probe bug that produced a wrong mechanism, corrected in public.** An early attempt to
attribute the corpus-pool residual to "block reads per lookup" used a custom probe
(`CfReadCost`) that opened each store with its own block cache and no filter policy
configured. RocksDB won't use the bloom filters present in the files unless a policy is
supplied, so every level check cost a data block on both stores, and the probe reported
1.28 block reads per lookup on the snapshot against 1.00 on the generated store. The tell
was in the probe's own output: `bloom useful 0, full_positive 0` on both stores, when both
stores' own geometry reports hundreds of megabytes of filters in cf06. Corrected with
filters on and 30,000 keys drawn uniformly across the keyspace: both stores answer a
lookup with almost exactly one data block, the two per-lookup ratios point in opposite
directions, and neither matches the workload's ratio. Cost per lookup is not the
mechanism; the residual is the number of lookups per prefetched account, and that is
unmeasured. Lesson kept for the next probe: any tool that reconfigures the store it
measures is measuring its own configuration, not the store.

**A medium confusion, made twice.** Establishing whether the generated store's
distinct-code residual was a store property or a disk property took two failed attempts
before the paired-reference comparison in "Where it stands" landed. First, a claim that
the generated store reads "3.03x the clean reference" turned out to compare NVMe (schelk)
against the HDD array; the path-invariance check that was meant to catch this held the
device fixed and varied only the method, so it proved nothing about media. Second, a
follow-up claim that the archived reference "reads 3.96x what the same state costs when
prepared cleanly" made the identical mistake in the other direction: archived arm on NVMe
against a rebuild on the HDD array. The rule that came out of both corrections: any
cross-store number in this study must name its medium, and two numbers may only be
divided if they share one. The oracles in the generator now assert that the NVMe and
array numbers disagree, so the caveat can't quietly disappear from a future edit.

**Dead ends, not pursued further.** A candidate fix that sampled 64 contracts from the
snapshot's own code column, prefix-sliced with a spill into the next member
(`state-actor#140`), passed its own aggregate test but failed CI on goldens it never ran
and was closed in favour of the union-sampled, uniformly-windowed pool that shipped as
`#141`. A tool for probing miss-rate counters (`MissCost`) stopped working once the
generated store's RocksDB `OPTIONS` file gained `max_manifest_space_amp_pct`; dropped,
since the filter-bytes evidence already covers the same claim. And the absence and
shared-code classes have not been re-run against a purpose-built same-medium reference the
way the distinct-code class was; that rerun is an open item in "What's left."
