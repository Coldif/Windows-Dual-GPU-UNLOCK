/* GPL-2.0-only. Multi-target wrapper: USB stick -> UNLOCK-MULTI.EFI -> Windows.
 *
 * The wrapper owns the parts the child must not do around a driver release:
 * it identifies the stick and the Windows ESP, opens one log, loads the child
 * image from verified bytes, offers one Esc window before anything is touched,
 * and starts Windows in the same power session once the child returns success.
 *
 * It never prints after the child has run: the child may have stopped the
 * console GOP that this image's ConOut still points at.
 */
#include <Uefi.h>
#include <Protocol/LoadedImage.h>
#include <Protocol/SimpleFileSystem.h>
#include <Guid/FileInfo.h>
#include "media.h"
#include "log-config.h"
#include "../unlock/sha256.h"
#include "build/multi/child-contract.h"

#ifndef GU_CHILD_BYTES
#error Build with a generated build/multi/child-contract.h from the built child image
#endif
#ifndef GU_CHILD_SHA256
#error Build with a generated build/multi/child-contract.h from the built child image
#endif

static EFI_GUID LoadedGuid = EFI_LOADED_IMAGE_PROTOCOL_GUID;
static EFI_GUID FsGuid = EFI_SIMPLE_FILE_SYSTEM_PROTOCOL_GUID;
static EFI_GUID PathGuid = EFI_DEVICE_PATH_PROTOCOL_GUID;
static EFI_GUID InfoGuid = EFI_FILE_INFO_ID;

static EFI_SYSTEM_TABLE *Table;
static EFI_HANDLE Self, OwnDevice, WindowsImage, ChildImage;
static EFI_FILE_PROTOCOL *Root, *Log;
/* CONFIG.TXT on the stick decides whether this boot leaves any file behind.
 * The child reads the same file, so both halves agree; nothing else changes. */
static BOOLEAN LogEnabled = TRUE;

static VOID Say(const CHAR16 *Text) {
  if (Table && Table->ConOut) Table->ConOut->OutputString(Table->ConOut, (CHAR16 *)Text);
}

static VOID Stop(VOID) {
  Say(L"\r\nMULTI UNLOCK STOPPED. No reset and no retry.\r\n"
      L"Power off with the physical button, then boot Windows (F8 -> Windows Boot Manager).\r\n");
  if (Table && Table->BootServices) Table->BootServices->SetWatchdogTimer(0, 0, 0, NULL);
  for (;;) __asm__ volatile("pause");
}

/* This image is compiled position-independently apart from one absolute
 * pointer. Keeping it (a volatile load the compiler cannot fold away) gives the
 * loader a real fixup to apply, so the image is genuinely relocatable at any
 * firmware-chosen base — the property the PE gate checks — instead of relying
 * on a zero-fixup image being loadable only by accident. */
static VOID (*volatile RelocationAnchor)(const CHAR16 *) = Say;

static EFI_STATUS PathFor(EFI_HANDLE Device, EFI_DEVICE_PATH_PROTOCOL **Out) {
  *Out = NULL;
  EFI_STATUS Status = Table->BootServices->HandleProtocol(Device, &PathGuid, (VOID **)Out);
  return Status == EFI_SUCCESS && *Out ? EFI_SUCCESS : EFI_UNSUPPORTED;
}

/* Append one file-path node to a firmware-provided device path. */
static EFI_STATUS FilePath(EFI_HANDLE Device, const CHAR16 *Name, EFI_DEVICE_PATH_PROTOCOL **Out) {
  EFI_DEVICE_PATH_PROTOCOL *Base = NULL;
  UINTN BaseBytes = 0, Chars = 0;
  *Out = NULL;
  EFI_STATUS Status = PathFor(Device, &Base);
  if (Status != EFI_SUCCESS || !GuInspectPath(Base, NULL, &BaseBytes, NULL, NULL))
    return EFI_UNSUPPORTED;
  while (Name[Chars] && Chars < 256) Chars++;
  if (!Chars || Chars == 256) return EFI_INVALID_PARAMETER;
  UINTN NodeBytes = 4 + (Chars + 1) * sizeof(CHAR16), Total = BaseBytes - 4 + NodeBytes + 4;
  UINT8 *Data = NULL;
  Status = Table->BootServices->AllocatePool(EfiBootServicesData, Total, (VOID **)&Data);
  if (Status != EFI_SUCCESS || !Data) return EFI_OUT_OF_RESOURCES;
  for (UINTN i = 0; i < BaseBytes - 4; i++) Data[i] = ((UINT8 *)Base)[i];
  EFI_DEVICE_PATH_PROTOCOL *Node = (VOID *)(Data + BaseBytes - 4);
  Node->Type = MEDIA_DEVICE_PATH;
  Node->SubType = MEDIA_FILEPATH_DP;
  Node->Length[0] = (UINT8)NodeBytes;
  Node->Length[1] = (UINT8)(NodeBytes >> 8);
  for (UINTN i = 0; i < (Chars + 1) * sizeof(CHAR16); i++)
    ((UINT8 *)Node)[4 + i] = ((const UINT8 *)Name)[i];
  EFI_DEVICE_PATH_PROTOCOL *End = (VOID *)((UINT8 *)Node + NodeBytes);
  End->Type = END_DEVICE_PATH_TYPE;
  End->SubType = END_ENTIRE_DEVICE_PATH_SUBTYPE;
  End->Length[0] = 4;
  End->Length[1] = 0;
  *Out = (VOID *)Data;
  return EFI_SUCCESS;
}

