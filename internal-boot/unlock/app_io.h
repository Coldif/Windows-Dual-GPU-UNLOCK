#pragma once
#include "port.h"
EFI_STATUS GuIoOpen(EFI_HANDLE Image,EFI_SYSTEM_TABLE *Table);
EFI_STATUS GuIoClose(VOID);
EFI_STATUS GuLoadAssets(VOID);
VOID GuReleaseAssets(VOID);
BOOLEAN GuLogReady(VOID);
VOID GuConsole(const char *Text);
#ifdef GU_MULTI_GPU
/* File-only logging from this point on (see app_io.c). */
VOID GuConsoleOff(VOID);
#endif
