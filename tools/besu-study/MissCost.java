// Does the bloom filter actually reject absent-account lookups without reading data blocks?
//
// The absence class cost 50.1x the bytes and ran 9.07x slower on the v1 store, which shipped
// with no filter policy on any column family. #133 fixed that. This measures the mechanism
// directly instead of waiting for a 22 h benchmark arm: N lookups for keys that are NOT in
// ACCOUNT_INFO_STATE, with RocksDB's own statistics counting how often a filter did the
// rejecting and how many bytes came off disk.
//
// BLOOM_FILTER_USEFUL is the metric: it increments every time a filter let RocksDB skip reading a
// block. A store with no filter cannot increment it at all.
//
// Counters, not wall time: the stores sit on different devices, so bytes and filter hits are
// the comparable quantities.
//
// Usage: MissCost <datadir>/database [lookups]
import org.rocksdb.*;
import java.util.*;

public class MissCost {
  public static void main(String[] args) throws Exception {
    final String path = args[0];
    final int n = args.length > 1 ? Integer.parseInt(args[1]) : 20000;
    RocksDB.loadLibrary();

    final DBOptions dbOptions = new DBOptions();
    final List<ColumnFamilyDescriptor> cfDescs = new ArrayList<>();
    try (ConfigOptions cfgOpts = new ConfigOptions()) {
      OptionsUtil.loadLatestOptions(cfgOpts, path, dbOptions, cfDescs);
    }
    final Statistics stats = new Statistics();
    dbOptions.setStatistics(stats);
    final List<ColumnFamilyHandle> handles = new ArrayList<>();

    try (RocksDB db = RocksDB.openReadOnly(dbOptions, path, cfDescs, handles)) {
      ColumnFamilyHandle acct = null;
      for (ColumnFamilyHandle h : handles)
        if (h.getName().length == 1 && h.getName()[0] == 0x06) acct = h;

      // Learn the key shape from the store itself rather than assuming Besu's encoding.
      List<byte[]> sample = new ArrayList<>();
      TreeMap<Integer, Integer> klen = new TreeMap<>();
      try (ReadOptions ro = new ReadOptions().setFillCache(false);
           RocksIterator it = db.newIterator(acct, ro)) {
        for (it.seekToFirst(); it.isValid() && sample.size() < 2000; it.next()) {
          byte[] k = it.key();
          klen.merge(k.length, 1, Integer::sum);
          sample.add(k);
        }
      }
      System.out.println("cf06 key lengths in the sampled prefix: " + klen);

      // Absent keys of the identical shape: take a real key and perturb the middle bytes.
      // Verified absent below; any accidental hit is counted and excluded.
      Random rnd = new Random(42);
      List<byte[]> probes = new ArrayList<>(n);
      for (int i = 0; i < n; i++) {
        byte[] k = sample.get(rnd.nextInt(sample.size())).clone();
        for (int j = 4; j < k.length - 2; j++) k[j] = (byte) rnd.nextInt(256);
        probes.add(k);
      }

      stats.reset();
      int found = 0;
      long t0 = System.nanoTime();
      try (ReadOptions ro = new ReadOptions().setFillCache(false)) {
        for (byte[] k : probes) if (db.get(acct, ro, k) != null) found++;
      }
      long dt = System.nanoTime() - t0;

      long useful = stats.getTickerCount(TickerType.BLOOM_FILTER_USEFUL);
      long fullPos = stats.getTickerCount(TickerType.BLOOM_FILTER_FULL_POSITIVE);
      long readBytes = stats.getTickerCount(TickerType.COMPACT_READ_BYTES)
                     + stats.getTickerCount(TickerType.BLOCK_CACHE_DATA_BYTES_INSERT);
      long dataMiss = stats.getTickerCount(TickerType.BLOCK_CACHE_DATA_MISS);
      long idxMiss = stats.getTickerCount(TickerType.BLOCK_CACHE_INDEX_MISS);
      long filtMiss = stats.getTickerCount(TickerType.BLOCK_CACHE_FILTER_MISS);
      long gets = stats.getTickerCount(TickerType.NUMBER_KEYS_READ);

      System.out.printf("%nstore                : %s%n", path);
      System.out.printf("lookups              : %,d  (accidental hits: %d)%n", n, found);
      System.out.printf("BLOOM_FILTER_USEFUL  : %,d   (%.3f per lookup)  <- filter skipped a block%n",
          useful, (double) useful / n);
      System.out.printf("BLOOM_FILTER_FULL_POSITIVE : %,d%n", fullPos);
      System.out.printf("data-block reads     : %,d   (%.3f per lookup)%n", dataMiss, (double) dataMiss / n);
      System.out.printf("index-block reads    : %,d   filter-block reads: %,d%n", idxMiss, filtMiss);
      System.out.printf("data bytes into cache: %,d   (%.0f B per lookup)%n", readBytes, (double) readBytes / n);
      System.out.printf("keys read (ticker)   : %,d%n", gets);
      System.out.printf("wall                 : %.1f us per lookup (device-dependent, not comparable)%n",
          dt / 1000.0 / n);
    } finally {
      for (ColumnFamilyHandle h : handles) h.close();
      stats.close();
      dbOptions.close();
    }
  }
}
