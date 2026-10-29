/* GPL-2.0-only. Multi-target runtime unlock child (GU_PROFILE_MULTI_GPU).
 *
 * Purpose: unlock more than one discrete NVIDIA card in the SAME power-on
 * session, because the unlock is volatile and is lost on power off. The
 * vendor transaction (vendor/unlock_610.c) already supports one card per call
 * and explicitly allows concurrent unlocks sharing one firmware load; what
 * upstream does not have is an orchestration layer for more than one target.
 *
 * What this file deliberately keeps from the single-target method:
 *   - cold, unbound GPU: PLM/WPR2/GFW sample and chip/VRAM identity per card;
 *   - exact PCI admission (segment, device, function, class, PM/D0, FLR,
 *     memory decode on, bus master off, expansion ROM off);
 *   - exclusive ownership of the card, one guarded transaction per card,
 *     no retry, and hardware containment (BME cleared) after every attempt.
 *
 * What this file deliberately does not do:
 *   - it never runs a second attempt, on the same card or on another one,
 *     after any failure that touched hardware;
 *   - it does not require an independent display adapter: on a no-iGPU board
 *     releasing the card's firmware driver ends console output, so output is
 *     file-only from that point and Windows is started immediately after;
 *   - it does not pin a compile-time PROM hash or console fingerprint. The
 *     live PROM hash is logged per card as identity evidence, and the card is
 *     admitted by device ID, subsystem, chip revision, VRAM size and bus.
 */
#include "app_io.h"
#include "checks.h"
#include "sha256.h"
#include "ownership.h"
#include "compat/compat.h"
#include "vendor/unlock_610.h"
#include "vendor/gfw_eval.h"
#include <IndustryStandard/Acpi.h>
#include <Guid/GlobalVariable.h>

#ifndef GU_MULTI_GPU
#error multi-app.c must only be built for GU_PROFILE_MULTI_GPU
#endif
#if !defined(GU_EXPERIMENTAL_3090) || !defined(GU_ENTRY_LATCHED_SS1_FULL)
#error The multi-target child uses the validated entryLatchedSs1Full transaction
#endif

#define GU_MULTI_MAX_TARGETS 2U
#define GU_MULTI_MAX_NVIDIA 4U
#define GU_MULTI_BAR_BYTES 0x1000000ULL
#define GU_MULTI_PROM_BYTES 1048576U
#define GU_MULTI_PROM_OFFSET 0x300000ULL

typedef struct {
  UINT32 Device;
  UINT32 Subsystem;
  UINT32 Chip;
  UINT32 Memory;
  const char *Name;
  EFI_HANDLE Handle;
  EFI_PCI_IO_PROTOCOL *Pci;
  UINT32 Config[64];
  UINT64 BarBase, BarSize;
  GU_CAPS Caps;
  UINTN Segment, Bus, DeviceNumber, Function;
  BOOLEAN Present;
  BOOLEAN Done;
  BOOLEAN Released;
  BOOLEAN DecodeEnabled;
} GU_MULTI_TARGET;

/* Cards this build is allowed to release and unlock. Identity comes from the
 * Windows device instance (PCI\VEN_10DE&DEV_xxx&SUBSYS_yyyyyyyy) plus the
 * chip revision and usable FB size read back from the live card. */
static GU_MULTI_TARGET Targets[GU_MULTI_MAX_TARGETS] = {
  /* The console card goes first: its firmware driver still owns it, so the one
   * unproven step (release) runs before any other card is unlocked. A refusal
   * there leaves the machine untouched and the wrapper boots Windows. */
  {0x250410deU, 0x153610deU, 0xb76000a1U, 0x3000U, "GA106 RTX 3060 12GB 10de:1536", 0, 0, {0}, 0, 0, {0, 0, 0, 0, 0}, 0, 0, 0, 0, FALSE, FALSE, FALSE, FALSE},
  {0x248710deU, 0x40741458U, 0xb74000a1U, 0x3000U, "GA104 RTX 3060 12GB 1458:4074", 0, 0, {0}, 0, 0, {0, 0, 0, 0, 0}, 0, 0, 0, 0, FALSE, FALSE, FALSE, FALSE},
};

static EFI_GUID PciGuid = EFI_PCI_IO_PROTOCOL_GUID;
static EFI_SYSTEM_TABLE *Table;
static const char *Stage = "init";
/* Set immediately before the first firmware driver release. After this point a
 * failure has no in-session recovery: power off and boot Windows again. */
static BOOLEAN HardwareTouched;
static UINTN Completed;

static EFI_STATUS Step(EFI_STATUS Status) {
  if (EFI_ERROR(Status)) GuLog("step failed: stage=%s status=%#llx\n", Stage,
                               (unsigned long long)Status);
  return Status;
}

static VOID Halt(VOID) {
  Gu.retained = TRUE;
  /* The last write of a faulted run once landed in the report as garbage, so
   * publish the instruction twice with the storage given time to settle. */
  GuLogText("HALT: hardware was touched. Power off with the physical button.\n");
  Gu.bs->Stall(250000);
  GuLogText("STOP: multi-target unlock cannot prove cleanup. No reset, retry or Windows.\n"
            "POWER OFF with the physical button, then boot Windows normally (F8 -> Windows Boot Manager).\n");
  for (;;) Gu.bs->Stall(1000000);
}

static VOID HexDigest(const UINT8 Digest[32]) {
  static const char Digits[] = "0123456789abcdef";
  char Text[65];
  for (UINTN i = 0; i < 32; i++) {
    Text[i * 2] = Digits[Digest[i] >> 4];
    Text[i * 2 + 1] = Digits[Digest[i] & 15];
  }
  Text[64] = 0;
  GuLogText("prom sha256=");
  GuLogText(Text);
  GuLogText("\n");
}

