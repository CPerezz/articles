#!/usr/bin/env python3
"""Reth state-DB study: every number the article quotes, grouped by the claims C1-C17 of the
verification plan (articles-wt-specs docs/superpowers/plans/2026-10-06-reth-gap-verification.md) and
the cycles C18-C20 of plans 2026-10-08-reth-layout-root-causes.md and 2026-10-13-reth-study-finalize.md.

Runs where the data is (the bench host's /root/bench/reth; RETH_BENCH overrides) and prints JSON:
    tsh ssh CPerezz@stateless-bloatnet-benchmarks 'sudo -n python3 -' < collect_reth.py > data/report_data.json
Raw traces stay on the host. Failed registry checks are listed under "checks" and make the exit code 1,
unless --partial is given (for a campaign still running: missing runs are skipped, not failed)."""
import ast
import datetime
import glob
import json
import math
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from statistics import median

R = os.environ.get("RETH_BENCH", "/root/bench/reth") + "/"
PARTIAL = "--partial" in sys.argv
UTC = datetime.timezone.utc
# exp-dio.sh set loop direct-io for the first time at this instant; every earlier run was buffered.
FIRST_DIO = datetime.datetime(2026, 10, 5, 16, 31, 16, tzinfo=UTC).timestamp()
# rid: (loop direct-io, tests expected). Arm, image and the hashed-reads switch come from cfg/<rid>.yaml.
RUNS = {
    **{r: (0, 266) for r in ("j1", "s1", "j2", "s2")},
    **{r: (0, 66) for r in ("jc", "jh")},
    **{r: (0, 6) for r in ("fj", "fjh", "fs", "ras", "rajh")},
    **{r: (1, 6) for r in ("xfs", "xfjh")},
    **{r: (1, 66) for r in ("xs", "xjh", "xjc", "xs2", "xjh2", "xjc2", "xsr", "xsr2")},
    **{r: (1, 36) for r in ("xse", "xjce", "xse2", "xjhe2", "xjce2", "xser", "xser2")},
    "xjhe": (1, 198),  # its filter lacked value_(160|240)M; only the 36 common tests are scored
    **{r: (1, 266) for r in ("dj1", "ds1", "dj2", "ds2")},
    **{r: (1, 14) for r in ("t2jc", "t2jh", "t2s", "t2sr")},
    "iod": (1, 2), "iob": (0, 2),
    # v2 jochemnet campaign (plan 2026-10-06-reth-v2-state-actor-prs.md): baseline against the original
    # store, then the store regenerated with state-actor PR1+PR2.
    **{r: (1, 6) for r in ("vjsmoke", "fsmoke", "gsmoke")},
    **{r: (1, 266) for r in ("vj1", "vs1", "vj2", "vs2", "fj1", "fs1", "fj2", "fs2", "gj1", "gs1", "gj2", "gs2")},
    **{r: (1, 14) for r in ("t2jv", "t2sf")},
    # Cycle 1 (plan 2026-10-08-reth-layout-root-causes.md): the store regenerated with PR1-PR4, migrated fill.
    **{r: (1, 21) for r in ("t3jg", "t3sg")},
    # Cycle 2: the store regenerated with PR1-PR5 (mainnet storage shape at J's account count); its
    # fixtures refilled by reth on the new genesis. J's store and binary are unchanged, so t3jg serves both.
    "hsmoke": (1, 6), "t3sh": (1, 21),
    **{r: (1, 266) for r in ("hj1", "hs1", "hj2", "hs2")},
    "ksmoke": (1, 6), "t3sk": (1, 21),
    **{r: (1, 266) for r in ("kj1", "ks1", "kj2", "ks2")},
}
DRIVER_STEP = {"ras": "ra", "rajh": "ra"}  # traced inside one driver step
MAPS = {"fj": "fj", "fjh": "fj", "fs": "fs", "t2jc": "t2j", "t2jh": "t2j", "t2s": "t2s", "t2sr": "t2sr",
        "t2jv": "t2jv", "t2sf": "t2sf", "t3jg": "t3jg", "t3sg": "t3sg", "t3sh": "t3sh"}
checks = []


def check(ok, what):
    if not ok:
        checks.append(what)
    return ok


def cfg(rid):
    for p in (f"cfg/{rid}.yaml", f"cfg/{rid.upper()}.yaml"):
        if os.path.exists(R + p):
            y = open(R + p).read()
            return {"arm": "J" if "/schelk-joc/" in y else "S",
                    "image": re.search(r"image: (\S+)", y).group(1),
                    "hashed_reads": "RETH_FORCE_HASHED_READS" in y,
                    "filter": re.search(r"filter: '(.*)'", y).group(1)}
    return None


def key(t):
    # the two fixture sets name the same test differently in their prefix; match on the pytest id
    m = re.search(r"(test_[a-z_]+\[.*\])", t)
    return m.group(1).replace("blockchain_test_engine", "BTE").replace("blockchain_test_stateful_engine", "BTE") if m else t


def agg(e):
    return ((e.get("steps") or {}).get("test") or {}).get("aggregated") or {}


def mg(e):
    a = agg(e)
    g, t = a.get("gas_used_total"), a.get("gas_used_time_total")
    return (g / 1e6) / (t / 1e9) if g and t and not a.get("fail") else None


def secs(e):
    t = agg(e).get("gas_used_time_total")
    return t / 1e9 if t else None


def load(rid):
    best, bn = None, -1
    for rj in glob.glob(R + f"results/{rid}/runs/*/result.json"):
        n = len(json.load(open(rj)).get("tests", {}))
        if n > bn:
            best, bn = rj, n
    if not best:
        return None
    return {"tests": {key(t): (t, e) for t, e in json.load(open(best))["tests"].items()},
            "epoch": int(os.path.basename(os.path.dirname(best)).split("_")[0]),
            "path": os.path.relpath(best, R)}


def driver_dio():
    d = {}
    for f in ("logs/exp-dio.out", "logs/exp-dio2.out", "logs/verify.out", "logs/v2.out", "logs/v2b.out", "logs/fix.out", "logs/g.out",
              "logs/stage4.out", "logs/stage5.out"):
        if not os.path.exists(R + f):
            continue
        cur = None
        for line in open(R + f, errors="ignore"):
            m = re.match(r"== (\S+) ", line)
            if m:
                cur = m.group(1)
                continue
            m = re.match(r"(\S+) ok dio loop1=(\d) loop3=(\d)", line)
            if m:
                d[m.group(1)] = (int(m.group(2)), int(m.group(3)))
                continue
            m = re.match(r"dio loop1=(\d) loop3=(\d)", line)
            if m and cur and cur not in d:
                d[cur] = (int(m.group(1)), int(m.group(2)))
    return d


def category(t):
    fam = re.search(r"::(test_[a-z_]+)\[", t) or re.search(r"(test_[a-z_]+)\[", t)
    fam = fam.group(1) if fam else t
    mode = re.search(r"account_mode_AccountMode\.([A-Z_]+)", t)
    op = re.search(r"opcode_([A-Z0-9]+)", t)
    if fam == "test_account_access" and mode:
        return "%s %s" % (op.group(1) if op else "?", mode.group(1))
    return fam.replace("test_", "")


def group(t):
    """Finer than category: the test's own parameters, for per-cell tables."""
    p = re.search(r"\[(.*)\]", t).group(1)
    p = re.sub(r"fork_Amsterdam-(BTE|blockchain_test_(stateful_)?engine)-|cache_strategy_CacheStrategy\.NO_CACHE-|"
               r"benchmark-gas-value_|account_mode_AccountMode\.|overhead_baseline_", "", p)
    return category(t).split(" ")[0] + " " + p if "test_account_access" in t else category(t) + " " + p


