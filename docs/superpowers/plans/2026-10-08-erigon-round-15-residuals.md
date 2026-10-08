# Erigon study, round 15: the two residuals

Article state before this round: `articles-wt-erigon-article` `19bee3f` (figures `fig_steps`,
`fig_residuals`, `fig_nostate`; "What's left" names both residuals as open). Predictions for every
step below are in the ledger (round 15) before any run.

## Where we are (final pairs H, over a second, 110 tests)

- 93 / 88 inside ±10%; each store measured twice: 90 (state-actor), 94 (jochemnet). No row outside the
  band in both pairs.
- **Residual A, over a second:** state-actor leans 3-4% slow (0.971 / 0.960 against floor centres
  0.99 / 1.00; 15 of 17 and 19 of 22 misses fall low). It reads 2-7% more pages on every traced test.
  Candidates: its storage and commitment keys are still raw (we re-encoded only the code file); it
  holds 21% more accounts (429 M vs 355 M).
- **Residual B, under a second:** controls, warm queries and one-slot reloads run 1.20-1.42x faster on
  state-actor in both pairs, floors centred on 0.96-1.02. Jochemnet spends ~16 ms more per block
  (median), there since untreated.

## Point 1: where jochemnet's ~16 ms goes

**Evidence already in hand (no new runs):**
- benchmarkoor's read counter on the 80 controls: jochemnet's newPayload reads 5.1 MB, state-actor's
  0.08 MB, the same at 160M and 240M (3.8 MB untreated).
- One control (BALANCE, distinct contract, 160M, run joc-H1 / sa-H1), from Erigon's own log:
  jochemnet logs `[NewPayload] Handling new payload` 30 ms after the request arrives and executes in
  29.8 ms; state-actor after 3 ms, executing in 39.9 ms. The extra time is before Erigon starts on
  the block.
- Source (`5f62f4ed`): before that log line, `newPayload` (`execution/engineapi/engine_server.go:269`)
  calls `getQuickPayloadStatusIfPossible`, whose first lookup is `GetHeaderByHash` of the new block's
  hash, one Erigon has never seen. `BlockReader.HeaderByHash`
  (`db/snapshotsync/freezeblocks/block_reader.go:568`) misses in MDBX and then checks every frozen
  headers segment, newest first. Jochemnet has 65 headers segments (136 MB of hash index); state-actor
  has none. With the page cache dropped before every test, each check is cold.

**Hypothesis:** the 16 ms is one unknown-hash sweep over 65 cold header indexes per newPayload. It's
chain history, not state, and a running node keeps those pages hot.

**Steps** (stores unchanged; ~2 h, ~1 h of box time; box steps hold `.busy`):
1. `collect_np_phases.py` (new, reads existing benchmarkoor logs of D/E/G/H): per test and arm, split
   newPayload into *before handling* (request start to `Handling new payload`), *execution*
   (`parallel done in=`) and *rest*. Gives both residuals a home: is the lean in execution, is the
   16 ms before it?
2. Probe on both stores (boot with the benchmark's flags, as in `recode-sa.sh`'s `boot()`, no
   payloads): drop caches, time `eth_getBlockByHash(random hash)` 20 times cold and 20 warm, with the
   `mm_filemap_add_to_page_cache` trace on. First confirm in source that this RPC reaches
   `BlockReader.HeaderByHash` on a miss; if it doesn't, use the one that does.
3. Trace T3 through the benchmark (`trace-tests.sh`, new `trace-tests-T3.regex`): 4 controls
   (BALANCE and CALL, 160M and 240M), 1 warm query, 1 one-slot reload, both arms. Extend
   `collect_trace.py` to split each newPayload window at the `Handling new payload` time.
4. Decide:
   - **Confirmed** (extra pages are headers `.idx`/`.seg`, before handling): harness artefact of
     dropping the page cache on a store with history. Remedy is in benchmarkoor (one discarded
     burn-in newPayload per test, already on the list), not in either store. Article: a fourth
     finding with the phase split and the trace.
   - **Refuted, reads in domain files** (e.g. the system contracts' storage, full on mainnet, near
     empty on a generated genesis): a generator realism question; separate decision.
   - **No extra reads:** CPU before handling; profile with pprof on a booted node.

