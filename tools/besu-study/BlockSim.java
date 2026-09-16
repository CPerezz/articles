// What does the data block holding a fixture code record actually cost?
//
// The fixture blobs themselves are near-free to store: 24,576 B deflating to ~1% on BOTH stores.
// So the 1.96x measured on a code read cannot be the fixture code. What differs is what shares
// its data block. RocksDB flushes a block once its UNCOMPRESSED size passes block_size (32 KiB
// here), so a 24,576 B record leaves ~8 KiB of room that the next records fill -- and code is
// keyed by code hash, so those neighbours are a uniform sample of each store's code population.
//
// This models the block: take each 24,576 B record, append following records until the block
// would exceed 32 KiB, and deflate the concatenation. That is the unit a lookup pays for.
//
// Usage: BlockSim <datadir>/database [block-size] [max-blocks]
import org.rocksdb.*;
import java.io.ByteArrayOutputStream;
import java.util.*;
import java.util.zip.Deflater;

public class BlockSim {
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
    final int FIX = 24576;
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

      long blocks = 0, rawTot = 0, compTot = 0, tenants = 0, tenantRaw = 0;
      long fixAloneRaw = 0, fixAloneComp = 0;

      try (ReadOptions ro = new ReadOptions().setFillCache(false).setVerifyChecksums(false);
           RocksIterator it = db.newIterator(code, ro)) {
        for (it.seekToFirst(); it.isValid() && blocks < maxBlocks; it.next()) {
          if (it.value().length != FIX) continue;
          // the fixture record on its own, for reference
          byte[] fix = it.value();
          fixAloneRaw += fix.length;
          fixAloneComp += deflated(fix);
          // now pack the block the way RocksDB would
          ByteArrayOutputStream buf = new ByteArrayOutputStream(blockSize * 2);
          buf.write(fix);
          int n = 0;
          it.next();
          while (it.isValid() && buf.size() < blockSize) {
            byte[] v = it.value();
            buf.write(v);
            tenantRaw += v.length;
            n++;
            it.next();
          }
          byte[] blk = buf.toByteArray();
          blocks++;
          tenants += n;
          rawTot += blk.length;
          compTot += deflated(blk);
          if (!it.isValid()) break;
        }
      }

      System.out.printf("store            : %s%n", path);
      System.out.printf("blocks simulated : %d  (block_size %,d B)%n", blocks, blockSize);
      System.out.printf("fixture alone    : %,d B raw -> deflate %.4f%n",
          FIX, (double) fixAloneComp / fixAloneRaw);
      System.out.printf("co-tenants       : %.1f records per block, %,.0f B raw each%n",
          (double) tenants / blocks, tenants == 0 ? 0.0 : (double) tenantRaw / tenants);
      System.out.printf("SIMULATED BLOCK  : %,.0f B raw -> %,.0f B compressed  (ratio %.4f)%n",
          (double) rawTot / blocks, (double) compTot / blocks, (double) compTot / rawTot);
    } finally {
      for (ColumnFamilyHandle h : handles) h.close();
      dbOptions.close();
    }
  }
}
