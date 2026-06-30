#!/usr/bin/env python3
"""Statistics for the slot-0 epoch-boundary reorg study (scipy/numpy only).

Reads the JSON datasets written by extract.py for a given --label and writes
summary_<label>.json with: per-position orphan rates + Wilson 95% CIs, the slot-0-vs-pooled-rest
test (Fisher exact + chi2 + risk ratio with delta-method CI), the three effect-size metrics,
per-entity excess-over-own-baseline with Wilson CIs, and daily MAD anomaly flags.

Wald is invalid at these rates (~0.1-1%) -> Wilson everywhere. statsmodels/sklearn are NOT
installed; the scale-only logistic model (scipy.optimize MLE + bootstrap) is added later.

Usage:  python3 analyze.py --label janspike
"""
from __future__ import annotations
import argparse
import json
import math
import os

import numpy as np
from scipy.stats import fisher_exact, chi2_contingency, mannwhitneyu

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name: str):
    p = os.path.join(HERE, f"{name}.json")
    return json.load(open(p)) if os.path.exists(p) else None


# query_raw returns TSV strings; NULL is '\N' (older runs) or None (after the runner fix).
def _f(v):
    return None if v in (None, "\\N", "") else float(v)


def _i(v):
    return None if v in (None, "\\N", "") else int(float(v))


def _slot_sdt(name: str) -> dict:
    """slot -> slot_start_date_time 'YYYY-MM-DD HH:MM:SS' (for era covariate + within-era splits)."""
    return {int(r["slot"]): r.get("slot_start_date_time")
            for r in (_load(name) or []) if r.get("slot") is not None and r.get("slot_start_date_time")}


def _month_idx(sdt: str) -> int:
    return (int(sdt[:4]) - 2024) * 12 + int(sdt[5:7])


def _relay_delivered_map(name: str) -> dict:
    """slot -> 1 if a relay delivered the payload (relays_delivered non-empty), else 0. Uses the
    CORRECT column (relays_delivered), not the broken no_relay_delivery."""
    return {int(r["slot"]): (0 if r.get("relays_delivered") in (None, "[]", "\\N", "") else 1)
            for r in (_load(name) or []) if r.get("kind") == "slot0"}


def _slot_col_map(name: str, col: str) -> dict:
    """slot -> integer column value from a CBT per-block dataset (slot0_orphans / canon_slot0)."""
    return {int(r["slot"]): _i(r.get(col)) for r in (_load(name) or []) if _i(r.get(col)) is not None}


def wilson_ci(x: int, n: int, z: float = 1.959963985) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = x / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z / d * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, c - h), min(1.0, c + h))


def per_position(q4: list) -> dict:
    """q4 rows: position_in_epoch, total_slots, orphaned, orphan_rate, count_vs_avg."""
    rows = sorted(q4, key=lambda r: _i(r["position_in_epoch"]))
    out = []
    for r in rows:
        x, n = _i(r["orphaned"]), _i(r["total_slots"])
        lo, hi = wilson_ci(x, n)
        out.append({"pos": _i(r["position_in_epoch"]), "orphaned": x, "total": n,
                    "rate": x / n if n else 0.0, "ci_lo": lo, "ci_hi": hi,
                    "count_vs_avg": _f(r["count_vs_avg"])})
    return {"positions": out}


