# Implementation Plan — Closing the Gaps vs DLSS5-Feeder & ShortFuse DLSS Tool

Companion to `ANALYSIS-vs-DLSS5-Feeder-and-ShortFuse-DLSS-Tool.md` (read that first for the per-gap evidence).
Every gap below gets: steps, target files, dependencies, risks, effort, acceptance criteria. Effort is in focused
dev-days (d). Ordered by dependency and value; Phase A is the Preset-L work the user asked about specifically.

---

## Phase A — Preset L / preset switching (user's headline ask)

### A1. Per-quality-mode DLSS SR preset override (Preset E/F/J/K/L/M) — gap #3, S2
**Goal:** let the user pick, per quality mode (DLAA/UltraQuality/Quality/Balanced/Performance/UltraPerformance), which
SR model preset runs, including DLSS 4.5 Preset L (12) and M (13), same way the Feeder/ShortFuse drive it.

**Steps**
1. `native/include/nvsdk_ngx_defs.h` — verify enums `NVSDK_NGX_DLSS_Hint_Render_Preset_L=12`, `_M=13` (already
   present at lines 82-85; extend only if adding names for DRS constants).
2. `native/dlss5-feed-host64.cpp`:
   - Extend the SR create probe (`SafeCreateDLSS`, host:582-585) into a real optional SR feature: read env/config
     `NS_SR_PRESET_<MODE>` (int 0=default…13) or one global `NS_SR_PRESET`; if set (≠0), create the SR feature with
     `h.params->Set("DLSS.Hint.Render.Preset.<Mode>", value)` before `NGX_D3D12_CREATE_DLSS_EXT`.
   - Version-gate: probe availability first via the capability-parameter path (Feeder pattern,
     `dlss5-feed.cpp:3880-3884` — query optimal settings on the *CAPABILITY* parameter object, not an
     AllocateParameters one) and fall back to preset K or default with a log line when the DLL predates L/M
     (310.5.0).
   - Optional DRS route (highest priority per RE @0x18006DD10): set `NGX_OVERRIDE_RENDER_PRESET_SELECTION` on the
     create params.
3. `main.py` + `overlay_ui.py`: add a "DLSS SR Preset" panel (per-mode combo: Default/E/F/J/K/L/M) writing config
   keys; pass to host via the existing env-var channel (`NS_*` envs read by host at startup — pattern:
   `NS_PW_*`, host:2971+).
4. Feature re-create on change: preset is **create-time** (RE-confirmed; ShortFuse re-creates Reserved18 in
   `sub_180065A60`). Add a host control message or restart-the-worker path (existing restart machinery,
   main.py:restart_worker) when presets change.

**Target files:** `native/dlss5-feed-host64.cpp`, `native/include/nvsdk_ngx_defs.h`, `main.py`, `overlay_ui.py`,
`config.json` (schema), `TECHNICAL.md` (docs), `tests/test_protocol_sizes.py` or new `tests/test_sr_presets.py`.
**Dependencies:** NGX SDK headers in repo (present); `nvngx_dlss.dll` ≥310.5 installed by the user (log a clear
message when absent — string pattern from ShortFuse: "Unavailable (nvngx_dlss.dll missing)" @0x180217557).
**Risks:** wrong parameter-object type → silent DLAA fallback (Feeder documented this trap, dlss5-feed.cpp:3880-3884);
older DLLs reject L/M (validation in `FillCreationParams` @0x18004ECF0 → `sub_1800B5D60` availability check); creating
a second NGX feature on the desktop capture path may cost VRAM.
**Effort:** 3-4 d (host 1.5 d, UI 1 d, gating/tests/docs 1 d).
**Acceptance:** (a) host log shows `DLSS.Hint.Render.Preset.Quality=12` → create succeeds on 310.9.1; (b) with a
pre-310.5 DLL the host logs fallback and keeps running; (c) `tests/test_sr_presets.py` covers env parsing, enum
validation, per-mode table, config round-trip; (d) existing `tests/run_tests.py` green.

### A2. NR preset selector (Default/#1/#2/#3) — gap #4, S1
**Steps**
1. Host: on feature create (`g_nr_create`, host:962), read `NS_NR_PRESET` (0=Default, 1-3) and
   `h.params->Set("DLSSNR.Hint.Render.Preset", v)` — exactly the ShortFuse create-path key (RE @0x180066375).
2. Re-create feature on change (retained-feature pattern optional; simplest: worker restart, already robust).
3. UI combo in `overlay_ui.py` + config key `nr_preset`; document that NR DLL 310.8.SF-v2 only ships network #1
   (RE: weight registry has one entry, `sub_180023A40` walker) so higher presets need a newer `nvngx_dlssnr.dll`.
