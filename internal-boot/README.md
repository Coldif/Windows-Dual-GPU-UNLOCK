# Internal boot implementation

Read the [Korean walkthrough](../docs/INTERNAL-BOOT.ko.md) or
[English walkthrough](../docs/INTERNAL-BOOT.en.md) before building or installing.

This tree is separate from the legacy USB source. Scope: exact RTX3090/AMD/ASUS
BIOS 3057 profile. Manual direct handoff is hardware verified; automatic firmware
boot and the public registration/promotion adapter remain experimental.

1. `Configure.ps1`: inspect existing dedicated ESP; generate ignored local partition config.
2. `Build.ps1`: build separate manual and automatic child/wrapper pairs.
3. `Install.ps1 -Assets <directory>`: stage only, never format or overwrite different files.
4. `Install.ps1 -Assets <directory> -RegisterManual`: register a manual test, Windows first.
5. After actual manual/performance success, optionally use `-EnableAutomaticBoot -ConfirmedManualSuccess`.
6. `Install.ps1 -RestoreWindowsFirst`: recovery independent of EFI/build files.

Keep local config, install state and backups private. No firmware is distributed.
GPL-2.0-only; root LICENSE and THIRD_PARTY_NOTICES.md apply.
