/* GPL-2.0-only. One policy file on the stick decides whether a run writes any
 * files at all. It only ever gates logging: no identity, decode, release or
 * transaction decision may read this file, so a stick with logging off runs
 * exactly the same hardware sequence as one with logging on.
 *
 * File: \RTX3090-UNLOCK\CONFIG.TXT, plain text, one setting per line:
 *
 *   # full logs: RUNnn\REPORT.TXT plus one MBxxx.TXT breadcrumb per boot
 *   log = 1
 *
 * Accepted values, case-insensitive: 1/on/true/yes and 0/off/false/no.
 * '#' or ';' starts a comment. Unknown keys and unreadable files are ignored:
 * the default is logging on, because a missing report is worse than a full
 * stick. With log=0 nothing is written, so a failed run leaves no evidence. */
#ifndef GU_LOG_CONFIG_H
#define GU_LOG_CONFIG_H
#include <Uefi.h>
#include <Protocol/SimpleFileSystem.h>

#define GU_LOG_CONFIG_PATH L"\\RTX3090-UNLOCK\\CONFIG.TXT"
#define GU_LOG_CONFIG_BYTES 1024

typedef struct {
  BOOLEAN Enabled; /* FALSE only when the file says log=0 */
  BOOLEAN Found;   /* the file exists and was readable */
  BOOLEAN Invalid; /* a log= line carried a value we do not understand */
} GU_LOG_CONFIG;

static BOOLEAN GuLogConfigWord(const char *Text, UINTN Length, const char *Word) {
  UINTN i = 0;
  for (; i < Length && Word[i]; i++) {
    char a = Text[i], b = Word[i];
    if (a >= 'A' && a <= 'Z') a = (char)(a - 'A' + 'a');
    if (b >= 'A' && b <= 'Z') b = (char)(b - 'A' + 'a');
    if (a != b) return FALSE;
  }
  return i == Length && !Word[i];
}

static GU_LOG_CONFIG GuReadLogConfig(EFI_FILE_PROTOCOL *Root) {
  GU_LOG_CONFIG Out = {TRUE, FALSE, FALSE};
  char Text[GU_LOG_CONFIG_BYTES];
  EFI_FILE_PROTOCOL *File = NULL;
  UINTN Total = 0;
  if (!Root || !Root->Open) return Out;
  if (EFI_ERROR(Root->Open(Root, &File, GU_LOG_CONFIG_PATH, EFI_FILE_MODE_READ, 0)) || !File)
    return Out;
  while (Total + 1 < sizeof(Text)) {
    UINTN Want = sizeof(Text) - 1 - Total;
    EFI_STATUS Status = File->Read(File, &Want, Text + Total);
    if (EFI_ERROR(Status)) {
      Total = 0; /* unreadable config: fall back to the default */
      break;
    }
    if (!Want) break;
    Total += Want;
  }
  (void)File->Close(File);
  Out.Found = TRUE;
  Text[Total] = 0;
  for (UINTN At = 0; At < Total;) {
    UINTN End = At;
    while (End < Total && Text[End] != '\r' && Text[End] != '\n') End++;
    const char *Line = Text + At;
    UINTN Length = End - At;
    At = End;
    while (At < Total && (Text[At] == '\r' || Text[At] == '\n')) At++;
    for (UINTN i = 0; i < Length; i++)
      if (Line[i] == '#' || Line[i] == ';') {
        Length = i;
        break;
      }
    const char *Cursor = Line;
    UINTN Left = Length;
    while (Left && (*Cursor == ' ' || *Cursor == '\t')) {
      Cursor++;
      Left--;
    }
    UINTN Key = 0;
    while (Key < Left && Cursor[Key] != '=' && Cursor[Key] != ' ' && Cursor[Key] != '\t') Key++;
    if (Key != 3 || !GuLogConfigWord(Cursor, Key, "log")) continue;
    const char *Value = Cursor + Key;
    UINTN Rest = Left - Key;
    while (Rest && (*Value == ' ' || *Value == '\t')) {
      Value++;
      Rest--;
    }
    if (!Rest || *Value != '=') continue;
    Value++;
    Rest--;
    while (Rest && (*Value == ' ' || *Value == '\t')) {
      Value++;
      Rest--;
    }
    UINTN ValueLength = 0;
    while (ValueLength < Rest && Value[ValueLength] != ' ' && Value[ValueLength] != '\t')
      ValueLength++;
    if (GuLogConfigWord(Value, ValueLength, "1") || GuLogConfigWord(Value, ValueLength, "on") ||
        GuLogConfigWord(Value, ValueLength, "true") || GuLogConfigWord(Value, ValueLength, "yes")) {
      Out.Enabled = TRUE;
    } else if (GuLogConfigWord(Value, ValueLength, "0") ||
               GuLogConfigWord(Value, ValueLength, "off") ||
               GuLogConfigWord(Value, ValueLength, "false") ||
               GuLogConfigWord(Value, ValueLength, "no")) {
      Out.Enabled = FALSE;
    } else {
      Out.Invalid = TRUE;
    }
  }
  return Out;
}
#endif
