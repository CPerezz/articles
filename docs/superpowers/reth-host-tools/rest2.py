import re, datetime, json, glob, bisect
L = "/root/bench/reth/logs/j1.log"
io = []
for l in open("/root/bench/reth/logs/io-1s.log"):
    p = l.split("|")[0].split()
    try: io.append((float(p[0]), int(p[2 + 6])))  # sectors written on the J scratch loop
    except Exception: pass
ts_ = [x[0] for x in io]
def written(a, b):
    i, j = bisect.bisect_left(ts_, a), bisect.bisect_left(ts_, b)
    return (io[min(j, len(io)-1)][1] - io[min(i, len(io)-1)][1]) * 512 if io else 0
ev, start, last = [], None, None
for l in open(L, errors="ignore"):
    l = re.sub(r"\x1b\[[0-9;]*m", "", l)
    if "CLIE" in l or "RPC call completed" in l: continue
    m = re.search(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+)Z", l)
    if not m: continue
    t = datetime.datetime.fromisoformat(m.group(1)[:26]).replace(tzinfo=datetime.timezone.utc).timestamp()
    if "Executing test component=runner" in l: start = t
    if "Running `schelk restore`" in l and start: ev.append((start, t, last)); start = None
    if "Test completed successfully" in l: last = re.search(r"test=(\S+)", l).group(1)
rows = []
for a, b, name in ev:
    rows.append((written(a, b), name))
rows.sort(key=lambda r: -r[0])
for w, n in rows[:6]: print(f"{w/1e9:6.1f} GB written during {re.sub(r'.*::', '', n or '?')[:110]}")
print("total written GB", round(sum(r[0] for r in rows)/1e9, 1))
# remaining order
idx = [re.search(r"index=(\d+)/266.*test=(\S+)", re.sub(r"\x1b\[[0-9;]*m", "", l)) for l in open(L, errors="ignore") if "Executing test component=runner" in l]
done = {m.group(2) for m in idx if m}
