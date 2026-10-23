# Windows GPU UNLOCK

> **Research branch: `research/single-gpu-headless`.** This branch investigates
> one RTX3090 without an iGPU display. R1 hardware observation confirmed one active
> RTX GOP and Windows entry without unlocking or detaching drivers. This is
> **not a headless unlock EFI**. A separate F8-selected R2 console-consumer test
> proceeds without further keys. It is
> available; hardware detachment remains unverified.
> [Research notes and experiments](research/headless/README.ko.md).
> The observation entry preserves the existing default boot priority; [main](https://github.com/impacifist/Windows-GPU-UNLOCK/tree/main)
> remains the supported release path.

**English** | [한국어](README.ko.md)

## Start here: choose USB or an internal partition

This experiment requires the supported **RTX 3090 / ASUS BIOS 3057 / AMD iGPU**
profile. Check [compatibility](docs/COMPATIBILITY.en.md) first. Copying `.c` source
files onto a drive is not enough: you need an **EFI application and five firmware
assets**. Back up existing files before preparing a drive.

| Method | File location | Boot flow | Full instructions |
|---|---|---|---|
| First manual trial using USB | FAT32 USB | USB → U → firmware Boot Override → Windows | [USB guide](docs/GUIDE.en.md) |
| Internal disk with optional automatic handoff | Separate FAT32 ESP | Internal EFI → unlock → Windows directly | [Internal boot guide](docs/INTERNAL-BOOT.en.md) |

### A. Put the manual version on USB

1. **Prepare** — get the source from [Releases](https://github.com/impacifist/Windows-GPU-UNLOCK/releases)
   or clone this repository. Prepare the five [firmware assets](docs/ASSETS.en.md)
   in a local `assets/` directory.
2. **Generate a USB folder** — from the repository directory, run:

   ```powershell
   python .\tools\prepare_usb.py --assets .\assets --output .\usb-package
   ```

   This creates a new local folder; it does not format or write to USB. Choose a
   new output path if `usb-package` already exists.
3. **Copy** — copy the **contents** of `usb-package` to the FAT32 USB root. You
   should have `USB:/EFI/BOOT/BOOTX64.EFI` and `USB:/RTX3090-UNLOCK/ASSETS/`.
4. **Unlock** — save work, fully shut down, start, choose **ASUS F8 → UEFI USB**,
   then press **U once after preflight passes**.
5. **Continue to Windows** — after success and cleanup, use **Boot Override →
   Windows Boot Manager**, without Save Changes & Reset or another reboot.
6. **Measure** — check [FP16/BF16 performance](docs/BENCHMARK.en.md) in Windows.

**This USB version is manual.** Setting firmware priority to `USB → Windows` alone
does not implement a no-reset automatic handoff. Use method B for that implementation.

### B. Put the internal version on a separate ESP

1. **Prepare storage** — preserve the existing Windows ESP and recovery partition.
   Create or select a **separate FAT32 ESP of at least 1 GiB**, such as U:.
   Follow the [partition preparation steps](docs/INTERNAL-BOOT.en.md#prerequisites).
2. **Build for your PC** — run `Configure.ps1` with the Windows ESP GUID and the
   dedicated partition letter, then `Build.ps1`.
   [Exact commands](docs/INTERNAL-BOOT.en.md#configure-and-build).
3. **Stage and register** — use `Install.ps1 -Assets <directory>`, then add
   `-RegisterManual`. Windows stays first. [File placement and registration](docs/INTERNAL-BOOT.en.md#stage-then-register-a-manual-test).
4. **Test manually first** — fully power off, choose **F8 → Windows GPU UNLOCK
   Manual**, then U once in the unlock app. Confirm direct Windows entry and
   FP16/BF16 performance without an intervening reset.
5. **Enable automatic boot** — after personally confirming that test, run:

   ```powershell
   .\internal-boot\Install.ps1 -Assets 'C:\LOCAL-FIRMWARE\assets' `
     -EnableAutomaticBoot -ConfirmedManualSuccess
   ```

6. **Boot without key input** — firmware order becomes **Windows GPU UNLOCK Auto →
   Windows Boot Manager**. On the next full power-on, wait for the automatic path.
   Esc in the first five seconds boots Windows without unlocking.

Automatic firmware boot is **still awaiting its first real validation**; confirm
both Windows entry and performance yourself. The manual direct handoff is hardware
verified. On failure, fully power off and choose **F8 → Windows Boot Manager**.
Use the [recovery command](docs/INTERNAL-BOOT.en.md#restore-windows-first) to put
Windows first again. Sleep/hibernate resume is outside the validated scope.

## Internal implementation and validation status

**[Step-by-step install, automatic boot and recovery](docs/INTERNAL-BOOT.en.md)**

On 2026-10-23 the same ASUS BIOS 3057 / RTX 3090 system completed internal manual
unlock, direct Windows handoff and Tensor verification: FP16 **125.91**, BF16
**128.93 TFLOPS**, three-run medians. [Measurements](evidence/internal-handoff/summary.json).

`internal-boot/` adds live display-endpoint discovery, bounded status-bit handling,
detailed handoff failures and a separate **no-U automatic variant**. Automatic mode
has host tests and a local installation, but **its first real firmware boot remains
unverified**. No new hardware profile is supported. Build for your own partition
GUIDs and verify manual operation first. The legacy USB instructions and release EFI below remain manual.

Experimental UEFI code and a reproducible Windows guide for an **NVIDIA RTX 3090 Tensor compute case study**. Adapted from [rough2515-hub/rtx3080-unlock-public](https://github.com/rough2515-hub/rtx3080-unlock-public/tree/a08254d269af30ace9e57237abd3d8e6c261e8f5), using the original [Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock/tree/0ebdb1c6308b6a2072be5bf04513472942541956) core.

> **Current scope: one verified RTX 3090 / ASUS / AMD iGPU system.** The shipped EFI contains exact-machine checks. Other RTX 3090 cards, motherboards, CPUs and display configurations are unverified. Do not bypass checks or replace constants to force execution.

The key observation in this case was to **continue to Windows Boot Manager without resetting after unlock**. On the tested ASUS firmware, this was `Boot Override → Windows Boot Manager`. `Save Changes & Reset` may discard the modified state.

## Measured results

Medians of three runs per path on October 20, 2026, using the same CUDA 12.6 / cuBLAS 12.6 executable. The installed **NVIDIA Windows driver 617.14 was unchanged**.

| Workload | Earlier boot path, TFLOPS | No-reset Windows handoff, TFLOPS | Change |
|---|---:|---:|---:|
| FP32 pedantic | 24.505702 | 24.890281 | +1.57% |
| FP16 Tensor / FP32 accumulation | 70.548081 | 125.907816 | +78.47% |
| BF16 Tensor / FP32 accumulation | 70.529545 | 128.699728 | +82.48% |

Both paths had reported UEFI unlock success. This comparison is **not a controlled untreated cold-boot baseline**. The operator reported resetting in the earlier path and using Boot Override without reset in the later path. The results support the handoff explanation but do not isolate every possible cause. They do not establish equivalent gains in games or ComfyUI, or long-term stability. See [results and limitations](docs/RESULTS.en.md).

## Verified environment

- NVIDIA RTX 3090 24 GiB: PCI `10de:2204`, subsystem `10de:1454`, BDF `0000:01:00.0`.
- ASUS TUF GAMING B650M-PLUS WIFI / AMD Ryzen 7 7800X3D.
- AMD integrated graphics: PCI `1002:164e`, subsystem `1043:8877`. Monitor connected to the motherboard output through Windows entry.
- Windows 11 Home build 26200 / NVIDIA 617.14.
- x64 UEFI, Secure Boot disabled, FAT32 USB.
- Profile `entryLatchedSs1Full`: target SS0 `0x88888888`, SS1 `0x8`.
- Additional exact PROM, BAR and GOP requirements: [compatibility](docs/COMPATIBILITY.en.md).

AMD here describes the **host CPU and integrated display adapter**. This repository does not provide an AMD Radeon GPU unlock. An Intel host is a future portability target; other NVIDIA GPUs also require separate investigation and validation.

## Getting started on the verified system

1. Read the [USB and boot guide](docs/GUIDE.en.md), check compatibility and back up existing USB contents.
2. Prepare the five required [firmware assets](docs/ASSETS.en.md). Firmware is not distributed in this repository.
3. Use the packaging tool described in the guide to create a new local folder containing the published EFI, assets, documentation and corresponding source. Copy its contents to a FAT32 USB manually. You can also [build the EFI](docs/BUILD.en.md).
4. Save your work, fully shut down Windows, and boot with the monitor connected to the motherboard.
5. On the tested ASUS system: **F8 → UEFI USB → preflight passes → press U once**.
6. After success and completed cleanup, return to firmware and select **F7 → Advanced Mode → Boot → Boot Override → Windows Boot Manager**.
7. **Do not use F10, Save Changes & Reset, or reboot between unlock and Windows entry.**
8. Close other GPU workloads and compare using the [same benchmark](docs/BENCHMARK.en.md).

If the app reports `STOP / POWER OFF` or fails, fully power off instead of continuing to Windows. Do not press U again in the same boot. Keep the display on integrated graphics through Windows entry; switching to RTX display output afterward is unverified. ASUS menu names are a record of this system, not instructions proven on every firmware.

## Help expand compatibility

We want to support more systems through **discovery, reviewed device profiles and reproducible evidence**. The current EFI remains restricted to the verified machine. A Windows inventory report cannot verify pre-boot GPU ownership, firmware compatibility or cleanup safety.

- [Submit a compatibility report](docs/CONTRIBUTING.en.md) without running the unlock on an unverified system.
- [Portability design and acceptance criteria](docs/PORTABILITY.en.md): separate platform discovery from GPU policy, preserve safety checks, validate each new profile.
- Reports and host mock tests do not automatically add hardware support.

## Repository contents and limits

| Path | Contents |
|---|---|
| `unlock/`, `deps/` | Port source, headers, host mock tests and build tools |
| `release/` | Successful-case EFI and corresponding-source hashes; no firmware assets |
| `benchmark/` | Measurement source and local CUDA 12.6 setup/build/run tools |
| `evidence/` | Measurement data, selected logs and hashes; no original PROM or device UUIDs |

The original root app remains the USB manual version returning to firmware. The separate `internal-boot/` implementation adds a hardware-verified manual Windows handoff and an automatic variant awaiting real firmware validation. Neither procedure requires VBIOS flashing or Windows driver replacement. Existing Windows EFI/recovery partitions are preserved; internal installation uses a separate dedicated ESP.

## License and attribution

The port and reused core are **GPL-2.0-only**; EDK2 and separately attributed components retain their licenses. Preserve [LICENSE](LICENSE), [third-party notices](THIRD_PARTY_NOTICES.md) and [change history](CHANGES.md). NVIDIA firmware, drivers and CUDA DLLs are not redistributed.
