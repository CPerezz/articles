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

## Round 4 — is jochemnet compacted and state-actor not?

**Hypothesis.** A pebble Get probes candidate SSTables level by level. The
jochemnet arm is compacted; the state-actor store never was. If its LSM has
overlapping levels, every lookup probes more files - which is exactly the
2.04x block-probe ratio round 3b measured.

**Test.** (a) SST inventory and size histogram of both stores. (b) The live
LSM shape from geth's `eth/db/chaindata/tables/levelN` gauges.

**Result.**

| | jochemnet | state-actor |
| --- | --- | --- |
| SST files | 8,515 | 11,304 |
| mean SST size | 45.4 MB | 49.9 MB |
| size 32-80 MB | 85% | 84% |
| **tables in L0-L5** | **0** | **0** |
| **tables in L6** | **8,515** | **11,304** |

**Verdict. REFUTED.** Both stores are perfectly compacted - a single sorted
run, every table in L6, nothing above it. The state-actor generator leaves a
fully compacted store behind. LSM shape is not the difference.

## Round 5 — round 3b was measuring boot history

**Hypothesis.** Round 3b's table-cache numbers (0 misses vs 3,026) look like
cache thrash, but the container's `ulimit -n` is 1,048,576, so geth allocates
~524,288 handles on both arms - far more than either store's file count. Those
"misses" are therefore *first-touch opens*, and jochemnet simply happened to
have opened all 8,515 of its SSTables during boot while state-actor had not.
If so, the 2.04x collapses once both nodes are warm.

**Test.** Re-run with a 1,500-read warm-up before the measured 1,000 reads,
so both arms are measured in steady state rather than in their boot
transient.

**Result.**

| measure | jochemnet | state-actor |
| --- | --- | --- |
| nodes per read | 8.80 | 8.87 |
| table-cache misses per node | 0.000 | 0.040 |
| block lookups per node | 1.84 | 1.93 |
| block-cache miss rate | 48.7% | 52.1% |

**Verdict. Round 3b's 2.04x is RETRACTED** - it was a boot-history artifact,
not a property of the databases. In steady state the storage engine does only
~5% more work per node on state-actor, which is far too small to carry a 17%
byte difference.

**And it exposes a flaw in rounds 1, 3 and 5 alike.** `eth_getProof` forces
the *trie* path. The EVM does not read accounts that way: it reads the **flat
snapshot**. Every probe so far has measured the wrong keyspace.

The inspect data for the right keyspace is suggestive on its own:

| account snapshot | jochemnet | state-actor |
| --- | --- | --- |
| size | 16.40 GiB | 23.38 GiB |
| entries | 354,792,873 | 430,696,738 |
| **bytes per entry** | **49.6** | **58.3 (+17.4%)** |

Round 2 measured disk read bytes per Mgas at **+17.1%**. That is a very close
match to a structural prediction, and it is the hypothesis for round 6:
state-actor's account records are simply fatter, because a generated bloatnet
is full of contracts carrying a storage root and a code hash, while a mainnet
snapshot is dominated by lean EOAs whose slim encoding omits both.

## Round 6 — are state-actor's account records fatter?

**Hypothesis.** The EVM reads accounts from the flat snapshot, and a snapshot
account is slim-encoded: an EOA drops its empty storage root and code hash, a
contract carries 33 bytes of each. A generated bloatnet should be far more
contract-heavy than a mainnet snapshot, so every account read moves more
bytes.

**Test, first attempt — FAILED.** `debug_accountRange` timed out on both arms
(`-32002 request timed out`): it seeks a multi-hundred-GB trie from a random
start key. Replaced with a direct measurement, which is better anyway - it
reads the true on-disk value bytes instead of estimating an encoding.
`snapstat` (committed beside this ledger) iterates the account-snapshot
keyspace and decodes each record. Account hashes are uniformly distributed, so
the first 200,000 in hash order are an unbiased sample.

**Result.**

