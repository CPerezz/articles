// probe-flat measures the physical cost of a single account point-lookup in a Nethermind
// flat-state RocksDB, independently of Nethermind and of the benchmark harness.
//
// Why this exists: the two study arms diverge ~16x on account-reading tests while agreeing
// exactly on storage-slot tests, and the RocksDB configuration of the two stores is identical
// (same ribbon filter policy, whole_key_filtering, 4 KB blocks, kBinarySearch, no compression).
// This tool removes every variable except the store itself: same key count, same random access
// pattern, same process, measuring bytes actually pulled from disk via /proc/self/io.
//
//	go build -tags=cgo_neth -buildvcs=false -o /tmp/probe-flat ./scripts/probe-flat
//	probe-flat -db <datadir>/flat -mode sample -n 5000 -keys /tmp/k.bin
//	(drop caches)
//	probe-flat -db <datadir>/flat -mode probe  -keys /tmp/k.bin
//
//go:build cgo_neth

package main

import (
	"bufio"
	"encoding/binary"
	"flag"
	"fmt"
	"io"
	"log"
	"math/rand/v2"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/linxGnu/grocksdb"

	"github.com/ethereum/state-actor/internal/neth/flat"
)

// readBytes reports bytes this process actually pulled from block devices. Unlike rusage or
// wall time it is immune to page-cache hits, which is the whole point of the measurement.
func readBytes() uint64 {
	b, err := os.ReadFile("/proc/self/io")
	if err != nil {
		return 0
	}
	for _, line := range strings.Split(string(b), "\n") {
		if strings.HasPrefix(line, "read_bytes:") {
			v, _ := strconv.ParseUint(strings.TrimSpace(strings.TrimPrefix(line, "read_bytes:")), 10, 64)
			return v
		}
	}
	return 0
}

func openRO(path string) (*grocksdb.DB, []*grocksdb.ColumnFamilyHandle) {
	opts := grocksdb.NewDefaultOptions()
	opts.SetCreateIfMissing(false)
	cfOpts := make([]*grocksdb.Options, len(flat.ColumnNames))
	for i := range cfOpts {
		cfOpts[i] = grocksdb.NewDefaultOptions()
	}
	db, hs, err := grocksdb.OpenDbForReadOnlyColumnFamilies(opts, path, flat.ColumnNames, cfOpts, false)
	if err != nil {
		log.Fatalf("open %s: %v", path, err)
	}
	return db, hs
}

func main() {
	dbPath := flag.String("db", "", "path to the flat/ RocksDB directory")
	mode := flag.String("mode", "sample", "sample | probe")
	cfName := flag.String("cf", "Account", "column family to probe")
	n := flag.Int("n", 5000, "number of keys")
	keysFile := flag.String("keys", "/tmp/probe-keys.bin", "key file to write/read")
	seed := flag.Uint64("seed", 42, "sampling seed")
	flag.Parse()
	if *dbPath == "" {
		log.Fatal("-db required")
	}

	cfIdx := -1
	for i, nm := range flat.ColumnNames {
		if nm == *cfName {
			cfIdx = i
		}
	}
	if cfIdx < 0 {
		log.Fatalf("unknown cf %q; have %v", *cfName, flat.ColumnNames)
	}

	db, handles := openRO(*dbPath)
	defer db.Close()
	cf := handles[cfIdx]
	ro := grocksdb.NewDefaultReadOptions()
	ro.SetFillCache(false) // each lookup must pay its own way

	switch *mode {
	case "sample":
		// Walk the CF and keep every stride-th key, giving a spread across the whole keyspace
		// rather than a contiguous run (a contiguous run would sit in a handful of blocks and
		// understate per-lookup cost — the mistake round 13 of the geth study made).
		// Keys are hashes, so uniformly random 32-byte seek targets give a uniform spread over
		// the whole keyspace. Iterating a contiguous prefix instead would land in a handful of
		// SSTs and understate per-lookup cost.
		r := rand.New(rand.NewPCG(*seed, 0xA5A5))
		it := db.NewIteratorCF(ro, cf)
		defer it.Close()
		f, err := os.Create(*keysFile)
		if err != nil {
			log.Fatal(err)
		}
		w := bufio.NewWriter(f)
		count := 0
		for count < *n {
			seek := make([]byte, 32)
			for i := 0; i < 4; i++ {
				binary.LittleEndian.PutUint64(seek[i*8:], r.Uint64())
			}
			it.Seek(seek)
			if !it.Valid() {
				it.SeekToFirst()
				if !it.Valid() {
					log.Fatal("column family is empty")
				}
			}
			k := it.Key()
			b := make([]byte, k.Size())
			copy(b, k.Data())
			k.Free()
			binary.Write(w, binary.LittleEndian, uint16(len(b)))
			w.Write(b)
			count++
		}
		w.Flush()
		f.Close()
		fmt.Printf("sampled %d random-seek keys from cf=%s -> %s\n", count, *cfName, *keysFile)

	case "probe":
		f, err := os.Open(*keysFile)
		if err != nil {
			log.Fatal(err)
		}
		r := bufio.NewReader(f)
		var keys [][]byte
		for {
			var l uint16
			if err := binary.Read(r, binary.LittleEndian, &l); err != nil {
				break
			}
			k := make([]byte, l)
			// bufio.Read may return a short read without error; that desynchronises the
			// stream and turns every subsequent key into garbage (observed: identical
			// hit/miss counts across two different databases).
			if _, err := io.ReadFull(r, k); err != nil {
				break
			}
			keys = append(keys, k)
		}
		f.Close()

		before := readBytes()
		start := time.Now()
		hits, miss := 0, 0
		for _, k := range keys {
			v, err := db.GetCF(ro, cf, k)
			if err != nil {
				log.Fatalf("get: %v", err)
			}
			if v.Exists() {
				hits++
			} else {
				miss++
			}
			v.Free()
		}
		el := time.Since(start)
		after := readBytes()

		got := after - before
		fmt.Printf("db=%s cf=%s\n", *dbPath, *cfName)
		fmt.Printf("  lookups        : %d (hits %d, miss %d)\n", len(keys), hits, miss)
		fmt.Printf("  wall           : %.3f s  (%.1f us/lookup)\n", el.Seconds(), float64(el.Microseconds())/float64(len(keys)))
		fmt.Printf("  disk read      : %.1f MB\n", float64(got)/1e6)
		fmt.Printf("  BYTES/LOOKUP   : %.0f\n", float64(got)/float64(len(keys)))
		fmt.Printf("  BLOCKS/LOOKUP  : %.2f  (4 KiB blocks)\n", float64(got)/float64(len(keys))/4096)

	default:
		log.Fatalf("unknown mode %q", *mode)
	}
}
