// Command drainjournal flattens every pathdb diff layer into the disk layer
// and force-flushes the write buffer into pebble, so the datadir carries no
// journal-resident state. Run it against a stopped geth datadir. The chain
// head is untouched; only *where* trie state lives changes (journal -> disk).
//
// Built from the exact client commit so journal formats match.
package main

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/ethereum/go-ethereum/common"
	"github.com/ethereum/go-ethereum/core/rawdb"
	"github.com/ethereum/go-ethereum/ethdb"
	"github.com/ethereum/go-ethereum/ethdb/pebble"
	"github.com/ethereum/go-ethereum/log"
	"github.com/ethereum/go-ethereum/triedb"
	"github.com/ethereum/go-ethereum/triedb/pathdb"
)

func die(step string, err error) {
	if err != nil {
		fmt.Fprintf(os.Stderr, "FATAL %s: %v\n", step, err)
		os.Exit(1)
	}
}

func main() {
	datadir := flag.String("datadir", "", "geth datadir (the directory containing geth/chaindata)")
	stateHistory := flag.Uint64("history.state", 90000, "state history retention, must match the node's setting")
	checkOnly := flag.Bool("check", false, "read-only integrity check, mutate nothing")
	flag.Parse()
	if *datadir == "" {
		fmt.Fprintln(os.Stderr, "usage: drainjournal [--check] --datadir /path/to/datadir")
		os.Exit(2)
	}
	log.SetDefault(log.NewLogger(log.NewTerminalHandlerWithLevel(os.Stderr, log.LevelInfo, true)))

	chaindata := filepath.Join(*datadir, "geth", "chaindata")
	journalDir := filepath.Join(*datadir, "geth", "triedb")
	journalFile := filepath.Join(journalDir, "merkle.journal")
	if before, err := os.Stat(journalFile); err == nil {
		fmt.Printf("journal before: %d bytes\n", before.Size())
	} else {
		fmt.Println("journal before: absent (already drained?)")
	}
	// Open exactly the way the node does (node/database.go newPebbleDBDatabase):
	// legacy v1-format stores must go through the v1 wrapper; the v2 opener
	// would initialize a fresh store beside the real one. Format is left
	// untouched so benchmark clients keep their storage path unchanged.
	var kv ethdb.KeyValueStore
	var err2 error
	if pebble.NeedsV1(chaindata) {
		fmt.Println("store format: legacy pebble v1")
		kv, err2 = pebble.NewV1(chaindata, 512, 1024, "eth/db/chaindata/", false)
	} else {
		kv, err2 = pebble.New(chaindata, 512, 1024, "eth/db/chaindata/", false)
	}
	die("open pebble", err2)
	db, err := rawdb.Open(kv, rawdb.OpenOptions{Ancient: filepath.Join(chaindata, "ancient")})
	die("open rawdb", err)

	// Benchmark snapshots keep the whole chain in the ancient store and may
	// carry no head-pointer entries in the KV store; resolve the head from
	// the ancient store's top item in that case, exactly like a booting node.
	head := rawdb.ReadHeadHeader(db)
	if head == nil {
		frozen, err := db.Ancients()
		die("read ancients", err)
		if frozen == 0 {
			die("read head", fmt.Errorf("no head pointer and empty ancient store - refusing"))
		}
		num := frozen - 1
		hash := rawdb.ReadCanonicalHash(db, num)
		if hash == (common.Hash{}) {
			die("read head", fmt.Errorf("no canonical hash for ancient top %d - refusing", num))
		}
		head = rawdb.ReadHeader(db, hash, num)
		if head == nil {
			die("read head", fmt.Errorf("no header for ancient top %d - refusing", num))
		}
	}
	fmt.Printf("head: block=%d root=%x\n", head.Number, head.Root)
	if *checkOnly {
		die("close", db.Close())
		fmt.Println("CHECK_OK")
		return
	}

	tdb := triedb.NewDatabase(db, &triedb.Config{PathDB: &pathdb.Config{
		TrieCleanSize:    16 << 20,
		StateCleanSize:   16 << 20,
		WriteBufferSize:  64 << 20,
		JournalDirectory: journalDir,
		StateHistory:     *stateHistory,
		TrienodeHistory:  -1, // disabled, matching the node (no ancient/trienodes)
	}})

	// Commit flattens every diff layer into the disk layer and force-flushes
	// the write buffer into pebble. If the head root already IS the disk layer
	// (journal previously drained), pathdb reports it as such - treat that as
	// success so the pipeline hook can run unconditionally.
	if err := tdb.Commit(head.Root, true); err != nil {
		if strings.Contains(err.Error(), "is disk layer") {
			fmt.Println("already drained: head root is the disk layer")
		} else {
			die("commit (flatten all layers, force-flush buffer)", err)
		}
	}
	die("close triedb", tdb.Close())
	die("close rawdb", db.Close())

	// The file journal is obsolete once state is flattened to disk: it can only
	// describe pre-drain layers, and a booting client would discard it anyway
	// (with a noisy "unmatched journal" + history-truncation detour). Drop it.
	if _, err := os.Stat(journalFile); err == nil {
		die("remove obsolete journal", os.Remove(journalFile))
		fmt.Println("journal file removed (obsolete after drain)")
	}
	fmt.Println("DRAIN_OK")
}
