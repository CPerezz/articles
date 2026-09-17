# Hand-off prompt: one PR to `ethereum/state-actor` — replace the tiled single runtime with a real bytecode corpus

Everything below the rule is the prompt. It is self-contained: it assumes the reader has never
seen this study. Every number in it is a measurement, and each one says what produced it.

---

## What this is

You are making one PR to `github.com/ethereum/state-actor`, a synthetic Ethereum state
generator. A benchmarking study used it to build a 524 GB store meant to stand in for a real
mainnet snapshot, then measured an execution client (Besu) against both. Where the synthetic
store's *physical* layout diverges from the snapshot's, the benchmark measures the generator
instead of the client — so each divergence is a bug in state-actor's realism.

Three such divergences were found. Two are fixed and verified upstream (#133 bloom filters on
every column family, #137/#138 account-record entropy and contract-code sharing). **The third is
what you are fixing: the bytecode the generator emits is 6.6x more compressible than mainnet's,
so contract-code reads are artificially cheap.**

PR #138 ("autofill: share contract bytecode from a deterministic pool") introduced the code pool
and got two of three dimensions right. It is not being reverted — it is being completed.

## The defect

`internal/autofill/code_pool.go`:

```go
// codePoolSeed is fixed (not --seed) so every client derives the same pool.
const codePoolSeed = 0x57a7ec0de

// ponytail: one real contract sliced at rotating offsets, not a corpus.
// Upgrade to a small corpus if a benchmark shows it over-compresses.
func poolCode(j int, s Sampler) ([]byte, common.Hash) {
	src := templates.ERC20RuntimeBytecode          // ONE runtime, 1,723 bytes
	code := make([]byte, s.Draw(mrand.New(mrand.NewSource(codePoolSeed+int64(j)))))
	for n := copy(code, src[j%len(src):]); n < len(code); {
		n += copy(code[n:], src)                   // tile the same runtime
	}
	return code, crypto.Keccak256Hash(code)
}
```

The embedded source runtime is **1,723 bytes** (`internal/templates/erc20_oz_v5.hex`, 3,446 hex
chars) and `CodeSampler` draws a mean of **5,120 bytes**, so every pool entry is that one runtime
**tiled about 3x**, rotated by `j`. Pool entries are therefore self-similar internally *and* to
each other. LZ4 exploits both.

The comment predicted the failure mode exactly. A benchmark now shows it over-compresses.

## The measurements

Built a 4 GB store from the image containing #138 (`state-actor-besu:main-95e5a10`,
`--target-size=4GB --seed=42 --fork=osaka`), then read RocksDB's own table properties and
compressed sampled records. "mainnet" is a real Bonsai mainnet snapshot at block 24,402,727,
2,416,222 records in `cf07`, scanned read-only.

