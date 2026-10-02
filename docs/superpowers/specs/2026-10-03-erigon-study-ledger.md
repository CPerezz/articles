# Erigon state-DB study: execution ledger

Append-only. The box (`ubuntu@157.180.2.180`, "gas-repricing") is the source of truth; scripts and
configs under `tools/erigon-study/` are copies of what runs from `/bench/erigon/tools` and
`/bench/cfg`. Plan: `docs/superpowers/plans/2026-10-03-erigon-state-db-study.md`.

## Round 0 - host preparation (2026-10-02 22:20 UTC onward)

**Isolation.** Worktree `articles-wt-erigon`, branch `erigon-state-db-study` from `origin/main`
(`bc34cde`). Another session is active in the other articles worktrees; nothing here writes there.
On the box: schelk instances `er-joc` (`/dev/ram0`, `/schelk-er-joc`, 1900G) and `er-sa`
(`/dev/ram1`, `/schelk-er-sa`, 800G), dirs `/bench/erigon/*`, configs `/bench/cfg/er-*.yaml`.

**What existed.** 7.0 TB md2 NVMe at `/`, 1.1 TB free. Nethermind data: four schelk images
(nm-joc 1.6 TB x2, nm-sa 640 GB x2), `/bench/nm-store/v1` (523 GB, superseded) and `v2`
(472 GB). No suite running, no dm devices, last use 2026-09-25 (nm-13810 runs).

**Removed (Anon authorised wiping Nethermind data as needed).** `/bench/nm-store/v1`; the four
`nm-*.img` after detaching loop9/10/4/8. Their schelk state files are kept in
`/var/lib/schelk/retired/` (they name loops that no longer exist); notice in
`/bench/schelk-vols/NM-IMAGES-REMOVED-2026-10-03.txt`. Free after: 5.9 TB. `v2` stays until the
reference hashes below are recorded in this ledger (now done) and the fill is copied.

**Snapshot.** `https://snapshots.ethpandaops.io/jochemnet/erigon/24402727/snapshot.tar.zst`,
1,038,829,525,851 B (Last-Modified 2026-04-28). Head of the tarball: `_snapshot_eth_getBlockByNumber.json`
reports block 24,350,000 (0x1738d30), the mainnet fork base, and `chaindata/mdbx.dat` is
572,455,387,136 B. Download by `eg-fetch-joc.sh` (wget -c, Nethermind's retry policy, then size
and `zstd -t`) started 22:30; ~80-100 MB/s alone.

**Images (rootful podman).**
- `docker.io/ethpandaops/erigon:glamsterdam-devnet-7`: id `2e208c1e…`, digest
  `sha256:4023a007fe974301277fdcae8446e4c1c491dfefc92c762a81b70aaadb32d535`, built 2026-08-26,
  `erigon version 3.7.0-dev-5f62f4ed`, runs as uid 1000. Has `--override.amsterdam`,
  `--exec.no-merge`, `--exec.no-background-maintenance`, `--experimental.parallel-commitment`.
- `ghcr.io/ethereum/state-actor-erigon:main-005a19c`: id `f7eb453d…`, digest
  `sha256:ae9ca8c94d37d1a83ec48fce8c68f507abfc855c0270044a09269d1626d6e6ba`, revision
  `005a19c67534b7383a352acd65b9b06b2f81d58e` (the Nethermind v2 generator).
- benchmarkoor `dev` (no commit stamp; supports `method: schelk`), schelk 0.1.0 (93522c7).

**Reference values for the state-actor arm** (Nethermind v2 manifest and the fill's pre_run file):
genesis `0x0cb035288eb4e257f34f3d570ed4f43f9d2fc45c09f19db6c0392f60f4a68623`, state root
`0x48d611bb839188317e983453705b31e1420b2c4416675f98d776ad8e130d51b8`, chain id 1337, spec sha256
`74dea7d1de9d869d87ddcabf52912cada6d48cb1eb295819d322aef51c3f7194` (= `~/state-actor-spec-baseline.yaml`,
checked). The Erigon store must reproduce both hashes for the fill to apply.

**jochemnet genesis.** The canonical gist saved as `/bench/erigon/cfg/jochemnet-genesis.json`,
sha256 `998008d3…ab42e`: chainId 1, amsterdamTime 1769856767, osakaTime 1764798551. The
canonical override is `--override.amsterdam=1769856769`.

**Deviation from the plan.** The state-actor arm has no pre-run (as on Nethermind: the spec
pre-deploys the fixture accounts; `nm-sa-fin1` ran with `pre_run_steps=0`), so its suite A is
just the two smoke tests, without a promote.

**Contention observed.** `schelk init-new` clones the whole virgin image to scratch (1.9 TB at
0.4-1.3 GB/s); while it ran, the single-stream download fell from ~90 MB/s to ~8-18 MB/s although
a parallel range read still got 69 MB/s. Left to finish; the clone is ~1-1.5 h.
