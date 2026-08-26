# Log mining report: container_compacted_db.log

Total lines: 96958. Container lifecycles (START/END pairs found): 914. Distinct geth message kinds: 86. Harness marker kinds: 2.

## 1. Message-kind census

| kind | type | count |
|---|---|---|
| 'Unclean shutdown detected' | human | 9140 |
| '' | human | 6398 |
| 'Opened ancient database' | human | 1829 |
| '---------------------------------------------------------------------------------------------------------------------------------------------------------' | human | 1828 |
| 'Chain head was updated' | human | 1828 |
| 'HTTP server started' | human | 1828 |
| 'Imported new potential chain segment' | human | 1828 |
| 'Slow block' | json | 1828 |
| 'HTTP server stopped' | human | 1818 |
| 'Allocated cache and file handles' | human | 915 |
| 'Allocated trie memory caches' | human | 915 |
| 'Enabling metrics collection' | human | 915 |
| 'Enabling stand-alone metrics HTTP endpoint address=127.0.0.1:8008' | human | 915 |
| 'Engine API maximum reorg depth' | human | 915 |
| 'Initialising Ethereum protocol' | human | 915 |
| 'Initializing the KZG library' | human | 915 |
| 'Load database journal from file' | human | 915 |
| 'Maximum peer count' | human | 915 |
| 'Opened Era store' | human | 915 |
| "Pebble database uses legacy v1 format; upgrade offline with 'geth db pebble-upgrade'" | human | 915 |
| 'Sanitizing invalid node buffer size' | human | 915 |
| 'Set global gas cap' | human | 915 |
| 'Smartcard socket not found, disabling' | human | 915 |
| 'Starting Geth on Ethereum mainnet...' | human | 915 |
| 'Starting metrics server' | human | 915 |
| 'State scheme set to already existing' | human | 915 |
| 'Using pebble as the backing database' | human | 915 |
| ' - Amsterdam:' | human | 914 |
| ' - Arrow Glacier:' | human | 914 |
| ' - BPO1:' | human | 914 |
| ' - BPO2:' | human | 914 |
| ' - Berlin:' | human | 914 |
| ' - Byzantium:' | human | 914 |
| ' - Cancun:' | human | 914 |
| ' - Constantinople:' | human | 914 |
| ' - DAO Fork:' | human | 914 |
| ' - Gray Glacier:' | human | 914 |
| ' - Homestead:' | human | 914 |
| ' - Istanbul:' | human | 914 |
| ' - London:' | human | 914 |
| ' - Muir Glacier:' | human | 914 |
| ' - Osaka:' | human | 914 |
| ' - Petersburg:' | human | 914 |
| ' - Prague:' | human | 914 |
| ' - Shanghai:' | human | 914 |
| ' - Spurious Dragon/1 (EIP 155): #2675000' | human | 914 |
| ' - Spurious Dragon/2 (EIP 158): #2675000' | human | 914 |
| ' - Tangerine Whistle (EIP 150): #2463000' | human | 914 |
| ' - Total terminal difficulty:' | human | 914 |
| 'All fork specifications can be found at https://ethereum.github.io/execution-specs/src/ethereum/forks/' | human | 914 |
| 'Chain ID:' | human | 914 |
| 'Chain history database is pruned' | human | 914 |
| 'Chain history is pruned' | human | 914 |
| 'Consensus: Beacon (proof-of-stake), merged from Ethash (proof-of-work)' | human | 914 |
| 'Enabled full-sync' | human | 914 |
| 'Gasprice oracle is ignoring threshold set threshold=2' | human | 914 |
| 'IPC endpoint opened' | human | 914 |
| 'Initialized log indexer' | human | 914 |
| 'Initialized path database' | human | 914 |
| 'Initialized transaction indexer' | human | 914 |
| 'Loaded JWT secret file' | human | 914 |
| 'Loaded last snap-sync pivot marker' | human | 914 |
| 'Loaded local transaction journal' | human | 914 |
| 'Loaded most recent local block' | human | 914 |
| 'Merge configured:' | human | 914 |
| 'New local node record' | human | 914 |
| 'Post-Merge hard forks (timestamp based):' | human | 914 |
| 'Pre-Merge hard forks (block based):' | human | 914 |
| 'Registered sync override service' | human | 914 |
| 'Started P2P networking' | human | 914 |
| 'Starting peer-to-peer node' | human | 914 |
| 'WebSocket enabled' | human | 914 |
| 'Blockchain stopped' | human | 909 |
| 'Ethereum protocol stopped' | human | 909 |
| 'Got interrupt, shutting down...' | human | 909 |
| 'IPC endpoint closed' | human | 909 |
| 'Log index tail unindexing finished' | human | 909 |
| 'Persisted dirty state to file' | human | 909 |
| 'Persisting dirty state' | human | 909 |
| 'Started log indexer' | human | 909 |
| 'Transaction pool stopped' | human | 909 |
| 'Loaded most recent local finalized block number=24,410,463 hash=452533..102c4e age=6mo2w4d' | human | 717 |
| 'Loaded most recent local finalized block number=24,410,463 hash=452533..102c4e age=6mo2w5d' | human | 197 |
| 'Log index head rendering finished' | human | 42 |
| 'Log index head rendering in progress' | human | 42 |
| 'Waiting background transaction indexer to exit' | human | 25 |