/* Read the 256-byte config snapshot of the active target. */
static EFI_STATUS ReadConfig(UINT32 Config[64]) {
  for (UINTN i = 0; i < 64; i++) {
    if (EFI_ERROR(GuConfigRead(EfiPciIoWidthUint32, (UINT32)i * 4, &Config[i]))) {
      GuLog("PCI config read failed: offset=%#x\n", (unsigned)(i * 4));
      return EFI_DEVICE_ERROR;
    }
  }
  return EFI_SUCCESS;
}

/* Identity and structure only: decode state is deliberately excluded, because
 * firmware enumeration leaves memory decode off on cards it does not drive. */
static BOOLEAN IdentityOk(const UINT32 Config[64], const GU_MULTI_TARGET *Target) {
  return Config[0] == Target->Device && Config[0x2c / 4] == Target->Subsystem &&
         ((Config[2] >> 24) & 0xffU) == 0x03U &&
         ((Config[3] >> 16) & 0x7fU) == 0;
}

/* Defined below: the post-release comparison must ignore the command decode
 * bits that the release and its restore are allowed to change. */
static BOOLEAN ConfigSameExceptCommand(const UINT32 A[64], const UINT32 B[64]);

static EFI_STATUS ConfigAdmit(GU_MULTI_TARGET *Target, BOOLEAN Save) {
  UINT32 Config[64];
  GU_CAPS Caps;
  UINTN Segment, Bus, Device, Function;
  EFI_STATUS Status = Gu.pci->GetLocation(Gu.pci, &Segment, &Bus, &Device, &Function);
  if (EFI_ERROR(Status)) return Status;
  Status = ReadConfig(Config);
  if (EFI_ERROR(Status)) return Status;
  /* This board's firmware assigns BAR0 on every card but leaves memory decode
   * off on the ones it is not driving. Identity and structure are validated
   * first; only then is the MEMORY attribute granted, through the protocol so
   * the firmware's own attribute bookkeeping matches the Command register that
   * the transaction later compares. The bit is cleared again if the run stops
   * before any card is touched. */
  if (Save && !(Config[1] & 2U) && IdentityOk(Config, Target)) {
    UINT64 Supported = 0, Before = 0;
    if (!Gu.pci->Attributes) return EFI_UNSUPPORTED;
    Status = Gu.pci->Attributes(Gu.pci, EfiPciIoAttributeOperationSupported, 0, &Supported);
    if (EFI_ERROR(Status)) return Status;
    if (!(Supported & EFI_PCI_IO_ATTRIBUTE_MEMORY)) return EFI_UNSUPPORTED;
    Status = Gu.pci->Attributes(Gu.pci, EfiPciIoAttributeOperationGet, 0, &Before);
    if (EFI_ERROR(Status)) return Status;
    Status = Gu.pci->Attributes(Gu.pci, EfiPciIoAttributeOperationEnable,
                                EFI_PCI_IO_ATTRIBUTE_MEMORY, NULL);
    if (EFI_ERROR(Status)) return Status;
    Status = ReadConfig(Config);
    if (EFI_ERROR(Status)) return Status;
    if (!(Config[1] & 2U)) return EFI_DEVICE_ERROR;
    Target->DecodeEnabled = TRUE;
    GuLog("memory decode enabled: %s command=%#x attributes=%#llx supported=%#llx\n",
          Target->Name, (unsigned)(Config[1] & 0xffffU), (unsigned long long)Before,
          (unsigned long long)Supported);
  }
  /* A card that the firmware driver still owns is admitted here with bus
   * mastering on. The strict gate that forbids it runs again after the driver
   * is released, before any transaction can start. */
  UINT32 Gate[64];
  memcpy(Gate, Config, sizeof(Gate));
  if (Save && (Gate[1] & 4U)) {
    Gate[1] &= ~4U;
    GuLogText("bus master is on: firmware driver still owns this card; strict gate deferred to post-release\n");
  }
  BOOLEAN Checked = GuCheckConfigFor(Gate, Segment, Bus, Device, Function,
                                     Target->Device, Target->Subsystem, &Caps);
  /* Same admission shape as the single-target child: display class, revision
   * A1, BAR0 already assigned low, memory space on, bus master off, expansion
   * ROM off, FLR supported and not pending. */
  BOOLEAN Valid = Checked && (Config[2] >> 24) == 0x03U &&
                  (Config[2] & 0xffU) == 0xa1U &&
                  Config[0x10 / 4] != 0 && (Config[0x10 / 4] & 0xfU) == 0 &&
                  (Config[0x30 / 4] & 1U) == 0 &&
                  !(Config[(Caps.pcie + 8) / 4] & 0x00200000U);
  /* The first snapshot also carries the firmware driver's bus mastering, which
   * the release legitimately clears; only the decode bits may differ. */
  BOOLEAN Same = Save || ConfigSameExceptCommand(Config, Target->Config);
  GuLog("config: bdf=%zu:%zu:%zu.%zu checks=%u class=%#x rev=%#x bar0_low=%#x pm=%#x pcie=%#x msi=%#x msix=%#x same=%u\n",
        (size_t)Segment, (size_t)Bus, (size_t)Device, (size_t)Function, Checked,
        (unsigned)(Config[2] >> 24), (unsigned)(Config[2] & 0xffU), Config[0x10 / 4],
        (unsigned)Caps.pm, (unsigned)Caps.pcie, (unsigned)Caps.msi, (unsigned)Caps.msix,
        (unsigned)Same);
  if (!Valid) {
    GuLog("config gate: id_match=%u sub_match=%u class=%u header=%#x cmd=%#x status=%#x rom=%#x\n",
          (unsigned)(Config[0] == Target->Device),
          (unsigned)(Config[0x2c / 4] == Target->Subsystem),
          (unsigned)((Config[2] >> 24) & 0xffU),
          (unsigned)((Config[3] >> 16) & 0xffU),
          (unsigned)(Config[1] & 0xffffU), (unsigned)(Config[1] >> 16),
          Config[0x30 / 4]);
    for (UINTN i = 0; i < 64; i += 8)
      GuLog("cfg%03x: %08x %08x %08x %08x %08x %08x %08x %08x\n", (unsigned)(i * 4),
            Config[i], Config[i + 1], Config[i + 2], Config[i + 3], Config[i + 4],
            Config[i + 5], Config[i + 6], Config[i + 7]);
    return EFI_UNSUPPORTED;
  }
  if (!Same) {
    for (UINTN i = 0; i < 64; i++)
      if (Config[i] != Target->Config[i])
        GuLog("config drift: offset=%#x now=%08x was=%08x\n", (unsigned)(i * 4),
              Config[i], Target->Config[i]);
    return EFI_NOT_READY;
  }
  if (Save) memcpy(Target->Config, Config, sizeof(Config));
  Gu.pm_cap = Caps.pm;
  Gu.pcie_cap = Caps.pcie;
  Gu.pcie_version = Caps.pcie_version;
  Gu.msi_cap = Caps.msi;
  Gu.msix_cap = Caps.msix;
  Target->Caps = Caps;
  return EFI_SUCCESS;
}