def slot0_vs_rest(q4: list) -> dict:
    by = {_i(r["position_in_epoch"]): r for r in q4}
    if 0 not in by:
        return {"error": "no position 0 in q4"}
    x0, n0 = _i(by[0]["orphaned"]), _i(by[0]["total_slots"])
    xr = sum(_i(r["orphaned"]) for p, r in by.items() if p != 0)
    nr = sum(_i(r["total_slots"]) for p, r in by.items() if p != 0)
    if x0 == 0 or xr == 0:
        return {"x0": x0, "n0": n0, "xr": xr, "nr": nr, "note": "zero cell -> RR undefined; report counts"}
    _, p_fisher = fisher_exact([[x0, n0 - x0], [xr, nr - xr]], alternative="greater")
    chi2, p_chi, *_ = chi2_contingency([[x0, n0 - x0], [xr, nr - xr]], correction=True)
    p0, pr = x0 / n0, xr / nr
    rr = p0 / pr
    se = math.sqrt((1 - p0) / x0 + (1 - pr) / xr)
    # three effect metrics
    mean_per_pos = sum(_i(r["orphaned"]) for r in q4) / len(q4)
    return {"x0": x0, "n0": n0, "xr": xr, "nr": nr,
            "slot0_rate": p0, "rest_rate": pr,
            "risk_ratio": rr, "rr_ci": [rr * math.exp(-1.96 * se), rr * math.exp(1.96 * se)],
            "count_vs_avg_slot0": x0 / mean_per_pos if mean_per_pos else None,
            "fisher_p": p_fisher, "chi2_p": p_chi}


def entity_excess(qattr2: list, top_n: int = 20) -> dict:
    out = []
    for r in qattr2:
        x, n = _i(r["slot0_orphaned"]), _i(r["slot0_blocks"])
        lo, hi = wilson_ci(x, n)
        out.append({"entity": r["entity"], "slot0_blocks": n, "slot0_orphaned": x,
                    "slot0_rate": x / n if n else 0.0, "ci_lo": lo, "ci_hi": hi,
                    "baseline_rate": _f(r["baseline_orphan_rate"]),
                    "excess": _f(r["slot0_excess"])})
    ranked = sorted([e for e in out if e["excess"] is not None and e["slot0_blocks"] >= 50],
                    key=lambda e: e["excess"], reverse=True)
    return {"all": out, "ranked_top": ranked[:top_n]}


def daily_anomalies(daily: list, k: float = 3.5) -> dict:
    """MAD-based anomaly flag on the daily slot-0 orphan rate."""
    rows = sorted(daily, key=lambda r: r["day"])
    rates = np.array([(_i(r["slot0_orphaned"]) / _i(r["slot0_total"])) if _i(r["slot0_total"]) else 0.0
                      for r in rows])
    med = float(np.median(rates))
    mad = float(np.median(np.abs(rates - med))) or 1e-9
    flags = []
    for r, rate in zip(rows, rates):
        z = 0.6745 * (rate - med) / mad
        if z >= k:
            flags.append({"day": r["day"], "slot0_rate": float(rate), "robust_z": float(z),
                          "slot0_orphaned": _i(r["slot0_orphaned"]), "slot0_total": _i(r["slot0_total"])})
    return {"median_rate": med, "mad": mad, "spike_days": flags}


def half_year_trend(daily: list) -> dict:
    """slot-0 vs all-slot orphan rate aggregated by calendar half-year — shows the trend
    that the pooled rate hides (the rate is rising, not steady)."""
    from collections import defaultdict
    b = defaultdict(lambda: [0, 0, 0, 0])  # s0_orph, s0_tot, all_orph, all_tot
    for r in daily:
        y, m = int(r["day"][:4]), int(r["day"][5:7])
        h = f"{y}-H{1 if m <= 6 else 2}"
        b[h][0] += _i(r["slot0_orphaned"]); b[h][1] += _i(r["slot0_total"])
        b[h][2] += _i(r["all_orphaned"]);  b[h][3] += _i(r["all_total"])
    out = {}
    for h in sorted(b):
        so, st, ao, at = b[h]
        out[h] = {"slot0_rate": so / st if st else None, "all_slot_rate": ao / at if at else None,
                  "slot0_orphaned": so, "slot0_total": st}
    return out


def _pctl(vals, q):
    vals = sorted(v for v in vals if v is not None)
    return vals[min(len(vals) - 1, int(len(vals) * q))] if vals else None


def _ecdf(vals, thresholds=(2000, 2500, 3000, 3500, 4000, 4500)):
    """fraction of vals < each threshold (the plotted p2p_p50 column)."""
    vals = [v for v in vals if v is not None]
    return {f"by_{t/1000}s": round(sum(1 for v in vals if v < t) / len(vals), 4) for t in thresholds} if vals else {}


