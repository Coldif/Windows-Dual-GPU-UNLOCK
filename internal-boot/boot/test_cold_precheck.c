/* GPL-2.0-only. Host test for GuPeekCold: read-only pre-release cold check. */
#include "full-release.c"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int Checks,Failures;
static void Check(int ok,const char *name){Checks++;if(!ok){Failures++;fprintf(stderr,"FAIL %s\n",name);}}

typedef struct {EFI_PCI_IO_PROTOCOL io;UINTN bus,dev,fun;UINT32 cfg[16];UINT32 regs[9];BOOLEAN failRead;} FAKE;
static FAKE Devs[3];static UINTN DevCount;static UINTN Writes;
static EFI_STATUS EFIAPI Loc(EFI_PCI_IO_PROTOCOL *io,UINTN *s,UINTN *b,UINTN *d,UINTN *f){FAKE *x=(FAKE *)io;*s=0;*b=x->bus;*d=x->dev;*f=x->fun;return EFI_SUCCESS;}
static EFI_STATUS EFIAPI CfgRead(EFI_PCI_IO_PROTOCOL *io,EFI_PCI_IO_PROTOCOL_WIDTH w,UINT32 at,UINTN n,VOID *out){
  (void)w;if(at||n!=16)return EFI_INVALID_PARAMETER;memcpy(out,((FAKE *)io)->cfg,64);return EFI_SUCCESS;}
static EFI_STATUS EFIAPI MemRead(EFI_PCI_IO_PROTOCOL *io,EFI_PCI_IO_PROTOCOL_WIDTH w,UINT8 bar,UINT64 at,UINTN n,VOID *out){
  FAKE *x=(FAKE *)io;if(w!=EfiPciIoWidthUint32||bar||n!=1)return EFI_INVALID_PARAMETER;
  for(UINTN i=0;i<9;i++)if(ColdOffsets[i]==at){if(x->failRead && i==6)return EFI_DEVICE_ERROR;*(UINT32 *)out=x->regs[i];return EFI_SUCCESS;}
  return EFI_INVALID_PARAMETER;}
static EFI_STATUS EFIAPI MemWrite(EFI_PCI_IO_PROTOCOL *io,EFI_PCI_IO_PROTOCOL_WIDTH w,UINT8 bar,UINT64 at,UINTN n,VOID *in){
  (void)io;(void)w;(void)bar;(void)at;(void)n;(void)in;Writes++;return EFI_SUCCESS;}
static EFI_STATUS EFIAPI LocateBuf(EFI_LOCATE_SEARCH_TYPE t,EFI_GUID *g,VOID *k,UINTN *n,EFI_HANDLE **out){
  (void)t;(void)k;if(!GuGuidEqual(g,&PciGuid))return EFI_NOT_FOUND;
  if(!DevCount){*n=0;*out=NULL;return EFI_NOT_FOUND;}
  *n=DevCount;*out=malloc(DevCount*sizeof(EFI_HANDLE));for(UINTN i=0;i<DevCount;i++)(*out)[i]=&Devs[i];return EFI_SUCCESS;}
static EFI_STATUS EFIAPI HandleProto(EFI_HANDLE h,EFI_GUID *g,VOID **out){
  if(!GuGuidEqual(g,&PciGuid)){*out=NULL;return EFI_UNSUPPORTED;}*out=&((FAKE *)h)->io;return EFI_SUCCESS;}
static EFI_STATUS EFIAPI FreeP(VOID *p){free(p);return EFI_SUCCESS;}

/* A power-on state for the selected profile; SS0/SS1 are any valid entry values. */
static void Card(FAKE *x){
  memset(x,0,sizeof(*x));x->io.GetLocation=Loc;x->io.Pci.Read=CfgRead;x->io.Mem.Read=MemRead;x->io.Mem.Write=MemWrite;
  x->bus=1;x->cfg[0]=GU_BOARD_ID;x->cfg[2]=0x030000a1;x->cfg[11]=GU_BOARD_SUBSYSTEM;
  const UINT32 r[9]={GU_CHIP_ID,0x8b8f,0x3ff,0x10,0,0xffffff8f,0x40123070,0x3,GU_DEVICE_MEMORY_SIZE};memcpy(x->regs,r,sizeof(r));
}
static EFI_STATUS Run(void){
  static EFI_BOOT_SERVICES bs;static EFI_SYSTEM_TABLE t;UINT32 v[9];
  bs.LocateHandleBuffer=LocateBuf;bs.HandleProtocol=HandleProto;bs.FreePool=FreeP;t.BootServices=&bs;
  return GuPeekCold(&t,v);
}
int main(void){
  DevCount=1;Card(&Devs[0]);Check(Run()==EFI_SUCCESS,"real cold X870 state accepted");
  for(UINT32 ss1=0;ss1<=15;ss1++){Card(&Devs[0]);Devs[0].regs[7]=ss1;Check(Run()==EFI_SUCCESS,"any power-on SS1 0..15 accepted");}
  Card(&Devs[0]);Devs[0].regs[7]=16;Check(Run()==EFI_NOT_READY,"SS1 above 15 refused");
  Card(&Devs[0]);Devs[0].regs[4]=0x5ff2e00;Check(Run()==EFI_NOT_READY,"initialized WPR2 (warm restart) refused");
  Card(&Devs[0]);Devs[0].regs[6]=0x88888888;Check(Run()==EFI_NOT_READY,"already unlocked SS0 refused");
  Card(&Devs[0]);Devs[0].regs[6]=0xbadf5040;Check(Run()==EFI_NOT_READY,"inaccessible SS0 refused");
  Card(&Devs[0]);Devs[0].regs[3]=0;Check(Run()==EFI_NOT_READY,"running GFW falcon refused");
  Card(&Devs[0]);Devs[0].regs[8]=GU_DEVICE_MEMORY_SIZE+4;Check(Run()==EFI_NOT_READY,"other memory size refused");
  Card(&Devs[0]);Devs[0].regs[0]=GU_CHIP_ID^0x00100000U;Check(Run()==EFI_NOT_READY,"other chip refused");
  Card(&Devs[0]);Devs[0].failRead=TRUE;Check(Run()==EFI_DEVICE_ERROR,"register read failure reported");
  Card(&Devs[0]);Devs[0].cfg[11]=GU_BOARD_SUBSYSTEM^1U;Check(Run()==EFI_NOT_FOUND,"other subsystem not a target");
  Card(&Devs[0]);Devs[0].bus=2;Check(Run()==EFI_NOT_FOUND,"card at another slot not a target");
  DevCount=2;Card(&Devs[0]);Card(&Devs[1]);Devs[1].fun=1;Devs[1].cfg[0]=0x1aef10de;Check(Run()==EFI_SUCCESS,"HD audio function ignored");
  Card(&Devs[1]);Check(Run()==EFI_NOT_FOUND,"two identical targets refused");
  DevCount=0;Check(Run()==EFI_NOT_FOUND,"no PCI devices refused");
  Check(Writes==0,"no MMIO writes in any case");
  if(Failures){fprintf(stderr,"%d/%d cold pre-check cases failed\n",Failures,Checks);return 1;}
  printf("PASS %d cold pre-check cases; read-only, no MMIO writes\n",Checks);return 0;
}
