// Command readprobe measures what an *existing* account read actually costs
// in each store, through the same pathdb reader the EVM uses.
//
// Earlier probes drove eth_getProof over pseudorandom addresses. Those are
// absent from both stores, terminate early, and never read a leaf value, so
// they measure the wrong thing. This samples real account hashes out of the
// store itself (state-actor has no preimages, so hashes are the only handle)
// and reads them back, reporting pathdb's own counters - which do not depend
// on which device the store sits on.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"math/big"
	"math/rand/v2"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/core/rawdb"
	"github.com/ethereum/go-ethereum/ethdb"
	"github.com/ethereum/go-ethereum/ethdb/pebble"
	"github.com/ethereum/go-ethereum/log"
	"github.com/ethereum/go-ethereum/metrics"
)

// procReadBytes reports bytes this process has pulled from the block layer.
func procReadBytes() int64 {
	b, err := os.ReadFile("/proc/self/io")
	if err != nil {
		return 0
	}
	for _, line := range strings.Split(string(b), "\n") {
		if strings.HasPrefix(line, "read_bytes:") {
			var v int64
			fmt.Sscanf(line, "read_bytes: %d", &v)
			return v
		}
	}
	return 0
}

func counter(name string) int64 {
	switch m := metrics.Get(name).(type) {
	case *metrics.Meter:
		return m.Snapshot().Count()
	case *metrics.Counter:
		return m.Snapshot().Count()
	case *metrics.Gauge:
		return m.Snapshot().Value()
	}
	return 0
}

var watch = []string{
	"pathdb/clean/state/hit", "pathdb/clean/state/miss",
	"pathdb/clean/node/hit", "pathdb/clean/node/miss",
	"pathdb/state/account/exist/total", "pathdb/state/account/exist/disk",
	"eth/db/chaindata/cache/block/hit", "eth/db/chaindata/cache/block/miss",
}

func main() {
	datadir := flag.String("datadir", "", "geth datadir")
	label := flag.String("label", "", "report label")
	n := flag.Int("n", 20000, "accounts to read")
	pool := flag.Int("pool", 400000, "account hashes to sample from")
	cache := flag.Int("cache", 16, "pebble cache MB - deliberately small so reads reach disk")
	randomKeys := flag.Bool("randomkeys", false, "read uniformly random hashes instead of sampled ones; matches the benchmark, whose CREATE2 targets are uniform over the keyspace")
	flag.Parse()
	metrics.Enable()
	log.SetDefault(log.NewLogger(log.NewTerminalHandlerWithLevel(os.Stderr, log.LevelWarn, true)))

	chaindata := filepath.Join(*datadir, "geth", "chaindata")
	open := func() ethdb.KeyValueStore {
		var db ethdb.KeyValueStore
		var err error
		if pebble.NeedsV1(chaindata) {
			db, err = pebble.NewV1(chaindata, *cache, 4096, "", false)
		} else {
			db, err = pebble.New(chaindata, *cache, 4096, "", false)
		}
		if err != nil {
			fmt.Fprintf(os.Stderr, "open: %v\n", err)
			os.Exit(1)
		}
		return db
	}
	kv := open()

	// Sample across the WHOLE keyspace. Taking a contiguous run from the start
	// yields a few tens of MB that sit entirely in cache and measure nothing.
	var hashes []common.Hash
	seeks := 500
	per := *pool / seeks
	for sk := range seeks {
		start := common.BigToHash(new(big.Int).Lsh(big.NewInt(int64(sk)), 247)).Bytes()
		it := rawdb.NewKeyLengthIterator(
			kv.NewIterator(rawdb.SnapshotAccountPrefix, start),
			len(rawdb.SnapshotAccountPrefix)+32)
		for i := 0; it.Next() && i < per; i++ {
			hashes = append(hashes, common.BytesToHash(it.Key()[len(rawdb.SnapshotAccountPrefix):]))
		}
		it.Release()
	}
	if len(hashes) == 0 {
		fmt.Fprintln(os.Stderr, "no accounts sampled")
		os.Exit(1)
	}

	// Sampling pulled every one of those blocks into both the OS page cache
	// and pebble's own block cache. Closing the store discards the latter;
	// dropping caches discards the former. Only then are the reads cold.
	_ = kv.Close()
	if err := os.WriteFile("/proc/sys/vm/drop_caches", []byte("3"), 0o600); err != nil {
		fmt.Fprintf(os.Stderr, "warn: could not drop caches: %v\n", err)
	}
	time.Sleep(3 * time.Second)
	kv = open()
	defer kv.Close()

	rnd := rand.New(rand.NewPCG(0x5eed, 0xf00d))
	if *randomKeys {
		// Uniform over the whole keyspace: the sampled-run pattern above is far
		// more clustered than the benchmark's, which walks CREATE2 addresses
		// whose hashes are uniformly distributed.
		hashes = hashes[:0]
		for range *n * 2 {
			var h common.Hash
			for b := range h {
				h[b] = byte(rnd.UintN(256))
			}
			hashes = append(hashes, h)
		}
	}
	rnd.Shuffle(len(hashes), func(i, j int) { hashes[i], hashes[j] = hashes[j], hashes[i] })

	// Warm up so the measurement is steady state, not the boot transient.
	ioBefore := procReadBytes()
	before := map[string]int64{}
	for _, w := range watch {
		before[w] = counter(w)
	}
	var bytesRead, found int
	t0 := time.Now()
	for i := range *n {
		h := hashes[(i*7919+13)%len(hashes)]
		v, err := kv.Get(append(append([]byte{}, rawdb.SnapshotAccountPrefix...), h.Bytes()...))
		if err == nil {
			found++
			bytesRead += len(v)
		}
	}
	wall := time.Since(t0)
	ioDelta := procReadBytes() - ioBefore

	delta := map[string]int64{}
	for _, w := range watch {
		delta[w] = counter(w) - before[w]
	}
	bh := delta["eth/db/chaindata/cache/block/hit"]
	bm := delta["eth/db/chaindata/cache/block/miss"]
	out := map[string]any{
		"label":            *label,
		"pool":             len(hashes),
		"reads":            *n,
		"found":            found,
		"mean_value_bytes": float64(bytesRead) / float64(max(found, 1)),
		"us_per_read":      float64(wall.Microseconds()) / float64(*n),
		"block_lookups":    bh + bm,
		"block_misses":     bm,
		"blocks_per_read":  float64(bh+bm) / float64(*n),
		"misses_per_read":  float64(bm) / float64(*n),
		"disk_bytes_total": ioDelta,
		"disk_bytes_read":  float64(ioDelta) / float64(*n),
		"raw":              delta,
	}
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", " ")
	_ = enc.Encode(out)
}
