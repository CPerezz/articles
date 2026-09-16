# Hand-off prompt: three PRs to `state-actor`

Everything below the rule is the prompt. It is self-contained: it assumes the reader has never
seen this study. Numbers in it are measurements, and each one says what produced it.

---

## Context: what you are fixing and why it matters

`state-actor` is the generator that synthesises large Ethereum execution-layer state for
benchmarking. Client teams use its output as the "big state" arm and compare it against a real
mainnet snapshot to decide whether a change is fast or slow.

We ran that comparison on Besu at scale and it does not hold up. Three defects in the generated
store, none of them in Besu and none of them properties of "large state", make the generated arm
look between 1.2x and 8x slower than a mainnet snapshot holding the same logical state. Any
repricing or storage-layout decision taken off that comparison is reading generator artifacts.

Your job is three PRs to `state-actor` that remove those artifacts. They are independent and can
land in any order, though PR 1 is by far the cheapest and should go first.

### How the numbers below were produced

- **Hardware/suite.** One host, one NVMe device, three Besu arms, `ethpandaops/besu:glamsterdam-devnet-7`
  on all three, ~1,460 EEST stateful tests each (`tests/benchmark/stateful/bloatnet/test_account_query.py`),
  1,100 workloads common to all arms, page cache dropped between every test.
  Gas consumed is identical across arms to six significant figures, so every arm was asked for
  the same work.
- **Arms.** (a) the published mainnet-shadowfork snapshot `jochemnet` at block 24,402,727 as
  shipped, (b) the same snapshot flushed and fully compacted, (c) the `state-actor` store built
  with `--db=/data --client=besu --target-size=350GB --spec=<baseline> --seed=42 --fork=osaka
  --gas-limit=1000000000`.
- **Reference arm for every ratio below is (b), the compacted snapshot.** Arm (a) carries a
  separate, already-understood artifact (the benchmark's own pre-run leaves its writes at the
  top of the LSM tree, worth up to 6x) which compaction removes. Both stores are a single sorted
  run per column family, so placement is controlled and what remains is a data comparison.
- **Store-level numbers** come from RocksDB's own table properties via a read-only open
  (`getPropertiesOfAllTables` per column family), not from filesystem guesses.
- **Control.** Every EEST workload exists twice: once doing account-state work and once as an
  `overhead_baseline` control that runs the same loop and touches no state. Controls read a
  median 1.9 MB against the measurement rows' 8.6 GB. All ratios below use measurement rows
  only. The control sits at 1.019, i.e. the generated arm is 1.9% *faster* on work that touches
  no state; that is the floor below which nothing here is claimed.

### Column families referenced

Besu Bonsai names its RocksDB column families by a single byte. Relevant ones:
`06` ACCOUNT_INFO_STATE (the flat account keyspace), `07` CODE_STORAGE (contract code, keyed by
code hash), `08` ACCOUNT_STORAGE_STORAGE, `09` TRIE_BRANCH_STORAGE, `01` BLOCKCHAIN.

---

## The measured gap, by class of read

Throughput, generated store divided by compacted snapshot, per-workload median over measurement
rows. 48 opcode/account-mode categories, 24 of them within +/-10% of parity, 24 not:

| class of read | categories | throughput | bytes read | which PR |
|---|---|---|---|---|
| proves an account is absent (`NON_EXISTING_ACCOUNT`) | 8 | **0.117** | **50.1x** | PR 1 |
| reads a distinct contract per access (`DIFF_MAX`, `JUMPDEST`) | 16 | **0.823** | 1.44x | PR 2, PR 3 |
| reads an account, code shared or absent (`EOA`, `MINIMAL`, `SAME_MAX`) | 24 | **0.948** | 1.14x | PR 2 |
| control: same loop, no account-state work | 440 workloads | 1.019 | ~1.0x | n/a |

Time tracks bytes throughout. Nothing here is a Besu code path; all of it is how many physical
bytes a lookup has to move.

---

## PR 1 — write a filter policy on every column family

### The defect

`state-actor`'s SSTs carry **no filter of any kind**. RocksDB table properties, per column
family:

| column family | snapshot filter bytes | snapshot policy | state-actor |
|---|---|---|---|
| `06` ACCOUNT_INFO_STATE | 443,500,673 | `bloomfilter` | **0**, `(none)` |
| `07` CODE_STORAGE | 3,024,215 | `bloomfilter` | **0**, `(none)` |
| `08` ACCOUNT_STORAGE_STORAGE | 2,278,300,355 | `bloomfilter` | **0**, `(none)` |
| `09` TRIE_BRANCH_STORAGE | 3,766,897,459 | `bloomfilter` | **0**, `(none)` |
| `01` BLOCKCHAIN | 550,578,537 | `bloomfilter` | **0**, `(none)` |

