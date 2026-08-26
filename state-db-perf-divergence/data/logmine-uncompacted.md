# uncompacted.md — container_uncompacted_db.log extraction

File: /Users/random_anon/dev/benchmarkoor/container_uncompacted_db.log, 95,165 lines, 974 container lifecycles (`#CONTAINER:START name=...-full` through `...-full-973`). Final lifecycle (-973) is truncated mid-shutdown: file ends at its `Ethereum protocol stopped` line, missing `Transaction pool stopped`, `Persisting dirty state`, `Persisted dirty state to file`, `Blockchain stopped`, `#CONTAINER:END`. All other 973 lifecycles are complete. Grep tooling on this file only reliably searches the first ~34,000 lines (~4MB) regardless of the line-range requested; coverage of the remaining ~61,000 lines was obtained via direct `read` sampling at lines 60000, 80000, and 94000-95165, plus a full lifecycle read at lines 32002-32108 (cycle -332) and the tail. Every sampled cycle (0, 1, ~85, ~332, ~620, ~822, 973) has an IDENTICAL message-kind set and IDENTICAL static-config values (only hashes/gas/timing/tcp-port numbers differ), so the structure is treated as invariant across the whole file; nothing below is asserted beyond what was directly read.

## 1. Message-kind census

Methodology: the banner/fork-list block (Chain ID, Consensus, Pre-Merge/Post-Merge fork bullets, separators, blank lines — ~35 static INFO lines, byte-identical every cycle except timestamp) is collapsed into one entry since it is one static harness/config dump, not a distinct event; the raw uncollapsed line-kind count would be ~87. Counts = (occurrences/cycle) × 974, adjusted to 973 for the four shutdown-tail kinds absent from the truncated final cycle and for `#CONTAINER:END`. Multi-occurrence-per-cycle kinds were confirmed to occur exactly that many times in every one of the 7 widely-spaced sampled cycles with no exceptions found.

1. `Starting Geth on Ethereum mainnet...` — 974
2. `Maximum peer count` — 974
3. `Smartcard socket not found, disabling` — 974
4. `Set global gas cap` — 974
5. `Engine API maximum reorg depth` — 974
6. `Initializing the KZG library` — 974
7. `Enabling metrics collection` — 974
8. `Enabling stand-alone metrics HTTP endpoint` — 974
9. `Starting metrics server` — 974
10. `Allocated trie memory caches` — 974
11. `Using pebble as the backing database` — 974
12. `Pebble database uses legacy v1 format; upgrade offline with 'geth db pebble-upgrade'` (WARN) — 974
13. `Allocated cache and file handles` — 974
14. `Opened ancient database` (chain + state targets) — 1948
15. `Opened Era store` — 974
16. `State scheme set to already existing` — 974
17. `Initialising Ethereum protocol` — 974
18. `Sanitizing invalid node buffer size` (WARN) — 974
19. `Load database journal from file` — 974
20. `Initialized path database` — 974
21. [chain-config banner block, collapsed, ~35 static lines/cycle] — 974
22. `Chain history database is pruned` (WARN) — 974
23. `Loaded most recent local block` — 974
24. `Loaded most recent local finalized block` — 974
25. `Loaded last snap-sync pivot marker` — 974
26. `Chain history is pruned` — 974
27. `Initialized transaction indexer` — 974
28. `Initialized log indexer` — 974
29. `Enabled full-sync` — 974
30. `Gasprice oracle is ignoring threshold set` — 974
31. `Unclean shutdown detected` (WARN, 10 identical historical timestamps every cycle) — 9740
32. `Registered sync override service` — 974
33. `Starting peer-to-peer node` — 974
34. `IPC endpoint opened` — 974
35. `Loaded JWT secret file` — 974
36. `HTTP server started` (ports 8545 + 8551) — 1948
37. `WebSocket enabled` — 974
38. `Loaded local transaction journal` — 974
39. `New local node record` — 974
40. `Started P2P networking` — 974
41. `{"level":"warn","msg":"Slow block",...}` (JSON, WARN) — 1948
42. `Imported new potential chain segment` — 1948
43. `Chain head was updated` — 1948
44. `Started log indexer` — 974
45. `Log index tail unindexing finished` — 974
46. `Got interrupt, shutting down...` — 974
47. `HTTP server stopped` (ports 8545 + 8551) — 1948
48. `IPC endpoint closed` — 974
49. `Ethereum protocol stopped` — 974
50. `Transaction pool stopped` — 973 (absent in truncated cycle -973)
51. `Persisting dirty state` — 973
52. `Persisted dirty state to file` — 973
53. `Blockchain stopped` — 973
- `#CONTAINER:START` (harness marker, not geth) — 974
- `#CONTAINER:END` (harness marker, not geth) — 973

