#!/usr/bin/env python3
"""Publication figures for the slot-0 epoch-boundary reorg study.
Reads JSON datasets (extract.py) + summary_<label>.json (analyze.py); writes PNG+SVG to
../figures/. Reuses the repo's plot idioms (Agg, dual PNG+SVG @150dpi,
on-figure caveats). Run after extract.py + analyze.py for a given --label.

Usage:  python3 plot.py --label janspike
"""
from __future__ import annotations
import argparse
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "figures"))   # slot0-epoch-reorgs/figures/
os.makedirs(OUT, exist_ok=True)

REST = "#3b6ea5"; SLOT0 = "#c0392b"; SLOT1 = "#e08a2b"; ACCENT = "#6a51a3"
LABEL = ""   # set in __main__; figures are suffixed _{LABEL} so pilots/scale don't overwrite


def _load(name: str):
    p = os.path.join(HERE, f"{name}.json")
    return json.load(open(p)) if os.path.exists(p) else None


def _i(v):  # query_raw values are TSV strings; NULL is '\N' (or None after runner fix)
    return None if v in (None, "\\N", "") else int(float(v))


def save(fig, name):
    fig.tight_layout()
    suffix = f"_{LABEL}" if LABEL else ""
    for ext in ("png", "svg"):
        fig.savefig(f"{OUT}/{name}{suffix}.{ext}", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print("wrote", name + suffix)


def fig_client_orphan_rate(label: str):
    """Pre-Electra slot-0 orphan rate by proposer CL client (blockprint). Label-independent —
    reads client_attribution_scale.json (written by client_attribution.py)."""
    ca = _load("client_attribution_scale")
    if not ca:
        print("skip fig_client_orphan_rate (no client_attribution_scale.json)"); return
    bc = ca["orphan_rate_by_client"]
    items = sorted(((c, v) for c, v in bc.items() if v.get("orphan_rate") is not None),
                   key=lambda kv: kv[1]["orphan_rate"])
    names = [c for c, _ in items]
    rates = [v["orphan_rate"] * 100 for _, v in items]
    ns = [v["orphaned"] for _, v in items]
    lo = np.array([v.get("ci_lo", v["orphan_rate"]) * 100 for _, v in items])
    hi = np.array([v.get("ci_hi", v["orphan_rate"]) * 100 for _, v in items])
    colors = [REST] * len(names)
    if names:
        colors[0] = "#2e7d32"; colors[-1] = SLOT0   # best green, worst red
    # horizontal bars: client names on the y-axis can't collide (the vertical version smeared them together)
    rates = np.array(rates)
    y = np.arange(len(names))
    fig, ax = plt.subplots(figsize=(9, 4.8))
    ax.barh(y, rates, height=0.62, color=colors, zorder=3,
            xerr=[np.clip(rates - lo, 0, None), np.clip(hi - rates, 0, None)],
            capsize=4, error_kw={"lw": 1.0})
    ax.set_yticks(y); ax.set_yticklabels([n.capitalize() for n in names], fontsize=11)
    xmax = float(max(hi)) * 1.32
    ax.set_xlim(0, xmax)
    for yi, r, h, n in zip(y, rates, hi, ns):
        ax.text(h + xmax * 0.012, yi, f"{r:.2f}%   n={n}", va="center", ha="left", fontsize=8.5, color="#333")
    ax.set_xlabel("slot-0 orphan rate  (%)")
    ax.set_title("slot-0 orphan rate by proposer CL client  (pre-Electra, 2024-09 → 2025-05)")
    ax.grid(axis="x", ls=":", alpha=.5)
    ax.text(0.0, -0.26,
            "blockprint via Xatu (frozen after Electra); whiskers = Wilson 95% CI; n = orphaned slot-0 count.\n"
            "Only Nimbus-worst is robust (Fisher p≈3e-19 vs Lighthouse, ~3e-8 vs Prysm); Lighthouse & Grandine\n"
            "overlap (p=0.69); Lodestar (n=5) uninformative. 342 of 371 orphans classified; Prysm+Teku dominate the count.",
            transform=ax.transAxes, ha="left", va="top", fontsize=7.5, color="#555")
    save(fig, "fig_client_orphan_rate")


def fig_relay_localbuild(label: str):
    """Corrected H4: orphaned slot-0s are far less relay-delivered (more locally built) than survivors."""
    summ = _load(f"summary_{label}")
    if not summ or "relay_baseline" not in summ:
        print("skip fig_relay_localbuild (no summary)"); return
    rb = summ["relay_baseline"]
    cohorts = [("canonical slot-0\n(survived)", rb["canonical"], REST),
               ("orphaned slot-0\n(victims)", rb["orphaned"], SLOT0)]
    fig, ax = plt.subplots(figsize=(7.5, 5))
    for i, (lbl, d, color) in enumerate(cohorts):
        rd = (d["relay_delivered_frac"] or 0) * 100
        ax.bar(i, rd, color=color, label="relay-delivered" if i == 0 else None)
        ax.bar(i, 100 - rd, bottom=rd, color="#bbb", label="locally built" if i == 0 else None)
        ax.text(i, 50, f"{100-rd:.0f}%\nlocal", ha="center", va="center", fontsize=10, fontweight="bold")
        ax.text(i, rd / 2, f"{rd:.0f}%\nrelay", ha="center", va="center", fontsize=9, color="white")
    ax.set_xticks([0, 1]); ax.set_xticklabels([c[0] for c in cohorts])
    ax.set_ylabel("share of slot-0 blocks  (%)"); ax.set_ylim(0, 100)
    ax.set_title("Orphaned slot-0 blocks are disproportionately locally built")
    ax.legend(fontsize=8, loc="upper center", ncol=2)
    ax.text(0.5, -0.13, "relay-delivered = a relay payload_delivered record exists for the slot. Victims are "
            "~62% locally built vs ~11% for survivors — local building at the busy epoch transition is the slow path.",
            transform=ax.transAxes, ha="center", fontsize=7, color="#555")
    save(fig, "fig_relay_localbuild")


def fig_slow_attesters(label: str):
    """The slow-attester tail: across slot-31 parents, the fraction of their eventual head-voters
    observed by t seconds — most of the committee is still unseen at the 3-4s deadline region."""
    rows = _load(f"slot31_attest_support_{label}") or []
    fr3 = []
    for r in rows:
        va = _i(r.get("voters_all")); v3 = _i(r.get("voters_3s"))
        if va and v3 is not None:
            fr3.append(v3 / va)
    if not fr3:
        print("skip fig_slow_attesters (no data)"); return
    fig, ax = plt.subplots(figsize=(9, 5))
    xs = np.sort(np.array(fr3)) * 100; ys = np.arange(1, len(xs) + 1) / len(xs)
    ax.step(xs, ys, where="post", color=ACCENT, lw=2.2)
    ax.axvline(50, color="#444", ls="--", lw=1); ax.text(50, 1.01, "50%", ha="center", fontsize=8, color="#444")
    ax.set_xlabel("fraction of the slot-31 parent's eventual voters seen by 3 s  (%)")
    ax.set_ylabel("cumulative fraction of parents")
    ax.set_title("Attestations arrive slowly on the boundary parent")
    ax.grid(ls=":", alpha=.5)
    ax.text(0.5, -0.16, "ECDF over the slot-31 PARENTS of orphaned slot-0s: how much of each parent's committee had "
            "voted (unaggregated attestations only — a participation proxy) by 3 s. Evidence the attester tail is "
            "non-negligible on the boundary, not a network-wide committee-completion curve.",
            transform=ax.transAxes, ha="center", fontsize=7, color="#555")
    save(fig, "fig_slow_attesters")


def fig_propagation_compare(label: str):
    """The mechanism money-figure: orphaned slot-0 blocks propagate far later than the slot-0
    blocks that survived — ECDF of own first-seen time, victims vs survivors."""
    o = [_i(r.get("p2p_p50")) for r in (_load(f"slot0_propagation_{label}") or [])]
    c = [_i(r.get("p2p_p50")) for r in (_load(f"slot0_propagation_canon_{label}") or [])]
    o = [v / 1000 for v in o if v is not None]; c = [v / 1000 for v in c if v is not None]
    if not o or not c:
        print("skip fig_propagation_orphaned_vs_canonical (no data)"); return
    fig, ax = plt.subplots(figsize=(9, 5))
    for data, color, lbl in [(c, REST, f"canonical slot-0 — survived (n={len(c)})"),
                             (o, SLOT0, f"orphaned slot-0 — victims (n={len(o)})")]:
        xs = np.sort(np.array(data)); ys = np.arange(1, len(xs) + 1) / len(xs)
        ax.step(xs, ys, where="post", color=color, lw=2.2, label=lbl)
    for d, cc in [(2, "#444"), (3, ACCENT), (4, "#444")]:
        ax.axvline(d, color=cc, ls="--", lw=1)
        ax.text(d, 1.01, f"{d}s", color=cc, ha="center", fontsize=8)
    ax.set_xlabel("slot-0 block first-seen time  (s into slot, p2p p50)")
    ax.set_ylabel("cumulative fraction of blocks")
    ax.set_xlim(0, 8); ax.set_title("Why slot-0 blocks get orphaned: their own propagation (victims vs survivors)")
    ax.legend(fontsize=9, loc="lower right"); ax.grid(ls=":", alpha=.5)
    ax.text(0.5, -0.16, "ECDF of each slot-0 block's own first-seen time. Survivors land early; victims "
            "land far past the attestation deadline — orphaning is explained by the block's own lateness, "
            "not by being slot-0 per se.", transform=ax.transAxes, ha="center", fontsize=7, color="#555")
    save(fig, "fig_propagation_orphaned_vs_canonical")


def fig_orphan_by_position(label: str):
    summ = _load(f"summary_{label}")
    if not summ or "per_position" not in summ:
        print("skip fig_orphan_by_slot_position (no summary)"); return
    pos = summ["per_position"]["positions"]
    xs = [p["pos"] for p in pos]
    rate = np.array([p["rate"] for p in pos]) * 100
    lo = np.array([p["ci_lo"] for p in pos]) * 100
    hi = np.array([p["ci_hi"] for p in pos]) * 100
    colors = [SLOT0 if x == 0 else SLOT1 if x == 1 else REST for x in xs]
    fig, ax = plt.subplots(figsize=(11, 5))
    # Wilson interval is centered on the adjusted estimate, not the point rate -> clamp to >=0.
    ax.bar(xs, rate, color=colors,
           yerr=[np.clip(rate - lo, 0, None), np.clip(hi - rate, 0, None)],
           capsize=2, error_kw={"lw": .6})
    ax.set_xlabel("position in epoch  (slot % 32)")
    ax.set_ylabel("orphaned-block rate  (%)")
    ax.set_title("Orphaned blocks by position in epoch — slot 0 (red), slot 1 (orange)")
    ax.set_xticks(range(0, 32, 2))
    ax.grid(axis="y", ls=":", alpha=.5)
    s = summ.get("slot0_vs_rest", {})
    if s.get("risk_ratio"):
        ax.text(0.02, 0.95, f"slot-0 RR vs rest = {s['risk_ratio']:.2f}  (Fisher p={s['fisher_p']:.1e})",
                transform=ax.transAxes, fontsize=9, va="top", color=SLOT0, fontweight="bold")
    ax.text(0.5, -0.16,
            f"bars = orphan rate per position over the {label} window; whiskers = Wilson 95% CI. "
            "Victim slot recovered from fct_block.status='orphaned' (not chain_reorg.slot).",
            transform=ax.transAxes, ha="center", fontsize=7, color="#555")
    save(fig, "fig_orphan_by_slot_position")


def fig_slot31_relationship(label: str):
    lat = _load(f"slot31_lateness_{label}")
    if not lat:
        print("skip fig_slot31_lateness_vs_slot0_orphan (no data)"); return
    vals = [_i(r.get("earliest_first_seen_ms")) for r in lat]
    vals = [v for v in vals if v not in (None, 4294967295)]
    if not vals:
        print("skip fig_slot31_lateness_vs_slot0_orphan (no timing values)"); return
    vals = np.array(vals) / 1000.0  # ms -> s
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.hist(vals, bins=40, color=SLOT1, edgecolor="#7a4a10", alpha=.85)
    for d, c in [(2, SLOT0), (3, ACCENT), (4, "#333")]:
        ax.axvline(d, color=c, ls="--", lw=1, label=f"{d}s deadline")
    ax.set_xlabel("slot-31 parent first-seen time  (s into slot)")
    ax.set_ylabel("orphaned slot-0 count")
    ax.set_title("How late was the slot-31 parent of each orphaned slot 0?  (H2)")
    ax.legend(fontsize=8); ax.grid(axis="y", ls=":", alpha=.5)
    ax.text(0.5, -0.16,
            "distribution of the slot-31 parent's earliest first-seen time, over orphaned slot-0s. "
            "Mass to the right of a deadline line = parents that would miss that attestation cutoff.",
            transform=ax.transAxes, ha="center", fontsize=7, color="#555")
    save(fig, "fig_slot31_lateness_vs_slot0_orphan")


def fig_entity_over_representation(label: str):
    summ = _load(f"summary_{label}")
    if not summ or "entity_excess" not in summ:
        print("skip fig_entity_over_representation (no summary)"); return
    ranked = summ["entity_excess"]["ranked_top"][:12]
    if not ranked:
        print("skip fig_entity_over_representation (no entities w/ >=50 slot-0 blocks)"); return
    names = [e["entity"] for e in ranked][::-1]
    excess = [e["excess"] * 100 for e in ranked][::-1]
    rate = np.array([e["slot0_rate"] for e in ranked][::-1]) * 100
    lo = np.array([e["ci_lo"] for e in ranked][::-1]) * 100
    hi = np.array([e["ci_hi"] for e in ranked][::-1]) * 100
    y = np.arange(len(names))
    fig, ax = plt.subplots(figsize=(9, max(4, 0.45 * len(names) + 1)))
    ax.barh(y, excess, color=[SLOT0 if e > 0 else REST for e in excess])
    ax.set_yticks(y); ax.set_yticklabels(names, fontsize=8)
    ax.axvline(0, color="#333", lw=.8)
    ax.set_xlabel("slot-0 orphan rate − entity's own all-slot baseline  (pp)")
    ax.set_title("Which operators over-orphan specifically at slot 0  (entity ≠ CL client)")
    ax.grid(axis="x", ls=":", alpha=.5)
    ax.text(0.5, -0.14 if len(names) > 6 else -0.2,
            "excess of slot-0 orphan rate over each entity's own baseline (controls for entities that "
            "orphan more everywhere); entities with ≥50 slot-0 blocks. Proposer CL client is unattributable "
            "(blockprint frozen pre-Electra), so this is operator-level, not client-level.",
            transform=ax.transAxes, ha="center", fontsize=7, color="#555")
    save(fig, "fig_entity_over_representation")


def fig_timeseries(label: str):
    daily = _load(f"daily_orphan_series_{label}")
    summ = _load(f"summary_{label}")
    if not daily:
        print("skip fig_jan2026_orphan_timeseries (no daily series)"); return
    rows = sorted(daily, key=lambda r: r["day"])
    days = [r["day"] for r in rows]
    slot0 = np.array([(_i(r["slot0_orphaned"]) / _i(r["slot0_total"])) if _i(r["slot0_total"]) else 0 for r in rows]) * 100
    allr = np.array([(_i(r["all_orphaned"]) / _i(r["all_total"])) if _i(r["all_total"]) else 0 for r in rows]) * 100
    x = np.arange(len(days))
    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(x, slot0, color=SLOT0, lw=1.3, label="slot-0 orphan rate")
    ax.plot(x, allr, color=REST, lw=1.0, alpha=.8, label="all-slot orphan rate")
    if summ and "daily_anomalies" in summ:
        da = summ["daily_anomalies"]
        med = da["median_rate"] * 100
        ax.axhline(med, color="#888", ls=":", lw=.8)
        spike_days = {f["day"] for f in da["spike_days"]}
        for i, d in enumerate(days):
            if d in spike_days:
                ax.scatter([i], [slot0[i]], color=SLOT0, zorder=5, s=30)
                ax.annotate(d, (i, slot0[i]), fontsize=7, color=SLOT0,
                            xytext=(0, 6), textcoords="offset points", ha="center")
    step = max(1, len(days) // 12)
    ax.set_xticks(x[::step]); ax.set_xticklabels([days[i] for i in range(0, len(days), step)], rotation=45, fontsize=7, ha="right")
    ax.set_ylabel("orphan rate  (%)"); ax.set_title("Daily orphan rate — slot 0 vs all slots")
    ax.legend(fontsize=8); ax.grid(axis="y", ls=":", alpha=.5)
    ax.text(0.5, -0.28, "dotted = median slot-0 rate; dots = MAD anomaly days (robust-z ≥ 3.5). "
            "The 2026-03-31 spike is a NETWORK-WIDE incident (all-slot rate ~23%), not slot-0-specific; "
            "underneath, the slot-0 rate is rising (≈0.6%→1.7% by half-year). MAD also flags Poisson-noise days.",
            transform=ax.transAxes, ha="center", fontsize=7, color="#555")
    save(fig, "fig_jan2026_orphan_timeseries")


def fig_slot_anatomy(label: str):
    """Schematic explainer: the slot timeline, the candidate attestation deadlines (2/3/4s),
    and where surviving vs orphaned slot-0 blocks actually land — the thesis in one picture."""
    o = sorted(v / 1000 for v in (_i(r.get("p2p_p50")) for r in (_load(f"slot0_propagation_{label}") or [])) if v is not None)
    c = sorted(v / 1000 for v in (_i(r.get("p2p_p50")) for r in (_load(f"slot0_propagation_canon_{label}") or [])) if v is not None)
    if not o or not c:
        print("skip fig_slot_anatomy (no data)"); return

    def pct(a, q): return a[min(len(a) - 1, int(len(a) * q))]
    fig, ax = plt.subplots(figsize=(11, 3.8))
    ax.axvspan(0, 3, color="#2e7d32", alpha=.05); ax.axvspan(3, 6, color=SLOT0, alpha=.05)
    for d, col, lbl in [(2, "#444", "2s\ncandidate"), (3, ACCENT, "3s\ncandidate"), (4, "#333", "4s\ntoday")]:
        ax.axvline(d, color=col, ls="--", lw=1.3, zorder=1)
        ax.text(d, 1.0, lbl, color=col, ha="center", va="bottom", fontsize=8, fontweight="bold")
    for name, a, color, y in [("survivors", c, REST, 0.68), ("victims", o, SLOT0, 0.32)]:
        p10, p50, p90 = pct(a, .1), pct(a, .5), pct(a, .9)
        ax.plot([p10, p90], [y, y], color=color, lw=11, alpha=.35, solid_capstyle="round", zorder=2)
        ax.plot([p50], [y], "o", color=color, ms=13, zorder=3)
        ax.text(p50, y + 0.12, f"median {p50:.1f}s", color=color, ha="center", fontsize=9, fontweight="bold")
    ax.set_yticks([0.32, 0.68]); ax.set_yticklabels(["orphaned\nslot-0", "surviving\nslot-0"], fontsize=9)
    ax.set_ylim(0.05, 1.18); ax.set_xlim(0, 6)
    ax.set_xticks(range(0, 7)); ax.set_xlabel("time into the 12-second slot  (s) — block first-seen  ·  bar = p10–p90, dot = median")
    ax.set_title("Where slot-0 blocks land vs where the deadline could sit", pad=26)
    ax.grid(axis="x", ls=":", alpha=.4)
    ax.text(0.5, -0.30, "Survivors clear the line; victims pile up past 4s. Moving the deadline earlier (3s, 2s) "
            "eats into the survivor margin — 16% of survivors are first-seen after 3s, 61% after 2s. The slot is "
            "12s wide; only the 0–6s decision region is shown.", transform=ax.transAxes, ha="center", fontsize=7, color="#555")
    save(fig, "fig_slot_anatomy")


def fig_epoch_boundary(label: str):
    """Schematic: why the cost lands on slot 0 — slot 31 is fork-choice-protected, so a late
    slot-0 block is the one the next proposer can (and does) reorg."""
    import matplotlib.patches as mpatches
    fig, ax = plt.subplots(figsize=(11, 3.8))
    ax.set_xlim(0, 10); ax.set_ylim(0, 4); ax.axis("off")
    w, h, y = 1.7, 0.95, 1.7
    boxes = [("slot 30", 0.5, REST), ("slot 31", 2.7, "#2e7d32"), ("slot 0", 5.5, SLOT0), ("slot 1", 7.7, REST)]
    cx = {}
    for name, x, color in boxes:
        ax.add_patch(mpatches.Rectangle((x, y), w, h, facecolor=color, edgecolor="#222", lw=1.2, alpha=.88, zorder=2))
        ax.text(x + w / 2, y + h / 2, name, ha="center", va="center", color="white", fontweight="bold", fontsize=12, zorder=3)
        cx[name] = x + w / 2
    bx = (2.7 + w + 5.5) / 2
    ax.axvline(bx, ymin=0.30, ymax=0.66, color="#222", ls="--", lw=1.2)
    ax.text(bx, y - 0.92, "epoch\nboundary", ha="center", va="top", fontsize=7.5, color="#222")
    ax.text(cx["slot 31"], y - 0.30, "PROTECTED\ncan't be honestly reorged", ha="center", va="top", fontsize=8, color="#2e7d32", fontweight="bold")
    ax.text(cx["slot 0"], y - 0.30, "late  →  orphaned", ha="center", va="top", fontsize=8.5, color=SLOT0, fontweight="bold")
    ax.plot([5.5, 5.5 + w], [y, y + h], color="#222", lw=2.2, zorder=4)
    ax.plot([5.5, 5.5 + w], [y + h, y], color="#222", lw=2.2, zorder=4)
    ax.annotate("", xy=(cx["slot 31"], y + h + 0.06), xytext=(cx["slot 1"], y + h + 0.06),
                arrowprops=dict(arrowstyle="-|>", color=ACCENT, lw=1.8, connectionstyle="arc3,rad=0.30"), zorder=5)
    ax.text((cx["slot 31"] + cx["slot 1"]) / 2, y + h + 1.18, "slot-1 proposer builds on slot 31, skipping the late slot 0",
            ha="center", fontsize=8.5, color=ACCENT)
    ax.set_title("Why the cost lands on slot 0: slot 31 is protected, so slot 0 is what gets reorged", fontsize=11)
    ax.text(0.5, 0.02, "The fork-choice rule (get_proposer_head / is_epoch_boundary) forbids honestly reorging the "
            "last slot of an epoch. So when a slot-0 block is late, the slot-1 proposer is free to build on slot 31 "
            "and leave slot 0 behind — the protection pushes the cost one slot forward.",
            transform=ax.transAxes, ha="center", fontsize=7, color="#555")
    save(fig, "fig_epoch_boundary")


def fig_half_year_trend(label: str):
    """The slot-0 rate is rising, not steady: slot-0 vs all-slot orphan rate by calendar half-year."""
    summ = _load(f"summary_{label}")
    if not summ or "half_year_trend" not in summ:
        print("skip fig_half_year_trend (no trend)"); return
    t = summ["half_year_trend"]; halves = sorted(t)
    s0 = [t[h]["slot0_rate"] * 100 for h in halves]
    al = [t[h]["all_slot_rate"] * 100 for h in halves]
    x = np.arange(len(halves)); bw = 0.38
    fig, ax = plt.subplots(figsize=(9, 5))
    b1 = ax.bar(x - bw / 2, s0, bw, color=SLOT0, label="slot-0 orphan rate")
    b2 = ax.bar(x + bw / 2, al, bw, color=REST, label="all-slot orphan rate")
    for b, v in zip(b1, s0): ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.2f}", ha="center", va="bottom", fontsize=8, color=SLOT0, fontweight="bold")
    for b, v in zip(b2, al): ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.2f}", ha="center", va="bottom", fontsize=7, color=REST)
    ax.set_xticks(x); ax.set_xticklabels(halves)
    ax.set_ylabel("orphan rate  (%)")
    ax.set_title("The slot-0 rate is rising, not steady — while the baseline stays flat")
    ax.legend(fontsize=9); ax.grid(axis="y", ls=":", alpha=.5)
    ax.text(0.5, -0.16, "slot-0 orphan rate by calendar half-year vs the all-slot baseline. The slot-0 rate nearly "
            "triples (0.58% → 1.73%) while all-slot stays ~0.15–0.29% — so calibrate the dial to the current regime, "
            "not the 21-month pooled 1.17%.", transform=ax.transAxes, ha="center", fontsize=7, color="#555")
    save(fig, "fig_half_year_trend")


