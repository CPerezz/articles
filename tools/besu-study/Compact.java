// Offline full compaction of a Besu RocksDB store — the analogue of `geth db compact`,
// which Besu does not ship (`besu storage rocksdb` offers only `usage` and `x-stats`).
//
// Two things make this safe to point at a benchmark store:
//   1. It links the SAME rocksdbjni jar Besu itself uses, so there is no format skew.
//   2. It loads the store's OWN OPTIONS file via OptionsUtil rather than guessing settings.
//      That matters: these stores use BlobDB (.blob files present), and opening with default
//      options would rewrite blob-separated values back into SSTs during compaction — a
//      physical layout change Besu never intended, silently corrupting the very measurement
//      the study is trying to make.
//
// Usage: Compact <datadir>/database
import org.rocksdb.*;
import java.util.*;

public class Compact {
  public static void main(String[] args) throws Exception {
    if (args.length < 1) {
      System.err.println("usage: Compact <rocksdb-dir>");
      System.exit(2);
    }
    final String path = args[0];
    RocksDB.loadLibrary();

    final DBOptions dbOptions = new DBOptions();
    final List<ColumnFamilyDescriptor> cfDescs = new ArrayList<>();
    try (ConfigOptions cfgOpts = new ConfigOptions()) {
      OptionsUtil.loadLatestOptions(cfgOpts, path, dbOptions, cfDescs);
    } catch (RocksDBException e) {
      // state-actor's image links librocksdb 10.10; Besu ships rocksdbjni 10.6.2. A store
      // straight out of the generator has an OPTIONS file with 10.10-only keys (e.g.
      // max_manifest_space_amp_pct) that 10.6.2 refuses to parse. Besu rewrites OPTIONS on
      // first open, so the fix is to boot it once — which the benchmark pipeline does anyway.
      System.err.println("cannot read OPTIONS at " + path + ": " + e.getMessage());
      System.err.println("if this is a freshly generated store, boot Besu on it once first "
          + "(it rewrites OPTIONS with its own rocksdb version), then re-run.");
      System.exit(3);
    }
    System.out.printf("loaded OPTIONS: %d column families%n", cfDescs.size());

    final List<ColumnFamilyHandle> handles = new ArrayList<>();
    final CompactRangeOptions cro = new CompactRangeOptions()
        // Without kForce RocksDB skips the bottommost level when it believes it is already
        // compacted, which would make "compacted" mean something different per store.
        .setBottommostLevelCompaction(CompactRangeOptions.BottommostLevelCompaction.kForce);

    long start = System.currentTimeMillis();
    try (RocksDB db = RocksDB.open(dbOptions, path, cfDescs, handles)) {
      for (int i = 0; i < handles.size(); i++) {
        // Besu names its column families with single binary bytes, so render hex.
        final String cf = HexFormat.of().formatHex(cfDescs.get(i).getName());
        final long t0 = System.currentTimeMillis();
        db.compactRange(handles.get(i), null, null, cro);
        System.out.printf("  cf=%-28s %6.1fs%n", cf, (System.currentTimeMillis() - t0) / 1000.0);
      }
    } finally {
      for (ColumnFamilyHandle h : handles) h.close();
      cro.close();
      dbOptions.close();
    }
    System.out.printf("total %.1fs%n", (System.currentTimeMillis() - start) / 1000.0);
  }
}