static EFI_STATUS BarAdmit(GU_MULTI_TARGET *Target) {
  EFI_ACPI_ADDRESS_SPACE_DESCRIPTOR *Range = NULL;
  EFI_STATUS Status = Gu.pci->GetBarAttributes(Gu.pci, 0, NULL, (VOID **)&Range);
  if (EFI_ERROR(Status)) return Status;
  if (!Range) return EFI_DEVICE_ERROR;
  if (Range->Desc != ACPI_ADDRESS_SPACE_DESCRIPTOR || Range->Len != sizeof(*Range) - 3 ||
      Range->ResType != 0 || Range->AddrSpaceGranularity != 32 ||
      Range->AddrLen != GU_MULTI_BAR_BYTES || Range->AddrTranslationOffset ||
      (Range->AddrRangeMin & (GU_MULTI_BAR_BYTES - 1)) != 0 ||
      (Range->AddrRangeMax != 0x00ffffffULL &&
       Range->AddrRangeMax != (Range->AddrRangeMin + GU_MULTI_BAR_BYTES - 1)) ||
      ((UINT8 *)(Range + 1))[0] != ACPI_END_TAG_DESCRIPTOR) {
    GuLog("bar0 rejected: type=%u granularity=%llu min=%#llx max=%#llx length=%#llx translation=%#llx\n",
          (unsigned)Range->ResType, (unsigned long long)Range->AddrSpaceGranularity,
          (unsigned long long)Range->AddrRangeMin, (unsigned long long)Range->AddrRangeMax,
          (unsigned long long)Range->AddrLen, (unsigned long long)Range->AddrTranslationOffset);
    GuFree(Range);
    return EFI_UNSUPPORTED;
  }
  UINT8 *Raw = (UINT8 *)Range, Sum = 0;
  for (UINTN i = 0; i < sizeof(*Range) + 2; i++) Sum = (UINT8)(Sum + Raw[i]);
  if (Raw[sizeof(*Range) + 1] && Sum) {
    GuFree(Range);
    return EFI_COMPROMISED_DATA;
  }
  Target->BarBase = Range->AddrRangeMin;
  Target->BarSize = Range->AddrLen;
  Gu.bar_base = Target->BarBase;
  Gu.bar_size = Target->BarSize;
  GuFree(Range);
  GuLog("bar0: base=%#llx bytes=%#llx\n", (unsigned long long)Gu.bar_base,
        (unsigned long long)Gu.bar_size);
  return EFI_SUCCESS;
}

/* PROM identity is logged, not pinned: this machine has no capture to pin. */
static EFI_STATUS PromAdmit(const GU_MULTI_TARGET *Target) {
  VOID *Prom = GuAlloc(GU_MULTI_PROM_BYTES);
  if (!Prom) return EFI_OUT_OF_RESOURCES;
  GuCopyFromIo(Prom, (VOID *)(UINTN)(Gu.bar_base + GU_MULTI_PROM_OFFSET), GU_MULTI_PROM_BYTES);
  UINT8 Digest[32];
  GuSha256(Prom, GU_MULTI_PROM_BYTES, Digest);
  GuFree(Prom);
  if (Gu.fault) return EFI_DEVICE_ERROR;
  Gu.prom_verified = TRUE;
  GuLog("target %s prom present=1\n", Target->Name);
  HexDigest(Digest);
  return EFI_SUCCESS;
}

/* Cold, unbound card. Every value here is the transaction's own precondition;
 * mutating them would change the method, not the machine support. */
