# Reth study: root causes per family, fill-controlled state-actor writer

Debated plan (proposer/critic/adjudicator, 2026-10-08). Evidence:
- `local://rc-*.md`: reth runtime, libmdbx, state-actor writer, host evidence, EEST semantics; summarized in `local://rc-briefing.md`.
- Ledger section "v2 jochemnet and the state-actor fixes".

## Goal

Explain every remaining S/J difference per benchmark family, and bring every family whose J time is >= 0.5 s inside ±10%:
- S = state-actor store; J = jochemnet converted to storage v2.
- Below 0.5 s is reported but not gated.
- Fix the libmdbx configuration of the generator.
- Commit and open the PRs only once results pass.
- Answer whether the deferred storage PR is worth it.

## Root causes (settled)

**reth has no geth-journal analogue.**
- Every cross-block cache is in-process and dies with the process: execution cache, preserved sparse trie, per-block storage-root cache, ChangesetCache. The precompile cache is disabled.
- RocksDB history is write-only on the hot path. Static files are read only by BLOCKHASH. There are no persisted trie changesets.
- reth opens both stores with the same MDBX env (libmdbx 0.13.12, WriteMap, MADV_RANDOM, page size 4096).
- benchmarkoor drops the page cache between steps on both arms.
- The two arms replay byte-identical workloads: all 266 BALs decoded, 0 mismatches.
- So every gap is store layout plus content parameters, all on the state-actor side.

| family (>= 0.5 s), after PR1+PR2 | cause | evidence | fix | predicted |
|---|---|---|---|---|
| Account reads, value 0 (1.07-1.10) | HashedAccounts too dense: key-order Append gives fill 0.99; J's organic is 0.59/0.69 | T2: J 94k pages vs S 87k; page ratio 1.086 vs time ratio 1.05-1.10. The distinct-page model reproduces both | Key order + reserve ≈26,300 (leaf 0.59) | 0.945-0.955; S's +21% accounts is a permanent ~5% term at matched fill |
| Code-heavy reads, DIFF_MAX / JUMPDEST (1.09) | Same HashedAccounts effect | HashedAccounts 94.2k vs 86.9k; Bytecodes overflow equal (352k vs 350k) | Same as above | 1.05-1.06: J's far larger Bytecodes B-tree (47k vs 16.5k pages) is a code-population residual, in band |
| CALL / CALLCODE with value (0.90-0.95) and transfers (0.945-1.04) | (a) AccountsTrie written in post-order: fill 0.57 vs J's rebuilt 0.97. (b) Nested-storage walks of mid-size autofill contracts ("other" 13.7-17.4k pages), amplified by random subkey order + prefer_waf. J's contracts are 97.8% inline | AccountsTrie +7.4k pages; sibling storage-root recomputation confirmed in reth's code (roots never stored, no EOA shortcut, a full or partial walk where rows are missing); autofill 98% nested 29-4000 slots | Sorted trie writes; per-contract subkey sort + fill target; PR5 removes the structure | 0.94-0.99 / 0.95-1.02, parity by cancellation; PR5 for a structural match |
| sstore write (0.81-0.83) | The bloated contract's StoragesTrie nested tree is sparse and one level taller (S h8, fill 0.53 vs J h7, 0.97) | Same rows in both (25,758,807); StoragesTrie nested pages S 18.3k vs J 13.0k | Sorted StoragesTrie writes (dense, like J's rebuild) | 0.95-1.03 |
| sload / no-op sstore (1.19-1.20, S faster) | The bloated contract's HashedStorages nested tree is too dense (S 0.99 vs J 0.72) | Nested pages J 95.5k vs S 83.7k | Reserve ≈17,600 (target 0.72) | 1.03-1.06 |

**Cross-cutting generator causes:**
- (i) insertion order per table;
- (ii) libmdbx 0.14.2 defaults `prefer_waf_insteadof_balance=true` where reth's 0.13.12 has false: random-insert fill 0.505 vs 0.661;
- (iii) no fill control;
- (iv) the autofill storage shape: a truncated normal of 254 ± 89 slots measured, with 64-byte rows. Mainnet has p50 = 1 slot, 97.8% inline, and 0.07% of contracts holding 53% of all storage;
- (v) a +21.4% budget in both accounts and slots.

**Reference side:** J v2 is a hybrid, with organic hashed tables (the compacting copy preserved pages exactly) and densely rebuilt tries. Benchmark results move ~10-20% with fill history; every report states the fill profile.

