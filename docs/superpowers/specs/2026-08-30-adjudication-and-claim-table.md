# Task 17 — three-agent analysis, adjudication, and final claim table

Agents: Recompute-A and Recompute-B (raw data only, no report numbers, forced
onto different computational paths), Adversary-C (report + data, briefed to
falsify). Every load-bearing agent claim below was re-verified by me against
raw data before acceptance; nothing was accepted on an agent's word.

## Agent agreement

A, B and my own Task 16 derivation agree on every shared quantity. B's path was
genuinely independent: it refused the `mgas_s` field and derived throughput as
`gas_used["0"] / duration_ns[0]` — **bit-exact against `mgas_s` on all 2,924
tests** — then cross-checked against geth's own `Slow block` telemetry as a
third source. benchmarkoor's arithmetic, my parsing, and geth's self-reported
throughput all agree.

A found one real error in my derivation: my "100 Mgas discontinuity" was an
artifact of snapping gas from `gas_used` (overhead-baseline variants burn less
gas than nominal and fell into my 100 M bucket). Gas parsed from the full test
name (via `.test-name`) removes it.

## The adversary's findings, fact-checked

Adversary-C's central objection is **correct and I accept it**. My Task 16
conclusion — "journal-provenance as the sole cause is refuted" — is **retracted**.
It conflated the *shipped* journal file (265.6 MiB) with the *journal at
measurement time*. Verified from raw data:

- The pre-run deterministically **rewrites** the journal to 380.15 MiB /
  4248 layers — matching the original report's published pair to the digit,
  which proves the original runs also measured with a post-pre-run journal.
- Baseline H restores that journal before every test; **1463/1463** jochemnet
  boots log `Load database journal from file`. All 1461 state-actor boots log
  `journal not found`.
- Disk-read telemetry (`resources["0"].disk_read_bytes`, my re-computation):
  jochemnet BALANCE/DIFF_MAX reads **12.6 kB/Mgas**; the other five modes in the
  same arm read **18,813-19,030 kB/Mgas** (~1,500×); state-actor DIFF_MAX reads
  22,076 kB/Mgas. With drop_caches verified firing and a fresh geth per test,
  the boot-time journal load is the only memory vessel that can serve those
  leaves. The same-arm SAME_MAX reads are the internal control proving caches
  were cold.
- The leaf-vs-code split seals the mechanism: pathdb's journal carries trie
  nodes, not code blobs. Leaf-only opcodes (BALANCE, EXTCODEHASH) diverge
  ~23× at near-zero disk; code-reading opcodes (CALL/CALLCODE at 7.7 MB/Mgas)
  diverge only ~2.8×.

**The journal-residency mechanism is therefore CONFIRMED as proximate cause —
measured, no longer inferred.** What changes versus the original report is the
provenance detail: the operative journal is not the shipped file but the one
the pre-run + promote + restore pipeline deterministically recreates. It is a
*pipeline* artifact rather than a *download* artifact — and it was present in
the original runs too.

Also accepted from the adversary, each verified:

1. **Magnitude framing** ("23×, tripled from 7.71×") retracted. 7.71× was a
   slope statistic; the original's own per-test throughput ratios were
   **7.8-12.1×** (its `worst_15`). Like-for-like growth is ~10× → 23×, and the
   growth is dominated by an asymmetric host penalty: on identical test names,
   disk-bound categories run 6.8-7.9× slower here than in the original
   (loop-device 4K random reads) while the RAM-served DIFF_MAX runs only ~3×
   slower — a RAM/disk ratio mechanically inflates. My "1.4× host penalty" was
   measured on cycle time and sequential I/O and does not describe random reads.
2. **Internal contradiction struck**: my results doc speculated the original
   compacted arm carried un-compacted pre-run writes; the pre-registration
   records the operator stating the original also compacted after pre-runs.
   The speculation is removed; the asymmetric-host explanation replaces it.
