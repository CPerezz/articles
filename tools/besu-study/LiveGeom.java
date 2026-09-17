// Per-column-family geometry and code compressibility on a LIVE store.
//
// The probes that came before this one discover column families via
// OptionsUtil.loadLatestOptions, which fails on a store state-actor is still
// writing: it writes OPTIONS with librocksdb 10.10 and Besu's 10.6.2 rejects
// `max_manifest_space_amp_pct` until Besu itself reopens the store and rewrites
// the file. That reopen needs the write lock, which the generator holds.
//
// listColumnFamilies needs no OPTIONS file, and table properties are stored
// inside each SST, so plain ColumnFamilyOptions are enough to read them. A
// read-only open takes no lock and writes nothing, so this is safe to point at
// a store mid-generation. The view is the manifest as of open time; an SST
// compacted away underneath us surfaces as a read error, never as corruption.
import org.rocksdb.*;
import java.util.*;
import java.util.zip.Deflater;

public class LiveGeom {
    public static void main(String[] args) throws Exception {
        if (args.length < 1) {
            System.err.println("usage: LiveGeom <rocksdb-dir> [sampleTarget] [maxSamples]");
            System.exit(2);
        }
        String path = args[0];
        int target = args.length > 1 ? Integer.parseInt(args[1]) : 24576;
        int maxSamples = args.length > 2 ? Integer.parseInt(args[2]) : 3000;
        RocksDB.loadLibrary();

        List<byte[]> names;
        try (Options probe = new Options()) {
            names = RocksDB.listColumnFamilies(probe, path);
        }
        List<ColumnFamilyDescriptor> descs = new ArrayList<>();
        for (byte[] n : names) descs.add(new ColumnFamilyDescriptor(n, new ColumnFamilyOptions()));
        if (descs.isEmpty()) descs.add(new ColumnFamilyDescriptor(RocksDB.DEFAULT_COLUMN_FAMILY, new ColumnFamilyOptions()));

        List<ColumnFamilyHandle> handles = new ArrayList<>();
        DBOptions dbo = new DBOptions().setCreateIfMissing(false);
        RocksDB db = RocksDB.openReadOnly(dbo, path, descs, handles);
        try {
            System.out.printf("store : %s%n", path);
            System.out.printf("%-8s %14s %14s %14s %9s %9s %10s%n",
                    "cf", "entries", "raw_bytes", "file_bytes", "phys/log", "blk_B", "filter_B");
            ColumnFamilyHandle code = null;
            for (int i = 0; i < handles.size(); i++) {
                String label = label(names.get(i));
                Map<String, TableProperties> props = db.getPropertiesOfAllTables(handles.get(i));
                long entries = 0, raw = 0, file = 0, filter = 0, dataBlocks = 0;
                for (TableProperties tp : props.values()) {
                    entries += tp.getNumEntries();
                    raw += tp.getRawKeySize() + tp.getRawValueSize();
                    file += tp.getDataSize() + tp.getIndexSize() + tp.getFilterSize();
                    filter += tp.getFilterSize();
                    dataBlocks += tp.getNumDataBlocks();
                }
                if (entries == 0) continue;
                System.out.printf("%-8s %14d %14d %14d %9.3f %9d %10d%n",
                        label, entries, raw, file,
                        raw == 0 ? 0.0 : (double) file / raw,
                        dataBlocks == 0 ? 0 : file / dataBlocks,
                        filter);
                if (label.equals("cf07")) code = handles.get(i);
            }
            if (code == null) { System.out.println("no cf07 (CODE_STORAGE) in this store"); return; }

            // Code population: how compressible is a record on its own, and how
            // compressible is the payload that shares its data block.
            long nTarget = 0, dTarget = 0, rawTarget = 0;
            long nOther = 0, dOther = 0, rawOther = 0;
            long nAll = 0, sumLen = 0;
            Map<Integer, Integer> lens = new HashMap<>();
            List<byte[]> pool = new ArrayList<>();
            try (ReadOptions ro = new ReadOptions().setFillCache(false); RocksIterator it = db.newIterator(code, ro)) {
                for (it.seekToFirst(); it.isValid() && nAll < 400_000; it.next()) {
                    byte[] v = it.value();
                    nAll++; sumLen += v.length;
                    lens.merge(v.length, 1, Integer::sum);
                    if (v.length == target) {
                        if (nTarget < maxSamples) { nTarget++; rawTarget += v.length; dTarget += deflate(v); }
                    } else if (v.length >= 1024) {
                        if (nOther < maxSamples) {
                            nOther++; rawOther += v.length; dOther += deflate(v);
                            if (pool.size() < 2000) pool.add(v);
                        }
                    }
                }
            }
            System.out.printf("%nscanned      : %,d records  mean %,d B%n", nAll, nAll == 0 ? 0 : sumLen / nAll);
            if (nTarget > 0)
                System.out.printf("target %,d B : n=%d  deflate %.4f%n", target, nTarget, (double) dTarget / rawTarget);
            if (nOther > 0)
                System.out.printf("other >=1 KiB: n=%d  deflate %.4f  (mainnet 0.443)%n", nOther, (double) dOther / rawOther);

            // Packed: the co-tenant payload beside one fixture-sized contract.
            if (pool.size() > 8) {
                long rawP = 0, dP = 0;
                Random rnd = new Random(7);
                for (int rep = 0; rep < 60; rep++) {
                    java.io.ByteArrayOutputStream buf = new java.io.ByteArrayOutputStream();
                    while (buf.size() < 32768 - target) buf.write(pool.get(rnd.nextInt(pool.size())));
                    byte[] b = buf.toByteArray();
                    rawP += b.length; dP += deflate(b);
                }
                System.out.printf("packed block : deflate %.4f  (mainnet 0.329, v2 0.955)%n", (double) dP / rawP);
            }
            System.out.println("top value lengths:");
            lens.entrySet().stream()
                    .sorted((a, b) -> Long.compare((long) b.getValue() * b.getKey(), (long) a.getValue() * a.getKey()))
                    .limit(6)
                    .forEach(e -> System.out.printf("  %,10d B  x %,d%n", e.getKey(), e.getValue()));
        } finally {
            for (ColumnFamilyHandle h : handles) h.close();
            db.close();
            dbo.close();
        }
    }

    private static String label(byte[] n) {
        String s = new String(n);
        if (s.equals("default")) return "default";
        StringBuilder sb = new StringBuilder("cf");
        for (byte b : n) sb.append(String.format("%02x", b));
        return sb.toString();
    }

    private static int deflate(byte[] v) {
        Deflater d = new Deflater(Deflater.BEST_SPEED);
        d.setInput(v); d.finish();
        byte[] out = new byte[v.length + 64];
        int n = 0;
        while (!d.finished() && n < out.length) {
            int k = d.deflate(out, n, out.length - n);
            if (k == 0) break;
            n += k;
        }
        d.end();
        return n;
    }
}
