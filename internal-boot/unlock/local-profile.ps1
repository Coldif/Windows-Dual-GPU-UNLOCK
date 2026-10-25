# GPL-2.0-only. Local machine profile (-DGU_PROFILE_LOCAL) identity and its write-build evidence gate.
# Dot-sourced by build.ps1, research/headless/build-usb.ps1, stage-usb.ps1 and research/profile/test-profile.ps1.
# A generated profile-local.h is never write-eligible on its own: a write build needs
# research/profile/local/test-results.json from a passing test-profile.ps1 run against exactly
# this header, this machine's fixtures and this source tree.

function Get-GuSha256([string]$Path){(Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()}

function Get-LocalProfile([string]$Repo) {
 $header=Join-Path $Repo 'internal-boot/unlock/profile-local.h'
 if(!(Test-Path -LiteralPath $header)){throw 'No local profile: run research/profile/make-profile.py on this machine''s probe captures first'}
 $text=[IO.File]::ReadAllText($header)
 if($text -notmatch '(?m)^#define GU_LOCAL_PROFILE_GENERATOR [0-9]+$'){throw 'profile-local.h was not produced by research/profile/make-profile.py'}
 function Value([string]$Name,[string]$Pattern){
  $m=[regex]::Match($text,"(?m)^#define $Name $Pattern$")
  if(!$m.Success){throw "profile-local.h has no valid $Name"}
  return $m.Groups[1].Value
 }
 return [ordered]@{
  Define='-DGU_PROFILE_LOCAL';Name=(Value 'GU_PROFILE_NAME' '"(LOCAL-[0-9a-f]{8}-[0-9a-f]{8}-[0-9a-f]{8})"')
  TargetPci=(Value 'GU_BOARD_ID' '0x([0-9a-f]{8})U');Subsystem=(Value 'GU_BOARD_SUBSYSTEM' '0x([0-9a-f]{8})U')
  Chip=('0x'+(Value 'GU_CHIP_ID' '0x([0-9a-f]{8})U'));Prom=(Value 'GU_PROM_SHA256' '"([0-9a-f]{64})"')
  Memory=('0x'+(Value 'GU_DEVICE_MEMORY_SIZE' '0x([0-9a-f]+)U'));HeadlessOnly=$true;UsbOnly=$true
  HeaderSha256=(Get-GuSha256 $header)
 }
}

# Everything the host tests compile or that decides what they check. Local build inputs written
# by the build scripts themselves (platform-config.h, generated.h, build/) are excluded.
function Get-LocalTreeDigest([string]$Repo) {
 $rows=@()
 $roots=@(@('internal-boot/unlock','\.(c|h|py|json|ps1)$'),@('internal-boot/boot','\.(c|h|py|ps1)$'),@('research/profile','\.(c|py|json|ps1)$'))
 foreach($r in $roots) {
  $base=Join-Path $Repo $r[0]
  foreach($f in [IO.Directory]::EnumerateFiles($base,'*',[IO.SearchOption]::AllDirectories)) {
   $rel=$f.Substring($Repo.TrimEnd('\','/').Length+1).Replace('\','/')
   if($rel -match '(^|/)(build|local)/' -or $rel -notmatch $r[1]){continue}
   if($rel -in @('internal-boot/unlock/profile-local.h','internal-boot/boot/platform-config.h','internal-boot/boot/generated.h')){continue}
   $rows+="$rel $(Get-GuSha256 $f)"
  }
 }
 $bytes=[Text.Encoding]::UTF8.GetBytes((($rows | Sort-Object -CaseSensitive) -join "`n")+"`n")
 $sha=[Security.Cryptography.SHA256]::Create()
 try{return (($sha.ComputeHash($bytes) | ForEach-Object {$_.ToString('x2')}) -join '')}finally{$sha.Dispose()}
}

function Assert-LocalProfileEvidence([string]$Repo) {
 $hw=Get-LocalProfile $Repo
 $local=Join-Path $Repo 'research/profile/local'
 $path=Join-Path $local 'test-results.json'
 if(!(Test-Path -LiteralPath $path)){throw "Local profile $($hw.Name) has no passing host-test evidence; run research/profile/test-profile.ps1"}
 $e=Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
 if($e.Format -ne 1 -or $e.AllPassed -ne $true -or $e.HardwareAccess -ne $false -or $e.ProfileName -ne $hw.Name){throw 'Local profile test evidence is not a complete pass for this profile'}
 if($e.HeaderSha256 -ne $hw.HeaderSha256){throw 'profile-local.h changed after its host tests passed; rerun research/profile/test-profile.ps1'}
 if($e.PromSha256 -ne $hw.Prom){throw 'Local test evidence is for another PROM'}
 foreach($f in $e.Fixtures.PSObject.Properties) {
  $p=Join-Path $local ('fixtures/'+$f.Name)
  if(!(Test-Path -LiteralPath $p) -or (Get-GuSha256 $p) -ne $f.Value){throw "Local fixture $($f.Name) changed after its host tests passed"}
 }
 if((Get-GuSha256 (Join-Path $local 'fixtures/PROM.BIN')) -ne $hw.Prom){throw 'Local PROM fixture does not match the profile PROM hash'}
 if($e.TreeSha256 -ne (Get-LocalTreeDigest $Repo)){throw 'Sources or tests changed after the local host tests passed; rerun research/profile/test-profile.ps1'}
 return $e
}
