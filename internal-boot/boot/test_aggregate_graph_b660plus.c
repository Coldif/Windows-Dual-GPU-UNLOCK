/* GPL-2.0-only. Freestanding host replay of the B660-PLUS two-child console
 * graph (one console GOP child + one EDID-only sibling), modelled on the real
 * DIAG00/DIAG01 probe captures. Synthetic handles/paths/PCI data; never calls
 * firmware or a GPU. Drives the actual compiled Consumers()/FullConsumers()/
 * FullExpected(), then a battery of fail-closed mutations. */
#include "full-release.c"

#if !GU_CONSOLE_MULTI_CHILD || GU_CONSOLE_CHILD_COUNT!=2
#error This replay is for the two-child aggregate profile
#endif

/* LLVM may lower large UEFI struct initializers to these C runtime intrinsics. */
VOID *memset(VOID *target,int value,UINTN count) {
  UINT8 *p=target;for(UINTN i=0;i<count;i++)p[i]=(UINT8)value;return target;
}
VOID *memcpy(VOID *target,const VOID *source,UINTN count) {
  UINT8 *p=target;const UINT8 *q=source;for(UINTN i=0;i<count;i++)p[i]=q[i];return target;
}

enum { H_PCI=1,H_PRIMARY,H_AUX1,H_AGG,H_CONSOLE,H_NV,H_EDID,H_COMBO,
       H_GFX,H_TEXT,H_IMAGE_EDID=20,H_IMAGE_COMBO,H_IMAGE_GFX,H_IMAGE_TEXT,H_EXTRA };
#define H(x) ((EFI_HANDLE)(UINTN)(x))

static EFI_BOOT_SERVICES MockBoot;
static EFI_SYSTEM_TABLE MockTable;
static EFI_PCI_IO_PROTOCOL MockPci;
static UINT32 MockConfig[16];
static UINT8 Paths[2][36];
static EFI_DRIVER_BINDING_PROTOCOL Bindings[4];
static EFI_LOADED_IMAGE_PROTOCOL Images[4];
static UINT8 ImagePaths[4][24];
static GRAPH Original,Current;
static UINT8 EdidData;
static BOOLEAN AuxHasGop;

