# Task 2 — benchmarkoor source-reading verdicts (read at `1e0b9d4`)

Read on 2026-08-27 against the upstream tree, not the host's working copy.

## V6 — does the runner skip the per-test pre-run replay once the baseline carries it?

**Yes.** `pkg/runner/strategy_container.go`. `promoteSchelkAfterPreRuns` returns
`(newIP, baked, err)`; the caller sets `preRunsBaked = promoted`, and the per-test
branch became `if !useZFSSnapshot && !preRunsBaked`.

Two paths set `baked = true`:
1. this invocation promoted, or
2. `verifyPreRunBundleHead` reports the head is already at the bundle's end, which
   logs `"Pre-run bundle already applied to this datadir; nothing to promote"` and
   returns `("", true, nil)` — no replay, no second promote.

Commit `93e70fc` (#298) exists because a jochemnet run was "about to replay the
bundle 1463 times… ~65 hours of work reproducing state the datadir already had".
Its first bundle replay took **2m44s** — useful sizing for the smoke.

**Decision unblocked:** Tasks 10 and 11 share ONE unmodified config differing only
by `tests.filter`. No `pre_runs` removal, no `promote_post_pre_runs` flip. The
Phase 2/3 split described in the plan is not needed.

## V3 — does promote fire after a FAILED pre-run?

**No.** `RunPreRunSteps` errors return before the promote call
(`"running pre-run steps before schelk promote: %w"`). Separately, `n == 0` warns
`"promote_post_pre_runs is set but the suite has no pre-run steps; refusing to
promote (the baseline would be the raw snapshot)"` and returns `baked=false`.

**Decision unblocked:** a broken H cannot be promoted. The smoke's
assert-before-accept ordering is defence in depth, not the only guard.

## V1 — is pre-run execution gated?

**Yes, by config.** `useSchelkPromote := strategy == config.RollbackStrategyContainerRecreate
&& params.DataDirCfg.ShouldPromotePostPreRuns()`. Per-test execution is additionally
gated by `!useZFSSnapshot && !preRunsBaked`, and by the suite actually having
pre-run steps.

## V2 — does promote fire with ZERO `pre_runs` blocks?

**No** — see V3's `n == 0` branch. It still boots the client and attempts the steps
before discovering there are none, so carrying the flag on a pre-run-less suite is
wasteful rather than dangerous.

**Decision unblocked:** the state-actor config omits `schelk_options` entirely.

## V5 — does `live_reporting.enabled: false` fully disable it?

**Yes.** `LiveReportingConfig.Enabled bool` is checked at
`pkg/runner/runner.go:605` before the reporter is constructed. The `/etc/hosts`
null-route stays as belt-and-braces.

## V4 — `extra_mounts`: NOT UPSTREAM

**`ExtraMounts` does not exist anywhere upstream** — absent at `1e0b9d4`, absent at
`9b8a5d8`, absent on `origin/master`. No equivalent key (`mounts`, `volumes`,
`binds`, `extra_volumes`) exists either.

It is an **uncommitted local patch** in `~/benchmarkoor` on the host: `M go.mod`,
`M pkg/config/config.go`, `M pkg/runner/lifecycle.go`, `M pkg/runner/runner.go`,
27 inserted lines. The lifecycle hunk appends `docker.Mount{Type: "bind", ...}`
entries from `instance.ExtraMounts`, commented *"Add user-defined extra mounts
(e.g. geth flat-file + freezer on HDD)"*.

My earlier verification read the host's dirty working tree and mistook it for
upstream.

**Consequence:** Option 2 (hoisting `ancient/chain` out of the schelk volume and
bind-mounting it read-only) is impossible with the clean `1e0b9d4` binary. An
unrecognised YAML key risks being ignored rather than rejected, which would boot
geth against an EMPTY `ancient/chain` — wrong numbers, not a loud failure.

Note this also means the ORIGINAL runs necessarily had the freezer INSIDE the
schelk volume, since they ran `1e0b9d4`. Option 1 is the faithful configuration.

**Decision blocked:** awaiting the operator's choice between Option 1 (upstream
binary, 1.25 T volume), porting the patch onto `1e0b9d4`, or Option 1 now with a
later revisit.
