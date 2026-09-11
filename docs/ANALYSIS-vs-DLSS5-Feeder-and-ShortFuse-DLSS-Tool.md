# Gap Analysis — DLSS5-NeuralScreen vs DLSS5-Feeder & ShortFuse DLSS Tool

Date: 2026-09-11
Analyst: automated RE pass (IDA + source cross-read)
Scope: what **this repo** (DLSS5-NeuralScreen, `perseval-BLR/DLSS5-NeuralScreen` @ `85a0b72`) is missing relative to
(1) `jlrouzies-fr/DLSS5-Feeder` (v4.7-era add-on + helper hosts) and
(2) ShortFuse's DLSS Tool (`renodx-dlss.addon64`), with per-feature evidence.

---

## 0. What the three projects ARE

| | DLSS5-NeuralScreen (this repo) | DLSS5-Feeder | ShortFuse DLSS Tool |
|---|---|---|---|
| Form | Python desktop app + native C++ out-of-process host (`native/dlss5-feed-host64.cpp`) driving DLSS 5 NR (feature `NVSDK_NGX_Feature_Reserved18`) on a captured desktop stream | ReShade add-on (`src/dlss5-feed.cpp`, `src/dlss5-feed32.cpp`) + out-of-process 64-bit D3D11/D3D12 helper host (`host/dlss5-feed-host64.cpp`) that publishes a "feeder" contract any neural consumer (RenoDX DLSS 5, Deep Fried Chicken, OptiScaler) can eat | RenoDX-based ReShade add-on (`renodx-dlss.addon64`, internal namespace `renodx::addons::dlss::neural_rendering`, PDB `renodx-dlss.pdb`) that drives `nvngx_dlssnr.dll` NR in-game with a settings UI |
| Target | Whole-desktop NR for video/windows (screen-level post) | In-game neural rendering for any D3D11/12/Vulkan/OpenGL title | In-game DLSS + DLSS 5 NR (the "RenoDX DLSS" deployment RHI ships) |

RE artifacts used (all local, hashed for provenance — see §5):
- `renodx-dlss.addon64` — SHA256 `C575F3F7C8CA6F4EF3BAA2194EA8E37E06E8EA32EE0701ECFB99035291304B00`, 2,642,432 bytes.
- `nvngx_dlssnr-310.8.SF-v2.dll` — SHA256 `6EB209E764F39872625DEBD6ABAF45E2BB6322F6F270F781F70C059AE30B3927`, 165,830,144 bytes.
- `nvngx_dlss-310.9.1.dll` (SR) — SHA256 `3975567B8943C53ACCE397F2B72380092F84F162D00B0D2C7D08A1025C563983`, 58,956,912 bytes.

---

## 1. Feature matrix — DLSS5-Feeder vs this repo

Labels: ✅ present · 🟡 partial (works but narrower) · ❌ missing.