def stats(xs):
    xs = [x for x in xs if x]
    if not xs:
        return None
    return {"n": len(xs), "median": round(median(xs), 4), "within10": sum(abs(x - 1) <= 0.10 for x in xs),
            "min": round(min(xs), 4), "max": round(max(xs), 4)}


def windows(rid):
    """Measured test steps in benchmarkoor's log: (start, end, full test name), in run order."""
    out, cur = [], None
    p = R + f"logs/{rid}.log"
    if not os.path.exists(p):
        return out
    for line in open(p, errors="ignore"):
        line = re.sub(r"\x1b\[[0-9;]*m", "", line)
        m = re.search(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+)Z\s+\w+\s+\|\s+(Running test step|Test completed successfully|Test failed).*?test=(\S+)", line)
        if not m:
            continue
        t = datetime.datetime.fromisoformat(m.group(1)).replace(tzinfo=UTC).timestamp()
        if m.group(2) == "Running test step":
            cur = (t, m.group(3))
        elif cur:
            out.append((cur[0], t, cur[1]))
            cur = None
    return out


def label(lab):
    # mdbxmap walks main trees only; leaf/branch pages with 34-36-byte keys are the nested dup
    # subtrees of HashedStorages / PlainStorageState
    if lab.startswith("unmapped:leaf:k3") or lab.startswith("unmapped:leaf:k2"):
        return "dupsub:leaf"
    if lab.startswith("unmapped:branch"):
        return "dupsub:branch"
    return "other" if lab.startswith("unmapped") or lab == "noheader" else lab


_maps = {}


def page_map(name):
    if name not in _maps:
        p = R + f"probe/{name}.map"
        _maps[name] = {int(a): label(b) for a, b in (line.rstrip("\n").split("\t") for line in open(p))} if os.path.exists(p) else None
    return _maps[name]


def trace(rid):
    """Per traced test: step seconds, distinct mdbx.dat pages, backing-image pages, pages by table."""
    win = R + f"probe/{rid}.win"
    if not os.path.exists(win):
        return None
    W = windows(rid)
    rows = [re.search(r"\s([\d.]+)s mdbx_pages=\s*(\d+) .* backing_pages=\s*(\d+)", line).groups() for line in open(win) if line.strip()]
    if not check(len(rows) == len(W), f"{rid}: {len(rows)} .win rows vs {len(W)} log windows"):
        return None
    mp = page_map(MAPS[rid]) if rid in MAPS else None
    out = {}
    for n, (row, (_, _, name)) in enumerate(zip(rows, W)):
        r = {"secs": float(row[0]), "mdbx_pages": int(row[1]), "backing_pages": int(row[2])}
        if mp is not None:
            pages = [int(x) for x in open(R + f"probe/{rid}-{n}.pages") if x.strip()]
            r["by_table"] = dict(Counter(mp.get(p, "other") for p in pages).most_common())
        out[key(name)] = r
    return out


def geo(*xs):
    xs = [x for x in xs if x]
    return (xs[0] * xs[1]) ** 0.5 if len(xs) == 2 else (xs[0] if xs else None)


# Registry: every run exists, ran its expected tests, all passed, under the expected loop mode.
dd = driver_dio()
runs, prov = {}, {}
for rid, (dio, n) in RUNS.items():
    c, L = cfg(rid), load(rid)
    if L is None or c is None:
        if not PARTIAL:
            check(False, f"{rid}: missing (results or cfg)")
        continue
    passed = sum(1 for _, e in L["tests"].values() if mg(e))
    check(len(L["tests"]) == n and passed == n, f"{rid}: {len(L['tests'])} tests, {passed} passed, want {n}")
    if L["epoch"] < FIRST_DIO:
        seen = 0
    else:
        v = dd.get(DRIVER_STEP.get(rid, rid))
        seen = v[0] if v and v[0] == v[1] else None
    check(seen == dio, f"{rid}: loop dio {seen}, want {dio}")
    runs[rid] = L["tests"]
    prov[rid] = {**c, "dio": dio, "tests": n, "started": datetime.datetime.fromtimestamp(L["epoch"], UTC).isoformat(),
                 "result": L["path"]}


def have(*rids):
    return all(r in runs for r in rids)


def M(rid, k):
    return mg(runs[rid][k][1]) if k in runs.get(rid, {}) else None


def S(rid, k):
    return secs(runs[rid][k][1]) if k in runs.get(rid, {}) else None


def ratio(a, b, ids):
    return [M(a, k) / M(b, k) for k in ids if M(a, k) and M(b, k)]


def common(*rids, only=None):
    ks = set.intersection(*(set(runs[r]) for r in rids))
    return sorted(k for k in ks if (only is None or only(k)) and all(M(r, k) for r in rids))


claims = {}

# C13: the baselines, recomputed and checked against the saved reductions.
for tag, P in (("buffered", ""), ("dio", "d"), ("v2", "v"), ("fix", "f"), ("g-fill", "g"), ("pr5", "h"), ("final", "k")):
    rs = [P + r for r in ("j1", "s1", "j2", "s2")]
    if not have(*rs):
        continue
    j1, s1, j2, s2 = rs
    ids = common(*rs)
    cls = {k: "ge1s" if S(j1, k) >= 1.0 else "lt1s" for k in ids}
    by = {}
    for c in ("ge1s", "lt1s"):
        sel = [k for k in ids if cls[k] == c]
        by[c] = {"pair_a": stats(ratio(s1, j1, sel)), "pair_b": stats(ratio(s2, j2, sel)),
                 "floor_sa": stats(ratio(s2, s1, sel)), "floor_joc": stats(ratio(j2, j1, sel))}
    cats = defaultdict(list)
    for k in ids:
        cats[(cls[k], category(runs[j1][k][0]))].append(k)
    claims.setdefault("C13", {})[tag] = {
        "class_from": j1, "common": len(ids), "classes": dict(Counter(cls.values())), "by_class": by,
        "categories": {f"{c} | {cat}": {"n": len(ks), "pair_a": stats(ratio(s1, j1, ks))["median"],
                                        "pair_b": stats(ratio(s2, j2, ks))["median"],
                                        "joc_secs": round(median(S(j1, k) for k in ks), 3),
                                        "sa_secs": round(median(S(s1, k) for k in ks), 3)}
                       for (c, cat), ks in sorted(cats.items())}}
    saved = R + "results/" + {"": "baseline", "d": "baseline-dio", "v": "baseline-v2", "f": "baseline-fix", "g": "baseline-g",
                              "h": "baseline-h", "k": "baseline-k"}[P] + ".json"
    if os.path.exists(saved):
        b = json.load(open(saved))["by_class"]
        for c in by:
            for f in ("pair_a", "pair_b", "floor_sa", "floor_joc"):
                check(abs(b[c][f]["median"] - by[c][f]["median"]) < 1e-4, f"C13 {tag} {c} {f}: recomputed {by[c][f]['median']} vs saved {b[c][f]['median']}")