3. **state-actor is uniform only for leaf reads** (BALANCE spread 1.02×).
   Code-touching opcodes show an SA-side slowdown on distinct-24KB-code modes
   (verified: CALL spread 1.74×, EXTCODESIZE 1.76×, slowest DIFF_MAX ~9.8-10.0
   MGas/s). The cross-arm CALL 2.84× decomposes as ~1.44 (jochemnet fast) ×
   ~1.73 (state-actor's own code-path slowdown). C6 passed as registered, but
   scoped to BALANCE.
4. **C4 shift**: all 50 non-DIFF_MAX ratios (1.100-1.187) sit at or above the
   original's entire band (1.031-1.117) — "reproduced, shifted +3%, no overlap",
   inside the pre-registered σ-widened band. Consistent with the host story.
5. **Documentation errors in my Task 16 doc**, corrected here: the grids were
   effectively ob=False (not "pooled"); B5's correct statistic is **406/406
   report IDs present verbatim in both arms** (I verified: 406/406 in each),
   not "550 common surface tests"; the SA slow-block count difference is
   explained by its extra setup payload, not an anomaly.

## Attacks the data killed (adversary's own, all verified in its transcript)

- Measurement-window asymmetry: `mgas_s == gas/duration` bit-exact both arms;
  spot-check BALANCE/DIFF_MAX@200M: jochemnet 464 ms vs state-actor 11,824 ms
  on the same step with identical `gas_used`.
- Fixture-workload differences: `gas_used` identical for **all 1,461**
  same-named tests across arms, zero mismatches.
- Absent-key fast path: killed three ways — NON_EXISTING on jochemnet is slow
  (17-20 MGas/s, 4 GB reads); DIFF_MAX code opcodes read 2.2-2.3 GB of real,
  distinct code; EXTCODEHASH shows the same 23× with zero disk.
- Setup-step warming: setup is one ~537 kgas deployment in both arms; if it
  touched the targets both arms would be fast — state-actor is not.

## Final claim table

| Report claim | Verdict | Evidence |
| --- | --- | --- |
| DIFF_MAX diverges massively; 13 other categories agree | **REPRODUCED** | 23.1× vs a 1.100-1.187 band (50/50 categories); original per-test was 7.8-12.1× |
| state-actor uniform, jochemnet anomalous | **REPRODUCED, qualified** | exact for leaf opcodes (SA spread 1.02×); SA has its own 1.74× code-path slowdown on 24KB-distinct-code modes |
| Root cause: journal shipped in the snapshot (provenance artifact) | **SHARPENED** | journal-residency confirmed by measurement (12.6 kB/Mgas vs 19 MB/Mgas; 1463/1463 journal loads; leaf-vs-code split). Correction: the operative journal is the pre-run's deterministic rewrite (380.15 MiB/4248 — in the original too, per its own published pair), not the shipped 265.6 MiB file |
| Agreement band 1.031-1.117 | **REPRODUCED in structure** | shifted to 1.100-1.187 (host-dependent absolute), inside the pre-registered band |
| Instrumentation defects (neg. execution_ms, constant state counters, dead caches) | **REPRODUCED, all three** | 54%/20% negative `execution_ms`; `(accounts=4,code=0)` top bucket; 0/7047 nonzero cache counters |
| 7.71× headline magnitude | **UNDERSTATED by its own data** | slope stat vs its 7.8-12.1× per-test ratios; our 20.6-25.5× additionally inflated by asymmetric host I/O |
| Anomaly extends beyond the report's fixture set | **NEW** | EXTCODEHASH DIFF_MAX ~23× (leaf-only), CALL-family ~2.8× (code-diluted) |

## The discriminating experiment (next step)

Never run, and it settles causality in minutes: re-run a small jochemnet
DIFF_MAX subset with `triedb/merkle.journal` **deleted** from the baseline
before boot. Journal-residency predicts DIFF_MAX collapses to ~19 MGas/s with
~4 GB disk reads; "property of the state itself" predicts it stays ~390.
Secondary follow-ups: state-actor on jochemnet's bundle (the report's own
flagged confound-removal), and a raw-device schelk host to kill the asymmetric
I/O penalty.