static EFI_STATUS ColdAdmit(const GU_MULTI_TARGET *Target) {
  Gu.profile_verified = FALSE;
  UINT32 Chip = GuRead32(0);
  struct gpu_unlock_gfw_sample Sample = {
    .config_ok = true,
    .plm = GuRead32(GU_GFW_PLM_OFFSET),
    .boot = GuRead32(GU_GFW_BOOT_OFFSET),
    .cpuctl = GuRead32(GU_GFW_CPUCTL_OFFSET),
  };
  UINT32 Hi = GuRead32(0x1fa828);
  UINT32 Plm = GuRead32(GU_FEAT_PLM_OFFSET);
  UINT32 Ss0 = GuRead32(GU_FEAT_SS0_OFFSET);
  UINT32 Ss1 = GuRead32(GU_FEAT_SS1_OFFSET);
  UINT32 Memory = GuRead32(0x1183a4);
  GuLog("cold: chip=%#x/%#x memory=%#x/%#x plm=%#x gfw=%#x/%#x/%#x WPR2_HI=%#x SS0=%#x SS1=%#x\n",
        Chip, Target->Chip, Memory, Target->Memory, Plm, Sample.plm, Sample.boot,
        Sample.cpuctl, Hi, Ss0, Ss1);
  if (Gu.fault) return EFI_DEVICE_ERROR;
  if (Chip != Target->Chip || Memory != Target->Memory || gpu_unlock_gfw_assess(&Sample) ||
      Sample.plm != 0x8b8f || Sample.boot != 0x3ff || Sample.cpuctl != 0x10 ||
      Hi != 0 || Plm != 0xffffff8f || !Gu.prom_verified) {
    GuLog("cold rejected: card is not in the expected cold, unbound state\n");
    return EFI_NOT_READY;
  }
  if (!GuLatchEntrySelectors(Ss0, Ss1)) {
    GuLog("cold rejected: entry selectors cannot be latched (SS0=%#x SS1=%#x)\n", Ss0, Ss1);
    return EFI_NOT_READY;
  }
  Gu.profile_verified = TRUE;
  GuLog("cold verified: %s SS0target=0x88888888 SS1target=0x8\n", Target->Name);
  return EFI_SUCCESS;
}

/* No independent display adapter is required: the console is expected to die
 * when this card's firmware driver stops. The transaction still needs a
 * display_ok value, and the only defensible value is "we own the card and are
 * about to hand off to Windows". */
static BOOLEAN MultiDisplayPolicy(VOID) {
  return Gu.owned && !Gu.fault;
}

/* Compare two 256-byte config snapshots, ignoring only the low three bits of
 * the Command register (IO decode, MEM decode, bus master). Everything else
 * must be byte-identical. */
static BOOLEAN ConfigSameExceptCommand(const UINT32 A[64], const UINT32 B[64]) {
  for (UINTN i = 0; i < 64; i++) {
    UINT32 X = A[i], Y = B[i];
    if (i == 1) {
      X &= ~7U;
      Y &= ~7U;
    }
    if (X != Y) return FALSE;
  }
  return TRUE;
}

/* Mirrors the single-target decode restore: a firmware driver's Stop may have
 * cleared the IO/MEM decode bits and bus mastering that it owned. Restore the
 * decode bits, keep bus mastering off, and refuse if anything else in the
 * 256-byte snapshot moved. */
static EFI_STATUS RestoreDecode(const GU_MULTI_TARGET *Target) {
  UINT32 Current[64], After[64];
  UINTN Segment, Bus, Device, Function;
  if (GU_PREFLIGHT_ONLY || !Gu.profile_verified || !Gu.pci || !Gu.owned || !Gu.armed ||
      Gu.started || Gu.allocations || Gu.fault || Gu.retained) return EFI_ACCESS_DENIED;
  EFI_STATUS Status = Gu.pci->GetLocation(Gu.pci, &Segment, &Bus, &Device, &Function);
  if (EFI_ERROR(Status)) return Status;
  Status = ReadConfig(Current);
  if (EFI_ERROR(Status)) return Status;
  if (!GuTargetConfigFor(Current, Segment, Bus, Device, Function, Target->Device,
                         Target->Subsystem)) return EFI_UNSUPPORTED;
  UINT32 Lost = Target->Config[1] & ~Current[1] & 7U;
  UINT32 Gained = Current[1] & ~Target->Config[1] & 7U;
  if (Gained || !ConfigSameExceptCommand(Current, Target->Config)) {
    GuLogText("decode restore refused: config differs beyond the command decode bits\n");
    return EFI_UNSUPPORTED;
  }
  UINT32 Missing = Lost & 3U;
  BOOLEAN BusMaster = (Current[1] & 4U) != 0;
  if (!Missing && !BusMaster) {
    GuLogText("decode restore not needed\n");
    return EFI_SUCCESS;
  }
  if (!Gu.pci->Attributes) return EFI_UNSUPPORTED;
  UINT64 Needed = (Missing & 1U ? EFI_PCI_IO_ATTRIBUTE_IO : 0) |
                  (Missing & 2U ? EFI_PCI_IO_ATTRIBUTE_MEMORY : 0);
  UINT64 Supported = 0, Attributes = 0;
  Status = Gu.pci->Attributes(Gu.pci, EfiPciIoAttributeOperationSupported, 0, &Supported);
  if (EFI_ERROR(Status)) return Status;
  if ((Supported & Needed) != Needed) return EFI_UNSUPPORTED;
  Status = Gu.pci->Attributes(Gu.pci, EfiPciIoAttributeOperationGet, 0, &Attributes);
  if (EFI_ERROR(Status)) return Status;
  GuLog("decode restore: missing=%#x bus_master=%u attributes=%#llx\n", Missing,
        (unsigned)BusMaster, (unsigned long long)Attributes);
  if (!GuLogReady() || Gu.fault) return EFI_DEVICE_ERROR;
  if (Needed) {
    /* Never EFI_PCI_DEVICE_ENABLE: that would also set bus mastering. */
    EFI_STATUS Enabled = Gu.pci->Attributes(Gu.pci, EfiPciIoAttributeOperationEnable, Needed, NULL);
    if (EFI_ERROR(Enabled)) return Enabled;
    if (!GuLogReady() || Gu.fault) return EFI_DEVICE_ERROR;
  }
  if (BusMaster) {
    /* A Stop that leaves bus mastering on must not reach the transaction. */
    GuLogText("bus master still enabled after driver release: clearing it\n");
    Status = Gu.pci->Attributes(Gu.pci, EfiPciIoAttributeOperationDisable,
                                EFI_PCI_IO_ATTRIBUTE_BUS_MASTER, NULL);
    if (EFI_ERROR(Status)) return Status;
    if (!GuLogReady() || Gu.fault) return EFI_DEVICE_ERROR;
  }
  Status = ReadConfig(After);
  if (EFI_ERROR(Status)) return Status;
  BOOLEAN Matched = ConfigSameExceptCommand(After, Target->Config) &&
                    (After[1] & Missing) == Missing && !(After[1] & 4U);
  GuLog("decode readback matched=%u command=%#x\n", Matched, (unsigned)(After[1] & 0xffffU));
  if (!GuLogReady() || Gu.fault) return EFI_DEVICE_ERROR;
  return Matched ? EFI_SUCCESS : EFI_COMPROMISED_DATA;
}

