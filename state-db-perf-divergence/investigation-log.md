# Investigation log — origin of the compacted vs state-actor divergence

Companion to `state-db-perf-report.html`. The report states conclusions; this log states
the reasoning, including everything discarded and what killed it. Written before the
evidence phase so the hypotheses cannot be retrofitted to the findings.

Scope decision: the mechanism is hunted in `go-ethereum` at `upstream/master`
(`2a439ba452`, 2026-08-06). The benchmarked binary was
`jochem-brouwer/go-ethereum @ 4d92c8e0` (glamsterdam-devnet-7, 2026-08-11), five days
newer. For the trie/pathdb/state read paths the two are expected to be identical;
where a conclusion depends on a specific line, it is spot-checked against the real ref.
The local checkout's own branch (`pbt`, 147 commits ahead, +13k lines in `trie/bintrie`)
is **out of scope** — it never ran this benchmark, and it rewrites exactly the subsystem
under suspicion, so reading it would manufacture plausible wrong answers.

## 1. What actually needs explaining

µs per cold account lookup, BALANCE, value_sent=0:

| account class | compacted | uncompacted | state-actor |
|---|---|---|---|
| NON_EXISTING | 14.3 | 17.3 | 15.7 |
| EOA | 15.1 | 8.3 | 16.7 |
| MINIMAL | 14.2 | 3.2 | 15.2 |
| SAME_MAX | 13.8 | 2.6 | 15.3 |
| JUMPDEST | 13.9 | 3.1 | 15.5 |
| **DIFF_MAX** | **2.1** | **2.4** | 16.3 |

The report's original framing — "state-actor is slow" — is backwards. state-actor is
*uniform*: 15.2–16.7 µs on every class, including the address range that exists in no
database. jochemnet is the outlier, because it has anomalously **fast** classes. Three
distinct questions follow:

- **P1** Why is DIFF_MAX ~7× cheaper than sibling classes *within the same database*?
- **P2** Why does state-actor have no fast class at all?
- **P3** Why did compaction destroy four of five fast paths (EOA, MINIMAL, SAME_MAX,
  JUMPDEST: 2.6–8.3 → 13.8–15.1 µs) yet leave DIFF_MAX untouched (2.4 → 2.1), while
  making NON_EXISTING *faster* (17.3 → 14.3)?

## 2. The deduction that shrinks the search space

Under `BALANCE`, geth reads one account leaf: `{Nonce, Balance, Root, CodeHash}`. That
leaf has the same shape whether the account's code is 1 byte (MINIMAL), a 24 KB blob
shared by 150,000 accounts (SAME_MAX), or a byte-unique 24 KB blob (DIFF_MAX). Contract
code lives in a separate table keyed by hash; `BALANCE` never reads it.

Corroborated empirically rather than assumed: the measured CODE delta (CALL slope minus
BALANCE slope) is ≈7 ms/Mgas for JUMPDEST and DIFF_MAX in **all three** databases, i.e.
code fetch is an additive cost that does not vary by database.

**Therefore P1 cannot be caused by object size, code size, or code-hash sharing.**
Structurally identical leaves cannot differ 7× in read cost because of what they point
at. The only remaining shape of explanation is *which storage tier answers the read*.
This eliminates an entire family of intuitive explanations a priori.

## 3. Discarded before spending any exploration

| Hypothesis | What killed it |
|---|---|
| Larger or unique code takes a different read path | Account leaves are fixed-shape under BALANCE; CODE delta ≈7 ms/Mgas in all three DBs |
| state-actor is missing the target accounts | value_sent=1 gas pricing separates existing from non-existing *within* each DB; compacted's DIFF_MAX ÷ its own NON_EXISTING = 3.36/0.47 = 7.1× |
| The three runs did different amounts of work | `block.gas_used` bit-identical across all three runs on 406/406 common tests |
| CPU, thermal, or host contention | overhead_baseline median `execution_ms` 33.1 / 33.8 / 32.9 ms |
| Time drift or warm-up over run position | compacted ÷ uncompacted tracks the account class measured (0.24–1.22×), not run position |
| The generator silently dropped the large classes on a size cap | `specbuild/build.go:243` — the 2 GiB limit is a warning by design; the cap is 64 GiB; the YAML creates every class at 150,000 |
| Different derived addresses between the two fixture bundles | Addresses derive from fixed constants — Bittrex CREATE-preimage chain, sequential EOAs from `0x1000`, `keccak256("random")` — not from the bundle hash |