def fig_blob_compare(label: str):
    """Reviewer hypothesis: orphaned slot-0 blocks carry more blobs than survivors."""
    def blobs(name): return [_i(r.get("blob_count")) for r in (_load(name) or []) if _i(r.get("blob_count")) is not None]
    o, c = blobs(f"slot0_orphans_{label}"), blobs(f"canon_slot0_{label}")
    if not o or not c:
        print("skip fig_blob_compare (no blob data)"); return
    buckets = [("0–2", 0, 2), ("3–5", 3, 5), ("6–8", 6, 8), ("9+", 9, 99)]
    def dist(v): return [sum(1 for x in v if lo <= x <= hi) / len(v) * 100 for _, lo, hi in buckets]
    od, cd = dist(o), dist(c)
    x = np.arange(len(buckets)); bw = 0.38
    fig, ax = plt.subplots(figsize=(9.5, 5.2))
    b1 = ax.bar(x - bw / 2, cd, bw, color=REST, label=f"canonical — survived (median {int(np.median(c))} blobs)")
    b2 = ax.bar(x + bw / 2, od, bw, color=SLOT0, label=f"orphaned — victims (median {int(np.median(o))} blobs)")
    for bars, vals in ((b1, cd), (b2, od)):
        for b, v in zip(bars, vals): ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.0f}", ha="center", va="bottom", fontsize=7.5)
    ax.set_xticks(x); ax.set_xticklabels([b[0] for b in buckets])
    ax.set_xlabel("blobs in the block"); ax.set_ylabel("share of slot-0 blocks  (%)")
    ax.set_title("Orphaned slot-0 blocks carry more blobs")
    ax.legend(fontsize=9); ax.grid(axis="y", ls=":", alpha=.5)
    ax.text(0.5, -0.15, "blob count = execution_payload_blob_gas_used / GAS_PER_BLOB. Orphaned slot-0 blocks skew to "
            "more blobs\n(≥9 blobs: 17% vs 9%; Mann-Whitney p≈1e-20) — yet are SMALLER in beacon-block bytes (median "
            "90 vs 114 KB),\nso the burden is the blob sidecars (DA propagation), not block size.",
            transform=ax.transAxes, ha="center", va="top", fontsize=7, color="#555")
    save(fig, "fig_blob_compare")


