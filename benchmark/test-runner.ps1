# Host-only runner integration: synthetic managed executable and mocked nvidia-smi.
# Run with Windows PowerShell 5.1. No CUDA, real DLL loading or GPU access.
$ErrorActionPreference = 'Stop'
$testRoot = Join-Path $PSScriptRoot ('build\runner-tests-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
$stub = Join-Path $testRoot 'stub.exe'
Add-Type -OutputAssembly $stub -OutputType ConsoleApplication -TypeDefinition @'
using System;
public class BenchmarkStub {
    public static int Main(string[] args) {
        Console.WriteLine(Environment.GetEnvironmentVariable(
            args.Length == 1 && args[0] == "--inspect-only" ?
            "GPU_UNLOCK_TEST_INSPECT" : "GPU_UNLOCK_TEST_TRIAL"));
        return 0;
    }
}
'@
$oldInspect = $env:GPU_UNLOCK_TEST_INSPECT
$oldTrial = $env:GPU_UNLOCK_TEST_TRIAL
$oldTestState = Get-Variable -Name GpuUnlockRunnerTestState -Scope Global -ErrorAction SilentlyContinue
$global:GpuUnlockRunnerTestState = @{Calls=0;SettingsCalls=0;Scenario=''}
function nvidia-smi {
    $global:GpuUnlockRunnerTestState.Calls++
    Set-Variable -Name LASTEXITCODE -Scope 1 -Value 0
    # PowerShell functions receive comma-separated native arguments as arrays.
    $query = ($args | ForEach-Object { $_ }) -join ' '
    if ($query -like '*power.limit*') {
        $global:GpuUnlockRunnerTestState.SettingsCalls++
        $power = '350.00'
        if ($global:GpuUnlockRunnerTestState.Scenario -eq 'settings-change' -and $global:GpuUnlockRunnerTestState.SettingsCalls -gt 1) { $power = '300.00' }
        return "NVIDIA GeForce RTX 3090, 00000000:01:00.0, 617.14, $power, 2100, 9751"
    }
    if ($query -like '*utilization.gpu*') { return 'NVIDIA GeForce RTX 3090, 00000000:01:00.0, 617.14, 0, 100, 40' }
    if ($global:GpuUnlockRunnerTestState.Scenario -eq 'telemetry-failure') { throw 'Synthetic telemetry failure' }
    return 'synthetic telemetry'
}
try {
    $env:GPU_UNLOCK_TEST_INSPECT = '{"cuda_runtime":12060,"cublas_major":12,"cublas_minor":6,"cublas_patch":0,"gpu_workload_run":false}'
    $benchmarks = foreach ($name in @('fp32_pedantic','fp16_tensor_fp32_accumulate','bf16_tensor_fp32_accumulate')) {
        [pscustomobject]@{name=$name;n=4096;samples=30;warmup_seconds=2;median_ms=2;min_ms=1.9;max_ms=2.1;gflops=(2.0*4096*4096*4096/2e6);reference_checked=$true}
    }
    $env:GPU_UNLOCK_TEST_TRIAL = [pscustomobject]@{gpu='NVIDIA GeForce RTX 3090';pci='0000:01:00.0';compute_capability='8.6';cuda_runtime=12060;cuda_driver_api=13000;cublas=120600;benchmarks=@($benchmarks)} | ConvertTo-Json -Depth 5 -Compress
    foreach ($scenario in @('preflight','success','telemetry-failure','settings-change')) {
        $global:GpuUnlockRunnerTestState.Scenario = $scenario
        $global:GpuUnlockRunnerTestState.Calls = 0
        $global:GpuUnlockRunnerTestState.SettingsCalls = 0
        $caseRoot = Join-Path $testRoot $scenario
        New-Item -ItemType Directory -Path (Join-Path $caseRoot 'bin') | Out-Null
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'run-benchmark.ps1') -Destination $caseRoot
        Copy-Item -LiteralPath $stub -Destination (Join-Path $caseRoot 'bin\compute-benchmark-3090.exe')
        'not a DLL; hash fixture only' | Set-Content -LiteralPath (Join-Path $caseRoot 'bin\cublas64_12.dll') -Encoding utf8
        $manifest = foreach ($relative in @('bin\compute-benchmark-3090.exe','bin\cublas64_12.dll')) {
            [pscustomobject]@{Path=$relative;SHA256=(Get-FileHash -LiteralPath (Join-Path $caseRoot $relative)).Hash}
        }
        $manifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $caseRoot 'build-manifest.json') -Encoding utf8
        $failed = $false
        try {
            if ($scenario -eq 'preflight') { & (Join-Path $caseRoot 'run-benchmark.ps1') -PreflightOnly | Out-Null }
            else { & (Join-Path $caseRoot 'run-benchmark.ps1') | Out-Null }
        } catch {
            $failed = $true
            if ($scenario -notin @('telemetry-failure','settings-change')) { throw }
        }
        if ($scenario -eq 'preflight') {
            if ($global:GpuUnlockRunnerTestState.Calls -ne 0 -or (Test-Path (Join-Path $caseRoot 'results'))) { throw 'Preflight touched GPU queries or results' }
        } elseif ($scenario -eq 'success') {
            if ($failed) { throw 'Synthetic success failed' }
            $result = @(Get-ChildItem -LiteralPath (Join-Path $caseRoot 'results') -Directory)
            if ($result.Count -ne 1) { throw 'Expected one result directory' }
            # Exercise the real Python reader against PowerShell-produced BOM JSON.
            & python -c 'import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); from compare_results import load_run; load_run(Path(sys.argv[2]))' $PSScriptRoot $result[0].FullName
            if ($LASTEXITCODE -ne 0) { throw 'PowerShell evidence is not accepted by Python reader' }
        } else {
            if (-not $failed) { throw "Expected failure: $scenario" }
            if (Get-ChildItem -LiteralPath (Join-Path $caseRoot 'results') -Recurse -Filter comparison-complete.json) { throw 'Failed run produced completion record' }
        }
        Write-Output "PASS $scenario (synthetic host only)"
    }
    Write-Output "Evidence: $testRoot"
} finally {
    $env:GPU_UNLOCK_TEST_INSPECT = $oldInspect
    $env:GPU_UNLOCK_TEST_TRIAL = $oldTrial
    if ($null -ne $oldTestState) { $global:GpuUnlockRunnerTestState = $oldTestState.Value }
    else { Remove-Variable -Name GpuUnlockRunnerTestState -Scope Global }
}