static EFI_STATUS FindPartition(const EFI_GUID *Guid, EFI_HANDLE *Out) {
  EFI_HANDLE *Handles = NULL;
  UINTN Count = 0, Matches = 0;
  *Out = NULL;
  EFI_STATUS Status = Table->BootServices->LocateHandleBuffer(ByProtocol, &FsGuid, NULL, &Count, &Handles);
  if (Status != EFI_SUCCESS) return Status;
  for (UINTN i = 0; i < Count; i++) {
    EFI_DEVICE_PATH_PROTOCOL *Path = NULL;
    if (PathFor(Handles[i], &Path) == EFI_SUCCESS && GuPathIsPartition(Path, Guid)) {
      Matches++;
      *Out = Handles[i];
    }
  }
  if (Handles) Table->BootServices->FreePool(Handles);
  return Matches == 1 ? EFI_SUCCESS : Matches ? EFI_COMPROMISED_DATA : EFI_NOT_FOUND;
}

static EFI_STATUS OpenVolume(VOID) {
  EFI_SIMPLE_FILE_SYSTEM_PROTOCOL *Fs = NULL;
  EFI_STATUS Status = Table->BootServices->HandleProtocol(OwnDevice, &FsGuid, (VOID **)&Fs);
  if (Status != EFI_SUCCESS || !Fs) return EFI_UNSUPPORTED;
  Status = Fs->OpenVolume(Fs, &Root);
  return Status == EFI_SUCCESS && Root ? EFI_SUCCESS : EFI_DEVICE_ERROR;
}

static EFI_STATUS OpenLog(VOID) {
  if (!Root) return EFI_DEVICE_ERROR;
  for (UINTN i = 0; i < 100; i++) {
    CHAR16 Name[] = L"\\RTX3090-UNLOCK\\MBT00.TXT";
    Name[18] = (CHAR16)('0' + i / 10);
    Name[19] = (CHAR16)('0' + i % 10);
    EFI_FILE_PROTOCOL *Existing = NULL;
    EFI_STATUS Status = Root->Open(Root, &Existing, Name, EFI_FILE_MODE_READ, 0);
    if (Status == EFI_SUCCESS) {
      if (Existing) Existing->Close(Existing);
      continue;
    }
    if (Status != EFI_NOT_FOUND) return Status;
    Status = Root->Open(Root, &Log, Name, EFI_FILE_MODE_READ | EFI_FILE_MODE_WRITE | EFI_FILE_MODE_CREATE, 0);
    return Status == EFI_SUCCESS && Log ? EFI_SUCCESS : EFI_DEVICE_ERROR;
  }
  return EFI_VOLUME_FULL;
}

static EFI_STATUS Record(const char *Event, EFI_STATUS Status) {
  if (!Log) return EFI_SUCCESS;
  char Text[160];
  UINTN n = 0;
  while (*Event && n < 100) Text[n++] = *Event++;
  const char *Label = " status=0x";
  while (*Label) Text[n++] = *Label++;
  for (int i = 15; i >= 0; i--) Text[n++] = "0123456789abcdef"[((UINT64)Status >> (i * 4)) & 15];
  Text[n++] = '\r';
  Text[n++] = '\n';
  UINTN Written = n;
  EFI_STATUS Result = Log->Write(Log, &Written, Text);
  if (Result != EFI_SUCCESS || Written != n) return EFI_DEVICE_ERROR;
  return Log->Flush(Log);
}

/* Load one file from the stick, verify its exact size and hash, then execute
 * those same bytes (no re-open between verification and LoadImage). */