| # | Feature | Feeder evidence | NeuralScreen evidence | Label |
|---|---|---|---|---|
| 1 | **Multipass neural rendering** (2/3-pass cascade via Alex's Toolkit: `two_pass`/`three_pass` cfg, each pass keeps its own history, "cascade roughly doubles the effective history length") | `src/dlss5-feed.cpp:441-442,457,517-532,556` (`g_toolkit_passes`, `ToolkitCfgInt(text,"two_pass")`, v4.6/v4.7 handling); README "Deep Fried Chicken 1.4.8-alpha ✅ 300/300" | `native/dlss5-feed-host64.cpp` runs exactly ONE `NVSDK_NGX_D3D12_EvaluateFeature` per frame on one NR feature handle (`h.feature`); no pass-count concept anywhere in host or Python (rg "pass_" → 0 hits) | ❌ |
| 2 | **HDR10 / PQ bridge** (`hdr_bridge`: PQ BT.2020 decode to linear FP16 in, re-encode out; `hdr_paper_white` nits; auto-detects via ReShade color-space API, not DXGI format guessing; covers D3D11/12/Vulkan/OpenGL) | README:1076-1077 (`hdr_bridge`, `hdr_paper_white` keys, `src/feed_pq12.h` D3D12 compute pass); `src/dlss5-feed.cpp:806-824,935,990-996`; `host/dlss5-feed-host64.cpp:302` | Host captures/creates video textures in `DXGI_FORMAT_R8G8B8A8_UNORM` only (`native/dlss5-feed-host64.cpp:1918-1929`); no `IsHDR` flag, no PQ decode, no color-space detection; Python capture is SDR RGB (WGC/DDA) | ❌ |
| 3 | **Per-quality-mode SR preset override** (per DLAA/UQ/Q/B/P/UP select preset E/F/J/K/L/M via create-time `DLSS.Hint.Render.Preset.*` hints) | `src/dlss5-feed.cpp:3879-3952` (`kQualityPresetNames[]` + `NVSDK_NGX_Parameter_DLSS_Hint_Render_Preset_*` table, optimal-settings callback on CAPABILITY parameter object, `SRQualityPresetForRatio`) | No `DLSS.Hint.Render.Preset.*` / `Render_Preset` references anywhere in `native/` or Python (rg → 0 hits); the SR DLSS EXT feature (`NGX_D3D12_CREATE_DLSS_EXT` at host:585) is only used for the 1×1 warm-up probe | ❌ |
| 4 | **NR preset selector** (`NRPreset` combo: Default / #1 / #2 / #3 → `DLSSNR.Hint.Render.Preset` at feature create) | `src/dlss5-feed32.cpp:2553,2568` (`kNRPresetItems`, NR_COMBO UI); addon RE: string `DLSSNR.Hint.Render.Preset` @0x180214e39, set in NR create path @0x180066375 (decompile `sub_180065A60`) | No NR preset knob: host sets `DLSSNR.*` style/intensity knobs (`native/dlss5-feed-host64.cpp:3696-3715`) but never `DLSSNR.Hint.Render.Preset`; config.json has no preset key | ❌ |
| 5 | **OptiScaler cascade** (upscaler swap: XeSS/FSR2+ → DLSS via OptiScaler for non-NVIDIA GPU; Feeder publishes the feed contract OptiScaler's DLSS-NR side consumes) | `src/feed_opti.h` whole file (line 31: "OptiScaler ... can only forward that query to the driver core"); README OptiScaler.log interplay; `host/dlss5-feed-host64.cpp:742` (second consumer talks to OptiScaler) | None: no OptiScaler integration, no upscaler swap, no config keys (rg optiscaler → 0 hits) | ❌ |
| 6 | **DX11 host variant** (in-process 32-bit overlay + 64-bit D3D11 helper host; bridges into D3D11 games) | `src/dlss5-feed32.cpp` (32-bit in-game overlay, "Current (host64\OptiScaler.ini): Enabled=%s Preset=%s ..." at 5619); `PLAN-VULKAN32.md`, `PLAN-32BIT.md`, README:510 "A 64-bit D3D11 host, in-process, 3840x2160 HDR10" | Single host: out-of-process 64-bit D3D12 only (`native/dlss5-feed-host64.cpp`; build.bat produces one binary); no D3D11 path, no in-game injection | ❌ |
| 7 | **Vulkan / OpenGL transports** (private-device compute for PQ bridge; contract publishing on VK/GL presents) | `src/feed_pq12.h`; `PLAN-VULKAN.md`, `PLAN-VULKAN32.md`, `PLAN-OPENGL.md`, `PLAN-PROXY-SWAPCHAIN.md`; README:1076 (all four 64-bit transports) | None — desktop capture only (WGC/DDA/dxcam); no game-API transports | ❌ |
| 8 | **Neural Work Scale / supersample above 100%** ("Values above 100% supersample the neural pass", per-pass Reno-style controls, `work_upscale` FSR1 chain) | README "Neural Work Scale slider. Values above 100% supersample"; `work_upscale` cfg; per-pass neural controls | Partial: `work_scale` 0.1–1.0 clamp (TECHNICAL.md:127), i.e. downscale only; no supersample >1.0, no per-pass controls | 🟡 |
| 9 | **Adaptive exposure / paper-white** (NRGlobalTone: reversible SDR/sRGB ↔ linear HDR ↔ PQ codec driven by contract) | README:130 (v4.7 `NRGlobalTone`); `NRGlobalTone` slider keys | Present in different form: `NS_PW_*` adaptive-exposure envs (host:2971+ comment "Adaptive exposure (PaperWhite principle, Ghady983/RenoDX-DLSS-5-Artifact-Fix)"; main.py) — SDR-scoped, not HDR | 🟡 |
| 10 | **Color-space detection by API** (asks ReShade for actual color space; R10G10B10A2 cannot tell 10-bit SDR from HDR10) | `src/dlss5-feed.cpp:806-824` (`reshade::api::color_space` mapping: scrgb → "linear BT.709", hdr10_pq → "PQ BT.2020") | None — no color-space API use (desktop capture path has no swapchain introspection) | ❌ |
| 11 | **32-bit game support** (32-bit overlay + 32-bit host path) | `src/dlss5-feed32.cpp` whole file; `build-addon32.bat`; `PLAN-32BIT.md` | Out of scope by design (64-bit host only) — but no doc states the boundary | ❌/design |
| 12 | **Deep Fried Chicken consumer support** (DFC 1.4.8-alpha verified 300/300; DFC state machine detection, "NOT consuming" warnings) | `src/dlss5-feed.cpp:669,684-685` (`Deep Fried Chicken %s: %s -- NOT consuming`); README:25,97-105,256,425-449 | None — NeuralScreen is its own consumer; no DFC interop | ❌ |
| 13 | **Cross-consumer contract** (a documented feed contract any neural consumer can attach to: marker `feeder_marker=1`, structural-layout scan, IAT hook toolkit) | `host/dlss5-feed-host64.cpp:569-573` (toolkit attaches by recognizing structural layout inside the DLSS 5 add-on, only matches v4.55-era builds); `src/dlss5-feed.cpp:669` (marker) | None — NeuralScreen's IPC (`native/src/feed_ipc.h` structs FeedHelloAck/FeedBuild/FeedBuildAck/FeedFrameMsg) is internal to its own Python↔host pair | ❌ |
| 14 | **HDR create flag** (`hdr` key: -1 auto/0 SDR/1 HDR → `NVSDK_NGX_DLSS_Feature_Flags_IsHDR`) | `host/dlss5-feed-host64.cpp:2982` (`if (b.hdr) flags_active \|= NVSDK_NGX_DLSS_Feature_Flags_IsHDR`) | Not set anywhere | ❌ |
| 15 | **Auto-restart/watchdog on HDR/res change** ("the add-on faulted once during a resolution/HDR change, and every following...") | `host/dlss5-feed-host64.cpp:2247` | Present: worker restart/backoff (main.py:555+; MAX_CONSECUTIVE_RESTARTS, auto-revive) — equivalent robustness exists | ✅ |
| 16 | **Consumer version detection & compat gating** (`g_renodx_v46`, `g_renodx_v47` gating multipass; v4.55 signature scan warning) | `src/dlss5-feed.cpp:541-571`; `host/dlss5-feed-host64.cpp:569-573` | Partial: host knows about "v45+ adopts missed creates" (`native/dlss5-feed-host64.cpp:4648,4737` — `g_renodx_lazy`, STANDBY latch) — aware of renodx behaviors but no consumer version matrix | 🟡 |

## 2. Feature matrix — ShortFuse DLSS Tool (`renodx-dlss.addon64`) vs this repo

RE evidence: strings + decompiled NR create path `sub_180065A60` (imagebase 0x180000000); settings surface from string table 0x180213c00–0x180217557.

| # | Feature | ShortFuse evidence (RE) | NeuralScreen evidence | Label |
|---|---|---|---|---|
| S1 | **In-game settings UI with live preset switching** (NR feature re-created on preset change — "reused retained feature: handle={} size={}x{} performance={} preset={}" log; retained-feature cache with exhaust warning) | `sub_180065A60` decompile: retained-feature cache walk (0x180065a86-0x180066375), `DLSSNR.Hint.Render.Preset` set at 0x180066375 before `CreateFeature(Reserved18)` (0x180066416), success log 0x180066685 strings "CreateFeature(Reserved18) succeeded/failed" | Overlay UI changes style/intensity knobs only — a preset change would need feature re-create; host creates the feature once at startup (host:962 `g_nr_create(h.list, NVSDK_NGX_Feature_Reserved18, ...)`) and never re-creates on config change | ❌ |
| S2 | **Per-quality SR preset hints** (six create-time keys `DLSS.Hint.Render.Preset.DLAA/UltraQuality/Quality/Balanced/Performance/UltraPerformance`) | Strings 0x180213d25–0x180213dcc | None | ❌ |
| S3 | **Full `DLSSNR.*` knob surface** (Color/Output/MVec/Depth/UI/UIAlpha, JitterOffsetX/Y, MVecScaleX/Y, DepthInverted, Enabled, Reset, Intensity, LocalToneStrength, LocalStructureStrength, GlobalToneStrength, UseAutoMask, SkinStructureStrength, Style, UICorrection, ScalingRatio, Scale, Upscaling, Subrect params) | Strings 0x1802149bc–0x180214e96, 0x18022eaef–0x180232d25 | Partial — host already sets: Color/Output/MVec/Depth/UI/UIAlpha? no — sets MVec, Depth (host:3705-3713: MVec/MVecSubrect*/MVecScale*, Enabled, Reset), plus LocalTone/LocalStructure/SkinStructure/AutoMask/Style/UICorrection/Intensity (host:3696-3715) and ScalingRatio (host:955). Missing: GlobalToneStrength, JitterOffsetX/Y, DepthInverted, Upscaling, Subrect base (DLSS.Render.Subrect / Input.*.Subrect), Indicator.Invert axes | 🟡 |
| S4 | **UICorrection auto/off/on tri-state** ("Auto enables DLSSNR.UICorrection when the actual evaluated source is the swapchain and disables it for native DLSS SR/AA/RR and HUD-less sources. Off and On override the automatic source-based choice.") | String 0x180215969 | Host sets `DLSSNR.UICorrection` scalar (host:3700) — no tri-state/auto logic (NeuralScreen's source is always its own overlay, arguably always "swapchain-like") | 🟡 |
| S5 | **Per-knob range/validation docs in-UI** ("The supplied binaries default to 1 and consume this value without range validation...") | Strings 0x180215bbe-0x180215f8e | TECHNICAL.md documents profiles; no per-knob NGX validation semantics | 🟡 |
| S6 | **NVNGX runtime attach fallbacks** ("%s: Unavailable (nvngx_dlssnr.dll missing)", "RenoDX DLSS could not attach the direct nvngx_dlssnr.dll runtime.") | Strings 0x180217557, 0x18021777c | Host logs and restarts on failure (main.py worker restart) but has no multi-runtime attach chain | 🟡 |

## 3. Summary of what NeuralScreen is missing (the actual ask)

**vs DLSS5-Feeder:** multipass cascade (two/three-pass with per-pass history), the full HDR10/PQ bridge with paper-white and color-space-API detection, per-quality-mode SR preset overrides, NR preset selector, OptiScaler upscaler-cascade path, D3D11/Vulkan/OpenGL in-game transports, 32-bit path, DFC/third-party consumer interop + the published feed contract.

**vs ShortFuse DLSS Tool:** live preset switching (feature re-create on change), per-quality SR preset hints, the residual `DLSSNR.*` knobs (GlobalToneStrength, JitterOffsetX/Y, DepthInverted, Upscaling, Subrect, Indicator axes), UICorrection tri-state, multi-runtime attach fallbacks.

**What NeuralScreen has that they don't** (context, not gaps): whole-desktop out-of-process architecture, Spout2 output, recorder/audio (tests: test_recorder_audio.py, test_audio_pack.py), WGC/DDA/dxcam capture chain with fallbacks, residual composite/wipe split, hotkeys, i18n, tray, adaptive exposure (own implementation), extensive Python test suite.

## 4. Preset L feasibility — condensed verdict (full doc: `DLSS45-PRESET-L-FEASIBILITY.md`)

**Verdict: YES — with a version gate.** The DLSS SR 310.9.1 runtime already contains and accepts Preset L (12) and M (13):
- `NVSDK_NGX_DLSS_Hint_Render_Preset_L = 12` exists in this repo's own SDK headers (`native/include/nvsdk_ngx_defs.h:84`).
- RE of `nvngx_dlss-310.9.1.dll`: availability table init (fn @0x180010DB0, entries @0x1838414C0/0x18141F68) initializes **E(5), F(6), J(10), K(11), L(12), M(13)**; `NgxDltss::FillCreationParams` (@0x18004ECF0, refs "dltss.cpp"/"rel_310_9") validates requested preset against that table via `sub_1800B5D60` (preset-available check); DRS override `NGX_OVERRIDE_RENDER_PRESET_SELECTION` (strings @0x1801349b8/0x1801349f8, applied in @0x18006DD10) takes priority over hints.
- Constraint: presets are **create-time** parameters on the DLSS EXT create path (ShortFuse re-creates Reserved18 when preset changes — `sub_180065A60`), and the feature must be re-created (or DRS override set) to switch. `NGX_D3D12_CREATE_DLSS_EXT` is already resolved in our host (host:585), so the same drive path exists: set `DLSS.Hint.Render.Preset.Quality` (etc.) in the create params, or set the DRS override key, then create.
- NR side (Preset L for the *neural renderer*): `nvngx_dlssnr-310.8.SF-v2.dll` ships exactly ONE network — preset 1, weights `CC_Control_History_Blend_Quantize_With_Teacher_honest_tench_2026_07_04_22_30_weights` (weight registry walker `sub_180023A40`, entry @0x1800B0D80, stride 0x288; fallback logs and uses preset 1). So NR "Preset L" does not exist in that runtime — only SR Preset L. Any L+ NR claims would require a newer `nvngx_dlssnr.dll`.

## 5. Artifact provenance (RE inputs)

| Artifact | Source | SHA256 | Size |
|---|---|---|---|
| `renodx-dlss.addon64` | `C:\Users\admin\Downloads\renodx-dlss.addon64` (ShortFuse DLSS Tool, RHI-served) | `C575F3F7C8CA6F4EF3BAA2194EA8E37E06E8EA32EE0701ECFB99035291304B00` | 2,642,432 |
| `nvngx_dlssnr-310.8.SF-v2.dll` | `C:\Users\admin\AppData\Local\RHI\DLSS-NR\310.8.SF-v2\` (RHI dlss_manifest: `https://github.com/RankFTW/rhi-repo/releases/download/dlssnr-310.8.SF-v2/nvngx_dlssnr_310.8.SF-v2.zip`) | `6EB209E764F39872625DEBD6ABAF45E2BB6322F6F270F781F70C059AE30B3927` | 165,830,144 |
| `nvngx_dlss-310.9.1.dll` | `C:\Users\admin\AppData\Local\RHI\DLSS\310.9.1\` (RHI manifest; `LastKnownNewestDlss:310.9.1`) | `3975567B8943C53ACCE397F2B72380092F84F162D00B0D2C7D08A1025C563983` | 58,956,912 |

Working copies + IDA databases: `G:\projects\dlss-re\bin\` (not committed; binaries too large for git).

Sources compared: `G:\projects\DLSS5-Feeder` (git clone of `jlrouzies-fr/DLSS5-Feeder`), this repo tree.
