import re, datetime
L = "/root/bench/reth/logs/j1.log"
ev = []
for l in open(L, errors="ignore"):
    l = re.sub(r"\x1b\[[0-9;]*m", "", l)
    if "CLIE" in l or "RPC call completed" in l:
        continue
    m = re.search(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+)Z\s+\w+\s+\|\s+(.{0,80})", l)
    if m:
        ev.append((datetime.datetime.fromisoformat(m.group(1)[:26]), m.group(2)))
print(len(ev))
jumps = sorted(((ev[i + 1][0] - ev[i][0]).total_seconds(), ev[i][1], ev[i + 1][1], ev[i][0].strftime("%H:%M")) for i in range(len(ev) - 1))[-12:]
for j in jumps:
    print(f"{j[0]:7.0f}s at {j[3]}  {j[1][:50]!r} -> {j[2][:50]!r}")
