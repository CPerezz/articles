import re, datetime, bisect
io = []
for l in open("/root/bench/reth/logs/io-1s.log"):
    p = l.split("|")[0].split()
    try: io.append((float(p[0]), int(p[8])))
    except Exception: pass
L = "/root/bench/reth/logs/j1.log"
ev = []
for l in open(L, errors="ignore"):
    l = re.sub(r"\x1b\[[0-9;]*m", "", l)
    if "CLIE" in l or "RPC call completed" in l: continue
    m = re.search(r"(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+)Z\s+\w+\s+\|\s+(.{0,60})", l)
    if m: ev.append((datetime.datetime.fromisoformat(m.group(1)[:26]).replace(tzinfo=datetime.timezone.utc).timestamp(), m.group(2)))
# find the last heavy CALL value_sent_1 test: locate "Running setup step" ... "schelk restore"
marks = [(t, s) for t, s in ev if any(k in s for k in ("Running setup step", "Running test step", "Test completed successfully", "Stopping container with SIGTERM", "Container stopped for recreate", "Running `schelk restore`"))]
# pick window with the most writes
best = None
for i, (t, s) in enumerate(marks):
    if s.startswith("Running setup step"):
        j = i
        while j < len(marks) and not marks[j][1].startswith("Running `schelk restore`"): j += 1
        if j < len(marks):
            a, b = t - 5, marks[j][0]
            ia, ib = bisect.bisect_left([x[0] for x in io], a), bisect.bisect_left([x[0] for x in io], b)
            w = (io[min(ib, len(io)-1)][1] - io[min(ia, len(io)-1)][1]) * 512
            if not best or w > best[0]: best = (w, i, j)
w, i, j = best
print(f"window writes {w/1e6:.0f} MB")
ts = [x[0] for x in io]
for t, s in marks[i:j + 1]:
    k = bisect.bisect_left(ts, t)
    print(f"{datetime.datetime.utcfromtimestamp(t).strftime('%H:%M:%S.%f')[:12]}  cumMB={(io[min(k,len(io)-1)][1]-io[bisect.bisect_left(ts, marks[i][0]-5)][1])*512/1e6:8.0f}  {s}")