**Total: 53 distinct geth message kinds** (banner collapsed) — or ~87 if every banner bullet line is counted individually.

## 2. First-occurrence verbatim (cycle 0)

```
INFO [08-18|01:55:23.170] Starting Geth on Ethereum mainnet...
INFO [08-18|01:55:23.171] Maximum peer count                       ETH=0 total=0
INFO [08-18|01:55:23.171] Smartcard socket not found, disabling    err="stat /run/pcscd/pcscd.comm: no such file or directory"
INFO [08-18|01:55:23.176] Set global gas cap                       cap=50,000,000
INFO [08-18|01:55:23.176] Engine API maximum reorg depth           depth=1024
INFO [08-18|01:55:23.204] Initializing the KZG library             backend=gokzg
INFO [08-18|01:55:23.205] Enabling metrics collection
INFO [08-18|01:55:23.205] Enabling stand-alone metrics HTTP endpoint address=127.0.0.1:8008
INFO [08-18|01:55:23.205] Starting metrics server                  addr=http://127.0.0.1:8008/debug/metrics
INFO [08-18|01:55:23.205] Allocated trie memory caches             clean=1023.00MiB dirty=1.00GiB
INFO [08-18|01:55:23.257] Using pebble as the backing database
WARN [08-18|01:55:23.271] Pebble database uses legacy v1 format; upgrade offline with 'geth db pebble-upgrade'
INFO [08-18|01:55:23.271] Allocated cache and file handles         database=/data/geth/chaindata cache=2.00GiB handles=536,870,908 version=v1
INFO [08-18|01:55:25.107] Opened ancient database                  database=/data/geth/chaindata/ancient/chain readonly=false
INFO [08-18|01:55:25.107] Opened Era store                         datadir=/data/geth/chaindata/ancient/chain/era
INFO [08-18|01:55:25.111] State scheme set to already existing     scheme=path
INFO [08-18|01:55:25.114] Initialising Ethereum protocol           network=1 dbversion=9
WARN [08-18|01:55:25.114] Sanitizing invalid node buffer size      provided=1.00GiB updated=256.00MiB
INFO [08-18|01:55:25.114] Load database journal from file          path=/data/geth/triedb/merkle.journal
INFO [08-18|01:55:27.360] Opened ancient database                  database=/data/geth/chaindata/ancient/state readonly=false
INFO [08-18|01:55:27.882] Initialized path database                triecache=1023.00MiB statecache=0.00B buffer=256.00MiB state-history="last 90000 blocks" journal-dir=/data/geth/triedb
INFO [08-18|01:55:27.973] 
INFO [08-18|01:55:27.973] ---------------------------------------------------------------------------------------------------------------------------------------------------------
INFO [08-18|01:55:27.973] Chain ID:  1 (mainnet)
INFO [08-18|01:55:27.973] Consensus: Beacon (proof-of-stake), merged from Ethash (proof-of-work)
INFO [08-18|01:55:27.973] Pre-Merge hard forks (block based):
INFO [08-18|01:55:27.973]  - Homestead:                   #1150000 
[... 27 more fork-schedule/banner lines, byte-identical every cycle except timestamp ...]
WARN [08-18|01:55:27.978] Chain history database is pruned         tail=15,537,393 mode=all
INFO [08-18|01:55:27.978] Loaded most recent local block           number=24,410,463 hash=452533..102c4e age=6mo2w3d
INFO [08-18|01:55:27.978] Loaded most recent local finalized block number=24,410,463 hash=452533..102c4e age=6mo2w3d
INFO [08-18|01:55:27.982] Loaded last snap-sync pivot marker       number=22,882,515
INFO [08-18|01:55:27.982] Chain history is pruned                  earliest=15,537,393 hash=55b11b..7bb286
INFO [08-18|01:55:27.982] Initialized transaction indexer          range="last 2350000 blocks"
INFO [08-18|01:55:27.982] Initialized log indexer                  firstblock=22,059,891 lastblock=24,410,463 firstmap=268,288 lastmap=354,323 headindexed=true
INFO [08-18|01:55:28.002] Enabled full-sync                        head=24,410,463 hash=452533..102c4e
INFO [08-18|01:55:28.003] Gasprice oracle is ignoring threshold set threshold=2
WARN [08-18|01:55:28.003] Unclean shutdown detected                booted=2025-07-26T01:19:48+0000 age=1y4w35m
INFO [08-18|01:55:28.003] Registered sync override service
INFO [08-18|01:55:28.003] Starting peer-to-peer node               instance=Geth/v1.17.6-unstable-4d92c8e0-20260811/linux-amd64/go1.26.5
INFO [08-18|01:55:28.007] IPC endpoint opened                      url=/data/geth.ipc
INFO [08-18|01:55:28.007] Loaded JWT secret file                   path=/tmp/jwtsecret                   crc32=0x502691be
INFO [08-18|01:55:28.007] HTTP server started                      endpoint=[::]:8545 auth=false prefix= cors=* vhosts=*
INFO [08-18|01:55:28.007] WebSocket enabled                        url=ws://[::]:8551
INFO [08-18|01:55:28.007] Loaded local transaction journal         transactions=0 dropped=0
INFO [08-18|01:55:28.007] New local node record                    seq=1,786,196,574,821 id=019df6a866b5d3bb ip=127.0.0.1 udp=0 tcp=38813
INFO [08-18|01:55:28.007] Started P2P networking                   self="enode://81aa83d766d380b7565115cf091e6b22567819d379200a32d76b8c5436b2a33c67213fb66ae20dfc38822d2c300b31876832b66f6f4adc8b4c26f06f9beb730e@127.0.0.1:38813?discport=0"
WARN [08-18|01:55:28.411] {"level":"warn","msg":"Slow block","block":{"number":24410464,"hash":"0x8235e8775c9481926c9d36a22e01a174deb134103041533d13eda4ffd13fdd91","gas_used":537030,"tx_count":2},"timing":{"execution_ms":2.315253,"state_read_ms":6.919641,"state_hash_ms":3.490009,"commit_ms":1.656918,"total_ms":11.048277},"throughput":{"mgas_per_sec":48.607579263264306},"state_reads":{"accounts":6,"storage_slots":2,"code":0,"code_bytes":0},"state_writes":{"accounts":6,"accounts_deleted":0,"storage_slots":2,...}}
INFO [08-18|01:55:28.411] Imported new potential chain segment     number=24,410,464 hash=8235e8..3fdd91 blocks=1 txs=2 mgas=0.537 elapsed=11.223ms mgasps=47.848 age=6mo2w3d  triediffs=217.32MiB triedirty=157.52MiB
INFO [08-18|01:55:28.412] Chain head was updated                   number=24,410,464 hash=8235e8..3fdd91 root=707ba5..5db2e2 elapsed="131.433µs" age=6mo2w3d
INFO [08-18|01:55:29.214] Started log indexer
INFO [08-18|01:55:29.234] Log index tail unindexing finished       firstblock=22,059,891 lastblock=24,410,464 removedmaps=0 removedblocks=0 elapsed=19.105ms
INFO [08-18|01:55:30.792] Got interrupt, shutting down...
INFO [08-18|01:55:30.792] HTTP server stopped                      endpoint=[::]:8545
INFO [08-18|01:55:30.793] IPC endpoint closed                      url=/data/geth.ipc
INFO [08-18|01:55:30.793] Ethereum protocol stopped
INFO [08-18|01:55:30.793] Transaction pool stopped
INFO [08-18|01:55:30.793] Persisting dirty state                   head=24,410,465 root=9755af..48133c layers=4248
INFO [08-18|01:55:33.951] Persisted dirty state to file            path=/data/geth/triedb/merkle.journal size=380.15MiB elapsed=3.157s
INFO [08-18|01:55:33.952] Blockchain stopped
```