## Point 2: storage and commitment keys written the way Erigon writes them

Erigon's schema compresses storage keys (`state_schema.go:229`) and commitment keys (`:274`);
accounts stay raw (`:207`). The measured state-actor store has storage 181 GB and commitment 282 GB,
both raw-keyed.

**Option B, re-encode the two files in place (recommended for the study):** the same method as
finding 3, one variable.
- Tooling: generalise `compactlatest recode-code` to `recode --domain storage|commitment`. Storage goes
  through `RecodeDomain`. Commitment goes through `compactCommitment` (GetLatest), as in the
  jochemnet rebuild. Branch values are plain keys on both stores (state-actor's vendored hph strips
  `ReplacePlainKeys`; the rebuild writes plain), so offsets changing in the storage file break
  nothing.
- Cross-check first, on the small e2e stores (`/bench/erigon/e2e/{old,new}`): re-encoding `old`'s
  storage and commitment should give the files the fixed generator wrote in `new`. Byte-identical if
  the two erigon pins' compressors (`5f62f4ed` here, `14273f79a6` in the builder) agree; if not, the
  same stream hashes and dictionary sizes within 1%. That ties this route to the state-actor fix.
- `recode-sa-sc.sh` (from `recode-sa.sh`): restore, recode storage then commitment into staging
  (read-only on the scratch), stream hashes equal, sample answers on the old layout
  (`eth_getStorageAt` on every N-th storage key and the fixture slots, `eth_getProof` on accounts
  with storage), swap, the same answers on the new layout (`cmp`), promote, smoke S3 (2/2, 0
  validation failures; executing blocks proves the commitment still updates).
- Trace T4 on state-actor (the five T2 tests and the T3 tests); jochemnet's T2/T3 still apply.
- Pairs I1/I2: `chain-B.sh joc:I1 sa:I1 joc:I2 sa:I2` (~10.3 h), `collect_erigon.py '*' I`.
- Cost: tooling ~3 h; recode ~12-18 h [estimate: the code file took 6 h for 49.6 GB with one
  worker]; checks ~2 h; pairs ~10.3 h. About 1.5 days.
- Disk: sequential peak ~560 GB on the rootfs (temp words + output); 388 GB free now.

**Option A, regenerate state-actor's store with the fixed generator** (`cbc1719`, same base
`005a19c` as the measured store, so the same state root): proves the PR end to end at full size and
measures its real generation cost. Costs ~30 h [estimate] before the pairs, and the peak disk is
uncertain: stream-sort temps (~590 GB) plus the compressor's raw-size temp words plus the output
could reach ~1.1 TB, against ~1.24 TB free after every deletion below. Better run after the study,
as the PR's validation, with the e2e cross-check above already showing both routes write the same
files.

**After point 2:**
- Score the predictions.
- Article: a fifth stage in `fig_steps`, `fig_progress` and the table, `fig_residuals` on I.
- If the lean closes, a finding for it. If it doesn't, the extra accounts become the lead; testing
  them needs a store generated at jochemnet's account count (out of scope; noted).

## Needs Anon's approval

1. Run point 1 (stores unchanged).
2. Point 2 route: B now, A later as PR validation (recommended); or A now.
3. Deletions on the box (md2 is 95% full): `/bench/erigon/compact/staging` 313 GB (jochemnet rebuild
   staging, already promoted), `compact/staging-sa` 16 GB, `compact/answers-{old,new}.jsonl` 10 GB.
   Keep `/bench/erigon/e2e` until the cross-check, and `/bench/erigon/sa-store` (raw fallback) unless
   option A runs.

## Order

Point 1 step 1 and point 2's tooling in parallel (no box time), then point 1's probe and trace (~1 h
on the box), then the e2e cross-check, the recode, T4, and the I pairs.
