// What are the 23-byte code records that dominate the generated store's code keyspace?
// 23 bytes is the size of an EIP-7702 delegation designator: 0xef0100 || 20-byte address.
// If that is what they are, the "134M contracts" are delegated EOAs, each carrying a unique
// designator and therefore a unique code hash -- which is a different defect from "the
// generated contracts are too small".
//
// Usage: PeekCode <datadir>/database [value-length] [samples]
import org.rocksdb.*;
import java.util.*;

public class PeekCode {
  public static void main(String[] args) throws Exception {
    final String path = args[0];
    final int want = args.length > 1 ? Integer.parseInt(args[1]) : 23;
    final int samples = args.length > 2 ? Integer.parseInt(args[2]) : 6;
    RocksDB.loadLibrary();
    final DBOptions dbOptions = new DBOptions();
    final List<ColumnFamilyDescriptor> cfDescs = new ArrayList<>();
    try (ConfigOptions cfgOpts = new ConfigOptions()) {
      OptionsUtil.loadLatestOptions(cfgOpts, path, dbOptions, cfDescs);
    }
    final List<ColumnFamilyHandle> handles = new ArrayList<>();
    try (RocksDB db = RocksDB.openReadOnly(dbOptions, path, cfDescs, handles)) {
      ColumnFamilyHandle code = null;
      for (ColumnFamilyHandle h : handles)
        if (h.getName().length == 1 && h.getName()[0] == 0x07) code = h;

      int seen = 0, pref7702 = 0, total = 0;
      try (ReadOptions ro = new ReadOptions().setFillCache(false);
           RocksIterator it = db.newIterator(code, ro)) {
        for (it.seekToFirst(); it.isValid() && total < 400_000; it.next()) {
          byte[] v = it.value();
          total++;
          if (v.length != want) continue;
          boolean is7702 = v.length == 23
              && (v[0] & 0xff) == 0xef && (v[1] & 0xff) == 0x01 && (v[2] & 0xff) == 0x00;
          if (is7702) pref7702++;
          if (seen < samples) {
            StringBuilder sb = new StringBuilder();
            for (byte b : v) sb.append(String.format("%02x", b));
            System.out.printf("  value[%d] = %s%s%n", v.length, sb,
                is7702 ? "   <- 0xef0100 || address (EIP-7702 delegation)" : "");
            seen++;
          }
          if (seen >= samples && pref7702 > 2000) break;
        }
      }
      System.out.printf("scanned %,d records; of the %d-byte ones, %,d carried the 7702 prefix%n",
          total, want, pref7702);
    } finally {
      for (ColumnFamilyHandle h : handles) h.close();
      dbOptions.close();
    }
  }
}
