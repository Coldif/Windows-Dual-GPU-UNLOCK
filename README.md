# Windows GPU UNLOCK

**English** | [한국어](README.ko.md)

Experimental UEFI unlock and direct Windows handoff for one documented **RTX 3090
Founders Edition / ASUS BIOS 3057** system. **v0.3.0 is a source-only pre-release**:
build the internal EFI for your own partition GUIDs. Firmware assets and private,
partition-specific EFI binaries are not bundled with this release.

On October 24, 2026, the system completed an internal **headless unlock** with all
monitors on the RTX: one active RTX GOP before release, zero physical GOPs afterward,
one automatic unlock transaction, and Windows display recovery. Subsequent Windows
measurements reached **FP16 124.97 / BF16 128.93 TFLOPS** (three-run medians).
[Evidence and limitations](evidence/headless-handoff/README.md).

This is one machine and boot, not general RTX 3090 support. The Ryzen 7 7800X3D
**has an iGPU**; the experiment used no active AMD GOP. CPUs without an iGPU,
Intel hosts, other cards and other BIOS versions remain unverified.
Read [compatibility](docs/COMPATIBILITY.en.md) first.

## Choose the correct boot path

| Path | Display and input | Instructions |
|---|---|---|
| **Internal headless** | Monitors on RTX; display temporarily removed; no T/U/Enter | [Headless guide](docs/HEADLESS.en.md): one actual unlock + Windows handoff verified |
| Internal AMD-display manual / Auto | Motherboard/iGPU display preserved; manual variant requires U | [Existing internal guide](docs/INTERNAL-BOOT.en.md) |
| Legacy USB manual | AMD/iGPU display; U once, then Boot Override to Windows without reset | [USB guide](docs/GUIDE.en.md) |

**Headless USB boot has not been tested.** The legacy USB EFI still requires its AMD
display profile. BIOS priority `USB → Windows` alone does not implement direct handoff.

## Internal headless quick start

Read the [full guide and recovery procedure](docs/HEADLESS.en.md) before changing
boot settings. Use the exact supported hardware, Secure Boot disabled, a fully
decrypted Windows C: with BitLocker protection off, and a connected keyboard.
The tools do not disable encryption.

Preserve the **existing Windows ESP and recovery partition**. Prepare a separate
GPT FAT32 **EFI System Partition of at least 1 GiB**, with a letter such as U:.
Tools do not create, shrink, delete or format partitions. An ordinary FAT32 data
partition alone is not the required ESP.

You need Python 3.9+, clang/lld-link **20.1.8**, the pinned repository dependencies
and five locally obtained [firmware assets](docs/ASSETS.en.md).
Host integration tests additionally need MSVC/Windows SDK and private fixtures.

From an administrator PowerShell in the repository root:

```powershell
# Replace the GUID and tool paths with your own values.
.\internal-boot\Configure.ps1 -UnlockDriveLetter U `
  -WindowsEspGuid 'YOUR-WINDOWS-ESP-GUID'
.\research\headless\build-unlock.ps1 `
  -Clang 'C:\TOOLS\LLVM20\bin\clang.exe' `
  -LldLink 'C:\TOOLS\LLVM20\bin\lld-link.exe'

# Stage and append a separate F8 test entry; retain existing boot priority.
.\internal-boot\Headless.ps1 -Assets '.\assets' -Register
```

Without an action switch, `Headless.ps1 -Assets '.\assets'` only stages files.
Configuration and build do not register a boot entry.

1. Save work and fully power off. On the tested ASUS firmware, select
   **F8 → GPU Headless UNLOCK - EXPERIMENTAL**.
2. **Wait without T, U or Enter.** Initial Esc within five seconds skips release
   and unlock and boots Windows directly.
3. The screen becomes black while the RTX GOP is removed. The child attempts
   once and the wrapper starts Windows directly. Do not reset between unlock and
   Windows. Confirm display recovery and [measure](docs/BENCHMARK.en.md).
4. Only after that F8 test succeeds, enable default automatic boot:

   ```powershell
   .\internal-boot\Headless.ps1 -EnableAutomatic -ConfirmedSuccess
   ```

That explicit action places headless first and Windows Boot Manager second and
disables Windows Fast Startup. Test registration alone does not. Publishing this
release does not change the research PC's current default boot selection.

**The two Esc windows differ:** initial wrapper Esc boots Windows without release;
the later three-second child Esc window is after release and cancels into a stop.
It does not restore the display or continue to Windows. On failure or if Windows
does not return, fully power off and choose **F8 → Windows Boot Manager**.

```powershell
.\internal-boot\Headless.ps1 -RestoreWindowsFirst
```

Windows-first recovery is independent of experimental EFI/build artifacts and
still works without saved state. Restoring the prior Fast Startup setting needs
that state; retain it and backups. [Recovery details](docs/HEADLESS.en.md#recovery).

## Results and limits

The successful child reported SS0 `0x88888888`, SS1 `0x8`, BME disabled, zero
remaining mappings, completed cleanup and one FLR. The wrapper verified the released
topology before Windows entry. Windows display recovery was observed by the operator.

| CUDA 12.6 / cuBLAS 12.6, 4096 × 4096 | Three-run median |
|---|---:|
| FP32 pedantic | 22.85 TFLOPS |
| FP16 Tensor / FP32 accumulation | 124.97 TFLOPS |
| BF16 Tensor / FP32 accumulation | 128.93 TFLOPS |

There is **no contemporary controlled locked baseline** for this headless boot,
so these values do not establish an unlock percentage. They do not establish game
or ComfyUI gains, long-term stability, sleep/hibernate resume or repeated automatic
cold-boot reliability. [Sanitized measurements](evidence/headless-handoff/summary.json)
and [earlier results](docs/RESULTS.en.md) describe separate experiments.

## Implementation and boundaries

Headless is a separate compile-time profile. Exact GPU/PROM/PCI state, firmware
driver code, ownership, cold state, immutable selectors and cleanup checks remain.
The child logs to files only and rejects physical GOP reappearance or changed
console/input interfaces. Ordinary builds retain their AMD display guards.
Do not remove checks or substitute a PROM hash to force another machine through.

| Path | Purpose |
|---|---|
| `internal-boot/`, `research/headless/` | Internal/headless source, local build, installation and host tests |
| `unlock/`, `release/` | Preserved legacy USB manual implementation and historical artifacts |
| `benchmark/`, `evidence/` | Measurement tools and selected public evidence |
| `docs/` | Compatibility, assets, boot guides and limitations |

No VBIOS flashing or Windows driver replacement is part of the procedure.
Driver 617.14 was unchanged in the documented run. Host mock tests do not add hardware
support. New systems require [compatibility reporting](docs/CONTRIBUTING.en.md) and
[portability validation](docs/PORTABILITY.en.md).

## License and attribution

The port and reused core are **GPL-2.0-only**; EDK2 and separately attributed
components retain their licenses. Based on
[rough2515-hub/rtx3080-unlock-public](https://github.com/rough2515-hub/rtx3080-unlock-public/tree/a08254d269af30ace9e57237abd3d8e6c261e8f5)
and [Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock/tree/0ebdb1c6308b6a2072be5bf04513472942541956).
Preserve [LICENSE](LICENSE), [third-party notices](THIRD_PARTY_NOTICES.md) and
[change history](CHANGES.md). NVIDIA firmware, PROM/BIOS images, drivers and CUDA
DLLs are not redistributed in this source release.