| account snapshot | jochemnet | state-actor |
| --- | --- | --- |
| sampled | 200,000 | 200,000 |
| mean value bytes | 16.61 | **25.29 (+52%)** |
| median value bytes | 11 | 16 |
| p90 value bytes | 37 | 48 |
| accounts with a code hash | 19.2% | **31.3%** |
| accounts with a storage root | 7.0% | 1.8% |
| **plus the 33-byte key = bytes per entry** | **49.6** | **58.3 (+17.4%)** |

**Verdict. CONFIRMED, and it reconciles two independent measurements.** The
direct scan (16.61 vs 25.29 value bytes) plus the 33-byte key reproduces the
`db inspect` figures (49.6 vs 58.3 B/entry) exactly, and that +17.4% sits on
top of round 2's measured **+17.1%** disk-read penalty per Mgas.

The composition explains why: state-actor's state is 31.3% code-bearing
accounts against jochemnet's 19.2%, because a generated bloatnet is built
out of contracts while a mainnet snapshot is mostly lean EOAs. Interestingly
the storage-root fraction runs the other way (1.8% vs 7.0%) - state-actor's
contracts carry code but almost no storage.

**Caveat, and the job for round 7.** A numeric coincidence is not a causal
chain. Fatter records explain more bytes only if the reads are dense enough
for record size to drive block traffic; for purely random point lookups every
read costs one ~4 KB block whatever the record size, and the relevant quantity
would instead be total snapshot size (16.40 vs 23.38 GiB, +43%) against the
block cache. Round 7 must measure bytes actually read per account lookup
rather than infer it.

## Round 7 — does state-actor's data compress worse?

**Hypothesis.** Round 5 showed the storage engine does only ~5% more logical
work, yet round 2 measured +17% physical bytes. If the block count is nearly
equal, the bytes per block must differ - i.e. one store's data compresses
worse. A record carrying a 32-byte code hash is near-incompressible; a lean
EOA record is mostly zeros and small integers.

**Test.** Logical bytes (summed from the `db inspect` key-value rows) against
physical bytes (summed SST file sizes), per store.

**Result.**

| | logical KV | physical SST | physical / logical |
| --- | --- | --- | --- |
| jochemnet | 521.1 GiB | 377.3 GiB | **0.724** |
| state-actor | 674.3 GiB | 550.8 GiB | **0.817** |

Per key-value record: jochemnet 91.4 B logical / **66.2 B physical**;
state-actor 113.0 B logical / **92.3 B physical**.

**Verdict. CONFIRMED.** state-actor stores **12.8% more physical bytes per
logical byte**. Composed with round 5's +4.9% block probes per node:

    1.128 x 1.049 = 1.184 predicted   vs   1.171 measured (round 2)

Within 1.3 points of the measured penalty, from two independently measured
quantities.

## Round 8 — entropy or configuration?

**Hypothesis.** Worse compression could be a *setting*, not a property of the
data: the state-actor store was written by state-actor's own geth build,
which might have configured pebble differently. That distinction matters
enormously - a setting is a bug to fix, entropy is a fact about the state.

**Test.** Read the compression name and option string out of the largest SST
of each store.

**Result.** Both report `Snappy`, with byte-identical option strings
(`window_bits=-14; level=32767; strategy=0; max_dict_bytes=0;
zstd_max_train_bytes=0; enabled=0`).

**Verdict. Configuration is identical; the difference is the data itself.**

---

## Round 9 — composition, or fatter records of every kind?

**Hypothesis.** If composition drives it, then *per account type* the records
should cost the same on both stores and only the mix should differ. If
records are fatter within a type too, the story needs refining.

**Test.** Split the round-6 scan by account type.

**Result.**

| | mean | EOA records | contract records | contract share |
| --- | --- | --- | --- | --- |
| jochemnet | 16.61 B | **8.87 B** | 49.24 B | 19.2% |
| state-actor | 25.29 B | **14.68 B** | 48.56 B | 31.3% |

