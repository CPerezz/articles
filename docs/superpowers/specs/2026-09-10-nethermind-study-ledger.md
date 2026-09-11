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
