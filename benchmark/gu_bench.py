#!/usr/bin/env python3
# GPL-2.0-only. Measure the same cards twice and compare the two boots.
#
#   python benchmark\gu_bench.py -Label unlocked
#   python benchmark\gu_bench.py -Label normal
#   python benchmark\gu_bench.py -Compare unlocked normal
#
# gu-compute-benchmark.exe does the GPU work and prints one JSON record per
# card; this script only drives it, checks the machine is idle, and stores the
# runs. JSON, subprocess timeouts and process handling are Python's, so there
# is no PowerShell object graph and nothing to serialize twice.
#
# What the numbers mean:
#   fp32_pedantic              SGEMM on CUDA cores (clock sanity reference)
#   fp16 / bf16 / tf32 tensor  tensor-core paths with FP32 accumulate
#   d2d_copy                   device-to-device bandwidth (memory path)
#   memory_alloc_max           largest buffer the card allocated AND wrote
#
# The unlock is volatile and does not change the silicon, so the same card on
# an unlocked boot and on a normal boot should measure the same. A gap outside
# the run-to-run noise, or a card that only enumerated in one boot, is the
# finding - not a speed-up.

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "gu-compute-benchmark.cu"
EXE = ROOT / "bin" / "gu-compute-benchmark.exe"
DEFAULT_OUT = Path.home() / "Windows-GPU-DIAG" / "BENCH"
SMI = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "nvidia-smi.exe"
QUERY = ("index,pci.bus_id,uuid,name,memory.total,memory.used,"
         "utilization.gpu,temperature.gpu,power.draw,clocks.sm,driver_version")
RUN_TIMEOUT = 900


