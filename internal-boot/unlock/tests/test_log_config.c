/* GPL-2.0-only. Host test for boot/log-config.h: the stick decides whether a
 * boot writes files, so every accepted spelling and the fallback on a broken
 * file are pinned here. Only the two file-protocol calls the header uses are
 * stubbed; no firmware, no device and no hardware access. */
#include <Uefi.h>
#include <Protocol/SimpleFileSystem.h>
#include <stdio.h>
#include <string.h>
#include "../../boot/log-config.h"

static char Content[GU_LOG_CONFIG_BYTES];
static UINTN ContentSize;
static BOOLEAN Exists = TRUE;
static int Failures;

typedef struct {
  EFI_FILE_PROTOCOL Proto;
  UINTN Pos;
} FAKE_FILE;

static FAKE_FILE File;

static int WideEqual(const CHAR16 *Left, const CHAR16 *Right) {
  while (*Left && *Right) {
    if (*Left != *Right) return 0;
    Left++;
    Right++;
  }
  return *Left == *Right;
}

static EFI_STATUS EFIAPI FakeClose(EFI_FILE_PROTOCOL *This) {
  (void)This;
  return EFI_SUCCESS;
}

static EFI_STATUS EFIAPI FakeRead(EFI_FILE_PROTOCOL *This, UINTN *Size, VOID *Buffer) {
  FAKE_FILE *File = (FAKE_FILE *)This;
  UINTN Want = *Size;
  if (Want > ContentSize - File->Pos) Want = ContentSize - File->Pos;
  if (Want) memcpy(Buffer, Content + File->Pos, Want);
  File->Pos += Want;
  *Size = Want;
  return EFI_SUCCESS;
}

static EFI_STATUS EFIAPI FakeOpen(EFI_FILE_PROTOCOL *This, EFI_FILE_PROTOCOL **New,
                                  CHAR16 *Name, UINT64 Mode, UINT64 Attributes) {
  (void)This;
  (void)Mode;
  (void)Attributes;
  if (!WideEqual(Name, GU_LOG_CONFIG_PATH) || !Exists) return EFI_NOT_FOUND;
  File.Pos = 0;
  *New = &File.Proto;
  return EFI_SUCCESS;
}

static void Expect(const char *Name, const char *Text, BOOLEAN WantEnabled,
                   BOOLEAN WantFound, BOOLEAN WantInvalid) {
  FAKE_FILE Root;
  memset(&Root, 0, sizeof(Root));
  memset(&File, 0, sizeof(File));
  Root.Proto.Open = FakeOpen;
  File.Proto.Read = FakeRead;
  File.Proto.Close = FakeClose;
  ContentSize = Text ? (UINTN)strlen(Text) : 0;
  if (ContentSize) memcpy(Content, Text, ContentSize);
  Exists = Text != NULL;
  GU_LOG_CONFIG Out = GuReadLogConfig(&Root.Proto);
  int Ok = Out.Enabled == WantEnabled && Out.Found == WantFound &&
           Out.Invalid == WantInvalid;
  printf("%-4s %-28s enabled=%d found=%d invalid=%d\n", Ok ? "ok" : "FAIL", Name,
         Out.Enabled, Out.Found, Out.Invalid);
  if (!Ok) Failures++;
}

int main(void) {
  /* A missing or empty file must never turn logging off by accident. */
  Expect("missing file", NULL, TRUE, FALSE, FALSE);
  Expect("empty file", "", TRUE, TRUE, FALSE);
  Expect("log=1", "log = 1\n", TRUE, TRUE, FALSE);
  Expect("log=0", "log = 0\n", FALSE, TRUE, FALSE);
  Expect("log=0 crlf", "log=0\r\n", FALSE, TRUE, FALSE);
  Expect("LOG = OFF", "LOG = OFF\r\n", FALSE, TRUE, FALSE);
  Expect("log=no", "log = no\n", FALSE, TRUE, FALSE);
  Expect("log=yes", "log=yes\n", TRUE, TRUE, FALSE);
  Expect("log=false", "log=false\n", FALSE, TRUE, FALSE);
  Expect("log=true", "log=true\n", TRUE, TRUE, FALSE);
  Expect("spaces", "   log    =    0   \n", FALSE, TRUE, FALSE);
  Expect("inline comment", "log = 0 # daily use\n", FALSE, TRUE, FALSE);
  Expect("commented out", "# log = 0\n", TRUE, TRUE, FALSE);
  Expect("semicolon comment", "; log = 0\n", TRUE, TRUE, FALSE);
  Expect("unknown value", "log = maybe\n", TRUE, TRUE, TRUE);
  Expect("empty value", "log =\n", TRUE, TRUE, TRUE);
  Expect("other key", "loglevel = 0\n", TRUE, TRUE, FALSE);
  Expect("last line wins", "log = 0\nlog = 1\n", TRUE, TRUE, FALSE);
  Expect("last line wins 2", "log = 1\nlog = 0\n", FALSE, TRUE, FALSE);
  Expect("no equals", "log 0\n", TRUE, TRUE, FALSE);
  printf(Failures ? "FAILURES: %d\n" : "ALL LOG-CONFIG CASES PASSED\n", Failures);
  return Failures ? 1 : 0;
}