Harness container markers (not geth messages, shown separately):

- `#CONTAINER:START`: 915
- `#CONTAINER:END`: 914

## 2. First-occurrence verbatim

- kind 'Starting Geth on Ethereum mainnet...' (first at line 2):
  ```
  INFO [08-19|07:40:22.105] Starting Geth on Ethereum mainnet...
  ```
- kind 'Maximum peer count' (first at line 3):
  ```
  INFO [08-19|07:40:22.105] Maximum peer count                       ETH=0 total=0
  ```
- kind 'Smartcard socket not found, disabling' (first at line 4):
  ```
  INFO [08-19|07:40:22.106] Smartcard socket not found, disabling    err="stat /run/pcscd/pcscd.comm: no such file or directory"
  ```
- kind 'Set global gas cap' (first at line 5):
  ```
  INFO [08-19|07:40:22.110] Set global gas cap                       cap=50,000,000
  ```
- kind 'Engine API maximum reorg depth' (first at line 6):
  ```
  INFO [08-19|07:40:22.110] Engine API maximum reorg depth           depth=1024
  ```
- kind 'Initializing the KZG library' (first at line 7):
  ```
  INFO [08-19|07:40:22.137] Initializing the KZG library             backend=gokzg
  ```
- kind 'Enabling metrics collection' (first at line 8):
  ```
  INFO [08-19|07:40:22.138] Enabling metrics collection
  ```
- kind 'Enabling stand-alone metrics HTTP endpoint address=127.0.0.1:8008' (first at line 9):
  ```
  INFO [08-19|07:40:22.138] Enabling stand-alone metrics HTTP endpoint address=127.0.0.1:8008
  ```
- kind 'Starting metrics server' (first at line 10):
  ```
  INFO [08-19|07:40:22.138] Starting metrics server                  addr=http://127.0.0.1:8008/debug/metrics
  ```
- kind 'Allocated trie memory caches' (first at line 11):
  ```
  INFO [08-19|07:40:22.138] Allocated trie memory caches             clean=1023.00MiB dirty=1.00GiB
  ```
- kind 'Using pebble as the backing database' (first at line 12):
  ```
  INFO [08-19|07:40:22.167] Using pebble as the backing database
  ```
- kind "Pebble database uses legacy v1 format; upgrade offline with 'geth db pebble-upgrade'" (first at line 13):
  ```
  WARN [08-19|07:40:22.182] Pebble database uses legacy v1 format; upgrade offline with 'geth db pebble-upgrade'
  ```
- kind 'Allocated cache and file handles' (first at line 14):
  ```
  INFO [08-19|07:40:22.182] Allocated cache and file handles         database=/data/geth/chaindata cache=2.00GiB handles=536,870,908 version=v1
  ```
- kind 'Opened ancient database' (first at line 15):
  ```
  INFO [08-19|07:40:23.873] Opened ancient database                  database=/data/geth/chaindata/ancient/chain readonly=false
  ```
- kind 'Opened Era store' (first at line 16):
  ```
  INFO [08-19|07:40:23.873] Opened Era store                         datadir=/data/geth/chaindata/ancient/chain/era
  ```
- kind 'State scheme set to already existing' (first at line 17):
  ```
  INFO [08-19|07:40:23.875] State scheme set to already existing     scheme=path
  ```
- kind 'Initialising Ethereum protocol' (first at line 18):
  ```
  INFO [08-19|07:40:23.878] Initialising Ethereum protocol           network=1 dbversion=9
  ```
- kind 'Sanitizing invalid node buffer size' (first at line 19):
  ```
  WARN [08-19|07:40:23.878] Sanitizing invalid node buffer size      provided=1.00GiB updated=256.00MiB
  ```
- kind 'Load database journal from file' (first at line 20):
  ```
  INFO [08-19|07:40:23.878] Load database journal from file          path=/data/geth/triedb/merkle.journal
  ```
- kind 'Initialized path database' (first at line 22):
  ```
  INFO [08-19|07:40:26.558] Initialized path database                triecache=1023.00MiB statecache=0.00B buffer=256.00MiB state-history="last 90000 blocks" journal-dir=/data/geth/triedb
  ```
- kind '' (first at line 23):
  ```
  INFO [08-19|07:40:26.629] 
  ```
- kind '---------------------------------------------------------------------------------------------------------------------------------------------------------' (first at line 24):
  ```
  INFO [08-19|07:40:26.629] ---------------------------------------------------------------------------------------------------------------------------------------------------------
  ```
- kind 'Chain ID:' (first at line 25):
  ```
  INFO [08-19|07:40:26.629] Chain ID:  1 (mainnet)
  ```