The snapshot's filters are **exactly 10 bits per key** on every column family
(443,500,673 B / 354,792,873 entries = 1.250 B = 10.00 bits; same to two decimals on all five),
totalling 7.04 GB.

### Why it costs what it costs

A bloom filter answers "this file cannot contain that key" without reading a block. Without one,
a lookup that will find nothing must read index and data blocks to establish the same thing. The
absence classes probe addresses genuinely missing from **both** stores — Besu's own
`get_account_missing_flat_database_total` counter puts the miss rate at 0.955 on the snapshot and
0.999 on the generated store, so it is the same question with the same answer — and they pay
**50.1x the bytes** and run **8.5x slower** for it. Lookups that do find their key pay a smaller
penalty, 1.21x to 1.32x the bytes, because they were going to read that block anyway.

A filter is baked into an SST when the SST is written. It cannot be added to an existing store
except by rewriting every file, which is why this needs a generator fix and a regeneration.

### What to change

Set a filter policy on the table options used to write **every** column family, for every
`--client` target. Match the client's own default rather than inventing one: bloom, 10 bits per
key. Pebble (geth) also defaults to bloom at 10 bits/key, so a single value is right for both
backends.

`[INFERENCE, worth checking first]` This looks like an omission rather than a decision: RocksDB's
`BlockBasedTableOptions` has no filter policy unless one is set explicitly, in every language
binding. If `state-actor` builds its own table options for `--client=besu` while inheriting
Pebble's defaults for `--client=geth`, that would explain why only the Besu path is affected. The
geth study of the same generator never flagged a missing filter.

### Cost

For the generated store's 6,404,913,398 entries across those five column families, filters add
about **8.0 GB**, or 1.4% of its 572 GB. `--target-size` accounting has to allow for it.

### Acceptance criteria

- Every column family reports a non-empty filter policy and a filter size of 1.25 B/entry
  (+/-2%).
- Total store size grows by ~1.4%, not more.

### Validate before you write any code

You can test this PR's hypothesis on the *existing* store without touching `state-actor`, in
about 90 minutes: open the generated store with RocksDB, set a bloom filter at 10 bits/key on
the table options, run a full-range compaction (`compactRange` per column family), and re-measure
the absence classes. Compaction rewrites every SST, so the rewritten store carries filters. If
the absence gap does not move, stop and tell us before doing anything else.

---

## PR 2 — stop filling to target size with uniquely-delegated EOAs

### The defect

**94.6% of the generated store's code records are EIP-7702 delegation designators**, each unique.
Sampled from `cf07` (scan 2,115 records, 2,001 were 23-byte values beginning `0xef0100`):

```
value[23] = ef01003ba448e2bf46fb0ac28463a4ffe4b2332f4cbaf6
value[23] = ef0100be88b60bdc83c258e8c75cad47615db118324065
value[23] = ef01003f5aea3bbdb51e46d203c5ace31c528cf8dd4db9
```

`0xef0100 || <20-byte address>`. The same scan on the mainnet snapshot finds designators at
**4.2%** of code records (2,001 hits in 47,730 records), which is a real post-Pectra population.
The generated store is at 94.6%: a 22x over-representation.

The declared spec accounts for only 150,000 of them (`delegations-300m`, `template:
sequential_pkey_delegations`, `count: 150000`). The store holds 134,442,676 code records. So
roughly **134.3 million designators come from the `--target-size` filler, not from any declared
entity.** Finding where is the first task of this PR; we could not, as we have no access to the
source.

### Why it costs what it costs, twice

Each designator is unique to its account, and that has two separate consequences.

**On account reads (the 24-category class, 0.948).** A Bonsai flat account record is
`RLP(nonce, balance, storageRoot, codeHash)`. A plain EOA carries `EMPTY_TRIE_ROOT` and
`EMPTY_CODE_HASH` — two 32-byte constants shared by every EOA in the store, which LZ4 collapses
across a data block. A uniquely-delegated EOA carries a unique 32-byte code hash instead, which
compresses to nothing. Sampled from each store's `cf06`:

