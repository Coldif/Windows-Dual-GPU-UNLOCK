/* GPL-2.0-only. Flush queued keys after detach, then require a new Enter.
 * No successful timeout, no reconnect, no reset, no console output. */
#include "research-input.h"
#include <Protocol/SimpleTextIn.h>
EFI_STATUS GuResearchChooseInput(EFI_SYSTEM_TABLE *t,BOOLEAN *skip) {
  if(!skip)return EFI_INVALID_PARAMETER;
  *skip=TRUE;
  if(!t || !t->BootServices || !t->BootServices->Stall || !t->ConIn || !t->ConIn->Reset || !t->ConIn->ReadKeyStroke)return EFI_INVALID_PARAMETER;
  EFI_STATUS s=t->ConIn->Reset(t->ConIn,FALSE);if(s!=EFI_SUCCESS)return s;
  for(UINTN i=0;i<300;i++) {
    EFI_INPUT_KEY key;s=t->ConIn->ReadKeyStroke(t->ConIn,&key);
    if(s==EFI_SUCCESS && (key.ScanCode==0x17 || key.UnicodeChar==27))return EFI_SUCCESS;
    if(s==EFI_SUCCESS && (key.UnicodeChar=='t' || key.UnicodeChar=='T')){*skip=FALSE;return EFI_SUCCESS;}
    if(s!=EFI_SUCCESS && s!=EFI_NOT_READY)return s;
    s=t->BootServices->Stall(100000);if(s!=EFI_SUCCESS)return s;
  }
  return EFI_SUCCESS; /* No T: no mutation. Windows-only path. */
}
EFI_STATUS GuResearchConfirmInput(EFI_SYSTEM_TABLE *t,GU_PREPARE_LOG log,VOID *context) {
  if(!t || !t->BootServices || !t->BootServices->Stall || !t->ConIn || !t->ConIn->Reset || !t->ConIn->ReadKeyStroke || !log)return EFI_INVALID_PARAMETER;
  EFI_STATUS s=log(context,"r2-new-enter-required-within-30-seconds",EFI_SUCCESS);
  if(s!=EFI_SUCCESS)return s;
  s=t->ConIn->Reset(t->ConIn,FALSE);if(s!=EFI_SUCCESS)return s;
  for(UINTN i=0;i<300;i++) {
    EFI_INPUT_KEY key;s=t->ConIn->ReadKeyStroke(t->ConIn,&key);
    if(s==EFI_SUCCESS) {
      if(key.ScanCode==0x17 || key.UnicodeChar==27)return EFI_ABORTED;
      if(key.UnicodeChar=='\r')return log(context,"r2-new-enter-confirmed",EFI_SUCCESS);
    } else if(s!=EFI_NOT_READY)return s;
    s=t->BootServices->Stall(100000);if(s!=EFI_SUCCESS)return s;
  }
  return EFI_TIMEOUT;
}