- kind 'Consensus: Beacon (proof-of-stake), merged from Ethash (proof-of-work)' (first at line 26):
  ```
  INFO [08-19|07:40:26.629] Consensus: Beacon (proof-of-stake), merged from Ethash (proof-of-work)
  ```
- kind 'Pre-Merge hard forks (block based):' (first at line 28):
  ```
  INFO [08-19|07:40:26.629] Pre-Merge hard forks (block based):
  ```
- kind ' - Homestead:' (first at line 29):
  ```
  INFO [08-19|07:40:26.629]  - Homestead:                   #1150000 
  ```
- kind ' - DAO Fork:' (first at line 30):
  ```
  INFO [08-19|07:40:26.629]  - DAO Fork:                    #1920000 
  ```
- kind ' - Tangerine Whistle (EIP 150): #2463000' (first at line 31):
  ```
  INFO [08-19|07:40:26.629]  - Tangerine Whistle (EIP 150): #2463000 
  ```
- kind ' - Spurious Dragon/1 (EIP 155): #2675000' (first at line 32):
  ```
  INFO [08-19|07:40:26.629]  - Spurious Dragon/1 (EIP 155): #2675000 
  ```
- kind ' - Spurious Dragon/2 (EIP 158): #2675000' (first at line 33):
  ```
  INFO [08-19|07:40:26.629]  - Spurious Dragon/2 (EIP 158): #2675000 
  ```
- kind ' - Byzantium:' (first at line 34):
  ```
  INFO [08-19|07:40:26.629]  - Byzantium:                   #4370000 
  ```
- kind ' - Constantinople:' (first at line 35):
  ```
  INFO [08-19|07:40:26.629]  - Constantinople:              #7280000 
  ```
- kind ' - Petersburg:' (first at line 36):
  ```
  INFO [08-19|07:40:26.629]  - Petersburg:                  #7280000 
  ```
- kind ' - Istanbul:' (first at line 37):
  ```
  INFO [08-19|07:40:26.629]  - Istanbul:                    #9069000 
  ```
- kind ' - Muir Glacier:' (first at line 38):
  ```
  INFO [08-19|07:40:26.629]  - Muir Glacier:                #9200000 
  ```
- kind ' - Berlin:' (first at line 39):
  ```
  INFO [08-19|07:40:26.629]  - Berlin:                      #12244000
  ```
- kind ' - London:' (first at line 40):
  ```
  INFO [08-19|07:40:26.629]  - London:                      #12965000
  ```
- kind ' - Arrow Glacier:' (first at line 41):
  ```
  INFO [08-19|07:40:26.629]  - Arrow Glacier:               #13773000
  ```
- kind ' - Gray Glacier:' (first at line 42):
  ```
  INFO [08-19|07:40:26.629]  - Gray Glacier:                #15050000
  ```
- kind 'Merge configured:' (first at line 44):
  ```
  INFO [08-19|07:40:26.629] Merge configured:
  ```
- kind ' - Total terminal difficulty:' (first at line 45):
  ```
  INFO [08-19|07:40:26.629]  - Total terminal difficulty:  58750000000000000000000
  ```
- kind 'Post-Merge hard forks (timestamp based):' (first at line 47):
  ```
  INFO [08-19|07:40:26.629] Post-Merge hard forks (timestamp based):
  ```
- kind ' - Shanghai:' (first at line 48):
  ```
  INFO [08-19|07:40:26.629]  - Shanghai:                    @1681338455
  ```
- kind ' - Cancun:' (first at line 49):
  ```
  INFO [08-19|07:40:26.629]  - Cancun:                      @1710338135 blob: (target: 3, max: 6, fraction: 3338477)
  ```
- kind ' - Prague:' (first at line 50):
  ```
  INFO [08-19|07:40:26.629]  - Prague:                      @1746612311 blob: (target: 6, max: 9, fraction: 5007716)
  ```
- kind ' - Osaka:' (first at line 51):
  ```
  INFO [08-19|07:40:26.629]  - Osaka:                       @1764798551
  ```
- kind ' - BPO1:' (first at line 52):
  ```
  INFO [08-19|07:40:26.629]  - BPO1:                        @1765290071 blob: (target: 10, max: 15, fraction: 8346193)
  ```
- kind ' - BPO2:' (first at line 53):
  ```
  INFO [08-19|07:40:26.629]  - BPO2:                        @1767747671 blob: (target: 14, max: 21, fraction: 11684671)
  ```
- kind ' - Amsterdam:' (first at line 54):
  ```
  INFO [08-19|07:40:26.629]  - Amsterdam:                   @1769856769
  ```
- kind 'All fork specifications can be found at https://ethereum.github.io/execution-specs/src/ethereum/forks/' (first at line 56):
  ```
  INFO [08-19|07:40:26.629] All fork specifications can be found at https://ethereum.github.io/execution-specs/src/ethereum/forks/
  ```
- kind 'Chain history database is pruned' (first at line 60):
  ```
  WARN [08-19|07:40:26.634] Chain history database is pruned         tail=15,537,393 mode=all
  ```
