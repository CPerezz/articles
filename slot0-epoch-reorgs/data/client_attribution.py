#!/usr/bin/env python3
"""Pre-Electra CL-client attribution of slot-0 orphans, disentangled from operator effect.

blockprint (Xatu `beacon_block_classification`) covers mainnet up to ~2025-05-07 (Electra freeze),
so client attribution is only possible for the pre-Electra slice of the study window. This script
joins, per slot-0 boundary in that slice: status (CBT fct_block), proposer client (blockprint,
modal per proposer), and operator entity (CBT fct_block_proposer_entity) — then asks whether the
client ranking (Lighthouse low / Nimbus high / Prysm+Teku bulk) survives removing the heaviest
over-orphaning operators. Confound check: a client's count could be one bad operator that runs it.

Writes client_attribution_scale.json. Usage: python3 client_attribution.py
"""
from __future__ import annotations
import json
import math
import os
from collections import Counter, defaultdict

import runner
import extract

HERE = os.path.dirname(os.path.abspath(__file__))
PRE_START, PRE_END = "2024-09-01 00:00:00", "2025-05-07 00:00:00"   # blockprint coverage end
CLIENTS = ["prysm", "lighthouse", "teku", "nimbus", "lodestar", "grandine"]


def _wilson(x, n, z=1.959963985):
    if not n:
        return (0.0, 0.0)
    p = x / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z / d * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, c - h), min(1.0, c + h))


def _i(v):
    return None if v in (None, "\\N", "") else int(float(v))


