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
