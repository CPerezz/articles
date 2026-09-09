// Command sstgeom reads the real block geometry out of pebble SST files.
//
// The question it answers: a point lookup fetches one block, so record size
// should be irrelevant - unless the physical block itself differs in size.
// This reports, per SST, the compressed data-block size, how many records a
// block holds, and the compression ratio, restricted to whichever keyspace
// the file covers.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"sort"

	"github.com/cockroachdb/pebble/sstable"
	"github.com/cockroachdb/pebble/vfs"
)

type row struct {
	File        string  `json:"file"`
	FirstPrefix string  `json:"first_key_prefix"`
	NumEntries  uint64  `json:"entries"`
	DataBlocks  uint64  `json:"data_blocks"`
	DataSize    uint64  `json:"data_size"`
	IndexSize   uint64  `json:"index_size"`
	RawKV       uint64  `json:"raw_key_value_bytes"`
	BytesPerBlk float64 `json:"compressed_bytes_per_block"`
	EntriesPerB float64 `json:"entries_per_block"`
	Compression string  `json:"compression"`
	Ratio       float64 `json:"physical_over_logical"`
}

func inspect(path string) (*row, error) {
	f, err := vfs.Default.Open(path)
	if err != nil {
		return nil, err
	}
	readable, err := sstable.NewSimpleReadable(f)
	if err != nil {
		return nil, err
	}
	r, err := sstable.NewReader(readable, sstable.ReaderOptions{})
	if err != nil {
		return nil, err
	}
	defer r.Close()
	p := r.Properties

	first := "?"
	it, err := r.NewIter(nil, nil)
	if err == nil {
		if k, _ := it.First(); k != nil && len(k.UserKey) > 0 {
			first = fmt.Sprintf("%q", string(k.UserKey[:1]))
		}
		it.Close()
	}
	raw := p.RawKeySize + p.RawValueSize
	out := &row{
		File: filepath.Base(path), FirstPrefix: first,
		NumEntries: p.NumEntries, DataBlocks: p.NumDataBlocks,
		DataSize: p.DataSize, IndexSize: p.IndexSize, RawKV: raw,
		Compression: p.CompressionName,
	}
	if p.NumDataBlocks > 0 {
		out.BytesPerBlk = float64(p.DataSize) / float64(p.NumDataBlocks)
		out.EntriesPerB = float64(p.NumEntries) / float64(p.NumDataBlocks)
	}
	if raw > 0 {
		out.Ratio = float64(p.DataSize) / float64(raw)
	}
	return out, nil
}

func main() {
	dir := flag.String("dir", "", "chaindata directory")
	label := flag.String("label", "", "report label")
	want := flag.String("prefix", "a", "only report SSTs whose first key starts with this byte")
	n := flag.Int("n", 40, "how many matching SSTs to report")
	flag.Parse()

	files, _ := filepath.Glob(filepath.Join(*dir, "*.sst"))
	sort.Strings(files)
	var hits []*row
	// Walk from the middle outwards: the snapshot keyspace sits well inside
	// the file ordering, so scanning from index 0 wastes time on chain data.
	for i := 0; i < len(files) && len(hits) < *n; i++ {
		r, err := inspect(files[i])
		if err != nil {
			continue
		}
		if *want != "" && r.FirstPrefix != fmt.Sprintf("%q", *want) {
			continue
		}
		hits = append(hits, r)
	}
	if len(hits) == 0 {
		fmt.Fprintf(os.Stderr, "%s: no SST with first-key prefix %q among %d files\n",
			*label, *want, len(files))
		os.Exit(1)
	}
	var db, ds, ne, raw uint64
	for _, h := range hits {
		db += h.DataBlocks
		ds += h.DataSize
		ne += h.NumEntries
		raw += h.RawKV
	}
	summary := map[string]any{
		"label": *label, "prefix": *want, "ssts_sampled": len(hits),
		"compression":                hits[0].Compression,
		"compressed_bytes_per_block": float64(ds) / float64(db),
		"entries_per_block":          float64(ne) / float64(db),
		"physical_over_logical":      float64(ds) / float64(raw),
		"mean_raw_record_bytes":      float64(raw) / float64(ne),
	}
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", " ")
	_ = enc.Encode(summary)
}