def fig_blob_by_position(label: str):
    """Test the rollup-clustering folklore: avg blobs by epoch position (it's flat)."""
    bp = _load(f"blob_by_position_{label}")
    if not bp:
        print("skip fig_blob_by_position (no data)"); return
    bp = sorted(bp, key=lambda r: _i(r["position_in_epoch"]))
    xs = [_i(r["position_in_epoch"]) for r in bp]; av = [float(r["avg_blobs_canonical"]) for r in bp]
    fig, ax = plt.subplots(figsize=(11, 4.2))
    ax.bar(xs, av, color=[SLOT0 if x == 0 else REST for x in xs])
    mean = sum(av) / len(av); ax.axhline(mean, color="#333", ls="--", lw=1)
    ax.text(31, mean, f" cross-position mean {mean:.2f}", va="bottom", ha="right", fontsize=8, color="#333")
    ax.set_xlabel("position in epoch  (slot % 32)"); ax.set_ylabel("avg blobs (canonical)")
    ax.set_xticks(range(0, 32, 2)); ax.set_ylim(0, max(av) * 1.18)
    ax.set_title("Blob load is flat across the epoch — slot 0 (red) is not blob-elevated")
    ax.grid(axis="y", ls=":", alpha=.5)
    ax.text(0.5, -0.22, "avg blobs per canonical block by epoch position, 21 months. Slot 0 (3.70) sits at the "
            "cross-position mean (3.72); no clustering\nat slot 0 or slots 20–22 — refuting the 'rollups time blobs by "
            "epoch position' hypothesis. Blob-heavy blocks are orphaned regardless of position.",
            transform=ax.transAxes, ha="center", va="top", fontsize=7, color="#555")
    save(fig, "fig_blob_by_position")