## 4. Live hypotheses, each with its kill condition

All are storage-tier shaped, per §2.

**HA — Journal residency across container recreation.** *Leading.* The benchmark uses
container-recreate, so geth restarts fresh for every test. jochemnet loads a
**380.15 MiB `merkle.journal` at every startup**; state-actor logs `journal not found`.
pathdb's journal holds unflushed dirty trie nodes, so jochemnet begins every test with
380 MiB of trie state already resident while state-actor begins cold. Explains P1, P2 and
P3 with one mechanism, and compaction cannot touch it because the journal is a separate
file from the SSTables.
*Kill if:* the journal does not contain account-trie leaves for the benchmark classes; or
the journal is loaded lazily rather than into memory; or state-actor's startup shows an
equivalent warm tier by another name.

**HA′ — Write-order recency inside the journal.** Refines HA to answer "why DIFF_MAX
specifically". If the pre-run bundle writes classes in a fixed order, only the
last-written survive in the journal/dirty set at benchmark time. The uncompacted ordering
is a suggestive gradient: DIFF_MAX 2.4 < SAME_MAX 2.6 < JUMPDEST 3.1 < MINIMAL 3.2 <
EOA 8.3 < NON_EXISTING 17.3.
*Kill if:* bundle write order does not match the speed ordering.

**HB — Snapshot (flat state) availability differs.** geth's snapshot layer answers
account reads from a flat KV table without walking the trie. If one database has a usable
snapshot and the other is missing or regenerating it, that is a large uniform difference —
a natural P2 candidate.
*Kill if:* both runs report identical snapshot status at startup.

**HC — Trie cache sizing differs between containers.** `Allocated trie memory caches`
reports the clean/dirty split. Different `--cache` settings would shift everything
uniformly.
*Kill if:* the reported sizes are identical across runs. (Cheap; also a candidate for the
flat ~10% offset rather than the 7× gap.)

**HD — Unclean-shutdown recovery.** `Unclean shutdown detected` appears 9,140× in the
compacted container log and is absent from state-actor's top message kinds. Unclean
shutdown drives recovery paths that can repopulate memory or force regeneration.
*Kill if:* state-actor shows them at comparable rate, or the line is a benign banner with
no recovery consequence.

**HE — Compaction changed on-disk layout.** Would explain P3's NON_EXISTING improvement
(absence proofs get cheaper on tidier SSTables) and the loss of the other fast paths.
*Kill if:* the logs carry no pebble level/SST evidence — in which case it is parked as
unevaluable rather than claimed.

## 5. Method

1. **Eliminate first** (§3), using only facts already verified, so no exploration is spent
   on dead hypotheses.
2. **Mine the un-mined evidence.** Three read-only agents, one per `container_*.log`
   (10 MB each, never parsed — v1 used them only for hand-copied constants), all
   extracting one identical schema so the runs are directly comparable.
3. **Map asymmetries to code.** Every cross-run difference is traced to its emitting call
   site in `upstream/master`, converting an observed log line into a named code path.
4. **Verdict each hypothesis** against its kill condition. Survivors are stated with the
   evidence that supports them; the rest are recorded here with what killed them.

Findings are appended below as §6 onward.

## 6. Evidence — the three container logs, mined

Three read-only agents, one log each, identical extraction schema. Reports:
`/tmp/statedb-logmine/{compacted,uncompacted,state-actor}.md`.