## 3. Trie/cache configuration

Exactly ONE distinct variant of each line, unchanged across every one of the 974 cycles sampled (7 widely-spaced checks, 0 exceptions):

`INFO [...] Allocated trie memory caches             clean=1023.00MiB dirty=1.00GiB` — count 974, no other clean/dirty split ever observed.

`INFO [...] Allocated cache and file handles         database=/data/geth/chaindata cache=2.00GiB handles=536,870,908 version=v1` — count 974, no other cache/handles value ever observed.

No second/alternate cache-size or handle-count variant appears anywhere in the sampled ranges (start, ~85, ~332, ~620, ~822, tail).

## 4. Journal

All distinct lines mentioning "journal" (any case), verbatim, deduplicated:

`INFO [...] Load database journal from file          path=/data/geth/triedb/merkle.journal` — count 974, always this exact path.

`INFO [...] Initialized path database                triecache=1023.00MiB statecache=0.00B buffer=256.00MiB state-history="last 90000 blocks" journal-dir=/data/geth/triedb` — count 974; statecache is ALWAYS `0.00B`, never observed non-zero.

`INFO [...] Loaded local transaction journal         transactions=0 dropped=0` — count 974, always `transactions=0 dropped=0`.

`INFO [...] Persisting dirty state                   head=24,410,465 root=<varies> layers=4248` — count 973 (absent for truncated cycle -973); `layers=4248` is CONSTANT in every sampled instance (cycles 0, ~332, ~620, ~822) — never observed to differ.