def die(message):
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def invoke(command, timeout=RUN_TIMEOUT, env=None):
    """Run a command and return its output; a hung child is killed, not waited on."""
    try:
        done = subprocess.run(command, capture_output=True, text=True, errors="replace",
                              timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        die(f"timed out after {timeout} s: {' '.join(map(str, command))}")
    return done


def find_vcvars():
    if os.environ.get("VSCMD_VER"):
        return None
    candidates = [
        r"C:\Program Files\Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvars64.bat",
        r"C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat",
        r"C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat",
        r"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat",
        r"C:\Program Files (x86)\Microsoft Visual Studio\2019\Enterprise\VC\Auxiliary\Build\vcvars64.bat",
        r"C:\Program Files (x86)\Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvars64.bat",
    ]
    vswhere = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe")
    if vswhere.exists():
        found = invoke([str(vswhere), "-latest", "-products", "*",
                        "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
                        "-property", "installationPath"], timeout=60).stdout.strip()
        if found:
            candidates.insert(0, str(Path(found) / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"))
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    die("no vcvars64.bat found; nvcc on Windows needs an MSVC host compiler (pass -VcVars)")


def host_environment(vcvars):
    """Import vcvars into a copy of this process environment only."""
    env = dict(os.environ)
    if not vcvars:
        return env
    done = invoke([os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c",
                   f'call "{vcvars}" >nul 2>&1 && set'], timeout=120)
    for line in done.stdout.splitlines():
        if "=" not in line or line.startswith("="):
            continue
        name, _, value = line.partition("=")
        if re.match(r"^[A-Za-z_][A-Za-z0-9_()]*$", name):
            env[name] = value
    return env


def find_nvcc():
    found = shutil.which("nvcc")
    if found:
        return found
    for base in (os.environ.get("CUDA_PATH"), r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.8"):
        if base and (Path(base) / "bin" / "nvcc.exe").exists():
            return str(Path(base) / "bin" / "nvcc.exe")
    die("nvcc.exe not found; install the CUDA toolkit or put it in PATH")


def build(args):
    nvcc = find_nvcc()
    env = host_environment(args.vcvars or find_vcvars())
    code = args.arch[3:] if args.arch.startswith("sm_") else args.arch
    EXE.parent.mkdir(parents=True, exist_ok=True)
    print(f"building {SOURCE.name} for {args.arch}")
    done = invoke([nvcc, "-std=c++17", "-O3",
                   "-gencode", f"arch=compute_{code},code=sm_{code}",
                   "-gencode", f"arch=compute_{code},code=compute_{code}",
                   "-Xcompiler", "/utf-8", "-o", str(EXE), str(SOURCE), "-lcublas"],
                  timeout=900, env=env)
    if done.returncode != 0:
        print(done.stdout[-4000:])
        print(done.stderr[-4000:], file=sys.stderr)
        die(f"nvcc failed (exit {done.returncode})")
    for line in (done.stdout + done.stderr).splitlines():
        if "warning" in line.lower():
            print(line)


def smi(fmt="csv,noheader,nounits"):
    if not SMI.exists():
        return []
    done = invoke([str(SMI), f"--query-gpu={QUERY}", f"--format={fmt}"], timeout=60)
    return [line.strip() for line in done.stdout.splitlines() if line.strip()]


def field(row, index):
    parts = [part.strip() for part in row.split(",")]
    if index >= len(parts) or not parts[index].isdigit():
        return 0
    return int(parts[index])


def assert_idle(force):
    rows = []
    for attempt in range(6):
        rows = smi()
        if not rows or not any(field(row, 6) > 5 for row in rows):
            break
        if attempt == 0:
            print("waiting up to 10 s for the GPUs to go idle...")
        time.sleep(2)
    if not rows:
        return []
    print()
    for row in rows:
        parts = [part.strip() for part in row.split(",")]
        if len(parts) < 8:
            print(f"  {row}")
            continue
        print(f"  {parts[0]}  {parts[1]}  {parts[2]}  {field(row, 9)} MHz  "
              f"{field(row, 7)} C  util {field(row, 6)}%  {field(row, 5)} MiB")
    apps = []
    if SMI.exists():
        done = invoke([str(SMI), "--query-compute-apps=pid,process_name,used_memory",
                       "--format=csv,noheader"], timeout=60)
        for line in done.stdout.splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) >= 3 and parts[2].isdigit() and int(parts[2]) > 0:
                apps.append(line)
    if apps:
        print("\ncompute processes are using the GPUs:")
        for line in apps:
            print(f"  {line}")
    hot = [row for row in rows if field(row, 7) >= 85]
    busy = [row for row in rows if field(row, 6) > 5]
    if hot or busy or apps:
        if not force:
            die("GPUs are not idle or are hot; close the load and retry, or pass -Force")
        print("-Force: measuring anyway.")
    return rows


def unlock_evidence():
    """The stick is evidence, not proof: it can be pulled before Windows boots."""
    stick = None
    for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
        candidate = Path(f"{letter}:\\RTX3090-UNLOCK")
        try:
            if candidate.is_dir():
                stick = candidate
                break
        except OSError:
            continue
    if stick is None:
        return None
    runs = sorted((p for p in stick.glob("RUN*") if p.is_dir()), key=lambda p: p.name)
    evidence = {"stick": str(stick), "run": None, "final": None,
                "report_sha256": None, "report_time": None, "breadcrumb": None}
    if runs:
        run = runs[-1]
        evidence["run"] = run.name
        report = run / "REPORT.TXT"
        if report.exists():
            text = report.read_text(encoding="utf-8", errors="replace")
            for line in reversed(text.splitlines()):
                if line.startswith("FINAL "):
                    evidence["final"] = line.strip()
                    break
            evidence["report_sha256"] = hashlib.sha256(report.read_bytes()).hexdigest()
            evidence["report_time"] = datetime.fromtimestamp(
                report.stat().st_mtime).astimezone().isoformat()
    crumbs = sorted((p for p in stick.glob("MB*.TXT") if p.is_file()), key=lambda p: p.name)
    if crumbs:
        crumb = crumbs[-1]
        evidence["breadcrumb"] = {
            "name": crumb.name,
            "lines": [line for line in crumb.read_text(encoding="utf-8", errors="replace").splitlines()
                      if line.strip()],
            "time": datetime.fromtimestamp(crumb.stat().st_mtime).astimezone().isoformat(),
        }
    return evidence


def save_run(run, out_dir, label):
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", label)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    final = out_dir / f"{safe}-{stamp}.json"
    text = json.dumps(run, indent=2, ensure_ascii=True)
    final.write_text(text + "\n", encoding="utf-8")
    shutil.copyfile(final, out_dir / f"latest-{safe}.json")
    return final


def resolve(name, out_dir):
    path = Path(name)
    if path.is_file():
        return path
    candidate = out_dir / f"latest-{re.sub(r'[^A-Za-z0-9_.-]', '_', name)}.json"
    if candidate.is_file():
        return candidate
    die(f"no saved run '{name}' (looked for {candidate})")


def row(metric, left, right, change, left_flops="-", right_flops="-"):
    print(f"{metric:<38} {left:>11} {right:>11} {change:>9} {left_flops:>11} {right_flops:>11}")


def change_text(left, right):
    if not left:
        return "-"
    return f"{(right / left - 1.0) * 100.0:+.1f}%"


def compare(names, out_dir):
    left_path = resolve(names[0], out_dir)
    right_path = resolve(names[1], out_dir)
    left = json.loads(left_path.read_text(encoding="utf-8-sig"))
    right = json.loads(right_path.read_text(encoding="utf-8-sig"))
    print()
    print(f"A = {left.get('label')}   ({left_path})")
    print(f"B = {right.get('label')}   ({right_path})")
    if left.get("exe_sha256") != right.get("exe_sha256"):
        print("WARNING: different benchmark binaries")
    tool = lambda run: "/".join(str(run["devices"][0][k]) for k in
                                ("cuda_runtime", "cuda_driver_api", "cublas"))
    if tool(left) != tool(right):
        print(f"WARNING: different CUDA/cuBLAS/driver API ({tool(left)} vs {tool(right)})")
    by_uuid = {device["uuid"]: device for device in right["devices"]}
    missing = 0
    for a in left["devices"]:
        b = by_uuid.get(a["uuid"])
        print()
        print(f"--- {a['pci']}  {a['gpu']}  {a['uuid']} ---")
        if b is None:
            print("  THIS CARD IS MISSING FROM B: it did not enumerate on that boot.")
            missing += 1
            continue
        row("metric", "A", "B", "B vs A", "A TFLOP/s", "B TFLOP/s")
        for mode_a in a["benchmarks"]:
            mode_b = next((m for m in b["benchmarks"] if m["name"] == mode_a["name"]), None)
            if mode_b is None:
                continue
            row(f"{mode_a['name']} ms", f"{mode_a['median_ms']:.3f}",
                f"{mode_b['median_ms']:.3f}",
                change_text(mode_a["median_ms"], mode_b["median_ms"]),
                f"{mode_a['gflops'] / 1000.0:.1f}",
                f"{mode_b['gflops'] / 1000.0:.1f}")
        row("d2d_copy GB/s", f"{a['d2d_copy']['median_gbps']:.1f}",
            f"{b['d2d_copy']['median_gbps']:.1f}",
            change_text(a["d2d_copy"]["median_gbps"], b["d2d_copy"]["median_gbps"]))
        row("memory_alloc_max MiB", f"{a['memory_alloc_max']['allocated_mib']:.0f}",
            f"{b['memory_alloc_max']['allocated_mib']:.0f}",
            change_text(a["memory_alloc_max"]["allocated_mib"],
                        b["memory_alloc_max"]["allocated_mib"]))
    for b in right["devices"]:
        if b["uuid"] not in {a["uuid"] for a in left["devices"]}:
            print()
            print(f"--- {b['pci']}  {b['gpu']}  {b['uuid']} ---")
            print("  THIS CARD IS MISSING FROM A: it did not enumerate on that boot.")
            missing += 1
    print()
    print("Read it as: the unlock does not change the silicon, so the same card should")
    print("measure the same on both boots. A gap far outside run-to-run noise, or a card")
    print("that only exists in one run, is the finding.")
    return 1 if missing else 0


def main():
    parser = argparse.ArgumentParser(description="Two-boot compute benchmark for the RTX 3060 pair")
    parser.add_argument("-Label", "--label", default="session")
    parser.add_argument("-Compare", "--compare", nargs=2, metavar=("A", "B"))
    parser.add_argument("-Rebuild", "--rebuild", action="store_true")
    parser.add_argument("-Force", "--force", action="store_true")
    parser.add_argument("-Device", "--device")
    parser.add_argument("-Arch", "--arch", default="sm_86")
    parser.add_argument("-Trials", "--trials", type=int, default=3)
    parser.add_argument("-Samples", "--samples", type=int, default=25)
    parser.add_argument("-OutDir", "--outdir", default=str(DEFAULT_OUT))
    parser.add_argument("-VcVars", "--vcvars")
    args = parser.parse_args()
    out_dir = Path(args.outdir)

    if args.compare:
        return compare(args.compare, out_dir)

    if args.rebuild or not EXE.exists() or SOURCE.stat().st_mtime > EXE.stat().st_mtime:
        build(args)

    if os.environ.get("NVIDIA_TF32_OVERRIDE"):
        die("unset NVIDIA_TF32_OVERRIDE: it would make fp32_pedantic mean something else")
    probe = json.loads(invoke([str(EXE), "--inspect-only"], timeout=120).stdout)
    if not probe["tf32_allowed"]:
        die("the benchmark reports TF32 overrides enabled; refusing to run")
    print(f"CUDA runtime {probe['cuda_runtime']}, driver API {probe['cuda_driver_api']}, "
          f"cuBLAS {probe['cublas_major']}.{probe['cublas_minor']}.{probe['cublas_patch']}, "
          f"{probe['device_count']} device(s)")

    before = assert_idle(args.force)
    devices = json.loads(invoke([str(EXE), "--list"], timeout=120).stdout)
    if args.device:
        devices = [d for d in devices
                   if args.device in (d["pci"], d["uuid"], str(d["index"]))]
        if not devices:
            die(f"no device matched '{args.device}'")
    if not devices:
        die("no CUDA devices found")

    evidence = unlock_evidence()
    if evidence:
        print(f"stick evidence: {evidence['run']} / {evidence['final']}")
        if "ALL TARGETS UNLOCKED" not in (evidence["final"] or ""):
            print("WARNING: the last UEFI run on the stick did not report success.")
    else:
        print("stick evidence: none (stick removed, or this was a normal boot)")

    records = []
    for device in devices:
        print()
        print(f"measuring {device['gpu']} at {device['pci']} ({device['uuid']})...")
        done = invoke([str(EXE), "--device", device["pci"],
                       "--trials", str(args.trials), "--samples", str(args.samples)])
        if done.returncode != 0:
            print(done.stderr[-2000:], file=sys.stderr)
            die(f"benchmark failed on {device['pci']} (exit {done.returncode})")
        record = json.loads(done.stdout)
        records.append(record)
        for mode in record["benchmarks"]:
            print(f"  {mode['name']:<32} {mode['median_ms']:9.3f} ms  "
                  f"{mode['gflops'] / 1000.0:8.1f} TFLOP/s")
        print(f"  {'d2d_copy':<32} {record['d2d_copy']['median_gbps']:9.1f} GB/s")
        print(f"  {'memory_alloc_max':<32} {record['memory_alloc_max']['allocated_mib']:9.0f} MiB")

    after = smi()
    nvcc_version = ""
    done = invoke([find_nvcc(), "--version"], timeout=60)
    for line in done.stdout.splitlines():
        if "release" in line:
            nvcc_version = line.strip()
            break

    run = {
        "schema": 1,
        "label": args.label,
        "created": datetime.now().astimezone().isoformat(),
        "benchmark_protocol": 3,
        "exe_sha256": hashlib.sha256(EXE.read_bytes()).hexdigest(),
        "exe_path": str(EXE),
        "arch": args.arch,
        "trials": args.trials,
        "samples_per_trial": args.samples,
        "host": {
            "machine": os.environ.get("COMPUTERNAME"),
            "os": platform.platform(),
            "nvcc": nvcc_version,
        },
        "unlock_evidence": evidence,
        "nvidia_smi_before": before,
        "nvidia_smi_after": after,
        "nvidia_smi_query": QUERY,
        "devices": records,
    }
    saved = save_run(run, out_dir, args.label)
    print()
    print(f"saved {saved}")
    print(f"compare with: python benchmark\\gu_bench.py -Compare {args.label} <other-label>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