/* A normal handoff leaves the console card as the owner of the legacy VGA
 * decode: the firmware driver is still bound when Windows Boot Manager draws
 * its own screen, and the boot video keeps using 0xA0000-0xBFFFF and the 3B0/
 * 3C0 ports until ExitBootServices.
 *
 * We stop that driver early, so the decode is released and Windows cannot place
 * the legacy ranges for the card it still treats as the VGA device; RUN08 ended
 * with both cards unlocked but the console card refused by Windows with
 * CM_PROB_NORMAL_CONFLICT (0xC0000018, conflicting addresses), missing exactly
 * the VGA memory and I/O ranges it gets on a normal boot.
 *
 * Re-acquire the decode through the protocol (never by poking the bridge), so
 * the firmware's own VGA arbitration state is the one Windows inherits. This
 * runs after the transaction: failure is logged, not fatal, because the card
 * itself is unlocked and a wrong decode must not cost the run. */
static VOID RestoreVgaDecode(const GU_MULTI_TARGET *Target) {
  /* The 10-bit and the 16-bit decode requests are mutually exclusive by design:
   * PciBusDxe returns EFI_UNSUPPORTED when one call carries both, which is what
   * RUN09 hit with want=0x60018. Never ask for the palette snoop bits either -
   * they belong to the agent that does not decode, and enabling them on the
   * decoder walks into SupportPaletteSnoopAttributes and can fail for reasons
   * that have nothing to do with this card. */
  const UINT64 Legacy = EFI_PCI_IO_ATTRIBUTE_VGA_MEMORY | EFI_PCI_IO_ATTRIBUTE_VGA_IO;
  const UINT64 Legacy16 = EFI_PCI_IO_ATTRIBUTE_VGA_IO_16 | EFI_PCI_IO_ATTRIBUTE_VGA_MEMORY;
  UINT64 Supported = 0, Before = 0, After = 0;
  UINT32 Config[64];
  if (!Gu.pci || !Gu.pci->Attributes) {
    GuLogText("vga decode: no attributes interface\n");
    return;
  }
  EFI_STATUS Status = Gu.pci->Attributes(Gu.pci, EfiPciIoAttributeOperationSupported, 0, &Supported);
  if (EFI_ERROR(Status)) {
    GuLog("vga decode: supported read failed=%#llx\n", (unsigned long long)Status);
    return;
  }
  Status = Gu.pci->Attributes(Gu.pci, EfiPciIoAttributeOperationGet, 0, &Before);
  if (EFI_ERROR(Status)) {
    GuLog("vga decode: attributes read failed=%#llx\n", (unsigned long long)Status);
    return;
  }
  const UINT64 Eligible = Supported & (Legacy | Legacy16);
  GuLog("vga decode: card=%s supported=%#llx before=%#llx legacy=%#llx legacy16=%#llx\n",
        Target->Name, (unsigned long long)Supported, (unsigned long long)Before,
        (unsigned long long)(Supported & Legacy), (unsigned long long)(Supported & Legacy16));
  if (!Eligible) {
    GuLogText("vga decode: firmware does not offer legacy decode\n");
    return;
  }
  /* Classic 10-bit decode first: that is the state a normal boot leaves, and it
   * is what the legacy 0xA0000 window and the 3B0/3C0 ports need. Only if the
   * firmware does not expose it do we ask for the 16-bit variant. */
  UINT64 Attempts[2] = {Legacy, Legacy16};
  UINT64 Asked = 0;
  for (UINTN i = 0; i < 2; i++) {
    UINT64 Want = Supported & Attempts[i];
    if (!Want) continue;
    Asked = Want;
    if ((Before & Want) == Want) {
      GuLog("vga decode: variant %u already enabled want=%#llx\n", (unsigned)i,
            (unsigned long long)Want);
      break;
    }
    Status = Gu.pci->Attributes(Gu.pci, EfiPciIoAttributeOperationEnable, Want, NULL);
    GuLog("vga decode: variant %u want=%#llx enable=%#llx\n", (unsigned)i,
          (unsigned long long)Want, (unsigned long long)Status);
    if (!EFI_ERROR(Status)) break;
  }
  Status = Gu.pci->Attributes(Gu.pci, EfiPciIoAttributeOperationGet, 0, &After);
  if (!EFI_ERROR(Status) && !EFI_ERROR(ReadConfig(Config)))
    GuLog("vga decode: after=%#llx command=%#x asked=%#llx matched=%u\n",
          (unsigned long long)After, (unsigned)(Config[1] & 0xffffU),
          (unsigned long long)Asked, (unsigned)(Asked && (After & Asked) == Asked));
}