**Target files:** host cpp, `overlay_ui.py`, `main.py`, `TECHNICAL.md`, `tests/test_nr_small.py` sibling:
`tests/test_nr_preset.py`.
**Dependencies:** none new. **Risks:** runtime ignoring preset → verify via log; UX confusion (document).
**Effort:** 1-1.5 d. **Acceptance:** env→param mapping unit-tested; log line shows preset; default unchanged.

### A3. Live preset switch without full app restart (parity with ShortFuse's retained-feature cache)
**Steps:** host-side `RecreateNRFeature()` + IPC opcode (extend `native/src/feed_ipc.h` — there is room: protocol
structs are fixed-size, so add a new `FeedRecreate` message with version bump, mirroring `test_protocol_sizes.py`
expectations); on `FeedRecreate`, destroy feature handle, re-create with new params (pattern from `sub_180065A60`),
fence, resume. Fallback: `restart_worker` path already exists — ship A1/A2 with restart first, A3 as polish.
**Effort:** 2 d standalone. **Acceptance:** switch preset from UI mid-run; no worker restart visible to user; no
dead frames (fence wait); `test_protocol_sizes.py` updated + green.

---

## Phase B — HDR (gap #2, #10, #14)

### B1. HDR create flag + format detection
**Steps**
1. Host: pass `hdr` tri-state via env `NS_HDR` (-1 auto/0 SDR/1 HDR); on create set
   `NVSDK_NGX_DLSS_Feature_Flags_IsHDR` when active (Feeder host:2982 pattern).
2. Python side: detect desktop HDR (Windows `DisplayConfigGetDeviceInfo` / `GetDisplayConfigBufferQueries`
   via ctypes — the desktop analog of the Feeder's ReShade color-space query; WGC frames carry DXGI_FORMAT_R16G16B16A16_FLOAT
   when HDR is on).
3. Capture path: accept R16G16B16A16_FLOAT frames (WGC gives FP16 scRGB on HDR desktops) and convert to the
   linear-FP16 texture the NR consumer expects (see B2).
**Target files:** host cpp (video texture creation host:1918-1929 — add FP16 format branch), `worker.py`/`channels.py`
(capture formats), `guides.py`, `main.py` (detection), `TECHNICAL.md`, new `tests/test_hdr_flags.py`.
**Effort:** 3 d. **Risks:** scRGB vs PQ semantics (desktop is scRGB-linear, NOT PQ — the Feeder's PQ decode is a
game-swapchain concern; document that difference explicitly); perf of FP16 path.
**Acceptance:** on an HDR desktop with `NS_HDR=1`, create log shows IsHDR set; frame pipeline round-trips FP16
without banding (pixel-compare test in `tests/test_hdr_flags.py`); SDR behavior bit-identical (regression suite green).

### B2. Paper-white / adaptive-exposure for HDR (extend gap #9)
**Steps:** generalize the existing `NS_PW_*` adaptive exposure (host:2971+) with a `NS_HDR_PAPER_WHITE` nits key
(Feeder default 203, BT.2408); map 1.0 linear = paper white, highlights above; reuse existing exposure solver.
**Effort:** 1 d. **Acceptance:** `tests/test_adaptive_exposure.py` extended with HDR-range case; log shows nits.

---

## Phase C — Multipass cascade (gap #1, #8 partial)

