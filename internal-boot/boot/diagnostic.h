/* GPL-2.0-only. Observe the UEFI handle database; never detach a device. */
#pragma once
#include <Uefi.h>
#include <Protocol/SimpleFileSystem.h>
EFI_STATUS GuCaptureGraph(EFI_SYSTEM_TABLE *Table, EFI_FILE_PROTOCOL *Log);
