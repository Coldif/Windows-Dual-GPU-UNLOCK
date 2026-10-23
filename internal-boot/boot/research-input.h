/* GPL-2.0-only. Explicit bounded post-detach input; no output/device writes. */
#ifndef GU_RESEARCH_INPUT_H
#define GU_RESEARCH_INPUT_H
#include "prepare-console.h"
EFI_STATUS GuResearchConfirmInput(EFI_SYSTEM_TABLE *Table,GU_PREPARE_LOG Log,VOID *Context);
EFI_STATUS GuResearchChooseInput(EFI_SYSTEM_TABLE *Table,BOOLEAN *Skip);
#endif
