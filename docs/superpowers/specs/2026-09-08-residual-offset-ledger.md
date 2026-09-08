# Residual-offset investigation ledger — why is state-actor ~10% slower?

One entry per round: hypothesis, why it is plausible, the test, the result, the
verdict. Committed after every round. Hard cap 50 rounds or root cause,
whichever comes first.

**The target.** After the journal artifact was found and fixed, a residual gap
remains between the two arms on *every* category: slope ratio (state-actor ÷
compacted) 1.031–1.117x, median **1.091x**; per-test `total_ms` ratio ~1.21x
(the difference between the two figures is the fixed per-block intercept, which
the slope fit removes). It reproduces post-fix: the verdict run's MINIMAL
control sits at 1.10–1.14x.

---

## Round 0 — where the time goes (no new runs; committed logs only)

**Method.** Re-parsed the three original run logs with the report's own parser
(`investigate_offset.py`, committed beside this ledger), splitting per-test
`total_ms` into its phases at matched (opcode, mode, gas), with the
`overhead_baseline` tests as a control that performs no account-state work.

**Result — the control (165 baseline tests):**

| baseline (no state work) | compacted | uncompacted | state-actor |
| --- | --- | --- | --- |
| median `execution_ms` | 33.06 | 33.80 | 32.94 |
| median `total_ms` | 40.76 | 36.49 | 39.52 |
| per-test ratio vs compacted | — | 0.991 | 0.900 |

Harness, RPC and EVM overhead are identical across arms (2.6% spread). The
same-database control (uncompacted ÷ compacted — literally the same bytes)
has median 0.991 but an interquartile range of **0.868–1.059**, so per-test
ratios carry ±10% noise; only aggregated slopes resolve an effect this size.

**Result — phase split, non-DIFF_MAX tests (n=142):**

| phase | compacted | state-actor | ratio | paired median |
| --- | --- | --- | --- | --- |
| `execution_ms` | 1354.30 | 1647.22 | **1.216** | 1.240 |
| `state_hash_ms` | 0.58 | 0.12 | 0.215 | 0.223 |
| `commit_ms` | 11.44 | 7.56 | 0.661 | 0.678 |
| `total_ms` | 1437.09 | 1744.02 | 1.214 | 1.235 |

**Result — `execution_ms` ratio (state-actor ÷ compacted) per account mode:**

| mode | ratio | n |
| --- | --- | --- |
| NON_EXISTING | 1.247 | 22 |
| EOA | 1.254 | 22 |
| MINIMAL | 1.237 | 33 |
| SAME_MAX | 1.248 | 32 |
| JUMPDEST | 1.201 | 33 |
| DIFF_MAX | 1.872 | 33 |

**Verdict.** The gap lives **entirely inside EVM execution**. state-actor
*commits faster* (0.66x) and hashes faster (0.22x), so the write path is not
it; baseline execution is identical, so the harness is not it. Gas is matched
exactly (median `gas_used` 199,997,736, 12 txs, all three arms), so the same
work is being compared.

Killed this round: harness overhead, RPC round trips, gas accounting,
block/tx count, commit path, trie-hash path.

**The shape of what is left.** The ratio is *flat* at 1.20–1.25x across all
five honest modes — including NON_EXISTING, whose target addresses exist in
neither database. A size- or depth-driven effect should vary by class; perfect
uniformity points instead at a constant per-access cost in the state-read
path. (Note this also refutes the article's current claim that the offset
"cannot be a state-layout effect because NON_EXISTING has no state": an
absence proof still walks the trie. The claim needs rewriting whatever the
outcome here.)

**Instrumentation note.** The harness cannot attribute this: `state_reads.
accounts` is a constant 4.0 on every arm and the cache counters are absent.
Attribution has to come from geth's own pathdb meters.

---

## Constraints discovered before round 1

- **The state-actor schelk volumes are gone.** `/schelk-vols/` holds only
  `jochemnet-{virgin,scratch}.img` (md2, NVMe). The surviving state-actor copy
  is `/data/sa-store/state-actor/v1/geth` on **md3, the HDD array**. During the
  actual runs both arms sat on NVMe schelk volumes, so any wall-clock read
  comparison between the *current* copies measures NVMe vs HDD and is
  worthless. Every round below must therefore compare **device-independent**
  quantities (node fetches, disk-hit fractions, proof depths, counters), or
  first restore state-actor to NVMe.
- **state-actor has no trie preimages** (`Trie preimages` 0.00 B / 0 entries;
  jochemnet has 17.81 GiB / 266 M). Its accounts cannot be enumerated back to
  addresses, so probes must use address-independent reads.
- Available instruments (geth `--metrics`, `/debug/metrics`):
  `pathdb/state/account/{exist,inex}/{total,disk}` — reads that reached disk;
  `pathdb/clean/{node,state}/{hit,miss}`; `pathdb/dirty/{node,state}/{hit,miss,depth}`.

---
