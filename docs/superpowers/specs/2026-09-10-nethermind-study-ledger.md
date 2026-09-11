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
