# Erigon state-DB divergence: benchmarkoor bloatnet runs

Why identical EEST bloatnet benchmarks reported Erigon on a generated store (`state-actor`) up to
2× slower on newPayload and 3× faster on the whole block than on a mainnet snapshot (`jochemnet`,
a shadowfork snapshot at block 24,402,727). Four things made the gaps: the benchmark's state never
left jochemnet's database, jochemnet carried a code cache into every boot, and state-actor wrote
its code file raw and every other state file in Erigon's oldest format. Fixed one at a time, the
tests that run over a second land at a median of 0.964 / 0.974 on newPayload (two independent
pairs), 98 / 97 of 110 inside ±10%, against 101 / 94 for one store measured against itself.

This is the fifth client in the series, after the geth, Besu, Nethermind and reth studies in
sibling folders.

## Preconditions

None of these is discussed in the article, but all held for every run quoted in it.

**Both arms run under loop direct-io**, on one host, both scratches on the same NVMe array.
Buffered loops serve one read at a time (see the reth study). The A and B runs were buffered; the
article's numbers start at the D series.

**Both arms run the same image and flags:** `ethpandaops/erigon:glamsterdam-devnet-7` (Erigon
3.7.0-dev, `5f62f4ed`) with `--exec.no-merge=true --exec.no-prune=true
--exec.no-background-maintenance --experimental.parallel-commitment --override.amsterdam=<t>`,
benchmarkoor's container-recreate rollback and page-cache drops between steps. Each run's
`config.json` in `data/runs/` records the exact instance.

**Each arm uses fixtures filled on its own genesis.** jochemnet uses the published
`eest-payloads-jochemnet-v1` payloads; state-actor uses the fill made for its genesis (state root
`0x48d611bb…51b8`, the same store as the Nethermind study's). The same 266 tests run on both
(160M and 240M), with identical gas on every test.

**jochemnet is rebuilt to the worst case** (finding 1): its benchmark state is moved out of MDBX
into one frozen file per domain with Erigon's own writer, so a read takes the same path on both
stores. Every RPC answer sampled (339,329, `eth_getProof` included) is identical before and after.

## Layout

| Path | What |
|---|---|
| `erigon-state-db-report.html` | The deliverable. Zero JS, single file. |
| `gen_erigon_state_db_report.py` | Prose, computations and HTML/SVG emission. Python 3 stdlib only. Every factual sentence has an assertion against the data; the page is not written if one fails. |
| `collect_*.py` | Ran on the bench host to reduce raw runs, traces and probes into `data/report_data.json`. The host is wiped; they are kept to document how each number was derived. |
| `report_svg.py`, `crt_theme.py` | Inline-SVG primitives (with a self-check) and the site stylesheet shared with the sibling reports. |
| `data/report_data.json` | Every value the report renders. The only input to the generator. |
| `data/series/*.json` | The per-series result tables the collectors wrote from the runs (`baseline-*.json` per series B, D, E, G, H, I; `np-phases-*`, `fcu-*`, `step0-T*` traces, `probe-hash`). `report_data.json`'s provenance strings cite them by sha256. |
| `data/runs/*.tar.zst` | Every benchmarkoor run of the study (38): per-test results, step responses, run config, suite summary and benchmarkoor's log. The per-test fixture copies and fill reports are left out (they are the fixtures). |
| `data/SHA256SUMS` | Checksums of everything under `series/` and `runs/`. |
| `figures/fig_*.svg` | The 17 figures as standalone files. |

Run ids: `er-joc-*` and `er-sa-*` are the two arms. A, B: the first runs on buffered loops. D:
direct-io. E: jochemnet rebuilt. G: its code cache emptied. H: state-actor's code file
re-encoded. I: its other three state files re-encoded (the final pairs). F and S: smoke tests after
a store changed. T: page-cache traces.

Raw page-cache traces, probes, host logs and the stores themselves were not kept.

## Reproduce

```
python3 gen_erigon_state_db_report.py      # writes the html and the 17 svgs
python3 report_svg.py                      # primitive self-check, prints "report_svg selfcheck ok"
shasum -a 256 -c data/SHA256SUMS           # from data/
zstd -dc data/runs/er-sa-I1-20261011.tar.zst | tar -xf -
```

## Method

Ratios are state-actor's throughput divided by jochemnet's: 1.00 is parity, below 1 the generated
store is slower. A test is in band within ±10%. Tests are classed once, from jochemnet's
newPayload time: over a second they count, under a second they are shown and not counted,
because on this harness they mostly measure the client booting and jochemnet reading its chain
history cold. Every comparison is reported beside a replica floor, one store measured against
itself, from two independent pairs.

The generator side of the fixes is upstream: state-actor
[#148](https://github.com/ethereum/state-actor/pull/148) writes every Erigon file through the
pinned Erigon's own code, at its current versions, and
[#149](https://github.com/ethereum/state-actor/pull/149) keeps its peak disk at the old writer's
level.
