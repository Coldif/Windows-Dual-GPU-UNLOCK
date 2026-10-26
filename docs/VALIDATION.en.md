# Recording future hardware validation

[한국어](VALIDATION.ko.md)

This checklist organizes an owner's separately planned tests. It does not start a
workload, authorize an EFI run, or establish support. Existing observations can
be submitted with unknown fields; do not repeat hardware experiments just to
complete a report. Host fixtures and synthetic builds remain software evidence.

## Bind each observation to its environment

Record the physical card and VBIOS history, PCI/subsystem identity, board/BIOS,
source commit and local diff, EFI hash, compiler, display cables and other GPUs.
An installed iGPU or Windows display-active flag does not establish pre-boot
ownership. Keep per-run settings: do not combine captures taken before and after
changing BIOS/display configuration into one apparent snapshot.

Keep raw PROM, driver images, firmware, personal paths and disk identifiers
private. Publish reviewed metadata and hashes, not an EFI/archive supplied by
another person as proof of safe execution.

## Separate the evidence stages

| Stage | Evidence to retain | Does not prove |
|---|---|---|
| Windows inventory | Collector version, completeness and model/driver fields | Pre-boot safety or unlock compatibility |
| Diagnostic observation | Source/build identity, PCI command, read status, topology, capture completeness | Driver detach, durable file close or successful unlock |
| Transaction | Initial and target selectors, failure stage, containment, mappings/retained resources and cleanup | Windows recovery or performance uplift |
| Windows recovery | Display and driver health, exact boot transition, available error codes | Compute correctness or sustained stability |
| Matched compute comparison | Same card, executable/libraries/protocol/settings, numerical checks and complete before/after results | Gains in other workloads or other machines |

`capture-complete=1` precedes final flush and file close. A marker alone cannot
prove durable storage, successful cleanup, or Windows handoff. A reported
transaction success without corresponding source/build identity stays a report.

## Future compute measurements

Use the [benchmark protocol](BENCHMARK.en.md) and its comparison tool. New runs
include strict FP32, FP16/FP32 accumulation, BF16/FP32 accumulation and TF32/FP32
accumulation. Strict FP32 is a control, not interchangeable with Tensor Core
paths whose output or accumulator happens to be FP32.

Record matrix sizes, warmup/sample/process counts, CUDA/cuBLAS and driver
versions, numerical policies, GPU/clock/power/thermal conditions, background
load and source/build hashes. Compare matched before/after runs only. A
PyTorch baseline or a different card's published result is useful context,
not a matched cuBLAS unlock percentage. Protocol versions must not be mixed.

No benchmark is scheduled automatically. Hardware measurements remain deferred
until the owner next chooses to test; existing GPU work is left running.

## Lifecycle matrix for a future test session

For each separately planned transition, retain existing evidence with the same
record format. Unknown or untested is a valid result.

| Transition | Required distinction |
|---|---|
| Full shutdown / cold boot | Initial selector state, exact launch path, final driver/display/compute evidence |
| Warm restart | Whether state persists or a new guarded transaction occurs; do not infer cold state |
| Sleep | Actual Windows sleep type (S3 or S0 low-power idle, if known), resume and post-resume evidence |
| Hibernation | Separate from sleep; record whether state resets, without assuming reapplication is safe |
| Driver restart / TDR | Separate operation; no automatic reset/recovery helper is implied by this checklist |

Record repetition counts, failures and cancelled runs, not only a successful
attempt. Do not infer the project's lifecycle support from another
implementation's sleep report. No automatic retry, selector write or boot
configuration change follows from recording this table.
