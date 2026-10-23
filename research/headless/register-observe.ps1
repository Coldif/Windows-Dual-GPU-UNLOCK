# GPL-2.0-only. New manual observation entry only; preserve current boot priority.
param([switch]$Register)
$ErrorActionPreference='Stop'
$repo=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
. (Join-Path $repo 'internal-boot/install/automatic-policy.ps1')
$stateFile=Join-Path $PSScriptRoot 'registration.local.json'
$config=Get-Content -LiteralPath (Join-Path $repo 'internal-boot/local-config.json') -Raw | ConvertFrom-Json
function Bcd([string[]]$Arguments){$lines=@(& bcdedit @Arguments);if($LASTEXITCODE -ne 0){throw ('BCDEdit failed: '+($Arguments -join ' '))};return ($lines -join "`r`n")}
function Ids([string]$Text){return @([regex]::Matches($Text,'(?mi)^identifier\s+(\{[0-9a-f-]{36}\})') | ForEach-Object {$_.Groups[1].Value})}
function Order([string]$Text){
 $m=[regex]::Match($Text,'(?ms)^displayorder\s+(.*?)(?=\r?\n\S|\z)');if(!$m.Success){throw 'No firmware order'}
 $v=@([regex]::Matches($m.Groups[1].Value,'\{(?:bootmgr|[0-9a-f-]{36})\}') | ForEach-Object {$_.Value})
 if($v -notcontains '{bootmgr}' -or @($v | Select-Object -Unique).Count -ne $v.Count){throw 'Invalid firmware order'};return $v
}
function SetOrder([string[]]$Values){[void](Bcd (@('/set','{fwbootmgr}','displayorder')+$Values))}
function ExistsBcd([string]$Id){$null=& bcdedit /enum $Id;return $LASTEXITCODE -eq 0}
function Target {
 $p=Get-Partition -DriveLetter $config.UnlockDriveLetter;$d=Get-Disk -Number $p.DiskNumber;$v=$p | Get-Volume
 if($p.Guid -ne $config.UnlockPartitionGuid -or $p.IsSystem -or $p.Offset -ne $config.UnlockOffset -or $p.Size -ne $config.UnlockSize -or $d.UniqueId -ne $config.UnlockDiskUniqueId -or $p.GptType -ne '{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}' -or $v.FileSystem -ne 'FAT32' -or !$v.Path){throw 'Configured observation ESP identity changed'}
 return $v.Path
}
function CheckWindows {
 $w=@(Get-Partition | Where-Object {$_.Guid -eq $config.WindowsPartitionGuid})
 if($w.Count -ne 1 -or !$w[0].IsSystem -or $config.WindowsPartitionGuid -eq $config.UnlockPartitionGuid){throw 'Windows ESP identity changed'}
}
$root=Target
CheckWindows
if(Confirm-SecureBootUEFI){throw 'Unsigned observation EFI requires Secure Boot disabled'}
$encryption=Get-BitLockerVolume -MountPoint C:
if([int]$encryption.VolumeStatus -ne 0 -or [int]$encryption.ProtectionStatus -ne 0){throw 'Encryption state changed; observation installer does not change encryption settings'}
$m=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'build/manifest.json') -Raw | ConvertFrom-Json
if($m.Mode -ne 'headless-research-observation-only' -or $m.CanUnlock -ne $false -or $m.CanDetach -ne $false){throw 'Unexpected observation capabilities'}
$source=Join-Path $PSScriptRoot 'build/OBSERVE.EFI'
$hash='4c0672952a2b2f4a1e97520be1fe3332cc1a519efd9dbf5d3326ff900790988e'
if($m.EfiSha256 -ne $hash -or (Get-FileHash -LiteralPath $source).Hash -ne $hash){throw 'This registration requires the reviewed local observation image; different profiles need separate review'}
$target=Join-Path $root 'EFI\WindowsGPUUnlock\OBSERVE.EFI'
if(Test-Path -LiteralPath $target){if((Get-FileHash -LiteralPath $target).Hash -ne $hash){throw 'Different observation EFI exists; never overwrite'}}
else{[IO.File]::Copy($source,$target,$false)}
function CheckTarget {CheckWindows;if((Target) -ne $root -or (Get-FileHash -LiteralPath $target).Hash -ne $hash){throw 'Observation target changed'}}
CheckTarget
if(!$Register){Write-Output 'Observation EFI staged only; no boot entry/order changes.';return}
if(Test-Path -LiteralPath $stateFile){throw 'Registration state already exists; inspect it before registering again'}
$fw=Bcd @('/enum','{fwbootmgr}');$order=Order $fw;$manager=Bcd @('/enum','{bootmgr}');$firmwareBefore=Bcd @('/enum','firmware')
if($fw -match '(?mi)^bootsequence\s+'){throw 'Pending BootNext: observation registration refused'}
# Preserve every existing entry, including its device/path/description.
$existing=@{}
foreach($old in $order){$existing[$old]=Bcd @('/enum',$old)}
$beforeIds=Ids (Bcd @('/enum','all'));$reg=@{Id=$null}
$name='GPU Headless Observe - NO UNLOCK';$path='\EFI\WindowsGPUUnlock\OBSERVE.EFI'
$backup=Join-Path $env:ProgramData ('WindowsGPUUnlock\ResearchBackups\'+(Get-Date -Format 'yyyyMMdd-HHmmssfff'))
[void][IO.Directory]::CreateDirectory($backup)
[void](Bcd @('/export',(Join-Path $backup 'BCD-export')))
[IO.File]::WriteAllText((Join-Path $backup 'firmware-before.txt'),$firmwareBefore)
$state=[ordered]@{EntryId=$null;Name=$name;Path=$path;BackupRoot=$backup;BootOrderBefore=$order;EfiSha256=$hash;CanUnlock=$false;CanDetach=$false;Status='registering';HardwareTested=$false}
CheckTarget
if((Bcd @('/enum','{fwbootmgr}')) -cne $fw -or (Bcd @('/enum','firmware')) -cne $firmwareBefore){throw 'Firmware changed before registration'}
Invoke-AutomaticTransition -Steps @(
 {
  try{[void](Bcd @('/copy','{bootmgr}','/d',$name))}
  finally{
   $entries=@{}
   foreach($candidate in (Ids (Bcd @('/enum','all')))){if($beforeIds -notcontains $candidate){$entries[$candidate]=Bcd @('/enum',$candidate)}}
   $reg.Id=Resolve-NewBootCopy -BeforeIds $beforeIds -AfterEntries $entries -Source $manager -Name $name
  }
  $state.EntryId=$reg.Id
  $state | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $stateFile -Encoding utf8
 },
 {[void](Bcd @('/set',$reg.Id,'device',('partition='+$config.UnlockDriveLetter+':')))},
 {[void](Bcd @('/set',$reg.Id,'path',$path))},
 {SetOrder (@($order)+@($reg.Id))}
) -Verify {
 $after=Bcd @('/enum','{fwbootmgr}');$entry=Bcd @('/enum',$reg.Id)
 if(((Order $after) -join ',') -cne ((@($order)+@($reg.Id)) -join ',') -or $after -match '(?mi)^bootsequence\s+' -or $entry -notmatch ('(?mi)^path\s+'+[regex]::Escape($path)+'\s*$') -or $entry -notmatch ('(?m)^description\s+'+[regex]::Escape($name)+'\s*$') -or $entry -notmatch ('(?mi)^device\s+partition='+[regex]::Escape($config.UnlockDriveLetter)+':\s*$')){throw 'Observation entry verification failed'}
 foreach($old in $order){if((Bcd @('/enum',$old)) -cne $existing[$old]){throw 'Existing boot entry changed'}}
 CheckTarget
 $state.Status='registered';$state['RegisteredUtc']=[DateTime]::UtcNow.ToString('o')
 $state | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $stateFile -Encoding utf8
 $state | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $backup 'registration.json') -Encoding utf8
 [IO.File]::WriteAllText((Join-Path $backup 'firmware-after.txt'),(Bcd @('/enum','firmware')))
} -Rollback {
 Invoke-RecoveryActions -Actions @({SetOrder $order},{if($reg.Id -and (ExistsBcd $reg.Id)){[void](Bcd @('/delete',$reg.Id))}})
 if(!$reg.Id -or (Bcd @('/enum','{fwbootmgr}')) -cne $fw -or (ExistsBcd $reg.Id)){throw ('Recovery incomplete; inspect '+$backup)}
 foreach($old in $order){if((Bcd @('/enum',$old)) -cne $existing[$old]){throw ('Existing entry differs; inspect '+$backup)}}
 if(Test-Path -LiteralPath $stateFile){$owned=Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json;if($owned.EntryId -ne $reg.Id){throw 'State changed; refusing to remove it'};Remove-Item -LiteralPath $stateFile -ErrorAction Stop}
}
Write-Output "Registered $name at the end of F8 menu. Default order prefix preserved; no BootNext/reboot/BIOS changes. Backup: $backup"
