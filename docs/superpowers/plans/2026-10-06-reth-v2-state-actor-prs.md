# Reth study: jochemnet on v2, two state-actor PRs, regenerate, re-bench

Ledger: `docs/superpowers/specs/2026-10-03-reth-study-ledger.md`. Host: stateless-bloatnet-benchmarks,
`/root/bench/reth`. state-actor checkout: `~/dev/state-actor` (origin/main = `005a19c`, the commit the
current store was generated with). Untracked, like the ledger.

## Goal

1. Move every comparison to jochemnet in reth's current layout (v2, the default since reth 2.0).
2. Find the benchmarks where state-actor differs from v2 jochemnet by more than 1.1x.
3. Fix the two writer behaviours behind them in state-actor, as two mergeable PRs. Don't merge.
4. Regenerate the store with the fixed writer, re-bench, and show which differences went away.

## Stage 1: v2 jochemnet and the new baseline (running since 22:05 CEST)

The driver `v2.sh` runs in tmux `reth-v2`; the v1 backup `jbackup.sh` runs in tmux `reth-jbak`.
1. Back up the v1 jochemnet virgin to `/data/schelk-vols/reth-joc-virgin.v1.img` (md3).
2. Meanwhile, run `reth db migrate-v2 --chain mainnet` on the J scratch (published devnet-7 image,
   acf6e17). A failure recovers the scratch from the v1 virgin.
3. Put the original state-actor store (main 005a19c, the pre-repack backup) back as the S virgin and
   re-adopt it with `schelk init-from`. Check: HashedAccounts has 11,698,671 leaf pages.
4. After the backup: promote v2 J. Gate: `storage_v2: true`, idle writes on a fresh mount, 6-test
   smoke under DIO.
5. Baseline under DIO, published image, the 266 common tests: vj1 vs1 vj2 vs2, reduced to
   `results/baseline-v2.json` (class from vj1).

**The difference set D**: a test is in D when both pairs (vs1/vj1, vs2/vj2) put the ratio outside
[1/1.1, 1.1] on the same side, and both arms' replica floors are inside ±10% for it. Sub-second tests
are kept, but listed apart (their floors are ~70% in band). D and its per-test ratios go into the
ledger before stage 2 changes anything.

Prediction from the read-switch runs (v2 jochemnet should behave like jochemnet with hashed reads):
- The sequential-address family leaves D (s/jh 0.93-0.95).
- D keeps account rows (~0.94), CALL with value to EOAs (~0.82) and ether transfers (~0.88).
- D also gets sload/sstore_bloated, where state-actor is *faster* (~1.2).

## PR1: reth writer: write HashedAccounts in hashed-key order

**Why.** `WriteEOAs`/`WriteContracts` put HashedAccounts rows in RNG draw order. Each insert lands
inside the key range, so libmdbx splits pages in the middle: leaf fill 0.50, depth 6. A sorted insert
packs fully: the toy test gave 40,817 vs 79,846 leaves, and libmdbx has split by insert position since
v0.10.0. The repack (same rows, fill 0.99) took account rows from 0.867 to parity with jochemnet.

**Change.** Every account already goes through `putAccountRLP` into the streamsort store keyed by
AddrHash, which phase 2 reads in ascending order to build the root.
- Carry the account's compact HashedAccounts bytes beside its RLP in that stream.
- In phase 2, `cursor.Append` each (AddrHash, compact) into HashedAccounts while the trie builder
  consumes the RLP.
- `WriteEOAs`/`WriteContracts` stop writing HashedAccounts. They keep the archive tables
  (AccountChangeSets, AccountsHistory) and the `AccountBytes` accounting.
- The compact bytes are computed exactly as today: EOA `BytecodeHash=nil`; contract and 7702 EOA
  `&codeHash` after `WriteContracts` sets it. So the table's contents are byte-identical.