static EFI_STATUS EFIAPI MockHandle(EFI_HANDLE h,EFI_GUID *guid,VOID **out) {
  *out=NULL;
  if(GuGuidEqual(guid,&PciGuid) && h==H(H_PCI))*out=&MockPci;
  if(GuGuidEqual(guid,&PathGuid)) {
    if(h==H(H_PRIMARY))*out=Paths[0];
    if(h==H(H_AUX1))*out=Paths[1];
  }
  if(GuGuidEqual(guid,&EdidGuid) && (h==H(H_PRIMARY) || h==H(H_AUX1)))*out=&EdidData;
  if(GuGuidEqual(guid,&GopGuid) && AuxHasGop && h==H(H_AUX1))*out=&EdidData;
  for(UINTN i=0;i<4;i++) {
    if(GuGuidEqual(guid,&BindingGuid) && h==H(H_EDID+i))*out=&Bindings[i];
    if(GuGuidEqual(guid,&ImageGuid) && h==H(H_IMAGE_EDID+i))*out=&Images[i];
  }
  return *out?EFI_SUCCESS:EFI_NOT_FOUND;
}
static EFI_STATUS EFIAPI MockLocatePci(EFI_GUID *guid,EFI_DEVICE_PATH_PROTOCOL **path,EFI_HANDLE *handle) {
  if(!GuGuidEqual(guid,&PciGuid))return EFI_UNSUPPORTED;
  BOOLEAN known=FALSE;
  for(UINTN i=0;i<2;i++)if((VOID *)*path==(VOID *)Paths[i])known=TRUE;
  if(!known)return EFI_UNSUPPORTED;
  *handle=H(H_PCI);*path=(EFI_DEVICE_PATH_PROTOCOL *)((UINT8 *)*path+24);
  return EFI_SUCCESS;
}
static EFI_STATUS EFIAPI MockLocation(EFI_PCI_IO_PROTOCOL *io,UINTN *seg,UINTN *bus,UINTN *dev,UINTN *fun) {
  if(io!=&MockPci)return EFI_UNSUPPORTED;
  *seg=*dev=*fun=0;*bus=1;return EFI_SUCCESS;
}
static EFI_STATUS EFIAPI MockRead(EFI_PCI_IO_PROTOCOL *io,EFI_PCI_IO_PROTOCOL_WIDTH width,UINT32 at,UINTN count,VOID *data) {
  if(io!=&MockPci || width!=EfiPciIoWidthUint32 || at || count!=16)return EFI_UNSUPPORTED;
  for(UINTN i=0;i<16;i++)((UINT32 *)data)[i]=MockConfig[i];
  return EFI_SUCCESS;
}
static VOID Add(GRAPH *g,UINTN h,UINTN agent,UINTN controller,EFI_GUID guid,UINT32 attributes) {
  EDGE *e=&g->Edges[g->Count++];e->Handle=H(h);e->Agent=H(agent);e->Controller=H(controller);
  e->Protocol=guid;e->Attributes=attributes;e->Count=1;
}
static VOID CopyGraph(GRAPH *to,const GRAPH *from) {
  to->Count=from->Count;
  for(UINTN i=0;i<from->Count;i++)to->Edges[i]=from->Edges[i];
}
static VOID DropEdge(GRAPH *g,UINTN handle,EFI_GUID *guid) {
  UINTN next=0;
  for(UINTN i=0;i<g->Count;i++)
    if(g->Edges[i].Handle!=H(handle) || !GuGuidEqual(&g->Edges[i].Protocol,guid))g->Edges[next++]=g->Edges[i];
  g->Count=next;
}
static VOID InitImages(VOID) {
  const EFI_GUID *files[4]={&EdidFile,&ComboFile,&GfxFile,&OutFile};
  const UINTN sizes[4]={GU_EDID_IMAGE_SIZE,GU_COMBO_SIZE,GU_CONSOLE_GFX_SIZE,GU_CONSOLE_TEXT_SIZE};
  const UINTN stops[4]={GU_EDID_STOP,GU_COMBO_STOP,GU_CONSOLE_GFX_STOP,GU_CONSOLE_TEXT_STOP};
  const UINT32 versions[4]={1,GU_COMBO_VERSION,GU_CONSOLE_GFX_VERSION,GU_CONSOLE_TEXT_VERSION};
  for(UINTN i=0;i<4;i++) {
    UINT8 *path=ImagePaths[i];path[0]=MEDIA_DEVICE_PATH;path[1]=MEDIA_PIWG_FW_FILE_DP;path[2]=20;path[3]=0;
    for(UINTN j=0;j<16;j++)path[4+j]=((const UINT8 *)files[i])[j];
    path[20]=END_DEVICE_PATH_TYPE;path[21]=END_ENTIRE_DEVICE_PATH_SUBTYPE;path[22]=4;path[23]=0;
    Images[i]=(EFI_LOADED_IMAGE_PROTOCOL){0};Images[i].ImageBase=(VOID *)(UINTN)(0x100000+i*0x100000);
    Images[i].ImageSize=sizes[i];Images[i].ImageCodeType=i?EfiBootServicesCode:EfiRuntimeServicesCode;
    Images[i].FilePath=(EFI_DEVICE_PATH_PROTOCOL *)path;
    Bindings[i]=(EFI_DRIVER_BINDING_PROTOCOL){0};Bindings[i].Version=versions[i];
    Bindings[i].DriverBindingHandle=H(H_EDID+i);Bindings[i].ImageHandle=H(H_IMAGE_EDID+i);
    Bindings[i].Stop=(EFI_DRIVER_BINDING_STOP)((UINT8 *)Images[i].ImageBase+stops[i]);
  }
}
static VOID Init(VOID) {
  MockBoot=(EFI_BOOT_SERVICES){0};MockTable=(EFI_SYSTEM_TABLE){0};MockPci=(EFI_PCI_IO_PROTOCOL){0};
  MockBoot.HandleProtocol=MockHandle;MockBoot.LocateDevicePath=MockLocatePci;
  MockPci.GetLocation=MockLocation;MockPci.Pci.Read=MockRead;MockTable.BootServices=&MockBoot;
  for(UINTN i=0;i<16;i++)MockConfig[i]=0;
  MockConfig[0]=GU_BOARD_ID;MockConfig[2]=0x030000a1;MockConfig[11]=GU_BOARD_SUBSYSTEM;
  /* Primary ADR == RtxPath (0x80010300); the EDID-only sibling at 0x80010330. */
  for(UINTN c=0;c<2;c++)for(UINTN j=0;j<36;j++)Paths[c][j]=RtxPath[j];
  Paths[1][28]=0x30;
  InitImages();AuxHasGop=FALSE;Original.Count=0;
  Add(&Original,H_PCI,H_NV,H_PCI,PciGuid,EFI_OPEN_PROTOCOL_BY_DRIVER);
  /* Firmware enumeration order differs from display order: sibling first. */
  Add(&Original,H_PCI,H_NV,H_AUX1,PathGuid,EFI_OPEN_PROTOCOL_BY_CHILD_CONTROLLER);
  Add(&Original,H_PCI,H_NV,H_PRIMARY,PathGuid,EFI_OPEN_PROTOCOL_BY_CHILD_CONTROLLER);
  Add(&Original,H_PRIMARY,H_EDID,H_PRIMARY,EdidGuid,EFI_OPEN_PROTOCOL_BY_DRIVER);
  Add(&Original,H_PRIMARY,H_COMBO,H_PRIMARY,GopGuid,EFI_OPEN_PROTOCOL_BY_DRIVER);
  Add(&Original,H_PRIMARY,H_COMBO,H_AGG,GopGuid,EFI_OPEN_PROTOCOL_BY_CHILD_CONTROLLER);
  Add(&Original,H_AUX1,H_EDID,H_AUX1,EdidGuid,EFI_OPEN_PROTOCOL_BY_DRIVER);
  Add(&Original,H_AGG,H_GFX,H_AGG,GopGuid,EFI_OPEN_PROTOCOL_BY_DRIVER);
  Add(&Original,H_AGG,H_TEXT,H_AGG,TextGuid,EFI_OPEN_PROTOCOL_BY_DRIVER);
  Add(&Original,H_AGG,H_TEXT,H_CONSOLE,TextGuid,EFI_OPEN_PROTOCOL_BY_CHILD_CONTROLLER);
}
static PLAN NewPlan(VOID) {
  PLAN p={0};p.Rtx=H(H_PRIMARY);p.RtxPci=H(H_PCI);p.RtxIo=&MockPci;
  p.Console=H(H_CONSOLE);p.Input=H(H_EXTRA);p.Error=H(H_EXTRA+1);
  for(UINTN j=0;j<16;j++)p.RtxConfig[j]=MockConfig[j];
  for(UINTN j=0;j<36;j++)p.RtxDisplayPath[j]=Paths[0][j];
  /* Displays() pins the pathless aggregate GOP and its BY_DRIVER agent before
   * Consumers() runs; model that so the AggCandidate/AggDriver hardening holds. */
  p.AggCandidate=H(H_AGG);p.AggDriver=H(H_GFX);
  return p;
}

