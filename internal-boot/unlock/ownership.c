#include "ownership.h"
#include "runtime.h"
#include <Protocol/LoadedImage.h>
#ifdef GU_HEADLESS_RESEARCH
static BOOLEAN GuOwnerError(EFI_STATUS s){return s!=EFI_SUCCESS;}
#undef EFI_ERROR
#define EFI_ERROR(Status) GuOwnerError(Status)
#endif
static EFI_GUID PciGuid=EFI_PCI_IO_PROTOCOL_GUID,
  BindingGuid=EFI_DRIVER_BINDING_PROTOCOL_GUID,LoadedGuid=EFI_LOADED_IMAGE_PROTOCOL_GUID,
  PathGuid=EFI_DEVICE_PATH_PROTOCOL_GUID;
typedef struct {EFI_GUID protocol;EFI_OPEN_PROTOCOL_INFORMATION_ENTRY entry;} OWNER_RECORD;
#define MAX_RECORDS 32
/* UEFI open modes (UefiSpec.h). BY_DRIVER_STATE is newer than the rest and is
 * only a state marker: it never counts as ownership. */
#define MODE_BY_HANDLE 0x01u
#define MODE_GET 0x02u
#define MODE_TEST 0x04u
#define MODE_CHILD 0x08u
#define MODE_DRIVER 0x10u
#define MODE_EXCLUSIVE 0x20u
#define MODE_DRIVER_STATE 0x40u
static UINT32 KnownModes(VOID){
  return MODE_BY_HANDLE|MODE_GET|MODE_TEST|MODE_CHILD|MODE_DRIVER|MODE_EXCLUSIVE|MODE_DRIVER_STATE;
}
static BOOLEAN Passive(UINT32 A) {
  return A==MODE_BY_HANDLE || A==MODE_GET || A==MODE_TEST;
}
/* Only a driver or an exclusive claim holds the card. BY_CHILD_CONTROLLER is a
 * parent/child relationship (a driver's own child using its PciIo) and does not
 * block an exclusive open; a mode this table cannot explain is treated as an
 * owner, because refusing to classify an open is never a reason to take it. */
static BOOLEAN Owns(UINT32 A) {return (A&(MODE_DRIVER|MODE_EXCLUSIVE))!=0;}
static BOOLEAN Unknown(UINT32 A) {return (A&~KnownModes())!=0;}
static VOID ModeText(UINT32 A,char *Out,UINTN Size) {
  static const char *const Names[]={"handle","get","test","child","driver","exclusive","state"};
  const UINT32 Bits[7]={MODE_BY_HANDLE,MODE_GET,MODE_TEST,MODE_CHILD,MODE_DRIVER,MODE_EXCLUSIVE,MODE_DRIVER_STATE};
  UINTN n=0;Out[0]=0;
  for(UINTN i=0;i<7;i++) {
    if(!(A&Bits[i]))continue;
    for(const char *s=Names[i];*s && n+2<Size;s++)Out[n++]=*s;
    if(n+1<Size)Out[n++]='|';
  }
  if(n)Out[n-1]=0;
  else if(Size>1){Out[0]='-';Out[1]=0;}
}
/* Every record has to be explainable before ownership is taken. */
static EFI_STATUS Snapshot(OWNER_RECORD *Records,UINTN *Count) {
  EFI_GUID **protocols=NULL;UINTN protocol_count=0;BOOLEAN pci=FALSE;*Count=0;
  if(!Gu.bs->ProtocolsPerHandle)return EFI_UNSUPPORTED;
  EFI_STATUS status=Gu.bs->ProtocolsPerHandle(Gu.handle,&protocols,&protocol_count);
  if(!EFI_ERROR(status) && (!protocols || !protocol_count || protocol_count>32))status=EFI_COMPROMISED_DATA;
  for(UINTN i=0;!EFI_ERROR(status) && i<protocol_count;i++) {
    EFI_OPEN_PROTOCOL_INFORMATION_ENTRY *entries=NULL;UINTN count=0;
    if(!protocols[i]){status=EFI_COMPROMISED_DATA;break;}
    if(!memcmp(protocols[i],&PciGuid,sizeof(PciGuid)))pci=TRUE;
    status=Gu.bs->OpenProtocolInformation(Gu.handle,protocols[i],&entries,&count);
    if(!EFI_ERROR(status) && (count>MAX_RECORDS-*Count || (count && !entries)))status=EFI_COMPROMISED_DATA;
    if(!EFI_ERROR(status))for(UINTN j=0;j<count;j++) {
      Records[*Count].protocol=*protocols[i];Records[*Count].entry=entries[j];(*Count)++;
    }
    if(entries && EFI_ERROR(Gu.bs->FreePool(entries)))status=EFI_DEVICE_ERROR;
  }
  if(protocols && EFI_ERROR(Gu.bs->FreePool(protocols)))status=EFI_DEVICE_ERROR;
  return !EFI_ERROR(status) && !pci?EFI_NOT_FOUND:status;
}
static VOID LogRecords(const OWNER_RECORD *Records,UINTN Count,EFI_STATUS Status) {
  GuLog("ownership: records=%zu exclusive=%u status=%#llx\n",(size_t)Count,Gu.owned,(unsigned long long)Status);
  for(UINTN i=0;i<Count;i++) {
    const EFI_OPEN_PROTOCOL_INFORMATION_ENTRY *e=&Records[i].entry;char modes[64];
    ModeText(e->Attributes,modes,sizeof(modes));
    GuLog("owner[%u] protocol=%08x attributes=%#x(%s) count=%u agent=%#llx controller=%#llx\n",
      (unsigned)i,Records[i].protocol.Data1,e->Attributes,modes,e->OpenCount,
      (unsigned long long)(UINTN)e->AgentHandle,(unsigned long long)(UINTN)e->ControllerHandle);
  }
}
/* Size of a device path up to and including its end node; 0 if malformed. */
static UINTN PathBytes(const EFI_DEVICE_PATH_PROTOCOL *P) {
  if(!P)return 0;
  const UINT8 *Base=(const UINT8 *)P;UINTN n=0;
  for(UINTN i=0;i<64;i++) {
    if(n+4>4096)return 0;
    UINTN len=(UINTN)Base[n+2]|((UINTN)Base[n+3]<<8);
    if(len<4 || n+len>4096)return 0;
    BOOLEAN end=Base[n]==END_DEVICE_PATH_TYPE && Base[n+1]==END_ENTIRE_DEVICE_PATH_SUBTYPE;
    n+=len;
    if(end)return n;
  }
  return 0;
}
static EFI_STATUS PathOf(EFI_HANDLE Handle,EFI_DEVICE_PATH_PROTOCOL **Path) {
  *Path=NULL;
  if(!Handle || !Gu.bs->HandleProtocol)return EFI_UNSUPPORTED;
  return Gu.bs->HandleProtocol(Handle,&PathGuid,(VOID **)Path);
}
/* The controller handle a driver records is normally the device it manages, but
 * can be a handle it created for the same device. Accept it only when its
 * device path is the target's path or an extension of it, so a Stop can never
 * be aimed at a different device by accident. */
