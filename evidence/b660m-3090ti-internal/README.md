# B660M / RTX 3090 Ti headless internal-ESP evidence

## Provenance and build scope

These results come from one machine, reported by the contributor, on 2026-10-27.
The maintainer has not run a hardware test for them. The EFI hashes in
[summary.json](summary.json) are the files that were booted. They were built from
this PR revision with `research/headless/build-unlock.ps1 -HardwareProfile b660m-3090ti`.
The wrapper embeds the builder's Windows ESP GUID, so its hash differs on other machines.

This is the same physical machine and AMI BIOS 4003 as the reviewed `B660M_3070TI`
profile, with a Colorful RTX 3090 Ti 24 GiB (GA102) replacing the 3070 Ti in the
same root port. The AMI console, graphics console, EDID and nvgop driver
fingerprints are byte-identical to that entry; only the GPU-side constants
differ. It is the first internal-ESP (`GU_INTERNAL_BOOT`) profile contributed on
this route rather than USB.

## Machine

ASUS TUF GAMING B660M-E D4 (AMI BIOS 4003), Core i7-12700F (no iGPU), Colorful
RTX 3090 Ti 24 GiB (GA102, `10de:2203` / `1301:7377`, VBIOS 94.02.a0.00.0b),
Windows 11 Pro 22000, driver 616.92. Secure Boot off, BitLocker off, Fast
Startup off. All monitors on the RTX via the AMI aggregate console (same
`GU_CONSOLE_AGGREGATE` topology as `B660M_3070TI`).

The card reports `0x5ff4` MiB usable like the X870 GA102 sibling, not the 3070
Ti's `0x2000`; FRTS is at `0x5ff200000`. BAR0, root port `Pci(1,0)` and the
display device path are unchanged from the 3070 Ti board.

## How the profile was derived

1. A cold boot of a read-only generic probe EFI
   (`research/profile/build-probe-internal.ps1`, `-DGU_DIAGNOSTIC_PROBE` plus
   `-DGU_PROBE_GENERIC`) captured the config space, BAR0, PROM digest, GOP
   device path and driver image dumps on this machine.
2. `research/headless/fingerprint_probe.py` / `research/profile/make-profile.py`
   `code_hash` confirmed the nvgop driver (`0x60010`, .text SHA `615b37a7...`) and
   the EDID driver (.text SHA `a015d52f...`) are byte-identical to the `B660M_3070TI`
   entry. The console, graphics console and combo AMI drivers match too.
3. `test-cold-precheck.ps1 -HardwareProfile b660m-3090ti` and
   `test_efi_transaction.c` replayed against this card's PROM and probe captures
   before the write build was armed.

## Recorded hardware run

| Run | Boot | Pre-check | Entry SS0 / SS1 | Result |
|---|---|---|---|---|
| AUTO000024 | full shutdown, firmware bootsequence | passed (cold) | `0x2165162` / `0x7` | `FINAL status=0 clean=1`, one FLR, Windows direct, display recovered |

After the run: `SS0=0x88888888 SS1=0x8`, GFW boot completed, WPR2 cleared, BME
off, no retained mappings (`transaction result=0 containment=0 quiesced=1
fault=0 retained=0 maps=0 FLR=1`). The wrapper log ended with `verify-complete`
and `StartImage` of Windows Boot Manager. The firmware boot order now runs this
entry first on every boot for the automatic headless unlock.

Excluded: PROM image, raw probe/graph logs, driver dumps, partition identifiers,
EFI images. Not established: repeated cold-boot reliability (one transaction so
far), Windows restart behaviour and the pre-check skip branch, sleep/hibernate
resume, long-term stability, game/application performance and a controlled
locked baseline on this card.

See [summary.json](summary.json) and [report-excerpt.txt](report-excerpt.txt).