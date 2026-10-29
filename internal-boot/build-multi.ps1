# GPL-2.0-only. Build the multi-target unlock child + its USB wrapper, and
# optionally stage both (plus the five firmware assets) on a FAT32 USB stick.
#
#   .\internal-boot\build-multi.ps1 -WindowsEspGuid <esp-guid>
#   .\internal-boot\build-multi.ps1 -WindowsEspGuid <esp-guid> -Drive E -Stage
#
# Files only, and only under internal-boot/*/build/multi plus the chosen drive.
# Nothing here formats, partitions, writes boot entries or changes firmware
# settings. Only booting the staged stick touches the GPUs.
param(
 [Parameter(Mandatory)][guid]$WindowsEspGuid,
 [string]$Clang='clang',
 [string]$LldLink='lld-link',
 [string]$Python='python',
 [ValidatePattern('^[D-Zd-z]$')][string]$Drive,
 [switch]$Stage
)
$ErrorActionPreference='Stop'
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$boot=Join-Path $repo 'internal-boot/boot'
$unlock=Join-Path $repo 'internal-boot/unlock'
$outChild=Join-Path $unlock 'build/multi'
$outBoot=Join-Path $boot 'build/multi'

function GuidC([guid]$Value){
 $b=$Value.ToByteArray();$tail=($b[8..15] | ForEach-Object {'0x{0:x2}' -f $_}) -join ','
 return ('{{0x{0:x8},0x{1:x4},0x{2:x4},{{{3}}}}}' -f [BitConverter]::ToUInt32($b,0),[BitConverter]::ToUInt16($b,4),[BitConverter]::ToUInt16($b,6),$tail)
}

$windows=@(Get-Partition | Where-Object {$_.Guid -and [guid]$_.Guid -eq $WindowsEspGuid})
if($windows.Count -ne 1 -or !$windows[0].IsSystem){throw 'WindowsEspGuid must identify the current system EFI partition'}

$config=Join-Path $boot 'platform-config.h'
$marker='/* Local multi-target USB configuration (build-multi.ps1). Internal partition unused. */'
if((Test-Path -LiteralPath $config) -and (Get-Content -LiteralPath $config -TotalCount 1) -ne $marker){
 throw 'platform-config.h belongs to another setup; move it aside before a multi-target USB build'
}
@($marker,
  ('#define GU_INTERNAL_PARTITION_INITIALIZER '+(GuidC ([guid]::Empty))),
  ('#define GU_WINDOWS_PARTITION_INITIALIZER '+(GuidC $WindowsEspGuid))) |
 Set-Content -LiteralPath $config -Encoding ascii

New-Item -ItemType Directory -Path $outChild,$outBoot -Force | Out-Null

# --- child: both cards, one transaction each ---------------------------------
$childSources=@('multi-app','app_io','ownership','format','runtime','sha256','checks','port','compat',
 'vendor/unlock_610','vendor/prep_610','vendor/layout_610','vendor/vbios_610','vendor/gfw_eval')
$childObjects=@()
Push-Location -LiteralPath $unlock
try {
 foreach($source in $childSources) {
  $object=Join-Path $outChild (($source -replace '/','_')+'.obj')
  & $Clang -target x86_64-pc-windows-msvc -std=c11 -ffreestanding -fno-builtin -fno-stack-protector -mno-red-zone -fshort-wchar -Os -Wall -Wextra -Werror -Wno-unused-parameter -D__KERNEL__ -DGU_UEFI_PORT -DGU_PROFILE_MULTI_GPU -DGU_EXPERIMENTAL_3090 -DGU_ENTRY_LATCHED_SS1_FULL -DGU_USB_MEDIA -I compat -I ../../deps/edk2/MdePkg/Include -I ../../deps/edk2/MdePkg/Include/X64 -c "$source.c" -o $object
  if($LASTEXITCODE -ne 0){throw "Multi child compile failed: $source"}
  $childObjects+=$object
 }
 & $LldLink /nologo /nodefaultlib /subsystem:efi_application /entry:efi_main /machine:x64 /base:0 /dynamicbase /nxcompat /timestamp:0 /opt:ref /opt:icf "/map:$outChild/UNLOCK-MULTI.map" "/out:$outChild/UNLOCK-MULTI.EFI" @childObjects
 if($LASTEXITCODE -ne 0){throw 'Multi child link failed'}
 & $Python verify_pe.py "$outChild/UNLOCK-MULTI.EFI" "$outChild/UNLOCK-MULTI.map" --output "$outChild/pe-verification.json"
 if($LASTEXITCODE -ne 0){throw 'Multi child PE verification failed'}
} finally {Pop-Location}

$child=Join-Path $outChild 'UNLOCK-MULTI.EFI'
$childHash=(Get-FileHash -LiteralPath $child -Algorithm SHA256).Hash.ToLowerInvariant()
$childBytes=(Get-Item -LiteralPath $child).Length

