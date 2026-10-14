import re, datetime
L = "/root/bench/reth/logs/j1.log"
cur_test, t_start, rows = None, None, []
last_done = None
for l in open(L, errors="ignore"):
    l = re.sub(r"\x1b\[[0-9;]*m", "", l)
    if "CLIE" in l or "RPC call completed" in l:
        continue
    m = re.search(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+)Z", l)
    if not m:
        continue
    t = datetime.datetime.fromisoformat(m.group(1)[:26])
    if "Test completed successfully" in l:
        last_done = re.search(r"test=(\S+)", l).group(1)
    if "Running `schelk restore`" in l:
        t_start = t
    if "schelk datadir ready" in l and t_start:
        rows.append(((t - t_start).total_seconds(), last_done))
        t_start = None
rows.sort(key=lambda r: -r[0])
for s, tname in rows[:14]:
    print(f"{s:6.0f}s after {re.sub(r'.*::', '', tname or 'start')[:150]}")
print("restores", len(rows), "total h", round(sum(r[0] for r in rows) / 3600, 2), "over 300 s:", sum(1 for r in rows if r[0] > 300))
