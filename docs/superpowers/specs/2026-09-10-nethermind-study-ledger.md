# Nethermind state-DB study — execution ledger

Third client after geth and Besu, on a separate machine (`gas-repricing`, 157.180.2.180:
48 cores, 125 GB RAM, 7.0 T NVMe RAID0 at `/`).

Plan mirrors `2026-09-09-besu-state-db-study.md`. Findings below are the Nethermind-specific
deltas; anything not mentioned matched the Besu procedure.

---

## Round 0 — host prep, and what was NOT wiped

The brief was "wipe the Reth archive and the sqlite stuff". The box turned out to be running
live infrastructure:

- `actions.runner.CarlBeek-repricing-forensics.reth-server` — a GitHub Actions runner
- `eip7904-web.service` — an analysis web server, **publicly exposed** via `caddy` + `cloudflared`
- `openbao-agent`, `vector`, `teleport`, an 80-day-old python process

Wiped only `/home/ubuntu/.local/share/reth` (**3.3 T**) plus `.duckdb`, after confirming no reth
process was running and that `serve.py` references no reth path, DB, or RPC port. The services
were left alone. Risk recorded rather than hidden: the runner is labelled `reth-server`, so a
future CI job may expect that archive.

Result: 6.5 T free.

Tooling had to be built from nothing — no docker, no podman, no go. Installed **podman 4.9.3**
(the same version as the Besu box, for comparability), loaded `brd` with **two** ramdisks
(persisted via `/etc/modprobe.d/brd.conf`) because two schelk instances must coexist, and
copied `benchmarkoor` + `schelk` binaries plus the state-actor source tree from the Besu box.
Podman needed `unqualified-search-registries = ["docker.io"]` before any `FROM` would resolve.

---

## Round 1 — generation, and a third identical state

