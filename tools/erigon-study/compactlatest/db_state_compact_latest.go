package state

// Copied into erigon 5f62f4ed's db/state by build-compactlatest.sh; not part of upstream erigon.

import (
	"context"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"fmt"
	"hash"
	"io"
	"runtime"
	"time"

	"github.com/erigontech/erigon/common/background"
	"github.com/erigontech/erigon/common/log/v3"
	"github.com/erigontech/erigon/db/kv"
	"github.com/erigontech/erigon/db/seg"
)

// CompactStat describes one rewritten domain file.
type CompactStat struct {
	Path   string `json:"path"`
	Keys   uint64 `json:"keys"`
	Sha256 string `json:"sha256"` // over the (key, value) stream as written; the read-back must match
}

func streamHash(h hash.Hash, k, v []byte) {
	var n [binary.MaxVarintLen64]byte
	h.Write(n[:binary.PutUvarint(n[:], uint64(len(k)))])
	h.Write(k)
	h.Write(n[:binary.PutUvarint(n[:], uint64(len(v)))])
	h.Write(v)
}

// CompactLatest writes the latest live value of every key of the four state domains into a single
// [0,1) file set (.kv plus accessors) under dstDir: the layout of a node whose whole state sits in
// its bottom file. It reads through erigon's own latest-state iterator (MDBX and every file,
// newest wins), so a key deleted at the head is dropped, as a merge into step 0 drops it.
// Commitment branches are re-read through GetLatest, which expands shortened-key references into
// the old account/storage files; the new file is written plain (a one-step file is never read as
// referenced). Values are written with each domain's configured compression, as erigon's merge
// writes large files. Samples of keys go to samples ("all <domain> <hexkey>" every sampleEvery
// keys, "db <domain> <hexkey>" every dbSampleEvery MDBX-resident keys) for an RPC cross-check.
func (a *Aggregator) CompactLatest(ctx context.Context, db kv.RoDB, dstDir string, workers int,
	sampleEvery, dbSampleEvery uint64, samples io.Writer, logger log.Logger) (map[string]CompactStat, error) {
	out := map[string]CompactStat{}
	for _, domain := range []kv.Domain{kv.AccountsDomain, kv.StorageDomain, kv.CodeDomain, kv.CommitmentDomain} {
		started := time.Now()
		stat, err := a.compactDomain(ctx, db, domain, dstDir, workers, sampleEvery, samples, logger)
		if err != nil {
			return nil, fmt.Errorf("compact %s: %w", domain, err)
		}
		if domain != kv.CommitmentDomain && dbSampleEvery > 0 && samples != nil {
			if err := a.sampleDBKeys(ctx, db, domain, dbSampleEvery, samples); err != nil {
				return nil, fmt.Errorf("sample %s db keys: %w", domain, err)
			}
		}
		logger.Info("[compact] domain done", "domain", domain, "keys", stat.Keys, "took", time.Since(started))
		out[domain.String()] = stat
	}
	return out, nil
}

func (a *Aggregator) compactDomain(ctx context.Context, db kv.RoDB, domain kv.Domain, dstDir string, workers int,
	sampleEvery uint64, samples io.Writer, logger log.Logger) (CompactStat, error) {
	d := a.d[domain]
	path := d.kvNewFilePathIn(dstDir, 0, 1)
	comp, err := seg.NewCompressor(ctx, d.FilenameBase+".compact", path, d.dirs.Tmp, d.CompressCfg, log.LvlInfo, logger)
	if err != nil {
		return CompactStat{}, err
	}
	handedOff := false // buildFileRange closes the compressor on success and on error
	defer func() {
		if !handedOff {
			comp.Close()
		}
	}()
	w := d.dataWriter(comp, false)
	h := sha256.New()
	var keys uint64
	put := func(k, v []byte) error {
		if _, err := w.Write(k); err != nil {
			return err
		}
		if _, err := w.Write(v); err != nil {
			return err
		}
		streamHash(h, k, v)
		keys++
		if samples != nil && sampleEvery > 0 && keys%sampleEvery == 0 {
			fmt.Fprintf(samples, "all %s %s\n", domain, hex.EncodeToString(k))
		}
		if keys%50_000_000 == 0 {
			logger.Info("[compact] progress", "domain", domain, "keys", keys)
		}
		return nil
	}

	roTx, err := db.BeginRo(ctx)
	if err != nil {
		return CompactStat{}, err
	}
	defer roTx.Rollback()
	at := a.BeginFilesRo()
	defer at.Close()
	it, err := at.DebugRangeLatest(roTx, domain, nil, nil, -1)
	if err != nil {
		return CompactStat{}, err
	}
	defer it.Close()

	if domain != kv.CommitmentDomain {
		for it.HasNext() {
			k, v, err := it.Next()
			if err != nil {
				return CompactStat{}, err
			}
			if err := put(k, v); err != nil {
				return CompactStat{}, err
			}
		}
	} else if err := a.compactCommitment(ctx, db, it, workers, put); err != nil {
		return CompactStat{}, err
	}

	ps := background.NewProgressSet()
	handedOff = true
	static, err := d.buildFileRange(ctx, 0, 1, Collation{valuesComp: comp, valuesPath: path, valuesCount: int(keys)}, ps, dstDir)
	if err != nil {
		return CompactStat{}, err
	}
	static.CleanupOnError() // the files stay on disk; only the open handles are released
	sum := hex.EncodeToString(h.Sum(nil))

	// Read the file back through the domain's own reader: what erigon will see must be what we wrote.
	dec, err := seg.NewDecompressor(path)
	if err != nil {
		return CompactStat{}, err
	}
	defer dec.Close()
	r := d.dataReader(dec)
	rh := sha256.New()
	var rkeys uint64
	for r.HasNext() {
		k, _ := r.Next(nil)
		if !r.HasNext() {
			return CompactStat{}, fmt.Errorf("read-back: key without value at %d", rkeys)
		}
		v, _ := r.Next(nil)
		streamHash(rh, k, v)
		rkeys++
	}
	if rsum := hex.EncodeToString(rh.Sum(nil)); rsum != sum || rkeys != keys {
		return CompactStat{}, fmt.Errorf("read-back mismatch: wrote %d keys %s, read %d keys %s", keys, sum, rkeys, rsum)
	}
	return CompactStat{Path: path, Keys: keys, Sha256: sum}, nil
}

