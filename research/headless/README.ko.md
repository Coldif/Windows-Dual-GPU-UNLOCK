# 단일 GPU·화면 없는 언락 연구

브랜치: `research/single-gpu-headless` / 기준: `e26bccf`.
목표는 **3090으로 부팅 화면 조작 → 출력 해제 → 화면 없이 언락 → Windows에서 출력
복귀**라는 가설을 검증하는 것이다. 현재 상태는 **초기 조사와 오프라인 분석 도구**다.
단일 GPU 언락 EFI는 구현하거나 설치하지 않았다. 검증된 main의 GPU·입력·정리 검사를
지워 통과시키지 않으며 기존 설치 파일·BootOrder·릴리스도 변경하지 않는다.

## 확인된 사실과 아직 모르는 점

| 항목 | 현재 근거 | 판단 |
|---|---|---|
| 가상 콘솔과 물리 출력은 구분된다 | EDK2 ConSplitter는 물리 콘솔이 없어도 가상 handle을 유지하도록 설계됨 | 화면이 없다는 이유만으로 EFI 실행이 불가능하다고 단정할 수 없음 |
| 현재 ASUS에서 같은 동작인가 | 기존 캡처는 AMD 출력이 남아 있었음 | 미확인 |
| Windows는 부팅 중 GOP를 이용한다 | Microsoft UEFI 요구사항에 GOP 사용 명시 | 마지막 GOP 제거 뒤 Boot Manager 동작은 별도 실기 검증 필요 |
| headless Windows 개념 자체 | Microsoft WDDM headless 지침 | 이 데스크톱에서 실행 중 GOP 제거 후 부팅된다는 증거는 아님 |
| NVIDIA 드라이버가 화면을 복구하며 unlock 상태도 유지하는가 | 해당 조건의 실제 결과 없음 | 화면 복귀와 Tensor 성능을 따로 확인해야 함 |

현재의 iGPU 조건은 구현과 검증된 경로의 조건이다. 단일 GPU 방법의 불가능성을
증명한 것이 아니다. 반대로 Windows headless 문서만으로 성공 가능성을 확정하지 않는다.

## 코드에서 분리해야 할 의존성

- `internal-boot/boot/prepare-console.c`: AMD/RTX 두 물리 GOP와 양쪽 드라이버 연결을 요구한다.
- `internal-boot/boot/full-release.c`의 `AmdOnly`: 해제 후 AMD GOP·TextOut·PCI 보존을 요구한다.
- `internal-boot/unlock/app.c`의 `DisplayCheck`: 언락 전후 AMD 물리 출력을 검증한다.
- `internal-boot/unlock/compat.c`: 원본 transaction 도중에도 display check를 다시 호출한다.
- `internal-boot/unlock/app_io.c`: 파일 로그 전에 화면 출력을 호출한다. 출력 실패는
  LogFault, armed 상태에서는 GPU fault로 이어진다. 가상 출력이 성공을 반환할 수도
  있으므로 실제 마지막 sink 제거 후 반환값을 관찰해야 한다.

따라서 wrapper 한 곳에서 AMD 검사만 없애는 변경으로 해결되지 않는다. 화면 확인과
GPU 독점 소유·복구 가능성·영속 로그라는 안전 조건을 구분한 별도 연구 정책이 필요하다.

## 단계별 연구와 통과 조건

