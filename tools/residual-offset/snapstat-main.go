// Command snapstat measures the shape of a geth flat-state snapshot: how many
// bytes an account record actually occupies on disk, and how many of those
// accounts are contracts (a storage root and code hash cost 33 bytes each in
// the slim encoding, an EOA drops both).
//
// This is the keyspace the EVM really reads. Sizes are logical, so the result
// does not depend on which device the store happens to sit on.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"sort"

	"github.com/ethereum/go-ethereum/core/rawdb"
	"github.com/ethereum/go-ethereum/core/types"
	"github.com/ethereum/go-ethereum/ethdb"
	"github.com/ethereum/go-ethereum/ethdb/pebble"
	"github.com/ethereum/go-ethereum/log"
)

func main() {
	datadir := flag.String("datadir", "", "geth datadir")
	label := flag.String("label", "", "label for the report")
	sample := flag.Int("n", 200000, "account snapshot entries to sample")
	flag.Parse()
	log.SetDefault(log.NewLogger(log.NewTerminalHandlerWithLevel(os.Stderr, log.LevelWarn, true)))

	chaindata := filepath.Join(*datadir, "geth", "chaindata")
	var kv ethdb.KeyValueStore
	var err error
	if pebble.NeedsV1(chaindata) {
		kv, err = pebble.NewV1(chaindata, 256, 1024, "", false)
	} else {
		kv, err = pebble.New(chaindata, 256, 1024, "", false)
	}
	if err != nil {
		fmt.Fprintf(os.Stderr, "open %s: %v\n", chaindata, err)
		os.Exit(1)
	}
	defer kv.Close()

	var (
		sizes                 []int
		total, contracts      int
		withStorage, withCode int
		codeBytes             int
		eoaBytes, eoaN        int
		codeAccBytes          int
	)
	it := rawdb.NewKeyLengthIterator(
		kv.NewIterator(rawdb.SnapshotAccountPrefix, nil), len(rawdb.SnapshotAccountPrefix)+32)
	defer it.Release()

	for it.Next() && total < *sample {
		val := it.Value()
		sizes = append(sizes, len(val))
		total++
		acc, err := types.FullAccount(val)
		if err != nil {
			continue
		}
		if acc.Root != types.EmptyRootHash {
			withStorage++
		}
		if string(acc.CodeHash) != string(types.EmptyCodeHash.Bytes()) {
			withCode++
			codeBytes += 32
		}
		isContract := acc.Root != types.EmptyRootHash ||
			string(acc.CodeHash) != string(types.EmptyCodeHash.Bytes())
		if isContract {
			contracts++
			codeAccBytes += len(val)
		} else {
			eoaN++
			eoaBytes += len(val)
		}
	}
	if err := it.Error(); err != nil {
		fmt.Fprintf(os.Stderr, "iterate: %v\n", err)
	}
	sort.Ints(sizes)
	sum := 0
	for _, s := range sizes {
		sum += s
	}
	out := map[string]any{
		"label":            *label,
		"sampled":          total,
		"mean_bytes":       0.0,
		"median_bytes":     0,
		"p90_bytes":        0,
		"min_bytes":        0,
		"max_bytes":        0,
		"with_storage_pct": 0.0,
		"with_code_pct":    0.0,
		"contract_pct":     0.0,
	}
	if total > 0 {
		out["mean_bytes"] = float64(sum) / float64(total)
		out["median_bytes"] = sizes[total/2]
		out["p90_bytes"] = sizes[(total*9)/10]
		out["min_bytes"] = sizes[0]
		out["max_bytes"] = sizes[total-1]
		out["with_storage_pct"] = 100 * float64(withStorage) / float64(total)
		out["with_code_pct"] = 100 * float64(withCode) / float64(total)
		out["contract_pct"] = 100 * float64(contracts) / float64(total)
		if eoaN > 0 {
			out["mean_bytes_eoa"] = float64(eoaBytes) / float64(eoaN)
		}
		if contracts > 0 {
			out["mean_bytes_contract"] = float64(codeAccBytes) / float64(contracts)
		}
	}
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", " ")
	_ = enc.Encode(out)
}
