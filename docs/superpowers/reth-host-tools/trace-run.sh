#!/bin/bash
# usage: trace-run.sh <rid> <J|S>: run cfg/<rid>.yaml while tracing page-cache inserts of mdbx.dat
# (scratch FS) and of the loop backing image (md2 FS). Output logs/<rid>.log, logs/<rid>.pc
cd /root/bench/reth
RID=$1; A=$([ "$2" = J ] && echo joc || echo sa)
ST=/var/lib/schelk/reth-$A.json; MNT=/schelk-$A; IMGF=/schelk-vols/reth-$A-scratch.img
SCHELK_STATE=$ST schelk -y restore > /dev/null 2>&1
[ -f $MNT/reth/db/mdbx.dat ] || { echo "no mdbx.dat on $MNT"; exit 1; }
INO=$(stat -c %i $MNT/reth/db/mdbx.dat); BINO=$(stat -c %i $IMGF)
echo "inodes mdbx=$INO backing=$BINO" > logs/$RID.pc
BPFTRACE_PERF_RB_PAGES=2048 bpftrace -e "tracepoint:filemap:mm_filemap_add_to_page_cache /args->i_ino == $INO || args->i_ino == $BINO/ { printf(\"%s %lu %lu %u\n\", strftime(\"%s.%f\", nsecs), args->i_ino, args->index, args->order); }" >> logs/$RID.pc 2>&1 &
BP=$!
sleep 8
env SCHELK_STATE=$ST timeout 14400 benchmarkoor run --config cfg/$RID.yaml > logs/$RID.log 2>&1
echo "BENCH-EXIT $?" >> logs/$RID.log
sleep 2; kill -INT $BP; wait $BP
echo TRACE-DONE $RID
