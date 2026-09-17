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
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/ethereum/go-ethereum/crypto"
	"github.com/ethereum/go-ethereum/rlp"
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


// statTickers parses RocksDB's statistics dump into a ticker -> count map. The dump is the only
// way grocksdb exposes tickers; there is no typed accessor in this binding.
func statTickers(o *grocksdb.Options) map[string]int64 {
	out := map[string]int64{}
	if o == nil {
		return out
	}
	for _, line := range strings.Split(o.GetStatisticsString(), "\n") {
		f := strings.Fields(line)
		// shape: "<name> COUNT : <n>" and for histograms "<name> P50 : ..."
		if len(f) >= 4 && f[1] == "COUNT" && f[2] == ":" {
			if v, err := strconv.ParseInt(f[3], 10, 64); err == nil {
				out[f[0]] = v
			}
		}
	}
	return out
}

// dbOptsForStats holds the DB-level Options when statistics are enabled, so the filters mode can
// read tickers back out of them.
var dbOptsForStats *grocksdb.Options

// openedCFNames records the column families openRO actually opened.
var openedCFNames []string

func openRO(path string) (*grocksdb.DB, []*grocksdb.ColumnFamilyHandle) {
	opts := grocksdb.NewDefaultOptions()
	opts.SetCreateIfMissing(false)
	opts.EnableStatistics()
	dbOptsForStats = opts
	// Work against any Nethermind RocksDB, not just flat/: the code, state and blocks databases
	// carry their own column-family sets, and DIFF_MAX needs code/ measured directly rather than
	// inferred from the ordering of the account-access modes.
	names := flat.ColumnNames
	if listed, err := grocksdb.ListColumnFamilies(grocksdb.NewDefaultOptions(), path); err == nil &&
		len(listed) > 0 {
		names = listed
	}

	cfOpts := make([]*grocksdb.Options, len(names))
	for i, nm := range names {
		// A reader with no filter_policy configured will not consult the filters that are in the
		// files: RocksDB only builds a filter reader when a policy is set at open. Opening with
		// default options therefore measures any store as if it had no filters at all, which is
		// exactly what made an earlier run of this probe report zero bloom activity on both arms
		// and equal cost for present and absent keys.
		if spec, ok := flatSpecs[nm]; ok {
			cfOpts[i] = specOptions(spec)
		} else {
			cfOpts[i] = grocksdb.NewDefaultOptions()
		}
	}
	openedCFNames = names
	db, hs, err := grocksdb.OpenDbForReadOnlyColumnFamilies(opts, path, names, cfOpts, false)
	if err != nil {
		log.Fatalf("open %s: %v", path, err)
	}
	return db, hs
}

func openRW(path string) (*grocksdb.DB, []*grocksdb.ColumnFamilyHandle) {
	opts := grocksdb.NewDefaultOptions()
	opts.SetCreateIfMissing(false)
	cfOpts := make([]*grocksdb.Options, len(flat.ColumnNames))
	for i := range cfOpts {
		cfOpts[i] = grocksdb.NewDefaultOptions()
	}
	db, hs, err := grocksdb.OpenDbColumnFamilies(opts, path, flat.ColumnNames, cfOpts)
	if err != nil {
		log.Fatalf("open rw %s: %v", path, err)
	}
	return db, hs
}


