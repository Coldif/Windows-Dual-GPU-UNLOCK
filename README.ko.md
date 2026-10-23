# Windows GPU UNLOCK

> **연구 브랜치 `research/single-gpu-headless`:** RTX 물리 GOP 하나만 활성화된
> 상태에서 관찰용 EFI를 거쳐 Windows에 진입한 R1 결과를 확인했습니다.
> F8에서 선택하면 추가 키 입력 없이 진행하는 R2 시험 EFI를 준비했습니다. 언락과 NVIDIA GOP 제거는
> 수행하지 않으며 R2의 실제 해제 결과는 아직 미확인입니다.
> [실기 근거와 다음 단계](research/headless/README.ko.md#r1-실기-관찰-결과--2026-10-24).
> 기존 기본 부팅 우선순위와 main 릴리스는 유지합니다.

[English](README.md) | **한국어**

## 처음 시작하기: USB 또는 내부 파티션 선택

이 프로젝트는 **지원 조건이 일치하는 RTX 3090 / ASUS BIOS 3057 / AMD 내장그래픽**
환경을 위한 실험입니다. 먼저 [지원 조건](docs/COMPATIBILITY.ko.md)을 확인하세요.
소스 `.c` 파일만 USB에 복사해서 실행하는 방식이 아닙니다. **실행용 `.EFI`와
펌웨어 5개**가 필요합니다. 기존 파일은 먼저 백업합니다.

| 원하는 방식 | 저장 위치 | 부팅 흐름 | 안내 |
|---|---|---|---|
| USB로 먼저 수동 시험 | FAT32 USB | USB 부팅 → U → BIOS Boot Override → Windows | [USB 가이드](docs/GUIDE.ko.md) |
| USB 없이 사용·자동 연결 | 별도 FAT32 EFI 파티션 | 내부 EFI → 언락 → Windows 직접 진입 | [파티션·자동 부팅 가이드](docs/INTERNAL-BOOT.ko.md) |

### A. USB에 저장하고 수동으로 실행

1. **준비** — [릴리스](https://github.com/impacifist/Windows-GPU-UNLOCK/releases)에서
   소스를 받거나 저장소를 clone합니다. [펌웨어 준비 안내](docs/ASSETS.ko.md)에 따라
   필요한 5개 파일을 로컬 `assets/` 폴더에 둡니다.
2. **USB용 폴더 생성** — 저장소 폴더에서 아래 명령을 실행합니다. USB를 직접
   포맷하거나 쓰지는 않으며, 기존 `usb-package`가 있으면 새 경로를 지정합니다.

   ```powershell
   python .\tools\prepare_usb.py --assets .\assets --output .\usb-package
   ```

3. **USB로 복사** — `usb-package` **안의 내용**을 FAT32 USB 최상위에 복사합니다.
   `USB:/EFI/BOOT/BOOTX64.EFI`와 `USB:/RTX3090-UNLOCK/ASSETS/`가 있어야 합니다.
4. **언락 실행** — 작업 저장 → 완전 종료 후 켜기 → ASUS F8 → UEFI USB 선택 →
   사전 검사 통과 후 **U 한 번**.
5. **Windows로 연결** — 성공·정리 완료 후 ASUS BIOS의 **Boot Override → Windows
   Boot Manager**를 선택합니다. 중간에 `Save Changes & Reset`이나 재부팅을 하지 않습니다.
6. **성능 확인** — Windows에서 [FP16/BF16 벤치마크](docs/BENCHMARK.ko.md)를 실행합니다.

**이 USB판은 수동판입니다.** BIOS 순서를 `USB → Windows`로 바꾸는 것만으로
리셋 없는 자동 인계가 구현되지는 않습니다. 자동 연결을 원하면 아래 B를 사용하세요.

### B. 내부 파티션에 저장하고 언락 → Windows로 설정

1. **별도 저장 공간 준비** — 기존 Windows EFI·복구 파티션을 보존하고, **별도 1GiB
   이상 FAT32 EFI 파티션**을 준비합니다. 예: U:. [파티션 준비 절차](docs/INTERNAL-BOOT.ko.md#2-별도-파티션-준비)를 먼저 따릅니다.
2. **내 PC에 맞게 빌드** — 기존 Windows ESP의 GUID와 새 파티션 문자를 지정해
   `Configure.ps1`을 실행한 뒤 `Build.ps1`로 실행 파일을 만듭니다.
   [설정·빌드 명령](docs/INTERNAL-BOOT.ko.md#3-소스-받기와-로컬-설정)을 그대로 따라가세요.
3. **파일 배치·수동 항목 등록** — `Install.ps1 -Assets <펌웨어폴더>`로 EFI와 자산을
   배치하고, `-RegisterManual`로 시험 항목을 만듭니다. Windows는 계속 첫 번째입니다.
   [정확한 명령과 파일 위치](docs/INTERNAL-BOOT.ko.md#5-파일-설치와-수동-항목-등록).
4. **먼저 한 번 수동 시험** — 완전 종료 후 F8 → **Windows GPU UNLOCK Manual** →
   원본 앱이 나오면 U 한 번. **재부팅 없이 Windows 진입과 FP16/BF16 성능**을 확인합니다.
5. **자동 부팅으로 전환** — 수동 시험에 성공한 뒤 다음 명령을 실행합니다.

   ```powershell
   .\internal-boot\Install.ps1 -Assets 'C:\LOCAL-FIRMWARE\assets' `
     -EnableAutomaticBoot -ConfirmedManualSuccess
   ```

6. **다음부터 키 입력 없이 부팅** — 순서가 **Windows GPU UNLOCK Auto → Windows
   Boot Manager**로 설정됩니다. 완전 종료 후 켜고 기다리면 자동 실행 경로를 탑니다.
   처음 5초 안에 Esc를 누르면 언락 없이 Windows만 부팅합니다.

자동판은 **첫 실제 자동 부팅이 아직 미검증인 실험 기능**입니다. 첫 자동 부팅의 Windows
진입과 성능을 직접 확인해야 합니다. 수동 직접 인계는 실제 성공을 확인했습니다.
문제가 생기면 전원을 완전히 끈 뒤 **F8 → Windows Boot Manager**로 복귀합니다.
Windows에서 [자동 부팅 원복 명령](docs/INTERNAL-BOOT.ko.md#8-자동-부팅-원복)을 실행하면
Windows를 다시 첫 번째로 돌릴 수 있습니다. 절전·최대 절전 복귀는 검증 범위가 아닙니다.

## 내부 디스크 방식의 구현·검증 현황

**[단계별 내부 디스크 설치·자동 부팅·복구 가이드](docs/INTERNAL-BOOT.ko.md)**

2026-10-23, 같은 ASUS BIOS 3057 / RTX 3090 환경에서 내부 EFI가 드라이버를 정리하고
U 한 번 뒤 Windows로 직접 이어지는 경로를 확인했습니다. 3회 중앙값은 FP16
**125.91**, BF16 **128.93 TFLOPS**입니다. [원자료](evidence/internal-handoff/summary.json).

`internal-boot/`에는 출력 경로 자동 식별, 제한된 PCI 상태 비교, 자세한 인계 오류,
**U 없는 자동 부팅용 별도 소스**와 설치·원복 도구가 있습니다. 자동판은 host 검사와
로컬 설치까지 검증했으며 **첫 실제 자동 부팅은 아직 미검증**입니다. 다른 보드/BIOS
지원은 추가하지 않았습니다. 자신의 파티션 설정으로 빌드하고 수동 시험부터 진행하세요.
아래 USB 절차와 기존 `release/` EFI는 계속 수동판입니다.

RTX 3090의 Windows Tensor 연산 성능 향상을 확인한 UEFI 실험 코드와 재현 가이드입니다. [rough2515-hub/rtx3080-unlock-public](https://github.com/rough2515-hub/rtx3080-unlock-public/tree/a08254d269af30ace9e57237abd3d8e6c261e8f5)의 RTX 3080 포트를 바탕으로 RTX 3090 24GiB / AMD 내장그래픽 환경에 맞췄습니다. 원천 코어는 [Zagitta/gpu-unlock](https://github.com/Zagitta/gpu-unlock/tree/0ebdb1c6308b6a2072be5bf04513472942541956)입니다.

**핵심: 언락 성공 후 재부팅하지 않고 Windows Boot Manager로 이어서 부팅합니다.** ASUS에서 `Save Changes & Reset`을 누르면 다시 초기화될 수 있습니다. 이번 성공 사례는 `Boot Override → Windows Boot Manager`를 사용했습니다.

## 실제 측정 결과

2026-10-20, 동일한 CUDA 12.6 / cuBLAS 12.6 실행 파일로 각각 3회 실행한 중앙값입니다. NVIDIA Windows 드라이버 **617.14를 교체하지 않았습니다**.

| 항목 | 이전 경로 TFLOPS | 리셋 없이 Windows 진입 TFLOPS | 변화 |
|---|---:|---:|---:|
| FP32 pedantic | 24.505702 | 24.890281 | +1.57% |
| FP16 Tensor / FP32 누산 | 70.548081 | 125.907816 | +78.47% |
| BF16 Tensor / FP32 누산 | 70.529545 | 128.699728 | +82.48% |

이전 측정도 UEFI에서 언락 성공을 보고한 뒤의 값입니다. 미적용 콜드부팅 기준을 별도로 통제한 실험은 아닙니다. 사용자가 이전에는 BIOS에서 Reset했고 이번에는 Boot Override로 리셋 없이 진입했다고 확인했습니다. 결과는 부팅 인계 문제가 원인이었다는 가설을 강하게 뒷받침하지만, 다른 모든 원인을 배제하는 실험은 아닙니다. ComfyUI·게임 향상률과 장시간 안정성은 별도 검증이 필요합니다. [측정 원자료와 한계](docs/RESULTS.ko.md).

## 먼저 지원 조건 확인

**현재 실행 코드는 특정 PC에 고정된 실험 포트입니다. 모든 RTX 3090이나 RTX 30 시리즈에서 그대로 실행되는 범용 프로그램이 아닙니다.** 다른 시스템에서는 검사가 거부되는 것이 정상일 수 있습니다. 검사를 삭제하거나 숫자만 자신의 GPU 값으로 바꿔 실행하지 마세요.

검증 환경:

- NVIDIA RTX 3090 24GiB: PCI `10de:2204`, subsystem `10de:1454`, BDF `0000:01:00.0`.
- ASUS TUF GAMING B650M-PLUS WIFI, AMD Ryzen 7 7800X3D.
- AMD 내장그래픽 PCI `1002:164e`, subsystem `1043:8877`. 모니터는 메인보드 출력에 연결.
- Windows 11 Home build 26200, NVIDIA 617.14.
- x64 UEFI, Secure Boot 꺼짐, FAT32 USB.
- 프로필 `entryLatchedSs1Full`: SS0 `0x88888888`, SS1 `0x8`.
- PROM 해시·BAR·GOP 경로 등 추가 고정 조건: [지원 범위](docs/COMPATIBILITY.ko.md).

## 따라 하기

1. [USB 준비 가이드](docs/GUIDE.ko.md)에서 환경과 파일 구성을 확인합니다. 기존 USB 파일을 먼저 백업합니다.
2. 공개된 EFI 또는 [직접 빌드한 EFI](docs/BUILD.ko.md)를 FAT32 USB의 `EFI/BOOT/BOOTX64.EFI`에 둡니다.
3. 별도 준비한 펌웨어 5개를 `RTX3090-UNLOCK/ASSETS/`에 둡니다. [펌웨어 준비](docs/ASSETS.ko.md). 펌웨어는 이 저장소와 릴리스에 포함하지 않습니다.
4. Windows 작업을 저장하고 완전히 종료한 뒤, 모니터를 메인보드에 연결한 상태로 전원을 켭니다.
5. ASUS F8 → UEFI USB → 사전 검사 통과 → **U 한 번**.
6. 성공과 정리 완료를 확인하고 펌웨어로 돌아오면 **F7 → Advanced Mode → Boot → Boot Override → Windows Boot Manager**.
7. **이 사이에 F10 / Save Changes & Reset / 재부팅을 하지 않습니다.**
8. Windows에서 GPU를 사용하는 다른 프로그램을 종료한 상태로 [동일 벤치마크](docs/BENCHMARK.ko.md)를 실행해 비교합니다.

`STOP / POWER OFF` 또는 실패가 나오면 Windows로 이어서 진행하지 말고 전원을 완전히 끈 뒤 로그를 확인합니다. 같은 부팅에서 U를 반복하지 않습니다. Windows 진입까지 내장그래픽 출력을 유지하는 것이 검증된 조건입니다. 진입 후 RTX 출력으로 바꾸는 경우는 미검증입니다.

## 공개 내용과 현재 한계

- `unlock/`, `deps/`: 실제 포트 소스, 헤더, host mock 테스트, 빌드 도구.
- `release/`: 성공 사례 EFI와 해당 소스 연결 해시. 펌웨어는 제외.
- `benchmark/`: 동일 측정 소스와 로컬 CUDA 12.6 준비·빌드·실행 스크립트.
- `evidence/`: 개인정보와 원본 PROM을 제외한 측정 자료·실행 로그 발췌·해시.
- `internal-boot/`: 새 내부 디스크 수동 인계 성공 경로와 실기 미검증 자동 부팅판. 기존 루트 앱은 계속 펌웨어로 반환하는 USB 수동판입니다.
- 이 저장소는 GPU VBIOS 플래싱이나 Windows 드라이버 교체를 안내하지 않습니다. 현재 실험은 사전 부팅 상태를 바꿉니다. 재시작·전원 차단 뒤에는 다시 적용하는 절차를 전제로 합니다.

## 라이선스와 출처

포트·재사용 코어는 **GPL-2.0-only**이며, EDK2 및 별도 고지는 각 라이선스를 따릅니다. [LICENSE](LICENSE), [외부 코드 고지](THIRD_PARTY_NOTICES.md), [변경 기록](CHANGES.md)을 보존하세요. NVIDIA 펌웨어·드라이버·CUDA DLL은 재배포하지 않습니다.

## 다른 환경으로의 확장

ASUS 외 보드·Intel CPU/내장그래픽으로 확장하려면 PCI/BAR 자동 탐색, GPU와 별도인 화면 출력 검증, 카드별 검증 프로필이 필요합니다. AMD CPU 사용은 AMD Radeon GPU 지원을 의미하지 않습니다. 현재 EFI의 지원 범위는 그대로입니다.

[호환성 제보 안내](docs/CONTRIBUTING.ko.md)로 환경 정보를 수집할 수 있습니다. 수집 결과는 실행 허가가 아닙니다. [지원 확대 설계와 검증 단계](docs/PORTABILITY.en.md)를 참고하세요.