# C1: buffered vs DIO on the same stores and binary.
if have("j1", "dj1", "s1", "ds1"):
    fam = defaultdict(list)
    for k in common("j1", "dj1", "s1", "ds1"):
        t = runs["j1"][k][0]
        f = category(t).split(" ")[-1] if "test_account_access" in t else category(t)
        fam[f].append((S("j1", k) / S("dj1", k), S("s1", k) / S("ds1", k)))
    claims["C1"] = {"speedup_buffered_to_dio": {f: {"n": len(v), "joc": round(median(a for a, _ in v), 3),
                                                     "sa": round(median(b for _, b in v), 3)} for f, v in sorted(fam.items())}}
    same = {}
    for buf, dio in (("fs", "xfs"), ("fjh", "xfjh")):
        tb, tdio = trace(buf), trace(dio)
        if tb and tdio:
            same[f"{dio}/{buf}"] = {k: round(tdio[k]["mdbx_pages"] / tb[k]["mdbx_pages"], 4) for k in tb if k in tdio}
    claims["C1"]["mdbx_pages_dio_over_buffered"] = same

# C2: the buffered loop's serialization (fio on a throwaway loop, iostat in situ).
fio = {}
for p in sorted(glob.glob(R + "logs/fio-*-*-*.json")):
    m = re.search(r"fio-(buffered|dio|raw)-(psync|libaio)-(\d+)\.json$", p)
    if m:
        rd = json.load(open(p))["jobs"][0]["read"]
        fio.setdefault(m.group(1), {})[f"{m.group(2)}:{m.group(3)}"] = {"iops": round(rd["iops"]), "mean_us": round(rd["clat_ns"]["mean"] / 1000, 1)}
off = datetime.datetime.now().astimezone().utcoffset().total_seconds()


def iostat(rid):
    p = R + f"logs/{rid}.iostat"
    if not os.path.exists(p):
        return None
    W, ts, cols, rows = windows(rid), None, None, []
    for line in open(p):
        s = line.split()
        m = re.match(r"(\d\d/\d\d/\d{4} \d\d:\d\d:\d\d( [AP]M)?)", line)
        if m:
            fmt = "%m/%d/%Y %I:%M:%S %p" if m.group(2) else "%m/%d/%Y %H:%M:%S"
            ts = datetime.datetime.strptime(m.group(1), fmt).replace(tzinfo=UTC).timestamp() - off
        elif s and s[0] == "Device":
            cols = s
        elif cols and s and ts and s[0] in ("nvme0n1", "nvme1n1", "md2", "loop1"):
            rows.append((ts, s[0], dict(zip(cols[1:], map(float, s[1:])))))
    out = {}
    for a, b, name in W:
        # iostat stamps the end of each 1 s interval
        sel = [(dev, v) for t, dev, v in rows if a < t <= b + 1]
        f = lambda dev, c: round(median(v[c] for d, v in sel if d == dev), 2) if any(d == dev for d, _ in sel) else None
        inf = [list(map(float, line.split())) for line in open(R + f"logs/{rid}.inflight") if line.strip()]
        inf = [r for r in inf if a <= r[0] <= b]
        out[key(name)] = {"secs": round(b - a, 2), "samples": len(sel),
                          "nvme_r_s": [f("nvme0n1", "r/s"), f("nvme1n1", "r/s")], "nvme_r_await_ms": [f("nvme0n1", "r_await"), f("nvme1n1", "r_await")],
                          "nvme_aqu_sz": [f("nvme0n1", "aqu-sz"), f("nvme1n1", "aqu-sz")], "loop1_aqu_sz": f("loop1", "aqu-sz"),
                          "inflight_median": {"loop1": median(r[1] for r in inf) if inf else None,
                                              "nvme": median(r[3] + r[5] for r in inf) if inf else None}}
    return out


claims["C2"] = {"fio": fio, "iostat": {r: iostat(r) for r in ("iob", "iod")}}

# C3: backing-file readahead (buffered, DIO, buffered with readahead off).
tr = {r: trace(r) for r in ("fs", "fjh", "xfs", "xfjh", "ras", "rajh")}
c3 = {}
for r, t in tr.items():
    if t:
        c3[r] = {k: {"secs": v["secs"], "mdbx_pages": v["mdbx_pages"], "backing_pages": v["backing_pages"],
                     "backing_over_mdbx": round(v["backing_pages"] / v["mdbx_pages"], 3) if v["mdbx_pages"] else None} for k, v in t.items()}
s_over_jh = {}
for tag, (s, jh) in {"buffered": ("fs", "fjh"), "dio": ("xfs", "xfjh"), "buffered_ra0": ("ras", "rajh")}.items():
    if tr.get(s) and tr.get(jh):
        s_over_jh[tag] = {k: round(tr[jh][k]["secs"] / tr[s][k]["secs"], 3) for k in tr[s] if k in tr[jh]}
claims["C3"] = {"traces": c3, "throughput_s_over_jh_from_trace_steps": s_over_jh}

# C4: where the accessed code sits on disk, and in what order the test reads it.


def spearman(a, b):
    def rk(xs):
        o = sorted(range(len(xs)), key=xs.__getitem__)
        r = [0] * len(xs)
        for i, j in enumerate(o):
            r[j] = i
        return r
    ra, rb = rk(a), rk(b)
    m = (len(a) - 1) / 2
    return sum((x - m) * (y - m) for x, y in zip(ra, rb)) / sum((x - m) ** 2 for x in ra)


c4 = {}
for rid in ("fj", "fjh", "fs"):
    pc, mp, W = R + f"logs/{rid}.pc", page_map(MAPS[rid]), windows(rid)
    if not (os.path.exists(pc) and mp and W):
        continue
    ino = int(re.findall(r"=(\d+)", open(pc).readline())[0])
    a, b, name = next(w for w in W if "EXISTING_CONTRACT_DIFF_MAX" in w[2])
    first = {}
    for line in open(pc):
        p = line.split()
        if len(p) == 4 and p[0][0].isdigit() and int(p[1]) == ino and a - 0.5 <= float(p[0]) <= b + 0.5:
            for q in range(int(p[2]), int(p[2]) + (1 << int(p[3]))):
                first.setdefault(q, float(p[0]))
    large = sorted(q for q in first if mp.get(q) == "large")
    runs_ = []
    for q in large:
        if runs_ and q == runs_[-1][1] + 1:
            runs_[-1][1] = q
        else:
            runs_.append([q, q])
    c4[rid] = {"test": key(name), "code_pages": len(large), "contiguous_runs": len(runs_),
               "mean_run_pages": round(len(large) / len(runs_), 1) if runs_ else None,
               "spearman_first_touch_vs_page": round(spearman([first[q] for q in large], large), 3) if len(large) > 2 else None}
claims["C4"] = c4

# C5-C11: the read switch and the store, under DIO, two independent pairs each.


def cells(sets, ids):
    """Per test group: median throughput ratio of each named pair over the groups' tests."""
    by = defaultdict(list)
    for k in ids:
        by[group(k)].append(k)
    out = {}
    for g, ks in sorted(by.items()):
        out[g] = {"n": len(ks), **{name: (stats(ratio(a, b, ks)) or {}).get("median") for name, (a, b) in sets.items() if have(a, b)}}
    return out


