# Support evidence review: 26 October 2026

**Conclusion: ordinary CUDA operation is measured on this PC; Windows unlock
support for its exact configuration remains unestablished.**

The public upstream main revision was checked again at 2026-10-26T14:41:32Z:
[`5c98f11eaafdcb7a2a06fb14fcdcde7297eb409e`](https://github.com/impacifist/Windows-GPU-UNLOCK/commit/5c98f11eaafdcb7a2a06fb14fcdcde7297eb409e).
It is unchanged from the initial research. The
[pinned README](https://github.com/impacifist/Windows-GPU-UNLOCK/blob/5c98f11eaafdcb7a2a06fb14fcdcde7297eb409e/README.md)
still lists no dedicated RTX 3080 profile. The
[compatibility guide](https://github.com/impacifist/Windows-GPU-UNLOCK/blob/5c98f11eaafdcb7a2a06fb14fcdcde7297eb409e/docs/COMPATIBILITY.en.md)
does not document this complete GPU, motherboard, BIOS, CPU and driver
combination.

The local configuration remains the RTX 3080 10 GiB, `10de:2216` /
`1458:403f`, ASUS ROG STRIX X570-F GAMING BIOS 5043, Ryzen 7 3700X and
NVIDIA driver 610.88. Model/subsystem identifiers are software observations,
not proof of a particular retail SKU or PCB revision.

## What the related reports establish

| Public report | Relationship to this PC | Evidence boundary |
|---|---|---|
| [Issue #13](https://github.com/impacifist/Windows-GPU-UNLOCK/issues/13), opened 25 October | Same device and subsystem IDs; ASUS PRIME X570-P, BIOS 3603 and Ryzen 5900X | The original submission is inventory only and says no unlock was attempted. It is not a successful test on this X570-F machine. |
| [Issue #28](https://github.com/impacifist/Windows-GPU-UNLOCK/issues/28), updated 26 October | Same `2216` device, but Maxsun `7377:2000` subsystem, B760M, Intel i5-12490F and driver 617.14 | The reporter claims one successful run and a before/after GEMM pair. This is evidence about that different machine; it has not been independently reproduced here or integrated as a supported profile for this PC. |
| [Issue #20](https://github.com/impacifist/Windows-GPU-UNLOCK/issues/20), opened 25 October | RTX 3080 FE `2206` / `10de:1612` on ASUS Z390 and an Intel CPU | Diagnostics and ordinary benchmark evidence. The maintainer explicitly says that it does not yet establish unlock support. |
| [Issue #35](https://github.com/impacifist/Windows-GPU-UNLOCK/issues/35), opened and closed 26 October | Gigabyte subsystem `1458:403f`, but device `2206` and an Intel/B660M system | The body and author comment say no unlock was performed. Its title and closed state must not be counted as successful unlock evidence. |

Issue #13 also contains a success comment from a separate PNY / Ryzen 9800X3D /
MSI system. The maintainer asked for that machine's own reviewable report and
for its evidence to remain separate from the original Gigabyte/X570 submission.
That comment does not change the evidence classification of the original
report.

Issue #28's reported FP16/BF16 improvement is a reason to keep following the
research, not a measured improvement for this PC. The author limits the claim
to one boot and one benchmark pair; repeated starts, sleep/resume, stability
and application gains remain unestablished. This assessment compares the
published evidence without independently reproducing that experiment.

## New evidence from this PC

The separate [ordinary CUDA contribution, PR #45](https://github.com/impacifist/Windows-GPU-UNLOCK/pull/45),
has completed three processes with all four precision modes passing. Its
[immutable validation report](https://github.com/danhol86/Windows-GPU-UNLOCK/blob/a04471a8c2cec047c25383315d122f1d6513462c/benchmark/rtx3080/NATIVE-VALIDATION.md)
records medians of 21.57 TFLOPS FP32, 60.44 FP16, 60.30 BF16 and 30.60 TF32
under the explicit desktop entry profile. These are baseline measurements on
current settings, not a matched before/after experiment.

The [display-path follow-up](display-topology/README.md) supplements the earlier
unknown display-routing field with a read-only Windows observation: one active,
available external DisplayPort path on an adapter matching the inventoried
GPU IDs, with source and target on the same adapter. Windows display routing
cannot establish the pre-boot firmware topology, physical socket/cable chain
or recovery behavior.

Remaining identification questions are the physical card's exact part number
and board revision, firmware cross-flash history, any intermediate display
adapters or switches, and whether a separate spare display GPU is available.
Existing labels or purchase records can clarify retail identity; software
IDs alone cannot settle it.

No driver or BIOS change is justified merely to resemble another report.
The existing firmware sources and compatibility assessment remain unchanged.