def propagation_compare(label: str) -> dict:
    """Mechanism: orphaned slot-0 blocks vs canonical slot-0 blocks — own first-seen time (p2p_p50,
    the column the figure plots). Adds the ECDF (so prose cites the right column) and a within-era
    split (the canonical cohort is time-stratified while orphans skew late -> show the gap holds
    within each era, so it is not a secular-propagation-trend artifact)."""
    op = {int(r["slot"]): _i(r.get("p2p_p50")) for r in (_load(f"slot0_propagation_{label}") or []) if _i(r.get("p2p_p50")) is not None}
    cp = {int(r["slot"]): _i(r.get("p2p_p50")) for r in (_load(f"slot0_propagation_canon_{label}") or []) if _i(r.get("p2p_p50")) is not None}
    o, c = list(op.values()), list(cp.values())
    out = {"orphaned_n": len(o), "canonical_n": len(c),
           "orphaned_p2p_p50_median_ms": _pctl(o, 0.5), "canonical_p2p_p50_median_ms": _pctl(c, 0.5),
           "orphaned_p90_ms": _pctl(o, 0.9), "canonical_p90_ms": _pctl(c, 0.9),
           "orphaned_ecdf": _ecdf(o), "canonical_ecdf": _ecdf(c)}
    if o and c:
        out["mannwhitney_p_orphaned_later"] = float(mannwhitneyu(o, c, alternative="greater")[1])
    # within-era (half-year) medians, to control the temporal confound descriptively
    so = _slot_sdt(f"slot0_orphans_{label}"); sc = _slot_sdt(f"canon_slot0_{label}")
    def era(sdt):  # half-year bucket label
        return f"{sdt[:4]}-H{1 if int(sdt[5:7]) <= 6 else 2}"
    eras = {}
    for sl, v in op.items():
        if sl in so: eras.setdefault(era(so[sl]), {"orph": [], "canon": []})["orph"].append(v)
    for sl, v in cp.items():
        if sl in sc: eras.setdefault(era(sc[sl]), {"orph": [], "canon": []})["canon"].append(v)
    out["within_era_median_ms"] = {e: {"orphaned": _pctl(d["orph"], 0.5), "n_orph": len(d["orph"]),
                                       "canonical": _pctl(d["canon"], 0.5), "n_canon": len(d["canon"])}
                                   for e, d in sorted(eras.items())}
    return out


def relay_baseline(label: str) -> dict:
    """H4 (corrected): is the slot-0 block relay-delivered, or locally built? Uses relays_delivered
    (the no_relay_delivery column was uniformly 0 and is NOT used). Orphaned slot-0s being far less
    relay-delivered than survivors => disproportionately locally built. Bid-response timing is
    dropped: the bid columns are unreliable at scale (collector-poll, zero for many rows)."""
    def cohort(name):
        rows = [r for r in (_load(name) or []) if r.get("kind") == "slot0"]
        n = len(rows)
        deliv = sum(1 for r in rows if r.get("relays_delivered") not in (None, "[]", "\\N", ""))
        lo, hi = wilson_ci(deliv, n)
        return {"n": n, "relay_delivered": deliv, "locally_built": n - deliv,
                "relay_delivered_frac": deliv / n if n else None,
                "locally_built_frac": (n - deliv) / n if n else None,
                "relay_delivered_ci": [lo, hi]}
    return {"orphaned": cohort(f"relay_bid_timing_{label}"),
            "canonical": cohort(f"relay_bid_timing_canon_{label}")}


def parent_attestation(label: str) -> dict:
    """H2 (attestation aspect): what fraction of each parent's eventual head-voters voted by Ns?"""
    rows = _load(f"slot31_attest_support_{label}") or []
    fr = {2: [], 3: [], 4: []}
    for r in rows:
        va = _i(r.get("voters_all"))
        if not va:
            continue
        for s in (2, 3, 4):
            v = _i(r.get(f"voters_{s}s"))
            if v is not None:
                fr[s].append(v / va)
    return {"n_parents": len(rows),
            "median_frac_by_2s": _pctl(fr[2], 0.5), "median_frac_by_3s": _pctl(fr[3], 0.5),
            "median_frac_by_4s": _pctl(fr[4], 0.5),
            "parents_under_50pct_by_3s": sum(1 for x in fr[3] if x < 0.5)}