// compactWholeDB compacts every column family of an arbitrary RocksDB directory. Used for
// Nethermind's non-flat databases (code/, ...), which have their own CF sets.
func compactWholeDB(path string) {
	opts := grocksdb.NewDefaultOptions()
	opts.SetCreateIfMissing(false)
	names, err := grocksdb.ListColumnFamilies(opts, path)
	if err != nil {
		log.Fatalf("list cfs %s: %v", path, err)
	}
	cfOpts := make([]*grocksdb.Options, len(names))
	for i := range cfOpts {
		cfOpts[i] = grocksdb.NewDefaultOptions()
	}
	db, handles, err := grocksdb.OpenDbColumnFamilies(opts, path, names, cfOpts)
	if err != nil {
		log.Fatalf("open rw %s: %v", path, err)
	}
	defer db.Close()

	shape := func() map[int]int {
		m := map[int]int{}
		for _, f := range db.GetLiveFilesMetaData() {
			m[f.Level]++
		}
		return m
	}
	fmt.Printf("db=%s cfs=%v\n", path, names)
	fmt.Printf("  levels before : %v\n", shape())
	start := time.Now()
	for i, h := range handles {
		db.CompactRangeCF(h, grocksdb.Range{Start: nil, Limit: nil})
		fmt.Printf("  compacted cf %-12s (%.1f s elapsed)\n", names[i], time.Since(start).Seconds())
	}
	fmt.Printf("  levels after  : %v\n", shape())
}


// Per-CF table options transcribed from state-actor's OPTIONS, which is the faithful template:
// round 10 established the two stores matched on every read-path knob before any of my edits.
// Writing jochemnet's files with these makes both arms option-identical, so a residual
// difference is placement or content rather than table configuration. An earlier compaction of
// mine used grocksdb defaults and silently dropped the ribbon filter, which inverted the
// non-existing-account control - hence the verify step that diffs OPTIONS afterwards.
type cfSpec struct {
	blockSize   int
	restart     int
	compress    grocksdb.CompressionType
	fileBase    uint64
	fileMult    int
	levelBase   uint64
	dynamic     bool
	ribbon      bool
	dataIdxHash bool
	formatVer   int
	pinL0       bool
}

var flatSpecs = map[string]cfSpec{
	"Account":       {4096, 4, grocksdb.NoCompression, 32000000, 3, 128000000, false, true, true, 5, true},
	"Storage":       {8000, 4, grocksdb.LZ4Compression, 64000000, 2, 256000000, false, true, true, 5, true},
	"StateNodes":    {16000, 8, grocksdb.LZ4Compression, 64000000, 2, 256000000, true, true, true, 5, true},
	"StateTopNodes": {16000, 8, grocksdb.LZ4Compression, 64000000, 2, 256000000, true, true, true, 5, true},
	"StorageNodes":  {16000, 8, grocksdb.LZ4Compression, 64000000, 2, 350000000, true, true, true, 5, true},
	"FallbackNodes": {16000, 8, grocksdb.LZ4Compression, 64000000, 2, 4000000, true, true, true, 5, true},
	"Metadata":      {16000, 4, grocksdb.LZ4Compression, 64000000, 2, 1000000, false, true, true, 5, true},
	"default":       {4096, 16, grocksdb.SnappyCompression, 67108864, 1, 268435456, true, false, false, 6, false},
}

func specOptions(s cfSpec) *grocksdb.Options {
	o := grocksdb.NewDefaultOptions()
	o.SetCreateIfMissing(false)
	// Only the explicit CompactRange may write files. A background compaction would rewrite an
	// untouched CF and change its layout behind our backs, which is the whole failure mode here.
	o.SetDisableAutoCompactions(true)
	o.SetCompression(s.compress)
	o.SetTargetFileSizeBase(s.fileBase)
	o.SetTargetFileSizeMultiplier(s.fileMult)
	o.SetMaxBytesForLevelBase(s.levelBase)
	o.SetLevelCompactionDynamicLevelBytes(s.dynamic)

	b := grocksdb.NewDefaultBlockBasedTableOptions()
	b.SetBlockSize(s.blockSize)
	b.SetBlockRestartInterval(s.restart)
	b.SetWholeKeyFiltering(true)
	b.SetFormatVersion(s.formatVer)
	b.SetIndexType(grocksdb.KBinarySearchIndexType)
	b.SetCacheIndexAndFilterBlocks(false)
	b.SetPinL0FilterAndIndexBlocksInCache(s.pinL0)
	if s.ribbon {
		b.SetFilterPolicy(grocksdb.NewRibbonHybridFilterPolicy(10, 3))
	}
	if s.dataIdxHash {
		b.SetDataBlockIndexType(grocksdb.KDataBlockIndexTypeBinarySearchAndHash)
	}
	o.SetBlockBasedTableFactory(b)
	return o
}