def fig_blob_size_trend(label: str):
    """The 'blocks are growing' point: avg block size + blobs by half-year."""
    s = _load(f"summary_{label}")
    if not s or "blob_size_trend" not in s:
        print("skip fig_blob_size_trend (no trend)"); return
    t = s["blob_size_trend"]; halves = sorted(t)
    kb = [t[h]["avg_bytes"] / 1000 for h in halves]; blobs = [t[h]["avg_blobs"] for h in halves]
    x = np.arange(len(halves))
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.bar(x, kb, 0.5, color=REST, label="avg beacon-block size (KB)", zorder=2)
    for xi, v in zip(x, kb): ax.text(xi, v - 7, f"{v:.0f}", ha="center", va="top", fontsize=8, color="white", fontweight="bold")
    ax.set_ylabel("avg beacon-block size  (KB)", color=REST); ax.tick_params(axis="y", labelcolor=REST)
    ax.set_ylim(0, max(kb) * 1.25)
    ax2 = ax.twinx(); ax2.plot(x, blobs, color=SLOT0, marker="o", lw=2.2, label="avg blobs", zorder=3)
    for xi, v in zip(x, blobs): ax2.text(xi, v + 0.15, f"{v:.1f}", ha="center", va="bottom", fontsize=8, color=SLOT0)
    ax2.set_ylabel("avg blobs", color=SLOT0); ax2.tick_params(axis="y", labelcolor=SLOT0); ax2.set_ylim(0, max(blobs) * 1.4)
    ax.set_xticks(x); ax.set_xticklabels(halves)
    ax.set_title("Blocks are growing — the propagation burden rises with the reorg rate")
    ax.grid(axis="y", ls=":", alpha=.4)
    ax.text(0.5, -0.16, "avg canonical slot-0 beacon-block size and blob count by half-year. Block size grew ~60% "
            "(106→170 KB)\nand the slot-0 reorg rate rose 0.58%→1.73% over the same window — and ePBS removes exactly "
            "this\ngrowing data (payload, blobs, BAL) from the block attesters vote on.",
            transform=ax.transAxes, ha="center", va="top", fontsize=7, color="#555")
    save(fig, "fig_blob_size_trend")