# --- wrapper: stick -> child -> Windows --------------------------------------
Push-Location -LiteralPath $boot
try {
 @('/* Local multi-target child contract; GPL-2.0-only. Generated, never committed. */',
   ('#define GU_CHILD_SHA256 "'+$childHash+'"'),
   ('#define GU_CHILD_BYTES '+$childBytes)) | Set-Content build/multi/child-contract.h -Encoding ascii
 & $Clang -target x86_64-pc-windows-msvc -std=c11 -ffreestanding -fno-builtin -fno-stack-protector -mno-red-zone -fshort-wchar -Os -Wall -Wextra -Werror -Wno-unused-parameter -I ../../deps/edk2/MdePkg/Include -I ../../deps/edk2/MdePkg/Include/X64 -c multi-boot.c -o build/multi/multi-boot.obj
 if($LASTEXITCODE -ne 0){throw 'Multi wrapper compile failed'}
 & $Clang -target x86_64-pc-windows-msvc -std=c11 -ffreestanding -fno-builtin -fno-stack-protector -mno-red-zone -fshort-wchar -Os -Wall -Wextra -Werror -Wno-unused-parameter -I ../../deps/edk2/MdePkg/Include -I ../../deps/edk2/MdePkg/Include/X64 -c ../unlock/sha256.c -o build/multi/sha256.obj
 if($LASTEXITCODE -ne 0){throw 'Multi wrapper sha256 compile failed'}
 & $LldLink /nologo /nodefaultlib /subsystem:efi_application /entry:efi_main /machine:x64 /base:0 /dynamicbase /nxcompat /timestamp:0 /opt:ref /opt:icf /map:build/multi/BOOTX64.map /out:build/multi/BOOTX64.EFI build/multi/multi-boot.obj build/multi/sha256.obj
 if($LASTEXITCODE -ne 0){throw 'Multi wrapper link failed'}
 & $Python ../unlock/verify_pe.py build/multi/BOOTX64.EFI build/multi/BOOTX64.map --output build/multi/pe-verification.json
 if($LASTEXITCODE -ne 0){throw 'Multi wrapper PE verification failed'}
} finally {Pop-Location}

$bootEfi=Join-Path $outBoot 'BOOTX64.EFI'
[ordered]@{
 Format=1; Mode='multi-target-runtime-unlock-then-windows-usb'; CanUnlock=$true; HardwareTested=$false
 Targets=@('0x248710deU/0x40741458U/0xb74000a1U','0x250410deU/0x153610deU/0xb76000a1U')
 ChildSha256=$childHash; ChildBytes=$childBytes
 WrapperSha256=(Get-FileHash -LiteralPath $bootEfi -Algorithm SHA256).Hash.ToLowerInvariant()
 WrapperBytes=(Get-Item -LiteralPath $bootEfi).Length
 BuiltUtc=[DateTime]::UtcNow.ToString('o')
} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $outBoot 'multi-manifest.json') -Encoding utf8

"Built $childBytes byte child ($childHash) and wrapper $bootEfi"

if($Stage){
 if(!$Drive){throw '-Stage requires -Drive <letter>'}
 $target="${Drive}:"
 $volume=Get-Volume -DriveLetter $Drive -ErrorAction Stop
 if($volume.FileSystem -ne 'FAT32'){throw ("Stick {0}: is {1}, not FAT32; the assets need more than the 2 GB-free FAT16 layout" -f $Drive,$volume.FileSystem)}
 $assets=Join-Path $repo 'assets'
 $files=@('booter_load_ga102.bin','v67-ga102-610.43.03.bin','gsp_ga10x.bin','gsp_boot_ga102.bin','gsp_boot_desc_ga102.bin')
 foreach($name in $files){ if(!(Test-Path -LiteralPath (Join-Path $assets $name))){throw "Missing asset $name; run the firmware generation first"} }
 $needed=($files | ForEach-Object {(Get-Item -LiteralPath (Join-Path $assets $_)).Length} | Measure-Object -Sum).Sum + $childBytes + (Get-Item -LiteralPath $bootEfi).Length
 if($volume.SizeRemaining -lt $needed+1048576){throw ("Stick has {0} bytes free, need {1}" -f $volume.SizeRemaining,$needed+1048576)}
 foreach($dir in @("$target\EFI\BOOT","$target\EFI\WindowsGPUUnlock","$target\RTX3090-UNLOCK\ASSETS")){
  [void][IO.Directory]::CreateDirectory($dir)
 }
 Copy-Item -LiteralPath $bootEfi -Destination "$target\EFI\BOOT\BOOTX64.EFI" -Force
 Copy-Item -LiteralPath $child -Destination "$target\EFI\WindowsGPUUnlock\UNLOCK-MULTI.EFI" -Force
 foreach($name in $files){Copy-Item -LiteralPath (Join-Path $assets $name) -Destination "$target\RTX3090-UNLOCK\ASSETS\$name" -Force}
 # Boot options live on the stick and are never overwritten: logging off is a
 # deliberate choice, and a rebuild must not silently turn it back on.
 $options="$target\RTX3090-UNLOCK\CONFIG.TXT"
 if(!(Test-Path -LiteralPath $options)){
  @('# Windows GPU UNLOCK boot options, read by BOOTX64.EFI and UNLOCK-MULTI.EFI.',
    '#',
    '# log = 1 : write RUNnn\REPORT.TXT and one MBxxx.TXT breadcrumb per boot (default)',
    '# log = 0 : write nothing; the unlock is identical, but a failed run leaves no evidence',
    '#',
    '# Values: 1/on/true/yes or 0/off/false/no. Trailing text after "#" is ignored.',
    'log = 1') | Set-Content -LiteralPath $options -Encoding ascii
  "Created CONFIG.TXT with logging on"
 } else {
  $line=Select-String -LiteralPath $options -Pattern '^\s*log\s*=' | Select-Object -Last 1
  if($line){"Kept CONFIG.TXT: $($line.Line.Trim())"} else {"Kept CONFIG.TXT (no log= line; default is on)"}
 }
 "Staged wrapper, child and 5 assets on ${Drive}:"
}
