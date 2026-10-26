# B660-PLUS / RTX 3060 12GB headless USB evidence

## Provenance and build scope

Contributor-reported results from one machine, 2026-10-25, two boots:

| Run | Build | Wrapper `BOOTX64.EFI` | Child `UNLOCK-HEADLESS.EFI` |
|---|---|---|---|
| AUTO000000 | original contribution on the per-machine pipeline branch | `3e9bcb8f7c32211047d8c865fb98f1b14ed3d8b8bd49dc758f6a247cf3f8989a` (39,936 B) | `be5383812af499dddd278ecb4ddd8d1145127dec66b1d7b25f009feb57236985` (67,584 B) |
| AUTO000001 | original PR #24, `60ae7e4e3cb141200280ea82e8618ee39a8b14bd` | `809f483f0a0f9b286bc718b0825bc01ef05be5f559fb3f45758a703e0a339088` (40,448 B) | same, byte-identical |

The contributor reports the second run booted the exact wrapper/child pair the original PR revision builds
(`build-usb.ps1 -HardwareProfile b660plus-3060`; the wrapper embeds the builder's Windows ESP
GUID, so other machines get a different wrapper hash). Its wrapper includes main's
cold-precheck hardening, which passed on hardware (`pre-release-cold-check status=0`).
Later integration with main includes runtime hash bounds and validated-root capture
changes. Its host/build checks do not constitute another physical boot. The hashes
above identify historical contributor builds, not expected hashes for current main.

## Machine

ASUS PRIME B660-PLUS D4 (AMI BIOS 3010), Core i5-12600KF (no iGPU), NVIDIA RTX 3060 12 GB (GA104,
`10de:2487` / `10de:1530`, VBIOS 94.04.71.00.87, 170 W), Windows 11 Pro 26200, driver 616.92. **Launch
CSM disabled** (with CSM on, the AMI INT10 driver owns the card instead of nvgop and BAR0 moves to
`0x94000000`; the checks refuse that state). Secure Boot off, BitLocker off, Fast Startup off.

All monitors on the RTX, attached as in daily use; nvgop produces **two UEFI display children**: the console child (`AcpiAdr 0x80010300`, GOP via the AMI combo splitter) and an
EDID-only sibling (`AcpiAdr 0x80010330`). This is the first profile using `GU_CONSOLE_MULTI_CHILD`
(`GU_CONSOLE_CHILD_COUNT 2`). The topology was identical across three read-only probe captures, the
last taken in the normal multi-monitor boot state.

## Recorded hardware run

| Run | Boot | Pre-check | Entry SS0 / SS1 | Result |
|---|---|---|---|---|
| AUTO000000 | full shutdown, F8 → USB | (older wrapper) | `0x40110006` / `0x7` | `FINAL status=0 clean=1`, one FLR, Windows direct, all monitors restored |
| AUTO000001 | full shutdown, F8 → USB | passed (cold) | `0x60110006` / `0x7` | same |

Entry SS0 varies between power-ons; the `entryLatchedSs1Full` profile latches whatever it finds.
After each run: `SS0=0x88888888 SS1=0x8`, GFW boot completed, WPR2 cleared, BME off, no retained
mappings (`transaction result=0 containment=0 quiesced=1 fault=0 retained=0 maps=0 FLR=1`). The
wrapper log ended with `verify-complete` and `StartImage` of Windows Boot Manager.

## Benchmark

PyTorch (CUDA 12.4 build) / cuBLAS, n=4096, FP32 accumulation (reduced-precision reduction
disabled), 2 s warmup, median of 30 samples, all-ones reference check. Same driver, power limit and
script before and after. Locked baseline taken after a full shutdown and a normal boot without the
stick.

| TFLOPS | Locked | After AUTO000000 | After AUTO000001 (original PR revision) |
|---|---:|---:|---:|
| FP32 (no tensor) | 7.99 | 8.03 (1.00×) | 7.98 (1.00×) |
| TF32 tensor | 12.98 | 25.24 (1.94×) | 25.06 (1.93×) |
| FP16 tensor / FP32 acc. | 26.12 | 50.04 (1.92×) | 49.07 (1.88×) |
| BF16 tensor / FP32 acc. | 25.77 | 50.23 (1.95×) | 49.41 (1.92×) |

PyTorch 2.6.0+cu124, driver 616.92, 170 W.

Excluded: PROM image, raw probe/graph logs, driver dumps, partition identifiers. Not established:
Windows-restart behaviour, the pre-check skip branch, sleep/hibernate
resume, long-term stability and application performance, the internal-ESP route for this profile.