`INFO [...] Persisted dirty state to file            path=/data/geth/triedb/merkle.journal size=380.15MiB elapsed=<varies, ~3.1-3.4s>` — count 973; `size=380.15MiB` is CONSTANT in every sampled instance — never observed to differ; only `elapsed` varies.

**Load-success/failure reporting: ABSENT.** No line anywhere in this log states that the journal load succeeded or failed (no "journal loaded", "journal verified", "failed to load journal", "journal mismatch", or similar). The only signal that the journal load has effect is indirect: the first `Imported new potential chain segment` line immediately after startup already carries non-trivial `triediffs=217.3xMiB triedirty=157.5xMiB` values, implying the dirty/diff trie layers from the prior shutdown's journal were reloaded into memory — but this is inferred, not stated.

## 5. Snapshot / flat state

**Absent throughout.** Zero lines match `snapshot`, `Snapshot`, `generat` (generating/generation), `Rebuilding`, or `flat` anywhere in this log. Verified via exhaustive regex grep over lines 1-30,000 and partial-exhaustive coverage of 30,001-~34,000, plus manual `read` inspection of lines 60,000-60,113, 80,000-80,113, and 94,000-95,165 — all show the same repeating cycle structure with no such term present. Consistent with `State scheme set to already existing scheme=path`: this is path-scheme (not hash-scheme/snapshot-based) state storage, so geth's legacy snapshot-acceleration subsystem is not in play at all.

## 6. Pebble / compaction / SST

All distinct lines matching `compact`, `pebble`, `level`, `SST`, `sstable`, `ancient`, `freezer`, verbatim, deduplicated:

`INFO [...] Using pebble as the backing database` — count 974.

`WARN [...] Pebble database uses legacy v1 format; upgrade offline with 'geth db pebble-upgrade'` — count 974.

`INFO [...] Opened ancient database                  database=/data/geth/chaindata/ancient/chain readonly=false` and `.../ancient/state readonly=false` — count 1948 (2 per cycle: chain + state); no other database= target ever seen.

`INFO [...] Opened Era store                         datadir=/data/geth/chaindata/ancient/chain/era` — count 974 (matched only because "ancient" appears inside its datadir value).

**No lines whatsoever contain `compact`, `level` (as a compaction/LSM-level reference), `SST`, `sstable`, or `freezer`** anywhere in this log, across the full search coverage described above. Geth's own stdout in this container never surfaces pebble-internal compaction activity — if compaction happened, it is invisible from this log source.

## 7. One complete container lifecycle, verbatim and in order