def _logit_fit(X, y):
    """Plain logistic MLE via Newton-CG with the analytic gradient + Hessian (statsmodels absent).
    The analytic derivatives are essential — BFGS without them fails to converge on imbalanced
    case-control data. SEs from the inverse observed-information (Hessian)."""
    from scipy.optimize import minimize
    X = np.asarray(X, float); y = np.asarray(y, float)

    def _p(b):
        return 1.0 / (1.0 + np.exp(-np.clip(X @ b, -35, 35)))

    def nll(b):
        z = X @ b
        return -np.sum(y * z - np.logaddexp(0.0, z))

    def grad(b):
        return X.T @ (_p(b) - y)

    def hess(b):
        p = _p(b); w = p * (1 - p)
        return (X * w[:, None]).T @ X

    res = minimize(nll, np.zeros(X.shape[1]), jac=grad, hess=hess, method="Newton-CG")
    try:
        cov = np.linalg.inv(hess(res.x))
        se = np.sqrt(np.clip(np.diag(cov), 0, None))
    except np.linalg.LinAlgError:
        se = None
    return res.x, se


def logistic_block_lateness(label: str, winsor_ms: int = 12000) -> dict:
    """Case-control logistic: orphaned ~ log10(block_first_seen) + relay_delivered + era, over the
    slot-0 sample (all orphaned vs the canonical sample). Case-control preserves odds ratios; the
    intercept is biased by the sampling fraction (don't interpret it).

    Corrections vs the first version: (1) relay is the CORRECT delivered signal (relays_delivered),
    which now has real variance and stays in the model -- so the lateness OR is genuinely adjusted
    for local-vs-relay build; (2) first-seen is WINSORIZED at one slot (12s) before standardizing,
    because physically-impossible >12s 'first-seen' outliers (root-collisions) otherwise inflate the
    sd ~2.6x and bias the per-sd OR toward null; (3) an era (month) covariate controls the temporal
    confound (orphans skew late, the canonical sample is time-uniform). The lateness OR is also
    reported per DOUBLING of first-seen (scale-free, the interpretable unit)."""
    def firstseen(name):
        return {int(r["slot"]): _i(r.get("p2p_p50")) for r in (_load(name) or []) if _i(r.get("p2p_p50")) is not None}
    fo, fc = firstseen(f"slot0_propagation_{label}"), firstseen(f"slot0_propagation_canon_{label}")
    ro, rc = _relay_delivered_map(f"relay_bid_timing_{label}"), _relay_delivered_map(f"relay_bid_timing_canon_{label}")
    so, sc = _slot_sdt(f"slot0_orphans_{label}"), _slot_sdt(f"canon_slot0_{label}")
    bo, bc = _slot_col_map(f"slot0_orphans_{label}", "blob_count"), _slot_col_map(f"canon_slot0_{label}", "blob_count")
    rows = []  # (first_seen_ms, relay_delivered, month_idx, blob_count, y)
    for sl, fs in fo.items():
        if sl in ro and sl in so and sl in bo:
            rows.append((fs, ro[sl], _month_idx(so[sl]), bo[sl], 1))
    for sl, fs in fc.items():
        if sl in rc and sl in sc and sl in bc:
            rows.append((fs, rc[sl], _month_idx(sc[sl]), bc[sl], 0))
    if len({r[4] for r in rows}) < 2 or len(rows) < 20:
        return {"note": "insufficient data for logistic", "n": len(rows)}
    fs_raw = np.array([r[0] for r in rows], float)
    n_wins = int((fs_raw > winsor_ms).sum())
    fs_log = np.log10(np.clip(np.minimum(fs_raw, winsor_ms), 1.0, None))
    fs_std = fs_log.std() or 1.0
    fs_z = (fs_log - fs_log.mean()) / fs_std
    relay = np.array([r[1] for r in rows], float)
    era = np.array([r[2] for r in rows], float)
    era_z = (era - era.mean()) / (era.std() or 1.0)
    blob = np.array([r[3] for r in rows], float)
    blob_std = blob.std() or 1.0
    blob_z = (blob - blob.mean()) / blob_std
    y = np.array([r[4] for r in rows])
    # blob_count_z added (reviewer): does block lateness still predict orphaning controlling for
    # blob load, and does blob count predict independently? (the "control for smaller blocks" ask)
    cols = [np.ones(len(rows)), fs_z, relay, era_z, blob_z]
    names = ["intercept", "block_first_seen_z", "relay_delivered", "era_z", "blob_count_z"]
    coef, se = _logit_fit(np.column_stack(cols), y)
    out = {"n": len(rows), "cases_orphaned": int(y.sum()), "controls_canonical": int((1 - y).sum()),
           "winsor_ms": winsor_ms, "n_winsorized": n_wins, "log10_first_seen_sd": float(fs_std),
           "blob_sd": float(blob_std),
           "predictor_note": "OR per +1sd is on the winsorized log10 scale; per-doubling is scale-free"}
    for i, nm in enumerate(names):
        o = {"coef": float(coef[i]), "odds_ratio_per_1sd": float(np.exp(coef[i])),
             "se": float(se[i]) if se is not None else None}
        if nm == "block_first_seen_z":
            o["odds_ratio_per_doubling"] = float(np.exp(coef[i] * math.log10(2) / fs_std))
        if nm == "blob_count_z":
            o["odds_ratio_per_blob"] = float(np.exp(coef[i] / blob_std))
        out[nm] = o
    return out


