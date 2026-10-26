# H610M / RTX 3060 12GB (GA106) headless USB evidence

## Provenance and build scope

These results come from one machine, reported by the contributor, on 2026-10-26. The
maintainer has not run a hardware test for them. The EFI hashes in
[summary.json](summary.json) are the files that were booted. They were built from
original PR #30 revision `4b748f5e88344f1a1a1fa8d7b5788e528cb19dba` with
`research/headless/build-usb.ps1 -HardwareProfile h610m-3060`.
The wrapper embeds the builder's Windows ESP GUID, so its hash differs on other
machines.
Later integration preserves current ownership/local-profile checks and hardens
observation. It has no new physical boot result; historical hashes below are not
expected hashes for a new main build. Private-PROM transaction and app-level
tests have not been independently rerun by the maintainer.

Hardware: Gigabyte H610M H (BIOS FC), Core i5-14400 (UHD 730 iGPU enabled, no GOP)
and Gigabyte RTX 3060 12 GiB (GA106, `10de:2504` / `1458:4096`, VBIOS
94.06.2f.40.73). Both monitors were on the RTX. Upstream Zagitta/gpu-unlock already
accepts `0x2504` with the same GA10x transaction. This is the first GA106 profile
in this repository.

## How the profile was derived

1. Three cold boots of a read-only USB observation EFI built with `-DGU_PROFILE_PROBE_H610M_3060`.
   That profile defines only the PCI identity and fails to compile with any
   release or unlock define. A fourth boot also saved the 1 MiB PROM window
   (`-DumpProm`). The PROM stays local.
2. `research/headless/fingerprint_probe.py` read the captures and image dumps. The
   nvgop driver is byte-identical to the B660M and X870 entries (`0x60010`, .text
   SHA `615b37a7…`). The AMI console, graphics console and EDID drivers are new for BIOS FC.
3. Host tests: `test-cold-precheck.ps1 -HardwareProfile h610m-3060` (180 cold
   pre-check cases and 39 flow checks) and `test_efi_transaction.c` with this card's
   PROM, the five verified assets and the probe's config space (112 scenarios).
   FWSEC-FRTS is at PROM `0x416bc` (`0xea00` bytes).

## Recorded hardware run

| Run | Boot | Result |
|---|---|---|
| HLS000000 | full shutdown | refused before release: no RTX GOP in that boot (`console-prepare-preflight` `EFI_NOT_FOUND`). Nothing was released and the firmware boot order continued to Windows |
| HLS000001 / AUTO000000 | full shutdown | pre-check passed (cold). `FINAL status=0 clean=1`, `SS0=0x88888888 SS1=0x8`, one FLR, Windows started directly with both displays recovered |

The 12 GiB layout differs from the 24 GiB profiles. FRTS is at `0x2ffe00000` and WPR2
at `0x2ffe000`–`0x2ffee00` pages. See [report-excerpt.txt](report-excerpt.txt).

| torch.mm n=8192, FP32 accumulate, 170 W, TFLOPS (median of 5) | Locked | After AUTO000000 |
|---|---:|---:|
| FP32 | 9.58 | 9.34 |
| TF32 | 13.50 | 24.02 (1.78×) |
| FP16 | 27.06 | 46.61 (1.72×) |
| BF16 | 27.18 | 46.28 (1.70×) |

The locked baseline was measured on the same machine, driver (610.88), power limit
and script, after a read-only probe boot. This method differs from the cuBLAS n=4096
benchmark used for the other profiles. When unlocked, the card reaches its power
limit: the reported SM clock drops from about 1950 to about 1785 MHz. That is a
plausible contributor explanation for the slightly lower FP32 result, not an
independently controlled attribution.

Excluded: the PROM image, the raw probe and graph logs, driver image dumps and
partition identifiers. Not established: repeated cold-boot reliability (one
successful transaction), Windows restart, sleep/hibernate resume, long-term
stability and application performance, and the internal-ESP route.
