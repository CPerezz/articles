# Root-cause investigation ledger — DIFF_MAX divergence

One entry per round: hypothesis, test, result, verdict. Committed after every
round. Hard cap 50 rounds or root cause, whichever first.

**Established going in** (from the two full runs + adjudication, all verified):

- jochemnet BALANCE/EXTCODEHASH DIFF_MAX: ~23× faster than same-arm peers,
  reading **12.6 kB/Mgas** from disk vs ~19 MB/Mgas (peers) — near-zero disk.
- state-actor: flat for leaf opcodes (1.02×); own 1.74× slowdown on
  code-touching opcodes for DIFF_MAX/JUMPDEST (distinct-24KB-code modes).
- Every jochemnet boot loads the pathdb journal: 380.15 MiB / 4248 layers,
  deterministically rewritten by the pre-run (original's published pair
  matches ours to the digit). state-actor: no journal, 1461/1461.
- Leaf-vs-code split: journal carries trie nodes, not code → leaf-only opcodes
  23×, code-reading opcodes 2.8×.
- Prime suspect: **journal residency** — DIFF_MAX account leaves served from
  the in-memory layer tree loaded from the journal at boot.
- Open questions: (Q1) does removing the journal collapse DIFF_MAX? (Q2) why
  are DIFF_MAX leaves resident but MINIMAL/SAME_MAX/JUMPDEST's are not, when
  all receivers were deployed by the same pre-run? (Q3) SA-side code-op
  slowdown mechanism. 

**Run-1 data preserved** (immutable):
- `/data/archive/run1/results-run1.tar.gz` (967 MB: both arms' full results
  trees), both run logs (gz), `derivation.txt`, `pipeline.log` — on the host.
- Local copies: `/tmp/bench-local/` (extracted) and `/tmp/bench-agents/`.
- Baselines: `/data/archive/jochemnet-virgin-pristine.img.zst` (905 G,
  pre-pre-run), `/data/archive/jochemnet-virgin-promoted.img.zst` (907 G,
  uncompacted-H), state-actor datadir `/data/sa-store/` (552 G, verified).

---
## R1 — What do the per-class benchmarks actually read?

**Hypothesis**: the six account modes differ in how targets are addressed;
that difference selects what is journal-resident.

**Test**: RLP-decode the BALANCE fixtures' setup and benchmark transactions
(160M file, all modes).

**Result**: benchmark txs call a per-test-deployed ~90-byte driver with a
`(salt_start, salt_end)` calldata range. The contract-mode drivers compute
targets as `CREATE2(factory 0x4e59b448…C0B4956C, salt=i, H_class)` in a tight
`SHA3;BALANCE;POP` loop, where H_class is a class-specific initcode hash
embedded in the driver: MINIMAL 5e59e025…, SAME_MAX e6b00ac4…, JUMPDEST
b9cdb904…, DIFF_MAX bdaf4298…. EOA/NON_EXISTING drivers derive addresses
arithmetically (base+i / hash-offset+i). Setup also makes one 0-data,
value-carrying call to one class-specific pre-existing address.

**Verdict**: mechanism decoded. All four contract classes read create2
receivers with sequential salts; the only class discriminator is the initcode
hash → the pre-run's DEPLOY ORDER becomes the prime candidate for why only
DIFF_MAX leaves are journal-resident (leaves created in the last ≤4248
pre-run blocks stay in the journal's layer window; earlier ones are flushed).
Predicts: DIFF_MAX deploys sit in late pre-run blocks (≥ 24406217), others
earlier; code bytes bypass the journal → CALL's partial 2.8× (leaf RAM, 24KB
code disk) is explained.
## R2 — When did the pre-run deploy each class?

**Hypothesis** (from R1): DIFF_MAX receivers were deployed in the pre-run's
last ≤4248 blocks, so their leaves live in the journal's layer window;
earlier classes were flushed to disk.

**Test**: stream all 15,472 payloads of the 9.4 GB pre-run bundle; classify
every create2-factory tx by initcode keccak (pure-python; 5 distinct
initcodes total); report per-class deploy block ranges vs the window
(head 24410463, window ≥ 24406216).

**Result**: MINIMAL 100k deploys in blocks 24402731..24402749 (flushed);
SAME_MAX 100k in 24402749..24406595 (only the last ~9.9k salts in-window);
**DIFF_MAX 100k in 24406595..24410441 — entirely in-window**. Benchmark
calldata decodes to salt ranges ~0..54k, so the in-window SAME_MAX tail
(salts ~90k+) is never read — consistent with SAME_MAX measuring disk-cold.
Plus the two EIP-8282 predeploys at 24402729.

**Verdict**: CONFIRMED. The class selector is deploy order: the journal
holds the last 4248 blocks of trie writes, and only DIFF_MAX's leaves were
written there. Explains the leaf/code split too (code goes straight to
pebble; only trie nodes ride the journal → CALL 2.8× vs BALANCE 23×).

**New anomaly**: zero factory deploys match H_jumpdest anywhere in the
bundle. Either JUMPDEST receivers were created via internal calls (invisible
to calldata scanning) or jochemnet's JUMPDEST benchmarks read non-existent
accounts. R3's live-geth probe will settle it (getCode on derived addresses).