PAIRS = {
    "s/j A": ("xs", "xjc"), "s/j B": ("xs2", "xjc2"), "jh/jc A": ("xjh", "xjc"), "jh/jc B": ("xjh2", "xjc2"),
    "s/jh A": ("xs", "xjh"), "s/jh B": ("xs2", "xjh2"),
    "floor s": ("xs2", "xs"), "floor jh": ("xjh2", "xjh"), "floor jc": ("xjc2", "xjc"),
    "sr/jh A": ("xsr", "xjh"), "sr/jh B": ("xsr2", "xjh2"), "sr/s A": ("xsr", "xs"), "sr/s B": ("xsr2", "xs2"),
    "floor sr": ("xsr2", "xsr"), "sr/j A": ("xsr", "xjc"), "sr/j B": ("xsr2", "xjc2"),
    "dio baseline s/j A": ("ds1", "dj1"), "dio baseline s/j B": ("ds2", "dj2"),
}
EPAIRS = {
    "s/j A": ("xse", "xjce"), "s/j B": ("xse2", "xjce2"), "jh/jc A": ("xjhe", "xjce"), "jh/jc B": ("xjhe2", "xjce2"),
    "s/jh A": ("xse", "xjhe"), "s/jh B": ("xse2", "xjhe2"),
    "floor s": ("xse2", "xse"), "floor jh": ("xjhe2", "xjhe"), "floor jc": ("xjce2", "xjce"),
    "sr/jh A": ("xser", "xjhe"), "sr/jh B": ("xser2", "xjhe2"), "sr/s A": ("xser", "xse"), "sr/s B": ("xser2", "xse2"),
    "floor sr": ("xser2", "xser"), "sr/j A": ("xser", "xjce"), "sr/j B": ("xser2", "xjce2"),
    "dio baseline s/j A": ("ds1", "dj1"), "dio baseline s/j B": ("ds2", "dj2"),
}
c5 = {}
if have("xs", "xjh", "xjc"):
    ids = common("xs", "xjh", "xjc")
    cls = {k: S("dj1", k) >= 1 for k in ids} if "dj1" in runs else None
    c5["set_160M"] = {"tests": len(ids), "cells": cells(PAIRS, ids),
                      "by_class_from_dj1": {c: {name: stats(ratio(a, b, [k for k in ids if cls and cls[k] == (c == "ge1s")]))
                                                for name, (a, b) in PAIRS.items() if have(a, b)} for c in ("ge1s", "lt1s")} if cls else None}
if have("xse", "xjhe", "xjce"):
    ids = common("xse", "xjce", "xjhe")
    c5["set_ether"] = {"tests": len(ids), "all": {name: stats(ratio(a, b, ids)) for name, (a, b) in EPAIRS.items() if have(a, b)},
                       "cells": cells(EPAIRS, ids)}
claims["C5-C11"] = c5

# T2 page tables and A2 (µs per mdbx page against the untraced timing runs)
t2 = {r: trace(r) for r in ("t2jc", "t2jh", "t2s", "t2sr", "t2jv", "t2sf")}
TIMING = {"t2jc": (("xjc", "xjc2"), ("xjce", "xjce2")), "t2jh": (("xjh", "xjh2"), ("xjhe", "xjhe2")),
          "t2s": (("xs", "xs2"), ("xse", "xse2")), "t2sr": (("xsr", "xsr2"), ("xser", "xser2")),
          "t2jv": (("vj1", "vj2"), ("vj1", "vj2")), "t2sf": (("fs1", "fs2"), ("fs1", "fs2"))}
a2 = {}
for rid, t in t2.items():
    if not t:
        continue
    for k, v in t.items():
        pair = TIMING[rid][1] if "ether" in k else TIMING[rid][0]
        tm = [S(r, k) for r in pair if S(r, k)]
        a2.setdefault(k, {})[rid] = {"pages": v["mdbx_pages"], "timing_secs": round(median(tm), 4) if tm else None,
                                     "us_per_page": round(median(tm) * 1e6 / v["mdbx_pages"], 2) if tm and v["mdbx_pages"] else None,
                                     "by_table": v.get("by_table")}
for k, v in a2.items():
    if "t2s" in v and "t2jh" in v and v["t2s"]["timing_secs"] and v["t2jh"]["timing_secs"]:
        v["s/jh measured"] = round(v["t2jh"]["timing_secs"] / v["t2s"]["timing_secs"], 3)
        v["s/jh from pages"] = round(v["t2jh"]["pages"] / v["t2s"]["pages"], 3)
    if "t2sf" in v and "t2jv" in v and v["t2sf"]["timing_secs"] and v["t2jv"]["timing_secs"]:
        v["sf/jv measured"] = round(v["t2jv"]["timing_secs"] / v["t2sf"]["timing_secs"], 3)
        v["sf/jv from pages"] = round(v["t2jv"]["pages"] / v["t2sf"]["pages"], 3)
claims["T2_pages_and_A2"] = a2

# C6/C7: tree shape, and the repack that changes only it.


def mdbx_stats(p):
    out = {}
    if os.path.exists(R + p):
        for line in open(R + p):
            m = re.match(r"(\w+) (\{.*\}) branch_fill=(\S+) leaf_fill=(\S+)", line)
            if m:
                fill = lambda s: None if s == "None" else float(s)
                out[m.group(1)] = {**ast.literal_eval(m.group(2)), "branch_fill": fill(m.group(3)), "leaf_fill": fill(m.group(4))}
    return out


rp = {"tree_stats": {f: mdbx_stats(f"probe/{f}.map.log") for f in ("fj", "fs", "t2j", "t2s", "t2sr")},
      "repack_before": mdbx_stats("probe/repack-before.stats"), "repack_after": mdbx_stats("probe/repack-after.stats")}
if os.path.exists(R + "logs/repack.log"):
    log = open(R + "logs/repack.log").read()
    rp["repack_log"] = {"ok": "REPACK-OK" in log, "stat": re.findall(r"STAT (\S+) \S+ (\{.*\})", log),
                        "hash": re.findall(r"HASH (\w+) +(\w+) entries=(\d+) \((\S+)\)", log)}
    check(rp["repack_log"]["ok"], "repack: no REPACK-OK")
for f in ("logs/repack-toy.log", "logs/promote-repack.log", "logs/gate-repack/summary"):
    if os.path.exists(R + f):
        # libmdbx's debug lines (dxb_/gc_/meta_) would push the STAT lines out of the kept tail
        rp[os.path.basename(f)] = [line for line in open(R + f).read().strip().splitlines() if not line.startswith(("dxb_", "gc_", "meta_"))][-40:]
claims["C6-C7"] = rp

# C12: method (source build vs published image; benchmarkoor's disk counters vs page-cache truth).
c12 = {}
if have("xjc", "dj1", "dj2", "xs", "ds1", "ds2"):
    ids = common("xjc", "dj1", "dj2", "xs", "ds1", "ds2")
    c12["source_build_vs_published"] = {
        "xjc/geomean(dj1,dj2)": stats([M("xjc", k) / geo(M("dj1", k), M("dj2", k)) for k in ids]),
        "xs/geomean(ds1,ds2)": stats([M("xs", k) / geo(M("ds1", k), M("ds2", k)) for k in ids]),
        "floor dj2/dj1": stats(ratio("dj2", "dj1", ids)), "floor ds2/ds1": stats(ratio("ds2", "ds1", ids))}
infl = {}
for r in ("fjh", "fs", "xfjh", "xfs"):
    t = trace(r)
    if t and r in runs:
        infl[r] = {k: round((agg(runs[r][k][1]).get("resource_totals") or {}).get("disk_read_bytes", 0) / (v["mdbx_pages"] * 4096), 2)
                   for k, v in t.items() if k in runs[r] and v["mdbx_pages"]}
c12["benchmarkoor_disk_read_over_mdbx_page_bytes"] = infl
claims["C12"] = c12

# C14: how the earlier studies on this host attached their loops.
scripts = [p for p in glob.glob("/root/bench/*.sh") + glob.glob("/root/bench/*/*.sh") + glob.glob("/home/*/*.sh")
           if not p.startswith(R) and os.path.getsize(p) < 200_000]