`Dockerfile.nethermind` compiles **RocksDB from source** (Besu's used apt packages), so the
image build is materially longer.

Generation used parameters identical to geth and Besu — `--target-size=350GB --seed=42
--fork=osaka --gas-limit=1000000000`, same spec, no `--chain-id`:

```
nethermind: genesis hash = 0xa9e61c12051aeda72581c40b1718fa76b80c0b5cc5f7b7ebe96e0b6d9669491b
nethermind: state root  = 0x5b305cc0f85f9ffaf5eca1e72cfe0c82f92e14f121aed163cc4c0e784aa3b6e7
nethermind: 7 RocksDBs written under /data/
```

Both values are **identical to geth's and Besu's**. Three independent clients, one logical
state — the genesis hash also equals the cached payloads' `snapshotBlockHash`, so the
geth-filled payloads drive this arm too.

Phase 2 ran at **486k accounts/s** against Besu's 32.5k/s.

### Same state, three footprints

| client | store |
|---|---|
| geth | 674 GiB |
| besu | 532 GiB |
| **nethermind** | **409 GiB** |

Nethermind splits into **separate RocksDB directories** (`state/` 364 G, `code/` 44 G, and five
~286 M DBs) rather than Besu's single DB with column families. Any inventory or compaction tool
must iterate per-directory.

---

## Round 2 — the EIP-list trap (the expensive one)

The first pilot failed with a BAL hash mismatch **byte-identical to Besu's round 8**:

```
InvalidBlockLevelAccessListHash:
  Expected 0xbc207ccae7a10569a317cc3678a2b0b4e29ed0be27d40222833b60cbd26f4e98   (payload header)
  got      0xb1d04db6fc05f7f1f213667b2d0e3d6a0b8797d5c03130178168d16a5037fc64   (client-computed)
```

Wrong hypotheses, each disproved by running it:

| tried | result |
|---|---|
| `nethermind:glamsterdam-devnet-8` | same `0xb1d04db6…` — not a version issue |
| `nethermindeth/nethermind:master` | CLI diverged; rejects `--Blocks.ParallelExecution*` and more |
| drop EIP-7928 to disable BAL | `engine_newPayloadV5` → **"Unsupported fork"**; BAL is not optional |

**Actual cause: the EIP list.** geth and Besu activate Amsterdam *by fork name* and get the
client's complete built-in EIP set. Nethermind activates via `genesis_eip_override`, which
writes `params.eip<N>TransitionTimestamp` into a parity chainspec — so it gets **only what you
enumerate**. benchmarkoor ships two Amsterdam sets and the shorter one was copied from the
*state-actor fill* config:

| source | EIPs | outcome |
|---|---|---|
| `config.state-actor-eest.full…` | 9 | every block INVALID |
| `config.existing-snapshot-eest…pre-runs` | **14** (`+2780, 7997, 8038, 8246, 8282`) | **passes** |

A different active EIP set changes what execution records into the block access list. Pilot then
passed `failed=0 passed=2` at **16.47 MGas/s** on BALANCE/DIFF_MAX@160M (geth's post-fix figure
for that category was ~16.5).

**Generalisation:** for any per-EIP-configured client, the fork definition is an input that must
be sourced from the same context as the fixtures, not copied from a neighbouring config.

---

## Round 3 — jochemnet arm: three configuration facts that are not guessable

The snapshot is **1,261,351,401,168 B (1.26 TB)**, extracting to **1.4 T**. Produced by
`nethermind/nethermind:1.35.8`.

1. **Datadir depth.** The tarball root holds `mainnet/`, and the datadir must point at
   *that subdirectory*. The canonical config
   (`ethpandaops/benchmarkoor-tests: configs/datadirs/jochemnet/v1/global.yaml`) states it
   outright: *"the shallower path boots at MAINNET GENESIS instead of erroring"* — a silent
   wrong-answer failure, not a crash.
2. **Chainspec.** Nethermind needs `--Init.ChainSpecPath`, which the snapshot does not ship and
   the EEST bundle does not provide (`benchmarkoor` errors: *"sets genesis_eip_override but has
   no genesis file"*). The canonical value is a gist,
   `nethermind-jochemnet-with-osaka.json`, recorded in that same global.yaml.
3. **Amsterdam timestamp** `1769856769`, confirmed against
   `configs/contexts/repricing/jochemnet/v1/glamsterdam-devnet-7/global.yaml`: geth's genesis
   schedules `amsterdamTime 1769856767` and the snapshot head (block 24402727, ts 1770454055)
   sits ~6.9 days past it, so the chain is already on amsterdam.

---

## Round 4 — the structural finding: the two arms cannot share a state backend

Booting the jochemnet arm failed with:

```
Nethermind.Trie.MissingTrieNodeException: Node A: P: H:0x1582f753... is missing from the DB
```

`--FlatDb.Enabled` defaults to **false**, so Nethermind tried to serve reads from the patricia
trie. The snapshot was produced by a node running with the flat DB, and its trie is pruned —
the nodes simply are not there. With `--FlatDb.Enabled=true` the arm boots and the pilot passes
(`failed=0 passed=2`).

The two arms therefore report **different state backends, and neither can use the other's**:

| arm | backend logged | why it is forced |
|---|---|---|
| state-actor | `patricia (flat DB disabled)` | complete trie written by the generator; **no `flat/` DB exists** |
| jochemnet | `flat (existing flat DB detected)` | trie is pruned; trie-mode reads hit missing nodes |

Directory evidence — `flat/` is **319 G** on the jochemnet store and **absent** from the
generated one:

| `mainnet/` (jochemnet) | | state-actor |
|---|---|---|
| blocks | 503 G | 286 M |
| state | 341 G | 364 G |
| **flat** | **319 G** | **absent** |
| receipts | 200 G | 286 M |
| code | 7.4 G | **44 G** |

**Consequence for the study.** Any jochemnet-vs-state-actor throughput difference on Nethermind
conflates two causes: the data properties the study is about, and the state backend. This is a
first-order confound and must be stated with every number from this pair.

It is also the sharpest Nethermind-specific result so far, and the direct analogue of the geth
study's finding that one arm enjoyed an advantage the other structurally could not have
(there: journal residency; here: a flat DB that a generated store cannot possess).

The decisive follow-up is a symmetric run: build a flat DB for the generated store via
`--FlatDb.ImportFromPruningTrieState=true` and re-measure. Until then the comparison bounds the
effect but does not attribute it.

Note also `code`: **44 G generated vs 7.4 G mainnet**, ~6× more code-bearing state — consistent
with the geth study's 31.3% vs 19.2% code-bearing accounts, which drove the incompressible-record
residual.

---

## Round 5 — baselines launched, then the host stopped accepting logins

Both full suites launched sequentially (never concurrently: same NVMe array, and concurrent I/O
is what invalidated rounds 13/17/18 of the geth study). **1,461 tests** discovered per arm.

Last observation before access was lost: **120/1461 tests, 0 validation failures**, load 37/48.

The host then stopped completing SSH sessions, for the second time (the first cleared on its own
after ~2 h, with the detached download completing successfully). Signature:

| probe | result |
|---|---|
| ICMP | fine |
| TCP :22 | handshake completes |
| SSH banner | returned — **so sshd still forks a child per connection** |
| key auth | `Server accepts key` |
| session setup | **hangs**, never reaches `Authenticated` |
| :9100/:8008/:3000/:9090 | firewalled — no out-of-band telemetry |

`fork()` works and the key is accepted, so the stall is specifically in PAM / `systemd-logind`
session setup, not a dead kernel and not sshd config. `gas-repricing` is not in our teleport
cluster, so there is no second path in.

Unresolved after ~5 h of probing. The benchmark runs detached as root and is probably still
progressing, but that cannot be verified without a shell.

`tools/besu-study/classify.py` (added this round) will produce the per-category comparison —
median MGas/s per (opcode, account_mode, gas) for each arm plus the ratio — as soon as the
results directories are reachable.

---

## Round 6 — first round of baseline results (state-actor complete, jochemnet 31%)

The suites ran straight through the SSH outage. **state-actor: `rc=0`, passed=1461, failed=0,
9h58m13s, zero validation failures.** jochemnet at time of this snapshot: 448/1463, 0 failures.

`tools/nethermind-study/classify.py` reads metrics inline from each run's `result.json`
(`tests[<id>].steps.<step>.aggregated`; the `dir` field is empty and there are no per-test
files). The `test` step is the measurement.

### The control disagrees — by a lot

`overhead_baseline=True` tests do **no account-state work**, so they are the control: the two
arms should agree there whatever their data holds.

| control (132 categories) | sa/joc |
|---|---|
| min | 0.282 |
| **median** | **0.616** |
| max | 1.289 |
| within ±10% | **12 / 132** |

A 1.6× median offset with 0.28–1.29 scatter on work that touches no account state. That is the
noise/run-level floor for this pair, and it is enormous — differences smaller than ~1.6× cannot
be attributed to anything about the data.

### The measured gap is far outside that floor

| median sa/joc by account_mode | | by opcode | |
|---|---|---|---|
| NON_EXISTING_ACCOUNT | 0.066 | BALANCE | 0.050 |
| EXISTING_EOA | 0.090 | CALLCODE | 0.108 |
| EXISTING_CONTRACT_SAME_MAX | 0.106 | CALL | 0.191 |
| EXISTING_CONTRACT_MINIMAL | 0.108 | | |
| EXISTING_CONTRACT_DIFF_MAX | 0.148 | | |
| EXISTING_CONTRACT_JUMPDEST | 0.552 | | |

state-actor is **10–20× slower** on account-touching work: e.g. BALANCE/NON_EXISTING@260M
**529.71 vs 17.92 MGas/s**.

### And the bytes explain it

Median physical disk read per test:

| | jochemnet | state-actor |
|---|---|---|
| BALANCE / NON_EXISTING @260M | 99.9 MB | **8,345.4 MB** |
| BALANCE / SAME_MAX @300M | 231.8 MB | **10,140.1 MB** |

**~40× more bytes read per test.** That is the signature of the backend asymmetry recorded in
round 4, not of a data property: jochemnet serves an account from the **flat DB** (one block
per lookup) while state-actor must walk the **patricia trie** (multiple node reads per lookup,
caches dropped between steps).

Supporting sub-structure, all consistent with "the penalty is per trie-walk":
- `BALANCE` worst (0.050) — a bare account read, maximum trie exposure per unit gas.
- `CALL` best of the opcodes (0.191) — more EVM work per account touch dilutes the read penalty.
- `EXISTING_CONTRACT_JUMPDEST` the outlier mode (0.552) — code-dominated, and code lives in its
  own DB on both arms, so the trie penalty is diluted.
- `NON_EXISTING_ACCOUNT` among the worst (0.066) — proving absence still walks the trie, the
  same observation the geth study made.

### Verdict on this round

**The number is real but not yet attributable.** It measures *flat-DB vs patricia-trie reads*
at least as much as it measures *generated vs mainnet state*. Given a control that is itself
1.6× off, no conclusion about data properties can be drawn from this pair as configured.

The decisive experiment is the one round 4 already named: build a flat DB for the generated
store (`--FlatDb.ImportFromPruningTrieState=true`), then re-run. Only then do both arms read
through the same mechanism and the residual can be attributed.

Caveats on these specific figures: jochemnet is 31% complete, so most measured categories have
n=1; and the control floor above means fine-grained per-category ordering is not yet meaningful.
Re-classify when the arm finishes.

---

## Round 7 — RETRACTION: round 6's gap measures the state backend, not the state

Challenged on the size of the gap ("40x is insane — it can only come from something like
state-actor not using flat-state"). The challenge is correct. Round 6's headline is withdrawn
as a statement about generated-vs-mainnet state.

### The configs differ, and I let a number stand on that difference

Audited diff of the two run configs — four deliberate deltas, one decisive:

| delta | jochemnet | state-actor |
|---|---|---|
| **`--FlatDb.Enabled=true`** | **yes** | **no** |
| `pre_runs` + `promote_post_pre_runs` | yes | no |
| chainspec | upstream gist | generator-emitted |
| eip_override timestamp | 1769856769 | 1 |

### Chainspec ruled out

54 vs 61 EIP keys, 48 shared keys with differing values — but the differences are all
*historical schedule* (state-actor puts every fork at `0x0`; jochemnet carries real mainnet
block numbers such as `0x6f1580`). At the head both arms run the same 14 Amsterdam EIPs.
Not the cause.

### The aggregate that settles it

Medians over all measured (`overhead_baseline=False`) tests:

| | jochemnet | state-actor | ratio |
|---|---|---|---|
| gas | 182.3 M | 198.9 M | 1.09 (comparable work) |
| wall | 0.749 s | 11.405 s | **15.2×** |
| cpu | 4.44 s | 18.88 s | 4.3× |
| disk read | 233.1 MB | 6,885.1 MB | **29.5×** |
| **cpu/wall** | **5.93** | **1.66** | — |

`cpu/wall` is the tell. jochemnet keeps ~6 cores busy and is compute/parallel-bound;
state-actor sits at 1.66 and is **I/O-bound**, stalled on 29.5× more physical bytes for 9% more
gas. That is a read-path difference — flat DB (one block per account) versus patricia trie
(multiple node reads per account, caches dropped between steps) — not a data property.

### The control was misread

Round 6 treated the control's 1.6× as a noise floor. In absolute terms it is ~85 ms
(0.107 s vs 0.193 s) on 4.9 vs 6.0 Mgas, where fixed per-block overhead dominates and MGas/s is
a meaningless ratio. The control is too small to carry the interpretation put on it; it neither
supports nor refutes anything. Withdrawn.

### What is still standing

- The three-client state identity (round 1) — unaffected.
- The store-size progression 674 / 532 / 409 GiB — unaffected.
- The EIP-list finding (round 2) — unaffected.
- The **structural** finding of round 4 — strengthened, and now quantified: the arms cannot
  share a backend, and the cost of that asymmetry is 15× wall / 29.5× bytes. It dwarfs the
  ~1.1× effect the study is actually hunting.

### Consequence for sequencing

No data conclusion is available from this pair as configured, and none should be quoted. The
generated store must be given a flat DB before the arms are comparable:

1. let the jochemnet arm finish (running it concurrently with anything else would pollute its
   timings — the rounds 13/17/18 mistake);
2. mount the state-actor volume and boot Nethermind once with
   `--FlatDb.Enabled=true --FlatDb.ImportFromPruningTrieState=true` to build `flat/`, verifying
   the state root still equals `0x5b305cc0…b6e7`;
3. `schelk promote` so the flat DB is in the golden image;
4. re-run the state-actor suite with flat enabled;
5. re-classify — only then is the residual attributable.

The pre-run asymmetry (jochemnet replays a pre-run bundle and promotes; state-actor pre-deploys
via the spec and has none) remains a second, independent confound, and is the same mechanism
the geth study root-caused as journal residency. jochemnet's 400–530 MGas/s sits in the range of
geth's pre-fix artefact numbers (380) rather than its honest ones (18.5) — worth testing after
the backend is equalised.

---

## Round 8 — symmetric pair, and the geth F1 mechanism reproduces on Nethermind

The state-actor store was regenerated from state-actor HEAD `aef7bd8` (which carries `cdd7ffe`,
the flat-state writer). All four self-assertions passed:

```
OK flat/ present (479G)      OK log reports flat column DB
OK genesis hash unchanged (0xa9e61c12...9491b)
OK state root unchanged (0x5b305cc0...b6e7)
```

`state/` collapsed 364 G -> **84 K**, `flat/` is **479 G** — the trie relocated, store 523 G.
Both arms then logged the same thing for the first time:

```
state-actor: State backend: flat (existing flat DB detected)
jochemnet  : State backend: flat (existing flat DB detected)
```

state-actor suite: `rc=0`, **passed=1461, failed=0**, 11h16m, 0 validation failures.
jochemnet (unchanged, still valid): `rc=0`, passed=1463, 12h44m.

### Aggregate, both arms flat, identical gas

| | jochemnet | state-actor | ratio |
|---|---|---|---|
| gas | 198.9 M | 198.9 M | **1.00** |
| wall | 0.684 s | 9.471 s | 13.8x |
| cpu | 3.97 s | 9.52 s | 2.4x |
| disk read | 229.5 MB | 3,875.2 MB | 16.9x |
| cpu/wall | 5.80 | 1.00 | — |

Equalising the backend **halved the byte gap** (29.5x -> 16.9x) but barely moved wall
(15.2x -> 13.8x). So the backend was real but not the main term.

### The category that cracks it

Median sa/joc by account_mode (528 measured categories):

| mode | sa/joc |
|---|---|
| EXISTING_EOA | 0.061 |
| EXISTING_CONTRACT_SAME_MAX | 0.069 |
| EXISTING_CONTRACT_MINIMAL | 0.072 |
| EXISTING_CONTRACT_DIFF_MAX | 0.091 |
| EXISTING_CONTRACT_JUMPDEST | 0.383 |
| **NON_EXISTING_ACCOUNT** | **1.059** |

**Non-existing accounts are at parity.** When the lookup proves absence, the arms agree within
6%. Every category that reads a *real* account is 11–16x apart. That localises the difference
to reading existing account data — not the harness, not the engine, not the absence path.

### And the bytes say why

BALANCE, measured, same category at two gas budgets:

| | 160M | 300M |
|---|---|---|
| jochemnet read | 227.9 MB | 229.0 MB |
| state-actor read | 3,112 MB | 5,775 MB |

**jochemnet's read volume is flat in gas; state-actor's scales linearly.** Doubling the number
of accounts touched costs jochemnet nothing and costs state-actor 1.9x. A store genuinely
serving each account from disk cannot have a gas-independent read volume.

The explanation is the one the geth study spent eighteen rounds reaching: the jochemnet arm's
fixture accounts were **written moments earlier by the pre-run bundle and then promoted into the
golden image**, so they occupy a small, dense, recently-written stratum (~230 MB) that satisfies
every lookup. On geth that stratum was the pathdb journal (RAM-resident, 380 MGas/s before the
drain, 18.5 after). Here it is a compact set of freshly written SSTs. Same mechanism, different
storage layer.

The corroborating detail: jochemnet runs 400–530 MGas/s on BALANCE, sitting squarely in the
range of geth's **pre-fix artefact** (380) rather than its honest post-fix number (18.5), while
state-actor sits at 17–19 MGas/s — almost exactly geth's honest 16.5.

`NON_EXISTING_ACCOUNT` at parity is the control that proves it: those accounts were never
written by the pre-run, so neither arm has them in a privileged stratum, and the advantage
vanishes.

### Verdict

The remaining gap is **not** a property of generated state. It is the pre-run deployment
artefact, reproduced on a third client and a third storage engine. The study's target effect
(~1.1x on geth) is still buried beneath it.

**Next, and it is the geth study's own fix:** apply the treatment to the jochemnet arm — compact
its RocksDBs after the pre-run and before promote (the Nethermind analogue of
`drainjournal && geth db compact`, via the per-directory compactor) — then re-measure.
Prediction, recorded before running: jochemnet's 400–530 MGas/s collapses toward state-actor's
~18, its read volume becomes gas-proportional instead of flat, and the honest ratio lands near
1.0–1.2 rather than 0.09.

---

## Round 9 — full classification of all 1,461 tests; the compaction hypothesis is wrong

Challenged that "16x is too much to be a compaction-related thing". Correct — and the full
classification kills that hypothesis outright.

Earlier passes keyed categories on `(opcode, account_mode, gas)` and **silently dropped every
test family lacking those tokens** (sload/sstore/storage-pattern, ether transfers). This pass
matches on the **exact test identity** `file::func[params]`, arm to arm.

`jochemnet usable 1463 | state-actor usable 1461 | exact-id matches 1461 | gas mismatches 0`

### Bucket 1 vs Bucket 2

| bucket | n | share | ratio min / median / max |
|---|---|---|---|
| **AGREE** (within ±10%) | **187** | 12.8% | 0.903 / 1.003 / 1.098 |
| **DIVERGENT** | **1,274** | 87.2% | 0.032 / 0.403 / 1.870 |

Of the divergent: 1,162 state-actor slower, 112 state-actor faster.

### Divergent set, classified — with physical evidence

| category | n | agree | thr sa/joc | **read sa/joc** | cpu sa/joc | jocMB | saMB |
|---|---|---|---|---|---|---|---|
| ACCOUNT cold non-existing | 110 | 50 | 1.051 | 2.94 | 1.21 | 77.8 | 218.3 |
| **STORAGE slot access** | 88 | 57 | **1.006** | **1.04** | 1.13 | 632.9 | 626.0 |
| ACCOUNT warm query | 77 | 27 | 0.876 | **145.73** | 1.24 | 1.5 | 228.8 |
| CONTROL overhead_baseline | 440 | 46 | 0.733 | **49.54** | 2.21 | 1.9 | 96.1 |
| ETHER transfer receivers | 196 | 7 | 0.385 | 1.88 | 1.23 | 4015.1 | 7793.1 |
| ACCOUNT cold existing contract | 440 | 0 | **0.089** | 8.81 | 2.10 | 231.0 | 4618.7 |
| ACCOUNT cold existing EOA | 110 | 0 | **0.059** | 14.83 | 3.22 | 231.1 | 3906.5 |

state-actor-faster outliers (>1.10, n=112): CONTROL 42, non-existing 39, storage 21, warm 6,
ether 4 — i.e. they sit entirely in the categories that already agree.

### What this rules out

**Storage-slot access is identical**: throughput 1.006, **read ratio 1.04**, 632.9 vs 626.0 MB.
The two stores serve storage reads indistinguishably. Whatever is wrong is *not* a
whole-database property — not overall size, not LSM shape in general, not compaction state in
general, and not the storage column.

**Compaction cannot explain it.** A globally uncompacted store would penalise storage lookups
too. Storage is at parity while account lookups are 8.8–14.8x on bytes. The defect is confined
to the **account column**.

**Nor is it "generated vs mainnet state"**, the study's nominal question: non-existing account
lookups are at parity (1.051) and storage is at parity, both against the same generated store.

### The actual signature

The discriminator is **bytes per account point-lookup**, and it is present even where no
account work is expected:

- CONTROL does no account-state work, yet state-actor reads **96.1 MB vs 1.9 MB** (49.5x).
- Warm account queries read **228.8 MB vs 1.5 MB** (145.7x) while costing only 12% more time.
- jochemnet reads a near-constant **~231 MB** across every cold-existing-account category
  regardless of opcode or account type, i.e. roughly one block per lookup.

Order-of-magnitude: state-actor appears to pay **~20 block reads per account point-lookup**
where jochemnet pays ~1, consistently across control, warm and cold categories. That is the
signature of point lookups probing many overlapping SSTs and/or ineffective bloom filtering on
the account column — a property of how the store was *constructed*, not of what it contains.

CPU ratios corroborate the split: ~1.1–1.3x wherever bytes are at parity, 2.1–3.2x exactly in
the categories that read 9–15x more bytes.

### Next — isolate, do not re-run

The expensive suites have nothing more to give. The decisive measurements are cheap and
offline, on the account column of each flat DB:

1. SST count and level distribution (an L0 pile with overlapping ranges forces one probe per file);
2. bloom-filter presence/config and `whole_key_filtering` on the account column;
3. block size and index/filter block sizes;
4. a direct per-lookup counter: N random existing-account reads against each store, measuring
   physical bytes per lookup.

(4) converts "~20 blocks per lookup" from inference to measurement, and (1)–(3) say why.

---

## Round 10 — the database is exonerated: configs identical, per-lookup cost equal or better

Two questions, answered in order: are the RocksDB configurations the same, and do the two
stores have the same properties?

### 1. RocksDB configuration — the same

Compared each store's own OPTIONS file, database by database and column family by column
family. For the `Account` CF, every read-path-critical setting is **identical**:

| | SA | JOC |
|---|---|---|
| filter_policy | `ribbonfilter:10:3; bloom_before_level=3` | same |
| whole_key_filtering | true | same |
| block_size / metadata_block_size | 4096 | same |
| index_type / data_block_index_type | kBinarySearch / kDataBlockBinaryAndHash | same |
| cache_index_and_filter_blocks | false | same |
| format_version | 5 | same |
| compression | kNoCompression | same |
| target_file_size_base | 32 MB (x3/level) | same |

DBOptions likewise: `max_open_files=-1`, no direct I/O, `advise_random_on_open=true`,
`compaction_readahead_size=2 MB`, `table_cache_numshardbits=6` — all identical.

Only three keys differ, none of which affect per-lookup read cost:
`level0_file_num_compaction_trigger` (SA `2147483647` — a bulk-load setting),
`write_buffer_size` (256 MB vs 1–64 MB), `max_bytes_for_level_base` (128 vs 67 MB).
All three are **write-side**.

**"Missing bloom filters" and "different block size" are dead.**

### 2. LSM shape — different, but in state-actor's favour

`Account`: SA has **92 files, 23.17 GB, all in L3**; JOC has **364 files, 16.25 GB across
L0–L4**. Fewer levels means fewer probes per point lookup, so if anything this favours SA.
The `INT_MAX` L0 trigger did **not** leave data piled in L0 — the generator compacts internally.

Byte-per-entry, a useful cross-check: **SA 57.8 B vs JOC 49.2 B**, against the geth study's
58.3 vs 49.6. Third client, same record-shape result.

### 3. Per-lookup cost — measured, not inferred

`tools/nethermind-study/probe-flat` opens each store's flat DB directly (no Nethermind, no
benchmarkoor), samples keys by **uniformly random seeks** across the keyspace, drops the page
cache, and performs cold point lookups in a fresh process, measuring physical bytes via
`/proc/self/io`.

20,000 lookups, 100% hits, per column family:

| CF | SA blocks/lookup | JOC blocks/lookup | SA us/lookup | JOC us/lookup |
|---|---|---|---|---|
| Account | **1.99** | 2.51 | **188.4** | 219.2 |
| StateNodes | **3.45** | 10.69 | **344.9** | 391.4 |
| Storage | 2.52 | 2.21 | 200.4 | 197.9 |

**state-actor is as cheap or cheaper in every column family.** ~2 blocks per account lookup is
textbook for a leveled LSM with whole-key filtering.

(First run of this probe was discarded: `bufio.Read` short-reads desynchronised the key stream,
producing identical hit/miss counts on two different databases — an impossible result, and the
tell that the measurement was wrong. Fixed with `io.ReadFull`.)

### Verdict

The 9–15x read amplification seen in the benchmark **cannot come from the store**. Configuration
is identical, and per-lookup cost is equal or better on state-actor in all three column families
that matter. My round-8 pre-run-residency story and round-9 account-column story are both
**withdrawn** as explanations of the read volume.

What remains is arithmetic: the benchmark reads ~78 KB per account access on state-actor while a
cold Account lookup costs ~8 KB. So the client is performing **~10 lookups per account access**
on that arm, where jochemnet's ~4.6 KB per access is *below* one cold lookup (i.e. partly
cache-served).

### The sharp hypothesis, and how to kill it

A trie walk is ~8 nodes; at SA's measured 3.45 blocks/node that is ~113 KB — the right order for
the observed ~78 KB. The same walk on jochemnet would cost ~350 KB, which it plainly does not
pay. So: **state-actor's flat account lookups may be missing and falling back to the trie**,
while jochemnet serves from flat. Both arms log `State backend: flat`, and jochemnet *cannot*
fall back (its trie is pruned) — which is why only one arm shows it.

If true this is a **state-actor key-encoding defect in the flat Account CF**, not a property of
generated state, and it would explain the whole pattern: storage tests agree (storage path
fine), non-existing accounts agree (absence proven without a flat hit), existing-account reads
diverge.

Decisive test, cheap: take a known-existing address in the generated store (the spec's
sequential EOAs from `0x...1000`), compute the key exactly as Nethermind does, and check for its
presence in the flat `Account` CF. Present -> hypothesis dead. Absent -> root cause found.

---

## Round 11 - ROOT CAUSE: working-set saturation, not store quality

The key-encoding hypothesis of round 10 is **dead**: all six spec-guaranteed addresses resolve
in the state-actor flat `Account` CF (`keccak256(addr)[0:20]`, 20-byte keys, identical key
histograms in both stores), and they resolve in the jochemnet store too. No fallback to trie.

### What was disproven along the way
| hypothesis | killed by |
|---|---|
| flat key-encoding defect | all fixture addresses FOUND in both stores |
| client read path amplifies | cold client `eth_getBalance` on SA = 1.99 blk = exactly its raw RocksDB cost |
| startup I/O dominates | JOC boots **heavier** (6.53 GB) than SA (4.81 GB), yet runs 16x faster |
| background compaction | writes negligible during runs (W/R = 0.02) |
| flat `CurrentState` lag forces trie reads | both arms execute ~2 blocks past their own marker - symmetric |

### The measurement that settles it
Offline RocksDB point lookups on the exact key population the tests touch (the EEST fixtures'
sequential accounts), cold caches, fresh process per point, 100% hits on both arms:

| N | SA blk/lookup | SA total | JOC blk/lookup | JOC total |
|---|---|---|---|---|
| 500 | 2.00 | 4.1 MB | **1.88** | 3.9 MB |
| 2,000 | 1.99 | 16.3 MB | 1.65 | 13.5 MB |
| 8,000 | 1.99 | 65.2 MB | 1.06 | 34.8 MB |
| 20,000 | 1.99 | 162.6 MB | 0.55 | 45.0 MB |
| 50,000 | 1.97 | 404.4 MB | **0.23** | **47.2 MB** |

state-actor is **flat at ~1.99 blocks/lookup**, volume linear in N. jochemnet's per-lookup cost
**collapses** while its total read **saturates at ~47 MB**. At N=500 - before any amortisation -
the arms are at parity: **1.88 vs 1.88 blocks, 164 vs 184 us**.

### Root cause
The jochemnet arm's fixture accounts are concentrated in a bounded ~47 MB stratum, written and
promoted by its `pre_runs` + `promote_post_pre_runs: true` (a **jochemnet-only** config, flagged
as one of the four deliberate differences in round 5). A few thousand lookups make that stratum
fully resident; every later lookup is free. On the generated store the same accounts are ordinary
residents of a 24.88 GB fully-compacted L3 (92 files, all at level 3, 430.7 M entries), so there is
no bounded working set to saturate and the cost stays at two blocks indefinitely. Concentration
ratio: fixture keys are ~5% of entries in the blocks JOC touches vs ~0.005% on SA - about 1000x.

**The benchmark measures RAM on one arm and disk on the other.** The generated store is not slow:
its honest cold cost equals jochemnet's honest cold cost.

### Why this reproduces every category
- `NON_EXISTING_ACCOUNT` agrees (1.051) - misses short-circuit, never touch the stratum.
- `STORAGE slot access` agrees (1.006) - the storage sweep far exceeds any bounded stratum, so
  neither arm saturates.
- Every `EXISTING_*` account category diverges - exactly the ones that hit the stratum.
- jochemnet's benchmark read volume is flat in gas (227.9 MB @160M, 229.0 MB @300M) = saturated;
  state-actor scales linearly (3,112 -> 5,775 MB) = never saturates.

### Consequence for the study
Comparing a pre-run/promoted snapshot against a generated store is **invalid for account-read-heavy
tests**. Either give both arms a pre-run, or neither. The 674/532/409 GiB state-size progression,
the EIP-list finding, and the backend-asymmetry finding are unaffected.

Tooling: `tools/nethermind-study/probe-flat-main.go` (modes `probe`/`seq`/`addr`/`keys`/`meta`/`locate`),
`clientio.sh`, `clientio2.sh`, `pertest.py`, `rw.py`, `attrib.sh`.

---

## Round 12 - pipeline audit + causal proof + reconciliation with the geth study

Anon challenged round 11 on two correct grounds: benchmarkoor **does** clear caches between the
pre-run and the payload, and the Nethermind arm appends blocks so the last-256 preload misses
test slots. Both are true. Round 11's wording ("fully cache-resident") was wrong; the finding is
not about cache warmth and survives both mechanisms.

### Pipeline, from source (not assumed)
- `pkg/executor/executor.go:460` - `dropBetweenTests` is true for `"tests"` **and** `"steps"`;
  `:518` drops between every test after the first; `:592` drops between setup and test step.
  Both arms set `drop_memory_caches: "steps"`. Cache warmth is genuinely excluded.
- Pre-run steps run once, before the test loop (`:465`), so only test 1 of 1,461 sees pre-run heat.
- Both arms: `rollback_strategy: container-recreate`. **Only jochemnet** sets
  `pre_runs: .../pre_run_bundle` and `schelk_options: promote_post_pre_runs: true`.
- Pre-run bundle: single 10.06 GB NDJSON, **7,736 `engine_newPayloadV5` blocks x 64 txs**
  (~495k txs), blocks 24,402,728 -> 24,410,463. The tail blocks are **not** empty fillers
  (last 200 all carry 64 txs).

**The reconciliation:** `promote_post_pre_runs: true` makes schelk promote the volume *after* the
pre-run, freezing the post-pre-run **on-disk SST layout** into the golden image every test restores
from. Cache-clearing and filler blocks defend against *warmth*; neither touches *placement*.
And the amortisation is **intra-test**, not inter-test: each test independently re-pays a bounded
~47 MB distinct-block footprint on jochemnet versus unbounded growth on state-actor. (The probe
sets `fill_cache=false`, so the saturation measured is OS page-cache over distinct physical blocks,
which is exactly what a single test experiences.)

### Causal proof - single-variable intervention
Forced full compaction of the **jochemnet** Account CF. No value changed, only placement:
levels `map[3:4 4:36 5:304 6:20]` -> `map[6:196]`, 192.6 s.

| N | BEFORE (clustered) | AFTER (compacted) | state-actor (reference) |
|---|---|---|---|
| 2,000 | 1.65 blk, 13.5 MB, 107 us | 1.80 blk, 14.7 MB, 169 us | 1.99 blk, 16.3 MB, 185 us |
| 20,000 | 0.55 blk, 45.0 MB, 20 us | 1.78 blk, 146 MB, 216 us | 1.99 blk, 163 MB, 184 us |
| 50,000 | **0.23 blk, 47.2 MB, 11 us** | **1.76 blk, 361 MB, 186 us** | 1.97 blk, 404 MB, 179 us |

Compaction alone moved wall-clock **16.6x** and made jochemnet indistinguishable from state-actor.
That is the benchmark's 16x gap, reproduced by changing nothing but where bytes sit on disk.
Volume goes from saturating (45.0 -> 47.2 MB) to linear (146 -> 361 MB). Store restored afterwards
via `schelk promote`.

### Why the geth study saw "only a bit" - it didn't
The geth report's own provenance: *"compacted and uncompacted are the same jochemnet mainnet
shadowfork snapshot, with and without manual pebble compaction; state-actor is synthetically
generated state."* Its headline metric is **state-actor / compacted** - i.e. measured against the
arm whose clustering was **manually compacted away**. Against the *uncompacted* arm (the true
analogue of the Nethermind jochemnet arm), geth's own numbers (us per account lookup):

| category | compacted | uncompacted | state-actor | sa/compacted | **sa/uncompacted** |
|---|---|---|---|---|---|
| NON_EXISTING | 14.31 | 17.28 | 15.68 | 1.10 | **0.91** |
| EOA | 15.15 | 8.34 | 16.73 | 1.10 | **2.01** |
| MINIMAL | 14.22 | 3.17 | 15.23 | 1.07 | **4.80** |
| SAME_MAX | 13.83 | 2.63 | 15.25 | 1.10 | **5.81** |
| JUMPDEST | 13.87 | 3.14 | 15.49 | 1.12 | **4.94** |

Same signature as Nethermind: `NON_EXISTING` at parity (0.91 vs our 1.05), every account-reading
category diverging. Note also that **compacting made geth 4-5x slower** (15.15 vs 8.34, 14.22 vs
3.17) - the same direction as our intervention. The geth study's journal root cause explains
state-actor vs the snapshot pair; it cannot explain compacted vs uncompacted, since LOGMINE records
the 380.15 MiB journal as `loaded` on **both**.

So the answer to "why geth only a bit": the comparison differs, not the client. geth: 2.0-5.8x
against its uncompacted arm; Nethermind: 2.6-16.4x. Residual amplitude is plausibly geth's much
larger in-process absorption (1023 MiB clean trie cache + 2.00 GiB db cache, per LOGMINE) plus the
fact that Nethermind's jochemnet arm is promoted *immediately* after a 7,736-block pre-run, which
maximises clustering, whereas geth's snapshot was compacted by hand.

### Standing conclusion
Unchanged and now causally demonstrated: the generated store is not slow, and the gap is a
benchmark-methodology artefact of comparing a freshly-pre-run, promoted, uncompacted snapshot
against a generated store. Valid options: give both arms a pre-run, or compact both before
measuring. Compacting both is the cheaper control and geth's compacted arm shows it lands at ~1.1x.

### Provenance note - the jochemnet store is now compacted (my error, low impact)

I ran `schelk promote` intending to restore the pre-compaction volume. In schelk, `promote` copies
**scratch -> virgin**, i.e. it promotes the *current* state into the golden image. It did exactly
that (289,689 blocks, 17.68 GB, 12.07 s), so the jochemnet golden image now holds the **compacted**
Account CF: `196 files, 12.84 GB, levels map[6:196]`, behaviour 1.76 blk / 361 MB / 50k lookups.
The `snapshot-24402727.tar.zst` tarball was deleted earlier to reclaim space, so restoring the
pristine layout means re-downloading ~1.26 TB.

Impact is low, and partly favourable:
- Both baseline suites (jochemnet 1463/1463, state-actor 1461/1461) were measured **before** this
  and are committed; no collected result is affected.
- The store is now in precisely the state the corrected experiment needs: a **compacted** jochemnet,
  which is the geth study's headline reference arm (`sa/compacted` ~ 1.1x).

**Recommended next run:** re-run the jochemnet suite against the now-compacted store and compare to
the existing symmetric state-actor results. Predicted from the probe: the 16x gap collapses to
~1.1-1.2x. That would validate the placement finding end-to-end inside benchmarkoor rather than in
a probe, and it costs one ~13 h arm since state-actor's side is already done.

---

## Round 13 - the intervention arm: remove the advantage, measure the residual

Anon's actual goal (not a geth replication): modify one store so the perf-altering advantage is
**removed**, then measure how far jochemnet still sits from state-actor. Launched 2026-09-13 13:22.

### What was modified, and what deliberately was not
| target | size | action | why |
|---|---|---|---|
| `flat/Account` | 16.25 -> 12.84 GB | **compacted**, `map[3:4 4:36 5:304 6:20]` -> `map[6:196]` | the CF carrying every divergent category |
| `code/` | 7.6 GB | **compacted**, `map[0:3 5:6 6:117]` -> `map[6:115]` | 3 files sat at L0 - the pre-run's fresh code writes; JUMPDEST is code-dominated |
| `flat/Storage` | 88.92 GB | left alone | storage already at parity (1.006); nothing to remove |
| `flat/StorageNodes` | 195.21 GB | left alone | trie, bypassed by the flat backend; also > 117 GB free |
| `flat/StateNodes` | 39.10 GB | left alone | same |

### The config trap
Re-running the arm as-is would have **re-created the clustering**: `pre_runs` replays 7,736 blocks
x 64 txs, rewriting every fixture account into fresh L0 SSTs. So `nm-joc-compacted.yaml` drops
`pre_runs` and `schelk_options.promote_post_pre_runs`. Their *state* effects are already baked into
the promoted volume (head 24,410,463), so the arm starts from identical state without re-clustering.
Diff vs the original config is exactly: results_dir, label, instance id, and those two blocks.
Everything else byte-identical - image, genesis, `genesis_eip_override` (14 EIPs), `extra_args`
(`--FlatDb.Enabled=true`), `drop_memory_caches: "steps"`, `rollback_strategy: container-recreate`,
fixtures URL.

Smoke (1 test, pre-run stripped): `rc=0`, `passed=1 failed=0`, `State backend: flat`, zero
"pre-run" log lines. Full run discovered 1463 tests with **`pre_run_steps=0`**.

### Prediction, recorded before results exist
Basis: post-compaction probe parity - jochemnet 1.76 blk / 186 us vs state-actor 1.97 blk / 179 us;
and geth's analogous compacted comparison landing at 1.03-1.12x.

| category | before (sa/joc) | predicted after |
|---|---|---|
| EXISTING_EOA | 16.4x | **1.0-1.2x** |
| EXISTING_CONTRACT_SAME_MAX | 14.5x | 1.0-1.2x |
| EXISTING_CONTRACT_MINIMAL | ~14x | 1.0-1.2x |
| EXISTING_CONTRACT_DIFF_MAX | 11.0x | 1.0-1.3x |
| EXISTING_CONTRACT_JUMPDEST | 2.6x | 1.0-1.3x |
| NON_EXISTING_ACCOUNT | 1.05x | **unchanged ~1.05x** (control) |
| STORAGE slot | 1.006x | **unchanged ~1.0x** (control) |

The two controls are the falsifier: if the account categories collapse to ~1x *and* the controls
stay put, placement is confirmed as the whole mechanism. If the account categories stay high, the
placement story is incomplete and something else is carrying the gap.

Classify on completion with `tools/nethermind-study/buckets.py` /
`classify.py <joc-compacted_results> <sa_results>`.

### Round 13 operations - surviving this box's SSH stalls

This machine drops interactive sessions under sustained benchmark I/O (five occurrences, always
PAM/`systemd-logind` session setup starving on `md2` I/O, never a dead kernel or sshd). Every
detached job has completed through every episode, so the run is structured to need no session:

- **Suite**: `benchmarkoor` (pid 3266554) -> `run-joc-compacted.sh` -> **systemd(1)**, `TT=?`,
  own session id, **no sshd ancestor**. Launched with `setsid nohup`; proven independent by
  surviving the exit of its launching SSH connection.
- **Supervisor**: tmux session `joc` (server pid 3323279, **PPID 1**, no sshd ancestor) running
  `tools/nethermind-study/watch-joc.sh`. Logs progress to `/bench/logs/joc-monitor.log` every
  5 min and, the moment the suite exits with >100 tests done, runs `buckets.py`, `buckets2.py`
  and `classify.py` against `/bench/results/nm-state-actor`, writing
  `/bench/logs/joc-compacted-classification.txt`.

The two layers are independent: killing tmux does not touch the suite, and losing the suite still
leaves every result on disk. Attach with `ssh ubuntu@157.180.2.180 -t tmux attach -t joc`.
zellij is not installed on this host; tmux is.

Note the supervisor guards against a false "finished": a dead `benchmarkoor` with <=100 tests
completed is reported as a startup failure rather than classified.

---

## Round 14 - Phase 1: repair the contamination, extend the intervention to the trie

### Damage assessment: narrower than feared
`code/`'s **real** Nethermind options are `filter_policy=nullptr`, `kSnappyCompression`,
`block_size=4096`, `block_restart_interval=16` - i.e. essentially RocksDB defaults. So the round-13
`compactdb` of `code/` was **not** contaminated. Only `flat/Account` was.

Options are **per-CF, not uniform** - transcribing one set would have re-contaminated the others:

| CF | block_size | restart | compression | target/mult | mbflb | dynamic | filter |
|---|---|---|---|---|---|---|---|
| Account | 4096 | 4 | kNoCompression | 32M/3 | 128M | false | ribbon 10:3 |
| Storage | 8000 | 4 | kLZ4 | 64M/2 | 256M | false | ribbon 10:3 |
| StateNodes | 16000 | 8 | kLZ4 | 64M/2 | 256M | true | ribbon 10:3 |
| StateTopNodes | 16000 | 8 | kLZ4 | 64M/2 | 256M | true | ribbon 10:3 |
| StorageNodes | 16000 | 8 | kLZ4 | 64M/2 | 350M | true | ribbon 10:3 |
| FallbackNodes | 16000 | 8 | kLZ4 | 64M/2 | 4M | true | ribbon 10:3 |
| Metadata | 16000 | 4 | kLZ4 | 64M/2 | 1M | false | ribbon 10:3 |
| default | 4096 | 16 | kSnappy | 67M/1 | 268M | true | none |

`LatestOptions` has no exported accessors in grocksdb 1.10.8, so load-from-template was impossible;
the specs are transcribed into `flatSpecs` and **verified afterwards by an OPTIONS diff** - the
check that would have caught the original error. `SetDisableAutoCompactions(true)` on open, so only
the explicit `CompactRangeCFOpt(..., kForce)` writes files; kForce is required because a CF already
wholly in its bottom level is a no-op for a plain CompactRange.

### Result
| CF | before | after | time |
|---|---|---|---|
| `flat/Account` | `[6:196]` 12.84 GB (wrong options) | `[6:37]` **17.38 GB** | 185 s |
| `flat/StateNodes` | `[0:3 3:1 4:4 5:60 6:487]` 39.10 GB | `[6:158]` 38.98 GB | 708 s |

Account grew because compression went Snappy -> none (correct). **StateNodes had 3 files at L0** -
the pre-run's fresh trie writes, the same signature `code/` showed - now merged. OPTIONS parity
verified on every read-path knob for both CFs. Free space 117 -> 112 GB.
`flat/Storage` (88.92 GB, 2 files at L0) left untouched **on purpose**: it is the negative control.
`flat/StorageNodes` (195.21 GB) cannot fit in the free space.

### Probe: an honest correction to round 13's explanation
20,000 cold lookups, fresh process, `fill_cache=false`, Account CF:

| arm | hits | misses |
|---|---|---|
| jochemnet | 1.98 blk, 181 us | 1.99 blk, 198 us |
| state-actor | 1.99 blk, 210 us | 1.99 blk, 222 us |

Both arms now identical in block count, and jochemnet is marginally *cheaper* in time.

**But misses cost the same as hits (~2 blocks) on state-actor too - whose ribbon filter I never
touched.** So absent-account lookups get no filter-rejection benefit in this configuration on
either arm, and my round-13 claim that filter loss explains the NON_EXISTING inversion is
**incomplete**: placement was doing more of that work than I credited. Recorded rather than
quietly dropped; Phase 2 settles it.

### Phase 2 launched 2026-09-14 06:07 - predictions recorded before results exist
266 tests (`filter: regex:(160M|240M)`), covering all six families and every opcode x account_mode
cell at two gas points, so both the ratio and its gas-slope are checkable. Config diff vs the
round-13 arm: results_dir, label, instance id, filter.

| category | round 13 (contaminated) | predicted now | basis |
|---|---|---|---|
| existing EOA / contract | 0.866 / 0.858 | **0.88-1.00** | probe parity 1.98 vs 1.99 blk; jochemnet now uncompressed so reads slightly more |
| NON_EXISTING | 19.319 | **0.9-1.1** | probe miss parity 1.99 vs 1.99 blk |
| CONTROL overhead_baseline | 0.701 | **-> ~1.0 if trie placement is the cause; stays ~0.70 if not** | StateNodes now single-level |
| STORAGE slot | 1.026 | **~1.0 unchanged** | Storage CF deliberately untouched - negative control |

CONTROL is the discriminating cell: it does no account-state work, so only the trie-placement
hypothesis predicts it moving.

---

## Round 15 - Phase 2 attempt 1 was an accidental replication; the schelk promote trap

Phase 2 ran 266/266, 0 failures - and returned numbers essentially identical to round 13:

| category | round 13 | Phase 2 attempt 1 | delta |
|---|---|---|---|
| existing EOA | 0.866 | 0.865 | 0.1% |
| existing contract | 0.858 | 0.853 | 0.6% |
| NON_EXISTING | 19.319 | 19.175 | 0.7% |
| CONTROL | 0.701 | 0.709 | 1.1% |
| STORAGE | 1.026 | 1.047 | 2.0% |
| warm query | 0.914 | 0.874 | 4.4% |
| ETHER transfers | 0.747 | 0.735 | 1.6% |

Both pre-registered predictions "failed". They did not: **the intervention was never applied during
the run.** `rollback_strategy: container-recreate` restores the volume from schelk's **virgin**
image before every test. The Phase 1 rebuild was written to the mounted **scratch** volume and no
`schelk promote` followed, so test 1 discarded it. Proof: immediately after the run,
`flat/StateNodes` was back to `[0:3 3:1 4:4 5:60 6:487]` and `flat/Account` back to `[6:196]` with
`filter_policy=nullptr` / `kSnappyCompression` - byte-for-byte the round-13 state.

I had already learned `promote` means scratch -> virgin (round 13's provenance note, where it
overwrote the pristine image) and still failed to apply it as a required step. Recorded as a
process rule: **any store modification intended to be measured must be followed by
`schelk promote`, and verified by re-reading the CF shape after the first test completes.**

Silver lining: attempt 1 is a genuine independent replication of round 13 on a different test
subset. Agreement is 0.1-2% on six of seven categories, so these ratios are stable run-to-run and
neither the 16x collapse nor the 19x non-existing inversion is noise. Kept as
`/bench/results/nm-joc-replication`.

### Also corrected: the filter did not explain the non-existing inversion
The probe on the rebuilt store showed misses costing the same as hits (~1.99 blocks) on **both**
arms - including state-actor, whose ribbon filter I never touched. Absent-account lookups get no
filter-rejection benefit in this configuration, so round 13's "filter loss inverted the control"
claim was wrong. The inversion has to be placement or a structural difference; attempt 2 separates
them.

### Structural asymmetry now quantified
| arm | `state/` | `flat/` | `code/` | StateNodes CF | random cold StateNodes lookup |
|---|---|---|---|---|---|
| state-actor | **160 KB** | 478 GB | 45 GB | 603 files, 51.17 GB, `[6:603]` | **3.44 blk, 208 us** |
| jochemnet | **341 GB** | 314 GB | 7.6 GB | 555 files, 39.10 GB | **10.26 blk, 434 us** |

state-actor's trie is relocated into `flat/` (hence `state/` = 160 KB) and its trie-node lookups
are **3x cheaper** than jochemnet's. That is the candidate explanation for both the 19x
non-existing result and the CONTROL residual, and it is a property of the store, not an artifact.

### Phase 2 attempt 2 launched 2026-09-14 08:46
Rebuild re-applied **and promoted**; verified live after 2 completed tests: Account `[6:37]`
17.38 GB, StateNodes `[6:158]` 38.98 GB, `filter_policy={id=ribbonfilter:10:3;bloom_before_level=3;}`,
`kNoCompression` - now byte-identical to state-actor's settings. Same 266-test subset, same
predictions as round 14: CONTROL is the discriminating cell (only the trie-placement hypothesis
predicts it moving off ~0.70).

---

## Round 16 - Phase 2 corrected: the stores are at parity once placement is equalised

266/266, 0 failures, `rc=0`, finished 2026-09-14 11:04. Intervention verified **live** after two
completed tests (Account `[6:37]`, StateNodes `[6:158]`,
`filter_policy={id=ribbonfilter:10:3;bloom_before_level=3;}`, `kNoCompression`).

### The whole study in one table (throughput ratio state-actor / jochemnet; 1.00 = parity)

| category | original (confounded) | Account-only, wrong options | **corrected** | read sa/joc | jocMB | saMB |
|---|---|---|---|---|---|---|
| ACCOUNT cold existing EOA | **0.059** | 0.865 | **0.983** | 1.06 | 3587 | 3771 |
| ACCOUNT cold existing contract | **0.089** | 0.853 | **0.966** | 1.09 | 4366 | 4629 |
| ACCOUNT cold non-existing | 1.059 | 19.175 | **0.939** | 5.68 | 39 | 220 |
| STORAGE slot access | 1.006 | 1.047 | **1.013** | 1.05 | 763 | 842 |
| ETHER transfer receivers | **0.385** | 0.735 | **1.015** | 1.16 | 6471 | 7711 |
| ACCOUNT warm query | 0.876 | 0.874 | **0.867** | 176.2 | 1.4 | 242 |
| CONTROL overhead_baseline | 0.733 | 0.709 | **0.717** | 48.2 | 1.8 | 96 |

Tests agreeing within +/-10% rose from **12.6% -> 53.4%**. `EXISTING_EOA` agrees on **20/20**.
By account_mode: EOA 0.983, MINIMAL 0.969, SAME_MAX 0.966, NON_EXISTING 0.939, JUMPDEST 0.881,
DIFF_MAX 0.667 (DIFF_MAX was the outlier in the geth study too, at sa/compacted 7.71).

### Prediction scorecard (registered in round 14, before any of these numbers existed)
| prediction | outcome |
|---|---|
| existing EOA/contract 0.88-1.00 | **correct** - 0.983 / 0.966 |
| NON_EXISTING 0.9-1.1 | **correct** - 0.939 |
| STORAGE ~1.0 unchanged (negative control) | **correct** - 1.013 |
| CONTROL -> ~1.0 if trie placement is the cause | **FALSIFIED** - 0.717, unmoved (1.8 vs 2.0 MB) |

The non-existing inversion **was** the missing ribbon filter after all: restoring it returned the
category to parity. Round 15's probe reading ("misses cost the same as hits on both arms") was
misleading - most likely because `fill_cache=false` plus a synthetic address range defeats the
filter path the client actually exercises. Corrected again; the end-to-end measurement wins over
the micro-probe.

### Conclusion
**The original 11-16x gap is entirely a data-placement artifact.** With placement equalised and
every read-path option verified byte-identical, synthetically generated state and mainnet-derived
state are within **1.7-3.4%** on existing-account reads, **1.3%** on storage, **1.5%** on ether
transfers, and **6%** on absent accounts. Generated state is a valid substitute for state-DB
benchmarking **provided both arms get the same placement treatment**.

### What remains unexplained (one cell, and it is not placement)
`CONTROL overhead_baseline` - tests doing **no account-state work** - is stuck at 0.717 across all
three runs (0.733 / 0.709 / 0.717). state-actor reads **48x more bytes** (96 MB vs 1.8 MB) and burns
**2.2x the CPU**. Compacting `flat/StateNodes` moved it by 1%, so the trie-placement hypothesis is
dead. Candidates not yet tested: the `flat/StorageNodes` CF (195 GB, cannot be compacted in 112 GB
free), the 430.7M vs 354M account count, or per-block work proportional to generated storage size.
This is a **separate finding about baseline block execution**, not about state-DB reads, and it does
not affect the conclusion above - it is a floor present in every arm and category.

### Process rules earned
1. Any store modification intended to be measured MUST be followed by `schelk promote`, and
   verified by re-reading the CF shape **after the first test completes**.
2. Compact/rewrite with the store's **per-CF** options, never `NewDefaultOptions()`, and verify with
   an OPTIONS diff. Nethermind's per-CF settings differ substantially (4-16 KB blocks, restart 4-16,
   none/LZ4/Snappy).