static EFI_STATUS LoadChild(VOID) {
  EFI_FILE_PROTOCOL *File = NULL;
  EFI_STATUS Status = Root->Open(Root, &File, L"\\EFI\\WindowsGPUUnlock\\UNLOCK-MULTI.EFI",
                                EFI_FILE_MODE_READ, 0);
  if (Status != EFI_SUCCESS || !File) return EFI_NOT_FOUND;
  union { EFI_FILE_INFO Info; UINT8 Bytes[512]; } Metadata;
  UINTN Bytes = sizeof(Metadata);
  Status = File->GetInfo(File, &InfoGuid, &Bytes, &Metadata);
  UINT8 *Data = NULL;
  if (Status == EFI_SUCCESS &&
      (Bytes < sizeof(EFI_FILE_INFO) || Bytes > sizeof(Metadata) ||
       Metadata.Info.Size < sizeof(EFI_FILE_INFO) || Metadata.Info.Size > Bytes ||
       Metadata.Info.FileSize != GU_CHILD_BYTES || (Metadata.Info.Attribute & EFI_FILE_DIRECTORY)))
    Status = EFI_BAD_BUFFER_SIZE;
  if (Status == EFI_SUCCESS)
    Status = Table->BootServices->AllocatePool(EfiBootServicesData, GU_CHILD_BYTES, (VOID **)&Data);
  if (Status == EFI_SUCCESS && !Data) Status = EFI_OUT_OF_RESOURCES;
  if (Status == EFI_SUCCESS) {
    Bytes = GU_CHILD_BYTES;
    Status = File->Read(File, &Bytes, Data);
    if (Status == EFI_SUCCESS && Bytes != GU_CHILD_BYTES) Status = EFI_END_OF_FILE;
  }
  EFI_STATUS Closed = File->Close(File);
  if (Status == EFI_SUCCESS) Status = Closed;
  if (Status == EFI_SUCCESS && !GuHashMatches(Data, GU_CHILD_BYTES, GU_CHILD_SHA256))
    Status = EFI_CRC_ERROR;
  EFI_DEVICE_PATH_PROTOCOL *Path = NULL;
  if (Status == EFI_SUCCESS)
    Status = FilePath(OwnDevice, L"\\EFI\\WindowsGPUUnlock\\UNLOCK-MULTI.EFI", &Path);
  if (Status == EFI_SUCCESS)
    Status = Table->BootServices->LoadImage(FALSE, Self, Path, Data, GU_CHILD_BYTES, &ChildImage);
  if (Path) Table->BootServices->FreePool(Path);
  if (Data) Table->BootServices->FreePool(Data);
  if (Status != EFI_SUCCESS) return Status;
  EFI_LOADED_IMAGE_PROTOCOL *Loaded = NULL;
  Status = Table->BootServices->HandleProtocol(ChildImage, &LoadedGuid, (VOID **)&Loaded);
  if (Status != EFI_SUCCESS || !Loaded || Loaded->DeviceHandle != OwnDevice)
    return EFI_COMPROMISED_DATA;
  return EFI_SUCCESS;
}

static EFI_STATUS Choose(BOOLEAN *Skip) {
  *Skip = FALSE;
  /* No keyboard in the firmware console is not a reason to refuse to boot:
   * warn, wait, and run the unlock as if the window had expired. */
  if (!Table->ConIn || !Table->ConIn->ReadKeyStroke || !Table->ConIn->Reset) {
    Say(L"WINDOWS GPU UNLOCK: no firmware keyboard; Esc window unavailable.\r\n"
        L"Unlocking both cards in 5 seconds.\r\n");
    return Table->BootServices->Stall(5000000);
  }
  EFI_STATUS Status = Table->ConIn->Reset(Table->ConIn, FALSE);
  if (Status != EFI_SUCCESS) {
    Say(L"WINDOWS GPU UNLOCK: keyboard reset failed; Esc window unavailable.\r\n");
    return Table->BootServices->Stall(5000000);
  }
  Say(L"WINDOWS GPU UNLOCK: MULTI-TARGET, ONE BOOT.\r\n"
      L"Esc within 5 seconds boots Windows only.\r\n"
      L"Otherwise one transaction per card runs, then Windows starts.\r\n"
      L"Screen goes dark after the first driver release: expected. "
      L"On failure power off, then F8 -> Windows Boot Manager.\r\n");
  if (!LogEnabled)
    Say(L"Logging is off by CONFIG.TXT: a failed run leaves no report.\r\n");
  for (UINTN i = 0; i < 50; i++) {
    EFI_INPUT_KEY Key;
    Status = Table->ConIn->ReadKeyStroke(Table->ConIn, &Key);
    if (Status == EFI_SUCCESS && (Key.ScanCode == 0x17 || Key.UnicodeChar == 27)) {
      *Skip = TRUE;
      return EFI_SUCCESS;
    }
    if (Status != EFI_SUCCESS && Status != EFI_NOT_READY) break;
    Status = Table->BootServices->Stall(100000);
    if (Status != EFI_SUCCESS) return Status;
  }
  return EFI_SUCCESS;
}

