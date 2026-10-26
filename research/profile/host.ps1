# GPL-2.0-only. Host compiler setup shared by research/profile scripts. No GPU or firmware access.

function Import-GuHostCompiler([string]$VcVars) {
 if(!$VcVars) {
  $where=Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
  if(Test-Path -LiteralPath $where){$VcVars=& $where -latest -products * -find 'VC\Auxiliary\Build\vcvars64.bat' | Select-Object -First 1}
  if(!$VcVars){throw 'vcvars64.bat not found; pass -VcVars'}
 }
 $env:Path=(Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer')+';'+$env:Path
 $lines=& cmd.exe /d /c "call `"$VcVars`" >nul && set"
 if($LASTEXITCODE -ne 0){throw 'MSVC environment failed'}
 foreach($l in $lines){if($l -match '^([^=]+)=(.*)$'){[Environment]::SetEnvironmentVariable($matches[1],$matches[2],'Process')}}
}

# Host build of the production VBIOS parser; make-profile.py runs it on PROM.BIN.
function Build-GuFwsecLocate([string]$Repo,[string]$Clang) {
 $unlock=Join-Path $Repo 'internal-boot/unlock'
 $exe=Join-Path $Repo 'research/profile/build/fwsec-locate.exe'
 [void][IO.Directory]::CreateDirectory((Split-Path $exe))
 Push-Location -LiteralPath $unlock
 try {
  & $Clang -std=c11 -O1 -Wall -Wextra -Werror -Wno-unused-parameter -D_CRT_SECURE_NO_WARNINGS -D__KERNEL__ -DGU_UEFI_PORT -Icompat -I../../deps/edk2/MdePkg/Include -I../../deps/edk2/MdePkg/Include/X64 ../../research/profile/fwsec-locate.c vendor/vbios_610.c -o $exe
  if($LASTEXITCODE -ne 0){throw 'fwsec-locate compile failed'}
 } finally {Pop-Location}
 return $exe
}