// rebuildCFs force-rewrites the named column families with correct options. kForce is required:
// a CF already sitting entirely in its bottom level is a no-op for a plain CompactRange, so the
// wrong-option files would survive untouched.
func rebuildCFs(path string, want []string, targetLevel int) {
	cfOpts := make([]*grocksdb.Options, len(flat.ColumnNames))
	for i, nm := range flat.ColumnNames {
		spec, ok := flatSpecs[nm]
		if !ok {
			log.Fatalf("no option spec for cf %q", nm)
		}
		cfOpts[i] = specOptions(spec)
	}
	dbOpts := grocksdb.NewDefaultOptions()
	dbOpts.SetCreateIfMissing(false)
	dbOpts.SetDisableAutoCompactions(true)

	db, handles, err := grocksdb.OpenDbColumnFamilies(dbOpts, path, flat.ColumnNames, cfOpts)
	if err != nil {
		log.Fatalf("open rw %s: %v", path, err)
	}
	defer db.Close()

	shape := func(cf string) (map[int]int, float64) {
		m := map[int]int{}
		var sz int64
		for _, f := range db.GetLiveFilesMetaData() {
			if f.ColumnFamilyName == cf {
				m[f.Level]++
				sz += f.Size
			}
		}
		return m, float64(sz) / 1e9
	}

	cro := grocksdb.NewCompactRangeOptions()
	cro.SetBottommostLevelCompaction(grocksdb.KForce)
	// The default target (-1) is "the deepest level that already has files". A generated store
	// whose data is parked at L3 therefore gets rewritten *into L3* and stays compaction-pending;
	// the round-18 rebuild only reached L6 on jochemnet because its data was already there.
	if targetLevel >= 0 {
		// target_level is ignored unless change_level is set: RocksDB only relocates output
		// files when explicitly told the level may change.
		cro.SetChangeLevel(true)
		cro.SetTargetLevel(int32(targetLevel))
	}

	for _, cf := range want {
		cf = strings.TrimSpace(cf)
		idx := -1
		for i, nm := range flat.ColumnNames {
			if nm == cf {
				idx = i
			}
		}
		if idx < 0 {
			log.Fatalf("unknown cf %q", cf)
		}
		lv, gb := shape(cf)
		fmt.Printf("  %-14s before: %v  %.2f GB\n", cf, lv, gb)
		start := time.Now()
		db.CompactRangeCFOpt(handles[idx], grocksdb.Range{Start: nil, Limit: nil}, cro)
		lv, gb = shape(cf)
		fmt.Printf("  %-14s after : %v  %.2f GB  (%.1f s)\n", cf, lv, gb, time.Since(start).Seconds())
	}
}