- kind 'Loaded most recent local block' (first at line 61):
  ```
  INFO [08-19|07:40:26.634] Loaded most recent local block           number=24,410,463 hash=452533..102c4e age=6mo2w4d
  ```
- kind 'Loaded most recent local finalized block number=24,410,463 hash=452533..102c4e age=6mo2w4d' (first at line 62):
  ```
  INFO [08-19|07:40:26.634] Loaded most recent local finalized block number=24,410,463 hash=452533..102c4e age=6mo2w4d
  ```
- kind 'Loaded last snap-sync pivot marker' (first at line 63):
  ```
  INFO [08-19|07:40:26.634] Loaded last snap-sync pivot marker       number=22,882,515
  ```
- kind 'Chain history is pruned' (first at line 64):
  ```
  INFO [08-19|07:40:26.634] Chain history is pruned                  earliest=15,537,393 hash=55b11b..7bb286
  ```
- kind 'Initialized transaction indexer' (first at line 65):
  ```
  INFO [08-19|07:40:26.691] Initialized transaction indexer          range="last 2350000 blocks"
  ```
- kind 'Initialized log indexer' (first at line 66):
  ```
  INFO [08-19|07:40:26.692] Initialized log indexer                  firstblock=22,059,891 lastblock=24,410,463 firstmap=268,288 lastmap=354,323 headindexed=true
  ```
- kind 'Enabled full-sync' (first at line 67):
  ```
  INFO [08-19|07:40:26.715] Enabled full-sync                        head=24,410,463 hash=452533..102c4e
  ```
- kind 'Gasprice oracle is ignoring threshold set threshold=2' (first at line 68):
  ```
  INFO [08-19|07:40:26.715] Gasprice oracle is ignoring threshold set threshold=2
  ```
- kind 'Unclean shutdown detected' (first at line 69):
  ```
  WARN [08-19|07:40:26.715] Unclean shutdown detected                booted=2025-07-26T01:19:48+0000 age=1y4w1d
  ```
- kind 'Registered sync override service' (first at line 79):
  ```
  INFO [08-19|07:40:26.715] Registered sync override service
  ```
- kind 'Starting peer-to-peer node' (first at line 80):
  ```
  INFO [08-19|07:40:26.715] Starting peer-to-peer node               instance=Geth/v1.17.6-unstable-4d92c8e0-20260811/linux-amd64/go1.26.5
  ```
- kind 'IPC endpoint opened' (first at line 81):
  ```
  INFO [08-19|07:40:26.720] IPC endpoint opened                      url=/data/geth.ipc
  ```
- kind 'New local node record' (first at line 82):
  ```
  INFO [08-19|07:40:26.720] New local node record                    seq=1,786,196,574,821 id=019df6a866b5d3bb ip=127.0.0.1 udp=0 tcp=36565
  ```
- kind 'Started P2P networking' (first at line 83):
  ```
  INFO [08-19|07:40:26.720] Started P2P networking                   self="enode://81aa83d766d380b7565115cf091e6b22567819d379200a32d76b8c5436b2a33c67213fb66ae20dfc38822d2c300b31876832b66f6f4adc8b4c26f06f9beb730e@127.0.0.1:36565?discport=0"
  ```
- kind 'Loaded JWT secret file' (first at line 84):
  ```
  INFO [08-19|07:40:26.721] Loaded JWT secret file                   path=/tmp/jwtsecret                   crc32=0x502691be
  ```
- kind 'HTTP server started' (first at line 85):
  ```
  INFO [08-19|07:40:26.721] HTTP server started                      endpoint=[::]:8545 auth=false prefix= cors=* vhosts=*
  ```
- kind 'WebSocket enabled' (first at line 86):
  ```
  INFO [08-19|07:40:26.721] WebSocket enabled                        url=ws://[::]:8551
  ```
- kind 'Loaded local transaction journal' (first at line 88):
  ```
  INFO [08-19|07:40:26.721] Loaded local transaction journal         transactions=0 dropped=0
  ```
- kind 'Started log indexer' (first at line 89):
  ```
  INFO [08-19|07:40:27.181] Started log indexer
  ```
- kind 'Log index tail unindexing finished' (first at line 90):
  ```
  INFO [08-19|07:40:27.182] Log index tail unindexing finished       firstblock=22,059,891 lastblock=24,410,463 removedmaps=0 removedblocks=0 elapsed="795.039µs"
  ```
- kind 'Slow block' (first at line 91):
  ```
  WARN [08-19|07:40:27.329] {"level":"warn","msg":"Slow block","block":{"number":24410464,"hash":"0x8235e8775c9481926c9d36a22e01a174deb134103041533d13eda4ffd13fdd91","gas_used":537030,"tx_count":2},"timing":{"execution_ms":1.441124,"state_read_ms":1.376764,"state_hash_ms":1.459355,"commit_ms":1.566357,"total_ms":4.562189},"throughput":{"mgas_per_sec":117.71322932916632},"state_reads":{"accounts":6,"storage_slots":2,"code":0,"code_bytes":0},"state_writes":{"accounts":6,"accounts_deleted":0,"storage_slots":2,"storage_slots_deleted":0,"code":1,"code_bytes":111},"cache":{"account":{"hits":0,"misses":0,"hit_rate":0},"storage":{"hits":0,"misses":0,"hit_rate":0},"code":{"hits":0,"misses":0,"hit_rate":0,"hit_bytes":0,"miss_bytes":0}}}
  ```
