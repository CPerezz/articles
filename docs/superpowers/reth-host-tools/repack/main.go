// repack rewrites one mdbx table in key order with cursor Append so its pages fill up, and checks
// that the table's contents are byte-identical afterwards. Scratch-only tool: on any failure the
// scratch is restored from the schelk virgin.
//
//	repack -db <dir> -table HashedAccounts        stats, hash, repack, hash, stats
//	repack -db <dir> -table T -stats              stats only
//	repack -db <dir> -table T -hash               sha256 over every (k, v), read-only
//	repack -mktest <dir> -n N -order sorted|random -put put|append
//	                                              toy table "T" of N random 32-byte keys (40-byte values)
package main

import (
	"bytes"
	"crypto/rand"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"flag"
	"fmt"
	"log"
	"os"
	"sort"
	"time"

	"github.com/erigontech/mdbx-go/mdbx"
)

const batch = 1_000_000

func openEnv(dir string) *mdbx.Env {
	env, err := mdbx.NewEnv(mdbx.Label("chaindata"))
	must(err)
	// An existing database keeps its stored geometry (-1 everywhere: setting any field rewrites the meta);
	// a new toy db gets 4 KiB pages like reth.
	if _, err := os.Stat(dir + "/mdbx.dat"); os.IsNotExist(err) {
		must(env.SetGeometry(-1, -1, 1<<40, 1<<30, -1, 4096))
	} else {
		must(env.SetGeometry(-1, -1, -1, -1, -1, -1))
	}
	must(env.SetOption(mdbx.OptMaxDB, 64))
	must(env.SetOption(mdbx.OptMaxReaders, 32_000)) // reth's max_readers; sizes mdbx.lck if recreated
	must(os.MkdirAll(dir, 0o755))
	must(env.Open(dir, mdbx.WriteMap|mdbx.NoReadahead|mdbx.SafeNoSync, 0o644))
	return env
}

// dupsortTables are state-actor reth v2's DupSort DBIs (internal/reth/tables.go);
// OpenDBI must request the same flags the table was created with or mdbx
// returns MDBX_INCOMPATIBLE.
var dupsortTables = map[string]bool{
	"HashedStorages":    true,
	"StoragesTrie":      true,
	"AccountChangeSets": true,
	"StorageChangeSets": true,
}

func dbi(txn *mdbx.Txn, name string, create bool) (mdbx.DBI, error) {
	var f uint
	if create {
		f = mdbx.Create
	}
	if dupsortTables[name] {
		f |= mdbx.DupSort
	}
	return txn.OpenDBI(name, f, nil, nil)
}

func stats(env *mdbx.Env, name, tag string) {
	must(env.View(func(txn *mdbx.Txn) error {
		d, err := dbi(txn, name, false)
		if err != nil {
			return err
		}
		st, err := txn.StatDBI(d)
		if err != nil {
			return err
		}
		fmt.Printf("STAT %s %s %+v\n", tag, name, *st)
		return nil
	}))
}

func hashTable(env *mdbx.Env, name string) (string, uint64) {
	h := sha256.New()
	var n uint64
	var l [4]byte
	must(env.View(func(txn *mdbx.Txn) error {
		d, err := dbi(txn, name, false)
		if err != nil {
			return err
		}
		c, err := txn.OpenCursor(d)
		if err != nil {
			return err
		}
		defer c.Close()
		for k, v, err := c.Get(nil, nil, mdbx.First); ; k, v, err = c.Get(nil, nil, mdbx.Next) {
			if mdbx.IsNotFound(err) {
				return nil
			}
			if err != nil {
				return err
			}
			binary.LittleEndian.PutUint32(l[:], uint32(len(k)))
			h.Write(l[:])
			h.Write(k)
			binary.LittleEndian.PutUint32(l[:], uint32(len(v)))
			h.Write(l[:])
			h.Write(v)
			n++
		}
	}))
	return hex.EncodeToString(h.Sum(nil)), n
}

// copyAppend appends every entry of src to dst (dst must be empty), batch entries per transaction.
func copyAppend(env *mdbx.Env, src, dst string) uint64 {
	var last []byte
	var n uint64
	for done := false; !done; {
		must(env.Update(func(txn *mdbx.Txn) error {
			s, err := dbi(txn, src, false)
			if err != nil {
				return err
			}
			d, err := dbi(txn, dst, true)
			if err != nil {
				return err
			}
			cs, err := txn.OpenCursor(s)
			if err != nil {
				return err
			}
			defer cs.Close()
			cd, err := txn.OpenCursor(d)
			if err != nil {
				return err
			}
			defer cd.Close()
			var k, v []byte
			if last == nil {
				k, v, err = cs.Get(nil, nil, mdbx.First)
			} else {
				k, v, err = cs.Get(last, nil, mdbx.SetRange)
				if err == nil && bytes.Equal(k, last) {
					k, v, err = cs.Get(nil, nil, mdbx.Next)
				}
			}
			for i := 0; i < batch && err == nil; i++ {
				// copy out of the map: a put may grow and remap it
				kk, vv := append([]byte(nil), k...), append([]byte(nil), v...)
				if err := cd.Put(kk, vv, mdbx.Append); err != nil {
					return fmt.Errorf("append %x: %w", kk, err)
				}
				last = kk
				n++
				k, v, err = cs.Get(nil, nil, mdbx.Next)
			}
			if mdbx.IsNotFound(err) {
				done = true
				return nil
			}
			return err
		}))
	}
	return n
}