The decomposition reproduces both means exactly: 0.192x49.24 + 0.808x8.87 =
16.62, and 0.313x48.56 + 0.687x14.68 = 25.29.

**Verdict. PARTLY CONFIRMED, and the cause is broader than composition.** A
contract record costs the same in both databases (49.24 vs 48.56 B, -1.4%),
so contracts are not the differentiator by themselves. But state-actor's
*EOA* records are **65% fatter** (14.68 vs 8.87 B) - its generated accounts
carry substantial balances and nonces, where mainnet is full of near-empty
accounts whose RLP is a couple of bytes.

Holding state-actor's mix but giving it jochemnet's EOA size yields 21.29 B,
so of the 8.68 B excess roughly **4.68 B (54%) is composition** (more
contracts) and **4.00 B (46%) is that its EOAs are individually heavier**.

# ROOT CAUSE (found at round 8 of 50, refined at round 9)

The residual ~10% is **not a benchmark artifact and not a database defect**.
It is a real, quantitatively explained property of the two datasets:

1. **The gap lives in EVM execution, in the state-read path.** Harness, RPC,
   gas accounting, commit and trie-hash paths are all identical or favour
   state-actor (round 0). It reproduces on symmetric NVMe in our own
   reproduction, so it is not the original operator's host (round 2).
2. **It is not extra logical work.** Same trie depth (8), same nodes per
   lookup (8.80 vs 8.87), same disk-hit fraction, same fully-compacted LSM
   shape - every table in L6 on both (rounds 1, 4, 5).
3. **state-actor's records are fatter, for two reasons.** Mean snapshot
   account record 25.29 B vs 16.61 B; with the 33-byte key, 58.3 vs 49.6 B
   per entry, **+17.4%** (round 6). Round 9 splits that: 31.3% of its
   accounts carry a code hash against jochemnet's 19.2% (54% of the excess),
   and its EOAs are individually 65% fatter - 14.68 vs 8.87 B, because
   generated accounts carry real balances where mainnet is full of
   near-empty ones (46% of the excess). A contract record itself costs the
   same on both stores.
4. **And they compress worse, for the same reason.** A 32-byte code hash is
   high-entropy and near-incompressible, while an EOA record is small
   integers and zero padding. Same Snappy settings on both stores, yet
   physical/logical is 0.817 vs 0.724 - **+12.8% physical bytes per logical
   byte** (rounds 7, 8).
5. **So every block read moves more bytes.** With ~5% more block probes on
   top, the predicted penalty is 1.184 against a measured 1.171 in disk read
   bytes per Mgas, 1.238 in CPU (decompressing and checksumming more bytes),
   and 0.888 in throughput (round 2).

**What this means for the benchmark.** Unlike the DIFF_MAX anomaly, there is
nothing to fix here. Comparing a generated bloatnet against a mainnet
snapshot compares two genuinely different state compositions, and the
denser, more contract-heavy one costs ~10% more per unit of gas to read. The
honest statement is "state-actor's state is heavier, so reads cost more", not
"the benchmark is biased". The corollary for the article: its current claim
that this offset "cannot be a state-layout effect because NON_EXISTING has no
state" is wrong twice over - an absence proof still walks the trie, and the
penalty is a per-block property of the whole store, which is exactly why it
is uniform across every account mode.

**What is not fully accounted for.** The composed prediction overshoots
slightly (1.184 vs 1.171), and ~4 points of the penalty could equally be a
page-cache hit-rate effect from the larger store (23.38 vs 16.40 GiB of
account snapshot) rather than compression alone. Separating those two would
need a store with matched composition but different size, which does not
exist here.

**What would falsify this.** Re-encode the state-actor snapshot with
jochemnet's record-size distribution - same account count, mainnet-shaped
balances and code-hash share - and the penalty should fall to roughly the
block-probe residual (~5%). Round 9 already supplies the strongest available
version of that test: per account type the records cost the same, and the
whole difference is carried by the mix and by how heavy an average EOA is.