| | compacted | uncompacted | state-actor |
|---|---|---|---|
| container lifecycles | 914 | 974 | 999 |
| journal at startup | loaded | loaded (974×) | **`Failed to load journal, discard it err="journal not found"` ×999** |
| journal at shutdown | 380.15 MiB, `layers=4248` | 380.15 MiB, `layers=4248` | 39.80 MiB, `layers=3` |
| `triecache` | 1023.00 MiB | 1023.00 MiB | 1023.00 MiB |
| `statecache` | **0.00 B** | **0.00 B** | **0.00 B** |
| `buffer` | 256.00 MiB | 256.00 MiB | 256.00 MiB |
| `Allocated trie memory caches` | clean=1023.00 MiB dirty=1.00 GiB | identical | identical |
| db cache / handles / version | 2.00 GiB / 536,870,908 / v1 | identical | identical |
| `Pebble ... legacy v1 format` WARN | 915× | 974× | 999× |
| snapshot / flat-state lines | 0 | 0 | 0 |
| compaction / SST / level lines | 0 | 0 | 0 |
| `Unclean shutdown detected` | 9140 | 9740 | 0 |

Every tunable is byte-identical across the three runs. The only configuration-level
difference in the entire corpus is whether a journal is found at startup.

## 7. The read path, from source

`upstream/master`, `triedb/pathdb`:

- `loadLayers()` (`journal.go:162`) forks on exactly one condition:
  `loadJournal(root)` succeeds → return the reconstructed layer stack; it fails →
  `log.Info("Failed to load journal, discard it", "err", err)` then
  `newDiskLayer(root, …, newBuffer(WriteBufferSize, nil, nil, 0), nil)` — a **single disk
  layer with an empty write buffer**.
- `loadDiskLayer()` (`journal.go:197`) decodes the journal's `nodeSet` and `stateSet`
  straight into a live `newBuffer(…, &nodes, &states, id-stored)`. The journal does not
  merely record metadata; it **rehydrates the not-yet-written state buffer**.
- `diskLayer.account()` (`disklayer.go:171`) consults tiers in order:
  `dl.buffer` and `dl.frozen` → `dl.states` clean cache → disk. Each tier is metered:
  `dirtyStateHitMeter`, `dirtyStateMissMeter`, `cleanStateHitMeter`,
  `dirtyStateHitDepthHist`.
- `newDiskLayer()` (`disklayer.go:58`) allocates the state clean cache only
  `if db.config.StateCleanSize != 0`. With the measured `statecache=0.00B`,
  **`dl.states` is nil in all three runs** — there is no clean state tier anywhere.

Consequence: the journal-restored buffer and diff layers are the *only* warm tier that
exists for an account read in this configuration. A run without a journal serves 100% of
account reads from disk.

## 8. Verdicts

| Hypothesis | Verdict | Evidence |
|---|---|---|
| **HA** journal residency | **Confirmed (tier level)** | jochemnet rehydrates 380.15 MiB / 4248 layers at every one of ~900–970 restarts; state-actor fails 999/999 despite writing 39.80 MiB journals seconds earlier. Source shows the journal restores the first tier consulted, and no other warm tier exists (`statecache=0.00B`). Explains P1 and P2. |
| **HA′** write-order recency | **Supported, not proven** | The uncompacted ordering — DIFF_MAX 2.4 < SAME_MAX 2.6 < JUMPDEST 3.1 < MINIMAL 3.2 < EOA 8.3 < NON_EXISTING 17.3 µs — is exactly a hit-depth gradient over a 4248-layer stack, and geth meters precisely that (`dirtyStateHitDepthHist`). The journal's contents were never inspected. |
| **HB** snapshot / flat state | **Dead** | Zero matches for `snapshot`/`generat`/`Rebuilding`/`flat` in any of the three logs, checked across sequential windows spanning every file. All three run `scheme=path`; no snapshot layer is involved. |
| **HC** trie cache sizing | **Dead** | `clean=1023.00MiB dirty=1.00GiB`, `cache=2.00GiB handles=536,870,908`, `triecache=1023.00MiB statecache=0.00B buffer=256.00MiB` — byte-identical in all three runs, with no second variant anywhere. |
| **HD** unclean-shutdown recovery | **Dead** | The counts are 10 static, pre-existing 2025 timestamps replayed once per cycle (914×10≈9140, 974×10≈9740); `crashesToKeep = 10` caps the list. `NewShutdownTracker` is documented "no other side-effect" and `MarkStartup` only reports. No repair or regeneration follows. state-actor's 0 simply means its image carries no markers. |
| **HE** on-disk layout after compaction | **Parked, unevaluable from this evidence** | All three logs contain zero compaction/SST/level lines, exactly the kill condition stated in §4. It remains the only surviving candidate for P3 — why compacted lost four fast classes that uncompacted has, given both load an identical journal — but nothing here evidences it. |