func drop(env *mdbx.Env, name string, del bool) {
	must(env.Update(func(txn *mdbx.Txn) error {
		d, err := dbi(txn, name, false)
		if err != nil {
			return err
		}
		return txn.Drop(d, del)
	}))
}

func repack(dir, table string) {
	env := openEnv(dir)
	defer env.Close()
	tmp := table + "Repack"
	must(env.View(func(txn *mdbx.Txn) error {
		if _, err := dbi(txn, tmp, false); !mdbx.IsNotFound(err) {
			return fmt.Errorf("temp table %s exists (err=%v): restore the scratch first", tmp, err)
		}
		return nil
	}))
	t0 := time.Now()
	stats(env, table, "before")
	h0, n0 := hashTable(env, table)
	fmt.Printf("HASH before %s entries=%d (%s)\n", h0, n0, time.Since(t0).Round(time.Second))
	if n := copyAppend(env, table, tmp); n != n0 {
		log.Fatalf("copy to %s: %d entries, want %d", tmp, n, n0)
	}
	stats(env, tmp, "temp")
	fmt.Printf("COPIED to %s (%s)\n", tmp, time.Since(t0).Round(time.Second))
	drop(env, table, false)
	if n := copyAppend(env, tmp, table); n != n0 {
		log.Fatalf("copy back: %d entries, want %d", n, n0)
	}
	drop(env, tmp, true)
	must(env.Sync(true, false))
	h1, n1 := hashTable(env, table)
	fmt.Printf("HASH after  %s entries=%d (%s)\n", h1, n1, time.Since(t0).Round(time.Second))
	stats(env, table, "after")
	if h1 != h0 || n1 != n0 {
		log.Fatalf("REPACK-MISMATCH")
	}
	fmt.Println("REPACK-OK")
}

func mktest(dir string, n int, order, put string) {
	keys := make([][]byte, n)
	for i := range keys {
		keys[i] = make([]byte, 32)
		_, err := rand.Read(keys[i])
		must(err)
	}
	if order == "sorted" {
		sort.Slice(keys, func(i, j int) bool { return bytes.Compare(keys[i], keys[j]) < 0 })
	}
	val := make([]byte, 40)
	env := openEnv(dir)
	defer env.Close()
	for i := 0; i < n; i += batch {
		must(env.Update(func(txn *mdbx.Txn) error {
			d, err := dbi(txn, "T", true)
			if err != nil {
				return err
			}
			c, err := txn.OpenCursor(d)
			if err != nil {
				return err
			}
			defer c.Close()
			for _, k := range keys[i:min(i+batch, n)] {
				var f uint
				if put == "append" {
					f = mdbx.Append
				}
				if err := c.Put(k, val, f); err != nil {
					return err
				}
			}
			return nil
		}))
	}
	must(env.Sync(true, false))
	stats(env, "T", "mktest-"+order+"-"+put)
}

func must(err error) {
	if err != nil {
		log.Fatal(err)
	}
}

func main() {
	db := flag.String("db", "", "mdbx directory (holds mdbx.dat)")
	table := flag.String("table", "", "table to repack")
	statsOnly := flag.Bool("stats", false, "print table stats only")
	hashOnly := flag.Bool("hash", false, "print the table's content hash only (read-only)")
	mk := flag.String("mktest", "", "create a toy db in this directory")
	n := flag.Int("n", 2_000_000, "toy entries")
	order := flag.String("order", "sorted", "toy insert order: sorted|random")
	put := flag.String("put", "put", "toy insert call: put|append")
	flag.Parse()
	switch {
	case *mk != "":
		mktest(*mk, *n, *order, *put)
	case *db != "" && *table != "" && *hashOnly:
		env := openEnv(*db)
		defer env.Close()
		h, n := hashTable(env, *table)
		fmt.Printf("HASH %s %s entries=%d\n", *table, h, n)
	case *db != "" && *table != "" && *statsOnly:
		env := openEnv(*db)
		defer env.Close()
		stats(env, *table, "now")
	case *db != "" && *table != "":
		repack(*db, *table)
	default:
		flag.Usage()
		os.Exit(2)
	}
}