static BOOLEAN SameDeviceInstance(EFI_HANDLE Handle) {
  EFI_DEVICE_PATH_PROTOCOL *Other=NULL,*Self=NULL;
  if(!Handle || Handle==Gu.handle)return TRUE;
  if(EFI_ERROR(PathOf(Handle,&Other)) || EFI_ERROR(PathOf(Gu.handle,&Self)))return FALSE;
  UINTN a=PathBytes(Other),b=PathBytes(Self);
  return Other && Self && b && a>=b && !memcmp(Other,Self,b);
}
static VOID LogPath(EFI_HANDLE Handle,const char *Tag) {
  EFI_DEVICE_PATH_PROTOCOL *P=NULL;char Text[3*32+1];UINTN n=0,Size;
  static const char Digits[]="0123456789abcdef";
  if(EFI_ERROR(PathOf(Handle,&P)) || !P)return;
  Size=PathBytes(P);
  for(n=0;n<Size && n<32;n++) {
    UINT8 Byte=((const UINT8 *)P)[n];
    Text[n*3]=Digits[Byte>>4];Text[n*3+1]=Digits[Byte&15];Text[n*3+2]=' ';
  }
  if(n)Text[n*3-1]=0;else Text[0]=0;
  GuLog("%s: bytes=%zu hex=%s\n",Tag,Size,Text);
}
EFI_STATUS GuClaimController(VOID) {
  OWNER_RECORD records[MAX_RECORDS];UINTN count=0;
  EFI_TPL old=Gu.bs->RaiseTPL(TPL_NOTIFY);
  EFI_STATUS status=Snapshot(records,&count);
  if(!EFI_ERROR(status))for(UINTN i=0;i<count;i++)
    if(Unknown(records[i].entry.Attributes) || Owns(records[i].entry.Attributes))
      status=EFI_ACCESS_DENIED;
  if(!EFI_ERROR(status)) {
    EFI_PCI_IO_PROTOCOL *pci=NULL;
    status=Gu.bs->OpenProtocol(Gu.handle,&PciGuid,(VOID **)&pci,Gu.image,NULL,EFI_OPEN_PROTOCOL_EXCLUSIVE);
    if(!EFI_ERROR(status)){Gu.owned=TRUE;if(pci!=Gu.pci)status=EFI_COMPROMISED_DATA;}
  }
  Gu.bs->RestoreTPL(old);LogRecords(records,count,status);return status;
}
static BOOLEAN ConsoleHandle(EFI_SYSTEM_TABLE *Table,EFI_HANDLE Handle) {
  return Handle && (Handle==Table->ConsoleOutHandle || Handle==Table->ConsoleInHandle || Handle==Table->StandardErrorHandle);
}
EFI_STATUS GuFindReleaseOwner(EFI_SYSTEM_TABLE *Table,GU_RELEASE_OWNER *Owner,BOOLEAN Log) {
  OWNER_RECORD records[MAX_RECORDS];UINTN count=0,drivers=0,children=0;memset(Owner,0,sizeof(*Owner));
  if(!Gu.bs->DisconnectController || Gu.owned)return EFI_UNSUPPORTED;
  EFI_TPL old=Gu.bs->RaiseTPL(TPL_NOTIFY);
  EFI_STATUS status=Snapshot(records,&count);
  Gu.bs->RestoreTPL(old);if(Log)LogRecords(records,count,status);
  if(EFI_ERROR(status))return status;
  /* Exactly one driver may hold PciIo, and only through a single open. Its
   * controller handle must be this device or a handle belonging to it. */
  for(UINTN i=0;i<count;i++) {
    const EFI_OPEN_PROTOCOL_INFORMATION_ENTRY *e=&records[i].entry;
    if(memcmp(&records[i].protocol,&PciGuid,sizeof(PciGuid)) || !(e->Attributes&MODE_DRIVER))continue;
    BOOLEAN Self=e->ControllerHandle==Gu.handle, Child=SameDeviceInstance(e->ControllerHandle);
    if(Unknown(e->Attributes) || (e->Attributes&~(MODE_DRIVER|MODE_DRIVER_STATE)) ||
       !e->AgentHandle || !e->ControllerHandle || e->OpenCount!=1 || (!Self && !Child)) {
      if(Log) {
        GuLog("release refused: unsupported driver open at record %u self=%u same_device=%u count=%u\n",
          (unsigned)i,(unsigned)Self,(unsigned)Child,e->OpenCount);
        LogPath(e->ControllerHandle,"release refused: recorded controller");
      }
      return EFI_ACCESS_DENIED;
    }
    if(Log)GuLog("release driver: agent=%#llx controller=%#llx self=%u same_device=%u\n",
      (unsigned long long)(UINTN)e->AgentHandle,(unsigned long long)(UINTN)e->ControllerHandle,
      (unsigned)Self,(unsigned)Child);
    Owner->agent=e->AgentHandle;drivers++;
  }
  if(drivers!=1 || Owner->agent==Gu.image || Owner->agent==Gu.handle || ConsoleHandle(Table,Owner->agent))
    return EFI_ACCESS_DENIED;
  /* Nothing else may consume the card. A child relationship opened by the very
   * driver that is about to be stopped is expected and disappears with it; any
   * other child, another driver or an exclusive open is refused. */
  for(UINTN i=0;i<count;i++) {
    const EFI_OPEN_PROTOCOL_INFORMATION_ENTRY *e=&records[i].entry;
    UINT32 A=e->Attributes;BOOLEAN pci=!memcmp(&records[i].protocol,&PciGuid,sizeof(PciGuid));
    if(Passive(A))continue;
    if(Unknown(A)) {
      if(Log)GuLog("release refused: unknown open mode at record %u\n",(unsigned)i);
      return EFI_ACCESS_DENIED;
    }
    if(A&MODE_EXCLUSIVE) {
      if(Log)GuLog("release refused: exclusive open at record %u\n",(unsigned)i);
      return EFI_ACCESS_DENIED;
    }
    if(A&MODE_DRIVER) {
      if(e->AgentHandle!=Owner->agent) {
        if(Log)GuLog("release refused: second driver at record %u\n",(unsigned)i);
        return EFI_ACCESS_DENIED;
      }
      continue;
    }
    if(A&MODE_CHILD) {
      /* The firmware records the driver's own child with the driver binding
       * handle as agent; a child of anybody else is not ours to destroy. */
      if(e->AgentHandle!=Owner->agent) {
        if(Log)GuLog("release refused: foreign child at record %u (pci=%u)\n",(unsigned)i,(unsigned)pci);
        return EFI_ACCESS_DENIED;
      }
      if(pci)children++;
      continue;
    }
    if(pci) {
      if(Log)GuLog("release refused: unsupported PciIo open at record %u\n",(unsigned)i);
      return EFI_ACCESS_DENIED;
    }
  }
  EFI_DRIVER_BINDING_PROTOCOL *binding=NULL;EFI_LOADED_IMAGE_PROTOCOL *image=NULL;
  status=Gu.bs->HandleProtocol(Owner->agent,&BindingGuid,(VOID **)&binding);
  if(EFI_ERROR(status) || !binding || binding->DriverBindingHandle!=Owner->agent || !binding->Stop ||
    !binding->ImageHandle || binding->ImageHandle==Gu.image)return EFI_UNSUPPORTED;
  status=Gu.bs->HandleProtocol(binding->ImageHandle,&LoadedGuid,(VOID **)&image);
  if(EFI_ERROR(status) || !image)return EFI_UNSUPPORTED;
  if(Log)GuLog("release candidate: agent=%#llx image=%#llx source=%#llx base=%#llx bytes=%llu version=%#x code_type=%u children=%zu\n",
    (unsigned long long)(UINTN)Owner->agent,(unsigned long long)(UINTN)binding->ImageHandle,
    (unsigned long long)(UINTN)image->DeviceHandle,(unsigned long long)(UINTN)image->ImageBase,
    (unsigned long long)image->ImageSize,binding->Version,(unsigned)image->ImageCodeType,(size_t)children);
  if(!image->ImageBase || !image->ImageSize || image->ImageSize>64U*1024U*1024U || image->ImageCodeType!=EfiBootServicesCode)return EFI_UNSUPPORTED;
  Owner->image=binding->ImageHandle;Owner->base=image->ImageBase;Owner->size=image->ImageSize;
  Owner->version=binding->Version;Owner->stop=binding->Stop;return EFI_SUCCESS;
}
/* After the Stop, before the claim: no driver and no child may still hold
 * PciIo. BY_DRIVER_STATE is only a marker and is not a consumer. */
