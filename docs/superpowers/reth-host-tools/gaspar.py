import sys; sys.argv=["x"]
exec(open("/root/bench/reth/perfam.py").read().split("a, b = load(A)")[0])
a, b = load("j1"), load("s1")
by = defaultdict(list)
for t in a:
    if t in b:
        ga=a[t]["steps"]["test"]["aggregated"]["gas_used_total"]; gb=b[t]["steps"]["test"]["aggregated"]["gas_used_total"]
        by[cat(t)].append((ga, gb, re.search(r"benchmark-gas-value_(\d+)M", t).group(1) if "gas-value" in t else "?"))
for k, v in sorted(by.items()):
    print(f"{k:42}", " ".join(f"{g}M:{x/1e6:.1f}/{y/1e6:.1f}" for x, y, g in sorted(v, key=lambda r: r[2])))