def rr_excluding_day(q4: list, daily: list, day: str) -> dict:
    """Recompute the slot-0-vs-rest RR with one calendar day removed (e.g. the 2026-03-31
    network-wide incident), using the daily series to subtract that day's counts."""
    by = {_i(r["position_in_epoch"]): r for r in q4}
    x0 = _i(by[0]["orphaned"]); n0 = _i(by[0]["total_slots"])
    xr = sum(_i(r["orphaned"]) for p, r in by.items() if p != 0)
    nr = sum(_i(r["total_slots"]) for p, r in by.items() if p != 0)
    d = next((r for r in daily if r["day"] == day), None)
    if not d:
        return {"note": f"day {day} not found"}
    ds0, dt0 = _i(d["slot0_orphaned"]), _i(d["slot0_total"])
    dall, dallt = _i(d["all_orphaned"]), _i(d["all_total"])
    x0 -= ds0; n0 -= dt0
    xr -= (dall - ds0); nr -= (dallt - dt0)   # rest = all - slot0
    p0, pr = x0 / n0, xr / nr
    return {"excluded_day": day, "slot0": f"{x0}/{n0}", "rest": f"{xr}/{nr}", "risk_ratio": p0 / pr}


def blob_compare(label: str) -> dict:
    """Reviewer hypothesis (blobs): are orphaned slot-0 blocks blob-heavier than survivors, and is it
    concentrated in the locally-built path? blob_count = the DA/sidecar propagation burden;
    block_total_bytes is the beacon-block size (does NOT include blob sidecars)."""
    ob = _slot_col_map(f"slot0_orphans_{label}", "blob_count")
    cb = _slot_col_map(f"canon_slot0_{label}", "blob_count")
    obytes = _slot_col_map(f"slot0_orphans_{label}", "block_total_bytes")
    cbytes = _slot_col_map(f"canon_slot0_{label}", "block_total_bytes")
    ro = _relay_delivered_map(f"relay_bid_timing_{label}")
    rc = _relay_delivered_map(f"relay_bid_timing_canon_{label}")

    def stats(vals):
        vals = [v for v in vals if v is not None]
        if not vals:
            return {}
        return {"n": len(vals), "mean": round(sum(vals) / len(vals), 3), "median": _pctl(vals, 0.5),
                "share_ge6": round(sum(1 for v in vals if v >= 6) / len(vals), 4),
                "share_ge9": round(sum(1 for v in vals if v >= 9) / len(vals), 4)}

    def by_build(bmap, rmap):
        return {"local": stats([bmap[s] for s in bmap if rmap.get(s) == 0]),
                "relay": stats([bmap[s] for s in bmap if rmap.get(s) == 1])}

    out = {"orphaned_blobs": stats(list(ob.values())), "canonical_blobs": stats(list(cb.values())),
           "orphaned_bytes_median": _pctl([v for v in obytes.values() if v], 0.5),
           "canonical_bytes_median": _pctl([v for v in cbytes.values() if v], 0.5),
           "orphaned_by_build": by_build(ob, ro), "canonical_by_build": by_build(cb, rc)}
    if ob and cb:
        out["mannwhitney_p_orphaned_more_blobs"] = float(
            mannwhitneyu(list(ob.values()), list(cb.values()), alternative="greater")[1])
    return out