Files: `client/reth/run_cgo.go`, `data_writer_cgo.go`, `contracts_writer_cgo.go`, and the writer
tests. `state_root.go` keeps its iterator signature; `run_cgo.go` splits the stream value before
yielding the RLP.

**Invariants and checks.**
- State root unchanged: `TestRethGoldenStateRoot` and the cross-client genesis-root CI job.
- HashedAccounts contents identical. New test: a small autofill written by the old path and by the
  new one gives the same sha256 over all (k, v), and the new table is written in key order.
- New test: leaf pages for N sorted accounts are at most ~0.55x the old path's.
- At scale (the regenerated store): HashedAccounts sha256 = `c1710919…2ff0` (the value the repack
  tool printed for the 005a19c store), 430,696,738 entries.

**Risk.** Phase 2 is one MDBX write transaction. It already writes 161.7M AccountsTrie rows; PR1
adds ~6M dense pages to it. If libmdbx rejects the transaction size, commit the appends in chunks:
iterate the sorter in N-key windows, one txn each.

## PR2: reth writer: persist trie rows by alloy_trie's rule

**Why.** `NewHashBuilderFullEmissions` stores a row for every hashed branch:
`shouldEmit := storeInDbTrie || (b.fullEmissions && isHashed)` (`internal/reth/hash_builder.go:408`).
- The extra term adds exactly the bottom branches, whose children are all leaves. reth/alloy never
  store those: alloy's `store_branch_node` sets the parent's hash_mask unconditionally, so every
  non-bottom branch is already kept.
- AccountsTrie ends up with 161.7M rows against jochemnet's 26.9M (for 354.8M accounts), and
  StoragesTrie with 778M rows.
- State-changing blocks read them: CALL with value to EOAs touches 1.86x jochemnet's AccountsTrie
  branch pages.
- The doc comment's premise, that alloy would emit zero rows in a pure-leaf build, is wrong.

**Change.** Account and storage tries use the alloy-faithful gate (`storeInDbTrie` only). Clean
cutover: remove `NewHashBuilderFullEmissions` and the `fullEmissions` field, and rewrite the doc
comments (hash_builder.go, state_root.go, spec_storage_streaming_cgo.go, storage_root.go) to state
the real rule. The root path (`b.stack`, `Root()`) is untouched; emission doesn't feed it.

**Invariants and checks.**
- Root unchanged (goldens, cross-client CI).
- New property test on random pure-leaf builds (accounts and storage):
  - every emitted row has `tree_mask | hash_mask != 0`;
  - the emitted set equals the old set minus rows with both masks zero;
  - the old full-emission tests are replaced.
- If the alloy fixture generator (`internal/reth/testdata/gen`, Rust) builds, pin the emitted set
  against alloy. [The golden emissions test is skipped today over a path-format change; re-enabling
  it is a stretch goal, not a gate.]
