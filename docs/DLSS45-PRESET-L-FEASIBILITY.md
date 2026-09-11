# DLSS 4.5 Preset L — Feasibility Verdict (RE-backed)

Question: *can the DLSS 4.5 Preset L upscaler work the same way this repo drives other presets?*

**Verdict: YES — for the DLSS SR (super resolution) upscaler, with a DLL version gate. NO — for the DLSS 5
neural-render (NR) path: the shipped NR runtime contains only one network (preset 1); there is no NR "Preset L".**

All findings below are from static RE (IDA/Hex-Rays) of the exact binaries listed in §3, cross-checked against
this repo's own NGX SDK headers and against how DLSS5-Feeder and the ShortFuse DLSS Tool drive presets.

---

## 1. What "Preset L" is

DLSS 4.5 introduced second-generation transformer SR models selectable as render presets:

- Preset **L** = value **12**, "Default for Ultra Perf mode" — `native/include/nvsdk_ngx_defs.h:84` (this repo).
- Preset **M** = value **13**, "Default for Perf mode" — `nvsdk_ngx_defs.h:85`.
- The same enum exists for Ray Reconstruction (`nvsdk_ngx_defs_dlssd.h:50-51`: `Preset_L = 12`, `_M = 13`).
- Corroboration (web): NVIDIA/driver materials and DLSSTweaks describe L/M as the DLSS 4.5 transformer models,
  overridable via `DLSS.Hint.Render.Preset.*` per-quality-mode create-time parameters; DLSSTweaks does exactly
  this. Cross-checked against local binaries below rather than taken from the web alone.

## 2. The runtime actually accepts L/M (RE of `nvngx_dlss.dll` 310.9.1)

Binary: `nvngx_dlss-310.9.1.dll`, SHA256 `3975567B8943C53ACCE397F2B72380092F84F162D00B0D2C7D08A1025C563983`
(58,956,912 bytes), from `C:\Users\admin\AppData\Local\RHI\DLSS\310.9.1\` (RHI manifest field
`LastKnownNewestDlss:310.9.1`).

Findings (imagebase 0x180000000):

1. **Preset availability table.** Init function @ `0x180010DB0` populates the availability table referenced at
   `0x183840038`/`0x183840040` (xrefs in `NgxDltss::FillCreationParams` @ `0x18004ECF0`). Reading the initialized
   entries (`0x1838414C0`, `0x18141F68`) shows the table contains exactly presets
   **E=5, F=6, J=10, K=11, L=12, M=13**. So Preset L and M are present and selectable in 310.9.1.
   The function is tagged by the DLL's own strings/debug paths as `dltss.cpp` / `rel_310_9`.
2. **Requested presets are validated at create time.** `FillCreationParams` calls `sub_1800B5D60`
   ("is preset available") against that table before accepting a hint; an unavailable preset falls back (this is
   the gate that would reject L/M on pre-310.5 DLLs — 310.4 and earlier initialize only up to K per DLSSTweaks'
   version table).
3. **Two selection mechanisms, with a priority order** (RE @ `0x18006DD10`):
   a. `DLSS.Hint.Render.Preset.<QualityMode>` create-time parameters (per-mode values 0-13), and/or
   b. the DRS override key **`NGX_OVERRIDE_RENDER_PRESET_SELECTION`** (strings @ `0x1801349b8`, `0x1801349f8`),
      which takes priority over the per-mode hints.
4. **Create-time semantics.** Preset is a *feature-creation* parameter. The ShortFuse addon switches NR presets by
   re-creating the Reserved18 feature (`sub_180065A60`: sets `DLSSNR.Hint.Render.Preset` at `0x180066375` right
   before `CreateFeature(Reserved18)` @ `0x180066416`, with a retained-feature cache to make recreation cheap and
   the log lines "CreateFeature(Reserved18) succeeded: ... preset={}" / "reused retained feature: ...
   preset={}"). The same re-create requirement applies to SR preset switching.

## 3. Why this repo can drive it "the same way"

This repo's host already has the entire machinery needed:

- It links/loads NGX and resolves `NGX_D3D12_CREATE_DLSS_EXT` / `NGX_D3D12_EVALUATE_DLSS_EXT`
  (`native/dlss5-feed-host64.cpp:585,592` — `SafeCreateDLSS` currently uses it for the 1×1 warm-up probe).
- It builds a parameter object and sets create-time hints already (`DLSSNR.*` keys, host:3696-3715;
  `DLSSNR.ScalingRatio` at host:955).
- It has a robust worker-restart path that can re-create the feature on config change (main.py `restart_worker`,
  MAX_CONSECUTIVE_RESTARTS machinery).

Therefore: to run Preset L, set `DLSS.Hint.Render.Preset.Quality` (or whichever mode / all modes) to 12 in the
create params before `NGX_D3D12_CREATE_DLSS_EXT` — or set `NGX_OVERRIDE_RENDER_PRESET_SELECTION` for a global
override — then (re-)create the SR feature. Gate on the DLL version: parse `nvngx_dlss.dll` file version at load
(or query capability parameters the way the Feeder does on the CAPABILITY object — `dlss5-feed.cpp:3880-3884`,
which warns that an `AllocateParameters` object answers every preset query with no callback and silently falls
back to DLAA) and refuse L/M below 310.5.0 with a clear log line.

## 4. The NR side is a hard NO for "Preset L" on current binaries

Binary: `nvngx_dlssnr-310.8.SF-v2.dll` (RHI-served NR runtime, from
`https://github.com/RankFTW/rhi-repo/releases/download/dlssnr-310.8.SF-v2/nvngx_dlssnr_310.8.SF-v2.zip`),
SHA256 `6EB209E764F39872625DEBD6ABAF45E2BB6322F6F270F781F70C059AE30B3927` (165,830,144 bytes).

