// How compressible is the contract code each generator wrote?
//
// The dark-tier residual (DIFF_MAX, JUMPDEST) is 1.96x the bytes per read, and that matches the
// compressed data-block size of cf07 CODE_STORAGE (2.08x) rather than anything about placement.
// Both stores are configured identically -- 32 KiB blocks, LZ4 -- so a 2x difference in physical
// block size can only come from the bytes themselves. The two arms' fixture contracts are
// written by different generators (EEST's pre-run on jochemnet, state-actor's code_pattern on
// the generated store), so this samples the records and measures them.
//
// Deflate stands in for LZ4: it is not the same algorithm, but it separates "structured" from
// "high-entropy" decisively, which is the question. Ratios are therefore comparative, not
// RocksDB's own.
//
// Usage: CodeEntropy <datadir>/database [value-length] [max-samples]
import org.rocksdb.*;
import java.util.*;
import java.util.zip.Deflater;

public class CodeEntropy {
  static long deflated(byte[] v) {
    Deflater d = new Deflater(Deflater.BEST_SPEED);
    d.setInput(v);
    d.finish();
    byte[] out = new byte[v.length + 64];
    long n = 0;
    while (!d.finished()) {
      int k = d.deflate(out);
      if (k == 0) break;
      n += k;
    }
    d.end();
    return n;
  }

  public static void main(String[] args) throws Exception {
    final String path = args[0];
    final int want = args.length > 1 ? Integer.parseInt(args[1]) : 24576;
    final int maxSamples = args.length > 2 ? Integer.parseInt(args[2]) : 300;
    RocksDB.loadLibrary();

    final DBOptions dbOptions = new DBOptions();
    final List<ColumnFamilyDescriptor> cfDescs = new ArrayList<>();
    try (ConfigOptions cfgOpts = new ConfigOptions()) {
      OptionsUtil.loadLatestOptions(cfgOpts, path, dbOptions, cfDescs);
    }
    final List<ColumnFamilyHandle> handles = new ArrayList<>();

    try (RocksDB db = RocksDB.openReadOnly(dbOptions, path, cfDescs, handles)) {
      ColumnFamilyHandle code = null;
      for (ColumnFamilyHandle h : handles) {
        byte[] n = h.getName();
        if (n.length == 1 && n[0] == 0x07) code = h;
      }
      if (code == null) {
        System.err.println("no cf 07 (CODE_STORAGE) in this store");
        System.exit(3);
      }

      // Length histogram over the whole sampled prefix, plus compressibility of the target
      // population. The histogram is what shows which generator wrote what.
      TreeMap<Integer, Long> hist = new TreeMap<>();
      long scanned = 0, samples = 0, raw = 0, comp = 0;
      // and the same for everything that is NOT the target length, as a within-store control
      long oRaw = 0, oComp = 0, oN = 0;

      try (ReadOptions ro = new ReadOptions().setFillCache(false).setVerifyChecksums(false);
           RocksIterator it = db.newIterator(code, ro)) {
        for (it.seekToFirst(); it.isValid(); it.next()) {
          byte[] v = it.value();
          scanned++;
          hist.merge(v.length, 1L, Long::sum);
          if (v.length == want) {
            if (samples < maxSamples) {
              samples++;
              raw += v.length;
              comp += deflated(v);
            }
          } else if (v.length >= 1024 && oN < maxSamples) {
            oN++;
            oRaw += v.length;
            oComp += deflated(v);
          }
          if (samples >= maxSamples && oN >= maxSamples) break;
          if (scanned >= 4_000_000) break;
        }
      }

      System.out.printf("store        : %s%n", path);
      System.out.printf("scanned      : %,d records%n", scanned);
      System.out.printf("target %,d B : n=%d  deflate ratio %.3f%n",
          want, samples, samples == 0 ? Double.NaN : (double) comp / raw);
      System.out.printf("other >=1 KiB : n=%d  deflate ratio %.3f%n",
          oN, oN == 0 ? Double.NaN : (double) oComp / oRaw);
      System.out.println("top value lengths in the scanned prefix:");
      hist.entrySet().stream()
          .sorted((a, b) -> Long.compare(b.getValue(), a.getValue()))
          .limit(8)
          .forEach(e -> System.out.printf("   %,10d B  x %,d%n", e.getKey(), e.getValue()));
    } finally {
      for (ColumnFamilyHandle h : handles) h.close();
      dbOptions.close();
    }
  }
}