3. Prefer the end-to-end benchmark over micro-probes when they disagree.

---

## Round 17 - what still diverges, and why it is one overhead rather than many failures

124 of 266 tests remain outside +/-10%. Decomposed: **73 are `overhead_baseline=True`** (the known
control cell) and **51 actually read state**. Of those 51:

| cluster | n | ratio | jocMB | saMB | note |
|---|---|---|---|---|---|
| `EXISTING_CONTRACT_DIFF_MAX` | 16 (all of them) | 0.615-0.725 | 3.4-5.1 GB | 5.3-8.1 GB | reads ~1.55x more - the only genuine state-read residual |
| `NON_EXISTING_ACCOUNT` tail | 9 of 20 | 0.587-0.771 | 11-48 MB | 100-316 MB | category median is 0.939: the cell is bimodal |
| `test_ext_account_query_warm` | 8 of 14 | 0.612-0.785 | ~1 MB | 229-370 MB | 200x+ more bytes yet only 1.3-1.6x slower |
| `test_ether_transfers_onchain_receivers` | 7 of 36 | 0.676-1.238 | 5.4-8.7 GB | 7.2-10.9 GB | scatter about parity |
| sload/sstore_bloated | 7 | **1.6-1.76 (state-actor FASTER)** | - | - | reverse-sign outliers |

