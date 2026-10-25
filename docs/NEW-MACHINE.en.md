# Bringing up a new machine (local profile)

**English** | [README](../README.md) | [Headless USB guide](HEADLESS-USB.en.md) | [Portability](PORTABILITY.en.md)

A reviewed profile in `internal-boot/unlock/machine-profile.h` exists for each
hardware-verified machine. For any other motherboard/BIOS/card, this pipeline builds a
**local profile** for your machine only: the same compile-time constants as a reviewed
profile, derived from read-only captures of your own machine, never committed, and
write-eligible only after your machine's own host tests pass against exactly those bytes.

It does **not** add hardware support. A local profile is mock-tested on your fixtures; it is
not hardware evidence until you have run it and reported it (see the end of this page).

## What it accepts

The generator refuses anything outside `research/profile/proven.json`, the envelope that
reviewed profiles have proven on hardware. There is no override flag. Today that means:

| Requirement | Why |
|---|---|
| GA102 (`chip=0xb72000a1`, class/revision `030000a1`) with `0x6000` or `0x5ff4` MiB | the only chip/memory layouts that completed the transaction on hardware |
| exactly one NVIDIA display controller, at `0000:01:00.0`, behind one root port | `GuCheckConfig` / `GuDisplayPath` |
| one integrated (non-NVIDIA) display controller present | the single-RTX console replay has no design without one |
| `ConOut` is exactly the RTX GOP (non-aggregate console) | aggregate splitter consoles are not generated |
| AMI console text/GOP splitter and EDID drivers, `nvgop-ga1xx` | the release path in `full-release.c` |
| `nvgop-ga1xx` `.text` hash already released cleanly on hardware | another build has never been released |
| GPU in its power-on state at every capture | the unlock never runs from anything else |
| at least two complete captures from separate full shutdowns, all agreeing | load-address- or boot-dependent values are refused |
| PROM.BIN matches the captured hash; the production parser finds FWSEC-FRTS within tested bounds | FWSEC pin and transaction tests |

A RTX 3090 or 3090 Ti on an AMD-iGPU board with an AMI BIOS is the likely fit. Anything else
is refused with the reason. Widening the envelope needs a reviewed change that cites new
hardware evidence, normally a new reviewed profile (PORTABILITY stage 4).

## Steps

Needs: LLVM (`clang`, `lld-link`), MSVC build tools, Python 3.8+, the five firmware assets
(`docs/ASSETS.en.md`) and a FAT32 USB stick. Fast Startup off.

```powershell
# Windows ESP GUID: Get-Partition | Where-Object IsSystem | Select Guid
.\research\profile\new-machine.ps1 -Drive D -WindowsEspGuid 'YOUR-WINDOWS-ESP-GUID' -Assets 'C:\LOCAL-FIRMWARE\assets'
```

Run the same command repeatedly; each run does the next step.

1. **Probe.** The first run builds the generic read-only probe
   (`research/profile/build-probe.ps1`, `-DGU_PROBE_GENERIC`) and copies it to the stick as
   `EFI\BOOT\BOOTX64.EFI`, keeping any previous loader in `RTX3090-UNLOCK\backup\` and earlier
   capture files in `RTX3090-UNLOCK\old-*\`. Shut down fully, choose the stick in the firmware
   boot menu, and let it start Windows. Do this twice. The probe only reads: PCI config,
   16 BAR0 registers, the 1 MiB PROM window and loaded driver images. It writes
   `DIAGnn.TXT`, `PROM.BIN` and `IMGnn.BIN` to the stick; it cannot compile with unlock code.
2. **Profile.** With two captures on the stick, the next run copies them to
   `research/profile/local/capture/`, builds `fwsec-locate` (the production VBIOS parser for
   the host) and runs `research/profile/make-profile.py`. It writes
   `internal-boot/unlock/profile-local.h`, `research/profile/local/profile.json` and the test
   fixtures, or stops with the refusal.
3. **Test.** `research/profile/test-profile.ps1` compiles everything with
   `-DGU_PROFILE_LOCAL` and runs: the generator's refusal cases on your captures, the
   config/port/write-lock/BME/runtime/profile-lock tests, a reviewed profile for another
   card rejecting your config and console graph, the R2 console replay of your real graph,
   the cold pre-check, and the production transaction against your real PROM and the stock
   assets with all EFI/MMIO/DMA simulated. Only a complete pass writes
   `research/profile/local/test-results.json`.
4. **Package.** `research/headless/build-usb.ps1 -HardwareProfile local` builds the headless
   USB wrapper and child. Then the run stops; nothing is staged.
5. **Stick.** Read this page and the [headless USB guide](HEADLESS-USB.en.md), then rerun with
   `-StageUnlock`. That runs `research/headless/stage-usb.ps1`. Booting it is the first
   time anything writes to your GPU, and it is never automatic: choose the stick from the boot
   menu after a full shutdown, supervised, exactly as in the USB guide.

## The evidence gate

A write build of `-HardwareProfile local` (`internal-boot/unlock/build.ps1`, `build-usb.ps1`,
and `stage-usb.ps1` again before copying) is refused unless `test-results.json`:

- is a complete pass for this profile name with no hardware access,
- was made against exactly the current `profile-local.h` bytes and PROM hash,
- matches every fixture file byte for byte, and
- matches a digest of the sources, tests, generator and envelope (`Get-LocalTreeDigest` in
  `internal-boot/unlock/local-profile.ps1`).

Editing the header, a fixture or any source after the tests makes the build refuse until
`test-profile.ps1` passes again. A local profile only builds the headless USB write path; the
internal-ESP and manual paths refuse it. Diagnostic/preflight builds need no evidence.

`machine-profile.h` accepts `profile-local.h` only with the generator's marker and a
non-aggregate topology. Never commit it, `research/profile/local/` or any capture: they
identify your hardware and contain your PROM. Both paths are in `.gitignore`.

## When something changes

Regenerate (start again from step 1) after a BIOS update, a different or reflashed card, a
slot change or a Windows reinstall (new ESP). The boot-time checks would refuse anyway, but the
profile no longer describes the machine.

## Reporting a result

After a supervised run, the per-boot log and before/after benchmarks are what a reviewed
profile needs. Open a compatibility report ([CONTRIBUTING](CONTRIBUTING.en.md)) with the
`profile.json` values, the boot log and benchmark results, never the PROM or firmware assets.
A reviewed profile then moves your constants into `machine-profile.h` with that evidence,
and `proven.json` can widen for the next machine.