def blob_size_trend(label: str) -> dict:
    """The 'blocks are growing' point: avg blob count + beacon-block bytes by half-year (canonical
    slot-0 sample) — the propagation burden rising alongside the slot-0 reorg rate."""
    rows = _load(f"canon_slot0_{label}") or []
    eras = {}
    for r in rows:
        sdt = r.get("slot_start_date_time")
        if not sdt:
            continue
        e = f"{sdt[:4]}-H{1 if int(sdt[5:7]) <= 6 else 2}"
        d = eras.setdefault(e, {"blobs": [], "bytes": []})
        bc, bz = _i(r.get("blob_count")), _i(r.get("block_total_bytes"))
        if bc is not None:
            d["blobs"].append(bc)
        if bz is not None:
            d["bytes"].append(bz)
    return {e: {"avg_blobs": round(sum(d["blobs"]) / len(d["blobs"]), 3) if d["blobs"] else None,
                "avg_bytes": round(sum(d["bytes"]) / len(d["bytes"]), 0) if d["bytes"] else None,
                "n": len(d["blobs"])}
            for e, d in sorted(eras.items())}


def relay_delay_canonical(label: str) -> dict:
    """Reviewer point: a relay-delivered block's first-seen includes the relay/timing-game delay that
    a locally-built (or post-ePBS) block would not. Among CANONICAL slot-0 (survivors), compare
    first-seen of relay-delivered vs locally-built, and a low-blob cut as a smaller-block/ePBS proxy."""
    fc = {int(r["slot"]): _i(r.get("p2p_p50")) for r in (_load(f"slot0_propagation_canon_{label}") or [])
          if _i(r.get("p2p_p50")) is not None}
    rc = _relay_delivered_map(f"relay_bid_timing_canon_{label}")
    bc = _slot_col_map(f"canon_slot0_{label}", "blob_count")
    relay = [fc[s] for s in fc if rc.get(s) == 1]
    local = [fc[s] for s in fc if rc.get(s) == 0]
    out = {"relay_n": len(relay), "local_n": len(local),
           "relay_median_ms": _pctl(relay, 0.5), "local_median_ms": _pctl(local, 0.5),
           "relay_p90_ms": _pctl(relay, 0.9), "local_p90_ms": _pctl(local, 0.9),
           "relay_ecdf": _ecdf(relay), "local_ecdf": _ecdf(local)}
    if relay and local:
        out["median_delay_ms"] = (out["relay_median_ms"] or 0) - (out["local_median_ms"] or 0)
        out["mannwhitney_p_relay_later"] = float(mannwhitneyu(relay, local, alternative="greater")[1])
    lowblob = [fc[s] for s in fc if bc.get(s) is not None and bc[s] <= 3]
    out["low_blob_canonical_ecdf"] = _ecdf(lowblob)
    out["low_blob_n"] = len(lowblob)
    return out