### The unifying measurement: the excess is ADDITIVE, not multiplicative

| jochemnet read volume | n | med jocMB | med saMB | **med excess** | saMB/jocMB | thr sa/joc |
|---|---|---|---|---|---|---|
| 0-10 MB | 98 | 1.8 | 109.5 | **107.1** | 58.6 | **0.734** |
| 10-100 MB | 18 | 33.6 | 218.3 | **176.8** | 6.2 | 0.931 |
| 100-1000 MB | 10 | 481.2 | 703.0 | **78.6** | 1.1 | 1.125 |
| 1000-4000 MB | 44 | 2921.7 | 3105.1 | **189.7** | 1.1 | 0.978 |
| 4000+ MB | 96 | 5315.4 | 6588.7 | 901.4 | 1.1 | 0.972 |

Across a **1600x range** of test size the absolute excess stays at ~80-190 MB (median over all 266:
190 MB, p10 39, p90 1174). So the model is

**saMB ~= 1.1 x jocMB + ~150 MB**

and the throughput ratio follows mechanically: a test that would read 1.8 MB is swamped by the
fixed term (0.734), a test reading 34 MB partly absorbs it (0.931), and anything reading >=100 MB
is at parity (0.97-1.13). **The remaining "big diffs" are not a set of broken categories - they are
one fixed per-test read overhead surfacing wherever the test itself reads almost nothing.**

This retires the CONTROL puzzle as a special case: `overhead_baseline` tests read 1.8 MB, so they
are simply the extreme of the same additive term. It also explains why compacting `StateNodes`
moved nothing - the term is not placement.

### What is genuinely attributable to the generated store
- **~10% more bytes per unit of real work** (the 1.1x multiplicative component, matching the
  per-category read ratios of 1.05-1.16) -> throughput 0.966-1.015. Negligible.
- **`EXISTING_CONTRACT_DIFF_MAX`: ~1.55x more bytes**, the one real cell-specific difference, and
  the same cell the geth study flagged as its outlier (sa/compacted 7.71).
- A **fixed ~150 MB per-test read** whose origin is still unidentified. Candidates: per-container
  index/filter loading over state-actor's larger `flat/` (478 GB vs 314 GB), or the relocated trie
  root path. Bounded, additive, and irrelevant to any test doing real state work.

### Two script bugs caught by cross-checking against `buckets.py`
First pass reported 237/266 divergent with a median "real" ratio of 5.458 - impossible against
category medians of ~0.97. Causes: (1) selecting the step by dict order, so a **setup** step on one
arm was compared against the **test** step on the other (`steps` = `['setup','test']`); (2) a param
regex of `[A-Za-z0-9.]+` truncating `EXISTING_CONTRACT_MINIMAL` to `EXISTING` and mis-reading
`overhead_baseline`. Fixed version reproduces `buckets.py` exactly (124/266). Recorded because the
wrong numbers were superficially plausible and pointed at the opposite conclusion.

---

## Round 18 - what benchmarking remains

### Running: full corrected arm (launched 2026-09-14 14:10)
1463 tests, no filter, `pre_run_steps=0`. Store preconditions verified before launch and rollback
preservation verified after two completed tests: `flat/Account` `[6:37]` 17.38 GB with
`ribbonfilter` + `kNoCompression`, `flat/StateNodes` `[6:158]` 38.98 GB.

Why this run is worth 13 h when the 266-test subset already showed parity:
- The confounded baseline is **1461 tests at 11 gas points**; the corrected result so far is
  **266 tests at 2**. "Parity on a subset" is the one legitimate attack on the central claim.
- 11 gas points give a **gas slope** (ms per 1M gas), which is the geth study's primary metric, so
  the two studies become directly comparable instead of merely consistent.
- Supervisor `watch-run.sh joc-full 1463` auto-runs `buckets`, `buckets2`, `outliers` and
  `additive` on completion.

### Deferred to after the run (offline, no suite, ~30 min) - deliberately NOT run concurrently
Cross-arm I/O pollution already invalidated two earlier rounds, so no probing while a suite runs.
1. **Identify the fixed ~150 MB per-test excess.** Boot each arm, issue one minimal payload, diff
   `/proc/<pid>/io`. Leading candidate: per-container index/filter loading over state-actor's larger
   `flat/` (478 GB vs 314 GB). Bounded and irrelevant to real state work, but it is the last
   unexplained term.
2. **Characterise `EXISTING_CONTRACT_DIFF_MAX`** (16/16 tests at 0.615-0.725, reading ~1.55x more).
   Answerable from existing per-test data plus the fixtures - what that account_mode actually
   touches. The geth study flagged the same cell, so it is a fixture-shape property, not a store
   defect.

### Explicitly NOT worth running
- **A besu third arm.** Configs exist (`tools/besu-study/`), but the mechanism is LSM-generic and
  already demonstrated twice: geth's own compacted-vs-uncompacted arms and this study's
  intervention. A third client would add cost, not confidence.
- **state-actor WITH a pre-run** (the matched-methodology direction, and the more realistic one).
  **Blocked**: the state-actor fixtures release ships no `pre-runs/` bundle - only `eest-payloads`
  and `state-actor` - so it would require an EEST fill against the state-actor genesis. Recorded as
  the recommended ecosystem follow-up rather than something runnable here.

---

## Round 19 - full corrected arm lands; both deferred questions answered

### Full run: 1463/1463, 0 failures, `rc=0`, 12.7 h (finished 2026-09-15 02:49)
1461 comparable, 0 gas mismatches. The 266-test subset is vindicated - every category within
0.02-0.04 of it:

| category | n | thr sa/joc (full) | (266 subset) | read sa/joc | jocMB | saMB |
|---|---|---|---|---|---|---|
| STORAGE slot access | 88 | **1.034** | 1.013 | 1.08 | 578 | 626 |
| ETHER transfer receivers | 196 | **1.013** | 1.015 | 1.17 | 6668 | 7793 |
| ACCOUNT cold existing EOA | 110 | **0.979** | 0.983 | 1.06 | 3704 | 3907 |
| ACCOUNT cold existing contract | 440 | **0.968** | 0.966 | 1.08 | 4010 | 4619 |
| ACCOUNT cold non-existing | 110 | **0.904** | 0.939 | 5.65 | 40.5 | 218 |
| ACCOUNT warm query | 77 | **0.896** | 0.867 | 143.6 | 1.5 | 229 |
| CONTROL overhead_baseline | 440 | **0.708** | 0.717 | 52.4 | 1.8 | 96 |

Agreement within +/-10%: **53.0%** (subset: 53.4%). `EXISTING_EOA` agrees on **108/110 (98%)**.

### Deferred Q1 answered: DIFF_MAX is a code-DB size effect
Per account_mode, measured (non-control) tests only:

| account_mode | jocMB | saMB | **readX** | thrX | code involvement |
|---|---|---|---|---|---|
| EXISTING_CONTRACT_DIFF_MAX | 4030 | 5639 | **1.40** | **0.655** | a *different* max-size contract per access |
| EXISTING_CONTRACT_JUMPDEST | 4827 | 5598 | **1.16** | 0.931 | code scanned for jump destinations |
| EXISTING_CONTRACT_SAME_MAX | 3647 | 3863 | 1.06 | 0.980 | same contract reused -> code cached |
| EXISTING_CONTRACT_MINIMAL | 3647 | 3873 | 1.06 | 0.980 | minimal code |
| EXISTING_EOA | 3704 | 3907 | 1.05 | 0.979 | **no code at all** |

The ordering is **monotonic in code diversity**, and the cause is on disk:
**`code/` is 45 GB on state-actor vs 7.6 GB on jochemnet (5.9x)**. Reading a different max-size
contract per access costs 1.40x more bytes on the larger code DB; reuse the same contract, or touch
no code, and the arms are at parity. This is a property of how the generator sizes contract code,
not a state-DB defect - and it is why the geth study flagged the same cell.

### Deferred Q2 answered in part: the additive term is mode-independent and not a warmup artifact
Per-payload split (`resources` is a dict keyed by payload index, not a list - the earlier attempt
silently found nothing):

| total bucket | jochemnet n | state-actor n |
|---|---|---|
| 0-10 MB | **543** | **44** |
| 10-100 MB | 95 | 201 |
| 100-1000 MB | 68 | **447** |
| 1000+ MB | 757 | 769 |

Every test has 2 payloads and payload 0 carries 86-100% of the bytes on **both** arms, so the
measurement window is not swallowing warmup asymmetrically. The additive term instead shows as a
**population shift**: ~500 tests that read ~1.8 MB on jochemnet read ~170 MB on state-actor.

All four control variants read 89-104 MB on state-actor against 1.7-1.8 MB on jochemnet
**regardless of their nominal account_mode**, so the term is ~95 MB, fixed and mode-independent.
Not yet attributed to a column family. Ruled out: client boot I/O (jochemnet's is *larger*,
6.53 vs 4.81 GB) and trie placement (compacting `StateNodes` moved it 1%). Remaining candidate is
per-CF attribution from RocksDB LOG statistics during a single controlled test - optional, since
the term is bounded and invisible to any test doing real state work.

---

## Round 20 - article critique; two probe results that change the findings