EFI_STATUS EFIAPI efi_main(EFI_HANDLE Image, EFI_SYSTEM_TABLE *St) {
  Table = St;
  Self = Image;
  if (!St || !St->BootServices) Stop();
  if (St->BootServices->SetWatchdogTimer(0, 0, 0, NULL) != EFI_SUCCESS) Stop();
  /* Read the one absolute pointer so the relocation the loader applied above
   * is exercised, not merely present. */
  if (!RelocationAnchor) Stop();
  EFI_LOADED_IMAGE_PROTOCOL *Loaded = NULL;
  EFI_STATUS Status = St->BootServices->HandleProtocol(Image, &LoadedGuid, (VOID **)&Loaded);
  if (Status != EFI_SUCCESS || !Loaded) Stop();
  OwnDevice = Loaded->DeviceHandle;

  /* The media this image was loaded from must be the USB stick, and the log
   * and child live on that same volume. */
  EFI_DEVICE_PATH_PROTOCOL *OwnPath = NULL;
  BOOLEAN Usb = FALSE;
  if (PathFor(OwnDevice, &OwnPath) != EFI_SUCCESS ||
      !GuInspectPath(OwnPath, NULL, NULL, &Usb, NULL) || !Usb) {
    Say(L"MULTI UNLOCK: must be booted from the USB stick.\r\n");
    Stop();
  }

  EFI_HANDLE Windows = NULL;
  Status = FindPartition(&GuWindowsPartition, &Windows);
  if (Status != EFI_SUCCESS || Windows == OwnDevice) Stop();
  Status = OpenVolume();
  if (Status != EFI_SUCCESS) Stop();
  GU_LOG_CONFIG Config = GuReadLogConfig(Root);
  LogEnabled = Config.Enabled;
  if (Config.Invalid)
    Say(L"CONFIG.TXT: log= value not understood; keeping the default (logging on).\r\n");
  if (LogEnabled) {
    Status = OpenLog();
    if (Status != EFI_SUCCESS) Stop();
    Record("multi-wrapper-start", EFI_SUCCESS);
  } else {
    Say(L"CONFIG.TXT: logging off. No files are written to the stick this boot.\r\n");
  }

  Status = LoadChild();
  if (Status != EFI_SUCCESS) {
    Record("child-load", Status);
    Say(L"UNLOCK-MULTI.EFI missing or does not match its pinned hash.\r\n");
    Stop();
  }

  EFI_DEVICE_PATH_PROTOCOL *WinPath = NULL;
  Status = FilePath(Windows, L"\\EFI\\Microsoft\\Boot\\bootmgfw.efi", &WinPath);
  if (Status == EFI_SUCCESS)
    Status = St->BootServices->LoadImage(FALSE, Self, WinPath, NULL, 0, &WindowsImage);
  if (WinPath) St->BootServices->FreePool(WinPath);
  if (Status != EFI_SUCCESS) {
    Record("windows-load", Status);
    Stop();
  }
  EFI_LOADED_IMAGE_PROTOCOL *WinLoaded = NULL;
  Status = St->BootServices->HandleProtocol(WindowsImage, &LoadedGuid, (VOID **)&WinLoaded);
  if (Status != EFI_SUCCESS || !WinLoaded || WinLoaded->DeviceHandle != Windows) Stop();

  BOOLEAN Skip = FALSE;
  if (EFI_ERROR(Choose(&Skip))) {
    Record("choice-unavailable", EFI_SUCCESS);
    Skip = FALSE;
  }
  if (Skip) {
    Record("skipped-by-user", EFI_SUCCESS);
  } else {
    Record("child-start", EFI_SUCCESS);
    Status = St->BootServices->StartImage(ChildImage, NULL, NULL);
    Record("child-result", Status);
    if (EFI_ERROR(Status)) {
      /* The child halts instead of returning after any hardware change, so an
       * error here is a pre-hardware refusal: boot Windows normally. */
      Record("child-refused-before-hardware", Status);
    }
  }

  /* No console output from here: the console GOP may be stopped. */
  Record("windows-start", EFI_SUCCESS);
  if (Log) { (void)Log->Close(Log); Log = NULL; }
  St->BootServices->StartImage(WindowsImage, NULL, NULL);
  /* If Windows returns, its console may own the screen: halt silently. */
  for (;;) __asm__ volatile("pause");
  return Status;
}