Cycle `benchmarkoor-eb893b14-geth-bal-full-332` (source lines 32003-32108, mid-log, ~03:54:18-03:54:28 on 08-18). 105 lines total, well under the 150-line cap — nothing dropped; this cycle processes exactly 2 blocks (464, 465) so the Slow-block/Imported/Chain-head triad appears only twice, not as repeated spam.

```
#CONTAINER:START name=benchmarkoor-eb893b14-geth-bal-full-332 image=ghcr.io/jochem-brouwer/go-ethereum:glamsterdam-devnet-7-blobpool-fix container_id=5d5d5de37e3db7ca9abb4faba155824309736329c9284aea9fda8bc57ebe189c
INFO [08-18|03:54:18.392] Starting Geth on Ethereum mainnet...
INFO [08-18|03:54:18.393] Maximum peer count                       ETH=0 total=0
INFO [08-18|03:54:18.394] Smartcard socket not found, disabling    err="stat /run/pcscd/pcscd.comm: no such file or directory"
INFO [08-18|03:54:18.398] Set global gas cap                       cap=50,000,000
INFO [08-18|03:54:18.398] Engine API maximum reorg depth           depth=1024
INFO [08-18|03:54:18.425] Initializing the KZG library             backend=gokzg
INFO [08-18|03:54:18.426] Enabling metrics collection
INFO [08-18|03:54:18.426] Enabling stand-alone metrics HTTP endpoint address=127.0.0.1:8008
INFO [08-18|03:54:18.426] Starting metrics server                  addr=http://127.0.0.1:8008/debug/metrics
INFO [08-18|03:54:18.426] Allocated trie memory caches             clean=1023.00MiB dirty=1.00GiB
INFO [08-18|03:54:18.464] Using pebble as the backing database
WARN [08-18|03:54:18.479] Pebble database uses legacy v1 format; upgrade offline with 'geth db pebble-upgrade'
INFO [08-18|03:54:18.479] Allocated cache and file handles         database=/data/geth/chaindata cache=2.00GiB handles=536,870,908 version=v1
INFO [08-18|03:54:20.330] Opened ancient database                  database=/data/geth/chaindata/ancient/chain readonly=false
INFO [08-18|03:54:20.330] Opened Era store                         datadir=/data/geth/chaindata/ancient/chain/era
INFO [08-18|03:54:20.335] State scheme set to already existing     scheme=path
INFO [08-18|03:54:20.338] Initialising Ethereum protocol           network=1 dbversion=9
WARN [08-18|03:54:20.338] Sanitizing invalid node buffer size      provided=1.00GiB updated=256.00MiB
INFO [08-18|03:54:20.338] Load database journal from file          path=/data/geth/triedb/merkle.journal
INFO [08-18|03:54:22.579] Opened ancient database                  database=/data/geth/chaindata/ancient/state readonly=false
INFO [08-18|03:54:23.112] Initialized path database                triecache=1023.00MiB statecache=0.00B buffer=256.00MiB state-history="last 90000 blocks" journal-dir=/data/geth/triedb
INFO [08-18|03:54:23.180] 
INFO [08-18|03:54:23.180] ---------------------------------------------------------------------------------------------------------------------------------------------------------
INFO [08-18|03:54:23.180] Chain ID:  1 (mainnet)
INFO [08-18|03:54:23.180] Consensus: Beacon (proof-of-stake), merged from Ethash (proof-of-work)
INFO [08-18|03:54:23.180] Pre-Merge hard forks (block based):
INFO [08-18|03:54:23.180]  - Homestead:                   #1150000 
INFO [08-18|03:54:23.180]  - DAO Fork:                    #1920000 
INFO [08-18|03:54:23.180]  - Tangerine Whistle (EIP 150): #2463000 
INFO [08-18|03:54:23.180]  - Spurious Dragon/1 (EIP 155): #2675000 
INFO [08-18|03:54:23.180]  - Spurious Dragon/2 (EIP 158): #2675000 
INFO [08-18|03:54:23.180]  - Byzantium:                   #4370000 
INFO [08-18|03:54:23.180]  - Constantinople:              #7280000 
INFO [08-18|03:54:23.180]  - Petersburg:                  #7280000 
INFO [08-18|03:54:23.180]  - Istanbul:                    #9069000 
INFO [08-18|03:54:23.180]  - Muir Glacier:                #9200000 
INFO [08-18|03:54:23.180]  - Berlin:                      #12244000
INFO [08-18|03:54:23.180]  - London:                      #12965000
INFO [08-18|03:54:23.180]  - Arrow Glacier:               #13773000
INFO [08-18|03:54:23.180]  - Gray Glacier:                #15050000
INFO [08-18|03:54:23.180] Merge configured:
INFO [08-18|03:54:23.180]  - Total terminal difficulty:  58750000000000000000000
INFO [08-18|03:54:23.180] Post-Merge hard forks (timestamp based):
INFO [08-18|03:54:23.180]  - Shanghai:                    @1681338455
INFO [08-18|03:54:23.180]  - Cancun:                      @1710338135 blob: (target: 3, max: 6, fraction: 3338477)
INFO [08-18|03:54:23.180]  - Prague:                      @1746612311 blob: (target: 6, max: 9, fraction: 5007716)
INFO [08-18|03:54:23.180]  - Osaka:                       @1764798551
INFO [08-18|03:54:23.180]  - BPO1:                        @1765290071 blob: (target: 10, max: 15, fraction: 8346193)
INFO [08-18|03:54:23.180]  - BPO2:                        @1767747671 blob: (target: 14, max: 21, fraction: 11684671)
INFO [08-18|03:54:23.180]  - Amsterdam:                   @1769856769
INFO [08-18|03:54:23.180] All fork specifications can be found at https://ethereum.github.io/execution-specs/src/ethereum/forks/
WARN [08-18|03:54:23.185] Chain history database is pruned         tail=15,537,393 mode=all
INFO [08-18|03:54:23.185] Loaded most recent local block           number=24,410,463 hash=452533..102c4e age=6mo2w3d
INFO [08-18|03:54:23.185] Loaded most recent local finalized block number=24,410,463 hash=452533..102c4e age=6mo2w3d
INFO [08-18|03:54:23.189] Loaded last snap-sync pivot marker       number=22,882,515
INFO [08-18|03:54:23.189] Chain history is pruned                  earliest=15,537,393 hash=55b11b..7bb286
INFO [08-18|03:54:23.189] Initialized transaction indexer          range="last 2350000 blocks"
INFO [08-18|03:54:23.189] Initialized log indexer                  firstblock=22,059,891 lastblock=24,410,463 firstmap=268,288 lastmap=354,323 headindexed=true
INFO [08-18|03:54:23.211] Enabled full-sync                        head=24,410,463 hash=452533..102c4e
INFO [08-18|03:54:23.211] Gasprice oracle is ignoring threshold set threshold=2
WARN [08-18|03:54:23.211] Unclean shutdown detected                booted=2025-07-26T01:19:48+0000 age=1y4w2h
WARN [08-18|03:54:23.211] Unclean shutdown detected                booted=2025-07-28T20:21:37+0000 age=1y3w4d
WARN [08-18|03:54:23.211] Unclean shutdown detected                booted=2025-07-30T05:55:59+0000 age=1y3w2d
WARN [08-18|03:54:23.211] Unclean shutdown detected                booted=2025-07-31T15:29:23+0000 age=1y3w1d
WARN [08-18|03:54:23.211] Unclean shutdown detected                booted=2025-08-21T14:14:31+0000 age=1y1d13h
WARN [08-18|03:54:23.211] Unclean shutdown detected                booted=2025-08-28T13:44:25+0000 age=11mo3w3d
WARN [08-18|03:54:23.211] Unclean shutdown detected                booted=2025-09-03T09:38:22+0000 age=11mo2w4d
WARN [08-18|03:54:23.211] Unclean shutdown detected                booted=2025-09-08T17:51:40+0000 age=11mo1w6d
WARN [08-18|03:54:23.211] Unclean shutdown detected                booted=2025-10-08T12:21:33+0000 age=10mo1w6d
WARN [08-18|03:54:23.211] Unclean shutdown detected                booted=2025-10-13T16:29:52+0000 age=10mo1w1d
INFO [08-18|03:54:23.212] Registered sync override service
INFO [08-18|03:54:23.212] Starting peer-to-peer node               instance=Geth/v1.17.6-unstable-4d92c8e0-20260811/linux-amd64/go1.26.5
INFO [08-18|03:54:23.219] IPC endpoint opened                      url=/data/geth.ipc
INFO [08-18|03:54:23.222] Loaded JWT secret file                   path=/tmp/jwtsecret                   crc32=0x502691be
INFO [08-18|03:54:23.222] HTTP server started                      endpoint=[::]:8545 auth=false prefix= cors=* vhosts=*
INFO [08-18|03:54:23.222] WebSocket enabled                        url=ws://[::]:8551
INFO [08-18|03:54:23.222] HTTP server started                      endpoint=[::]:8551 auth=true  prefix= cors=localhost vhosts=*
INFO [08-18|03:54:23.222] Loaded local transaction journal         transactions=0 dropped=0
INFO [08-18|03:54:23.228] New local node record                    seq=1,786,196,574,821 id=019df6a866b5d3bb ip=127.0.0.1 udp=0 tcp=33075
INFO [08-18|03:54:23.228] Started P2P networking                   self="enode://81aa83d766d380b7565115cf091e6b22567819d379200a32d76b8c5436b2a33c67213fb66ae20dfc38822d2c300b31876832b66f6f4adc8b4c26f06f9beb730e@127.0.0.1:33075?discport=0"
WARN [08-18|03:54:23.392] {"level":"warn","msg":"Slow block","block":{"number":24410464,"hash":"0x2c86ea43805a4865d4409ad321344b7f604c35e242f4a493194d962b1b64a3e9","gas_used":553860,"tx_count":2},"timing":{"execution_ms":3.715266,"state_read_ms":4.220967,"state_hash_ms":2.831596,"commit_ms":1.31597,"total_ms":9.391957},"throughput":{"mgas_per_sec":58.97173507076321},"state_reads":{"accounts":6,"storage_slots":2,"code":0,"code_bytes":0},"state_writes":{"accounts":6,"accounts_deleted":0,"storage_slots":2,"storage_slots_deleted":0,"code":1,"code_bytes":122},"cache":{"account":{"hits":0,"misses":0,"hit_rate":0},"storage":{"hits":0,"misses":0,"hit_rate":0},"code":{"hits":0,"misses":0,"hit_rate":0,"hit_bytes":0,"miss_bytes":0}}}
INFO [08-18|03:54:23.392] Imported new potential chain segment     number=24,410,464 hash=2c86ea..64a3e9 blocks=1 txs=2 mgas=0.554 elapsed=9.544ms mgasps=58.030 age=6mo2w3d  triediffs=217.32MiB triedirty=157.52MiB
INFO [08-18|03:54:23.393] Chain head was updated                   number=24,410,464 hash=2c86ea..64a3e9 root=f36c99..8dfa5e elapsed="132.283µs" age=6mo2w3d
WARN [08-18|03:54:25.228] {"level":"warn","msg":"Slow block","block":{"number":24410465,"hash":"0x6538a272fc78be732f896470186e7622a4e74ede327d305ce28032302dfce7a8","gas_used":139997681,"tx_count":9},"timing":{"execution_ms":1386.850962,"state_read_ms":0.006831,"state_hash_ms":1.343741,"commit_ms":9.358846,"total_ms":1446.261404},"throughput":{"mgas_per_sec":96.79970758591854},"state_reads":{"accounts":4,"storage_slots":2,"code":0,"code_bytes":0},"state_writes":{"accounts":4,"accounts_deleted":0,"storage_slots":2,"storage_slots_deleted":0,"code":0,"code_bytes":0},"cache":{"account":{"hits":0,"misses":0,"hit_rate":0},"storage":{"hits":0,"misses":0,"hit_rate":0},"code":{"hits":0,"misses":0,"hit_rate":0,"hit_bytes":0,"miss_bytes":0}}}
INFO [08-18|03:54:25.228] Imported new potential chain segment     number=24,410,465 hash=6538a2..fce7a8 blocks=1 txs=9 mgas=139.998 elapsed=1.470s      mgasps=95.221 age=6mo2w3d  triediffs=217.25MiB triedirty=157.55MiB
INFO [08-18|03:54:25.264] Chain head was updated                   number=24,410,465 hash=6538a2..fce7a8 root=80fd75..53a5f8 elapsed="75.082µs"  age=6mo2w3d
INFO [08-18|03:54:25.384] Started log indexer
INFO [08-18|03:54:25.396] Log index tail unindexing finished       firstblock=22,059,891 lastblock=24,410,465 removedmaps=0 removedblocks=0 elapsed=11.117ms
INFO [08-18|03:54:25.437] Got interrupt, shutting down...
INFO [08-18|03:54:25.438] HTTP server stopped                      endpoint=[::]:8545
INFO [08-18|03:54:25.438] HTTP server stopped                      endpoint=[::]:8551
INFO [08-18|03:54:25.438] IPC endpoint closed                      url=/data/geth.ipc
INFO [08-18|03:54:25.438] Ethereum protocol stopped
INFO [08-18|03:54:25.438] Transaction pool stopped
INFO [08-18|03:54:25.438] Persisting dirty state                   head=24,410,465 root=80fd75..53a5f8 layers=4248
INFO [08-18|03:54:28.578] Persisted dirty state to file            path=/data/geth/triedb/merkle.journal size=380.15MiB elapsed=3.140s
INFO [08-18|03:54:28.579] Blockchain stopped
#CONTAINER:END
```

