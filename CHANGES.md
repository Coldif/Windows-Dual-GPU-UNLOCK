# Changes

## 2026-10-20 — Windows GPU UNLOCK public case study

- Base: rough2515-hub/rtx3080-unlock-public at a08254d269af30ace9e57237abd3d8e6c261e8f5; original core and licenses retained.
- Local changes made 2026-10-19/20: exact RTX3090 24GiB and AMD iGPU identity checks, memory layout, firmware ownership/PCI access checks, default read-only mode, explicit experimental profiles, immutable entry-selector latch and one SS1 write for entryLatchedSs1Full, phase guards, corresponding host mock tests.
- Modified upstream files: unlock/app.c, app_io.c, build.ps1, checks.c, checks.h, port.c, port.h, test-all.ps1, tests/test_app.c, test_checks.c, test_efi_transaction.c, test_master_attributes.c, test_pe.py, test_port.c, test_sha256.c, vendor/unlock_610.c. Additional RTX3090 tests are under unlock/tests/.
- Public packaging only: portable LLVM defaults, configurable MSVC environment and PE negative tests that inspect the selected profile rather than requiring a separate preflight build; no further GPU transaction changes. Success EFI is tied to hashes of the corresponding C sources and headers. Changed source files carry dated notices; C notices share an existing line to preserve diagnostic __LINE__ values and reproduce the successful EFI byte for byte.
- Added Korean USB/ASUS boot handoff guide, measured results and benchmark sources. Changed benchmark device selection to RTX3090, added inspect-only mode, and kept the original GEMM helper/measure path.
- The release deliberately excludes NVIDIA firmware, drivers, CUDA DLLs, original PROM dumps, private paths, credentials and unrelated repositories.
- Direct Windows chainload and internal disk automatic boot are not implemented.