## Anon's three items

1. **libmdbx config.**
   - reth's env is symmetric and stays untouched. The surface is the generator's write-time env:
     - `prefer_waf_insteadof_balance=false`, always and explicitly;
     - `MDBX_opt_split_reserve` per table phase, on sorted phases;
     - key-ordered writes, so the reserve has edge splits to act on.
   - Read back both options and check `mdbx_version >= 0.14.2` when a non-zero reserve is requested. Report achieved fill at the end. Page size stays 4096.
2. **Commits and PRs.**
   - PR branches stay uncommitted worktrees until cycle-1 full-266 results pass acceptance. This is Anon's instruction; it replaces the debate's local unsigned commits.
   - Then commit (key touch), push to the fork, and open draft PRs with:
     - per-family before/after tables and T2 attribution;
     - the fill profile and achieved fills;
     - both libmdbx versions and the prefer_waf difference;
     - the fill-history sensitivity.
   - PR1-PR4 do not wait for cycle 2.
3. **Is it worth trying?**
   - **PR3 (key-ordered writes): yes, unconditionally.** It fixes generator defects independent of J: trie fill 0.57, the extra StoragesTrie level, 2x pages on every autofill nested walk, nondeterministic Bytecodes order. On its own it should move sstore write 0.81 -> ~1.0.
   - **PR4 (fill control): yes, as an explicit opt-in calibration.** It is the only way to make the J comparison fair: account reads 1.10 -> ~0.95, sload 1.19 -> ~1.05.
   - **PR5 (mainnet-shaped autofill storage): yes, staged.** It is the structural fix for CALL with value and transfers, but it changes the state root, so it comes after cycle-1 evidence.

## Decisions