## Round 12 — is it block-cache pressure from more SSTables?

**Hypothesis.** state-actor has 33% more SSTables (11,304 vs 8,515), each with
index and filter blocks competing for one fixed block cache. More metadata
than the cache holds would raise misses per lookup - linear in store size,
not logarithmic in tree depth, which answers the objection that a 21% bigger
tree is only 0.07 of a trie level.

**Test.** Re-run the steady-state probe on both stores at `--cache 512` and
`--cache 16384`. If cache pressure drives it, the gap must shrink at 16 GB.

**Result.**

| cache | store | nodes/read | blocks/node | misses/node | miss rate |
| --- | --- | --- | --- | --- | --- |
| 512 MB | jochemnet | 8.80 | 1.84 | 0.895 | 48.7% |
| 512 MB | state-actor | 8.87 | 1.85 | 0.925 | 50.0% |
| 16 GB | jochemnet | 8.80 | 1.84 | 0.895 | 48.7% |
| 16 GB | state-actor | 8.87 | 1.85 | 0.925 | 50.0% |

**Verdict. REFUTED.** A 32x larger cache changes nothing - these are
compulsory cold misses on a 500 GB store, so cache size is irrelevant. And
with the cache flag set explicitly the gap is only **+3.4%** (0.895 vs 0.925),
not the +12% round 5 suggested. Note also that jochemnet carries ~54 GiB of
transaction index, log index and preimages that the benchmark never reads -
dead weight inflating its file count while it remains the *faster* arm, which
independently kills any file-count story.

## Round 13 — physical bytes per cold read

**Hypothesis (the rounds 6-9 story).** Fatter, less compressible records mean
each block read moves more physical bytes.

**Test.** Sample real account hashes across the *whole* keyspace (500 seek
points, not a contiguous prefix), close the store to discard pebble's block
cache, drop the OS page cache, reopen, then read 5,000 at random and measure
`/proc/self/io` read_bytes. md3's readahead was temporarily set to 128 KB to
match the loop device, then restored.

Three earlier attempts at this measurement were wrong and are recorded as
such: a contiguous sample (fits in cache), no store reopen (pebble's own
cache retains the blocks), and unrefreshed gauges.

**Result.**

| cold random account read | jochemnet | state-actor |
| --- | --- | --- |
| mean value bytes | 17.00 | 25.53 |
| **physical disk bytes per read** | **5,056** | **5,079 (+0.5%)** |
| us per read | 91.9 (NVMe) | 4,608 (HDD) |

**Verdict. ROUNDS 6-9 ARE RETRACTED.** A point lookup pulls one ~5 KB block
whatever the size of the records inside it. Fatter records and worse
compression therefore do **not** produce more physical bytes per read - the
measured difference is 0.5%, not 17%. The round-7 agreement between +12.8%
physical/logical and the +17.1% penalty was a coincidence, and the aggregate
ratio it rested on was confounded anyway: jochemnet holds ~54 GiB of index
and preimage data that state-actor lacks entirely, so that ratio partly
measured category mix rather than compressibility.

The original objection stands and is now backed by measurement: **a 21%
larger tree cannot cost 10%, and it does not.**

## Round 14 — eliminating the client

**Test.** Diff the actual client invocation between the two reproduction runs.

**Result.** Byte-identical: `cache=2.00GiB handles=524,288`, `clean=1023.00MiB
dirty=1.00GiB`, `triecache=1023.00MiB statecache=0.00B buffer=256.00MiB
state-history="last 90000 blocks"`, `gas cap 50,000,000`, same build. Also
worth noting `statecache=0.00B` on both: the flat-state clean cache is
disabled, so every snapshot read goes to pebble.

**Verdict. Client configuration eliminated.**

### Where this leaves the investigation

A genuine contradiction, stated plainly:

- identical logical work per lookup (nodes 8.80 vs 8.87, depth 8, same disk fraction)
- identical physical bytes per cold lookup (5,056 vs 5,079)
- identical lookup count per test (same salts, same 5,393-iteration loop, same gas)
- identical client configuration
- yet **+17.1% bytes, +13.6% IOPS, +23.8% CPU per Mgas** in the real runs

At least one of those four "identical"s must be false under the real
workload. The probes so far test *random* accounts; the benchmark reads
*specific* CREATE2 receivers. Round 15 must measure the real addresses.

## Round 15 — replay the real block (blocked)

**Test.** Send the fixture's own `engine_newPayload` to a node booted on each
store and diff the pathdb meters.

**Result.** `SYNCING` on both. The fixture payload is block 24,410,465 while
the promoted head is 24,410,463 - the anchor block between them comes from the
pre-run bundle, not the test fixture. Reconstructing it was not worth the
detour; round 16 gets the same information without chain surgery.

## Round 16 — run the benchmark's own EVM loop

**Test.** Lift the receiver-walking runtime bytecode out of the fixture's
*setup* payload (`setupEngineNewPayloads`, not the measured one), install it
with an `eth_call` state override, and hand it the same (start, end)
calldata. That executes the identical opcode sequence over each arm's real
CREATE2 receivers.

**Result.** Both arms read real existing accounts (jochemnet 5,394 before the
gas cap; state-actor 179 before the 5 s RPC timeout - it is on HDD). Two
findings matter far more than the counts:

- `trie_nodes` = **1** on both. Account reads are served by the **flat
  snapshot**, one read per account - *not* the 8-9 node trie walk every
  earlier probe was measuring. Rounds 1, 3, 5 and 12 were exercising the
  wrong path entirely.
- `from_disk` = 5,395 of 5,395. With `statecache=0.00B` (round 14),
  **100% of account reads go to pebble**. Nothing is cached in geth.

So per test the cost is simply 53,930 flat reads x bytes-per-read.

## Round 17 — does the penalty depend on scale?

**Test.** Cold physical bytes per read at 5,000 vs 54,000 reads, readahead
matched at 128 KB on both devices.

| reads | jochemnet | state-actor | ratio |
| --- | --- | --- | --- |
| 5,000 | 9,193 B | 9,800 B | 1.066 |
| 54,000 | 1,454 B | 1,483 B | 1.020 |

**Verdict. Hypothesis refuted, and the probe indicted.** The ratio *shrinks*
with scale, the opposite of the readahead-reuse prediction. The absolute
collapse (9,193 -> 1,454 B/read) exposes why: the sample was drawn as 500
contiguous runs, so at scale most reads land in a window some earlier read
already fetched. That access pattern is far more clustered than the
benchmark's, whose CREATE2 targets are uniform over the keyspace.

## Round 18 — the right access pattern

**Test.** Same cold measurement, but reading **uniformly random hashes** over
the whole keyspace, 54,000 of them, readahead matched.

| 54,000 uniform-random reads | jochemnet | state-actor |
| --- | --- | --- |
| physical disk bytes per read | 9,975 | **11,150** |
| ratio | — | **1.118** |

**Verdict. The effect is real and reproducible outside the benchmark**:
+11.8% physical bytes for one uniformly-random account read, against the
benchmark's +17.1% bytes and its 0.888 throughput ratio (i.e. jochemnet
12.6% faster). Round 13's null result was an artifact of the clustered
sample, so its retraction of the record-density story was itself too hasty -
the story survives, but only when measured with a representative access
pattern.

---

# ROOT CAUSE — corrected statement (round 18)

**It is not tree depth, and the original objection was right to reject that.**
state-actor's state is 21% larger, which is 0.07 of a trie level - worth
about 1%, nowhere near 10%. Depth was never the mechanism.

The mechanism is that **account reads do not walk the tree at all**:

1. The EVM reads accounts from the **flat snapshot**, one key-value read per
   account, and with `statecache=0.00B` every one of them reaches pebble
   (round 16). There is no logarithmic term in the cost - it is one physical
   read per account, flat.
