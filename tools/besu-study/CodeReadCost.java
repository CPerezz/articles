// What does one cold read of a distinct contract's code actually cost, in disk bytes?
//
// Two modes, because a single-process probe measures nothing: collecting the key sample
// warms exactly the blocks the read loop then reads, so the read loop hits the page cache
// and /proc/self/io reports only JVM startup. Run `sample` first, drop the page cache on
// the host, then run `read`.
//
// The block cache is sized explicitly (and identically on both arms) large enough to hold
// every block touched, so BLOCK_CACHE_DATA_MISS is the true first-touch block count rather
// than a measure of cache thrash. The default 8 MB cache makes that counter meaningless.
//
// Population: EXISTING_CONTRACT_DIFF_MAX is 150,000 contracts of exactly 24,576 bytes and
// both stores were generated from the same state-actor spec (hash 74dea7d1...), so
// selecting cf07 values of exactly that length selects the same contracts in both.
//
// Disk bytes come from /proc/self/io read_bytes - what the block layer served - so the
// headline number is measured, not modelled.
import org.rocksdb.*;
import java.io.*;
import java.nio.file.*;
import java.util.*;

public class CodeReadCost {
    static long readBytes() throws Exception {
        for (String l : Files.readAllLines(Paths.get("/proc/self/io")))
            if (l.startsWith("read_bytes:")) return Long.parseLong(l.split("\\s+")[1]);
        return -1;
    }

    static final long CACHE = 4L << 30;  // holds every block touched; identical on both arms

    public static void main(String[] args) throws Exception {
        if (args.length < 3) {
            System.err.println("usage: CodeReadCost <sample|read> <rocksdb-dir> <keyfile> [targetLen] [n]");
            System.exit(2);
        }
        String mode = args[0], path = args[1], keyfile = args[2];
        int targetLen = args.length > 3 ? Integer.parseInt(args[3]) : 24576;
        int n = args.length > 4 ? Integer.parseInt(args[4]) : 4000;
        RocksDB.loadLibrary();

        List<byte[]> names;
        try (Options o = new Options()) { names = RocksDB.listColumnFamilies(o, path); }
        Cache cache = new LRUCache(CACHE);
        BlockBasedTableConfig tc = new BlockBasedTableConfig().setBlockCache(cache);
        List<ColumnFamilyDescriptor> descs = new ArrayList<>();
        for (byte[] nm : names)
            descs.add(new ColumnFamilyDescriptor(nm, new ColumnFamilyOptions().setTableFormatConfig(tc)));

        Statistics stats = new Statistics();
        List<ColumnFamilyHandle> handles = new ArrayList<>();
        DBOptions dbo = new DBOptions().setCreateIfMissing(false).setStatistics(stats);
        RocksDB db = RocksDB.openReadOnly(dbo, path, descs, handles);
        try {
            ColumnFamilyHandle code = null;
            for (int i = 0; i < names.size(); i++) {
                StringBuilder sb = new StringBuilder("cf");
                for (byte b : names.get(i)) sb.append(String.format("%02x", b));
                if (sb.toString().equals("cf07")) code = handles.get(i);
            }
            if (code == null) { System.out.println("no cf07"); return; }

            if (mode.equals("sample")) {
                List<byte[]> keys = new ArrayList<>();
                try (ReadOptions ro = new ReadOptions().setFillCache(false);
                     RocksIterator it = db.newIterator(code, ro)) {
                    for (it.seekToFirst(); it.isValid() && keys.size() < n; it.next())
                        if (it.value().length == targetLen) keys.add(it.key());
                }
                Collections.shuffle(keys, new Random(42));
                try (DataOutputStream out = new DataOutputStream(
                        new BufferedOutputStream(new FileOutputStream(keyfile)))) {
                    out.writeInt(keys.size());
                    for (byte[] k : keys) { out.writeInt(k.length); out.write(k); }
                }
                System.out.printf("sampled %,d keys of value length %,d B -> %s%n",
                        keys.size(), targetLen, keyfile);
                return;
            }

            List<byte[]> keys = new ArrayList<>();
            try (DataInputStream in = new DataInputStream(
                    new BufferedInputStream(new FileInputStream(keyfile)))) {
                int cnt = in.readInt();
                for (int i = 0; i < cnt; i++) {
                    byte[] k = new byte[in.readInt()];
                    in.readFully(k);
                    keys.add(k);
                }
            }
            long b0 = readBytes(), t0 = System.nanoTime(), out = 0, hit = 0;
            try (ReadOptions ro = new ReadOptions().setFillCache(true)) {
                for (byte[] k : keys) {
                    byte[] v = db.get(code, ro, k);
                    if (v != null) { out += v.length; hit++; }
                }
            }
            long dt = System.nanoTime() - t0, b1 = readBytes();
            int r = keys.size();
            long blk = stats.getTickerCount(TickerType.BLOCK_CACHE_DATA_MISS);
            long ins = stats.getTickerCount(TickerType.BLOCK_CACHE_DATA_BYTES_INSERT);
            System.out.printf("store        : %s%n", path);
            System.out.printf("reads        : %,d  (found %,d, code returned %,d B)%n", r, hit, out);
            System.out.printf("DISK bytes   : %,d  ->  %,.0f B per code read%n", b1 - b0, (double)(b1 - b0) / r);
            System.out.printf("data blocks  : %,d  ->  %.3f per read (first touch)%n", blk, (double) blk / r);
            System.out.printf("block bytes  : %,d uncompressed  ->  %,.0f B per read%n", ins, (double) ins / r);
            System.out.printf("wall         : %.1f us per read%n", dt / 1000.0 / r);
            System.out.printf("amplification: %.2fx disk bytes per byte of code returned%n",
                    (double)(b1 - b0) / Math.max(1, out));
        } finally {
            for (ColumnFamilyHandle h : handles) h.close();
            db.close(); dbo.close(); stats.close(); cache.close();
        }
    }
}
