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
## Round 1 — is state-actor's read path doing more work?

**Hypothesis.** state-actor holds 22% more trie (597 M vs 489 M account
nodes, 3.03 B vs 2.47 B storage nodes) in the same cache budget, so each
account read fetches more nodes and/or reaches disk more often. That would
produce a roughly uniform penalty on all state-touching execution.

**Test.** Boot each store under an ephemeral overlay with `--metrics`, drop
the OS page cache, then issue an identical 300-address `eth_getProof`
workload and diff geth's own pathdb meters. The addresses are a fixed
pseudorandom set: they need no trie preimages (state-actor has none), they
are byte-identical work on both arms, and they exercise the absence path -
the NON_EXISTING category, whose offset (1.247x) is as large as any other.
Counters, not milliseconds: the surviving state-actor copy is on HDD.

**Result.**

| measure | jochemnet | state-actor |
| --- | --- | --- |
| proof depth min / median / max | 7 / 8 / 9 | 7 / 8 / 9 |
| absence reads, total | 1200 | 1200 |
| absence reads served from disk | 300 | 300 |
| disk fraction | 0.25 | 0.25 |
| trie nodes fetched | 2641 | 2662 |
| nodes per read | 8.80 | 8.87 |
| clean node hit / miss | 1017 / 1624 | 1017 / 1645 |
| ms per read | 2.70 | 84.36 |

**Verdict. REFUTED.** The two stores demand the same logical read work -
same depth, same node count within 0.8%, same disk fraction. The 22% larger
trie costs nothing measurable per lookup, exactly as the depth arithmetic
predicted (22% more nodes is ~0.07 of a trie level).

Two by-products worth keeping:

- The 31x wall-clock spread (2.70 vs 84.36 ms per read) is the NVMe/HDD
  confound, now quantified. It is not a property of the databases, and it
  rules out timing comparisons between the current copies for good.
- Proof depths are now measured on **both** stores, not just jochemnet. The
  article's "Trie shape" subsection can finally say that honestly.

**What this leaves.** The gap is not node-fetch volume on the absence path.
Either it is in a path this probe does not touch - existing-account reads,
storage slots, or contract code (state-actor holds 48.98 GiB of code in
134 M entries against jochemnet's 17.25 GiB in 2.4 M, a 55x difference in
entry count) - or it is not logical work at all but cost per unit of work.

## Round 2 — I/O volume vs CPU, on symmetric hardware

**Hypothesis.** Round 1 removed logical node count as the cause on the
absence path. Either state-actor moves more bytes per unit of work, or burns
more CPU, or neither (and the original offset was a property of the original
operator's host). Our own reproduction settles it: both arms ran on NVMe
schelk loop volumes on the same RAID pair, and the harness records per-test
`disk_read_bytes`, `disk_read_iops` and `cpu_delta_usec`.

**Test.** Join our two full reproduction runs on (opcode, mode, gas),
value_sent=0, non-baseline, and normalise every resource counter by the gas
actually executed. 528 cells joined, 440 of them non-DIFF_MAX.

**Result — honest modes:**

| per Mgas | jochemnet | state-actor | ratio | paired |
| --- | --- | --- | --- | --- |
| throughput (MGas/s) | 18.93 | 16.81 | 0.888 | 0.889 |
| disk read (kB) | 19,125 | 22,389 | **1.171** | 1.172 |
| read IOPS | 2,135 | 2,425 | 1.136 | 1.133 |
| CPU (us) | 79,003 | 97,797 | **1.238** | 1.227 |
| disk write (kB) | 4.98 | 2.95 | 0.592 | 0.682 |

**Per mode** (state-actor ÷ jochemnet): the read-volume penalty is uniform -
NON_EXISTING 1.170, EOA 1.172, MINIMAL 1.168, SAME_MAX 1.168, JUMPDEST 1.286,
DIFF_MAX 3.659. CPU tracks it: 1.220 / 1.236 / 1.238 / 1.236 / 1.161 / 2.217.

**Verdict. CONFIRMED that state-actor does more work** - and the offset
reproduces on symmetric hardware, so it is not an artifact of the original
operator's host. It reads 17% more bytes, issues 14% more read operations and
burns 24% more CPU for the same executed gas.

**The contradiction that defines round 3.** Round 1 measured *identical*
logical node fetches per lookup (8.80 vs 8.87) on the absence path, yet the
real workload moves 17% more bytes. Both cannot be true unless the extra
bytes are spent **per node fetched**, not on extra nodes: larger nodes,
larger physical blocks per node, or more index/filter reads per node. The
inspect data is consistent with the first - state-actor's storage trie nodes
average 119.7 B against jochemnet's 107.3 B (+11.5%), and its account nodes
127.7 B against 123.3 B (+3.5%). CPU rising faster than bytes (1.238 vs
1.171) also fits: bigger nodes cost more to decode.

## Round 3 — where do the extra bytes go? (first attempt: instrument failure)

**Hypothesis.** If the node count is equal but the byte count is not, the
extra bytes are spent inside the storage engine: more pebble blocks touched
per trie node, or less effective bloom filtering.

**Test.** Extend the round-1 probe to also diff geth's pebble meters
(`cache/block/{hit,miss}`, `cache/table/{hit,miss}`, `filter/{hit,miss}`,
`disk/read`).

**Result — INVALID, and worth recording.** jochemnet reported 246 block-cache
lookups against 2641 node fetches, which is impossible. geth refreshes the
pebble gauges from a background timer, and the jochemnet workload finishes in
0.8 s - inside a single refresh interval - while the state-actor workload
takes 98 s on HDD and spans many. The comparison measured sampling windows,
not databases.

**Fix.** Settle 12 s before the baseline scrape and 12 s after the workload,
so both snapshots are refreshed. Re-run as round 3b.

## Round 3b — the storage engine, measured properly

**Result.**

| measure | jochemnet | state-actor |
| --- | --- | --- |
| trie nodes fetched | 2641 | 2662 |
| block-cache hit | 2282 | 2193 |
| block-cache miss | 3490 | **9694** |
| **pebble block lookups per node** | **2.19** | **4.47** |
| block-cache miss rate | 60.5% | 81.6% |

**Verdict. CONFIRMED, and the layer is now located.** For the same logical
trie work, state-actor asks the storage engine for **2.04x more blocks per
node** and misses the block cache on 2.78x more of them. The trie is not the
problem; the LSM underneath it is. This is exactly the shape needed to
explain round 2: more physical reads (+17% bytes, +14% IOPS) and more CPU
(+24%, from decompressing, checksumming and binary-searching more blocks)
for identical logical work.

`filter/hit` and `filter/miss` stayed at zero on both arms, so bloom
effectiveness could not be read directly and remains untested.

**The obvious suspect for round 4.** A pebble Get probes candidate SSTables
level by level; a well-compacted store has few overlapping files and a
mostly-L6 shape, an uncompacted one has many. The jochemnet arm is
*compacted* - the article's whole "compacted" label, plus our own post-drain
`geth db compact`. The state-actor store has **never been compacted**: it was
written by the generator and benchmarked as-is. We may simply be comparing a
compacted LSM against an uncompacted one.