uses = [p for p in scripts if "losetup" in open(p, errors="ignore").read()]
# basenames only: the data is published with the article, the host's directory layout is not
claims["C14"] = {"scripts_scanned": len(scripts), "scripts_calling_losetup": sorted(os.path.basename(p) for p in uses),
                 "any_direct_io": sorted(os.path.basename(p) for p in scripts if re.search(r"direct-io|direct_io|0x4C08|loop/dio", open(p, errors="ignore").read()))}

# C15-C17: v2 jochemnet. D = tests whose state-actor/jochemnet ratio is outside 1.1x on the same side in
# both pairs while both replica floors are inside it; then the store regenerated with PR1+PR2 on D.
LO, HI = 1 / 1.1, 1.1
inband = lambda x: LO <= x <= HI


def pair_ratios(s1, j1, s2, j2, k):
    return M(s1, k) / M(j1, k), M(s2, k) / M(j2, k), M(j2, k) / M(j1, k), M(s2, k) / M(s1, k)


if have("vj1", "vs1", "vj2", "vs2"):
    ids = common("vj1", "vs1", "vj2", "vs2")
    D, outside_one = {}, 0
    for k in ids:
        a, b, fj, fs = pair_ratios("vs1", "vj1", "vs2", "vj2", k)
        if not (inband(a) and inband(b)):
            outside_one += 1
        if ((a > HI and b > HI) or (a < LO and b < LO)) and inband(fj) and inband(fs):
            D[k] = {"group": group(k), "class": "ge1s" if S("vj1", k) >= 1 else "lt1s",
                    "before": [round(a, 4), round(b, 4)], "before_floors": [round(fj, 4), round(fs, 4)]}
    c15 = {"tests": len(ids), "D": len(D), "outside_band_in_either_pair": outside_one,
           "D_by_class": dict(Counter(v["class"] for v in D.values())),
           "D_faster_sa": sum(1 for v in D.values() if v["before"][0] > 1), "cells": D}
    claims["C15"] = c15
    if have("fj1", "fs1", "fj2", "fs2"):
        # mean |ln ratio| over the two pairs; a change under 0.03 (~3%) counts as unchanged
        dist = lambda xs: sum(abs(math.log(x)) for x in xs) / len(xs)
        for k, v in D.items():
            a, b, fj, fs = pair_ratios("fs1", "fj1", "fs2", "fj2", k)
            v["after"], v["after_floors"] = [round(a, 4), round(b, 4)], [round(fj, 4), round(fs, 4)]
            d0, d1 = dist(v["before"]), dist(v["after"])
            v["verdict"] = ("fixed" if inband(a) and inband(b) else
                            "improved" if d1 < d0 - 0.03 else "worse" if d1 > d0 + 0.03 else "unchanged")
        regressed = {}
        for k in common("vj1", "vs1", "vj2", "vs2", "fj1", "fs1", "fj2", "fs2"):
            if k in D:
                continue
            a0, b0, _, _ = pair_ratios("vs1", "vj1", "vs2", "vj2", k)
            a1, b1, fj, fs = pair_ratios("fs1", "fj1", "fs2", "fj2", k)
            if inband(a0) and inband(b0) and not inband(a1) and not inband(b1) and inband(fj) and inband(fs):
                regressed[k] = {"group": group(k), "before": [round(a0, 4), round(b0, 4)], "after": [round(a1, 4), round(b1, 4)]}
        claims["C16"] = {"verdicts": dict(Counter(v["verdict"] for v in D.values())),
                         "by_group_verdict": dict(Counter(f'{v["group"].split(" ")[0]} | {v["verdict"]}' for v in D.values()).most_common()),
                         "regressed_outside_D": regressed}

fixlog = {}
for f in ("logs/gen-fix.log", "logs/gen-fix-hash.txt", "logs/fix-virgin-hash.txt", "logs/fix-scratch-hash.txt",
          "logs/gen-fix-du.txt", "logs/v2-migrate.log", "logs/v2-settings-promoted.txt", "logs/sa-build-fix.log"):
    if os.path.exists(R + f):
        lines = open(R + f, errors="ignore").read().strip().splitlines()
        fixlog[os.path.basename(f)] = [line for line in lines if re.search(r"State Root|HASH|Total Time|exit|INFO .*migrat|storage_v2|^\d+\s|STEP|COMMIT", line)][-25:]
claims["C17"] = {"tree_stats_original": mdbx_stats("probe/t2s.map.log"), "tree_stats_fixed": mdbx_stats("probe/fix-tables.stats"),
                 "tree_stats_v2_jochemnet": mdbx_stats("probe/t2jv.map.log"), "logs": fixlog}


# C18: cycle 1. Per family and duration class (fixed from vj1), the median of the per-test geomean of
# the two pairs for the original store (v), PR1+PR2 (f) and PR1-PR4 at migrated fill (g); then the plan's
# acceptance: every >= 0.5 s family median in band, >= 80% of >= 0.5 s tests in band.
# C19: cycle 2, the same reduction with PR1-PR5 (h) as the latest store.
def family(t):
    f = re.search(r"test_(\w+)\[", t).group(1)
    if f == "account_access":
        if "overhead_baseline_True" in t:
            return "overhead control"
        mode = re.search(r"AccountMode\.(\w+?)-", t).group(1)
        base = "code-heavy reads" if mode in ("EXISTING_CONTRACT_DIFF_MAX", "EXISTING_CONTRACT_JUMPDEST") else "account reads"
        return base + (" +value" if "value_sent_1" in t else "")
    if f.startswith("ether_transfers"):
        return "ether transfers"
    if f == "sstore_bloated":
        return "sstore " + ("write" if "write_new_value_True" in t else "no-write")
    return f


def cycle(stores, latest):
    ids = common("vj1", *(r for rs in stores.values() for r in rs))
    cls_ = {k: ">=1s" if S("vj1", k) >= 1 else "0.5-1s" if S("vj1", k) >= 0.5 else "<0.5s" for k in ids}
    pair = {st: {k: (M(s1, k) / M(j1, k), M(s2, k) / M(j2, k)) for k in ids} for st, (s1, j1, s2, j2) in stores.items()}
    geo_ = {st: {k: (a * b) ** 0.5 for k, (a, b) in v.items()} for st, v in pair.items()}
    cells = defaultdict(list)
    for k in ids:
        cells[(cls_[k], family(runs["vj1"][k][0]))].append(k)
    fams = {}
    for (c, f), ks in sorted(cells.items()):
        fams[f"{c} | {f}"] = {"n": len(ks), "J secs": round(median(S("vj1", k) for k in ks), 3),
                             **{st: round(median(geo_[st][k] for k in ks), 4) for st in stores},
                             **{f"in band {st}": sum(inband(geo_[st][k]) for k in ks) for st in stores},
                             f"{latest} pair medians": [round(median(pair[latest][k][i] for k in ks), 4) for i in (0, 1)]}
    big = [k for k in ids if cls_[k] != "<0.5s"]
    by_fam = defaultdict(list)
    for k in big:
        by_fam[family(runs["vj1"][k][0])].append(k)
    acc = {}
    for f, ks in by_fam.items():
        mg_ = median(geo_[latest][k] for k in ks)
        pa, pb = (median(pair[latest][k][i] for k in ks) for i in (0, 1))
        acc[f] = {"n": len(ks), "median": round(mg_, 4), "in band": inband(mg_), "robust": inband(pa) and inband(pb)}
    share = {st: round(sum(inband(geo_[st][k]) for k in big) / len(big), 4) for st in stores}
    out = {
        "families": fams, "acceptance_by_family": acc, "tests_ge_0.5s": len(big), "share_in_band": share,
        "accepted": all(v["in band"] for v in acc.values()) and share[latest] >= 0.8,
        "families_not_robust": sorted(f for f, v in acc.items() if not v["robust"]),
        "below_0.5s_flagged": sorted(k for k, v in fams.items() if k.startswith("<0.5s") and not 0.8 <= v[latest] <= 1.25),
        # every >= 0.5 s test the latest store leaves outside the band, with the path that led there
        "out_of_band": {group(runs["vj1"][k][0]): {"J secs": round(S("vj1", k), 3), "family": family(runs["vj1"][k][0]),
                                                   **{st: round(geo_[st][k], 4) for st in stores},
                                                   f"{latest} pairs": [round(x, 4) for x in pair[latest][k]],
                                                   "both pairs out": not inband(pair[latest][k][0]) and not inband(pair[latest][k][1])}
                        for k in big if not inband(geo_[latest][k])},
    }
    return out