def blob_by_position(bp: list) -> dict:
    """Reviewer hypothesis (rollups cluster blobs by epoch position, e.g. Arbitrum avoiding slot 0):
    avg canonical blobs per slot%32. Reports slot-0 vs the cross-position mean to test it directly."""
    rows = sorted(bp, key=lambda r: _i(r["position_in_epoch"]))
    avg = {_i(r["position_in_epoch"]): _f(r.get("avg_blobs_canonical")) for r in rows}
    vals = [v for v in avg.values() if v is not None]
    mean_all = sum(vals) / len(vals) if vals else None
    hi = max(avg, key=lambda p: avg[p]) if vals else None
    lo = min(avg, key=lambda p: avg[p]) if vals else None
    return {"slot0_avg_blobs": avg.get(0), "cross_position_mean": round(mean_all, 3) if mean_all else None,
            "max_pos": hi, "max_val": avg.get(hi), "min_pos": lo, "min_val": avg.get(lo),
            "by_position": {p: avg[p] for p in sorted(avg)}}


def analyze(label: str) -> dict:
    summary = {"label": label}
    q4 = _load(f"orphan_by_position_{label}")
    daily = _load(f"daily_orphan_series_{label}")
    if q4:
        summary["per_position"] = per_position(q4)
        summary["slot0_vs_rest"] = slot0_vs_rest(q4)
        if daily:
            # largest-spike day is a network-wide incident; show the RR is robust to removing it
            top = max(daily, key=lambda r: (_i(r["slot0_orphaned"]) / _i(r["slot0_total"])) if _i(r["slot0_total"]) else 0)
            summary["slot0_vs_rest"]["rr_excluding_largest_spike"] = rr_excluding_day(q4, daily, top["day"])
    qattr2 = _load(f"entity_excess_{label}")
    if qattr2:
        summary["entity_excess"] = entity_excess(qattr2)
    if daily:
        summary["daily_anomalies"] = daily_anomalies(daily)
        summary["half_year_trend"] = half_year_trend(daily)
    summary["propagation_compare"] = propagation_compare(label)
    summary["relay_baseline"] = relay_baseline(label)
    summary["parent_attestation"] = parent_attestation(label)
    summary["logistic"] = logistic_block_lateness(label)
    summary["blob_compare"] = blob_compare(label)
    summary["blob_size_trend"] = blob_size_trend(label)
    summary["relay_delay_canonical"] = relay_delay_canonical(label)
    bp = _load(f"blob_by_position_{label}")
    if bp:
        summary["blob_by_position"] = blob_by_position(bp)
    path = os.path.join(HERE, f"summary_{label}.json")
    json.dump(summary, open(path, "w"), indent=2)
    print(f"wrote summary_{label}.json")
    if "slot0_vs_rest" in summary:
        s = summary["slot0_vs_rest"]
        ex = s.get("rr_excluding_largest_spike", {})
        print(f"  slot-0 vs rest: RR={s.get('risk_ratio'):.2f}  fisher_p={s.get('fisher_p'):.1e}"
              f"  RR(excl {ex.get('excluded_day')})={ex.get('risk_ratio'):.2f}")
    pc = summary["propagation_compare"]
    print(f"  block first-seen p50 (ms): orphaned={pc.get('orphaned_p2p_p50_median_ms')} "
          f"canonical={pc.get('canonical_p2p_p50_median_ms')}  orphaned by-4s={pc['orphaned_ecdf'].get('by_4.0s')}")
    rb = summary["relay_baseline"]
    print(f"  relay-delivered: orphaned={rb['orphaned'].get('relay_delivered_frac'):.3f} "
          f"canonical={rb['canonical'].get('relay_delivered_frac'):.3f}")
    lg = summary["logistic"]
    if "block_first_seen_z" in lg:
        print(f"  logistic: OR(lateness,/doubling)={lg['block_first_seen_z']['odds_ratio_per_doubling']:.2f} "
              f"OR(lateness,/1sd)={lg['block_first_seen_z']['odds_ratio_per_1sd']:.2f} "
              f"OR(relay)={lg['relay_delivered']['odds_ratio_per_1sd']:.2f}  (n={lg['n']}, winsor={lg['n_winsorized']})")
    return summary


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="slot-0 reorg statistics")
    ap.add_argument("--label", required=True)
    args = ap.parse_args()
    analyze(args.label)