- kind 'Imported new potential chain segment' (first at line 92):
  ```
  INFO [08-19|07:40:27.329] Imported new potential chain segment     number=24,410,464 hash=8235e8..3fdd91 blocks=1 txs=2 mgas=0.537 elapsed=4.726ms     mgasps=113.623 age=6mo2w4d   triediffs=217.32MiB triedirty=157.52MiB
  ```
- kind 'Chain head was updated' (first at line 93):
  ```
  INFO [08-19|07:40:27.330] Chain head was updated                   number=24,410,464 hash=8235e8..3fdd91 root=707ba5..5db2e2 elapsed="99.903µs"  age=6mo2w4d
  ```
- kind 'Got interrupt, shutting down...' (first at line 97):
  ```
  INFO [08-19|07:40:29.730] Got interrupt, shutting down...
  ```
- kind 'HTTP server stopped' (first at line 98):
  ```
  INFO [08-19|07:40:29.730] HTTP server stopped                      endpoint=[::]:8545
  ```
- kind 'IPC endpoint closed' (first at line 100):
  ```
  INFO [08-19|07:40:29.730] IPC endpoint closed                      url=/data/geth.ipc
  ```
- kind 'Ethereum protocol stopped' (first at line 101):
  ```
  INFO [08-19|07:40:29.730] Ethereum protocol stopped
  ```
- kind 'Transaction pool stopped' (first at line 102):
  ```
  INFO [08-19|07:40:29.732] Transaction pool stopped
  ```
- kind 'Persisting dirty state' (first at line 103):
  ```
  INFO [08-19|07:40:29.732] Persisting dirty state                   head=24,410,465 root=9755af..48133c layers=4248
  ```
- kind 'Persisted dirty state to file' (first at line 104):
  ```
  INFO [08-19|07:40:32.845] Persisted dirty state to file            path=/data/geth/triedb/merkle.journal size=380.15MiB elapsed=3.113s
  ```
- kind 'Blockchain stopped' (first at line 105):
  ```
  INFO [08-19|07:40:32.847] Blockchain stopped
  ```
- kind 'Waiting background transaction indexer to exit' (first at line 1057):
  ```
  INFO [08-19|07:44:05.792] Waiting background transaction indexer to exit
  ```
- kind 'Log index head rendering in progress' (first at line 3054):
  ```
  INFO [08-19|07:51:47.839] Log index head rendering in progress     firstblock=22,059,891 lastblock=24,410,464 processed=1 remaining=0 elapsed=1.458s
  ```
- kind 'Log index head rendering finished' (first at line 3055):
  ```
  INFO [08-19|07:51:47.839] Log index head rendering finished        firstblock=22,059,891 lastblock=24,410,464 processed=1 elapsed=1.458s
  ```
- kind 'Loaded most recent local finalized block number=24,410,463 hash=452533..102c4e age=6mo2w5d' (first at line 76108):
  ```
  INFO [08-19|12:39:36.319] Loaded most recent local finalized block number=24,410,463 hash=452533..102c4e age=6mo2w5d
  ```

## 3. Trie/cache configuration

- count=915
  ```
  INFO [08-19|07:40:22.138] Allocated trie memory caches             clean=1023.00MiB dirty=1.00GiB
  ```
- count=915
  ```
  INFO [08-19|07:40:22.182] Allocated cache and file handles         database=/data/geth/chaindata cache=2.00GiB handles=536,870,908 version=v1
  ```

## 4. Journal

- count=915
  ```
  INFO [08-19|07:40:23.878] Load database journal from file          path=/data/geth/triedb/merkle.journal
  ```
- count=914
  ```
  INFO [08-19|07:40:26.558] Initialized path database                triecache=1023.00MiB statecache=0.00B buffer=256.00MiB state-history="last 90000 blocks" journal-dir=/data/geth/triedb
  ```
- count=914
  ```
  INFO [08-19|07:40:26.721] Loaded local transaction journal         transactions=0 dropped=0
  ```
- count=909 (226 distinct verbatim variants across occurrences, e.g. differing timing/size values)
  ```
  INFO [08-19|07:40:32.845] Persisted dirty state to file            path=/data/geth/triedb/merkle.journal size=380.15MiB elapsed=3.113s
  ```

## 5. Snapshot / flat state

absent

## 6. Pebble / compaction / SST

- count=915
  ```
  INFO [08-19|07:40:22.167] Using pebble as the backing database
  ```
- count=915
  ```
  WARN [08-19|07:40:22.182] Pebble database uses legacy v1 format; upgrade offline with 'geth db pebble-upgrade'
  ```
- count=915
  ```
  INFO [08-19|07:40:23.873] Opened ancient database                  database=/data/geth/chaindata/ancient/chain readonly=false
  ```