| | snapshot | state-actor |
|---|---|---|
| records carrying both empty constants (plain EOA) | **80.8%** | **68.6%** |
| records carrying an empty storage root | 92.9% | 98.3% |
| mean record | 73.2 B | 79.7 B |
| LZ4 `physical / logical` (RocksDB's own figure) | **0.434** | **0.513** |
| compressed bytes per data block (RocksDB's own) | **14,147** | **16,697** |

1.18x the physical bytes per block predicted, 1.14x measured on the read. That is the whole
5.2% on this class.

**On code reads (the 16-category class, 0.823).** Isolating what the code read itself costs, by
subtracting the classes that read only the account record: a distinct-contract access moves
**24.1 extra bytes per gas** on the snapshot against **47.3** on the generated store, a factor of
**1.97**.

The obvious explanation — that generated contract code compresses worse — is false, and we
checked: the 24,576-byte fixture contracts deflate to **0.0109** of their size on the snapshot
and **0.0070** on the generated store. The contract being read is near-free to store in both.

What a lookup pays for is the **data block** the record sits in. RocksDB closes a block once it
passes `block_size` (32,768 B on both stores), so a 24,576-byte contract leaves ~8 KB of room for
whatever follows it in code-hash order — a uniform sample of each store's code population.
Modelled by packing each store's own records the way RocksDB does, 200 blocks per store:

| per data block holding one fixture contract | snapshot | state-actor |
|---|---|---|
| the contract itself, compressed | 0.0109 of raw | 0.0070 of raw |
| co-tenant records | **2.4** | **32.5** |
| mean co-tenant size | 7,298 B | **352 B** |
| block, uncompressed | 41,726 B | 36,024 B |
| **block, compressed** | **5,912 B** | **10,718 B** |

1.81x modelled, 1.97x measured. The snapshot's co-tenants are a couple of mainnet contracts that
compress. The generated store's are ~32 unique designators that cannot.

So one generator choice drives both remaining classes.

### What to change

The target-size filler should reach its size target the way mainnet got there: predominantly
plain EOAs (empty code hash, empty storage root) and storage slots, not delegated EOAs with
unique designators. Keep delegations as a *represented* class at roughly mainnet's share, not as
the filler mechanism.

Removing ~134M designators removes ~3.1 GB of code records and ~134M `cf07` entries; the
generator has to make up the resulting shortfall against `--target-size` elsewhere (more plain
accounts, more storage slots under existing contracts). That rebalancing is part of this PR.

### Acceptance criteria, measured on a regenerated store

- **>= 80%** of `cf06` records carry both `EMPTY_CODE_HASH`
  (`c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470`) and `EMPTY_TRIE_ROOT`
  (`56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421`). Snapshot: 80.8%.
  Current: 68.6%.
- **<= 10%** of `cf07` records are 23-byte values beginning `0xef0100`. Snapshot: 4.2%.
  Current: 94.6%.
- `cf06` LZ4 `physical / logical` **<= 0.45**. Snapshot: 0.434. Current: 0.513.
- `--target-size` still reached within its existing tolerance.

---

## PR 3 — give contract code mainnet's size distribution and reuse

### The defect

Once the designators are gone, what is left in `cf07` should look like mainnet's contract
population, and today it would not. Current `cf07`:

| | snapshot | state-actor |
|---|---|---|
| records (distinct bytecodes) | 2,416,222 | **134,442,676** |
| mean record | 7,671 B | **398 B** |
| LZ4 `physical / logical` | 0.371 | 0.863 |
| contract accounts (derived, from the EOA share above) | 68,120,232 | 135,238,776 |
| **accounts per distinct bytecode** | **28.2** | **1.01** |

Mainnet reuses each bytecode about 28 times: proxies, token clones and factory output share
bytecode, so one code record serves many accounts and one code hash appears in many account
records. The generated store reuses none.

**Caveat on the reference column, read this before matching it.** Those snapshot figures are
measured after our benchmark's own pre-run, which added ~300,000 unique 24,576-byte fixture
blobs — 12% of the record count and 40% of the logical bytes, and highly compressible, so they
pull the mean up and the compression ratio down. Subtracting them gives a **fixture-corrected
mainnet estimate** of ~2,116,222 distinct bytecodes, mean **~5,265 B**, `physical / logical`
**~0.609**. Match that, or better, take your reference from a pristine mainnet snapshot with no
pre-run applied. Do not match the raw 7,671 B / 0.371 column.

### What to change

For the contracts the generator does create: draw their bytecode from a pool so that many
accounts share each distinct blob, at roughly mainnet's ratio, and size the pool's blobs like
mainnet's distribution rather than uniformly small. This is the difference between "reduce the
number of contracts" and "make contracts share bytecode": the second is what fixes both the code
block's co-tenancy and the account record's entropy, because a shared blob means a shared code
hash in `cf06` too.

### Acceptance criteria, measured on a regenerated store

- **accounts per distinct bytecode >= 10**. Snapshot: 28.2. Current: 1.01.
- mean distinct-bytecode size within 2x of the fixture-corrected mainnet estimate (~5.3 KB).
- mean compressed bytes per `cf07` data block **<= 18,000**. Snapshot: 14,018. Current: 29,136.

---

## Hard constraints: do not break these

1. **Do not touch the fixture code patterns.** `max_same_pre_amsterdam` (one shared 24,576-byte
   blob), `max_diff_pre_amsterdam` (byte-unique 24,576 B per account),
   `unique_jumpdest_pre_amsterdam`, and the minimal 1-byte `STOP` runtime must keep their exact
   sizes and semantics. `EXTCODESIZE`/`EXTCODECOPY`/`CALL` gas depends on code size, and "gas
   identical across arms to six significant figures" is the control that makes the whole
   comparison valid. PR 2 and PR 3 are about the **filler and the general contract population**,
   never about the classes the fixtures address by name.
2. **Do not change `block_size` (32,768) or compression (`kLZ4Compression`).** Both are matched
   against the snapshot deliberately; they are controlled variables, not tuning knobs. A smaller
   code-family block size would independently fix the co-tenancy effect, but it would do so by
   making the two stores differently configured, which defeats the comparison. If you think the
   default should change, that is a separate conversation with the benchmark harness, not this PR.
3. **Determinism must survive.** Same `--seed` and spec must still produce the same state root,
   and must still agree across `--client` backends — today geth and Besu runs of the same spec
   land 10 items apart in 6.4 billion with an identical state root. These PRs will change the
   state root; that is expected. They must not make it non-deterministic or client-dependent.
4. **Keep and extend the manifest.** `state-actor-manifest.json` already records
   `result.state_root`, `result.accounts_created`, `result.contracts_created`,
   `result.total_db_size_bytes`. Add the invariants above (plain-EOA share, designator share,
   distinct-bytecode count, accounts per bytecode, per-CF filter bytes) so the next person can
   check them without writing a RocksDB probe.

## Non-goals

- Any change to Besu, Nethermind or geth.
- Any change to the EEST fixtures or the benchmark harness.
- Chasing the 1.9% control offset. It is real but small, and it most likely comes from the two
  arms running different EEST payload bundle builds, which is ours to fix, not yours.

---

## Verification tooling

Four read-only Java probes were used for every store-level number above. They live in
`CPerezz/articles`, branch `state-db-bench-reproduction`, under `tools/besu-study/`. Each opens
the store read-only and never mutates it. Re-implement in any language if that is easier; what
matters is that the numbers come from RocksDB's own table properties, not from `du`.

| probe | what it reports |
|---|---|
| `SstGeom.java` | per column family: entries, SST count, data bytes, mean record, compressed bytes per block, `physical / logical`, filter bytes, filter policy |
| `Levels.java` | per column family and LSM level: file count, bytes, filter bytes |
| `AcctMix.java` | `cf06` composition: share of records carrying the empty code hash and empty trie root, mean record, simulated block cost |
| `BlockSim.java`, `CodeEntropy.java` | `cf07`: value-length histogram, compressibility of a given record length, and the modelled cost of the data block a fixture record sits in |

Two notes on method. First, these probes use `Deflater` as a stand-in for LZ4 where they
compress anything themselves; it is stronger than LZ4 and differentially stronger on redundant
data, so **its ratios are comparative only** and RocksDB's own reported figures
(`physical / logical`, compressed bytes per block) are authoritative for magnitude. Second,
`SstGeom` identifies column families by entry count rather than by guessing segment ids, because
the counts are already known and distinctive.

## Sequencing, and what to report back

1. **Run the pre-PR validation for PR 1** (bloom + full compaction on the existing store,
   ~90 min). It costs almost nothing and it tests the largest single effect before you write
   code. Report the absence-class numbers before and after.
2. **Land PR 1.** Regenerate. Re-measure. Some of the 1.21x-1.32x byte penalty on reads that
   find their key is probably filter absence rather than record entropy, so PR 2 and PR 3 may
   have less left to buy than the numbers above suggest. Do not size them until PR 1 is measured.
3. **Then PR 2, then PR 3.**

For each PR, report the probe output before and after, plus the manifest. With those we can
re-run the three benchmark arms and confirm the classes converge. Expected direction if all
three land: absence classes from 0.117 towards parity, distinct-contract classes from 0.823
towards parity, account classes from 0.948 towards parity, and the control unchanged at ~1.02.

If any measurement contradicts the reasoning above, say so rather than working around it. Two
of our own hypotheses died on contact with these probes — "the generated contract code is less
compressible" and "the shipped write-ahead log is the cause" — and both times the measurement
was the useful part.
