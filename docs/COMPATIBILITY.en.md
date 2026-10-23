# Verified hardware and exact checks

**English** | [한국어](COMPATIBILITY.ko.md)

The current EFI checks much more than a GPU model name. Its main constraints are:

| Item | Required value |
|---|---|
| GPU PCI | vendor `10de`, device `2204` |
| GPU subsystem | vendor `10de`, device `1454` |
| GPU BDF | `0000:01:00.0` |
| Chip | `0xb72000a1` |
| VRAM | `0x6000` MiB = 24 GiB |
| BAR0 | `0xf5000000`, 16 MiB |
| PROM SHA-256 | `8ea297373e9e5d3600ff41ad9fae88f2d14c98c017d100669f7333981da673b4` |
| iGPU PCI | `1002:164e`, subsystem `1043:8877` |
| iGPU BDF/GOP | `0000:0c:00.0` and the captured AMD display path |
| Secure Boot | Disabled |
| Successful profile | `entryLatchedSs1Full` |

Verified machine: ASUS TUF GAMING B650M-PLUS WIFI / Ryzen 7 7800X3D / Windows 11 Home 26200 / NVIDIA 617.14.

The executable checks are in [`unlock/port.h`](../unlock/port.h), [`port.c`](../unlock/port.c), [`checks.c`](../unlock/checks.c) and [`app.c`](../unlock/app.c). Additional checks cover the original PCI configuration, PROM and display path. This table does not independently authorize execution.

| Environment | Current status |
|---|---|
| Exact published machine and boot path | One documented successful case; long-term stability unverified |
| Another RTX 3090, including the same model in a different PC | Unverified; exact-machine checks can reject it |
| Intel CPU/iGPU or another AMD/ASUS platform | Unverified; current AMD display checks are restrictive |
| No iGPU, multiple discrete GPUs, laptop/hybrid graphics | Unverified; a separate display/ownership design is required |
| Other NVIDIA models or architectures | Separate GPU port and validation required |
| AMD Radeon or Intel discrete GPU as the unlock target | No unlock implementation in this repository |

Replacing a PROM hash or removing checks is not a safe port. A new port needs validated memory/WPR layout, firmware compatibility, PCI ownership, DMA cleanup and failure containment. See the [portability plan](PORTABILITY.en.md) and [reporting guide](CONTRIBUTING.en.md).