- count=915
  ```
  INFO [08-19|07:40:23.873] Opened Era store                         datadir=/data/geth/chaindata/ancient/chain/era
  ```
- count=914
  ```
  INFO [08-19|07:40:26.062] Opened ancient database                  database=/data/geth/chaindata/ancient/state readonly=false
  ```

## 7. One complete container lifecycle (verbatim, in order)

Selected lifecycle: file lines 48471-48576 (pair 458 of 914 found). Dropped 6 repeated per-block spam lines (Slow block / Imported new potential chain segment / Chain head was updated).

```
#CONTAINER:START name=benchmarkoor-a20c0626-geth-bal-full-457 image=ghcr.io/jochem-brouwer/go-ethereum:glamsterdam-devnet-7-blobpool-fix container_id=70b3d4d278edcc741ee974efd2f4f3673a2ba71945cdf2d7691e93b00b7646a9
INFO [08-19|10:50:49.004] Starting Geth on Ethereum mainnet...
INFO [08-19|10:50:49.004] Maximum peer count                       ETH=0 total=0
INFO [08-19|10:50:49.005] Smartcard socket not found, disabling    err="stat /run/pcscd/pcscd.comm: no such file or directory"
INFO [08-19|10:50:49.009] Set global gas cap                       cap=50,000,000
INFO [08-19|10:50:49.009] Engine API maximum reorg depth           depth=1024
INFO [08-19|10:50:49.036] Initializing the KZG library             backend=gokzg
INFO [08-19|10:50:49.037] Enabling metrics collection
INFO [08-19|10:50:49.037] Enabling stand-alone metrics HTTP endpoint address=127.0.0.1:8008
INFO [08-19|10:50:49.037] Starting metrics server                  addr=http://127.0.0.1:8008/debug/metrics
INFO [08-19|10:50:49.037] Allocated trie memory caches             clean=1023.00MiB dirty=1.00GiB
INFO [08-19|10:50:49.067] Using pebble as the backing database
WARN [08-19|10:50:49.087] Pebble database uses legacy v1 format; upgrade offline with 'geth db pebble-upgrade'
INFO [08-19|10:50:49.087] Allocated cache and file handles         database=/data/geth/chaindata cache=2.00GiB handles=536,870,908 version=v1
INFO [08-19|10:50:50.863] Opened ancient database                  database=/data/geth/chaindata/ancient/chain readonly=false
INFO [08-19|10:50:50.863] Opened Era store                         datadir=/data/geth/chaindata/ancient/chain/era
INFO [08-19|10:50:50.865] State scheme set to already existing     scheme=path
INFO [08-19|10:50:50.868] Initialising Ethereum protocol           network=1 dbversion=9
WARN [08-19|10:50:50.868] Sanitizing invalid node buffer size      provided=1.00GiB updated=256.00MiB
INFO [08-19|10:50:50.868] Load database journal from file          path=/data/geth/triedb/merkle.journal
INFO [08-19|10:50:53.116] Opened ancient database                  database=/data/geth/chaindata/ancient/state readonly=false
INFO [08-19|10:50:53.635] Initialized path database                triecache=1023.00MiB statecache=0.00B buffer=256.00MiB state-history="last 90000 blocks" journal-dir=/data/geth/triedb
INFO [08-19|10:50:53.725] 
INFO [08-19|10:50:53.725] ---------------------------------------------------------------------------------------------------------------------------------------------------------
INFO [08-19|10:50:53.725] Chain ID:  1 (mainnet)
INFO [08-19|10:50:53.725] Consensus: Beacon (proof-of-stake), merged from Ethash (proof-of-work)
INFO [08-19|10:50:53.725] 
INFO [08-19|10:50:53.725] Pre-Merge hard forks (block based):
INFO [08-19|10:50:53.725]  - Homestead:                   #1150000 
INFO [08-19|10:50:53.725]  - DAO Fork:                    #1920000 
INFO [08-19|10:50:53.725]  - Tangerine Whistle (EIP 150): #2463000 
INFO [08-19|10:50:53.725]  - Spurious Dragon/1 (EIP 155): #2675000 
INFO [08-19|10:50:53.725]  - Spurious Dragon/2 (EIP 158): #2675000 
INFO [08-19|10:50:53.725]  - Byzantium:                   #4370000 
INFO [08-19|10:50:53.725]  - Constantinople:              #7280000 
INFO [08-19|10:50:53.725]  - Petersburg:                  #7280000 
INFO [08-19|10:50:53.725]  - Istanbul:                    #9069000 
INFO [08-19|10:50:53.725]  - Muir Glacier:                #9200000 
INFO [08-19|10:50:53.725]  - Berlin:                      #12244000
INFO [08-19|10:50:53.725]  - London:                      #12965000
INFO [08-19|10:50:53.725]  - Arrow Glacier:               #13773000
INFO [08-19|10:50:53.725]  - Gray Glacier:                #15050000
INFO [08-19|10:50:53.725] 
INFO [08-19|10:50:53.725] Merge configured:
INFO [08-19|10:50:53.725]  - Total terminal difficulty:  58750000000000000000000
INFO [08-19|10:50:53.725] 
INFO [08-19|10:50:53.725] Post-Merge hard forks (timestamp based):
INFO [08-19|10:50:53.725]  - Shanghai:                    @1681338455
INFO [08-19|10:50:53.725]  - Cancun:                      @1710338135 blob: (target: 3, max: 6, fraction: 3338477)
INFO [08-19|10:50:53.725]  - Prague:                      @1746612311 blob: (target: 6, max: 9, fraction: 5007716)
INFO [08-19|10:50:53.725]  - Osaka:                       @1764798551
INFO [08-19|10:50:53.725]  - BPO1:                        @1765290071 blob: (target: 10, max: 15, fraction: 8346193)
INFO [08-19|10:50:53.725]  - BPO2:                        @1767747671 blob: (target: 14, max: 21, fraction: 11684671)
INFO [08-19|10:50:53.725]  - Amsterdam:                   @1769856769
INFO [08-19|10:50:53.725] 
INFO [08-19|10:50:53.725] All fork specifications can be found at https://ethereum.github.io/execution-specs/src/ethereum/forks/
INFO [08-19|10:50:53.725] 
INFO [08-19|10:50:53.725] ---------------------------------------------------------------------------------------------------------------------------------------------------------
INFO [08-19|10:50:53.725] 
WARN [08-19|10:50:53.730] Chain history database is pruned         tail=15,537,393 mode=all
INFO [08-19|10:50:53.730] Loaded most recent local block           number=24,410,463 hash=452533..102c4e age=6mo2w4d
INFO [08-19|10:50:53.730] Loaded most recent local finalized block number=24,410,463 hash=452533..102c4e age=6mo2w4d
INFO [08-19|10:50:53.730] Loaded last snap-sync pivot marker       number=22,882,515
INFO [08-19|10:50:53.730] Chain history is pruned                  earliest=15,537,393 hash=55b11b..7bb286
INFO [08-19|10:50:53.793] Initialized transaction indexer          range="last 2350000 blocks"
INFO [08-19|10:50:53.794] Initialized log indexer                  firstblock=22,059,891 lastblock=24,410,463 firstmap=268,288 lastmap=354,323 headindexed=true
INFO [08-19|10:50:53.815] Enabled full-sync                        head=24,410,463 hash=452533..102c4e
INFO [08-19|10:50:53.815] Gasprice oracle is ignoring threshold set threshold=2
WARN [08-19|10:50:53.815] Unclean shutdown detected                booted=2025-07-26T01:19:48+0000 age=1y4w1d
WARN [08-19|10:50:53.815] Unclean shutdown detected                booted=2025-07-28T20:21:37+0000 age=1y3w5d
WARN [08-19|10:50:53.815] Unclean shutdown detected                booted=2025-07-30T05:55:59+0000 age=1y3w4d
WARN [08-19|10:50:53.815] Unclean shutdown detected                booted=2025-07-31T15:29:23+0000 age=1y3w2d
WARN [08-19|10:50:53.815] Unclean shutdown detected                booted=2025-08-21T14:14:31+0000 age=1y2d20h
WARN [08-19|10:50:53.815] Unclean shutdown detected                booted=2025-08-28T13:44:25+0000 age=11mo3w4d
WARN [08-19|10:50:53.815] Unclean shutdown detected                booted=2025-09-03T09:38:22+0000 age=11mo2w6d
WARN [08-19|10:50:53.815] Unclean shutdown detected                booted=2025-09-08T17:51:40+0000 age=11mo2w16h
WARN [08-19|10:50:53.815] Unclean shutdown detected                booted=2025-10-08T12:21:33+0000 age=10mo2w22h
WARN [08-19|10:50:53.815] Unclean shutdown detected                booted=2025-10-13T16:29:52+0000 age=10mo1w2d
INFO [08-19|10:50:53.815] Registered sync override service
INFO [08-19|10:50:53.815] Starting peer-to-peer node               instance=Geth/v1.17.6-unstable-4d92c8e0-20260811/linux-amd64/go1.26.5
INFO [08-19|10:50:53.819] IPC endpoint opened                      url=/data/geth.ipc
INFO [08-19|10:50:53.820] New local node record                    seq=1,786,196,574,821 id=019df6a866b5d3bb ip=127.0.0.1 udp=0 tcp=40935
INFO [08-19|10:50:53.820] Started P2P networking                   self="enode://81aa83d766d380b7565115cf091e6b22567819d379200a32d76b8c5436b2a33c67213fb66ae20dfc38822d2c300b31876832b66f6f4adc8b4c26f06f9beb730e@127.0.0.1:40935?discport=0"
INFO [08-19|10:50:53.822] Loaded JWT secret file                   path=/tmp/jwtsecret                   crc32=0x502691be
INFO [08-19|10:50:53.823] HTTP server started                      endpoint=[::]:8545 auth=false prefix= cors=* vhosts=*
INFO [08-19|10:50:53.823] WebSocket enabled                        url=ws://[::]:8551
INFO [08-19|10:50:53.823] HTTP server started                      endpoint=[::]:8551 auth=true  prefix= cors=localhost vhosts=*
INFO [08-19|10:50:53.823] Loaded local transaction journal         transactions=0 dropped=0
INFO [08-19|10:50:54.263] Started log indexer
INFO [08-19|10:50:54.358] Log index tail unindexing finished       firstblock=22,059,891 lastblock=24,410,464 removedmaps=0 removedblocks=0 elapsed=94.469ms
INFO [08-19|10:50:54.512] Got interrupt, shutting down...
INFO [08-19|10:50:54.512] HTTP server stopped                      endpoint=[::]:8545
INFO [08-19|10:50:54.512] HTTP server stopped                      endpoint=[::]:8551
INFO [08-19|10:50:54.512] IPC endpoint closed                      url=/data/geth.ipc
INFO [08-19|10:50:54.512] Ethereum protocol stopped
INFO [08-19|10:50:54.512] Transaction pool stopped
INFO [08-19|10:50:54.512] Persisting dirty state                   head=24,410,465 root=922e2c..d60417 layers=4248
INFO [08-19|10:50:57.653] Persisted dirty state to file            path=/data/geth/triedb/merkle.journal size=380.15MiB elapsed=3.140s
INFO [08-19|10:50:57.654] Blockchain stopped
#CONTAINER:END
```