static EFI_STATUS Discover(VOID) {
  EFI_HANDLE *Handles = NULL;
  UINTN Count = 0, Nvidia = 0;
  EFI_STATUS Status = Gu.bs->LocateHandleBuffer(ByProtocol, &PciGuid, NULL, &Count, &Handles);
  GuLog("pci enumeration: status=%#llx handles=%zu\n", (unsigned long long)Status, (size_t)Count);
  if (EFI_ERROR(Status) || !Handles || !Count || Count > 256) {
    if (Handles) GuFree(Handles);
    return EFI_NOT_FOUND;
  }
  for (UINTN i = 0; i < Count; i++) {
    EFI_PCI_IO_PROTOCOL *Pci = NULL;
    UINT32 Id = 0, Class = 0, Subsystem = 0;
    if (EFI_ERROR(Gu.bs->HandleProtocol(Handles[i], &PciGuid, (VOID **)&Pci)) || !Pci) continue;
    if (EFI_ERROR(Pci->Pci.Read(Pci, EfiPciIoWidthUint32, 0, 1, &Id)) ||
        EFI_ERROR(Pci->Pci.Read(Pci, EfiPciIoWidthUint32, 8, 1, &Class)) ||
        EFI_ERROR(Pci->Pci.Read(Pci, EfiPciIoWidthUint32, 0x2c, 1, &Subsystem))) {
      GuFree(Handles);
      return EFI_DEVICE_ERROR;
    }
    if ((Id & 0xffffU) != 0x10deU || (Class >> 24) != 0x03U) continue;
    Nvidia++;
    UINTN Segment = 0, Bus = 0, Device = 0, Function = 0;
    Status = Pci->GetLocation(Pci, &Segment, &Bus, &Device, &Function);
    GuLog("nvidia display controller: id=%#x subsys=%#x bdf=%zu:%zu:%zu.%zu status=%#llx\n",
          Id, Subsystem, (size_t)Segment, (size_t)Bus, (size_t)Device, (size_t)Function,
          (unsigned long long)Status);
    if (EFI_ERROR(Status) || Segment != 0 || Device != 0 || Function != 0 || !Bus) continue;
    for (UINTN t = 0; t < GU_MULTI_MAX_TARGETS; t++) {
      if (Targets[t].Device != Id || Targets[t].Subsystem != Subsystem) continue;
      if (Targets[t].Present) {
        GuLog("ambiguous target: two controllers match %s\n", Targets[t].Name);
        GuFree(Handles);
        return EFI_COMPROMISED_DATA;
      }
      Targets[t].Present = TRUE;
      Targets[t].Handle = Handles[i];
      Targets[t].Pci = Pci;
      Targets[t].Segment = Segment;
      Targets[t].Bus = Bus;
      Targets[t].DeviceNumber = Device;
      Targets[t].Function = Function;
    }
  }
  GuFree(Handles);
  GuLog("nvidia display controllers=%zu targets=%u\n", (size_t)Nvidia,
        (unsigned)GU_MULTI_MAX_TARGETS);
  if (Nvidia > GU_MULTI_MAX_NVIDIA) return EFI_UNSUPPORTED;
  for (UINTN t = 0; t < GU_MULTI_MAX_TARGETS; t++) {
    if (!Targets[t].Present) {
      GuLog("missing target: %s (device %#x subsystem %#x)\n", Targets[t].Name,
            Targets[t].Device, Targets[t].Subsystem);
      return EFI_NOT_FOUND;
    }
  }
  return EFI_SUCCESS;
}