| 단계 | 동작 | 다음 단계로 갈 근거 |
|---|---|---|
| R0 현재 단계 | 소스·공식 자료 조사, 기존 캡처를 오프라인 분석 | 의존성 목록, 실패 조건, 캡처 분석 검증 |
| R1 관찰만 | 단일 활성 RTX GOP 환경에서 읽기 전용 그래프 수집 | AMD/다른 물리 GOP 없음, 정확한 RTX PCI 신원·ancestry·driver profile, console/input·디스크 로그 확인 |
| R2 콘솔 소비자만 해제 | 별도 수동 연구 EFI로 TextOut/GraphicsConsole만 해제. NVIDIA GOP는 보존 | unlock·DMA·FLR 없음, 파일 로그 지속, 새 실제 키 입력, Windows 인계 결과 |
| R3 마지막 GOP 해제 | 검토된 EDID/NVIDIA 해제와 제한된 decode 복원만 시험. unlock 없음 | 물리 GOP 0개 실제 확인, 입력·디스크 로그·보호 graph 유지, Windows/NVIDIA 화면 복귀 |
| R4 별도 headless 정책 | 소유권·cold/PROM·로그·입력/복구를 입증하는 연구 빌드와 mock 음성 검사 | 출력 API가 없어도 파일 오류를 놓치지 않음, 새 owner/부분 실패/timeout에서 transaction·Windows 강행 없음 |
| R5 언락 1회 시험 | 수동 선택 연구 항목에서만 실행 | selectors·containment·BME=0·mapping/할당 정리, 리셋 없는 Windows 새 부팅, 화면 복귀, FP16/BF16 효과 각각 확인 |

R2 이후는 이번 브랜치 생성 요청만으로 실제 실행하지 않는다. 구체적인 별도 EFI와
검증·복구 절차를 먼저 준비하고, 검토된 시험 범위로 진행한다. 초기 단계는 현재의
자동 부팅 항목을 대체하지 않고 F8에서 고르는 독립 수동 항목으로 설계한다.

현재 CPU에 iGPU가 있으므로 iGPU GOP가 없는 캡처가 나오더라도 **iGPU 없는 CPU 전체를
지원한다는 증거는 아니다**. BIOS에서 iGPU를 끄거나 화면 케이블을 바꾸는 조작도 아직
요청하지 않았다. 실제 시험 전 복구 화면·F8 Windows 진입을 사용할 방법을 확정한다.

## 지금 실행할 수 있는 도구

`analyze_capture.py`는 기존 `gpu-console-graph-v1` 파일을 읽는 **오프라인 분석기**다.
GPU·펌웨어·BCD·NVRAM에 접근하지 않으며 드라이버 해제나 언락을 허가하지 않는다.
주소와 원본 경로를 출력하지 않고 물리 GOP 개수·부모 장치 역할·console protocol
존재만 분류한다. 코드 해시·PROM·입력의 실제 반응·Windows 진입은 검증하지 않는다.

```powershell
python research\headless\analyze_capture.py --capture 'X:\RTX3090-UNLOCK\DIAG00.TXT'
```

FULL 로그처럼 캡처가 둘 이상이면 `--capture-index 0` 또는 `1`을 명시해야 한다.
부모 PCI bridge도 prefix가 되므로 가장 가까운 유일한 endpoint를 선택하고, 같은
깊이의 중복 부모·미완료 로그·해결되지 않는 ancestry는 거부한다.

```powershell
python research\headless\analyze_capture.py --capture 'X:\RTX3090-UNLOCK\FULL04.TXT' --capture-index 1
python -m unittest discover -s research/headless -p test_analyze_capture.py -v
```

`single_rtx_display_topology_observed=true`는 그 파일에 RTX 물리 출력 하나가 보였다는
뜻일 뿐 실행 허가가 아니다. 테스트의 단일 GPU 입력은 synthetic 데이터이며 실기
증거로 사용하지 않는다. `--output`은 새 파일에만 저장하고 기존 파일은 덮어쓰지 않는다.
원시 캡처와 생성 보고서는 ignored `research/results/`에 두고 GitHub에 올리지 않는다.

### R1 관찰 EFI 준비

기존 공개 `GU_DIAGNOSTIC_ONLY` 빌드를 재사용하는 별도 빌드 명령을 추가했다.
이 EFI는 드라이버 해제·언락·NVRAM 쓰기 없이 그래프를 파일로 수집하고 Windows를
정상 인계한다. 마지막 GOP를 제거하는 R2/R3 시험 EFI가 아니다.

