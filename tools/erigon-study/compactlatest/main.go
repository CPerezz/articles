// compactlatest rebuilds an Erigon datadir as a node whose whole state sits in its bottom file:
// one [0,1) file set per state domain holding every key's latest value, and no state in MDBX.
// The step size becomes the head's last txNum + 1, so that file ends exactly at the head block.
// Built against erigon 5f62f4ed by build-compactlatest.sh (Erigon study ledger, round 12).
//
//	compactlatest compact --datadir D --dst S --tmp T   write the file set into staging dir S
//	compactlatest reset   --datadir D --head N          clear MDBX state tables, execution progress := N
//	compactlatest clear-code-cache --datadir D          empty TblCodeCache (re-derivable from CodeDomain)
//	compactlatest inspect --datadir D                   print settings, head and file coverage
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"

	"github.com/erigontech/erigon/common/log/v3"
	"github.com/erigontech/erigon/db/datadir"
	"github.com/erigontech/erigon/db/kv"
	"github.com/erigontech/erigon/db/kv/dbcfg"
	"github.com/erigontech/erigon/db/kv/mdbx"
	"github.com/erigontech/erigon/db/kv/rawdbv3"
	"github.com/erigontech/erigon/db/kv/temporal"
	"github.com/erigontech/erigon/db/state"
	"github.com/erigontech/erigon/execution/commitment/commitmentdb"
	"github.com/erigontech/erigon/execution/stagedsync/rawdbreset"
	"github.com/erigontech/erigon/execution/stagedsync/stages"
)

type head struct {
	ExecProgress   uint64            `json:"exec_progress"`
	StateTxNum     uint64            `json:"state_txnum"`
	StateBlock     uint64            `json:"state_block"`
	MaxTxNum       uint64            `json:"max_txnum_of_state_block"`
	StepSize       uint64            `json:"step_size"`
	FilesEndTxNums map[string]uint64 `json:"files_end_txnum"`
}

func open(ctx context.Context, path, tmp string, readonly bool, logger log.Logger) (datadir.Dirs, kv.RwDB, *state.Aggregator, func()) {
	dirs, lock, err := datadir.New(path).MustFlock() // refuse to run beside a live node
	must(err)
	if tmp != "" {
		dirs.Tmp = tmp
	}
	db := mdbx.New(dbcfg.ChainDB, logger).Path(dirs.Chaindata).Accede(true).Readonly(readonly).MustOpen()
	settings, err := state.ResolveErigonDBSettings(dirs, logger, true)
	must(err)
	agg, err := state.New(dirs).SanityOldNaming().Logger(logger).WithErigonDBSettings(settings).Open(ctx, db)
	must(err)
	must(agg.OpenFolder())
	return dirs, db, agg, func() { agg.Close(); db.Close(); _ = lock.Unlock() }
}

func readHead(ctx context.Context, db kv.RoDB, agg *state.Aggregator) head {
	var h head
	at := agg.BeginFilesRo()
	defer at.Close()
	must(db.View(ctx, func(tx kv.Tx) error {
		var err error
		if h.ExecProgress, err = stages.GetStageProgress(tx, stages.Execution); err != nil {
			return err
		}
		v, _, ok, err := at.GetLatest(kv.CommitmentDomain, commitmentdb.KeyCommitmentState, tx, kv.GetLatestOptions{})
		if err != nil {
			return err
		}
		if !ok || len(v) < 16 {
			return fmt.Errorf("no commitment state key")
		}
		h.StateTxNum, h.StateBlock = commitmentdb.DecodeTxBlockNums(v)
		h.MaxTxNum, err = rawdbv3.TxNums.Max(ctx, tx, h.StateBlock)
		return err
	}))
	h.StepSize = agg.StepSize()
	h.FilesEndTxNums = map[string]uint64{}
	for _, d := range kv.StateDomains {
		h.FilesEndTxNums[d.String()] = at.TxNumsInFiles(d)
	}
	return h
}

