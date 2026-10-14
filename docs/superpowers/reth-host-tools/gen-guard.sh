#!/bin/bash
# Stop the generation before md2 (the root filesystem) runs out: J scratch is preallocated, the system is not.
while podman ps --format "{{.Names}}" | grep -q sa-gen-reth; do
  f=$(df -m / | awk "NR==2{print \$4}")
  if [ "$f" -lt 100000 ]; then echo "$(date -Is) md2 free ${f}MB < 100GB: stopping sa-gen-reth"; podman stop -t 120 sa-gen-reth; break; fi
  sleep 30
done
echo "guard exit $(date -Is)"
