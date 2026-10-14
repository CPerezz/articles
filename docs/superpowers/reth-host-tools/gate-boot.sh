#!/bin/bash
# Boot reth on a store the way benchmarkoor does (same flags), wait for RPC, record head, then 60 s idle I/O.
# usage: gate-boot.sh <tag> <datadir> <genesis.json> <image> <scratch loop> <era dm name>
tag=$1 dd=$2 gen=$3 img=$4 loop=$5 era=$6; L=/root/bench/reth/logs/gate-$tag; mkdir -p $L
openssl rand -hex 32 > $L/jwt
podman rm -f rgate >/dev/null 2>&1
sync; echo 3 > /proc/sys/vm/drop_caches
cat /sys/block/$loop/stat > $L/loop-before; dmsetup status $era > $L/era-before
t0=$(date +%s)
podman run -d --name rgate --stop-timeout 600 --ulimit nofile=1048576:1048576 -p 127.0.0.1:18545:8545 \
  -v $dd:/var/lib/reth -v $gen:/tmp/genesis.json:ro -v $L/jwt:/tmp/jwtsecret:ro $img \
  node --datadir=/var/lib/reth --http --http.addr=0.0.0.0 --http.api=admin,debug,eth,net,web3,rpc,reth --http.port=8545 \
  --authrpc.jwtsecret=/tmp/jwtsecret --authrpc.addr=0.0.0.0 --authrpc.port=8551 --engine.disable-precompile-cache \
  --debug.skip-genesis-validation --full --chain=/tmp/genesis.json > $L/cid
rpc() { curl -s --max-time 5 -H "content-type: application/json" -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"$1\",\"params\":$2}" http://127.0.0.1:18545; }
for i in $(seq 1 1200); do r=$(rpc eth_blockNumber "[]"); [ -n "$r" ] && break; podman ps -q --filter name=rgate | grep -q . || break; sleep 1; done
t1=$(date +%s); echo "rpc_ready_s=$((t1-t0))" > $L/summary
echo "blockNumber=$(rpc eth_blockNumber "[]")" >> $L/summary
echo "latest=$(rpc eth_getBlockByNumber "[\"latest\",false]" | python3 -c "import json,sys; r=json.load(sys.stdin)[\"result\"]; print(int(r[\"number\"],16), r[\"hash\"], r[\"stateRoot\"])" 2>&1)" >> $L/summary
echo "genesis=$(rpc eth_getBlockByNumber "[\"0x0\",false]" | python3 -c "import json,sys; r=json.load(sys.stdin)[\"result\"]; print(r[\"hash\"], r[\"stateRoot\"])" 2>&1)" >> $L/summary
pid=$(podman inspect -f "{{.State.Pid}}" rgate)
cat /sys/block/$loop/stat > $L/loop-ready; cat /proc/$pid/io > $L/io-ready 2>/dev/null; dmsetup status $era > $L/era-ready
sleep 60
cat /sys/block/$loop/stat > $L/loop-idle60; cat /proc/$pid/io > $L/io-idle60 2>/dev/null; dmsetup status $era > $L/era-idle60
python3 - $L >> $L/summary <<"PY2"
import sys
L = sys.argv[1]
def st(n): v = open(f"{L}/{n}").read().split(); return int(v[2]) * 512, int(v[6]) * 512
def io(n):
    try: return dict(l.split(": ") for l in open(f"{L}/{n}").read().split("\n") if l)
    except Exception: return {}
b, r, i = st("loop-before"), st("loop-ready"), st("loop-idle60")
print(f"scratch boot: read {(r[0]-b[0])/1e6:.1f} MB written {(r[1]-b[1])/1e6:.1f} MB")
print(f"scratch idle60: read {(i[0]-r[0])/1e6:.1f} MB written {(i[1]-r[1])/1e6:.1f} MB")
a, z = io("io-ready"), io("io-idle60")
if a and z: print(f"proc idle60: read_bytes {(int(z['read_bytes'])-int(a['read_bytes']))/1e6:.1f} MB write_bytes {(int(z['write_bytes'])-int(a['write_bytes']))/1e6:.1f} MB")
PY2
echo "era: $(cat $L/era-before) -> $(cat $L/era-idle60)" >> $L/summary
podman logs rgate > $L/reth.log 2>&1
podman stop -t 600 rgate > /dev/null; podman rm rgate > /dev/null
cat /sys/block/$loop/stat > $L/loop-stopped
cat $L/summary