```powershell
.\research\headless\build-observe.ps1 -UnlockDriveLetter U `
  -WindowsEspGuid 'WINDOWS-ESP-GUID-HERE' `
  -Clang 'C:\TOOLS\LLVM20\bin\clang.exe' -LldLink 'C:\TOOLS\LLVM20\bin\lld-link.exe'
```

소유한 별도 ESP와 Windows ESP를 지정해야 한다. 출력은 ignored
`research/headless/build/OBSERVE.EFI`다. 이 명령은 파일을 ESP에 설치하거나 부팅 항목을
추가하지 않는다. 실제 시험용 별도 수동 항목과 화면/BIOS 복구 절차를 준비하기 전에는
현재 자동 부팅 항목을 OBSERVE로 바꾸지 않는다. 단일 활성 RTX 조건의 실제 캡처는
아직 수집하지 않았다.

현재 설치된 Auto EFI는 AMD 출력을 요구하므로, iGPU를 끈 뒤 기존 Auto 항목을 선택하면
준비 검사에서 중단될 수 있다. 실제 R1 시험 전에는 **F8 → Windows Boot Manager로
직접 복귀하는 경로**와 별도 관찰 항목을 먼저 확보한다. 이 연구 브랜치 생성만으로
BIOS/iGPU 설정을 지금 바꾸라는 안내가 아니다.

### 초기 검증 기록

- 오프라인 분석기: synthetic 단위 검사 13개 통과. 동일 깊이 중복 PCI 부모,
  bridge prefix, 손상/미완료/개수 불일치, 복수 캡처, 잘못된 장치를 구분했다.
- 실제 DIAG00와 FULL04 post 캡처를 읽어 위의 2 GOP / AMD 1 GOP 결과를 확인했다.
- OBSERVE 빌드: 11,776 bytes, SHA256
  `4c0672952a2b2f4a1e97520be1fe3332cc1a519efd9dbf5d3326ff900790988e`.
  같은 private partition 설정으로 기존 읽기 전용 DIAGNOSTIC과 동일한 파일을 재현했다.
  이 해시는 단일 GPU 성공 증거나 다른 파티션에 맞는 범용 EFI 해시가 아니다.
- 기존 diagnostic host 검사 35개 통과. GPU/드라이버 변경 서비스가 없는 mock이다.
- 단일 GPU 실기 캡처·드라이버 해제·GOP 없는 Windows 인계·언락은 아직 미실행이다.

## 기존 실제 캡처에서 얻은 결과

- DIAG00: handles 585, 물리 GOP 2개 = AMD + RTX. 단일 GPU 조건이 아니다.
- FULL04 해제 후 캡처(index 1): 물리 GOP 1개 = AMD. 기존 성공 경로에서 AMD가
  계속 화면을 제공했음을 보여주며, RTX 단독 headless 성공 증거가 아니다.
- 원본 로그는 공개하지 않았다. 오프라인 분석은 캡처 생성 시각이나 진위를 입증하지 않는다.

## 출처

- [EDK2 ConSplitter: 고정 소스](https://github.com/tianocore/edk2/blob/5185e6cb00054a5c45110352be0dd865cfa1cb4a/MdeModulePkg/Universal/Console/ConSplitterDxe/ConSplitter.c).
  가상 콘솔 설계의 근거이며 ASUS의 실제 binary 동작 증거는 아니다.
- [Microsoft UEFI 요구사항](https://learn.microsoft.com/en-us/windows-hardware/drivers/bringup/uefi-requirements-that-apply-to-all-windows-platforms).
  Windows 데스크톱판에 대한 문서이지만 이 PC에서 GOP를 동적으로 제거한 결과는 다루지 않는다.
- [Microsoft WDDM headless 지침](https://learn.microsoft.com/en-us/windows-hardware/drivers/display/wddm-v1-2-best-practices).
  OS headless 동작과 이 실험의 부팅 인계를 구분한다.

연구 완료 조건은 R5의 실기 근거까지다. 지금은 R0를 진행했으며 단일 GPU 지원·EFI
배포·기본 부팅 승격을 완료했다고 표현하지 않는다.
