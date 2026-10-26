# GPL-2.0-only. Run the B660-PLUS two-child console graph replay in WebAssembly.
# The host never loads an unsigned Windows test executable or touches firmware.
param(
 [string]$Clang='clang',
 [string]$Node='node'
)
$ErrorActionPreference='Stop'
Push-Location -LiteralPath $PSScriptRoot
try {
 if(!(Get-Command -Name $Clang -CommandType Application -ErrorAction SilentlyContinue)){throw "clang unavailable: $Clang"}
 if(!(Get-Command -Name $Node -CommandType Application -ErrorAction SilentlyContinue)){throw "Node unavailable: $Node"}
 $build='build/aggregate-b660plus'
 New-Item -ItemType Directory -Path "$build/include" -Force | Out-Null
 @(
  '#define GU_INTERNAL_PARTITION_INITIALIZER {0x11111111,0x2222,0x3333,{0x44,0x55,0x66,0x77,0x88,0x99,0xaa,0xbb}}',
  '#define GU_WINDOWS_PARTITION_INITIALIZER {0xaaaaaaaa,0xbbbb,0xcccc,{0xdd,0xee,0xff,0,0x11,0x22,0x33,0x44}}'
 ) | Set-Content -LiteralPath "$build/include/platform-config.h" -Encoding ascii
 $common=@('-std=c11','-O1','-Wall','-Wextra','-Werror','-ffreestanding','-fno-builtin',
           '-fno-stack-protector','-fshort-wchar','-DGU_PROFILE_B660PLUS_3060','-DGU_HEADLESS_RESEARCH',
           '-DGU_SINGLE_RTX_CONSOLE','-DGU_FULL_UNLOCK','-DGU_AUTOMATIC_BOOT',
           '-I',"$build/include",'-I','../../deps/edk2/MdePkg/Include')
 & $Clang '-target' 'x86_64-pc-windows-msvc' @common '-I' '../../deps/edk2/MdePkg/Include/X64' '-fsyntax-only' 'full-release.c'
 if($LASTEXITCODE -ne 0){throw 'x64 UEFI source compile failed'}
 $wasm=@('--target=wasm32-unknown-unknown')+$common+@('-I','../../deps/edk2/MdePkg/Include/Ia32')
 foreach($source in @('test_aggregate_graph_b660plus.c','../unlock/checks.c','../unlock/sha256.c')) {
  $name=[IO.Path]::GetFileNameWithoutExtension($source)
  & $Clang @wasm '-c' $source '-o' "$build/$name.wasm.o"
  if($LASTEXITCODE -ne 0){throw "Graph replay compile failed: $source"}
 }
 $link=@('--target=wasm32-unknown-unknown','-nostdlib','-Wl,--no-entry',
         '-Wl,--export=mainCRTStartup','-Wl,--initial-memory=1310720','-o',"$build/test_aggregate_graph_b660plus.wasm",
         "$build/test_aggregate_graph_b660plus.wasm.o","$build/checks.wasm.o","$build/sha256.wasm.o")
 & $Clang @link
 if($LASTEXITCODE -ne 0){throw 'Graph replay link failed'}
 $runner="$build/run.js"
 @(
  'const fs=require("fs");',
  'const b=fs.readFileSync(process.argv[2]);',
  'WebAssembly.instantiate(b,{}).then(({instance})=>process.exit(instance.exports.mainCRTStartup())).catch(e=>{console.error(e);process.exit(99)});'
 ) | Set-Content -LiteralPath $runner -Encoding ascii
 & $Node $runner "$build/test_aggregate_graph_b660plus.wasm"
 if($LASTEXITCODE -ne 0){throw "Graph replay failed at invariant $LASTEXITCODE"}
 Write-Output 'PASS B660-PLUS two-child console graph replay; no firmware or GPU access'
} finally {Pop-Location}
