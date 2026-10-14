# Reth study: finalize (cycle 3)

**Goal.** One last generator round that makes state-actor's reth store mainnet-shaped in accounts as
well as storage, at any target size, measured once more against v2 jochemnet. Then close the study:
article, PRs, host.

## Starting point (2026-10-13)

- Upstream main `1c4aa321` contains PR1-PR5 (#143-#147, merged 10-12).
- Cycle 2: 153/154 tests >= 0.5 s in band, every family robust, 114/114 over a second on both pairs.
- Known gaps, each measured:

| gap | evidence | tests it touches |
|---|---|---|
| account rows 5.2% bigger | same 354.8M rows and fill; +3.9% leaves; +3.3% pages on account reads | account reads (64, **0.970**), smaller share of transfers and code-heavy |
| account shape | mainnet: 19.1% code-bearing, 62% of those storage-less proxies (65 B code, heavy reuse), 0.5% delegations; median nonce 1, balance 0. state-actor: 9.9%, 2% storage-less, 18%; nonce ~500, ~390 ETH | same as above |
| StoragesTrie top-level tree 43% vs 77% full | random contract order; +2.1k pages per value-transfer test | 48 value-transfer tests |
| storage tail capped at 2^24 | 4 mainnet contracts (13.5% of slots) replaced by 9.8% more contracts; tail is a power law (alpha ~1) | none today; grows with target size |

## Changes: three state-actor PRs on main (unsigned trees until results; Anon signs)

**A. Scale-free storage model** (rework of #147, branch `autofill-storage-tail`).
- Measured table up to 1M slots, kept in memory.
- Above 1M slots: an alpha=1 power law. Giant sizes are stratified quantiles in integer arithmetic,
  truncated at 1M x n, and written as streamed PreAlloc entities. No cap; the largest contract grows
  with the store.
- Calibration is an embedded JSON plus a Go tool (`scripts/storage-calibration`) that re-derives it
  from any reth node. `--storage-model` accepts a calibration path.
- **Status: done, unsigned tree `489a2b68`** (22 files).
  - Unit, cgo and reproduce tests pass.
  - At 3 GB, two reth runs and geth give the same root, `0x10c7eae7…`.
  - The 2 planned giants were measured in the store at the formula's sizes.
  - The calibration tool on that store matches mainnet's body shares within 0.0003.
  - `normal`-model roots are unchanged.
  - Tail sum on mainnet's own count: 0.8% off. Plan at 1 TB: 301 giants, the largest 201M slots.
  - Review detail: the embedded calibration is the full exact histogram (20,474 lines, 323 KB). It
    could be compacted if the diff size matters.

**B. StoragesTrie rows in address order** (reth writer). Spill `(addrHash, row)` to the existing
streamsort and append them after all contracts, as PR1 does for accounts. Contents and root unchanged.
Expected: top-level tree ~0.77 full; about 2k fewer pages per value-transfer test.

**C. Mainnet account shape** (new `--account-model=normal|mainnet|<file>`; recommended over folding
everything into one flag). Same calibration file, with an accounts section derived by the same tool:
- EOA and contract nonce/balance drawn from mainnet quantiles;
- storage-less contracts at mainnet's share, with codes from a small, heavily reused pool of tiny
  proxies;
- delegations at the measured rate (about 0.5% of accounts) instead of the 2% floor.

Platform-identical draws (quantile tables, fixed draw count per account), cross-client root parity
test. Expected: account rows match, so account reads 0.970 -> ~1.00. Smaller shifts on families whose
pages are partly HashedAccounts.

Each PR: unit tests, cgo suite, two-run determinism, geth = reth root at a size with giants, 1-3 GB
shape checks with the calibration tool.

## Cycle 3 on the host (one regeneration, one bench; ~16 h)

1. Build main + A + B + C into `localhost/state-actor-reth:final`.
2. Size: compute (plan-only) the target size that gives jochemnet's 354,792,873 accounts under the
   new per-account cost.
3. Generate. Every gate aborts the run:
   - fill (gatecheck; StoragesTrie top tree >= 0.70);
   - storage shape (distgate, tail included);
   - account shape vs jochemnet (acctsize/acctkind: value bytes +-3%, code-bearing share and its
     split +-2 points);
   - `reth db repair-trie` with 0 inconsistencies.
4. mkvirgin and adopt as S. Keep the cycle-2 virgin until cycle 3 passes.
5. Refill the fixtures with reth, smoke, then T3 traces plus classify.
6. Run 266 x 2 pairs (`kj1 ks1 kj2 ks2`), then reduce.
7. Collect C20 (cycle 3 vs cycle 2, per family and per traced table).

## Acceptance / stop rule

- Report the result whatever it is. Success means:
  - >= 153/154 gated tests in band and every family robust;
  - account reads median within +-2% of 1.00;
  - no family moving more than 2% further from parity than in cycle 2 (the noise floor is ~1.5-2%).
- If account reads doesn't move as predicted, attribute it with T3 HashedAccounts pages and stop.
  No cycle 4.

## Finalize

- Article: update to the final store (the progression gains cycle 3; finding 5 extends to accounts).
  **Publish after cycle 3** (recommended) rather than now; then one signed commit.
- PRs A, B, C as drafts on upstream main with cycle-3 numbers; Anon signs; no merges by me.
- Host: after cycle 3 passes, wipe the cycle-2 S virgin and fixtures. Keep J and the final S.
- Vault: ledger "Cycle 3", project file closing state, methodology wiki (account shape rule),
  session log.

## Risks

- New tables must draw identically on every platform. The geth = reth root parity tests gate it.
- Giants go through PreAlloc in all six writers, but only geth and reth are tested end to end.
- The fixed account/storage budget split means slots can land +-5% off jochemnet's when accounts are
  matched. This is stated as known.
- Teleport expires mid-run (re-login), and the host reboot from 10-08 is still pending (it would kill
  the run).

## Decisions for Anon

1. Account flag: separate `--account-model` (recommended) or one combined flag?
2. Publish the article now (cycle 2) or after cycle 3 (recommended)?
