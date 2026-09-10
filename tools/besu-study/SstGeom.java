// SST block geometry per column family — the Besu port of the geth study's `sstgeom`.
//
// The geth residual (F3) was settled by one number: the physical size of a data block. Records
// there were 49.6 vs 58.3 B/entry, compressing to 0.849 vs 0.991 of logical, landing blocks at
// 3,467 vs 4,043 bytes — 1.85 vs 1.99 4 KiB pages per read, +7.6% pages against +11.9% measured
// bytes. This reproduces that chain on RocksDB.
//
// It reads RocksDB's own table properties rather than sampling files, so the figures are exact
// and CF-scoped: getPropertiesOfAllTables(cf) covers precisely the SSTs of that column family.
//
// Column families are identified by ENTRY COUNT, not by guessing Besu's segment ids: the counts
// are already known from `besu storage rocksdb usage` and are distinctive (e.g.
// ACCOUNT_INFO_STATE = 430,696,738 on the state-actor store).
//
// Usage: SstGeom <datadir>/database
import org.rocksdb.*;
import java.util.*;

public class SstGeom {
  public static void main(String[] args) throws Exception {
    if (args.length < 1) {
      System.err.println("usage: SstGeom <rocksdb-dir>");
      System.exit(2);
    }
    final String path = args[0];
    RocksDB.loadLibrary();

    final DBOptions dbOptions = new DBOptions();
    final List<ColumnFamilyDescriptor> cfDescs = new ArrayList<>();
    try (ConfigOptions cfgOpts = new ConfigOptions()) {
      OptionsUtil.loadLatestOptions(cfgOpts, path, dbOptions, cfDescs);
    } catch (RocksDBException e) {
      // Same precondition as Compact: state-actor writes OPTIONS with librocksdb 10.10, which
      // Besu's 10.6.2 cannot parse until Besu has opened the store once.
      System.err.println("cannot read OPTIONS at " + path + ": " + e.getMessage());
      System.err.println("boot Besu on the store once first, then re-run.");
      System.exit(3);
    }

    final List<ColumnFamilyHandle> handles = new ArrayList<>();
    System.out.printf("%-8s %14s %12s %14s %10s %10s %8s%n",
        "cf", "entries", "ssts", "data_bytes", "rec_B", "blk_B", "phys/log");

    // read-only: never mutate a store we are about to measure
    try (RocksDB db = RocksDB.openReadOnly(dbOptions, path, cfDescs, handles)) {
      for (int i = 0; i < handles.size(); i++) {
        final String cf = HexFormat.of().formatHex(cfDescs.get(i).getName());
        final Map<String, TableProperties> props = db.getPropertiesOfAllTables(handles.get(i));
        if (props.isEmpty()) continue;

        long entries = 0, dataSize = 0, blocks = 0, rawKey = 0, rawValue = 0;
        for (TableProperties p : props.values()) {
          entries  += p.getNumEntries();
          dataSize += p.getDataSize();
          blocks   += p.getNumDataBlocks();
          rawKey   += p.getRawKeySize();
          rawValue += p.getRawValueSize();
        }
        if (entries == 0 || blocks == 0) continue;

        final long logical = rawKey + rawValue;
        System.out.printf("%-8s %14d %12d %14d %10.1f %10.1f %8.3f%n",
            cf, entries, props.size(), dataSize,
            (double) logical / entries,          // mean raw record bytes
            (double) dataSize / blocks,          // compressed bytes per data block
            (double) dataSize / logical);        // physical / logical
      }
    } finally {
      for (ColumnFamilyHandle h : handles) h.close();
      dbOptions.close();
    }
  }
}