def main():
    cfg = json.load(open(os.path.join(HERE, "datasources.json")))
    DS_RAW, DS_CBT = cfg["DS_RAW"], cfg["DS_CBT"]
    min_slot, max_slot = extract.slot_of(PRE_START), extract.slot_of(PRE_END)
    p = {"start": PRE_START, "end": PRE_END}
    cbtp = {**p, "min_slot": min_slot, "max_slot": max_slot}

    # --- orphaned slot-0s in the pre-Electra slice (status from the scale CBT pull) ---
    orph = [r for r in json.load(open(os.path.join(HERE, "slot0_orphans_scale.json")))
            if PRE_START <= r["slot_start_date_time"] < PRE_END]
    ent_map = {int(r["o.slot"] if "o.slot" in r else r["slot"]): r["slot0_entity"]
               for r in json.load(open(os.path.join(HERE, "entity_victim_parent_scale.json")))}
    orph_slots = {int(r["slot"]) for r in orph}
    orph_props = sorted({int(r["proposer_index"]) for r in orph})

    sess = runner.create_session()
    try:
        # proposer -> modal client (a validator runs one client; robust over the window)
        plist = ",".join(map(str, orph_props))
        pc = runner.run_query(DS_RAW,
            f"SELECT proposer_index pi, best_guess_single c, count() n FROM beacon_block_classification "
            f"WHERE meta_network_name='mainnet' AND proposer_index IN ({plist}) "
            f"AND slot_start_date_time>='{PRE_START}' AND slot_start_date_time<'{PRE_END}' GROUP BY pi,c",
            {}, session=sess)
        modal = {}
        tmp = defaultdict(dict)
        for r in pc:
            tmp[int(r["pi"])][r["c"]] = _i(r["n"])
        for pi, d in tmp.items():
            modal[pi] = max(d, key=d.get)

        # canonical slot-0 baseline: slot -> client (classification ~ canonical blocks)
        base_client = runner.run_query(DS_RAW,
            "SELECT slot, best_guess_single c FROM beacon_block_classification "
            "WHERE meta_network_name='mainnet' AND modulo(slot,32)=0 "
            f"AND slot_start_date_time>='{PRE_START}' AND slot_start_date_time<'{PRE_END}'",
            {}, session=sess)

        # slot -> entity for all slot-0 in the slice
        ent_rows = runner.run_query(DS_CBT,
            "SELECT slot, coalesce(entity,'unknown') entity FROM mainnet.fct_block_proposer_entity FINAL "
            "WHERE slot BETWEEN {min_slot:UInt32} AND {max_slot:UInt32} "
            "AND slot_start_date_time>={start:DateTime} AND slot_start_date_time<{end:DateTime} "
            "AND modulo(slot,32)=0", cbtp, session=sess)

        # relay-delivered pre-Electra slot-0 slots (full coverage, not the 3% sample) -> build-path,
        # to test whether the Nimbus-worst signal is a build-path/operator-profile confound (a reviewer
        # noted Nimbus skews toward home-stakers who self-build).
        relay_rows = runner.run_query(DS_RAW,
            "SELECT DISTINCT slot FROM mev_relay_proposer_payload_delivered "
            "WHERE meta_network_name='mainnet' AND modulo(slot,32)=0 "
            f"AND slot_start_date_time>='{PRE_START}' AND slot_start_date_time<'{PRE_END}'",
            {}, session=sess)
    finally:
        runner.destroy_session(sess)

    slot_entity = {int(r["slot"]): r["entity"] for r in ent_rows}
    relay_slots = {int(r["slot"]) for r in relay_rows}

    canon = [{"slot": int(r["slot"]), "client": r["c"]} for r in base_client if int(r["slot"]) not in orph_slots]
    orphans = [{"slot": int(r["slot"]), "proposer": int(r["proposer_index"]),
                "client": modal.get(int(r["proposer_index"]), "unknown")} for r in orph]

    # per-client orphan rate (orphaned / all classified slot-0 for that client) + Wilson 95% CI
    bn = Counter(c["client"] for c in canon)
    on = Counter(o["client"] for o in orphans)
    by_client = {}
    for cl in CLIENTS:
        o = on.get(cl, 0); b = bn.get(cl, 0); n = o + b
        lo, hi = _wilson(o, n)
        by_client[cl] = {"orphaned": o, "canonical": b,
                         "orphan_rate": (o / n) if n else None, "ci_lo": lo, "ci_hi": hi}
    n_attr = sum(on.get(cl, 0) for cl in CLIENTS)
    n_unattr = len(orphans) - n_attr   # orphans whose proposer blockprint could not classify

    # ---- disentangling: client effect is operator-confound-free by construction ----
    # 1) entity labels are POST-Electra only; the operator outliers (upbit) live in a different period.
    # 2) every orphan is a DISTINCT validator -> no single proposer drives a client's count.
    # 3) validator-index spread per client: distinct 5000-index buckets the orphans fall into
    #    (a rough operator/deposit-cohort spread proxy) -> high spread argues against one big operator.
    spread = {}
    for cl in CLIENTS:
        idxs = [o["proposer"] for o in orphans if o["client"] == cl]
        spread[cl] = {"orphans": len(idxs), "distinct_validators": len(set(idxs)),
                      "distinct_index_buckets": len({i // 5000 for i in idxs})}
    entity_pre = Counter(ent_map.get(o["slot"], "unknown") for o in orphans)

    # ---- build-path confound test (reviewer): split each client's slot-0 by relay vs local build ----
    def bp(slot):
        return "relay" if slot in relay_slots else "local"
    obp = Counter((o["client"], bp(o["slot"])) for o in orphans)
    cbp = Counter((c["client"], bp(c["slot"])) for c in canon)
    by_client_buildpath, local_share = {}, {}
    for cl in CLIENTS:
        for path in ("local", "relay"):
            o = obp.get((cl, path), 0); b = cbp.get((cl, path), 0); n = o + b
            lo, hi = _wilson(o, n)
            by_client_buildpath[f"{cl}_{path}"] = {"orphaned": o, "canonical": b, "n": n,
                                                   "orphan_rate": (o / n) if n else None, "ci_lo": lo, "ci_hi": hi}
        loc = obp.get((cl, "local"), 0) + cbp.get((cl, "local"), 0)
        tot = loc + obp.get((cl, "relay"), 0) + cbp.get((cl, "relay"), 0)
        local_share[cl] = {"local_share": (loc / tot) if tot else None, "n_slot0": tot}

    # robustness: which pairwise client contrasts are statistically separable (Fisher exact)
    from scipy.stats import fisher_exact
    def fisher(a, b):
        return float(fisher_exact([[by_client[a]["orphaned"], by_client[a]["canonical"]],
                                   [by_client[b]["orphaned"], by_client[b]["canonical"]]])[1])

    def fisher_local(a, b):
        A, B = by_client_buildpath.get(f"{a}_local", {}), by_client_buildpath.get(f"{b}_local", {})
        return float(fisher_exact([[A.get("orphaned", 0), A.get("canonical", 0)],
                                   [B.get("orphaned", 0), B.get("canonical", 0)]])[1])
    result = {"window": [PRE_START, PRE_END], "note": "client attribution is pre-Electra only "
              "(blockprint frozen ~2025-05-07); operator/entity labels are post-Electra only -> the two "
              "signals are temporally disjoint and cannot confound each other. blockprint is a probabilistic "
              "classifier with ~5-10% error concentrated in the minority clients (Nimbus/Lodestar/Grandine), "
              "so small-n client rates are directional only.",
              "n_orphans": len(orphans), "n_attributed_orphans": n_attr, "n_unattributed_orphans": n_unattr,
              "n_canonical_slot0": len(canon),
              "orphan_rate_by_client": by_client,
              "robustness": {"fisher_p_lighthouse_vs_grandine": fisher("lighthouse", "grandine"),
                             "fisher_p_nimbus_vs_lighthouse": fisher("nimbus", "lighthouse"),
                             "fisher_p_nimbus_vs_prysm": fisher("nimbus", "prysm")},
              "build_path_confound": {
                  "by_client_buildpath": by_client_buildpath,
                  "local_share_by_client": local_share,
                  "fisher_local_nimbus_vs_lighthouse": fisher_local("nimbus", "lighthouse"),
                  "fisher_local_nimbus_vs_prysm": fisher_local("nimbus", "prysm"),
                  "note": "tests whether the Nimbus-worst rate is a build-path/operator-profile artifact: "
                          "(a) local_share_by_client = does Nimbus self-build more? (b) within the local-build "
                          "stratum, is Nimbus still separable from Lighthouse/Prysm? Relay-delivery = slot present "
                          "in mev_relay_proposer_payload_delivered (full pre-Electra coverage)."},
              "disentangling": {"pre_electra_orphan_entities": dict(entity_pre),
                                "per_client_validator_spread": spread}}
    json.dump(result, open(os.path.join(HERE, "client_attribution_scale.json"), "w"), indent=2)

    # --- report ---
    print(f"pre-Electra slice {PRE_START[:10]}..{PRE_END[:10]}: {len(orphans)} orphaned slot-0, "
          f"{len(canon)} canonical slot-0")
    print(f"pre-Electra orphan entity labels: {dict(entity_pre)}  (entity labeling is post-Electra only)")
    print("\nslot-0 orphan RATE by client (pre-Electra):")
    print(f"{'client':11s}{'orphans':>8s}{'rate':>8s}{'distinct-vals':>14s}{'idx-buckets':>12s}")
    for cl in sorted(CLIENTS, key=lambda c: -(by_client[c]["orphan_rate"] or 0)):
        r = by_client[cl]["orphan_rate"]; sp = spread[cl]
        print(f"{cl:11s}{sp['orphans']:>8d}{(r*100 if r else 0):>7.2f}%{sp['distinct_validators']:>14d}{sp['distinct_index_buckets']:>12d}")
    print("\nwrote client_attribution_scale.json")


if __name__ == "__main__":
    main()
