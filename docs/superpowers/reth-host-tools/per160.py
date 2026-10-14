import sys; sys.argv=["x"]
exec(open("/root/bench/reth/perfam.py").read().split("a, b = load(A)")[0])
A,B="j1","s1"
if len(sys.argv)>2: A,B=sys.argv[1:3]
a, b = load(A), load(B)
rows=[]
for t in a:
    if t in b and "gas-value_160M" in t and "overhead_baseline_True" not in t:
        x,y=m(a[t]),m(b[t]); g=a[t]["steps"]["test"]["aggregated"]["gas_used_total"]
        rows.append((cat(t),x,y))
print(f"{'family':42} {'ratio':>6} {'J s':>6} {'S s':>6} {'J MB':>6} {'S MB':>6} {'J kIO':>6} {'S kIO':>6} {'J KB/IO':>7} {'S KB/IO':>7}")
for k,x,y in sorted(rows,key=lambda r:r[2]['mgas']/r[1]['mgas']):
    print(f"{k:42} {y['mgas']/x['mgas']:6.3f} {x['s']:6.2f} {y['s']:6.2f} {x['rb']/1e6:6.0f} {y['rb']/1e6:6.0f} {x['riops']/1e3:6.1f} {y['riops']/1e3:6.1f} {x['rb']/max(x['riops'],1)/1e3:7.1f} {y['rb']/max(y['riops'],1)/1e3:7.1f}")
