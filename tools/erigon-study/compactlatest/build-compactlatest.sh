#!/usr/bin/env bash
# Build compactlatest (and mdbx_copy/mdbx_stat from the same mdbx-go module erigon links) against
# erigon 5f62f4ed, the commit the benchmark image runs. Inputs, in /bench/erigon/compact:
#   erigon-5f62f4ed.tar.gz   `git archive 5f62f4ed` of erigontech/erigon
#   db_state_compact_latest.go, main.go
# Output: /bench/erigon/compact/bin/{compactlatest,mdbx_copy,mdbx_stat}
set -euo pipefail

C=/bench/erigon/compact
rm -rf "$C/src" && mkdir -p "$C/src" "$C/bin" "$C/gocache" "$C/gomod"
tar -xzf "$C/erigon-5f62f4ed.tar.gz" -C "$C/src"
cp "$C/db_state_compact_latest.go" "$C/src/db/state/compact_latest.go"
mkdir -p "$C/src/cmd/compactlatest" && cp "$C/main.go" "$C/src/cmd/compactlatest/main.go"

podman run --rm -v "$C":/c -e GOTOOLCHAIN=go1.25.7 -e GOCACHE=/c/gocache -e GOMODCACHE=/c/gomod \
  -w /c/src docker.io/library/golang:1.25-bookworm bash -euo pipefail -c '
    export CGO_CFLAGS="-O3 -D__BLST_PORTABLE__ -Wno-strict-prototypes -Wno-unused-but-set-variable"
    go version
    go vet ./db/state/ ./cmd/compactlatest/
    go build -trimpath -o /c/bin/compactlatest ./cmd/compactlatest
    m=$(go list -m -f "{{.Dir}}" github.com/erigontech/mdbx-go)
    rm -rf /tmp/mdbx-go && cp -r "$m" /tmp/mdbx-go && chmod -R u+w /tmp/mdbx-go
    cd /tmp/mdbx-go && MDBX_BUILD_TIMESTAMP=unknown make tools >/dev/null
    cp libmdbx/mdbx_copy libmdbx/mdbx_stat /c/bin/
    echo "mdbx-go: $(go -C /c/src list -m github.com/erigontech/mdbx-go)"'
ls -la "$C/bin"
