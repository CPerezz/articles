// What is in each store's flat account keyspace, and what does an account block cost?
//
// The light tier (EOA, MINIMAL, SAME_MAX) sits 5.2% off parity after the snapshot is treated,
// and neither the bloom-filter nor the contract-code fix touches it. cf06 record geometry says
// the generated store's account records are 1.06x larger and 1.18x less compressible. A Bonsai
// flat account is RLP(nonce, balance, storageRoot, codeHash): an EOA carries EMPTY_TRIE_ROOT and
// EMPTY_CODE_HASH, two shared 32-byte constants that compress to nothing across a block, while a
// contract carries two unique hashes that compress to nothing at all. So the account block's
// cost should follow the contract share. This measures both.
//
// Deflate stands in for LZ4: comparative, not RocksDB's own figure.
//
// Usage: AcctMix <datadir>/database [block-size] [max-blocks]
import org.rocksdb.*;
import java.io.ByteArrayOutputStream;
import java.util.*;
import java.util.zip.Deflater;

public class AcctMix {
  // keccak256("") and the RLP-empty trie root, as they appear inside a flat account record
  static final byte[] EMPTY_CODE_HASH = hex(
      "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470");
  static final byte[] EMPTY_TRIE_ROOT = hex(
      "56e81f171bcc55a6ff8345e692c0f86e5b48e01b996cadc001622fb5e363b421");

  static byte[] hex(String s) {
    byte[] o = new byte[s.length() / 2];
    for (int i = 0; i < o.length; i++)
      o[i] = (byte) Integer.parseInt(s.substring(i * 2, i * 2 + 2), 16);
    return o;
  }

  static boolean contains(byte[] h, byte[] n) {
    outer:
    for (int i = 0; i + n.length <= h.length; i++) {
      for (int j = 0; j < n.length; j++) if (h[i + j] != n[j]) continue outer;
      return true;
    }
    return false;
  }

  static long deflated(byte[] v) {
    Deflater d = new Deflater(Deflater.BEST_SPEED);
    d.setInput(v);
    d.finish();
    byte[] out = new byte[v.length + 1024];
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
    final int blockSize = args.length > 1 ? Integer.parseInt(args[1]) : 32768;
    final int maxBlocks = args.length > 2 ? Integer.parseInt(args[2]) : 200;
    RocksDB.loadLibrary();

    final DBOptions dbOptions = new DBOptions();
    final List<ColumnFamilyDescriptor> cfDescs = new ArrayList<>();
    try (ConfigOptions cfgOpts = new ConfigOptions()) {
      OptionsUtil.loadLatestOptions(cfgOpts, path, dbOptions, cfDescs);
    }
    final List<ColumnFamilyHandle> handles = new ArrayList<>();

    try (RocksDB db = RocksDB.openReadOnly(dbOptions, path, cfDescs, handles)) {
      ColumnFamilyHandle acct = null;
      for (ColumnFamilyHandle h : handles) {
        byte[] n = h.getName();
        if (n.length == 1 && n[0] == 0x06) acct = h;
      }

      long blocks = 0, rawTot = 0, compTot = 0, recs = 0, recBytes = 0;
      long emptyCode = 0, emptyRoot = 0, bothEmpty = 0;

      try (ReadOptions ro = new ReadOptions().setFillCache(false).setVerifyChecksums(false);
           RocksIterator it = db.newIterator(acct, ro)) {
        it.seekToFirst();
        while (it.isValid() && blocks < maxBlocks) {
          ByteArrayOutputStream buf = new ByteArrayOutputStream(blockSize * 2);
          while (it.isValid() && buf.size() < blockSize) {
            byte[] v = it.value();
            buf.write(v);
            recs++;
            recBytes += v.length;
            boolean ec = contains(v, EMPTY_CODE_HASH), er = contains(v, EMPTY_TRIE_ROOT);
            if (ec) emptyCode++;
            if (er) emptyRoot++;
            if (ec && er) bothEmpty++;
            it.next();
          }
          byte[] blk = buf.toByteArray();
          blocks++;
          rawTot += blk.length;
          compTot += deflated(blk);
        }
      }

      System.out.printf("store             : %s%n", path);
      System.out.printf("records sampled   : %,d  (mean %,.1f B)%n", recs, (double) recBytes / recs);
      System.out.printf("empty code hash   : %,d  (%.1f%%)%n", emptyCode, 100.0 * emptyCode / recs);
      System.out.printf("empty storage root: %,d  (%.1f%%)%n", emptyRoot, 100.0 * emptyRoot / recs);
      System.out.printf("plain EOA (both)  : %,d  (%.1f%%)%n", bothEmpty, 100.0 * bothEmpty / recs);
      System.out.printf("ACCOUNT BLOCK     : %,.0f B raw -> %,.0f B compressed  (ratio %.4f)%n",
          (double) rawTot / blocks, (double) compTot / blocks, (double) compTot / rawTot);
    } finally {
      for (ColumnFamilyHandle h : handles) h.close();
      dbOptions.close();
    }
  }
}