STORES = {"orig": ("vs1", "vj1", "vs2", "vj2"), "fixed": ("fs1", "fj1", "fs2", "fj2"), "g": ("gs1", "gj1", "gs2", "gj2")}
if have(*STORES["g"], "vj1"):
    claims["C18"] = {**cycle(STORES, "g"), "tree_stats_g": mdbx_stats("probe/g-tables.stats")}


def classified(rid):
    """classify3's page attribution of each traced test (table x main/nested tree), keyed by the .win name."""
    p, w = R + f"probe/{rid}.classify.json", R + f"probe/{rid}.win"
    if not (os.path.exists(p) and os.path.exists(w)):
        return None
    tests = json.load(open(p))[rid]["tests"]
    names = [line.split()[-1] for line in open(w) if line.strip()]
    return {n: tests[f"{rid}-{i}.pages"] for i, n in enumerate(names) if f"{rid}-{i}.pages" in tests}


def walk_shape(p):
    """Slots per storage account from an exact HashedStorages walk (rc/jwalk.py): quantiles, buckets, CDF."""
    if not os.path.exists(R + p):
        return None
    w = json.load(open(R + p))
    h = {int(k): v for k, v in w["hist"].items()}
    n, ks = sum(h.values()), sorted(h)
    cum, acc_, cdf = {}, 0, []
    for k in ks:
        acc_ += h[k]
        cum[k] = acc_ / n
    q = lambda f: next(k for k in ks if cum[k] >= f)
    for x in sorted({1, 2, 3, 5, 10, 20, 28, 50, 100, 200, 500, 1000, 4000, 10**4, 10**5, 10**6, 10**7, 2**24, ks[-1]}):
        cdf.append([x, round(max((c for k, c in cum.items() if k <= x), default=0), 6)])
    vl = {int(k): v for k, v in w["value_len_hist"].items()}
    tv = sum(vl.values()) or 1
    share = lambda lo, hi: round(sum(v for k, v in h.items() if lo <= k <= hi) / n, 5)
    return {"storage_accounts": n, "slots": sum(k * v for k, v in h.items()), "main_tree_leaves": w["leaves"],
            "p50": q(.5), "p90": q(.9), "p99": q(.99), "p999": q(.999), "max": ks[-1],
            "buckets": {"1": share(1, 1), "2-28": share(2, 28), "29-4000": share(29, 4000), ">4000": share(4001, 1 << 62)},
            "value_len_share": {str(k): round(vl.get(k, 0) / tv, 4) for k in (1, 20, 32)}, "cdf": cdf,
            # every account above PR5's per-contract cap (2^24 slots), the bloated test contract included
            "over_2_24": sorted(k for k, v in h.items() if k > 1 << 24 for _ in range(v))}


def fill_summary(p):
    """rc/fillgate.py on one store: the DupSort main trees on their own, the bloated contract's nested
    trees and the mid-size contracts' nested HashedStorages trees (mdbxmap's leaf_fill covers main trees only)."""
    if not os.path.exists(R + p):
        return None
    d = json.load(open(R + p))

    def g(*ks):
        o = d
        for k in ks:
            o = o.get(k) if isinstance(o, dict) else None
        return o
    out = {"midsize HashedStorages leaf_fill": g("midsize", "HashedStorages", "per_tree_leaf_fill", "mean")}
    for t in ("HashedStorages", "StoragesTrie"):
        out[f"bloated {t}"] = {"height": g("bloated", t, "descriptor", "height"), "leaf_pages": g("bloated", t, "descriptor", "leaf"),
                               "branch_pages": g("bloated", t, "descriptor", "branch"),
                               "leaf_fill": g("bloated", t, "leaf_fill", "mean"), "branch_fill": g("bloated", t, "branch_fill_exact")}
        out[f"main {t}"] = {"height": g("main_trees", t, "height"), "leaf_pages": g("main_trees", t, "main_only_leaf_pages"),
                            "leaf_fill": g("main_trees", t, "leaf_fill_uniform", "mean")}
    return out



STORES19 = {**STORES, "h": ("hs1", "hj1", "hs2", "hj2")}


def entries(p, rx):
    """First integer captured by rx in file p (the HashedAccounts row count of a store), or None."""
    m = re.search(rx, open(R + p).read(), re.M) if os.path.exists(R + p) else None
    return int(m.group(1)) if m else None


if have(*STORES19["h"], "vj1"):
    sg = json.load(open(R + "probe/jcal-sg.json")) if os.path.exists(R + "probe/jcal-sg.json") else None
    claims["C19"] = {**cycle(STORES19, "h"), "tree_stats_h": mdbx_stats("probe/h-tables.stats"),
                     "manifest_h": {k: v for k, v in json.load(open(R + "logs/h-manifest.json"))["result"].items() if not isinstance(v, (dict, list))},
                     "storage_shape": {"J": walk_shape("probe/jwalk-j.json"), "h": walk_shape("probe/jwalk-h.json"),
                                       # the cycle-1 store was only sampled (5,000 storage accounts, rc/jcal.py)
                                       "g_sample": sg and {"n": sg["n"], "slots_per_account": sg["slots_per_account"],
                                                           "buckets": {b: v["accounts"] for b, v in sg["buckets"].items()},
                                                           "quantiles_1000": sg["quantiles_1000"]}},
                     "t3_pages": {rid: classified(rid) for rid in ("t3jg", "t3sg", "t3sh")},
                     "tree_fill": {st: fill_summary(f"probe/{f}") for st, f in
                                   (("J", "jv-fill.json"), ("fixed", "sfix-fill.json"), ("g", "g-fill.json"), ("h", "h-fill.json"))},
                     # HashedAccounts rows: J's from reth db stats, h's from the gen-check table hash
                     "accounts": {"J": entries("probe/joc-stats.txt", r"^\| HashedAccounts +\| (\d+)"),
                                  "h": entries("logs/gen-h-hash.txt", r"^HASH HashedAccounts \S+ entries=(\d+)")},
                     # reth db repair-trie --dry-run on the PR1-5 store: every trie node rebuilt and compared
                     "rootcheck_inconsistencies": entries("logs/h-rootcheck.log", r"Found (\d+) inconsistencies")}

# C20: cycle 3 (final): PR1-PR5 + scale-free storage tail (A) + StoragesTrie in address order (B) + mainnet
# account model (C), as k.
STORES20 = {**STORES19, "k": ("ks1", "kj1", "ks2", "kj2")}