- At scale: AccountsTrie rows ≈ 0.076 per account (jochemnet's ratio), i.e. ~33M. StoragesTrie
  shrinks likewise.
- reth boots the store, and smoke newPayload times match the old store's. The comment's worry is
  that reth falls back to a full HashedAccounts walk. jochemnet carries exactly the alloy row set
  and runs fine, so a slow first block would refute that reasoning.
- If it finishes in reasonable time, `reth db repair-trie` (dry run) on the regenerated store
  reports no inconsistencies.

## Not in these PRs

- **HashedStorages and StoragesTrie entity order.** HashedStorages is the largest table (301 GiB at
  fill 0.27), but:
  - spec storage runs through an 8-worker pipeline whose completion order is not dispatch order;
  - contract storage arrives in RNG order across ~2.6M contracts, so key order needs an external
    sort of 2.2B entries, or a resequencing stage.
  - Evidence that it matters for D is weak: state-actor is already faster on the bloated-storage
    tests. A PR3 is proposed only if the re-bench leaves a storage-attributable residual. The
    ~12k unclassified 64-byte-key pages on state-changing blocks are the candidate.
- Bytecodes order.
- Merging, version bumps, publishing ghcr images.

## Build, branches, generation

- Branches off `main`: `reth-hashed-accounts-key-order` (PR1) and `reth-trie-rows-alloy-rule` (PR2),
  each with its own tests. The experiment branch `reth-layout-fixes` merges both.
- Push to the fork (`CPerezz/state-actor`); open draft PRs only after Anon says so (decision B).
- Local: `go test -tags cgo_reth ./internal/reth/... ./client/reth/...` (needs RocksDB via grocksdb;
  where the Mac can't, run the tests in the builder image on the host).
- Image: `Dockerfile.reth` on the host (native amd64). The RocksDB layer is being cached now
  (tmux `sa-build`, from main), so the fix build only recompiles Go. It runs between the end of the
  baseline and the generation, never during a measurement.
- Generation, after the baseline:
  1. Detach and delete the S scratch image. The original store stays as a virgin on md3.
  2. Run `gen.sh` with the fix image. Same args: spec sha256 74dea7d1, seed 42, osaka, gas limit 1e9,
     target 350GB. Output `/sa-gen` on md2, guard at 100 GB free. The old peak was 570 GB; ~430 GB is
     expected.
  3. Copy into a new ext4 virgin image on md3 (`mkfs.ext4 -E lazy_itable_init=0,lazy_journal_init=0`)
     and attach it as loop0. The original virgin file is kept.
  4. Recreate the S scratch image, then `schelk init-from`.
- Gate on the fixed store:
  - genesis 0x0cb03528… and state root 0x48d611bb… identical, so the fixtures stay valid;
  - HashedAccounts sha256 `c1710919…2ff0`;
  - tree stats per table (mdbxmap);
  - idle writes; 6-test smoke under DIO with newPayload times next to the original's.

## Re-bench and verdict

- Full 266-test DIO pairs, fixed store against v2 jochemnet: fj1 fs1 fj2 fs2, fresh jochemnet runs
  in the same window (~8 h).
- The verdict is read on D: per test, before (vs/vj) → after (fs/fj), with floors. The tests outside
  D are the regression check, since a PR that fixes D but moves other tests can't merge.
- Traces of the T2 set on the fixed store, to show where the pages went.
- Per-test verdict:
  - **fixed**: both pairs inside 1.1x;
  - **improved**: closer to 1, still outside;
  - **unchanged**;
  - **regressed**: a test outside D that left the band.
- The collector gets the new runs and claims; the ledger, project file and vault are updated.

Predictions:
- Account rows, the sequential family and DIFF_MAX/JUMPDEST go to parity or better, given the repack
  result (sr/jh 1.11).
- CALL with value to EOAs moves from ~0.82 to ≥ 0.9; the AccountsTrie part is fixed.
- Ether moves from ~0.88 to ~1.0.
- sload/sstore_bloated stay ~1.2: the PRs don't touch storage.
- Anything left in D is the storage tables (PR3 candidate) or the v2-specific write path.

## Decisions for Anon

- **A.** The PR scope above: PR1 accounts only, PR2 trie rule. Storage order deferred.
- **B.** When to open the draft PRs upstream: after the re-bench (recommended, with the measured
  effect in their descriptions) or now.
- **C.** Re-bench all 266 tests (recommended: it doubles as the regression check) or D only (~3 h).
- **D.** `reth-sa-virgin.repacked.img` (571 GB on md3): delete after the re-bench, or keep.

## Order and timing

| step | when |
|---|---|
| Stage 1 box work | now -> ~09:00 CEST 2026-10-07 |
| PR1/PR2 implementation and tests (local) | in parallel with stage 1 |
| Fix image build (Go only, cached RocksDB) | ~5 min, after the baseline |
| Generation | ~7-9 h |
| Adopt and gate | ~2 h |
| Re-bench (266 x 4) | ~8 h |

Total ≈ 1.5 days of box time.