## 9. What causes the discrepancy

**Proven.** state-actor's snapshot image ships without a pathdb journal, so every geth
restart — and the benchmark restarts geth for *every test* — begins with an empty write
buffer, no diff layers, and (because `statecache=0.00B`) no clean state cache. Every
account read goes to disk, which is why state-actor is uniformly 15.2–16.7 µs across every
class including the never-existing range. jochemnet's image ships a 380.15 MiB journal with
4248 diff layers, rehydrated into the first tier consulted on every read, so some fraction
of its accounts are served from RAM at ~2 µs. Compaction cannot touch this: the journal is
a separate file (`/data/geth/triedb/merkle.journal`) from the SSTables.

This is a **provenance artifact, not a property of either database.** The jochemnet image
was captured from a running geth that had unflushed dirty state — corroborated by the ten
static 2025 unclean-shutdown markers baked into the same image. The state-actor image was
synthesised by a tool that writes SSTables directly and never runs a geth that would
journal.

**Inferred, not proven.** That the specific fast classes are the ones resident in
jochemnet's journal. The speed ordering matches a recency/hit-depth gradient, but the
journal's contents were never read. This is the boundary v1 blurred: v1 called it "memory
residency, inferred". It is now *journal* residency with the tier proven from logs and
source, and only the per-class attribution left inferred.

**Open.** P3 — why manual compaction cost uncompacted's four other fast classes
(2.6–8.3 → 13.8–15.1 µs) while leaving DIFF_MAX at ~2 µs, and why it made NON_EXISTING
*faster* (17.3 → 14.3). Both jochemnet runs load an identical journal, so the diff-layer
tier cannot be the differentiator; the remaining explanation is on-disk layout (HE), which
this evidence cannot evaluate.

## 10. Next steps, in cost order

1. **Read the meters that already exist.** `dirtyStateHitMeter`, `dirtyStateMissMeter`,
   `cleanStateHitMeter` and `dirtyStateHitDepthHist` are already emitted per tier on the
   metrics endpoint the logs show running (`127.0.0.1:8008/debug/metrics`). Scraping them
   per test converts HA′ from inference to measurement and settles the per-class
   attribution directly. v1's "scrape `trie/memcache/clean/*`" named the wrong meters.
2. **Make the journal an explicit benchmark axis.** Either strip the journal from the
   jochemnet image before benchmarking, or generate one for state-actor, so the two images
   start from the same tier state. Until then the benchmark partly measures snapshot
   provenance rather than database access cost.
3. **Fix the pebble format.** All three runs log `Pebble database uses legacy v1 format;
   upgrade offline with 'geth db pebble-upgrade'`. Not a differentiator here, since all
   three share it, but it means every number was measured on a format geth asks you to
   migrate off.
4. **Settle P3** with a pebble-level probe (SST count and level distribution before and
   after manual compaction), the one question this corpus cannot answer.