| metric | v1 (pre-#138, unique random code) | **#138 (tiled pool)** | mainnet snapshot | #138 vs target |
|---|---|---|---|---|
| `cf07` phys/log, RocksDB LZ4, CF-wide | 0.863 | **0.056** | **0.371** | **0.15x** |
| pooled record deflate, records >=1 KiB | ~1.00 | **0.2147** | **0.443** | 0.48x |
| packed 32 KiB block deflate | 0.955 | **0.1116** | **0.329** | 0.34x |
| `cf06` phys/log (account records) | 0.513, then 0.422 after #137 | 0.447 | 0.434 | 1.03x — at parity, leave alone |

Read the first row as: **a code read on the synthetic store fetches a data block that has
compressed 6.6x better than the equivalent mainnet block.** Individual records are 2.1x too
compressible; packed into a block they are 2.9x too compressible, because neighbouring pool
entries are rotations of the same source and compress against each other. The CF-wide LZ4 figure
(0.056) is the worst of the three because it sees the most cross-record redundancy.

Consequence for the benchmark: the class of tests that read a distinct contract per access was
**18% slower** than the snapshot before #138 and is projected to become *faster* than the
snapshot after it. The gap changes sign instead of closing. Neither number measures the client.

## What #138 already got right — do not regress these

1. **Reuse.** `DistinctBytecodes = max(numContracts/MainnetAccountsPerDistinctBytecode, 1)` with
   `MainnetAccountsPerDistinctBytecode = 32`. Verified in the smoke store's manifest: 83,886
   autofill contracts / 2,621 distinct bytecodes = **32.0 per blob**, against mainnet's measured
   28.2. Correct. Keep it.
2. **Size distribution.** Truncated normal, mean `MeanContractCode` = 5 KiB, clamped to
   [1 KiB, 24 KiB]. Measured mean pooled record 4,705 B against mainnet's fixture-corrected mean
   5,265 B. Close enough. Keep it.
3. **Determinism and cross-client identity.** `codePoolSeed` is fixed rather than derived from
   `--seed`, so every client derives the same pool and the cross-client state-root invariant
   holds. Keep that property.
4. **RNG draw order.** `DrawContract` draws `rng.Intn(p.DistinctBytecodes)` from the *main* rng
   and then calls `GenerateContractWithCode`, which skips the two draws `GenerateContract` would
   have spent on code. `poolCode` uses its own separate rng. Your change must not alter the
   number or order of main-rng draws — `internal/entitygen` has tests asserting the draw
   sequence, and `internal/autofill/plan.go` documents it.

Only the **content** of the pool is wrong.

## The change

Replace the single tiled runtime with a **corpus of distinct real mainnet runtimes**, drawn so
the resulting population compresses like mainnet's.

Design notes, not prescriptions — take the shortest path that hits the acceptance numbers:

- Embed a handful of real, *different* mainnet runtimes alongside the existing ERC20 blob, in the
  same hex-blob style as `internal/templates/erc20_oz_v5.hex`. A dozen or two distinct contracts
  is plenty; mainnet's compressibility comes from having several genuinely different code bodies
  that each repeat across many accounts, not from having thousands of unique ones. Candidates
  that dominate real mainnet code: an OZ ERC20 (already present), ERC721, ERC1155, a minimal
  proxy, an EIP-1967 upgradeable proxy, a Uniswap V2 pair, WETH9, Multicall3, a Gnosis Safe
  singleton. Source them from verified mainnet runtime bytecode.
- Entry `j` picks one corpus member and takes a **prefix** of the drawn length. Do not tile a
  member to reach the length; tiling is what caused this. If the drawn length exceeds the chosen
  member, either pick a member long enough or concatenate **different** members.
- Prefixes of real runtime are not executable EVM code. That is already true of #138's output and
  is fine — this state is never executed, only read. Do not spend effort making it valid.
- Keep the whole thing in `poolCode` if you can. Do not add a dependency, a corpus-loading
  framework, or a new config surface. Embedded hex plus an index is the whole job.

## Acceptance criteria

Build a >=4 GB store and measure. `LiveGeom.java` (attached in this repo at
`tools/besu-study/LiveGeom.java`) reports every figure below in one run; it opens RocksDB
read-only without needing the OPTIONS file, so it works on a store state-actor wrote and on one
it is still writing.

```
docker run --rm -v $PWD:/w -v <store>:/db:ro -w /w eclipse-temurin:21-jdk \
  java -cp .:rocksdbjni-10.6.2.jar LiveGeom /db/database 24576 3000
```

Hard gates, all three measured on the same store:

| # | criterion | target | accept |
|---|---|---|---|
| 1 | pooled record deflate, records >=1 KiB | 0.443 (mainnet) | **0.39 - 0.50** |
| 2 | packed 32 KiB block deflate | 0.329 (mainnet) | **0.28 - 0.38** |
| 3 | `cf07` phys/log, CF-wide RocksDB LZ4 | 0.371 (mainnet) | **0.31 - 0.43** |

Criterion 3 is the one that matters for read cost and the hardest to hit, because it sees
cross-record redundancy. Criteria 1 and 2 are the fast diagnostics that tell you which way to
move: if 1 passes and 3 fails, corpus members are too few or too similar to each other.

Preserve, and state the measured value in the PR body:

| # | invariant | expected |
|---|---|---|
| 4 | accounts per distinct bytecode, from the manifest: `num_contracts / distinct_bytecodes` | 32.0 |
| 5 | mean pooled record size | 4,500 - 6,000 B |
| 6 | `cf06` phys/log unchanged | 0.43 - 0.46 |

## Constraints

- **Changing pool content changes state roots.** Golden-oracle fixtures that pin a state root
  must be regenerated in the same PR: search `--include=*_test.go` for `state_root`, `stateRoot`,
  `golden`. Say in the PR body that roots moved and why.
- Cross-client invariance must still hold: the pool must be derivable identically by every
  client, from `codePoolSeed` alone, with no dependence on `--seed`, `--target-size`, worker
  count, or iteration order.
- Do not change `MainnetAccountsPerDistinctBytecode`, `MeanContractCode`, `MinContractCode`,
  `MaxContractCode`, or `DistinctBytecodes`' formula. Those are measured-correct.
- Binary size: embedded hex for a dozen runtimes is a few hundred KB of source. If that is
  objectionable, say so in the PR rather than shrinking the corpus below what criterion 3 needs.

## Out of scope — mention, do not fix

Mainnet's code-size histogram has large mass **below** `MinContractCode` = 1 KiB that the
generator cannot reach. From a 41,486-record scan of the snapshot's `cf07`:

```
   216 B x 2,223      minimal / EIP-1167 proxies
    23 B x 1,734      EIP-7702 delegation designators (already handled by #137)
    77 B x 1,038
22,142 B x   964
 1,359 B x   828
   173 B x   778
    45 B x   635
```

So real mainnet code is bimodal: a large population of tiny proxies plus a body of multi-KB
contracts, while the generator emits only the latter. That is a separate realism gap, a change to
`CodeSampler` rather than to the pool, and it should not be bundled into this PR. Note it in the
PR body as follow-up work.

## One infrastructure prerequisite, if anyone benchmarks this

The acceptance criteria above are all store-level and need no benchmark. If someone does want a
throughput arm on the regenerated store, note that EEST stateful payloads are anchored to a
specific store: a fixture pins `snapshotBlockHash`, and a store with a different state root has a
different genesis hash, so an existing bundle's payloads are rejected with SYNCING. Payloads must
be refilled per store.

Refilling uses `fill-stateful`, whose `ClientBackend` builds blocks with `testing_buildBlockV1` -
a **Geth-only** RPC extension. So a fillable store needs a **geth twin**: generate the same spec
and seed with `--client=geth` as well. That is sound because the generator is client-independent -
identical spec and seed give the same state root across clients - and one geth-filled bundle then
drives every client under test.

Practically: generate both `--client=geth` and the client you intend to benchmark, then
`benchmarkoor build` with a `builder.eest_payloads` target pointing `source_dir` at the geth
store; it boots the filler, queries the genesis hash itself, and writes fixtures that
`tests.source.eest_fixtures.local_fixtures_dir` consumes. Budget roughly a full day of exclusive
device time for generation plus fill.

## What to report back

1. The three acceptance figures and the three invariants, measured, with the store size and the
   command used.
2. Which corpus members you embedded and where each came from.
3. Whether criterion 3 needed more members than criteria 1 and 2 did — that is the interesting
   finding either way, and it tells the study whether mainnet's code compressibility is driven by
   within-contract or across-contract redundancy.
4. Any criterion you could not hit, with the number you did hit. A measured miss is more useful
   than a passing store built by tuning the corpus until the number came out right.