static EFI_STATUS RunTarget(GU_MULTI_TARGET *Target, const struct gpu_unlock_610_shared *Shared) {
  EFI_STATUS Status;
  GuMultiSelectTarget(Target->Device, Target->Subsystem, Target->Bus);
  Gu.handle = Target->Handle;
  Gu.pci = Target->Pci;
  Gu.profile_verified = FALSE;
  Gu.prom_verified = FALSE;
  GuLog("TARGET %s bus=%zu\n", Target->Name, Target->Bus);

  Stage = "config";
  Status = Step(ConfigAdmit(Target, TRUE));
  if (EFI_ERROR(Status)) return Status;
  Stage = "bar0";
  Status = Step(BarAdmit(Target));
  if (EFI_ERROR(Status)) return Status;
  Stage = "prom";
  Status = Step(PromAdmit(Target));
  if (EFI_ERROR(Status)) return Status;
  Stage = "cold";
  Status = Step(ColdAdmit(Target));
  if (EFI_ERROR(Status)) return Status;

  Stage = "claim";
  Status = GuClaimController();
  if (Status == EFI_ACCESS_DENIED) {
    GU_RELEASE_OWNER Owner;
    GuLogText("card is bound to a firmware driver; taking the single release path\n");
    Status = GuFindReleaseOwner(Table, &Owner, TRUE);
    if (EFI_ERROR(Status)) return Status;
    /* Second, unlogged snapshot: the agent that is actually stopped must be the
     * one whose direct-open records were just validated. No file I/O between
     * this comparison and DisconnectController. */
    GU_RELEASE_OWNER Current;
    Status = GuFindReleaseOwner(Table, &Current, FALSE);
    if (!EFI_ERROR(Status) && !GuSameReleaseOwner(&Owner, &Current)) Status = EFI_ABORTED;
    if (EFI_ERROR(Status)) return Status;
    Stage = "release";
    /* File-only from here: the console GOP may be the driver we are stopping. */
    GuConsoleOff();
    HardwareTouched = TRUE;
    Target->Released = TRUE;
    EFI_PCI_IO_PROTOCOL *Prior = Gu.pci;
    Gu.armed = TRUE;
    Gu.pci = NULL;
    EFI_STATUS Released = Gu.bs->DisconnectController(Gu.handle, Owner.agent, NULL);
    EFI_TPL Old = Gu.bs->RaiseTPL(TPL_NOTIFY);
    EFI_STATUS Refreshed = GuRefreshTargetPci();
    Gu.bs->RestoreTPL(Old);
    GuLog("driver release: status=%#llx refresh=%#llx same_pci=%u\n",
          (unsigned long long)Released, (unsigned long long)Refreshed,
          (unsigned)(Gu.pci == Prior));
    Status = Step(EFI_ERROR(Released) ? Released : EFI_ERROR(Refreshed) ? Refreshed
                  : Gu.pci != Prior ? EFI_COMPROMISED_DATA : EFI_SUCCESS);
    if (EFI_ERROR(Status)) return Status;
    /* The Stop is only trusted once the open records prove nobody holds the
     * card any more; the claim that follows is the second, independent check. */
    Stage = "release-verify";
    Status = Step(GuVerifyNoDriverOwns());
    if (EFI_ERROR(Status)) return Status;
    Stage = "claim-after-release";
    Status = Step(GuClaimController());
    if (EFI_ERROR(Status)) return Status;
  } else if (EFI_ERROR(Status)) {
    return Status;
  }

  /* Only a card whose firmware driver was actually stopped can have had its
   * IO/MEM decode bits cleared. An unbound card keeps the snapshot it was
   * admitted with, and ConfigAdmit(FALSE) proves it did not move. */
  if (Target->Released) {
    Stage = "decode-after-release";
    Status = Step(RestoreDecode(Target));
    if (EFI_ERROR(Status)) return Status;
  }
  Stage = "config-after-release";
  Status = Step(ConfigAdmit(Target, FALSE));
  if (EFI_ERROR(Status)) return Status;
  Stage = "bar0-after-release";
  Status = Step(BarAdmit(Target));
  if (EFI_ERROR(Status)) return Status;
  Stage = "prom-after-release";
  Status = Step(PromAdmit(Target));
  if (EFI_ERROR(Status)) return Status;
  Stage = "cold-after-release";
  Status = Step(ColdAdmit(Target));
  if (EFI_ERROR(Status)) return Status;

  Stage = "transaction";
  GuLogText("ARMED: one transaction for this card; no retry.\n");
  if (!GuLogReady() || Gu.fault) return EFI_DEVICE_ERROR;
  Gu.display_ok = TRUE;
  Gu.armed = TRUE;
  HardwareTouched = TRUE;
  UINT64 Mask = 0xffffffffULL;
  struct pci_dev Device = {
    .dev = {.dma_mask = &Mask, .coherent_dma_mask = 0xffffffffULL},
    .pm_cap = Gu.pm_cap,
    .refs = 1,
  };
  int Result = gpu_unlock_610_unlock(&Device, Shared);
  EFI_STATUS Contained = GuClearMaster();
  GuLog("transaction: result=%d containment=%#llx started=%u quiesced=%u fault=%u retained=%u maps=%u FLR=%u\n",
        Result, (unsigned long long)Contained, Gu.started, Gu.quiesced, Gu.fault,
        Gu.retained, Gu.dma_count, Gu.flrs);
  Gu.armed = FALSE;
  if (EFI_ERROR(Contained) || !GuSafeToReturn() || Gu.allocations ||
      (Gu.started && Result)) {
    Halt();
  }
  if (Result) return EFI_DEVICE_ERROR;

  Stage = "post-state";
  UINT32 Chip = GuRead32(0);
  UINT32 Memory = GuRead32(0x1183a4);
  UINT32 Ss0 = GuRead32(0x82381c);
  UINT32 Ss1 = GuRead32(0x823820);
  GuLog("post-state: chip=%#x memory=%#x SS0=%#x SS1=%#x fault=%u\n", Chip, Memory, Ss0, Ss1,
        Gu.fault);
  if (Gu.fault || Chip != Target->Chip || Memory != Target->Memory ||
      Ss0 != 0x88888888U || Ss1 != 0x8U) {
    GuLogText("post-state mismatch: the card is not provably unlocked\n");
    Halt();
  }

  /* Give the legacy VGA decode back before the card leaves our hands. A normal
   * boot still has the firmware driver bound at this point, so Windows inherits
   * a console card that owns it. Failure here is logged only: the card is
   * already unlocked and must not be lost to a cosmetic handback. */
  if (Target->Released) RestoreVgaDecode(Target);

  Stage = "handback";
  EFI_STATUS Closed = Gu.bs->CloseProtocol(Gu.handle, &PciGuid, Gu.image, NULL);
  if (EFI_ERROR(Closed)) {
    GuLog("handback failed: status=%#llx\n", (unsigned long long)Closed);
    Halt();
  }
  Gu.owned = FALSE;
  Gu.profile_verified = FALSE;
  Gu.prom_verified = FALSE;
  Gu.display_ok = FALSE;
  GuMultiResetTransaction();
  Target->Done = TRUE;
  Completed++;
  GuLog("target done: %s (%u/%u)\n", Target->Name, (unsigned)Completed,
        (unsigned)GU_MULTI_MAX_TARGETS);
  return EFI_SUCCESS;
}

/* Leave an untouched machine as found: clear only the MEMORY decode bit this
 * run granted. Never runs after a driver release or any other hardware change. */