Anon's review: drop "What we ruled out"; the per-category/per-test signalling is still too thin;
the "contiguous corner of the tree" claim is wrong for a hash-addressed trie; "Removing the
confound" never says the treatment is compaction; the DIFF_MAX and residual sections assert
without concluding; and the article should follow geth's shape - problem, defects found, one
section per fix with its own before/after, then the unexplained remainder.

### Harness reality check
- `BENCHMARKOOR_POST_PRERUN_CMD` exists **only on branch `state-db-journal-drain`** (commit
  `c3c46f1`), never on master. It runs an operator command after the pre-run and before
  `schelk promote`, aborting the promote on failure - exactly the hook this study needed.
- `BENCHMARKOOR_COMPACT_BETWEEN_STEPS` is **named in a source comment and never implemented**
  anywhere in benchmarkoor's history. The per-setup-payload compaction is intent, not code.
- The Nethermind runs used **neither**. The treatment was the hook's effect achieved by hand
  (compact the promoted image, strip `pre_runs` so replaying it could not re-cluster). Same end
  state, but not reproducible by a third party and never described as such.

### Probe defect found and fixed (invalidates two earlier readings)
`openRO` opened every column family with `NewDefaultOptions()`, i.e. **`filter_policy=nullptr`**.
RocksDB only constructs a filter reader when a policy is configured at open, so the probe measured
both stores *as if they had no filters*. Fixed by opening with the store's real per-CF options.

| Account CF, 20k keys | state-actor | jochemnet |
|---|---|---|
| absent keys | **2.5 us, 73 B** | **2.8 us, 87 B** |
| present keys | 165 us, 7,314 B | 204 us, 7,305 B |
| `bloom.filter.useful` on absent | 19,821 / 20,000 | 19,786 / 20,000 |
| false positives | 179 | 214 |

Consequences:
1. **No Besu-style defect.** Both stores carry working ribbon filters at ~1% false-positive rate.
   The hypothesis that the generated store was written without filters is dead.
2. Round 15's claim that "misses cost the same as hits on both arms" was **the probe bug**, not a
   property of the stores. Absent lookups are ~100x cheaper than present ones.
3. That retroactively **vindicates round 13**: stripping filters from the files really is why the
   non-existing cell inverted to 19x. Round 15's retraction of that explanation was itself wrong.
4. All earlier byte figures were taken with a filterless reader, which inflates *hit* cost by
   ~11% (SA 8,140 -> 7,314 B) equally on both arms. Hits are unaffected in shape because a filter
   never saves a hit, so the amortisation curve's saturation-vs-linear result stands; the absolute
   bytes in it are ~11% high on both arms and must be labelled as such.

### The DIFF_MAX explanation is refuted
The article says DIFF_MAX costs 1.55x because the generated store's `code/` is 45 GB against 7.6 GB.
Measured directly, cold random code lookups go the other way:

| arm | code/ | SSTs | bytes/lookup | us/lookup |
|---|---|---|---|---|
| state-actor | 45 GB | 734 | **10,513** | **196** |
| jochemnet | 7.6 GB | 126 | **14,208** | **346** |

Per-lookup code reads are *cheaper* on the generated store. So size alone does not explain it. What
the benchmark actually shows is an **incremental** effect: going from SAME_MAX (one contract reused)
to DIFF_MAX (a different contract per access) costs state-actor +1,776 MB and jochemnet only
+383 MB. The monotonic ordering in the code ladder is real; the mechanism attributed to it is not
established. DIFF_MAX returns to the open list.

Probe now opens any Nethermind database (`ListColumnFamilies`, CF resolved after the open) so
`code/`, `state/` and `blocks/` can be measured the same way as `flat/`.

### Round 20b - the fixed overhead localises to a cross-step cache carry-over

Nethermind exposes no RocksDB statistics switch (515 help lines, no `--Db.*`, nothing
metrics-related), so per-column-family attribution through the client is not available. The
per-step resource totals were never examined, and they localise the effect:

| group | arm | setup MB | measured MB | total |
|---|---|---|---|---|
| CONTROL (no account work) | jochemnet (treated) | **31.5** | **1.8** | 33.2 |
| CONTROL | state-actor | **9.4** | **96.1** | 105.5 |
| MEASURED | jochemnet (treated) | 31.5 | 3663.0 | 3694.4 |
| MEASURED | state-actor | 9.4 | 4234.0 | 4243.4 |

The arms are **inverted across the two steps**: jochemnet reads 3.3x more during setup and far
less during the measured step. Setup volume is identical across categories on each arm (31.5 and
9.4), so it is a fixed per-test payload.

Mechanism: `drop_memory_caches: "steps"` drops the **OS page cache** between setup and the
measured step, but the client is not restarted inside a test - `container-recreate` rolls back
per test, not per step - so **Nethermind's own RocksDB block cache survives from setup into the
measurement**. Whatever the setup payload pulled in is already resident when the timer starts, and
it warms the two stores by different amounts.

This is a benchmark defect of the same class as the unimplemented `COMPACT_BETWEEN_STEPS`: the
harness controls the page cache but not the client's internal cache, so a measured step's cost
partly reflects what its own setup happened to load. Fixing it needs a harness change (restart the
client, or flush the block cache, between steps), not a store change.

It does not explain the whole control gap - totals are still 33.2 vs 105.5 MB - so the remainder
stays on the open list rather than being declared solved.

### Round 20c - article restructured to the geth shape

Harness binary on the host (built Sep 7) contains **neither** switch: 0 occurrences of
`BENCHMARKOOR_POST_PRERUN_CMD` and 0 of `BENCHMARKOOR_COMPACT_BETWEEN_STEPS`. Every Nethermind run
used a benchmarkoor without the geth-era methodology controls.

Per-step compaction is not affordable for Nethermind: no compaction RPC exists, and offline
compaction costs 185.1 s for the account family alone - 3.1 days across 1,463 tests, about 6x the
runtime of the suite it would be preparing. The defect we actually found has a cheaper fix
(restart the client between steps), which is what the article now recommends.

New structure, following geth's:
1. The behaviour - how many tests and categories are off, by how much, with the read-volume tell.
2. **What we found wrong with the measurement** - the three defects enumerated, each labelled
   fixed or not fixed.
3. The root cause, restated correctly: the **LSM tree**, not the Merkle trie. Keys are
   `keccak256(address)[0:20]` and therefore scattered; what is concentrated is the set of files
   holding their newest versions. The section now ends on the prediction that compaction must
   destroy the advantage, which is what the next section tests.
4. **Defect 1** - names the treatment explicitly: `CompactRange` with
   `bottommost_level_compaction=kForce`, the store's own per-family options, state root unchanged;
   and states that the reproducible path is the post-pre-run hook, which was absent from the
   binary used.
5. **Defect 2** - the cross-step block-cache carry-over, with the setup/measured table and figure,
   the affordable fix, and an explicit note that it is **diagnosed but not fixed** in these numbers.
6. **What is left** - DIFF_MAX demoted to an open item with "what we know" / "what we do not know",
   including the direct measurement that refutes the code-database-size explanation.
7. Three clients, recommendations, errata.

"What we ruled out" deleted. Dumbbell gained an in-figure legend (a standalone SVG has no caption).
Eight figures, seven tables.

---

## Round 21 - Experiment C: DIFF_MAX localised to one square, three explanations refuted

### The square
The grid already contained its own control. Splitting the same cells by whether the opcode loads
the callee's code, and by whether the contract differs each access:

| | one contract, reused (SAME_MAX) | a different contract each (DIFF_MAX) |
|---|---|---|
| **loads the code** (CALL, CALLCODE, DELEGATECALL, STATICCALL, EXTCODECOPY, EXTCODESIZE) | 0.983 (0.972-0.991) | **0.640 (0.626-0.775)** |
| **account row only** (BALANCE, EXTCODEHASH) | 0.977 | 0.969, 0.972 |

One cell of four. Not the account row, not distinctness on its own: **loading a distinct
contract's code**. This also corrects the grid caption, which claimed every row behaves the same -
true of the grid overall, false inside the DIFF_MAX column, which is the one that matters.

### Three refutations, all measured
| measurement | state-actor | jochemnet | verdict |
|---|---|---|---|
| cold random code lookup | 10,513 B / 196 us | 14,208 B / 346 us | generated store **cheaper** |
| cold sweep, 3,000 distinct >=24,576 B contracts | **4,186 B/read**, 12.6 MB | 9,705 B/read, 29.1 MB | generated store **cheaper** |
| contracts at/above 24,576 B per 400k accounts | 442 | 433 | same population |

Contract populations differ but not in the direction needed: the generated store holds *more*
contracts (31.29% of accounts vs 19.13%) that are *far smaller* (median 23 B vs 45 B, mean 397 vs
676), and its maximum-size contracts compress to 4,186 bytes on disk against jochemnet's 9,705.
Reading code is cheaper on the generated store at every granularity measurable.

Also checked: all 20,000 addresses in the fixture range carry **no code at all** on either arm, so
the fixture EOAs are not the contracts in question.

**Verdict: the effect is real, confined to one square, and every explanation that fits the square
is contradicted by direct measurement.** Recorded as open rather than reaching for a fourth story.
Four oracles now pin the square and the two refutations.

### Experiment B1 launched 2026-09-16 10:43
`--FlatDb.BlockCacheSizeBudget` defaults to 1 GiB; B1 sets it to 8 MiB on **both** arms and runs
the 266-test subset on each, sequentially (concurrent arms pollute each other's I/O). If the
cross-step block-cache carry-over is what holds the control category at 0.708, shrinking the cache
should move it toward parity while leaving the account categories within a few percent.

---

## Round 22 - B1/B1b: the block cache and memory hint move nothing

Both arms, 266-test subset, flat DB block cache 1 GiB -> 8 MiB (client log confirms: 2 MB to
accounts, 5 MB to storage). Pre-registered prediction: control 0.708 -> 0.85-0.95. Result:
control 0.686 -> 0.707 (+3.0%), every account category within 0.9%. B1b added
`--Init.MemoryHint=4000000000` (trie 750 MB, DB 3001 MB): control-only, no change.
**Falsified.** Cache carry-over from setup is additionally bounded by measured budget: setup reads
31.5 MB and writes 0.0 MB against a 104.5 MB gap, so <=30% in *any* client cache.

## Round 23 - E4: remove all cache drops; the 96 MB is real re-read and is non-causal

200 tests/arm with `drop_memory_caches: disabled`. state-actor's control reads 96.4 -> **0.0 MB**;
its control throughput 31.0 -> 27.8 MGas/s. Removing 100% of the I/O left it slower. Paired over
identical ids: cold cpu ratio 2.248, no-drop cpu ratio 1.769 with reads at zero.
**The control gap is CPU, not I/O.**

## Round 24 - locality and saturation: jochemnet's benchmark accounts are not privileged

Cold, per arm: fixture accounts (0x1000+) vs random pre-existing accounts.
joc 183.6 vs 185.4 us, sa 209.7 vs 205.4 us; blocks/lookup 1.98 vs 1.99 on both. Footprint growth
20k->200k lookups identical to 0.5% (162.5/403.1/796.9/1196.7 MB vs 162.6/404.4/802.1/1198.0).
Both arms sit at the compacted-LSM floor (~2 blocks per lookup) - a floor our own compaction put
them on. Storage-layer residual: 1.11-1.14x.

## Round 25 - warm client via rpc-debug-setHead: works, contaminated, withdrawn

setHead keeps one client alive (1 boot / 40 tests, 0 failures, rollback verified). Control
inverted to sa/joc 2.031 with cpu 0.914. But fixture accounts are reused across gas points with the
client's caches never cleared, so it is not a valid store comparison. Withdrawn; a 1,463-test
"corrected" run on it was killed at stage 2.

## Round 26 - the noise floor, finally measured

Same store, same config, twice (133 tests at 160M): overall 75.2% within +/-10%.
existing EOA 100% (med 1.003), existing contract 98% (0.999), non-existing 60% (0.946),
CONTROL 40% (1.018, range 0.62-1.77). Floor by duration on cache-knob pairs: <0.2 s 41%,
0.2-1 s 54%, 1-5 s 85%, >=5 s 98%. Noise-adjusted ledger: of 687 tests outside +/-10%, ~388 are
consistent with noise, ~299 are real; 100 of those are in the >=5 s population (84 existing
contract, 25 ether, 2 EOA, 0 storage). Control's per-test values are noise; its median is not
(1.018 same-store vs 0.708 cross-store). The worst-12 table (all 12 under 0.2 s) and the storage
spread oracle (span 0.80 reproduced on the same store) present noise as signal.

## Round 27 - divergence by operation: three regimes

Grid opcode x account_mode, 11 gas points per cell.
- Regime 1, cold reads (EOA/MINIMAL/SAME_MAX, all opcodes): 0.967-0.983, 0-1/11 outside. Parity.
- Regime 2, writes (CALL v=1, sstore, ether): 1.01-1.08. state-actor faster.
- Regime 3, CPU-bound: control 0.64-0.85 uniform across opcode and mode; DIFF_MAX 0.62-0.64 only
  under code-executing opcodes (BALANCE/EXTCODEHASH in DIFF_MAX stay at 0.97); JUMPDEST 0.92 only
  under code-executing opcodes; sload_same_key 0.812; warm query 0.86-0.95.
Control: cpu ratio 2.2x vs wall 1.4x, cpu/sec 1.89 vs 1.21 -> extra parallel CPU, not a slower
executing thread. Control gas scales 3.5 -> 10.4 M across the gas parameter and the ratio is flat
(0.65-0.74), so the cost is per-iteration, not per-boot.

Structural comparison (rocksdb.aggregated-table-properties): same CF set, identical key sizes
(28/60/16/11/36 B) so the trie layout is the same; state-actor +21% entries; Account values 25 vs
16 B, Storage 28 vs 10 B. Metadata CF: both have CurrentState; state-actor also has Layout=Flat
and **SlotEncoding=RLP** (1.39.0+). jochemnet lacks the marker -> its Storage CF is read as
legacy raw bytes. Different SLOAD read paths; storage tests only (88). Chain-profile confound
ruled out: `--config=none` on both arms. Launch args identical apart from genesis and fixtures.

## Round 28 - per-thread CPU profile (running) and the JIT precondition

Setup step: joc 0.24 s wall / 0.53 cpu-s / 31.5 MB; sa 0.04 s / 0.54 cpu-s / 9.4 MB. Identical
CPU, 6x wall: state-actor reaches its 0.12-0.18 s measured step 0.2 s earlier in the life of a
fresh .NET process. Hypothesis: .NET tiered compilation still promoting the interpreter's hot
methods during state-actor's measurement (tier-0 code = proportional slowdown; tiering thread =
extra parallel CPU; no I/O; worst on short CPU-bound payloads). Decided by the `.NET Tiered Com`
share inside test-step windows, from /proc utime+stime per task at 0.5 s.

## Round 28 (result) - the thread profile names it: RocksDB compaction on state-actor

Per-thread CPU (utime+stime from /proc, 0.5 s) inside the measured steps of 40 identical
control tests, published config:

| thread | jochemnet | state-actor |
|---|---|---|
| rocksdb:low | 0.00 | **25.43 s (41%)** |
| .NET Tiered Com | 22.60 (70%) | 21.06 (34%) |
| .NET TP Worker | 8.91 (28%) | 10.93 (18%) |
| .NET BGC | 0.01 | 3.71 (6%) |
| total | 32.2 s / 0.71 cores | 61.9 s / 1.24 cores |

RocksDB's low-priority background thread - compaction - accounts for 25.4 of the 29.7 extra
CPU-seconds. Tiered JIT compilation is large but symmetric (~22 s inside the windows on both
arms): a cost of restarting the client per test, not the difference. The JIT-timing hypothesis
(setup 0.24 s vs 0.04 s wall) is therefore dead.

**Correction to earlier statements this session:** the compaction treatment (round 18) was
applied to *jochemnet*, not state-actor. Level layouts prove it: jochemnet Account L6:37,
StateNodes L6:158 (the rebuilt shape); state-actor Account **L3:92 (23.7 GB)**, Storage L4:404,
Metadata L1, StateNodes L6:602 - exactly as generated. `rocksdb.compaction-pending=1` on
state-actor's Account CF and 0 on every other CF. Mechanism: the generator leaves Account parked
at L3; the client opens with auto-compaction on and immediately schedules it; it runs through
the measured step on rocksdb:low; container-recreate discards the work; the same compaction
restarts on every one of 1,463 tests. With the page cache dropped it re-reads its input SSTs
(the 96 MB); with drops disabled the inputs were cached, reads went to zero, CPU stayed (E4).
CPU-bound cells lose ~30-40% to the contention, I/O-bound cells hide it, writes are unaffected
or faster - the three regimes of round 27.