/* A nonzero process exit code identifies the first broken invariant. */
int mainCRTStartup(void) {
  Init();PLAN p=NewPlan();
  if(Consumers(&MockTable,&p,&Original)!=EFI_SUCCESS)return 1;
  if(p.ChildCount!=2 || p.Children[0]!=H(H_PRIMARY) || p.Children[1]!=H(H_AUX1) ||
     p.EdidAgent!=H(H_EDID))return 2;
  PreparedPlan=p;PreparedGraph=&Original;
  Full=(FULL){0};Full.Table=&MockTable;Full.Image=H(H_EXTRA+2);
  if(FullConsumers(&Original)!=EFI_SUCCESS || Full.ChildCount!=2 || Full.Children[0]!=H(H_PRIMARY) ||
     Full.Children[1]!=H(H_AUX1))return 3;
  CopyGraph(&Current,&Original);
  if(!FullExpected(&Current,2))return 4;
  /* Stage 3: detach each child's EDID in turn; each detached edge must be gone. */
  for(UINTN c=0;c<2;c++) {
    UINTN child=(UINTN)Full.Children[c];DropEdge(&Current,child,&EdidGuid);Full.EdidDetached++;
    if(!FullExpected(&Current,3))return (int)(5+c);
  }
  CopyGraph(&Current,&Original);Full.EdidDetached=1;
  if(FullExpected(&Current,3))return 7; /* First detached EDID must be absent. */
  /* Stage 4: after NV stop, every child handle and the NV ownership must be gone. */
  CopyGraph(&Current,&Original);Full.EdidDetached=2;
  for(UINTN c=0;c<2;c++)DropEdge(&Current,(UINTN)Full.Children[c],&EdidGuid);
  UINTN keep=0;
  for(UINTN i=0;i<Current.Count;i++) {
    EDGE *e=&Current.Edges[i];BOOLEAN remove=e->Handle==H(H_PCI) && e->Agent==H(H_NV);
    for(UINTN c=0;c<2;c++)if(e->Handle==Full.Children[c])remove=TRUE;
    if(!remove)Current.Edges[keep++]=*e;
  }
  Current.Count=keep;
  if(!FullExpected(&Current,4))return 8;
  Add(&Current,H_AUX1,H_EDID,H_AUX1,EdidGuid,EFI_OPEN_PROTOCOL_BY_DRIVER);
  if(FullExpected(&Current,4))return 9; /* No stale sibling edge after NV stop. */

  /* Fail-closed mutations. */
  Init();p=NewPlan();Original.Edges[6].Agent=H(H_EXTRA); /* sibling EDID by a foreign agent */
  if(Consumers(&MockTable,&p,&Original)==EFI_SUCCESS)return 11;
  Init();p=NewPlan();Paths[1][28]=Paths[0][28]; /* duplicate child path */
  if(Consumers(&MockTable,&p,&Original)==EFI_SUCCESS)return 12;
  Init();p=NewPlan();AuxHasGop=TRUE; /* sibling must not own a GOP */
  if(Consumers(&MockTable,&p,&Original)==EFI_SUCCESS)return 13;
  Init();p=NewPlan();Add(&Original,H_PCI,H_NV,H_EXTRA,PathGuid,EFI_OPEN_PROTOCOL_BY_CHILD_CONTROLLER); /* extra 3rd child */
  if(Consumers(&MockTable,&p,&Original)==EFI_SUCCESS)return 14;
  Init();p=NewPlan();if(Consumers(&MockTable,&p,&Original)!=EFI_SUCCESS)return 15;
  PreparedPlan=p;Full=(FULL){0};Full.Table=&MockTable;Full.Image=H(H_EXTRA+2);
  Add(&Original,H_AUX1,H_EXTRA,H_AUX1,TextGuid,EFI_OPEN_PROTOCOL_BY_DRIVER); /* sibling grows a TextOut */
  if(FullConsumers(&Original)==EFI_SUCCESS)return 16;
  Init();p=NewPlan();if(Consumers(&MockTable,&p,&Original)!=EFI_SUCCESS)return 17;
  PreparedPlan=p;Full=(FULL){0};Full.Table=&MockTable;Full.Image=H(H_EXTRA+2);
  Paths[1][28]^=1; /* child path drifts between prepare and release */
  if(FullConsumers(&Original)==EFI_SUCCESS)return 18;
  Init();p=NewPlan();DropEdge(&Original,H_PCI,&PathGuid); /* only one child present */
  Add(&Original,H_PCI,H_NV,H_PRIMARY,PathGuid,EFI_OPEN_PROTOCOL_BY_CHILD_CONTROLLER);
  if(Consumers(&MockTable,&p,&Original)==EFI_SUCCESS)return 19;
  return 0;
}