def acct_shape(size, kind):
    """rc/acctsize.py (200k uniform account samples) and rc/acctkind.py (20k code-bearing rows) on one store."""
    if not (os.path.exists(R + size) and os.path.exists(R + kind)):
        return None
    s, k = json.load(open(R + size)), json.load(open(R + kind))
    return {"value_len_mean": round(s["value_len_mean"], 3), "code_hash_share": round(s["code_hash_share"], 4),
            "nonce_len_share": {b: round(v / s["n"], 4) for b, v in s["nonce_len_hist"].items()},
            "balance_len_share": {b: round(v / s["n"], 4) for b, v in s["balance_len_hist"].items()},
            "nonce_quantiles": s["nonce_quantiles"], "coded_kinds": {c: round(v, 4) for c, v in k["kinds"].items()},
            "coded_accounts_per_distinct_code": round(k["accounts_per_distinct_code"], 2)}


if have(*STORES20["k"], "vj1"):
    claims["C20"] = {**cycle(STORES20, "k"), "tree_stats_k": mdbx_stats("probe/k-tables.stats"),
                     "manifest_k": {k: v for k, v in json.load(open(R + "logs/k-manifest.json"))["result"].items() if not isinstance(v, (dict, list))},
                     "storage_shape": {"J": walk_shape("probe/jwalk-j.json"), "h": walk_shape("probe/jwalk-h.json"),
                                       "k": walk_shape("probe/jwalk-k.json")},
                     # acctsize/acctkind S = the cycle-2 (h) store, sampled on its scratch before cycle 3
                     "account_shape": {st: acct_shape(f"probe/acctsize-{n}.json", f"probe/acctkind-{n}.json")
                                       for st, n in (("J", "J"), ("h", "S"), ("k", "k"))},
                     "t3_pages": {rid: classified(rid) for rid in ("t3jg", "t3sh", "t3sk")},
                     "tree_fill": {st: fill_summary(f"probe/{f}") for st, f in
                                   (("J", "jv-fill.json"), ("h", "h-fill.json"), ("k", "k-fill.json"))},
                     "accounts": {"J": entries("probe/joc-stats.txt", r"^\| HashedAccounts +\| (\d+)"),
                                  "k": entries("logs/gen-k-hash.txt", r"^HASH HashedAccounts \S+ entries=(\d+)")},
                     "rootcheck_inconsistencies": entries("logs/k-rootcheck.log", r"Found (\d+) inconsistencies")}

# Verdicts. Each oracle states its claim as a test on the numbers above; a threshold encodes the claim's
# wording, not the measurement. "contradicted" is a finding the article must reflect; "pending" (data
# missing) fails a final collection.
def med(a, b, rx, base=("xs", "xjh", "xjc")):
    if not have(a, b, *base):
        return None
    r = ratio(a, b, [k for k in common(*base) if re.search(rx, k)])
    return round(median(r), 4) if r else None


def ether(a, b, rx=""):
    return med(a, b, rx, ("xse", "xjhe", "xjce"))


def t2(rx, rid):
    k = next((k for k in a2 if re.search(rx, k)), None)
    return a2.get(k, {}).get(rid) if k else None


def tbl(rx, rid, *tables):
    v = t2(rx, rid)
    return sum((v["by_table"] or {}).get(t, 0) for t in tables) if v else None


def dig(d, *ks):
    for k in ks:
        d = d.get(k) if isinstance(d, dict) else None
    return d