func main() {
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "usage: compactlatest compact|reset|inspect [flags]")
		os.Exit(2)
	}
	fs := flag.NewFlagSet(os.Args[1], flag.ExitOnError)
	datadirFlag := fs.String("datadir", "", "erigon datadir")
	dst := fs.String("dst", "", "staging dir for the new domain files (compact)")
	tmp := fs.String("tmp", "", "temp dir for compressors (compact); default <datadir>/temp")
	workers := fs.Int("workers", 16, "commitment resolve workers (compact)")
	sampleEvery := fs.Uint64("sample-every", 1_000_000, "emit every n-th key per domain to the samples file (compact)")
	dbSampleEvery := fs.Uint64("db-sample-every", 1_000, "emit every n-th MDBX-resident key per domain (compact)")
	samplesPath := fs.String("samples", "", "samples output file (compact)")
	headFlag := fs.Uint64("head", 0, "head block the files end at (reset)")
	must(fs.Parse(os.Args[2:]))
	if *datadirFlag == "" {
		fmt.Fprintln(os.Stderr, "--datadir is required")
		os.Exit(2)
	}
	ctx := context.Background()
	logger := log.New()
	logger.SetHandler(log.LvlFilterHandler(log.LvlInfo, log.StderrHandler))
	enc := json.NewEncoder(os.Stdout)
	enc.SetIndent("", " ")

	switch os.Args[1] {
	case "inspect":
		_, db, agg, closeAll := open(ctx, *datadirFlag, "", true, logger)
		defer closeAll()
		must(enc.Encode(readHead(ctx, db, agg)))

	case "compact":
		if *dst == "" || *samplesPath == "" {
			fmt.Fprintln(os.Stderr, "compact needs --dst and --samples")
			os.Exit(2)
		}
		must(os.MkdirAll(*dst, 0o755))
		_, db, agg, closeAll := open(ctx, *datadirFlag, *tmp, true, logger)
		defer closeAll()
		h := readHead(ctx, db, agg)
		// The new step ends at the state's txNum: it has to be the head block's last txNum, or the
		// file would end inside a block.
		if h.StateBlock != h.ExecProgress || h.StateTxNum != h.MaxTxNum {
			must(fmt.Errorf("state is not at a block end: %+v", h))
		}
		samples, err := os.Create(*samplesPath)
		must(err)
		defer samples.Close()
		stats, err := agg.CompactLatest(ctx, db, *dst, *workers, *sampleEvery, *dbSampleEvery, samples, logger)
		must(err)
		must(enc.Encode(map[string]any{"head": h, "new_step_size": h.StateTxNum + 1, "domains": stats}))

	case "reset":
		if *headFlag == 0 {
			fmt.Fprintln(os.Stderr, "reset needs --head")
			os.Exit(2)
		}
		_, db, agg, closeAll := open(ctx, *datadirFlag, "", false, logger)
		defer closeAll()
		tdb, err := temporal.New(db, agg, nil)
		must(err)
		must(rawdbreset.ResetExec(ctx, tdb))
		// ResetExec leaves execution progress at 0; the new files end at the head block, so the
		// state is at the head.
		must(db.Update(ctx, func(tx kv.RwTx) error { return stages.SaveStageProgress(tx, stages.Execution, *headFlag) }))
		var counts = map[string]uint64{}
		must(db.View(ctx, func(tx kv.Tx) error {
			for _, d := range kv.StateDomains {
				for _, t := range tdb.Debug().DomainTables(d) {
					n, err := tx.Count(t)
					if err != nil {
						return err
					}
					counts[t] = n
				}
			}
			return nil
		}))
		must(enc.Encode(map[string]any{"exec_progress": *headFlag, "state_table_rows_after_reset": counts}))

	case "clear-code-cache":
		// state-actor's store starts with no CodeCache rows; a carried-over cache costs one full
		// table scan in the first forkchoiceUpdated of every freshly booted client.
		dirs, lock, err := datadir.New(*datadirFlag).MustFlock()
		must(err)
		db := mdbx.New(dbcfg.ChainDB, logger).Path(dirs.Chaindata).Accede(true).MustOpen()
		var before, after uint64
		must(db.Update(ctx, func(tx kv.RwTx) error {
			if before, err = tx.Count(kv.TblCodeCache); err != nil {
				return err
			}
			return tx.ClearTable(kv.TblCodeCache)
		}))
		must(db.View(ctx, func(tx kv.Tx) error { after, err = tx.Count(kv.TblCodeCache); return err }))
		db.Close()
		_ = lock.Unlock()
		must(enc.Encode(map[string]uint64{"code_cache_rows_before": before, "code_cache_rows_after": after}))

	default:
		fmt.Fprintln(os.Stderr, "unknown subcommand", os.Args[1])
		os.Exit(2)
	}
}

func must(err error) {
	if err != nil {
		fmt.Fprintln(os.Stderr, "error:", err)
		os.Exit(1)
	}
}
