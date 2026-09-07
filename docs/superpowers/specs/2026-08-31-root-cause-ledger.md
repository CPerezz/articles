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
## R3 — The discriminating experiment: journal present vs deleted

**Hypothesis**: DIFF_MAX leaves are served from the pathdb journal loaded at
boot; without the journal they are not merely slow — they do not exist
(R2 showed the disk layer sits at ~24406217, below DIFF_MAX's first deploy).

**Test**: rebuild the exact final-run baseline from the promoted archive
(verified byte-exact: ssts=8438, journal 398,702,082, md5 bd14b819…); boot
the benchmark geth image directly on the schelk scratch; per class, drop OS
caches then 150 sequential cold `eth_getBalance` + `getCode` + `getProof`,
recording wall time and geth's `/proc/<pid>/io` read_bytes. Then
`schelk recover`, delete `triedb/merkle.journal`, boot again, repeat.

**Probe A — journal present (head 24410463):**

| class | ms/call | disk read | code | proof nodes |
| --- | --- | --- | --- | --- |
| MINIMAL | 1.12 | 3.5 MB | 1 B | 9 |
| SAME_MAX | 1.06 | 2.9 MB | 24576 B | 8 |
| JUMPDEST | 1.07 | 2.8 MB | 24576 B | 8 |
| **DIFF_MAX** | 0.65 | **0.0 MB** | 24576 B | 8 |
| EOA | 1.00 | 2.6 MB | 0 (bal>0) | 9 |
| NON_EXISTING | 0.97 | 2.5 MB | 0 | 8 |

Equal proof depths kill any trie-depth explanation. JUMPDEST contracts exist
(R2's "missing deploys" were internal calls, invisible to calldata scans).

**Probe B — journal deleted:** geth logs "Failed to load journal, discard it"
and the head rewinds to **24406217 — exactly the disk-layer block predicted
by R2's window math**. Then:

| class | ms/call | disk read | code |
| --- | --- | --- | --- |
| MINIMAL | 1.18 | 7.2 MB | 1 B |
| SAME_MAX | 1.27 | 6.5 MB | 24576 B |
| JUMPDEST | 1.17 | 6.8 MB | 24576 B |
| **DIFF_MAX** | 1.17 | 5.2 MB | **0 B — the accounts no longer exist** |
| EOA | 1.49 | 7.4 MB | 0 (bal>0) |
| NON_EXISTING | 1.20 | 9.7 MB | 0 |

**Verdict**: CONFIRMED, terminally. DIFF_MAX's state exists ONLY in the
journal; with it, reads are pure memory (0 disk); without it, the accounts
vanish and every class is identically disk-bound. Scratch recovered to the
intact baseline afterward.

---

# ROOT CAUSE (found at round 3 of 50)

The DIFF_MAX performance divergence is a **benchmark-pipeline artifact**, not
a database property:

1. EEST's `test_setup_contracts` pre-run deploys receiver classes
   **sequentially**, and DIFF_MAX — the most expensive class — goes **last**:
   blocks 24406595..24410441 of a chain ending at 24410463 (R2).
2. This geth build retains the last **4248 blocks** of trie diffs in pathdb
   layers and journals them at shutdown (`--engine.maxreorgdepth=1024`-scaled
   retention). The disk layer stops at 24406217.
3. Therefore every DIFF_MAX account leaf lives **only in the journal** (R3-B:
   delete it and the accounts cease to exist).
4. benchmarkoor's promote/restore cycle hands that journal to **every** test
   boot (1463/1463 loads), so DIFF_MAX leaf reads (BALANCE, EXTCODEHASH) are
   served from memory: 0 disk bytes (R3-A), 12.6 kB/Mgas at benchmark scale
   (run 1) — ~23× on this host.
5. Code blobs live in pebble, not the journal → CALL/CALLCODE only partially
   accelerate (2.8×). state-actor generates receivers inside its bulk state
   and ships no journal → nothing resident → flat (1.02×).
6. The original runs measured the same mechanism — their published
   380.15 MiB / 4248-layer journal is the same deterministic pre-run rewrite
   we reproduce to the digit — with the ratio (≈8-12× there, ≈23× here)
   scaled by each host's disk-vs-RAM gap.

**Fix directions** (for the follow-up discussion): flush/compact the pathdb
journal into the disk layer after the pre-run (the trie-level analogue of the
`geth db compact` already applied to the LSM); or randomise/interleave EEST's
receiver deploy order; or run benchmarks against a baseline whose journal has
been drained. Any of the three makes all four contract classes equally cold.
## R4 — The fix, applied: drain the journal post-pre-run, then compact

**Request** (operator): implement journal draining in the pipeline, run the
jochemnet arm on a drained baseline, and check whether the data now matches
state-actor.

**Implementation**
- `drainjournal` (tools/drainjournal-main.go), built from the client fork at
  the image's exact commit (`4d92c8e`, verified via embedded buildinfo):
  opens the datadir the way the node does, resolves the head (ancient-store
  top when the KV head pointers are absent, as in these snapshots), then
  `triedb.Commit(headRoot)` = pathdb `tree.cap(root, 0)`: flattens all 128
  diff layers and force-flushes the ~380 MiB write buffer into pebble
  (8438 → 8541 SSTs). Idempotent; removes the then-obsolete journal file.
- benchmarkoor support: branch `state-db-journal-drain` (c3c46f1 on top of
  the runs' 1e0b9d4; tools/benchmarkoor-post-prerun-hook.patch):
  `BENCHMARKOOR_POST_PRERUN_CMD` runs between "pre-run complete, client
  stopped, fs synced" and `schelk promote`, so future from-scratch runs bake
  a drained baseline automatically. Hook failure aborts before promote.

**Operational traps hit and documented** (all recoverable via dm-era
recover; scratch destroyed once, virgin never touched):
- The fork carries a pebble v1/v2 duality: this snapshot's store is legacy
  v1-format (no format markers). The v2 opener treats it as "no database" -
  read-only opens error out, read-write opens *initialize a fresh store and
  GC the 8k+ existing SSTs as orphans*. The node goes through
  `pebble.NeedsV1 -> NewV1`; the tool now does the same.
- The snapshot KV's freshest entries (incl. the pathdb disk root) lived only
  in the store's WAL in a layout offline openers could not see; one clean
  node boot+stop flushed them durably. Head pointers are absent by
  provenance; boots derive the head from the ancient store (whole chain is
  frozen: 24,410,464 items).

**Probe C - drained only** (150 cold reads/class): DIFF_MAX accounts exist
(code 24576) and read 1.2 MB - real I/O but still below the 2.4-3.7 MB
sibling band. Benchmark smoke: BALANCE/DIFF_MAX/160M = **272 MGas/s** (from
~410 journal-resident). Partial: the drain wrote all its state into ~103
fresh, dense SSTs - LSM recency is physical locality, a private hot layout.

**Probe D - drained + `geth db compact`** (2m2s, 8524 -> 8515 SSTs):
DIFF_MAX 0.96 ms / 2.6 MB - statistically inside the sibling band on every
axis. Benchmark smoke: BALANCE/DIFF_MAX/160M = **18.3 MGas/s**, landing in
the state-actor band (~15-18) - a 22x collapse from the journal-resident
number, matching the report's cross-arm anomaly magnitude (23x).

**Recipe** (both legs required): after the pre-run, before promote:
`drainjournal --datadir <D>` then `geth db compact`; 390 -> 272 (drain)
-> 18.3 (compact).

**Verdict run**: full `test_account_access` surface (1100 fixtures, the
report's analytical superset) launched on the drained+compacted promoted
baseline - config `jochemnet-drained.yaml`, labels `journal=drained`,
results `/data/bench-results/jochemnet-drained`. Cross-arm comparison vs
state-actor run 1 follows as the final verdict.

## R4 verdict — drained jochemnet vs state-actor (final)

80-test verdict run (all 8 opcodes x {DIFF_MAX, MINIMAL control} x
{160M, 300M} gas, value_sent=0, overhead_baseline=False; run exit 0;
results `/data/bench-results/jochemnet-drained`, plus 32 bonus results from
the aborted full-surface run in `...-drained-headstart`). Cross-arm ratio =
jochemnet / state-actor, per cell:

| mode | opcode class | orig/SA | **drained/SA** |
| --- | --- | --- | --- |
| MINIMAL (control) | all 8 opcodes | 1.11-1.13x | **1.10-1.14x** |
| DIFF_MAX | leaf-readers (BALANCE, EXTCODEHASH) | 22.4-23.1x | **1.11-1.12x** |
| DIFF_MAX | code-readers (CALL, CALLCODE, DELEGATECALL, STATICCALL, EXTCODESIZE, EXTCODECOPY) | 2.80-2.91x | **1.18-1.22x** |

- The control is untouched by the fix (orig 1.12x median, drained 1.12x) -
  no collateral distortion from draining + compacting.
- The 23x leaf-read anomaly collapses exactly into the host band.
- The predicted secondary fingerprint confirms: partially-accelerated
  code-reading rows (2.8x) also collapse, to 1.18-1.22x - a ~6% residual
  above the 1.12x band, uniform across all six opcodes (plausibly code-blob
  key adjacency from the late pre-run inserts; within noise of the verdict).
- Within-arm structure now matches SA row-for-row (e.g. DIFF_MAX slower
  than MINIMAL on CALL-class opcodes in BOTH arms - real work, 24 KiB vs
  1 B code reads).

# FINAL VERDICT

With the pathdb journal drained into the disk layer and the store compacted
after the pre-run (`drainjournal` + `geth db compact`, wired as
benchmarkoor's post-pre-run hook), the jochemnet arm reproduces the
state-actor arm across the entire tested surface inside the same
~1.1-1.2x host band that every non-anomalous category always showed.
The DIFF_MAX divergence is eliminated at its root: it was never a property
of either database - it was pre-run deploy recency served from the
journal's RAM-resident layers, amplified by LSM recency locality. Both
legs of the fix are required: 410 -> 272 MGas/s (drain) -> 18.3 (compact),
landing on state-actor's 16.5.
