#!/usr/bin/env python3
"""Write cfg/<rid>.yaml for an experiment run. usage: mkexp.py <rid> <J|S> <image> <filter> [KEY=VAL ...]
Same arm settings as mkcfg.py; KEY=VAL pairs become container environment variables."""
import sys
src = open("/root/bench/reth/mkcfg.py").read().split('open("/root/bench/reth/cfg/J-prerun.yaml"')[0]
sys.argv = [sys.argv[0]] + sys.argv[1:]
rid, arm, img, filt, envs = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5:]
ns = {"__name__": "mkcfg", "sys": type("S", (), {"argv": ["x", img]})}
exec(src.replace("import sys\n", ""), ns)
out = ns["cfg"](rid, arm, filt)
if envs:
    out += "      environment:\n" + "".join(f'        {k}: "{v}"\n' for k, v in (e.split("=", 1) for e in envs))
open(f"/root/bench/reth/cfg/{rid}.yaml", "w").write(out)
print("wrote", rid, arm, img, filt, envs)