2. Each such read pulls a physical block whose size is set by the *data*, not
   the tree. state-actor's snapshot records are **58.3 B/entry against
   jochemnet's 49.6** (round 6), and the excess is high-entropy 32-byte code
   hashes that Snappy cannot compress - identical compression settings on
   both stores (round 8).
3. Measured directly with a benchmark-representative access pattern, that
   costs **+11.8% physical bytes per account read** (round 18), against the
   benchmark's +17.1% bytes, +13.6% IOPS and 11% throughput deficit.

So the residual ~10% is linear in *record density*, not logarithmic in state
size - which is exactly why a 21% bigger tree can carry a 10% penalty without
any contradiction. Every account read costs one block; state-actor's blocks
carry fewer useful accounts per byte.

**Still not fully closed.** The probe accounts for ~12 of the ~17 points.
The remainder is unattributed, and the decisive experiment is blocked by
infrastructure: state-actor's NVMe volume was deleted, so the two stores
cannot be timed side by side on identical media. Restoring it (552 GB rsync
back onto md2, ~1.5 h) would allow the benchmark itself to be re-run on
matched hardware, which is the only way to close the last gap.


---

# ROUND 18's ROOT-CAUSE STATEMENT IS WITHDRAWN (audit, round 19)

Challenged to produce the empirical backing, I checked whether my own numbers
close against the benchmark. They do not.

**The arithmetic that breaks it.** For the same test (BALANCE / MINIMAL /
160M) our reproduction recorded:

| per test | jochemnet | state-actor |
| --- | --- | --- |
| disk read | 3.21 GB | 3.77 GB |
| read operations | 349,774 | 397,574 |
| bytes per account lookup | **~59,500** | ~69,900 |
| I/O operations per account lookup | **~6.5** | ~7.4 |

Round 18's probe measured **9,975 bytes per read**. The benchmark spends
**~59,500 bytes per account** - six times more. The probe was therefore not
measuring the benchmark's work, and its +11.8% cannot be claimed to explain
the benchmark's +17.1%.

**Round 16's claim is withdrawn too.** "Account reads are a single flat
snapshot read, the trie is not walked" was measured through `eth_call`, which
runs neither the trie prefetcher nor the state-root computation that real
block execution performs. ~6.5 I/O operations per account is consistent with
an ~8-node trie walk, which is what rounds 1/5 measured all along. The
generalisation from `eth_call` to block execution was unjustified.

**Standing evidence** (measured, and believed sound):

- the offset itself: slope 1.091 in the original logs; +17.1% bytes, +13.6%
  IOPS, +23.8% CPU, 0.888 throughput across 440 joined cells in our own
  reproduction, with both arms verified to have run on `/schelk` NVMe volumes
- it is in execution, not commit or hashing (round 0)
- uniform across all six account modes and all eight opcodes (rounds 2, 10)
- both stores fully L6-compacted (round 4); client configuration byte-identical
  (round 14); fixture loops identical - same salts, iterations, gas (round 11);
  block-cache size irrelevant (round 12)
- state-actor's snapshot records are 58.3 vs 49.6 B/entry (round 6)

**No mechanism is established.** Three probes disagree - round 13 (clustered
sample) found no difference, round 17 found the ratio shrinking with scale,
round 18 found +11.8% - and round 18 is a single measurement across two
different I/O stacks (loop -> dm-era -> md2 NVMe versus raw md3 HDD) on keys
that matched nothing. Selecting it because it fit the hypothesis was
motivated reasoning.

**The only experiment that settles this** is the one the infrastructure
currently blocks: restore state-actor to an NVMe schelk volume (552 GB rsync
back onto md2, which has 810 GB free, ~1.5 h), then re-run the real benchmark
on both arms with client metrics enabled. That measures node fetches, block
reads and bytes under the actual execution path, on identical media, with the
harness that produced the original numbers. Everything short of that has
measured a different code path, a different access pattern, or a different
device.