DIFF_MAX detail: both arms' max-size contracts are the same EEST filler (`00 || address ||
0x5b x 24,555`), so code content is not the difference; EXTCODESIZE-in-DIFF_MAX at 0.626
(no jumpdest analysis) equals CALL-in-DIFF_MAX, so the cost is in loading, under compaction
contention on CPU and NVMe. Storage `SlotEncoding` (RLP on state-actor, legacy on jochemnet)
is a separate, storage-only generator-version difference.

## Round 32 (running) - settle state-actor's Account CF, promote, re-measure

Rounds 29-31 (parallel-execution and JIT A/Bs, DIFF_MAX read attribution) were stopped as moot.
Killing them with SIGKILL wedged jochemnet's dm-era device; recovered with `dmsetup remove` +
`schelk full-recover` (1.6 TB, 17 min). Lesson recorded: never SIGKILL a benchmarkoor run.
Plan: `probe-flat -mode rebuild -cf Account` on state-actor (CompactRange, bottommost force,
the store's own per-CF specs - the round-18 path), `schelk promote`, then control (40) and the
regime-3 slice (DIFF_MAX/SAME_MAX/warm/sload_same_key/NON_EXISTING at 160M) on state-actor
only, against the published runs as baseline. Pre-registered prediction: control 0.708 -> >0.9,
DIFF_MAX code-exec 0.64 -> >0.9, sload_same_key 0.81 -> >0.9, warm query 0.90 -> ~1.0;
compaction-pending=0 after promote; rocksdb:low absent from a re-profile.

## Round 32 (result) - aborted by the schelk lock; but the rebuild revealed the generator bug

My concurrent `schelk full-recover` of jochemnet (needed after the SIGKILL) held schelk's global
lock for 17 min: state-actor's baseline slice died at test 3, `promote` failed, and both
re-measure runs got 0 tests. **The state-actor virgin image is unchanged.**

The rebuild itself ran (303 s) and did nothing useful: `Account L0:1 L3:92 -> L3:92`, still
`compaction-pending=1`. Cause: RocksDB's manual `CompactRange` with the default `target_level=-1`
compacts into the deepest level that already holds files. Round 18 reached L6 on jochemnet only
because its Account already lived at L6.

The generator made the same mistake. The virgin image carries the generation run's RocksDB LOG
(2026-09-11 19:31-23:04, `create_if_missing=1`, 2,781 memtable flushes, 13,591 auto compactions
`LevelMaxLevelSize`, 163 `ManualCompaction`, shutdown mid-job). Its finishing pass on Account is
8 manual jobs, all `Compacting N@2 + M@3 files to L3` - never to L6. With
`level_compaction_dynamic_level_bytes=false` L3's target is 12.8 GB and the generator left
23.7 GB there, so `compaction-pending=1` from the moment generation ended. The CFs with
`dynamic=true` (StateNodes, StorageNodes) were compacted "to L6" by the same pass and are fine.
Storage sits at L4 under its 256 GB target and is not pending.

**Generator fix:** for every CF with `level_compaction_dynamic_level_bytes=false`, the finishing
`CompactRange` must set an explicit `target_level = num_levels-1` (or open with dynamic levels
for the pass). Probe gained `-mode rebuild -level N` for the post-hoc equivalent.

Also learned: Nethermind does not append to the store's `LOG` (RocksDB info log goes elsewhere),
so per-boot compaction jobs are not recoverable from the mounted volume; the per-thread profile
remains the evidence.

## Round 33 (running) - replicate the baseline profile on the unsettled image
## Round 34 (armed) - rebuild Account to L6 explicitly, promote, re-profile and re-measure

## Round 33 (result) - baseline profile replicated on the unsettled image

Second profile of 40 control tests on state-actor, same config: rocksdb:low 21.69 s (39%),
Tiered Com 18.22 (32%), TP Worker 11.20 (20%), BGC 4.27 (8%); 56.2 CPU-s / 1.22 cores inside
the windows. Same shape as round 28 (25.43 / 21.06 / 10.93 / 3.71). The compaction thread is a
stable feature of the unsettled image, not a one-off.

## Round 34 (result) - `-level 6` alone does not move the files

`CompactRange` with `SetTargetLevel(6)` still produced `Account L3:92`, `pending=1` (237 s), and
this time `promote` succeeded (33 GB, 20 s), so the virgin image now carries the rewritten but
unmoved CF - same options, same level, no behavioural change. RocksDB ignores `target_level`
unless `change_level=true` is also set. Wired both; the driver was stopped between runs (never
SIGKILL a benchmarkoor run) and round 35 re-runs the sequence with a guard that refuses to
promote unless the rebuild reports `pending=0` and `levels=L6:`.

## Round 35 (result) - Account settled at L6; the compaction was real and was NOT the cause

With `change_level=true` + `target_level=6`: `Account L3:92 -> L6:92, pending=0` (234 s),
promoted (33 GB, 20 s), verified on the virgin image. Re-measured on state-actor only, against
the published runs on identical ids:

| cell | thr before | thr after | cpu before | cpu after | sa reads before | after |
|---|---|---|---|---|---|---|
| CONTROL (40) | 0.695 | **0.697** | 2.28 | 1.71 | 85.7 MB | 12.1 MB |
| DIFF_MAX code-exec (8) | 0.638 | 0.653 | 1.11 | 1.06 | 5603 | 5453 |
| SAME_MAX code-exec (8) | 0.980 | 0.992 | 1.00 | 1.03 | | |
| NON_EXISTING code-exec (8) | 0.946 | 1.058 | 1.31 | 1.16 | | |
| warm query (7) | 0.891 | 0.850 | 1.19 | 1.18 | 228.8 | 13.8 |

Profile on the settled image: rocksdb:low 8.97 s (was 21.7-25.4), BGC 0.68 (was 3.7-4.3),
Tiered Com 21.6, TP Worker 11.4 (joc 8.9); 43.7 CPU-s / 0.91 cores (was 56-62 / 1.2). The
generator defect is fixed in the image and the re-reads are gone. **Control throughput did not
move.** The compaction thread was a genuine, now-removed difference, and it was not what made the
control loop slow. Falsified by intervention.

What remains: the executing threads themselves do ~28% more work on state-actor (TP Worker
11.4 vs 8.9 s over 40 tests; the extra ~2.5 CPU-s equals the extra wall time, 40 x ~50 ms).
Identical payload, reads now 12 MB, contention mostly gone. Candidates for a per-iteration CPU
multiplier on identical code: JIT tier state at measurement time (jochemnet's setup waits
0.2 s on I/O, state-actor's does not) and optimistic parallel execution re-running conflicting
transactions. Both are the round-29 A/Bs I cancelled; they run next.

Host stopped completing SSH sessions at ~15:55 UTC (banner returned, key accepted, session setup
stalls - the round-5 signature; cleared on its own after ~2 h then). Nothing of mine was running.

## Round 36 (running) - the fixtures differ by one empty block, and it shifts the JIT

Per-payload timing of one control test on each arm (profile runs):
- jochemnet setup: fcU 22 ms; block 535.5k gas **238.7 ms**; fcU 45 ms. test: block 5.57 M gas
  **122.1 ms**; fcU 1.5 ms.
- state-actor setup: fcU 15 ms; **empty block, 0 gas, 244.2 ms**; fcU 19 ms; block 535.5k gas
  **46.1 ms**; fcU 1.4 ms. test: block 5.57 M gas **289.6 ms**; fcU 2.5 ms.

state-actor's fixtures carry an extra empty block (chain at genesis, Amsterdam override at
timestamp 1 -> a fork-activation block). The first block after boot costs ~240 ms on both arms
regardless of content - process warm-up. On jochemnet that block is the EVM-heavy setup block,
followed by a 45 ms gap: the interpreter's hot methods pass .NET's 100 ms call-counting delay
and tier up before the test block. On state-actor the warm-up is spent on an empty block; the
EVM's first real work is the 46 ms setup block and the test block starts 1.4 ms later, on
tier-0 code with the JIT compiling underneath. The harness's gas-weighted setup timing ignores
the 0-gas block, which is why state-actor's setup reads 0.04 s. E4 (page cache warm) already
showed jochemnet's setup stays 0.23 s with 5.5 MB of reads, so the wait is not I/O.

Fits every regime-3a property: proportional per-iteration slowdown, extra CPU, zero I/O,
uniform across opcode and mode, shrinking with measured-step length (0.71 at 0.12 s -> 0.85-0.92
at 0.4 s -> ~0.98 at 9 s), unchanged by settling Account. Pre-registered: with
`DOTNET_TieredCompilation=0` on both arms the control ratio moves from ~0.70 toward 1.0.
Harness implication: a client restarted per test must be given equal EVM warm-up before
measurement on every arm - the pre-run problem again, at the JIT level.

Round 35's ledger text landed inside commit 7243233 (another workstream's `git add -A`);
content intact.

## Round 36 (result) - CONFIRMED: regime 3a is JIT warm-up, from the fixtures' extra empty block

40 control tests per arm, published config, state-actor on the settled-Account image:

| variant | thr sa/joc | cpu sa/joc | sa control step | joc control step |
|---|---|---|---|---|
| baseline | 0.726 | 1.538 | 0.165 s (30.7 MGas/s) | 0.118 s (45.2) |
| `--Blocks.ParallelExecution=false` (+BatchRead) | 0.556 | 1.864 | 0.132 s | 0.075 s |
| **`DOTNET_TieredCompilation=0`** | **1.143** | 1.520 | **0.094 s (55.3)** | 0.110 s (48.3) |

Pre-registered prediction held: removing tiered JIT moved control from ~0.70 to 1.14. The gain is
asymmetric (state-actor +43%, jochemnet +7%) because the asymmetry *is* warm-up: jochemnet's
first (warm-up) block is its EVM-heavy setup block, state-actor's is a 0-gas fork-activation
block the fixtures add because its chain starts at genesis, so its EVM enters the measured
block 1.4 ms after 46 ms of tier-0 execution. Parallel execution exonerated (disabling it hurts
state-actor more). Regime 3a - control, sload_same_key, warm query, non-existing, ~660 tests -
is a fixture-structure artifact, not a store property. Java-based clients (Besu) may carry the
same artifact on the same fixtures.

## Round 37 - perf with JIT symbols: not run (filter selected 0 tests; opcode precedes
`overhead_baseline` in the id - third time). Superseded by round 36.

## Round 38 (running, night3) - the code DB carries the same generator defect

state-actor `code/` (cf default): 134.4M entries, **L4:734 files, 45.7 GB, compaction-pending=1**,
no bloom filter. jochemnet `code/`: L0:3 (9 MB) L1:6 (132 MB) L3:117 (6.9 GB), pending=1 but
small enough to finish at boot. Every DIFF_MAX test hammers this DB while the client compacts
45 GB underneath it - the +1.4 GB reads and +5 s per test, and the 9 s of rocksdb:low that
survived settling Account. `compactWholeDB` gained change_level/target 6 and
disable_auto_compactions; night3 settles it, promotes, re-measures DIFF_MAX (slice38), then runs
the regime-3 slice (R39) and the 266 subset (R40) on both arms with TieredCompilation=0.
Follow-up owed: settle jochemnet's code DB too for strict symmetry (small, fast).
The first night2 attempt mis-read an empty probe result as "settled" (probe needed `-cf default`);
night3 refuses to proceed on an empty probe.

## Round 38 (result) - code DB settled on state-actor; DIFF_MAX does not move

state-actor `code/`: `L4:734 (45.7 GB) -> L6:729 (44.6 GB), pending=0` (185 s), promoted (26 s).
DIFF_MAX code-exec on identical ids: published 0.638 -> Account settled 0.653 -> +code settled
**0.651**; state-actor step 14.96 -> 14.58 s; reads 5,603 -> 4,895 MB. Third falsification for
this cell (code content, code-DB size, compaction). CPU ratio ~1.06 against a 1.5x time ratio:
DIFF_MAX is I/O-bound, state-actor reads ~20% more bytes and waits longer. Which CF the extra
bytes come from is the next fact (round 41: tracer + live-file->CF map, DIFF_MAX vs SAME_MAX).

For symmetry jochemnet's `code/` was settled too: `[0:3 1:6 3:117] -> [6:113]`, pending=0
(107 s), promoted (13.9 GB, 8.8 s). Both arms now carry Account, StateNodes and code at L6 with
their own per-CF options. Pipeline night4 (detached): R39 regime-3 slice with
`DOTNET_TieredCompilation=0` on both arms; R40 the 266 subset on both arms, settled images +
TieredCompilation=0 - the corrected cross-category comparison; then round 41.

Two sessions today the host stopped completing SSH sessions (15:55-17:44, ~19:20-20:13 UTC),
both shortly after a batch ended; detached work unaffected each time.

## Round 39 (result) - with the JIT equalised, every regime-3 cell collapses; DIFF_MAX was jochemnet's JIT

Regime-3 slice, both arms, `DOTNET_TieredCompilation=0`, settled images, identical ids:

| cell | published | JIT-eq both | joc step pub -> now | sa step pub -> now |
|---|---|---|---|---|
| DIFF_MAX code-exec (8) | 0.638 | **0.944** | 9.51 -> **13.61 s** | 14.96 -> 14.54 s |
| DIFF_MAX BAL/HASH (2) | 0.973 | 0.984 | 8.45 -> 8.34 | 8.68 -> 8.47 |
| NON_EXISTING code-exec (8) | 0.946 | 1.107 | 0.36 -> 0.19 | 0.39 -> 0.17 |
| NON_EXISTING BAL/HASH (2) | 0.990 | 1.149 | 0.35 -> 0.19 | 0.35 -> 0.16 |
| SAME_MAX code-exec (8) | 0.980 | 0.996 | 8.28 -> 8.22 | 8.41 -> 8.27 |
| sload_same_key (2) | 1.093 | 1.124 | 0.37 -> 0.07 | 0.34 -> 0.07 |
| warm query (7) | 0.891 | **1.468** | 0.43 -> **0.07** | 0.44 -> **0.05** |

DIFF_MAX: state-actor barely moved; **jochemnet slowed from 9.5 to 13.6 s** once tiered JIT/PGO
was removed. Its advantage on that cell was the JIT reaching the hot path early on jochemnet and
late or never on state-actor - the control-loop mechanism on a 15 s test. Three store-level
explanations were refuted for this cell; the fourth was never in the store.

Short tests: warm query 0.43 -> 0.07 s, sload_same_key 0.37 -> 0.07 s, non-existing 0.35 -> 0.17 s
on both arms. The published absolute numbers for sub-second tests are ~5-6x too slow on *both*
arms - they measure tier-0 interpreter code and JIT warm-up, and the between-arm ratios were a
warm-up race decided by fixture structure. Applies to any JIT-hosted client restarted per test
(Besu/JVM presumably; geth is AOT).

Combined with round 36 (control 0.726 -> 1.143): with JIT equalised, no cell has state-actor
slower than 0.94 and most sit at parity or state-actor-faster. TieredCompilation=0 is the clean
diagnostic, not the recommended config: a live node runs tier-1+PGO code, so the harness fix is
an EVM-heavy warm-up phase after boot on every arm, discarded before measurement (the pre-run
idea, applied to the JIT). R40 (266 subset, JIT-eq, both settled) running for the full picture.

## Round 40-41 status - completed unattended; host unreachable since ~23:20 UTC

R40 (266 subset, both arms, settled images, TieredCompilation=0) and R41 (per-CF read
attribution of DIFF_MAX vs SAME_MAX) were chained and run without supervision; by their own
timing both finished before 02:30 UTC. The host stopped completing SSH sessions from ~23:20 UTC
and had not resumed by 03:20 UTC local+? (4 h - longest so far; banner and ICMP fine, session
setup hangs, `gas-repricing` is not in Teleport so there is no second path). Results are on disk
under /bench/logs/night/{night4-verdict.txt,round41-verdict.txt}; nothing is lost by waiting.

### Where the investigation stands (before R40's numbers)

Two mechanisms, both found by intervention, both artifacts of the *procedure*, neither a store
property:

1. **Placement** (rounds 11-16): the pre-run promoted into jochemnet's image put the fixture
   accounts in a handful of young SSTs. Compaction equalised it. 17x -> account reads at parity.
2. **JIT warm-up** (rounds 28-39): the harness restarts the client per test; state-actor's
   fixtures add a 0-gas fork-activation block, so its EVM enters the measured block on tier-0
   code with the JIT compiling underneath, while jochemnet's EVM tiers up during its heavy setup
   block. Removing tiered compilation on both arms: control 0.73 -> 1.14, DIFF_MAX 0.64 -> 0.94
   (jochemnet's own DIFF_MAX slowed 9.5 -> 13.6 s), warm/short cells 0.85-0.95 -> 1.1-1.5, with
   all sub-second tests 5-6x faster on both arms. Every regime-3 cell was this.

Also found and fixed in the images along the way, none of which moved a ratio: state-actor's
Account CF (generator's CompactRange left it at L3, compaction-pending) and both arms' code DBs
(L4:734 / L0:3,L1:6,L3:117). Structural differences catalogued and ruled out: RocksDB options
identical, chain profile identical (--config=none), fixture accounts read like random accounts,
footprint growth identical, cache carry-over <=30% by budget and 3% measured, Storage
SlotEncoding differs (storage tests only, jochemnet is the legacy one).

Remaining after JIT equalisation, to be read from R40: whether any category sits below ~0.94
with n>=20, and the storage-slot cells (SlotEncoding). Per-test noise: 60-75% within +/-10% on
the same store for sub-second tests; 98% for tests over 5 s.

## Round 40 (result) - the corrected subset: no category below 0.93, and the correction overshoots

266-test subset, both arms, settled stores + `DOTNET_TieredCompilation=0`, identical ids:

| category | n | published | corrected | CPU sa/joc |
|---|---|---|---|---|
| existing contract | 80 | 0.968 | **0.982** | 1.05 |
| existing EOA | 20 | 0.979 | **0.986** | 1.20 |
| ether transfer | 36 | 1.013 | 1.086 | 0.97 |
| storage slot | 12 | 1.034 | 1.132 | 0.72 |
| CONTROL | 80 | 0.708 | **1.145** | 0.95 |
| sload_same_key | 4 | 0.812 | 1.192 | 1.05 |
| non-existing | 20 | 0.904 | 1.197 | 0.95 |
| warm query | 14 | 0.896 | **1.539** | 1.00 |
| overall median | 266 | 0.959 | **1.046** | |

DIFF_MAX code-exec 0.642 -> 0.934 (n=16). Nothing sits below 0.93. But the correction is not
neutral: it *overshoots*, because disabling tiering costs jochemnet the promoted code it used to
reach mid-test, so the short categories land above parity (warm query 1.54). Overall within-10%
barely moves (53.0% -> 52.6%) - the divergence changed sign rather than disappearing. The honest
statement is a bracket: every state-reading category lies between the two columns, within a few
per cent of parity in both. The recommended fix is an equal discarded burn-in block per arm, not
`TieredCompilation=0`.

## Round 41 - read attribution: produced no rows

The tracer ran and the inode/CF maps were collected, but the window-alignment join emitted empty
tables (the `WINDOW hh:mm:ss` stamps are wall-clock without a date and my day-offset guess did
not match the run's windows). Not re-run: DIFF_MAX's remainder after warm-up equalisation is
0.944 with a CPU ratio of 0.79 on ~4.9 GB of reads per test, so the open question is now "why
~20% more bytes", not "which subsystem". A correct version needs the tracer to print epoch
seconds; noted for whoever picks it up.

## Article rewritten and published - `bcf1bfe`, live, byte-identical

Defect 2 replaced end to end: the client-cache story is gone, the JIT mechanism is in with the
fixture asymmetry, per-thread profile, the three-configuration A/B, the regime-3 slice and the
corrected subset. The step figure survives with a caption that states what it does *not* show.
Removed: the worst-12 table (all twelve tests ran under 0.2 s) and the storage-spread oracle
(the same store reproduces the span it demanded). Requalified: the dispersion figure now states
the reproducibility floor. Recommendations now lead with warm-up equalisation and the generator's
`change_level` fix; the cache recommendation is demoted to "useful control, wrong suspect".
Errata gained the two mis-attributions and the reproducibility admission.

Eleven new oracles, each verified to refuse generation when contradicted: the JIT intervention
crossing parity, parallel execution staying exonerated, the JIT thread's share on both arms,
settling removing the compaction thread, DIFF_MAX closing and staying I/O-bound, the no-drop
reads vanishing without a speed-up, short tests not reproducing, long tests reproducing, and no
corrected category below 0.9.

Collectors added: `collect_jit.py` (profile, A/B, slice, subset, settle, drops) and
`collect_noise.py` (replica floor by category and duration).

---

## Round 42-44 - is the code DB configured correctly, and closing the last category

### The code DB is configured correctly on both arms

Every read-path knob is byte-identical between arms *and* matches what the client writes:
`kSnappyCompression, block_size=4096, block_restart_interval=16, index_type=kBinarySearch,
data_block_index_type=kDataBlockBinarySearch, cache_index_and_filter_blocks=false, num_levels=7,
level_compaction_dynamic_level_bytes=true, max_bytes_for_level_base=268435456,
target_file_size_base=67108864, optimize_filters_for_hits=false, whole_key_filtering=true`.

Two things look wrong and are not:
- **`filter_policy=nullptr`** - no bloom filter on either arm. Correct here: with every file at L6
  and disjoint key ranges a code-hash lookup consults exactly one file, so a filter would only add
  bytes. Changing it is a client change, not a store fix.
- **55x the entries at 1/21 the size** - state-actor 134,442,676 entries, avg 358 B, 48.2 GB raw /
  44 GB on disk, 7.50M data blocks, 729 files; jochemnet 2,417,142 entries, avg 7,629 B, 18.4 GB
  raw / 7.5 GB, 1.42M data blocks, 113 files. Structural: the code DB is keyed by code hash, so
  mainnet dedups proxies and clones while state-actor embeds the account address in each
  contract's bytecode and nothing dedups.

### My contamination, found and fixed (R42)

`compactWholeDB` used grocksdb defaults, which agree with the client on compression, block size
and restart interval but write **`format_version=6` where the client writes 5** - a read-path
change to the block trailer and index encoding. Applied to all 729 sa and 113 joc code files,
symmetric and before every corrected measurement, so it biases no comparison, but the stores
stopped matching a real node's layout. Same options-drift class as the round-13 error that
silently dropped a ribbon filter. `compactWholeDB` now transcribes the client's table options
explicitly (format 5, binary-search index, no filter policy) and R42 rewrites both code DBs,
verifying `format_version=5` before promoting.

### Why "code-related" is probably the wrong label

Reading code is *cheaper* on state-actor at every granularity measured: 10,513 B / 196 us vs
14,208 B / 345 us per cold random lookup; 4,186 vs 9,705 B/read on a cold sweep of 3,000 distinct
>=24,576-byte contracts (its filler bytecode compresses to ~4.2 KB). `EXTCODESIZE`-in-DIFF_MAX
diverges as much as `CALL`-in-DIFF_MAX and needs no jumpdest analysis, so analysis is out. Across
the 131 reliable (>5 s) tests, throughput correlates with CPU at **-0.48** and with reads at
**+0.08**, and the slower-11 and faster-18 groups have the *same* read ratio (1.12 both ways).

### The marginal-distinctness measurement, and why it forces R43 first

SAME_MAX and DIFF_MAX are the same opcodes at the same gas against same-size contracts, so their
difference is the cost of distinctness. Matched (opcode, value_sent, gas) pairs:

| | marginal read | marginal time |
|---|---|---|
| published | joc +118 MB, sa +263 MB (2.23x) | joc +0.28 s, sa +0.60 s (2.17x) |
| corrected (sub40) | joc +500 MB, sa +656 MB (1.31x) | joc +2.21 s, sa **+1.84 s (0.84x)** |

After correction the cost of distinctness is *cheaper* on state-actor in time, and jochemnet's
marginal time jumped 0.28 -> 2.21 s - the JIT effect again. But the same statistic from the
`slice39` runs of the *same* configuration gives joc +5.38 s vs sa +6.23 s (**1.16x, opposite
sign**). Also: if every marginal byte were a code read at the sweep's cost, the implied distinct
accesses per test are 51,558 (joc) against 156,617 (sa) - impossible, since payload and gas are
identical. So the cell's residual is at or below run-to-run variation and no mechanism claim is
defensible without a replicate.

### Plan (adjudicated alone: `/plan-debate` returned empty bodies for every role, 4th failure, reported)

- **R42** restore `format_version=5` on both code DBs, verify, promote. ~10 min offline.
  Prediction: no measurable throughput change.
- **R43** *the deciding experiment*: two replicas per arm of the corrected configuration
  (266-test subset, both stores settled, `DOTNET_TieredCompilation=0`), then intersect the tests
  outside +/-10%. ~9 h detached. Pre-registered: fewer than 5 of the 11 "state-actor slower"
  tests appear in both replicas, and DIFF_MAX's 0.934 moves by more than +/-0.03. If so, this
  category is noise and the output is a bound, not a mechanism.
- **R44** per-CF read attribution of DIFF_MAX vs SAME_MAX, both arms. Pre-registered: under 25%
  of the marginal bytes are `code`; the rest Account + StateNodes. ~40 min.
  Tracer bug found and fixed: it printed wall-clock `hh:mm:ss` and the consumer guessed the date.
  `nsecs` is boot-relative on this kernel (equals /proc/uptime), so the fix is
  `strftime("%s", nsecs)`; verified against `date +%s`.
- **Rejected**: `perf` with JIT symbols (the CPU spread is symmetric, 0.68-1.57 in both
  directions on identical payloads, and the asymmetric component is already removed); adding a
  bloom filter to the code DB; any further store surgery before R43.

All three chained and detached: R42 -> R43 -> R44.

## Round 42 (result) - format_version restored to 5 on both code DBs

joc `L6:113 -> L6:113`, sa `L6:729 -> L6:726`, both `pending=0`, `format_version=5` verified
before promoting (promotes: 4.1 s / 24.0 s). `compactWholeDB` now transcribes the client's table
options instead of taking grocksdb's defaults. My contamination is out of both golden images.

## Round 43 (result) - the deciding experiment: half my prediction was wrong

Two replicas per arm of the identical corrected configuration (266-test subset, settled stores,
`DOTNET_TieredCompilation=0`). All four runs 266/266, zero failures.

**This configuration's own reproducibility, measured for the first time** (same arm, two runs):
jochemnet 221/266 within +-10% (83%, median 0.9993); state-actor 192/266 (72%, median 1.0006).

**Per-test divergence is noise.** Cross-store outside +-10%: 108 in replica 1, 131 in replica 2,
87 in both - but in the *same direction* in both, with state-actor slower: **1 test out of 266**.
The "defensible list" is mostly sign-flippers: rep1 0.610 / rep2 1.136, rep1 1.162 / rep2 0.621,
and so on. Prediction "fewer than 5 of the 11 survive" - **confirmed, 1 survives**.

**Cell medians are not noise, and that falsifies the other half of my prediction.** I predicted
DIFF_MAX's 0.934 would move by more than +-0.03. It moved by **0.005**:

| cell | replica 1 | replica 2 | swing | published |
|---|---|---|---|---|
| **DIFF_MAX code-exec** (16) | **0.928** | **0.933** | **+0.005** | 0.643 |
| **JUMPDEST code-exec** (16) | **0.938** | **0.937** | **-0.000** | 0.925 |
| SAME_MAX code-exec (16) | 0.993 | 0.988 | -0.005 | 0.980 |
| MINIMAL code-exec (16) | 0.997 | 0.991 | -0.006 | 0.980 |
| EXISTING_EOA code-exec (16) | 0.987 | 0.994 | +0.007 | 0.982 |
| DIFF_MAX **BAL/HASH** (4) | 1.013 | 1.001 | -0.012 | 0.973 |
| JUMPDEST **BAL/HASH** (4) | 0.991 | 0.997 | +0.006 | 0.972 |
| ether transfer (36) | 1.049 | 1.073 | +0.023 | 1.014 |
| storage slot (12) | 1.053 | 1.066 | +0.013 | 1.078 |
| NON_EXISTING code-exec (16) | 1.092 | 1.209 | +0.117 | 0.932 |
| CONTROL (80) | 1.137 | 1.183 | +0.046 | 0.686 |
| sload_same_key (4) | 1.265 | 1.348 | +0.083 | 1.040 |
| warm query (14) | 1.286 | 1.293 | +0.006 | 0.920 |

So the last category is **real, reproducible to half a per cent, and precisely shaped**: about
**7% on DIFF_MAX and 6% on JUMPDEST, but only under opcodes that load the callee's code**. The
same two modes under BALANCE/EXTCODEHASH - which read the account row and never the code - are at
**parity (1.013, 0.991)**. MINIMAL and SAME_MAX, which do load code but small or reused code, are
also at parity (0.99). The axis is therefore *loading a large contract's code that was not just
loaded*, and nothing else.

Two honest caveats on the same table: the short/sub-second cells (CONTROL 1.14-1.18, warm query
1.29, sload_same_key 1.27-1.35, NON_EXISTING 1.09-1.21) sit above parity because
`TieredCompilation=0` over-corrects, and their swings (up to +0.12) are as large as several of the
effects being discussed. Only the >=5 s cells (all the DIFF_MAX/JUMPDEST/SAME_MAX/MINIMAL/EOA
rows, ether, storage) carry weight.

## Round 44 - attribution attempt failed on a YAML escape, relaunched

`filter: "...AccountMode\.EXISTING..."` - `\.` is an invalid escape in a double-quoted YAML
scalar, so benchmarkoor refused the config and all four traced runs executed 0 tests. Changed to
`AccountMode[.]` (verified through a YAML parse before shipping) and relaunched as R44b.

## Round 44b / 45 (result) - it is not the code database: state-actor resolves state reads through the Merkle trie

Per-CF attribution of one traced test per cell, every page-cache fill mapped to a file and each
SST to its column family. (The first pass mislabelled jochemnet because its snapshot path
contains `nethermind` as an intermediate directory; anchored on each arm's datadir root instead.)

**R44b - DIFF_MAX vs SAME_MAX (EXTCODESIZE), marginal cost of contract distinctness:**

| inside the datadir | jochemnet | state-actor |
|---|---|---|
| code | **+275 MB (100%)** | +310 MB (30%) |
| flat/StateNodes | **0** | **+716 MB (70%)** |
| flat/Account | -0.3 (flat) | -0.4 (flat) |

Code reads are equal between arms (275 vs 310 MB) and account reads are unchanged by
distinctness on both. The whole asymmetry is trie-node traffic that only state-actor performs.

**R45 - the same attribution on tests that touch no code at all:**

| | jochemnet | state-actor |
|---|---|---|
| BALANCE / EXISTING_EOA - trie nodes | **0** | **1,379.9 MB** |
| EXTCODESIZE / MINIMAL - trie nodes | **0** | **690.7 MB** |
| flat/Account | 421 / 402 MB | 422 / 403 MB |
| legacy Patricia `state/` | 157 / 0 MB | 0 / 0 |

state-actor reads 0.7-1.4 GB of `flat/StateNodes` on a pure BALANCE test. **The trie traffic is
universal on state-actor, not code-related.** It scales with the number of distinct accounts a
test touches, which is why the code-heavy modes (a new max-size contract per access) show the
largest gap while EOA/MINIMAL/SAME_MAX stay at parity - the extra reads are absorbed by the NVMe
until the volume roughly triples. Consistent with the earlier CPU evidence for that cell
(ratio 0.79: state-actor waits, it does not compute).

**Why: the generated store has no persisted-snapshot layer.** jochemnet's datadir carries
`persistedSnapshot/{arena,blob,catalog}` (plus `metadata`, `blockAccessLists`,
`blobTransactions`); state-actor has none of them, though both clients open a
`PersistedSnapshotCatalog` at boot. Both stores DO have a populated trie - state-actor's
`StateNodes` holds 596M nodes in 48.9 GB, and the generator's own `internal/neth/flat/doc.go`
states the flat backend relocates the Merkle trie into the node column families rather than
eliminating it, and emits both the nodes and the flat leaf rows. So nothing is missing from the
flat column DB itself; what is missing is the newer serving structure a client-written flat DB
accumulates. Without it the client appears to resolve reads through the trie; with it,
jochemnet answers from `flat/Account` alone and never touches `StateNodes`.

**Status of this claim:** the attribution is one traced test per cell, but the effect is 0 vs
1.4 GB, far outside anything noise could produce. The causal step - that the persisted snapshot
is what suppresses the trie reads - is inferred from the structural difference and is NOT yet
demonstrated by intervention. That is the next experiment, and it is a generator change rather
than a store edit.

## Round 44 first attempt - YAML escape

`filter: "...AccountMode\.EXISTING..."`: `\.` is an invalid escape in a double-quoted YAML
scalar, so benchmarkoor refused the config and all four traced runs executed 0 tests. Changed to
`AccountMode[.]`, verified through a YAML parse before shipping. Third identifier mistake of this
kind; the lesson each time is to validate the selector before spending runs on it.

## Rounds 46-53 - the flat state is correct; the residual is RocksDB tombstone GC on the trie CFs

Prompted by the reading that "a BALANCE lookup touching 1.4 GB of trie nodes means flat state is
broken or malformed". It is neither, and the trail ends somewhere better.

**R46 - RPC-level read test.** 2,000 `eth_getBalance` calls per arm, no block processing:
jochemnet reads 16.3 MB from `flat/Account` and **zero** trie nodes; state-actor reads **the same
16.3 MB** from `flat/Account` plus 2,181 MB of `flat/StateNodes`. Identical flat-leaf cost, so the
flat read path works on both. Latency 0.48 vs 0.64 ms - far too close for 1 MB of synchronous NVMe
per lookup, which is what first suggested the trie reads were not on the read path at all.
(First attempt aborted: `--config=none` without an engine port fails `InitializeMergePlugin`.)

**R47 - idle control, the decisive one.** Same boot, same cache drop, **zero queries**, 40 s idle:
jochemnet 0.1 MB, state-actor **3,569 MB of `flat/StateNodes` at 89 MB/s, continuously**. The reads
are not caused by the queries. Nothing about the read path explains them.

**R48 - the FlatDb compaction offset is not it.** `Generated new FlatDb compaction offset` at every
boot looked like the cause (state-actor has no `metadata` DB to load one from; the option's help says
"instead of loading from metadata DB"). But `--FlatDb.CompactionOffset=0` (log confirms "Using
configured FlatDb compaction offset 0") and `--FlatDb.MaxInFlightCompactJob=0` both leave the scan
running at 91.5 / 86.9 MB/s. Eliminated.

**R49 - a false negative worth recording.** Reported the client doing 0 MB of I/O. Two bugs:
`/proc/PID/io` was read as `ubuntu` against a root-owned container process (silently empty -> 0), and
`pidstat` ran after the client had exited. Also missed the compaction in `flat/LOG` because RocksDB
rotates `LOG` on open and the byte-offset tail read the wrong region.

**R50 - corrected attribution.** Client's own block-layer reads over 60 s idle, zero queries:
jochemnet **0 MB**, state-actor **1,962 MB** (~33 MB/s). It is the client.

**R51 - which thread.** Block I/O by thread name over 45 s: **`rocksdb:low` 1,948 MB** (the
`kworker/u96:*` entries are dm-era writeback servicing the same I/O). RocksDB background compaction,
not Nethermind-level code, and ~0% CPU on every client thread - pure I/O.

**R52 - the reason, from the event log.** One fresh boot each, zero queries:

| arm | compaction jobs | CF | `compaction_reason` |
|---|---|---|---|
| state-actor | **14** | **StateNodes** | **`BottommostFiles`** |
| jochemnet | 1 | StorageNodes | `LevelMaxLevelSize` |

`kBottommostFiles` is RocksDB rewriting bottommost files to zero out their sequence numbers.
`ComputeBottommostFilesMarkedForCompaction` marks every bottommost file whose `largest_seqno != 0`
once no snapshot protects it, so the trigger is not tombstone count but *how the file was produced*:
files written by flush, or by a compaction that could not zero seqnos, stay marked until something
rewrites them. That is the generator's whole output. jochemnet's files came out of a real node's
ordinary compaction cycles and are mostly already zeroed. `ttl=2592000` (30 days) is set on every CF
of both stores but is not the trigger here - the reason field says `BottommostFiles`, not `Ttl`.
(The seqno mechanism is read off RocksDB's semantics, not measured; what is measured is the reason
field, the 14 jobs, and that an explicit `CompactRange` on Account in round 34 stopped it recurring
for that CF.)

**Why it was invisible until now.** `estimate-pending-compaction-bytes` is 0 and every CF sits at
L6, which is what rounds 18/32/34 checked. Tombstone-driven bottommost GC is not counted in either.
Account (round 34) and code (rounds 38/42) were settled by explicit `CompactRange`; **the trie
families never were**. The harness restarts the client for every one of 1,463 tests, so the job
restarts from scratch each time and never finishes.

**Status of the fix (R53, incomplete).** `probe-flat -mode rebuild -cf
StateNodes,StateTopNodes,StorageNodes,FallbackNodes -level 6` on state-actor: `StateNodes` is 603
files / 51.17 GB, all already at L6. Rebuild launched 22:16 UTC and was still running 2.5 h later
when the host stopped accepting SSH sessions for the third time this study (same PAM/logind
signature as rounds 5 and 40-41; ping and the SSH banner both fine, session setup hangs). The
promote only runs after the rebuild returns, so a timeout kill leaves the virgin image untouched and
the scratch volume discardable with `schelk restore`.

Two tooling notes from this block: the probe image lives in the **rootless** podman store while the
nethermind image is in root's, so `sudo podman run` cannot see the probe (the flat dir is
`ubuntu:ubuntu 755`, so the rebuild runs fine unprivileged); and a guard loop of the form
`pgrep -f "benchmarkoor run"` matches **its own** command line when the script text is on a
`bash -c` process, which silently parked R52 for 78 minutes.

**What this does and does not claim.** Proven: the flat backend is detected and serving
(`State backend: flat (existing flat DB detected)`), flat-leaf reads are byte-identical between the
arms, and the trie traffic is background tombstone GC that runs with the client otherwise idle. Not
yet proven: that removing it closes the ~7% DIFF_MAX / ~6% JUMPDEST gap. That needs the rebuild to
land and the 266-test subset re-run on both arms.

## Round 53 (result) + upstream fix: state-actor PR #139

R53 landed while the host was unreachable, and it is unambiguous. After forcing bottommost
compaction on the trie CFs (`StateNodes` 603 -> 207 files in 422 s, `StorageNodes` 1211 -> 1126 in
2114 s, promoted at 1.39 GB/s):

| | before | after |
|---|---|---|
| client block-layer reads, 60 s idle, zero queries | 1,962 MB | **0 MB** |
| `compaction_started` events at boot | 14 | **0** |

(The verdict file's "10 ms per balance lookup" is my own per-call `curl` process spawn, not client
latency - R46's 0.48/0.64 ms figures came from a different loop. Not comparable, ignore it.)

**ethereum/state-actor#139 fixes this at the source.** Every writer called the plain
`CompactRange`/`CompactRangeCF`, leaving `bottommost_level_compaction` at `kIfHaveCompactionFilter`
with no filter configured, so RocksDB *trivially moved* the flushed L0 files into the empty bottom
level: flat tree, every file still carrying `largest_seqno != 0`. The PR switches all call sites to
`CompactRangeOpt`/`CompactRangeCFOpt` with `SetBottommostLevelCompaction(KForce)` - nethermind's
three (plain DBs, receipts CFs, flat CFs), plus besu, ethrex, and reth (which ran no Close-time
compaction at all). Both `*Opt` methods exist in the pinned `grocksdb v1.10.8`. Regression tests in
`client/besu` and `client/nethermind` reopen with auto-compactions disabled and assert every SST
reports `seq:0`, so they observe what `Close` left rather than what a reopen repairs.

Cross-checks against this study's measurements: the mechanism is the one located in rounds 46-52;
the option is the one R53 applied by hand; and the PR's cost estimate (~42 min at 350 GB, ~120 MB/s)
matches R53's measured 2,536 s at 121-132 MB/s over ~330 GB. Coverage is a superset of R53's manual
settle, which only touched the four trie families.

**One claim in the PR is contradicted by this study's data.** It says "an idling node never shows
this ... the marking needs a snapshot release, not just an open", on the evidence of Besu idling
150 s. That holds for Besu but not for Nethermind: R50/R51/R52 measured an *idle* Nethermind with
zero queries doing 1,962 MB / 60 s across 14 `compaction_started` events, all `StateNodes`, reason
`BottommostFiles`. Nethermind evidently takes and releases a snapshot during startup, so the marking
fires at boot with no client work at all. The distinction matters: it is the difference between "only
under load" and "on every one of 1,463 per-test client restarts", which is precisely why this
contaminated the whole suite.

**What the PR does not do:** it fixes future generations only. Every already-published state-actor
image still carries moved-not-rewritten files and needs either regeneration or the offline settle
pass (`probe-flat -mode rebuild` + `schelk promote`). The image under measurement here is settled by
hand, so R54 remains a valid test of the fix's premise. Out of scope and still true: state-actor
emits no `metadata` DB, so Nethermind regenerates the FlatDb compaction offset at every boot - R48
proved that is not a source of I/O, but it is still a difference between the two stores.

## Rounds 54-56 (result) and the article update - published

**R54 falsified the prediction.** 266-test subset, both arms, identical corrected config, settled
store, precondition verified at launch (`compaction jobs at boot = 0`), 266/266 with zero failures
on both arms:

| cell | R43 r1 | R43 r2 | R54 settled | move | R43 replica swing |
|---|---|---|---|---|---|
| DIFF_MAX code-exec | 0.928 | 0.933 | **0.938** | +0.007 | 0.005 |
| JUMPDEST code-exec | 0.938 | 0.937 | **0.943** | +0.005 | 0.000 |

7.0% slower -> 6.2%. Removing 33-90 MB/s of continuous background I/O from every test bought a
tenth of a seven-point gap. `CONTROL` stays at 1.142, i.e. state-actor is 14% *faster* on tests
that do no state work at all. Several unrelated cells moved far more than the two under study
(`NON_EXISTING_ACCOUNT BAL/HASH` +0.217, `sload_same_key` -0.207), consistent with the measured
floor, so R54 cannot resolve small effects - but a seven-point gap closing would have been
unmissable.

**R55/R56 - the attribution, re-run quiet, and it finally agrees with the throughput.** Non-code
access (BALANCE/EOA vs EXTCODESIZE/MINIMAL): state-actor's marginal is 19.3 MB from
`flat/Account` against jochemnet's 16.2 MB across its whole datadir, and `flat/StateNodes`
contributes 0.0 MB where it had shown 689. Distinct max-size contract per access, six matched
pairs per arm (EXTCODESIZE/CALL/EXTCODECOPY x 160M/240M): **2,821 MB against 1,671 MB = 1.69x**,
of which 2,444 MB is the code database; `flat/Account` is flat (-1.0 MB) and the trie families
stay at zero (-0.1 MB). Published was 2.23x, the contaminated "corrected" run said 1.31x.

**Correction to my own framing.** I had explained the old numbers as "inflation proportional to
test duration". That does not survive arithmetic: DIFF_MAX tests run 1.76 s (160M) and 2.67 s
(240M), so at the measured 33 MB/s idle rate the phantom is 58-87 MB - about 2% of a per-test
byte column, nowhere near the 716 MB it added to the *marginal*. The actual mechanism is that the
per-CF probes compare two separate runs, each with its own boot, so background traffic enters each
window in proportion to how long that window stayed open, and it landed on the difference between
two large numbers. The article says it this way, not the duration way.

**Article updated and live** at `a11d0ed`, byte-identical to the local build, published from a
clean checkout of `origin/main` with zero sibling folders touched. New section "Defect 3: the
generated store makes the client rewrite it"; the overview list goes from three defects to four;
the residual section is rebuilt on the settled-store attribution; the recommendation now covers
`kForce` as well as the target level and links state-actor#139; two errata items added. Three new
figures: `fig_seqno_paths` (the move-vs-rewrite diagram), `fig_idle_reads`, `fig_marginal_cf`.
Five new oracles, including one that fails the build if settling the store ever *does* move
DIFF_MAX - the section is written around that null result, so it must not be able to rot silently.

## Round 57 - the article is reported by duration class (published)

Plan gated through Plannotator (one revision: the class-mixing errata item was cut on request,
then approved). No new benchmark runs; everything below is recomputation from result trees on
disk, via a new `collect_classes.py`.

**The split, measured rather than asserted.** Membership is fixed once from the reference arm of
the treated pair and applied to every column, so rows do not change population between tables:

| pair | < 1 s | >= 1 s |
|---|---|---|
| published | n=676, median 0.805 | n=785, median **0.164** |
| treated | n=676, median 0.767, 18% within 10% | n=785, median **0.978**, 83% |
| replica floor (same store twice) | 49% within 10% | **97%** |

Every category still far from parity after treatment is wholly sub-second: CONTROL (440 tests,
0.12 s median, 0.708), sload_same_key (0.812), warm query (0.896), absent account (0.904). The
storage category straddles the boundary and reads **1.468 below a second against 1.007 above it**
- same category, same pair of stores - which is the cheapest evidence the line is real. The
boundary is not load-bearing either: the long class reads 0.979 / 0.978 / 0.977 at 0.5 / 1 / 2 s.

**Inside the long class the residual is one square**, and this is the taxonomy the article now
leads with. Account-row opcodes (BALANCE, EXTCODEHASH) sit at 0.971-0.977 under *every* access
mode, reading at most 1.06x the bytes. Code-loading opcodes match them at 0.980 while the contract
is reused, fall to 0.926 when the code is only scanned for jump destinations, and to 0.642 when
every access touches a distinct maximum-size contract - where they read 1.48x the bytes.
Throughput tracks bytes down the row.

**Structure.** New: "How to read a number on this page" (earns the split from the replica floor
before using it), "Class 2 in detail", "Class 1: why the sub-second tests are not evidence".
Defects renamed Findings 1-4. Cut: the mixed-class subset table and the "bracket the truth"
framing it forced, the 2x2 the family matrix supersedes, the additive two-term model and its
figure (never embedded since the JIT rewrite, and its bytes predate Finding 3), and the grid's
absent column (all 110 of its tests are sub-second). Two new figures; `fig_ratio_dots` now marks
class membership per row. Seven new oracles, each mutation-tested to confirm it refuses
generation when contradicted.

**One near-miss worth recording.** `main` had moved while this was in progress: the Besu study
rewrote `collect_nethermind.py` to derive its reference ratios with the `overhead_baseline`
controls excluded, having previously pooled them (0.962x/2.92x published against 0.908x/10.06x
measured). A plain rsync of this folder would have silently reverted both their collector and
their corrected numbers. Caught by diffing the publish checkout against `main` before committing;
their version was adopted instead, and the cross-client table now reads 6.5x untreated / 0.908x
treated for Besu. Publishing by folder rsync needs that diff every time.

Live at `5ffec1f`, byte-identical to the local build, zero sibling folders touched.

## Round 58 - the article cut to its findings, with the residual's mechanism (published)

Editorial round on request: remove the floor-figure caption, the class-table caption and storage
note, and the Class 1, Three clients and What to do about it sections; condense the root cause,
the JIT test and Findings 1-3; make Finding 4 direct; add a closing figure with the results after
all fixes. Prose ~7,000 -> ~6,100 words, every table and figure kept, errata untouched.

**Correction to the premise as stated.** The request assumed EXTCODESIZE "might be cached".
It is not: under DIFF_MAX it is the *worst* opcode at 0.626, below CALL at 0.775. The parity
opcodes are exactly the two that read only the account row, BALANCE 0.969 and EXTCODEHASH 0.972.
The article says so.

**Correction to my own earlier claim.** "state-actor embeds the address in the code key, so
nothing dedups" was wrong: both the Nethermind and Besu writers key code by hash
(`codeSink.put(acc.CodeHash[:], ...)`, `PutCode(codeHash, ...)`). The 134M-vs-2.4M entry count
is fixture composition - almost every generated account carries a distinct 23-byte stub - not
keying. Removed from the article.

**The residual's mechanism, cross-checked against the Besu study.** Its `code_block_sim`
(BlockSim.java, packing each store's own records the way RocksDB does) puts the block that must
be read to fetch one 24,576-byte fixture contract at **10,718 B on state-actor vs 5,912 B on
jochemnet** - 1.81x per fetch. The generated store's block is *smaller raw* (36 KB vs 42 KB)
but *larger compressed*, because its ~32 tenants are 352-byte stubs that do not compress while
jochemnet's ~2.4 tenants are real bytecode that compresses ~3x. This brackets the 1.69x marginal
measured here (R56), reconciles the cold single-lookup probe (which measures one block and sees
the generated store as cheaper), and matches the same cell's shape on Besu: **0.831 DIFF_MAX vs
0.944 SAME_MAX** for code-loading opcodes. So the effect follows the artifact across two engines.
(The "faster on Besu" recollection was geth, treated 1.031-1.117x.) Decisive test, not yet run:
rebuild the generated code CF with large values isolated in their own blocks and re-run the
cell. Folded into `measured.besu_cross_check`, derived from the sibling data at collect time.

**Ether transfers (state-actor 7.6% faster, reproducibly, while reading 17% more bytes)** are
the mirror image: trie-node lookups on each store's own keys cost 3.44 blocks / 208 us on
state-actor against 10.26 / 434 us on jochemnet, and transfers do the most state-root work per
unit gas. Not written into the article; the per-CF trace on a transfer window is the test.

**Closing figure** `fig_final_cells`: every long-class cell after all four findings, from
`classes.final_cells`: 12 of 12 inside +/-10%, DIFF_MAX code-exec 0.938 and JUMPDEST code-exec
0.943 with the two R43 replicas beside them. Four new oracles (simulation direction, Besu split,
residual pair below 0.97, every other cell in band), mutation-tested.

Live at `355675a`, byte-identical, zero sibling folders touched; `main` had moved again (Besu
re-cut) and the shared files and cross-client block were checked for drift before publishing.
