# GPL-2.0-only. Copy the build-observe-usb.ps1 EFI to a FAT32 USB stick as its removable-media
# boot file. Files only: no partitioning, formatting, firmware assets, boot entries or settings.
param([Parameter(Mandatory)][ValidatePattern('^[D-Zd-z]$')][string]$Drive)
$ErrorActionPreference='Stop'
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
. (Join-Path $PSScriptRoot 'observe-manifest.ps1')
$part=Get-Partition -DriveLetter $Drive;$disk=Get-Disk -Number $part.DiskNumber;$vol=Get-Volume -DriveLetter $Drive
if($disk.BusType -ne 'USB' -or $vol.FileSystem -ne 'FAT32' -or $part.IsSystem -or $disk.IsBoot){throw "$($Drive): is not a FAT32 USB data stick"}
$usb="$($Drive.ToUpperInvariant()):\"
function Sha([string]$p){(Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLowerInvariant()}
$m=Get-Content (Join-Path $PSScriptRoot 'build/usb-observe/manifest.json') -Raw | ConvertFrom-Json
$src=Join-Path $PSScriptRoot 'build/usb-observe/OBSERVE-USB.EFI'
Assert-ObservationManifest $repo $m 'usb-observation-only' $src
Assert-ObservationCaptureEmpty (Join-Path $usb 'RTX3090-UNLOCK')
$hash=$m.EfiSha256
$boot=Join-Path $usb 'EFI\BOOT\BOOTX64.EFI'
if(Test-Path -LiteralPath $boot) {
 $bak=Join-Path $usb ('RTX3090-UNLOCK\backup\BOOTX64-'+(Sha $boot).Substring(0,12)+'.EFI')
 if(!(Test-Path -LiteralPath $bak)){[void][IO.Directory]::CreateDirectory((Split-Path $bak));Copy-Item -LiteralPath $boot -Destination $bak}
 if((Sha $bak) -ne (Sha $boot)){throw 'Existing boot loader backup verification failed'}
 "previous BOOTX64.EFI kept as $bak"
}
[void][IO.Directory]::CreateDirectory((Split-Path $boot))
Copy-Item -LiteralPath $src -Destination $boot -Force
if((Sha $boot) -ne $hash){throw 'Copy verification failed'}
# The log (DIAGnn.TXT) and probe image dumps (IMGnn.BIN) go here; EFI file Open does not create directories.
[void][IO.Directory]::CreateDirectory((Join-Path $usb 'RTX3090-UNLOCK'))
"{0,-24} {1}" -f 'EFI\BOOT\BOOTX64.EFI',$hash
'Staged. Fully power off, then pick this stick once from the firmware boot menu (Gigabyte: F12).'
'IMGnn.BIN dumps are firmware code: keep them local, never publish them.'