SEQ = r"value_sent_0-account_mode_AccountMode\.(EXISTING_EOA|NON_EXISTING_ACCOUNT)-overhead_baseline_False"
ROWS = r"value_sent_0-account_mode_AccountMode\.EXISTING_CONTRACT_(MINIMAL|SAME_MAX)-overhead_baseline_False"
CONTRACT = r"\[transfer_amount_0-case_id_diff_to_contract-|diff_to_contract-benchmark-gas-value_160M"
fs_ = claims.get("C3", {}).get("traces", {})
DM = "EXISTING_CONTRACT_DIFF_MAX"
pick = lambda t, rx: next((v for k, v in (t or {}).items() if rx in k), None)
ORACLES = {
    "C1": lambda: {"ext_account_query_warm joc, sa": [dig(claims, "C1", "speedup_buffered_to_dio", "ext_account_query_warm", a) for a in ("joc", "sa")],
                   "state families joc, sa (min)": [min(v[a] for f, v in dig(claims, "C1", "speedup_buffered_to_dio").items() if f not in ("ext_account_query_warm", "sload_same_key_benchmark", "EXISTING_EOA", "NON_EXISTING_ACCOUNT", "sload_bloated")) for a in ("joc", "sa")],
                   "mdbx pages dio/buffered (max dev)": max(abs(x - 1) for v in dig(claims, "C1", "mdbx_pages_dio_over_buffered").values() for x in v.values())},
    "C2": lambda: {"buffered psync 64 / psync 4": round(fio["buffered"]["psync:64"]["iops"] / fio["buffered"]["psync:4"]["iops"], 3),
                   "dio / buffered at psync 16": round(fio["dio"]["psync:16"]["iops"] / fio["buffered"]["psync:16"]["iops"], 2),
                   "iob loop1 aqu-sz, nvme aqu-sz sum": [min(v["loop1_aqu_sz"] for v in claims["C2"]["iostat"]["iob"].values()), max(sum(v["nvme_aqu_sz"]) for v in claims["C2"]["iostat"]["iob"].values())]},
    "C3": lambda: {"fs, ras DIFF_MAX backing/mdbx": [pick(fs_.get("fs"), DM)["backing_over_mdbx"], pick(fs_.get("ras"), DM)["backing_over_mdbx"]],
                   "DIFF_MAX s/jh buffered, readahead off": [pick(claims["C3"]["throughput_s_over_jh_from_trace_steps"]["buffered"], DM), pick(claims["C3"]["throughput_s_over_jh_from_trace_steps"]["buffered_ra0"], DM)]},
    "C4": lambda: {f"{r} rho, mean run": [claims["C4"][r]["spearman_first_touch_vs_page"], claims["C4"][r]["mean_run_pages"]] for r in ("fj", "fjh", "fs")},
    "C5": lambda: {"jh/jc A, B": [med("xjh", "xjc", SEQ), med("xjh2", "xjc2", SEQ)], "s/jh A, B": [med("xs", "xjh", SEQ), med("xs2", "xjh2", SEQ)]},
    "C6": lambda: {"s/jh A, B": [med("xs", "xjh", ROWS), med("xs2", "xjh2", ROWS)], "repacked sr/jh A, B": [med("xsr", "xjh", ROWS), med("xsr2", "xjh2", ROWS)],
                   "us/page s/jh (BALANCE MINIMAL)": round(t2("BALANCE-value_sent_0.*MINIMAL", "t2s")["us_per_page"] / t2("BALANCE-value_sent_0.*MINIMAL", "t2jh")["us_per_page"], 3),
                   "HashedAccounts pages t2s, t2sr, t2jh (BALANCE MINIMAL)": [tbl("BALANCE-value_sent_0.*MINIMAL", r, "HashedAccounts:branch", "HashedAccounts:leaf") for r in ("t2s", "t2sr", "t2jh")]},
    "C7": lambda: {"leaf fill before, after": [dig(rp, "repack_before", "HashedAccounts", "leaf_fill"), dig(rp, "repack_after", "HashedAccounts", "leaf_fill")],
                   "hash before == after": len({h[1] for h in rp["repack_log"]["hash"]}) == 1,
                   "toy leaf pages": re.findall(r"STAT mktest-(\S+) T \{.*LeafPages:(\d+)", "\n".join(rp.get("repack-toy.log", [])))},
    "C8": lambda: {"s/j A, B": [ether("xse", "xjce"), ether("xse2", "xjce2")], "jh/jc A, B": [ether("xjhe", "xjce"), ether("xjhe2", "xjce2")],
                   "s/jh A, B": [ether("xse", "xjhe"), ether("xse2", "xjhe2")], "repacked sr/jh A, B": [ether("xser", "xjhe"), ether("xser2", "xjhe2")]},
    "C9": lambda: {"t2jc Plain, Hashed accounts": [tbl(CONTRACT, "t2jc", "PlainAccountState:leaf", "PlainAccountState:branch"), tbl(CONTRACT, "t2jc", "HashedAccounts:leaf", "HashedAccounts:branch")],
                   "t2jh Plain": tbl(CONTRACT, "t2jh", "PlainAccountState:leaf", "PlainAccountState:branch"),
                   "pages t2jc, t2jh": [t2(CONTRACT, "t2jc")["pages"], t2(CONTRACT, "t2jh")["pages"]]},
    "C10": lambda: {"AccountsTrie branch t2s / t2jh (CALL EOA value 1)": round(tbl("CALL-value_sent_1.*EXISTING_EOA", "t2s", "AccountsTrie:branch") / tbl("CALL-value_sent_1.*EXISTING_EOA", "t2jh", "AccountsTrie:branch"), 2)},
    "C11": lambda: {"pages t2s, t2jh (sload)": [t2("sload_bloated", "t2s")["pages"], t2("sload_bloated", "t2jh")["pages"]],
                    "s/jh A, B": [med("xs", "xjh", "sload_bloated"), med("xs2", "xjh2", "sload_bloated")]},
    "C12": lambda: {"xjc/geomean(dj)": dig(claims, "C12", "source_build_vs_published", "xjc/geomean(dj1,dj2)", "median"),
                    "disk_read / mdbx bytes (median)": median(x for v in claims["C12"]["benchmarkoor_disk_read_over_mdbx_page_bytes"].values() for x in v.values())},
    "C13": lambda: {"dio ge1s A, B": [dig(claims, "C13", "dio", "by_class", "ge1s", p, "median") for p in ("pair_a", "pair_b")],
                    "dio ge1s floors within10": [dig(claims, "C13", "dio", "by_class", "ge1s", p, "within10") for p in ("floor_joc", "floor_sa")],
                    "buffered ge1s A, B": [dig(claims, "C13", "buffered", "by_class", "ge1s", p, "median") for p in ("pair_a", "pair_b")]},
    "C14": lambda: {"scripts calling losetup": len(claims["C14"]["scripts_calling_losetup"]), "any direct-io": claims["C14"]["any_direct_io"]},
}
within = lambda x, lo, hi: x is not None and lo <= x <= hi
TESTS = {
    "C1": lambda e: all(within(x, 0.9, 1.1) for x in e["ext_account_query_warm joc, sa"]) and min(e["state families joc, sa (min)"]) >= 2 and e["mdbx pages dio/buffered (max dev)"] <= 0.03,
    "C2": lambda e: e["buffered psync 64 / psync 4"] <= 1.1 and e["dio / buffered at psync 16"] >= 5 and e["iob loop1 aqu-sz, nvme aqu-sz sum"][0] >= 32 and e["iob loop1 aqu-sz, nvme aqu-sz sum"][1] <= 1.5,
    "C3": lambda e: e["fs, ras DIFF_MAX backing/mdbx"][0] >= 2.5 and e["fs, ras DIFF_MAX backing/mdbx"][1] <= 1.05 and e["DIFF_MAX s/jh buffered, readahead off"][0] <= 0.8 and within(e["DIFF_MAX s/jh buffered, readahead off"][1], 0.95, 1.05),
    "C4": lambda e: abs(e["fj rho, mean run"][0]) <= 0.1 and abs(e["fjh rho, mean run"][0]) <= 0.1 and e["fs rho, mean run"][0] >= 0.9
    and e["fs rho, mean run"][1] <= 10 and e["fj rho, mean run"][1] >= 50,
    "C5": lambda e: all(within(x, 0, 0.3) for x in e["jh/jc A, B"]) and all(within(x, 0.85, 1.1) for x in e["s/jh A, B"]),
    "C6": lambda e: all(within(x, 0.88, 0.98) for x in e["s/jh A, B"]) and all(within(x, 0.98, 1.2) for x in e["repacked sr/jh A, B"]) and within(e["us/page s/jh (BALANCE MINIMAL)"], 0.9, 1.1),
    "C7": lambda e: e["leaf fill before, after"][0] <= 0.55 and e["leaf fill before, after"][1] >= 0.9 and e["hash before == after"]
    and (lambda t: t["sorted-put"] == t["sorted-append"] and int(t["random-put"]) >= 1.8 * int(t["sorted-put"]))(dict(e["toy leaf pages"])),
    "C8": lambda e: all(within(x, 0.95, 1.05) for x in e["s/j A, B"]) and all(x >= 1.08 for x in e["jh/jc A, B"]) and all(x <= 0.92 for x in e["s/jh A, B"]),
    "C9": lambda e: min(e["t2jc Plain, Hashed accounts"]) >= 20_000 and e["t2jh Plain"] <= 1_000 and e["pages t2jc, t2jh"][0] > e["pages t2jc, t2jh"][1],
    "C10": lambda e: e["AccountsTrie branch t2s / t2jh (CALL EOA value 1)"] >= 1.5,
    "C11": lambda e: e["pages t2s, t2jh (sload)"][0] < e["pages t2s, t2jh (sload)"][1] and all(x >= 1.1 for x in e["s/jh A, B"]),
    "C12": lambda e: within(e["xjc/geomean(dj)"], 0.97, 1.03) and within(e["disk_read / mdbx bytes (median)"], 3.5, 4.5),
    "C13": lambda e: all(within(x, 0.97, 1.03) for x in e["dio ge1s A, B"]) and min(e["dio ge1s floors within10"]) >= 95 and max(e["buffered ge1s A, B"]) <= 0.9,
    "C14": lambda e: e["scripts calling losetup"] >= 1 and not e["any direct-io"],
}
verdicts = {}
for c, ev in ORACLES.items():
    try:
        e = ev()
        if "None" in repr(e):
            raise ValueError(f"missing evidence: {e}")
        verdicts[c] = {"verdict": "supported" if TESTS[c](e) else "contradicted", "evidence": e}
    except (KeyError, TypeError, ValueError, StopIteration, ZeroDivisionError, AttributeError) as x:
        verdicts[c] = {"verdict": "pending", "missing": repr(x)}
        if not PARTIAL:
            check(False, f"{c}: verdict pending ({x!r})")
claims["verdicts"] = verdicts


def sh(cmd):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:
        return None


images = sorted({p["image"] for p in prov.values()})
out = {"provenance": {"collected_at": datetime.datetime.now(UTC).isoformat(timespec="seconds"),
                      "kernel": sh("uname -r"),
                      "images": {i: sh(f"podman image inspect --format '{{{{.Id}}}}' {i}") for i in images},
                      "runs": prov, "partial": PARTIAL},
       "checks": checks, "claims": claims}
json.dump(out, sys.stdout, indent=1, sort_keys=True, default=str)
sys.exit(1 if checks and not PARTIAL else 0)