## 8. Unclean shutdown

Count of `Unclean shutdown detected`: 9140

Every startup in this log emits a run of 10 such WARN lines (one per remembered prior unclean boot, capped at 10), immediately after `Enabled full-sync` / `Gasprice oracle is ignoring threshold` and before `Registered sync override service`. The `booted=` timestamps in the list are from 2025 (pre-benchmark) and stay identical run to run in this log (see section 7) -- the benchmark's own restarts are not appended to this history, and geth takes no corrective/repair action as a result of detecting them; execution proceeds immediately into normal P2P/HTTP startup.

5 lines of context before the block, the full block, and 5 lines after (showing the block has no visible consequence -- startup continues normally):

```
INFO [08-19|10:50:53.730] Chain history is pruned                  earliest=15,537,393 hash=55b11b..7bb286
INFO [08-19|10:50:53.793] Initialized transaction indexer          range="last 2350000 blocks"
INFO [08-19|10:50:53.794] Initialized log indexer                  firstblock=22,059,891 lastblock=24,410,463 firstmap=268,288 lastmap=354,323 headindexed=true
INFO [08-19|10:50:53.815] Enabled full-sync                        head=24,410,463 hash=452533..102c4e
INFO [08-19|10:50:53.815] Gasprice oracle is ignoring threshold set threshold=2
--- block start ---
WARN [08-19|10:50:53.815] Unclean shutdown detected                booted=2025-07-26T01:19:48+0000 age=1y4w1d
WARN [08-19|10:50:53.815] Unclean shutdown detected                booted=2025-07-28T20:21:37+0000 age=1y3w5d
WARN [08-19|10:50:53.815] Unclean shutdown detected                booted=2025-07-30T05:55:59+0000 age=1y3w4d
WARN [08-19|10:50:53.815] Unclean shutdown detected                booted=2025-07-31T15:29:23+0000 age=1y3w2d
WARN [08-19|10:50:53.815] Unclean shutdown detected                booted=2025-08-21T14:14:31+0000 age=1y2d20h
WARN [08-19|10:50:53.815] Unclean shutdown detected                booted=2025-08-28T13:44:25+0000 age=11mo3w4d
WARN [08-19|10:50:53.815] Unclean shutdown detected                booted=2025-09-03T09:38:22+0000 age=11mo2w6d
WARN [08-19|10:50:53.815] Unclean shutdown detected                booted=2025-09-08T17:51:40+0000 age=11mo2w16h
WARN [08-19|10:50:53.815] Unclean shutdown detected                booted=2025-10-08T12:21:33+0000 age=10mo2w22h
WARN [08-19|10:50:53.815] Unclean shutdown detected                booted=2025-10-13T16:29:52+0000 age=10mo1w2d
--- block end ---
INFO [08-19|10:50:53.815] Registered sync override service
INFO [08-19|10:50:53.815] Starting peer-to-peer node               instance=Geth/v1.17.6-unstable-4d92c8e0-20260811/linux-amd64/go1.26.5
INFO [08-19|10:50:53.819] IPC endpoint opened                      url=/data/geth.ipc
INFO [08-19|10:50:53.820] New local node record                    seq=1,786,196,574,821 id=019df6a866b5d3bb ip=127.0.0.1 udp=0 tcp=40935
INFO [08-19|10:50:53.820] Started P2P networking                   self="enode://81aa83d766d380b7565115cf091e6b22567819d379200a32d76b8c5436b2a33c67213fb66ae20dfc38822d2c300b31876832b66f6f4adc8b4c26f06f9beb730e@127.0.0.1:40935?discport=0"
```