RE findings (imagebase 0x180000000):

- The weight-network registry walker `sub_180023A40` iterates entries of stride 0x288 (648 bytes) starting at
  `0x1800B0D80` until terminator `0x1800B1008` — exactly **one entry**.
- That entry: preset = **1** (DWORD @ `0x1800B0D80+8`), network weights named
  `CC_Control_History_Blend_Quantize_With_Teacher_honest_tench_2026_07_04_22_30_weights`
  (string @ `0x1800B1010`), with arch variants `WEIGHTS_HT` (@`0x1800B1068`) and `CC_SILVER_AARDWOLD`
  (@`0x1800B1078`).
- Any other requested NR preset falls back to preset 1 with a log line.
- `DLSSNR.Hint.Render.Preset` is consumed at NR feature create (string @ `0x180214e39` in the ShortFuse addon;
  set at `0x180066375` before `CreateFeature(Reserved18)`).

Conclusion: "Preset L for the neural renderer" does not exist in 310.8.SF-v2. The NR preset selector we plan
(gap #4 / A2) will expose Default/#1/#2/#3 and simply document that only #1 is present on this runtime — new
NR presets would need a newer `nvngx_dlssnr.dll` from NVIDIA's deployment chain (RHI tracks
`LastKnownNewestDlssnr` in its manifest; none newer was present locally to verify).

## 5. Compatibility constraints (summary)

| Constraint | Detail | Evidence |
|---|---|---|
| DLL version | SR Preset L/M require `nvngx_dlss.dll` ≥ **310.5.0**; 310.9.1 confirmed carrying L+M | availability table @ `0x1838414C0` init `0x180010DB0`; validation `sub_1800B5D60` |
| Create-time only | preset cannot be changed via EvaluateFeature params; must re-create feature (or use DRS override) | ShortFuse re-create path `sub_180065A60`; our host's create path host:582-585 |
| Correct param object | optimal-settings/preset capability queries must target the CAPABILITY parameter object; AllocateParameters answers with no callback → silent DLAA fallback | Feeder `dlss5-feed.cpp:3880-3884` (their own bug note) |
| Priority | `NGX_OVERRIDE_RENDER_PRESET_SELECTION` > per-mode hints | applied in `0x18006DD10`, strings `0x1801349b8/f8` |
| NR runtime | `DLSSNR.Hint.Render.Preset` accepted at NR create; 310.8.SF-v2 has only network 1 | weight registry `sub_180023A40` |
| Vendor | DLSS SR requires NVIDIA NGX-capable GPU/driver; that's unchanged from today's requirements | unchanged |

## 6. Implementation pointer

Concrete steps, files, risks, and acceptance criteria: `PLAN-missing-features.md` § Phase A (A1 per-quality SR
preset override — the Preset L enabler; A2 NR preset selector; A3 live re-create without restart).

## 7. Artifacts & provenance

| Artifact | SHA256 | Size | Role |
|---|---|---|---|
| `renodx-dlss.addon64` (ShortFuse DLSS Tool) | `C575F3F7C8CA6F4EF3BAA2194EA8E37E06E8EA32EE0701ECFB99035291304B00` | 2,642,432 | RE of preset-switching UI/mechanics |
| `nvngx_dlssnr-310.8.SF-v2.dll` | `6EB209E764F39872625DEBD6ABAF45E2BB6322F6F270F781F70C059AE30B3927` | 165,830,144 | NR runtime weight registry |
| `nvngx_dlss-310.9.1.dll` | `3975567B8943C53ACCE397F2B72380092F84F162D00B0D2C7D08A1025C563983` | 58,956,912 | SR runtime preset table |

Sources: local files under `C:\Users\admin\Downloads`, `C:\Users\admin\AppData\Local\RHI\` (per RHI
`dlss_manifest.json`), cloned `G:\projects\DLSS5-Feeder` (github.com/jlrouzies-fr/DLSS5-Feeder), this repo.
IDA databases kept at `G:\projects\dlss-re\bin\*.i64` (working copies, not committed).