func main() {
	dbPath := flag.String("db", "", "path to the flat/ RocksDB directory")
	mode := flag.String("mode", "sample", "sample | probe")
	cfName := flag.String("cf", "Account", "column family to probe")
	n := flag.Int("n", 5000, "number of keys")
	keysFile := flag.String("keys", "/tmp/probe-keys.bin", "key file to write/read")
	seed := flag.Uint64("seed", 42, "sampling seed")
	addrs := flag.String("addrs", "", "comma-separated 20-byte hex addresses for -mode addr")
	// Shifting the address base turns the same probe into a pure-miss workload, which is how
	// filter loss shows up: a filter only ever saves work on keys that are absent.
	abase := flag.Uint64("abase", 0x1000, "first synthetic account address for -mode seq")
	db2Path := flag.String("db2", "", "second database (the code/ store) for -mode codesize")
	minSize := flag.Int("minsize", 24000, "minimum code size for -mode codesample")
	targetLevel := flag.Int("level", -1, "output level for -mode rebuild (-1 = deepest level that already has files)")
	flag.Parse()
	if *dbPath == "" {
		log.Fatal("-db required")
	}

	if *mode == "rebuild" {
		rebuildCFs(*dbPath, strings.Split(*cfName, ","), *targetLevel)
		return
	}

	if *mode == "compactdb" {
		compactWholeDB(*dbPath)
		return
	}

	var db *grocksdb.DB
	var handles []*grocksdb.ColumnFamilyHandle
	if *mode == "compact" {
		db, handles = openRW(*dbPath)
	} else {
		db, handles = openRO(*dbPath)
	}
	defer db.Close()
	cfIdx := -1
	for i, nm := range openedCFNames {
		if nm == *cfName {
			cfIdx = i
		}
	}
	if cfIdx < 0 {
		log.Fatalf("unknown cf %q; have %v", *cfName, openedCFNames)
	}

	cf := handles[cfIdx]
	ro := grocksdb.NewDefaultReadOptions()
	ro.SetFillCache(false) // each lookup must pay its own way

	// The control-test gap is ~96 MB of reads for a payload that touches no accounts. A cold
	// client must fault in each SST's index and filter before it can answer anything, and those
	// blocks live outside the block cache when cache_index_and_filter_blocks is false. So the
	// per-CF index+filter footprint is a candidate for a fixed per-boot cost, and RocksDB will
	// report it without a new binding: aggregated-table-properties is a plain string property.
	if *mode == "props" {
		for i, nm := range openedCFNames {
			fmt.Printf("######## CF %s ########\n", nm)
			for _, p := range []string{
				"rocksdb.aggregated-table-properties",
				"rocksdb.levelstats",
				"rocksdb.estimate-num-keys",
				"rocksdb.total-sst-files-size",
				"rocksdb.live-sst-files-size",
				// Whether RocksDB considers this CF's shape unfinished. A generated store can
				// leave files parked at intermediate levels; the client then compacts in the
				// background on every open, and a per-test image restore discards the work.
				"rocksdb.compaction-pending",
				"rocksdb.estimate-pending-compaction-bytes",
				"rocksdb.num-running-compactions",
			} {
				v := db.GetPropertyCF(p, handles[i])
				if v == "" {
					continue
				}
				fmt.Printf("---- %s\n%s\n", p, strings.TrimRight(v, "\n"))
			}
		}
		return
	}

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

	case "dump":
		// Full key+value dump, for column families small enough to read whole. The Metadata CF
		// holds a handful of entries the client consults at boot to decide how to treat the flat
		// store, and the two arms have a different number of them.
		it := db.NewIteratorCF(ro, cf)
		defer it.Close()
		shown := 0
		for it.SeekToFirst(); it.Valid() && shown < *n; it.Next() {
			k, v := it.Key(), it.Value()
			fmt.Printf("  key=%x\n  val=%x  (%d bytes)\n", k.Data(), v.Data(), v.Size())
			k.Free()
			v.Free()
			shown++
		}
		fmt.Printf("cf=%s entries dumped=%d\n", *cfName, shown)

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
			binary.BigEndian.PutUint64(addr[12:], *abase+uint64(i))
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
			binary.BigEndian.PutUint64(addr[12:], *abase+uint64(i))
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

	case "compact":
		// Causal intervention: merge the column family into its bottom level. This destroys
		// the clustering that a recent write burst leaves behind, without changing a single
		// value. If clustering is what makes the fixture keys cheap, this alone must erase
		// the advantage.
		levels := func() map[int]int {
			m := map[int]int{}
			for _, f := range db.GetLiveFilesMetaData() {
				if f.ColumnFamilyName == *cfName {
					m[f.Level]++
				}
			}
			return m
		}
		fmt.Printf("  levels before : %v\n", levels())
		start := time.Now()
		db.CompactRangeCF(cf, grocksdb.Range{Start: nil, Limit: nil})
		fmt.Printf("  compaction    : %.1f s\n", time.Since(start).Seconds())
		fmt.Printf("  levels after  : %v\n", levels())

	case "filters":
		// Do these SST files actually carry filters, and do the filters reject absent keys?
		//
		// Counting bytes cannot answer this: a column family built with no filter policy and one
		// whose filter is present but never consulted read identically. RocksDB's own bloom
		// tickers can - bloom.filter.useful counts negatives a filter rejected without touching
		// a data block. Besu's study found a generated store written with no filters at all, so
		// this is the same class of defect being checked for on Nethermind.
		present := make([][]byte, 0, *n)
		absent := make([][]byte, 0, *n)
		for i := 0; i < *n; i++ {
			a1, a2 := make([]byte, 20), make([]byte, 20)
			binary.BigEndian.PutUint64(a1[12:], *abase+uint64(i))
			binary.BigEndian.PutUint64(a2[12:], 0x900000000+uint64(i))
			present = append(present, crypto.Keccak256(a1)[:20])
			absent = append(absent, crypto.Keccak256(a2)[:20])
		}

		run := func(keys [][]byte) (hits, miss int, bytes uint64, el time.Duration) {
			before := readBytes()
			t0 := time.Now()
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
			return hits, miss, readBytes() - before, time.Since(t0)
		}

		// Warm the table readers first: on a cold handle the first lookups pay for index and
		// filter blocks, which would otherwise be charged to whichever phase ran first.
		run(present[:min(len(present), 2000)])

		for _, phase := range []struct {
			name string
			keys [][]byte
		}{{"absent keys", absent}, {"present keys", present}} {
			s0 := statTickers(dbOptsForStats)
			h, m, by, el := run(phase.keys)
			s1 := statTickers(dbOptsForStats)
			fmt.Printf("  %-13s n=%d hits=%d miss=%d  %6.1f us/lookup  %7.0f bytes/lookup\n",
				phase.name, len(phase.keys), h, m,
				float64(el.Microseconds())/float64(len(phase.keys)),
				float64(by)/float64(len(phase.keys)))
			for _, t := range []string{
				"rocksdb.bloom.filter.useful",
				"rocksdb.bloom.filter.full.positive",
				"rocksdb.bloom.filter.full.true.positive",
				"rocksdb.block.cache.filter.hit",
				"rocksdb.block.cache.filter.miss",
				"rocksdb.table.open.io.micros",
			} {
				d := s1[t] - s0[t]
				if d != 0 || strings.Contains(t, "bloom") {
					fmt.Printf("      %-42s %d\n", t, d)
				}
			}
		}

	case "codesize":
		// What does an *additional distinct contract* cost? Random code lookups said the generated
		// store is the cheaper one per read, so the DIFF_MAX residual cannot be "its code database
		// is bigger". It has to come from the size, or the number, of the contracts the fixtures
		// actually touch - which random sampling never looks at. This walks the fixture address
		// range, pulls each account's codeHash out of its slim-RLP row, and measures the code
		// entry it points at.
		if *db2Path == "" {
			log.Fatal("-db2 (the code database) is required for -mode codesize")
		}
		codeDB, codeHandles := openRO(*db2Path)
		defer codeDB.Close()
		codeCF := codeHandles[0]
		for i, nm := range openedCFNames {
			if nm == "default" {
				codeCF = codeHandles[i]
			}
		}

		var sizes []int
		accounts, withCode, undecodable, shown := 0, 0, 0, 0
		for i := 0; i < *n; i++ {
			addr := make([]byte, 20)
			binary.BigEndian.PutUint64(addr[12:], *abase+uint64(i))
			v, err := db.GetCF(ro, cf, crypto.Keccak256(addr)[:20])
			if err != nil {
				log.Fatalf("account get: %v", err)
			}
			if !v.Exists() {
				v.Free()
				continue
			}
			raw := make([]byte, v.Size())
			copy(raw, v.Data())
			v.Free()
			accounts++

			var fields [][]byte
			if err := rlp.DecodeBytes(raw, &fields); err != nil {
				undecodable++
				if shown < 3 {
					fmt.Printf("  undecodable account row (%d bytes): %x\n", len(raw), raw)
					shown++
				}
				continue
			}
			if len(fields) < 4 || len(fields[3]) != 32 {
				continue
			}
			withCode++
			cv, err := codeDB.GetCF(ro, codeCF, fields[3])
			if err != nil {
				log.Fatalf("code get: %v", err)
			}
			if cv.Exists() {
				sizes = append(sizes, cv.Size())
			}
			cv.Free()
		}

		fmt.Printf("  addresses probed : %d\n", *n)
		fmt.Printf("  accounts present : %d (undecodable rows %d)\n", accounts, undecodable)
		fmt.Printf("  with code        : %d, code entries found %d\n", withCode, len(sizes))
		if len(sizes) > 0 {
			sort.Ints(sizes)
			sum := 0
			for _, x := range sizes {
				sum += x
			}
			fmt.Printf("  code size bytes  : min %d  p50 %d  p90 %d  max %d  mean %d\n",
				sizes[0], sizes[len(sizes)/2], sizes[9*len(sizes)/10], sizes[len(sizes)-1],
				sum/len(sizes))
			fmt.Printf("  total code bytes : %d over %d contracts\n", sum, len(sizes))
		}

	case "codescan":
		// The fixture EOA range carries no code, so characterise the contract population of each
		// store directly: walk the account family, pull codeHash out of the rows that have one,
		// and measure the code entry behind it. If one store's contracts are uniformly maximal
		// and the other's follow mainnet's size distribution, then "a different contract per
		// access" costs a different amount on each, which is what DIFF_MAX measures.
		if *db2Path == "" {
			log.Fatal("-db2 (the code database) is required for -mode codescan")
		}
		codeDB, codeHandles := openRO(*db2Path)
		defer codeDB.Close()
		codeCF := codeHandles[0]
		for i, nm := range openedCFNames {
			if nm == "default" {
				codeCF = codeHandles[i]
			}
		}

		it := db.NewIteratorCF(ro, cf)
		defer it.Close()
		var sizes []int
		scanned, withCode := 0, 0
		for it.SeekToFirst(); it.Valid() && scanned < *n; it.Next() {
			v := it.Value()
			raw := make([]byte, v.Size())
			copy(raw, v.Data())
			v.Free()
			scanned++

			var fields [][]byte
			if err := rlp.DecodeBytes(raw, &fields); err != nil {
				continue
			}
			if len(fields) < 4 || len(fields[3]) != 32 {
				continue
			}
			withCode++
			cv, err := codeDB.GetCF(ro, codeCF, fields[3])
			if err != nil {
				log.Fatalf("code get: %v", err)
			}
			if cv.Exists() {
				sizes = append(sizes, cv.Size())
			}
			cv.Free()
		}

		fmt.Printf("  accounts scanned : %d\n", scanned)
		fmt.Printf("  with code        : %d (%.2f%%), code entries resolved %d\n",
			withCode, 100*float64(withCode)/float64(max(scanned, 1)), len(sizes))
		if len(sizes) > 0 {
			sort.Ints(sizes)
			sum := 0
			for _, x := range sizes {
				sum += x
			}
			atMax := 0
			for _, x := range sizes {
				if x >= 24000 {
					atMax++
				}
			}
			fmt.Printf("  code size bytes  : min %d  p10 %d  p50 %d  p90 %d  max %d  mean %d\n",
				sizes[0], sizes[len(sizes)/10], sizes[len(sizes)/2],
				sizes[9*len(sizes)/10], sizes[len(sizes)-1], sum/len(sizes))
			fmt.Printf("  at/above 24000 B : %d of %d (%.1f%%)\n",
				atMax, len(sizes), 100*float64(atMax)/float64(len(sizes)))
		}

	case "codesample":
		// Collect the code hashes of large contracts so a cold *sweep* of distinct contracts can
		// be measured. Single-lookup probes said the generated store is cheaper per read; a sweep
		// is a different question, because touching N distinct entries in a 45 GB database shares
		// far fewer physical blocks than touching N in a 7.6 GB one.
		if *db2Path == "" {
			log.Fatal("-db2 (the code database) is required for -mode codesample")
		}
		codeDB, codeHandles := openRO(*db2Path)
		defer codeDB.Close()
		codeCF := codeHandles[0]
		for i, nm := range openedCFNames {
			if nm == "default" {
				codeCF = codeHandles[i]
			}
		}

		f, err := os.Create(*keysFile)
		if err != nil {
			log.Fatalf("create %s: %v", *keysFile, err)
		}
		wtr := bufio.NewWriter(f)
		it := db.NewIteratorCF(ro, cf)
		defer it.Close()
		scanned, kept := 0, 0
		var shape struct{ n, size, jd, push, distinct int }
		for it.SeekToFirst(); it.Valid() && kept < *n; it.Next() {
			v := it.Value()
			raw := make([]byte, v.Size())
			copy(raw, v.Data())
			v.Free()
			scanned++

			var fields [][]byte
			if err := rlp.DecodeBytes(raw, &fields); err != nil {
				continue
			}
			if len(fields) < 4 || len(fields[3]) != 32 {
				continue
			}
			cv, err := codeDB.GetCF(ro, codeCF, fields[3])
			if err != nil {
				log.Fatalf("code get: %v", err)
			}
			big := cv.Exists() && cv.Size() >= *minSize
			if big && shape.n < 64 {
				// DIFF_MAX executes each store's *own* max-size contracts, so their bytecode
				// shape - not their size - is what a per-contract analysis cost depends on.
				// Jumpdest analysis marks every 0x5b outside PUSH data; a filler of JUMPDESTs
				// is the pathological case for any set-based implementation.
				code := cv.Data()
				jd, push, distinct := 0, 0, map[byte]bool{}
				for i := 0; i < len(code); i++ {
					b := code[i]
					distinct[b] = true
					if b >= 0x60 && b <= 0x7f { // PUSH1..PUSH32: skip immediate data
						push++
						i += int(b - 0x5f)
						continue
					}
					if b == 0x5b {
						jd++
					}
				}
				shape.n++
				shape.size += len(code)
				shape.jd += jd
				shape.push += push
				shape.distinct += len(distinct)
				if shape.n <= 3 {
					fmt.Printf("  code[%d] size=%d jumpdest=%d push=%d distinct_bytes=%d head=%x\n",
						shape.n, len(code), jd, push, len(distinct), code[:min(48, len(code))])
				}
			}
			cv.Free()
			if !big {
				continue
			}
			if err := binary.Write(wtr, binary.LittleEndian, uint16(len(fields[3]))); err != nil {
				log.Fatal(err)
			}
			if _, err := wtr.Write(fields[3]); err != nil {
				log.Fatal(err)
			}
			kept++
		}
		wtr.Flush()
		f.Close()
		fmt.Printf("scanned %d accounts, kept %d code hashes of >= %d bytes -> %s\n",
			scanned, kept, *minSize, *keysFile)
		if shape.n > 0 {
			fmt.Printf("BYTECODE SHAPE over %d max-size contracts: avg size=%d avg jumpdest=%d avg push=%d avg distinct_bytes=%d\n",
				shape.n, shape.size/shape.n, shape.jd/shape.n, shape.push/shape.n, shape.distinct/shape.n)
		}

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
