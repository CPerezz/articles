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
	"bytes"
	"encoding/binary"
	"encoding/hex"
	"flag"
	"fmt"
	"io"
	"log"
	"math/rand/v2"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/ethereum/go-ethereum/crypto"
	"github.com/linxGnu/grocksdb"

	"github.com/ethereum/state-actor/internal/neth/flat"
)

// readBytes reports bytes this process actually pulled from block devices. Unlike rusage or
// wall time it is immune to page-cache hits, which is the whole point of the measurement.
type LiveFile struct {
	level   int
	size    int64
	entries uint64
}

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
	addrs := flag.String("addrs", "", "comma-separated 20-byte hex addresses for -mode addr")
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

	case "seq":
		// Probe the exact key population the benchmark touches: the EEST fixtures'
		// sequential accounts. Random keys measure the store's average; these measure the
		// stratum the two arms actually read, which is where they can legitimately differ.
		keys := make([][]byte, 0, *n)
		for i := 0; i < *n; i++ {
			addr := make([]byte, 20)
			binary.BigEndian.PutUint64(addr[12:], uint64(0x1000+i))
			keys = append(keys, crypto.Keccak256(addr)[:20])
		}

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
		got := readBytes() - before

		fmt.Printf("db=%s cf=%s (sequential fixture accounts)\n", *dbPath, *cfName)
		fmt.Printf("  lookups        : %d (hits %d, miss %d)\n", len(keys), hits, miss)
		fmt.Printf("  wall           : %.3f s  (%.1f us/lookup)\n", el.Seconds(), float64(el.Microseconds())/float64(len(keys)))
		fmt.Printf("  disk read      : %.1f MB\n", float64(got)/1e6)
		fmt.Printf("  BYTES/LOOKUP   : %.0f\n", float64(got)/float64(len(keys)))
		fmt.Printf("  BLOCKS/LOOKUP  : %.2f (4 KiB blocks)\n", float64(got)/float64(len(keys))/4096)

	case "locate":
		// Where do the fixture keys physically live? Sub-one-block-per-lookup is only
		// possible if they share SST blocks, so count the files that actually cover them
		// and how big those files are. That separates "dense recent stratum" from
		// "ordinary residents of a fully compacted LSM".
		keys := make([][]byte, 0, *n)
		for i := 0; i < *n; i++ {
			addr := make([]byte, 20)
			binary.BigEndian.PutUint64(addr[12:], uint64(0x1000+i))
			keys = append(keys, crypto.Keccak256(addr)[:20])
		}

		all := db.GetLiveFilesMetaData()
		files := all[:0:0]
		for _, f := range all {
			if f.ColumnFamilyName == *cfName {
				files = append(files, f)
			}
		}

		covering := map[string]LiveFile{}
		for _, k := range keys {
			for _, f := range files {
				if bytes.Compare(k, f.SmallestKey) >= 0 && bytes.Compare(k, f.LargestKey) <= 0 {
					covering[f.Name] = LiveFile{f.Level, f.Size, f.Entries}
				}
			}
		}

		byLevel := map[int]int{}
		var coverSize int64
		var coverEntries uint64
		for _, f := range covering {
			byLevel[f.level]++
			coverSize += f.size
			coverEntries += f.entries
		}
		var totalSize int64
		totalLevel := map[int]int{}
		for _, f := range files {
			totalSize += f.Size
			totalLevel[f.Level]++
		}

		fmt.Printf("db=%s cf=%s\n", *dbPath, *cfName)
		fmt.Printf("  CF total       : %d files, %.2f GB, levels %v\n", len(files), float64(totalSize)/1e9, totalLevel)
		fmt.Printf("  keys probed    : %d\n", len(keys))
		fmt.Printf("  covering files : %d  (%.2f GB, %d entries)\n", len(covering), float64(coverSize)/1e9, coverEntries)
		fmt.Printf("  covering levels: %v\n", byLevel)
		fmt.Printf("  entries/key in covering files : %.0f\n", float64(coverEntries)/float64(len(keys)))

	case "keys":
		// Dump raw key shapes so the two stores' encodings can be compared directly.
		it := db.NewIteratorCF(ro, cf)
		defer it.Close()
		it.SeekToFirst()
		lens := map[int]int{}
		shown := 0
		for ; it.Valid() && shown < *n; it.Next() {
			k := it.Key()
			b := make([]byte, k.Size())
			copy(b, k.Data())
			k.Free()
			lens[len(b)]++
			if shown < 5 {
				fmt.Printf("  key[%d] len=%d %x\n", shown, len(b), b)
			}
			shown++
		}
		fmt.Printf("cf=%s scanned=%d key-length histogram: %v\n", *cfName, shown, lens)

	case "addr":
		// The decisive test: does the flat Account CF contain the key Nethermind would compute
		// for an address known to exist in this store? Key = keccak256(address)[0:20].
		for _, a := range strings.Split(*addrs, ",") {
			a = strings.TrimPrefix(strings.TrimSpace(a), "0x")
			raw, err := hex.DecodeString(a)
			if err != nil || len(raw) != 20 {
				log.Fatalf("bad address %q", a)
			}
			h := crypto.Keccak256(raw)
			key := h[:20]
			v, err := db.GetCF(ro, cf, key)
			if err != nil {
				log.Fatalf("get: %v", err)
			}
			fmt.Printf("  addr 0x%s  keccak[0:20]=%x  -> %s (value %d bytes)\n",
				a, key, map[bool]string{true: "FOUND", false: "MISSING"}[v.Exists()], v.Size())
			v.Free()
		}

	case "meta":
		// Dump the Metadata CF: Layout / SlotEncoding / CurrentState markers. CurrentState is
		// 8-byte block number || 32-byte state root, and tells us which state the flat layout
		// is authoritative for.
		it := db.NewIteratorCF(ro, cf)
		defer it.Close()
		it.SeekToFirst()
		for ; it.Valid(); it.Next() {
			k, v := it.Key(), it.Value()
			kb := make([]byte, k.Size())
			copy(kb, k.Data())
			vb := make([]byte, v.Size())
			copy(vb, v.Data())
			k.Free()
			v.Free()
			name := "?"
			switch {
			case len(kb) == 32 && fmt.Sprintf("%x", kb) == fmt.Sprintf("%x", crypto.Keccak256([]byte("CurrentState"))):
				name = "CurrentState"
			case len(kb) == 32 && fmt.Sprintf("%x", kb) == fmt.Sprintf("%x", crypto.Keccak256([]byte("Layout"))):
				name = "Layout"
			case len(kb) == 32 && fmt.Sprintf("%x", kb) == fmt.Sprintf("%x", crypto.Keccak256([]byte("SlotEncoding"))):
				name = "SlotEncoding"
			}
			extra := ""
			if name == "CurrentState" && len(vb) == 40 {
				extra = fmt.Sprintf("   block=%d root=0x%x", binary.BigEndian.Uint64(vb[:8]), vb[8:])
			}
			fmt.Printf("  %-14s key=%x value=%x%s\n", name, kb, vb, extra)
		}

	default:
		log.Fatalf("unknown mode %q", *mode)
	}
}