EFI_STATUS GuVerifyNoDriverOwns(VOID) {
  OWNER_RECORD records[MAX_RECORDS];UINTN count=0,held=0,children=0;
  if(!Gu.handle)return EFI_UNSUPPORTED;
  EFI_TPL old=Gu.bs->RaiseTPL(TPL_NOTIFY);
  EFI_STATUS status=Snapshot(records,&count);
  Gu.bs->RestoreTPL(old);
  if(EFI_ERROR(status))return status;
  for(UINTN i=0;i<count;i++) {
    const EFI_OPEN_PROTOCOL_INFORMATION_ENTRY *e=&records[i].entry;
    if(memcmp(&records[i].protocol,&PciGuid,sizeof(PciGuid)))continue;
    if(e->Attributes&(MODE_DRIVER|MODE_CHILD|MODE_EXCLUSIVE)) {
      held++;
      GuLog("release verify: open still held at record %u attributes=%#x\n",(unsigned)i,e->Attributes);
    }
    if(e->Attributes&MODE_CHILD)children++;
  }
  GuLog("release verify: records=%zu held=%zu children=%zu\n",(size_t)count,(size_t)held,(size_t)children);
  return held?EFI_ACCESS_DENIED:EFI_SUCCESS;
}
BOOLEAN GuSameReleaseOwner(const GU_RELEASE_OWNER *A,const GU_RELEASE_OWNER *B) {
  if(A->agent!=B->agent || A->image!=B->image || A->base!=B->base || A->size!=B->size ||
    A->version!=B->version || A->stop!=B->stop)return FALSE;
  return TRUE;
}
EFI_STATUS GuRefreshTargetPci(VOID) {
  EFI_PCI_IO_PROTOCOL *fresh=NULL;UINTN segment,bus,device,function;UINT32 config[64]={0};
  Gu.pci=NULL;
  EFI_STATUS status=Gu.bs->HandleProtocol(Gu.handle,&PciGuid,(VOID **)&fresh);
  if(EFI_ERROR(status) || !fresh || !fresh->GetLocation || !fresh->Pci.Read || !fresh->Pci.Write)return EFI_NOT_FOUND;
  status=fresh->GetLocation(fresh,&segment,&bus,&device,&function);if(EFI_ERROR(status))return status;
  const UINT32 offsets[]={0,8,12,44};
  for(UINTN i=0;i<4;i++) {
    status=fresh->Pci.Read(fresh,EfiPciIoWidthUint32,offsets[i],1,&config[offsets[i]/4]);if(EFI_ERROR(status))return status;
  }
  if(!GuTargetConfig(config,segment,bus,device,function))return EFI_UNSUPPORTED;
  Gu.pci=fresh;return EFI_SUCCESS;
}