// compactCommitment resolves every branch through GetLatest in parallel batches and writes them
// in key order. Each worker holds its own read transaction and files view for the whole run.
func (a *Aggregator) compactCommitment(ctx context.Context, db kv.RoDB, it interface {
	HasNext() bool
	Next() ([]byte, []byte, error)
}, workers int, put func(k, v []byte) error) error {
	type job struct {
		keys, vals [][]byte
		done       chan error
	}
	jobs := make(chan job)
	for i := 0; i < workers; i++ {
		go func() {
			runtime.LockOSThread()
			defer runtime.UnlockOSThread()
			roTx, err := db.BeginRo(ctx)
			if err != nil {
				for j := range jobs {
					j.done <- err
				}
				return
			}
			defer roTx.Rollback()
			at := a.BeginFilesRo()
			defer at.Close()
			for j := range jobs {
				var jerr error
				for n, k := range j.keys {
					v, _, ok, err := at.GetLatest(kv.CommitmentDomain, k, roTx, kv.GetLatestOptions{})
					if err == nil && !ok {
						err = fmt.Errorf("branch %x listed by the iterator but not found", k)
					}
					if err != nil {
						jerr = err
						break
					}
					j.vals[n] = append([]byte(nil), v...)
				}
				j.done <- jerr
			}
		}()
	}
	defer close(jobs)

	const batch = 1 << 16
	for {
		keys := make([][]byte, 0, batch)
		for len(keys) < batch && it.HasNext() {
			k, _, err := it.Next()
			if err != nil {
				return err
			}
			keys = append(keys, k)
		}
		if len(keys) == 0 {
			return nil
		}
		vals := make([][]byte, len(keys))
		chunk := (len(keys) + workers - 1) / workers
		var pending []chan error
		for from := 0; from < len(keys); from += chunk {
			to := min(from+chunk, len(keys))
			done := make(chan error, 1)
			jobs <- job{keys: keys[from:to], vals: vals[from:to], done: done}
			pending = append(pending, done)
		}
		for _, done := range pending {
			if err := <-done; err != nil {
				return err
			}
		}
		for n := range keys {
			if err := put(keys[n], vals[n]); err != nil {
				return err
			}
		}
	}
}

// sampleDBKeys lists every n-th distinct key of the domain's MDBX values table: the keys the
// untreated store serves from its database, which the benchmark's reads mostly are.
func (a *Aggregator) sampleDBKeys(ctx context.Context, db kv.RoDB, domain kv.Domain, n uint64, samples io.Writer) error {
	d := a.d[domain]
	return db.View(ctx, func(tx kv.Tx) error {
		var seen uint64
		emit := func(k []byte) {
			seen++
			if seen%n == 0 {
				fmt.Fprintf(samples, "db %s %s\n", domain, hex.EncodeToString(k))
			}
		}
		if d.LargeValues {
			c, err := tx.Cursor(d.ValuesTable)
			if err != nil {
				return err
			}
			defer c.Close()
			var last []byte
			for k, _, err := c.First(); k != nil; k, _, err = c.Next() {
				if err != nil {
					return err
				}
				bare := k[:len(k)-8]
				if string(bare) != string(last) {
					emit(bare)
					last = append(last[:0], bare...)
				}
			}
			return nil
		}
		c, err := tx.CursorDupSort(d.ValuesTable)
		if err != nil {
			return err
		}
		defer c.Close()
		for k, _, err := c.First(); k != nil; k, _, err = c.NextNoDup() {
			if err != nil {
				return err
			}
			emit(k)
		}
		return nil
	})
}