### C1. N-pass NR with per-pass history
**Goal:** run 2-3 NR evaluates per frame (Feeder: "each stage keeps its OWN history, so a two-pass cascade roughly
doubles the effective history length").
**Steps**
1. Host: generalize `struct` video session to N features: create `NRFeature slots[3]` (own history = own feature
   handle + own Reset bookkeeping), evaluate sequentially per frame feeding pass k's Output into pass k+1's Color
   (the same way Deep Fried Chicken runs up to 30 passes; Feeder gates 2/3 via `two_pass`/`three_pass`).
2. `NS_NR_PASSES` env (1-3), `nr_passes` config key, UI stepper with the Feeder's own warning text about history
   length (README:441-442).
3. Per-pass knob overrides: `NS_NR_PASS2_INTENSITY` etc. (pattern: Feeder "per-pass Reno-style controls").
4. Fence once per frame still (evaluate is async; single fence after last pass).
**Target files:** host cpp (video struct + eval loop ~3700s), `main.py`, `overlay_ui.py`, `config.json`,
`TECHNICAL.md`, `tests/test_nr_passes.py` (protocol + param matrix), extend `tests/test_protocol_sizes.py` if IPC
changes (passes can ride the env channel — prefer that: zero protocol change).
**Dependencies:** none. **Risks:** VRAM ×N for histories; latency ×N (70-100 ms/frame today — document expected
fps); Reset semantics across passes (reset must cascade pass1→passN same frame).
**Effort:** 2-3 d. **Acceptance:** `nr_passes=2` produces stable output (no history bleed — verify via existing
residual tests extended); log shows `pass 1/2 evaluated`; single-pass default unchanged; suite green.

### C2. Supersampling work_scale >1.0 (finish gap #8)
**Steps:** lift the 0.1-1.0 clamp (TECHNICAL.md:127) to 0.1-2.0 behind the existing `nr_small` path; the Feeder
calls this "supersample the neural pass". Verify memory (w×2 buffers) and add UI hint.
**Effort:** 0.5 d. **Acceptance:** `work_scale=1.5` runs, `test_nr_small.py` extended, no regression at ≤1.0.

---

## Phase D — Remaining `DLSSNR.*` knob parity (S3, S4)

### D1. Missing knobs
Add host sets (host:3696-3715 pattern) + UI + config for: `DLSSNR.GlobalToneStrength` (exists in Streamline ABI —
ShortFuse string @0x180215e6b notes its effect isn't visible in the recovered NGX path; ship off by default with
that caveat documented), `DLSSNR.JitterOffsetX/Y`, `DLSSNR.DepthInverted`, `DLSSNR.Upscaling`,
`DLSSNR.Indicator.Invert.X/Y`, and Subrect params (`DLSS.Render.Subrect.Dimensions.*`,
`DLSS.Input.MV.Subrect.Base.*`, `DLSS.Input.Depth.Subrect.Base.*`, `DLSS.Output.Subrect.Base.*` — strings
0x18022eaef-0x180232d25).
**Effort:** 1-2 d (mostly mechanical; Subrects matter once crop/region capture exists). **Acceptance:** knob matrix
unit test `tests/test_nr_knobs.py` asserting exact param names (guard against typos — the DLL silently ignores
unknown keys); defaults preserve today's behavior exactly.

### D2. UICorrection tri-state (S4)
**Steps:** `NS_UI_CORRECTION` (-1 auto/0 off/1 on); auto = ON when the evaluated source is NeuralScreen's own
overlay (always the case here — so auto≡on today; document that with the ShortFuse's own wording @0x180215969),
explicit off/for users who feed HUD-less sources.
**Effort:** 0.5 d. **Acceptance:** `tests/test_ui_buttons.py`-style UI test + param mapping test.

---

## Phase E — Interop & transports (larger, clearly-scoped follow-ups)

### E1. OptiScaler / upscaler-cascade path (gap #5)
Out-of-process NeuralScreen cannot inject OptiScaler into arbitrary games — that's a different product shape
(Feeder is an in-game add-on). Plan instead: **document** the boundary + optional "feed contract" export
(gap #13) so third-party consumers could attach to NeuralScreen's host output (publish the shm/Spout2 stream with
a marker + versioned schema; ReShade add-ons and OBS already consume Spout2). Steps: version the shm layout
(`channels.py`), add marker+schema doc, optional `feed_contract.json`.
**Effort:** 2 d (doc + schema versioning). **Acceptance:** `tests/test_out_shm.py` extended with schema version
assert; doc merged.

### E2. Vulkan/OpenGL/D3D11 in-game transports, 32-bit support, DFC interop (gaps #6,7,11,12)
These change NeuralScreen's product identity (desktop app → in-game injector). Recommendation: keep as a tracked
**non-goal** with a short RATIONALE section in TECHNICAL.md explaining the architecture difference (out-of-process
desktop capture vs in-game add-on), so the gap analysis stays honest without forking the project's purpose. If
pursued later: port `src/feed_pq12.h`-style private-device compute from the Feeder (Apache/MIT per its LICENSE —
verify before copying).
**Effort:** n/a (decision documented; revisit on user request).

---

## Execution order & totals

| Phase | Items | Effort | Unlocks |
|---|---|---|---|
| A | A1, A2, A3 | 6-7.5 d | Preset L + preset switching (headline ask) |
| B | B1, B2 | 4 d | HDR |
| C | C1, C2 | 2.5-3.5 d | Multipass + supersampling |
| D | D1, D2 | 1.5-2.5 d | Knob parity |
| E | E1 (+E2 rationale) | 2 d | Interop doc |

Every phase ends with: `python tests/run_tests.py` green, TECHNICAL.md + README touched, host log evidence pasted
into the PR description. No TODO placeholders; anything not implemented ships as an explicit documented decision
(E2) rather than a silent gap.
