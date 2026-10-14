#!/bin/bash
while podman ps --format "{{.Names}}" | grep -q sa-gen-reth; do echo "$(date -Is) sa-gen=$(du -sm /sa-gen | cut -f1)MB spill=$(du -sm /data/spill-reth | cut -f1)MB md2free=$(df -m / | awk "NR==2{print \$4}")MB"; sleep 600; done