---

## Round 20 — state-actor restored to NVMe

551 GB rsynced from the HDD copy into a loop-backed ext4 image on md2, the
same device and stack jochemnet uses (`fallocate`, then `mkfs.ext4 -E
nodiscard`, then re-`fallocate`, because mkfs discards otherwise punch the
image thin - the hazard a previous run hit). Verified: rsync rc=0, dry-run
diff empty, 11,328 files and 551 G on both sides.

Caution worth recording: the setup script ran `losetup -D`, which detaches
*all* unused loop devices, and it dropped jochemnet-virgin's association.
No data loss - the image is intact and schelk re-attaches on restore - but
that was careless on a box with live volumes.

## Round 21 — running the real block, and four harness bugs

Getting the genuine execution path to run took four fixes, each of which had
been silently corrupting earlier probes:

1. **The setup block was missing.** Round 15's SYNCING was simply the test
   payload being head+2; the fixture's `setupEngineNewPayloads` block sits
   between. Send it first.
2. **state-actor needs its pre-run block.** Its store is at genesis while its
   fixtures start at block 1; that block lives in
   `pre_run/<startBlockHash>.json`.
3. **The fork override differs per arm.** jochemnet uses
   `--override.amsterdam=1769856769`, state-actor `--override.amsterdam=1`
   (Amsterdam from genesis, synthetic chain). Using jochemnet's value made
   every state-actor block INVALID.
4. **A store with no head marker starts in sync mode** and answers every
   payload with `Ignoring payload while snap syncing ... forced head needed
   for startup`. An initial forkchoiceUpdated on the node's own head fixes it.

And the flags themselves were wrong. The harness launches geth with
`--syncmode=full --snapshot=false --cache=2048` (pkg/client/geth.go @1e0b9d4);
none of my probes used them.

## Round 22 — the offset, isolated and reproduced

Both arms, same NVMe device, harness flags, three runs each, caches dropped
before the measured block.

| | jochemnet | state-actor | ratio |
| --- | --- | --- | --- |
| wall time | 8.69 / 8.69 / 8.71 s | 9.58 / 9.64 / 9.67 s | **1.107** |
| accounts read | ~51,565 | ~51,562 | 1.000 |
| account reads served from disk | 51,536-51,547 | 51,546-51,557 | 1.000 |
| trie nodes fetched | 44 | 39 | - |
| disk bytes read | 0.471 GB (x3) | 0.527 GB (x3) | **1.119** |
| **bytes per account read** | **9,131** | **10,216** | **1.119** |

**This is the residual, isolated.** Identical logical work - the same ~51,540
disk-backed account reads, to three significant figures - yet state-actor
moves **11.9% more physical bytes** and takes **10.7% longer**. Time tracks
bytes. Run-to-run variance is negligible (9,130 / 9,132 / 9,134 bytes per
account).

The 10.7% reproduces the full benchmark's 11.2% throughput deficit, in a
ten-second experiment on matched hardware rather than a sixteen-hour run.

**What it means.** The cost is not tree depth, not node count, not the number
of reads - all three are equal. It is **bytes moved per read**. Each account
read fetches one pebble block, and state-actor's blocks are physically larger
for the same logical content: 0.817 physical/logical against jochemnet's
0.724 (round 7, +12.8%) predicts the measured +11.9% closely, with identical
Snappy settings on both stores (round 8). The underlying reason is
composition - 31.3% of state-actor's accounts carry a high-entropy 32-byte
code hash against jochemnet's 19.2%, and its records are 58.3 vs 49.6 B
(round 6).

Round 18's +11.8% - dismissed at the time as a single cross-device shot -
turns out to have been right, and matches this to a tenth of a point.

**Still one inferential step.** That the extra bytes come from block-level
compressibility rather than some other layout property is consistent with
every measurement but not directly proven; measuring compressed block sizes
within the account-snapshot key range of each store would close it.