**Ancillary factual observation (not causal synthesis):** the log's own `state_reads.accounts` field on the block-465 JSON line varies enormously across cycles at different points in the file (verbatim examples seen: `accounts=4` at cycle 0, `accounts=11954` at cycle ~85, `accounts=22410` at cycle ~330, `accounts=549` a few cycles later, `accounts=985` a few cycles after that) — within groups of consecutive cycles the account-read count climbs steadily then resets to a small value at a group boundary, and `gas_used` for block 464 also steps between a small set of constant values (537030 / 535500 / 457470 / 503370 / 553860) that change at the same group boundaries. Stated as a raw observation only; no interpretation offered.

## 8. Unclean shutdown

Total count: **9,740** (10 identical lines × 974 cycles — the same 10 historical `booted=` timestamps: 2025-07-26, 07-28, 07-30, 07-31, 08-21, 08-28, 09-03, 09-08, 10-08, 10-13; only `age=` changes as it's recomputed relative to current time). These are static artifacts baked into the snapshot/container image, not events generated during the benchmark — every cycle in this run shuts down cleanly via `Got interrupt, shutting down...` (SIGINT), so no new unclean-shutdown record is ever added across all 974 restarts.

Context around one occurrence (the 10th/last of the 10, from cycle 0, showing that nothing else happens as a consequence — startup proceeds normally immediately after):

```
WARN [08-18|01:55:28.003] Unclean shutdown detected                booted=2025-08-21T14:14:31+0000 age=1y1d11h
WARN [08-18|01:55:28.003] Unclean shutdown detected                booted=2025-08-28T13:44:25+0000 age=11mo3w3d
WARN [08-18|01:55:28.003] Unclean shutdown detected                booted=2025-09-03T09:38:22+0000 age=11mo2w4d
WARN [08-18|01:55:28.003] Unclean shutdown detected                booted=2025-09-08T17:51:40+0000 age=11mo1w6d
WARN [08-18|01:55:28.003] Unclean shutdown detected                booted=2025-10-08T12:21:33+0000 age=10mo1w6d
WARN [08-18|01:55:28.003] Unclean shutdown detected                booted=2025-10-13T16:29:52+0000 age=10mo1w1d
INFO [08-18|01:55:28.003] Registered sync override service
INFO [08-18|01:55:28.003] Starting peer-to-peer node               instance=Geth/v1.17.6-unstable-4d92c8e0-20260811/linux-amd64/go1.26.5
INFO [08-18|01:55:28.007] IPC endpoint opened                      url=/data/geth.ipc
INFO [08-18|01:55:28.007] Loaded JWT secret file                   path=/tmp/jwtsecret                   crc32=0x502691be
INFO [08-18|01:55:28.007] HTTP server started                      endpoint=[::]:8545 auth=false prefix= cors=* vhosts=*
```
No repair, resync, or snapshot-regeneration ever follows any `Unclean shutdown detected` line in any sampled cycle — the consequence is purely cosmetic logging.