def fig_client_buildpath(label: str):
    """The Nimbus confound test: pre-Electra orphan rate by client × build path."""
    ca = _load("client_attribution_scale")
    if not ca or "build_path_confound" not in ca:
        print("skip fig_client_buildpath (no data)"); return
    bcp = ca["build_path_confound"]["by_client_buildpath"]
    clients = ["lighthouse", "prysm", "teku", "nimbus"]
    local = [(bcp[f"{c}_local"]["orphan_rate"] or 0) * 100 for c in clients]
    relay = [(bcp[f"{c}_relay"]["orphan_rate"] or 0) * 100 for c in clients]
    x = np.arange(len(clients)); bw = 0.38
    fig, ax = plt.subplots(figsize=(9, 5))
    b1 = ax.bar(x - bw / 2, local, bw, color=SLOT0, label="locally built")
    b2 = ax.bar(x + bw / 2, relay, bw, color=REST, label="relay-delivered")
    for bars, vals in ((b1, local), (b2, relay)):
        for b, v in zip(bars, vals): ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.2f}", ha="center", va="bottom", fontsize=8)
    ax.set_xticks(x); ax.set_xticklabels([c.capitalize() for c in clients])
    ax.set_ylabel("slot-0 orphan rate  (%)")
    ax.set_title("Build path dominates — and Nimbus is worst in both (pre-Electra)")
    ax.legend(fontsize=9); ax.grid(axis="y", ls=":", alpha=.5)
    ax.text(0.5, -0.15, "pre-Electra slot-0 orphan rate by client × build path. Locally-built blocks orphan ~5–10× more "
            "than relay-delivered\nfor every client (build path is the dominant axis). Nimbus self-builds at the same "
            "~14% rate as others yet is worst\nin BOTH strata — so its signal is not a build-path artifact "
            "(operator-mix and blockprint minority-client error still apply).",
            transform=ax.transAxes, ha="center", va="top", fontsize=7, color="#555")
    save(fig, "fig_client_buildpath")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="slot-0 reorg figures")
    ap.add_argument("--label", required=True)
    args = ap.parse_args()
    LABEL = args.label
    fig_orphan_by_position(args.label)
    fig_propagation_compare(args.label)
    fig_relay_localbuild(args.label)
    fig_slow_attesters(args.label)
    fig_client_orphan_rate(args.label)
    fig_slot31_relationship(args.label)
    fig_entity_over_representation(args.label)
    fig_timeseries(args.label)
    fig_slot_anatomy(args.label)
    fig_epoch_boundary(args.label)
    fig_half_year_trend(args.label)
    fig_blob_compare(args.label)
    fig_blob_by_position(args.label)
    fig_blob_size_trend(args.label)
    fig_client_buildpath(args.label)
    print("\nfigures ->", OUT)