| Decision | Resolution |
|---|---|
| Fill target | `--fill-profile {fresh\|migrated\|aged}` plus a `--fill Table=0.xx` override. Default `fresh` (reserve 0, the generator's canonical dense output); the benchmark passes `migrated`. Profile, reserves, achieved fills, libmdbx version and generator commit are written into the store (metadata table or sidecar) |
| `migrated` values | HashedAccounts 0.59; HashedStorages nested 0.72 for the bloated contract and J's measured mid-size nested fill for autofill (0.70 if unmeasured); main trees organic (no reserve, prefer_waf=false ≈ 0.66); tries dense (reserve 0); Bytecodes organic or J's measured value. `aged` = J v1 (tries ≈0.54, storage 0.70). `fresh` = 0.99 everywhere |
| Cycles | Cycle 1 = PR3+PR4 combined: root-preserving, gated on identical content hashes. Cycle 2 = PR5 + matching J's totals (354.8M accounts / 1.82B slots as a run parameter), only if triggered |
| PR5 timing | Developed during cycle-1 host time; regenerated only if cycle 1 fails acceptance |
| Validation route | Regenerate. No in-place repack, which would duplicate writer logic for comparable hours |
| HashedStorages order | Per-contract in-memory subkey sort; contract order unchanged; no global stream and no external sort (the main tree's target ≈ random-insert fill under prefer_waf=false) |
| Bloated-contract reserve | One HashedStorages reserve (target 0.71), unless step 0 shows J's mid-size nested fill differs from 0.72 by > 0.05; then one reserve per phase, set at write-txn boundaries. No per-key override, no hard-coded address |
| Targeted bench | Dropped. T2 traces (~20 min) gate the full 266. A targeted bench is a fallback only when traces miss the model by > 15% on any table |
| Acceptance | Every >= 0.5 s family median (per-test geomean of the pairs) in [0.909, 1.1], and >= 80% of >= 0.5 s tests in band. A family is "robust" if its median is in band on each pair separately. Cycle 2 triggers on acceptance failure or on >= 2 families failing robustness. Below 0.5 s: reported per family, flagged outside [0.8, 1.25], not gated |
| Stop rule | At most two regenerations. Residuals get T2 attribution in the PRs as known differences. Don't chase < 3% |
| PR split | PR1 and PR2 unchanged in content; PR3 (order) and PR4 (fill) stacked on them; PR5 an independent branch on top of PR4 |

## Step 0: prerequisites (before coding; none deferred)

**Local:**
- **Noise estimate** from the existing A/B data: per test >= 0.5 s, |log(ratio_A / ratio_B)|; median and p90 per family.
- **Read the generator:**
  - write-txn/phase structure per table (are spec and autofill storage separate phases at txn boundaries?);
  - does the autofill writer emit whole contracts or interleave within a batch?
  - HashBuilder emission order (post-order, subtrees completing left to right);
  - is the Bytecodes map complete at write time?
  - the budget parameters behind 430.7M/2.21B, and the 203 ± 68 (spec) vs 254 ± 89 (measured) slot-mean discrepancy; resolve which "1.49B autofill slots" or the bytes->slot conversion is wrong.
- **mdbx-go v0.40.1 option API:** `SetOption`/`GetOption` signatures, whether raw `21` is accepted, and the prefer_waf constant (env.go:110 exists). A cgo shim if needed. Confirm the reserve unit in mdbx.c.
- **benchmarkoor:** does it wait for the setup payload's persistence before the cache drop? If not, record it as a residual asymmetry (fill-dependent split cost in the write tail).
- **Tooling:**
  - (a) Extended sibling attribution: all targets, every ancestor branch's direct-leaf siblings (~6.5 per target), deduped per block, slot counts from HashedStorages descents. Predicted vs measured "other" on both arms; the J consistency check is predicted 0.3-1k vs measured 0.7-1.1k.
  - (b) Per-table sorted-iteration content hash for all five tables (extends `repack -hash`).
  - (c) Fill reporter: dbi_stat for plain tables, a descent sampler for nested trees.

**Host, read-only (~3 h, nothing else running):**
- J's Bytecodes entries, fill and height;
- J's HashedStorages main-tree-only leaf fill (descents);
- J's nested fill for 29-4000-slot contracts (sets the autofill nested target);
- content hashes of all five S-fixed tables, stored as a sidecar (the cycle-1 identity gate);
- the extended attribution run against the existing T2 traces.

## Code changes (state-actor)

**PR3: key-ordered writes (root- and content-preserving).**
- **AccountsTrie / StoragesTrie:**
  - Buffer HashBuilder rows by depth-k prefix: AccountsTrie k=3 (~3k rows, 1.6 MB); bloated StoragesTrie k=2 (~100k rows, 18 MB); autofill tries whole-contract.
  - Sort, and flush when the prefix changes or a shorter (ancestor) key arrives. Ancestors (<= 273 rows) are plain late inserts.
  - If emission turns out not to be contiguous per prefix, fall back to streamsort.
- **HashedStorages:** buffer each contract's slots (or the whole batch, if interleaved), sort by keccak(slot), Put ascending. Contract order is unchanged; the spec path keeps keccak order.
- **Bytecodes:** sort and Put ascending if the map is complete at write time. Otherwise leave the order and exclude Bytecodes from the page-count determinism check.
- Tables are never interleaved within a phase, because the options are env-global (verify in step 0).

**PR4: fill control, stacked on PR3.**
- `prefer_waf_insteadof_balance=false` at env open, read back, independent of profile.
- `--fill-profile` plus a per-table override:
  - the reserve comes from interpolating the measured curve: 0.59 ≈ 26,300; 0.72 ≈ 17,600; 0.70 ≈ 18,900;
  - set it at write-txn boundaries before each phase, idempotently on every txn open;
  - read back `get_option(21)` and check the version; generation fails on any option error.
- HashedAccounts keeps PR1's cursor Append with the reserve active. Contingency: if Append bypasses the reserve locally, switch to sorted plain Put, which is byte-identical at reserve 0.
- Store metadata as in Decisions, plus an achieved-fill report at the end.

**PR5: mainnet-like autofill storage (root-changing).** Flag-gated, default off, two independent switches:
- `--storage-size-model mainnet`: heavy-tailed, calibrated to J (p50 1, p90 11, 97.8% <= 28 slots, 0.07% > 4000 holding ~53% of the budget). Per-contract in-memory sort up to ~10^7 slots, external sort above.
- `--storage-value-model mainnet`: compact values, ~36-byte rows.
- Needs a new fixture version, regenerated against the new head.

## Local verification (1 GB Docker runs, 4 KiB pages)

- **Identity:** PR3 and PR4 at `fresh` and `migrated` keep the state root and all five content hashes byte-identical to main. Two runs give identical content and page counts (Bytecodes excepted if unsorted).
- **Fill:** achieved fill per table within ±0.03 of the profile (dbi_stat), nested fill via descents. Reserve 0 vs 26,300 must change HashedAccounts fill under Append. Re-fit per table if the result deviates > 0.03 from the interpolated curve at real item sizes.
- **Scaling:** in a scaled-down bloated contract, leaf counts scale with fill as predicted.
- **Unit tests:**
  - ascending emission per table and per nested tree, with only ancestor rows out of order;
  - prefix flush when an ancestor arrives;
  - reserve interpolation;
  - option readback and version check;
  - option setting at phase/txn boundaries.
  Fill is asserted only on the 1 GB run, since tiny-scale fill is noise.
- cgo suite in Docker.

## Host cycle 1 (no overlap with any I/O)

1. **Generate** with `--fill-profile migrated` (~4 h). Gate before any bench:
   - state root identical;
   - all five content hashes equal to the S-fixed sidecar;
   - HashedAccounts leaf fill 0.59 ± 0.03, AccountsTrie >= 0.95;
   - bloated HashedStorages nested h5 at 0.72 ± 0.03;
   - bloated StoragesTrie nested h7, >= 0.95, ≈1.28M leaves;
   - autofill nested sample within ±0.04 of target.
   Any miss: fix locally and regenerate; never bench a miscalibrated store.
2. **Prepare:** copy to a virgin image, adopt, gate, smoke (~1.7 h). The existing S fixtures stay valid (same root).
3. **T2 traces** (~20 min): the extended 19 tests, one SHA3 control, and whole-step accounting for sload/sstore (both payloads). Page gate vs the model:
   - account reads: HashedAccounts ≈98-100k (J 94k);
   - CALL with value: HashedAccounts ~31k, AccountsTrie ~47-48k, HashedStorages main ~15-18k, StoragesTrie ~3k, other ~8-11k (J total 104.3k);
   - sstore write: StoragesTrie nested ≈13k (J 13.0k);
   - sload: HashedStorages nested ≈91-93k (J 95.5k);
   - transfers: other ~8-11k.
   Extended attribution must cover >= 80% of "other" on both arms. Any table more than 15% off: stop, attribute and fix before benching.
4. **Full 266**, 2 pairs (~7 h), then apply the acceptance rule.

## Cycle 2 (only if triggered)

- **Setup:** PR5 with both switches on, autofill budget set to J's totals, profile `migrated`. Re-derive the autofill nested target from slots per contract and let libmdbx's subpage rule decide inline vs nested.
- **Gates:** reth recomputes the root and it matches; fills as in cycle 1; fixtures regenerated for 266 tests (cost confirmed in step 0); smoke.
- **T2:** expect other -> ~1k, HashedStorages main -> J-like (~20k, inline-dominated), the account-read term -> ~1.0.
- **Full 266.**

## Reporting (every PR and the results doc)

- per-family before/after tables (both pairs and the geomean) and per-table page attribution;
- fill profile, reserves and achieved fills;
- the structural terms: +21% accounts, the Bytecodes population, J v2's hybrid layout;
- the ~10-20% fill-history sensitivity, and the rule that benchmark results state the profile;
- the status of the write-tail asymmetry;
- the `mdbx_copy -c` locality difference, uncontrolled but neutralised by MADV_RANDOM and direct-io.

## Assumptions to verify (step 0) and risks

- **To verify:**
  - HashBuilder subtree-completion order; the phase/txn structure and no interleaving within a phase; whole-contract emission by the autofill writer; Bytecodes map completeness;
  - the mdbx-go option API and the reserve unit; whether Append honours split_reserve;
  - benchmarkoor's persistence wait; the slot-mean discrepancy; the fixture-regeneration cost for a new root;
  - J's mid-size nested fill and its main-tree fill.
- **Risks:**
  - The reserve curve was measured on synthetic item sizes; the 1 GB gate catches a miss.
  - A 4 h regeneration per miss.
  - The cancellation in the CALL-with-value and transfer families may land just outside the band; PR5 is the structural answer.
  - The Teleport session must be renewed before any host step.

## Order and timing

1. Step 0: local ~1 day; host read-only ~3 h.
2. PR3 + PR4 code, tests and the 1 GB checks: ~1-2 days.
3. Cycle 1 on the host: ~4 h generation + ~1.7 h preparation + 20 min traces + ~7 h bench. PR5 is developed in parallel.
4. Commit, PRs and report, after acceptance and with Anon's key touch.
5. Cycle 2, only if triggered: ~1 host day plus fixture regeneration.