static VOID RestoreDecodeBits(VOID) {
  for (UINTN t = 0; t < GU_MULTI_MAX_TARGETS; t++) {
    GU_MULTI_TARGET *T = &Targets[t];
    UINT16 Command = 0;
    if (!T->DecodeEnabled || !T->Pci || Gu.fault || Gu.retained) continue;
    if (EFI_ERROR(T->Pci->Pci.Read(T->Pci, EfiPciIoWidthUint16, 4, 1, &Command)) ||
        !(Command & 2U))
      continue;
    UINT16 Disabled = (UINT16)(Command & ~2U);
    EFI_STATUS Status = T->Pci->Pci.Write(T->Pci, EfiPciIoWidthUint16, 4, 1, &Disabled);
    GuLog("decode restore: %s command=%#x -> %#x status=%#llx\n", T->Name,
          (unsigned)Command, (unsigned)Disabled, (unsigned long long)Status);
  }
}

/* Secure Boot is only a hazard when the platform enforces it. This board (AMI
 * Aptio V, X99) does not publish the SecureBoot variable at all, so
 * EFI_NOT_FOUND means "no Secure Boot implementation" and is logged instead of
 * aborting: an enforcing firmware would never have started these unsigned
 * images. A present variable that reports enabled is still a hard stop. */
static EFI_STATUS SecureBootGate(VOID) {
  EFI_GUID Guid = EFI_GLOBAL_VARIABLE;
  UINT32 Attrs = 0, SetupAttrs = 0;
  UINTN Size = 1, SetupSize = 1;
  UINT8 Secure = 0xff, Setup = 0xff;
  EFI_STATUS Status = Table->RuntimeServices->GetVariable(L"SecureBoot", &Guid,
                                                          &Attrs, &Size, &Secure);
  if (!EFI_ERROR(Status))
    (VOID)Table->RuntimeServices->GetVariable(L"SetupMode", &Guid, &SetupAttrs,
                                              &SetupSize, &Setup);
  GuLog("secure-boot: status=%#llx size=%u value=%u setup=%u\n",
        (unsigned long long)Status, (unsigned)Size, (unsigned)Secure,
        (unsigned)Setup);
  if (Status == EFI_NOT_FOUND) {
    GuLogText("secure-boot: variable absent; platform does not implement Secure Boot.\n");
    return EFI_SUCCESS;
  }
  if (EFI_ERROR(Status) || Size != 1 || Secure != 0) return EFI_SECURITY_VIOLATION;
  return EFI_SUCCESS;
}

EFI_STATUS EFIAPI efi_main(EFI_HANDLE Image, EFI_SYSTEM_TABLE *St) {
  if (!St || !St->BootServices || !St->RuntimeServices) return EFI_INVALID_PARAMETER;
  Table = St;
  GuInit(St->BootServices, NULL);
  Gu.image = Image;
  Gu.display_check = MultiDisplayPolicy;
  Stage = "usb-log";
  EFI_STATUS Status = GuIoOpen(Image, St);
  if (EFI_ERROR(Status)) return Status;
  GuLog("BUILD MODE: MULTI-TARGET RUNTIME UNLOCK; %u cards, one transaction each, no retry.\n",
        (unsigned)GU_MULTI_MAX_TARGETS);
  GuLog("Profile placeholders are never used for identity; each card is admitted at boot.\n");

  Stage = "secure-boot";
  Status = SecureBootGate();
  if (EFI_ERROR(Status)) goto finish;
  Stage = "watchdog";
  Status = Step(Gu.bs->SetWatchdogTimer(0, 0, 0, NULL));
  if (EFI_ERROR(Status)) goto finish;
  Stage = "discover";
  Status = Step(Discover());
  if (EFI_ERROR(Status)) goto finish;
  Stage = "assets";
  Status = Step(GuLoadAssets());
  if (EFI_ERROR(Status)) goto finish;

  Stage = "shared-firmware";
  UINT64 Mask = 0xffffffffULL;
  struct pci_dev First = {
    .dev = {.dma_mask = &Mask, .coherent_dma_mask = 0xffffffffULL},
    .pm_cap = Gu.pm_cap,
    .refs = 1,
  };
  struct gpu_unlock_610_shared Shared = {0};
  int Loaded = gpu_unlock_610_load_shared(&First, &Shared);
  if (Loaded) {
    GuLog("shared firmware load failed: result=%d\n", Loaded);
    Status = EFI_DEVICE_ERROR;
    goto finish;
  }
  GuLogText("shared firmware loaded once; both cards will reuse it.\n");

  for (UINTN t = 0; t < GU_MULTI_MAX_TARGETS; t++) {
    Status = RunTarget(&Targets[t], &Shared);
    if (EFI_ERROR(Status)) break;
  }
  if (!EFI_ERROR(Status)) Stage = "done";
  gpu_unlock_610_release_shared(&Shared);

finish:
  Gu.armed = FALSE;
  if (!HardwareTouched) RestoreDecodeBits();
  if (EFI_ERROR(Status)) {
    GuLog("FINAL status=%#llx stage=%s completed=%u hardware=%s\n",
          (unsigned long long)Status, Stage, (unsigned)Completed,
          HardwareTouched ? "touched" : "untouched");
    /* Any hardware change forbids a second attempt in this power session. */
    if (HardwareTouched || Gu.started || Gu.retained || Gu.fault) Halt();
    if (GuLogReady()) GuLogText("No card was changed; returning to the wrapper for a normal Windows boot.\n");
  } else {
    GuLog("FINAL status=%#llx stage=%s completed=%u hardware=touched ALL TARGETS UNLOCKED\n",
          (unsigned long long)Status, Stage, (unsigned)Completed);
  }
  if (Gu.owned) {
    EFI_STATUS Closed = Gu.bs->CloseProtocol(Gu.handle, &PciGuid, Image, NULL);
    if (EFI_ERROR(Closed)) Status = Closed;
    else Gu.owned = FALSE;
  }
  GuReleaseAssets();
  EFI_STATUS Io = GuIoClose();
  if (EFI_ERROR(Io) && !EFI_ERROR(Status)) Status = Io;
  return Status;
}
