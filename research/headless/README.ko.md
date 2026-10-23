# 단일 GPU·화면 없는 언락 연구

브랜치: `research/single-gpu-headless` / 기준: `e26bccf`.
목표는 **3090으로 부팅 화면 조작 → 출력 해제 → 화면 없이 언락 → Windows에서 출력
복귀**라는 가설을 검증하는 것이다. 현재 상태는 **R1 단일 활성 RTX 출력 관찰 완료**다.
단일 GPU 언락 EFI는 구현하거나 설치하지 않았다. R2는 콘솔 소비자 해제만 시험한다.
검증된 main의 GPU·입력·정리 검사를
지워 통과시키지 않으며 기존 설치 파일·BootOrder·릴리스도 변경하지 않는다.

## 확인된 사실과 아직 모르는 점

| 항목 | 현재 근거 | 판단 |
|---|---|---|
| 가상 콘솔과 물리 출력은 구분된다 | EDK2 ConSplitter는 물리 콘솔이 없어도 가상 handle을 유지하도록 설계됨 | 화면이 없다는 이유만으로 EFI 실행이 불가능하다고 단정할 수 없음 |
| 현재 ASUS에서 마지막 출력 제거 후에도 콘솔이 유지되는가 | DIAG02는 RTX 물리 GOP 하나와 정상 console/input protocol을 확인했지만 출력을 제거하지 않음 | 마지막 출력 제거 후 동작은 미확인 |
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
| R0 조사 완료 | 소스·공식 자료 조사, 기존 캡처를 오프라인 분석 | 의존성 목록, 실패 조건, 캡처 분석 검증 |
| R1 관찰만 | 단일 활성 RTX GOP 환경에서 읽기 전용 그래프 수집 | AMD/다른 물리 GOP 없음, 정확한 RTX PCI 신원·ancestry·driver profile, console/input·디스크 로그 확인 |
| R2 콘솔 소비자만 해제 | F8 선택 연구 EFI로 TextOut/GraphicsConsole만 해제. NVIDIA GOP는 보존 | unlock·DMA·FLR 없음, 파일 로그 지속, 입력 protocol 검사, Windows 인계 결과. 실제 키 입력 반응은 미검증 |
| R3 마지막 GOP 해제 | 검토된 EDID/NVIDIA 해제와 제한된 decode 복원만 시험. unlock 없음 | 물리 GOP 0개 실제 확인, 입력·디스크 로그·보호 graph 유지, Windows/NVIDIA 화면 복귀 |
| R4 별도 headless 정책 | 소유권·cold/PROM·로그·입력/복구를 입증하는 연구 빌드와 mock 음성 검사 | 출력 API가 없어도 파일 오류를 놓치지 않음, 새 owner/부분 실패/timeout에서 transaction·Windows 강행 없음 |
| R5 언락 1회 시험 | 수동 선택 연구 항목에서만 실행 | selectors·containment·BME=0·mapping/할당 정리, 리셋 없는 Windows 새 부팅, 화면 복귀, FP16/BF16 효과 각각 확인 |

R2 이후는 이번 브랜치 생성 요청만으로 실제 실행하지 않는다. 구체적인 별도 EFI와
검증·복구 절차를 먼저 준비하고, 검토된 시험 범위로 진행한다. 초기 단계는 현재의
자동 부팅 항목을 대체하지 않고 F8에서 고르는 독립 수동 항목으로 설계한다.

현재 CPU에 iGPU가 있으므로 iGPU GOP가 없는 캡처가 나오더라도 **iGPU 없는 CPU 전체를
지원한다는 증거는 아니다**. 사용자는 모든 모니터를 RTX에 연결해 R1 관찰을 수행했다.
BIOS에서 iGPU를 비활성화했는지는 확인하지 않았다. 후속 해제 시험 전 복구 화면·F8
Windows 진입을 사용할 방법을 확정한다.

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
2026-10-24 DIAG02에서 수집했다. 아래 실기 기록을 참고한다.

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
- 단일 활성 RTX 실기 캡처는 아래 R1 기록으로 추가했다. 드라이버 해제·GOP 없는
  Windows 인계·단일 GPU 언락은 아직 미실행이다.

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

연구 완료 조건은 R5의 실기 근거까지다. 지금은 R1 출력 토폴로지를 관찰했으며 단일 GPU 지원·EFI
배포·기본 부팅 승격을 완료했다고 표현하지 않는다.

## 관찰용 항목 등록 상태

2026-10-24 사용자의 관찰용 시험 준비 요청으로 연구 PC에 별도 항목
**GPU Headless Observe - NO UNLOCK**을 등록했다. 새 파일은
`EFI/WindowsGPUUnlock/OBSERVE.EFI`이며 기존 기본 순서의 마지막에만 항목을 추가했다.
기존 Auto·Windows·UEFI OS 항목과 해당 순서, BootNext 부재를 사후 검증했다.
재부팅·BIOS 변경·드라이버 해제·언락은 실행하지 않았다.

등록 도구는 `register-observe.ps1`이다. 기본 실행은 파일 배치만 수행하고 `-Register`만
새 항목을 추가한다. 이 도구는 현재 검토한 정확한 로컬 EFI 해시만 허용하며 다른
파티션 구성의 빌드에는 별도 검토가 필요하다. 공개 설치 범용 도구가 아니다.
등록 상태와 BCD/firmware 백업은 로컬에만 보존하며 `registration.local.json`은 ignored다.

관찰용 EFI의 두 차례 실제 부팅에서 정상 완료 로그를 수집했다. U 입력은 없으며
언락·드라이버 해제를 수행하지 않는다. 아래 결과는 출력 토폴로지 관찰 결과이며,
단일 GPU 언락 성공으로 표현하지 않는다.

## R1 실기 관찰 결과 — 2026-10-24

같은 연구 PC에서 수집한 로컬 원본을 오프라인 분석기로 다시 읽었다. 원본 로그의
주소·장치 경로·파티션 설정은 공개하지 않고 재현 식별용 파일 해시만 기록한다.

| 항목 | 기준 부팅 DIAG01 | RTX 출력 부팅 DIAG02 |
|---|---|---|
| 파일 수정 시각 (KST) | 02:04:48 | 02:18:06 |
| 원본 크기 | 426,367 bytes | 424,086 bytes |
| handle 수 | 585 | 585 |
| 물리 GOP | AMD + RTX, 2개 | RTX만, 1개 |
| 가상 콘솔 GOP | 0개 | 0개 |
| 시스템 TextOut / Input protocol | 있음 / 있음 | 있음 / 있음 |
| capture-complete / diagnostic-result | 1 / status 0 | 1 / status 0 |

- DIAG01 SHA256: `faf9955cf0ae79791b164c3d58be8cc6f92fd952fc68a259246a77e42784c88e`.
- DIAG02 SHA256: `32c5567d4cf47ed7df2cc645301fc732a0fc75eeb680a87408e7a200f88b2a2f`.
- DIAG02는 `OBSERVE.EFI` 실행 경로를 포함한다. Windows의 LastBootUpTime은
  같은 날 02:18:10 KST였고 사용자가 Windows 복귀를 보고했다.
- 사용자는 모든 모니터를 3090에 연결했다고 보고했다. 캡처는 AMD 물리 GOP가 없음을
  확인하지만 CPU의 iGPU 제거·비활성화 또는 iGPU 없는 CPU 지원을 입증하지 않는다.
- protocol 존재는 실제 키 입력 반응 검증과 다르다. 드라이버 코드 profile·독점
  소유권·PROM·안전한 해제 가능성은 이 분석기의 검증 범위 밖이다.

**판정:** R1의 읽기 전용 단일 RTX 출력 관찰과 해당 상태의 Windows 진입을 확인했다.
언락·화면 해제·물리 GOP 0개 상태의 Windows 인계·FP16/BF16 향상은 시험하지 않았다.
R1의 driver profile 및 입력 반응 등 해제 전 조건은 별도로 확인해야 한다.

**다음 시험:** 아래 R2 전용 수동 시험 EFI를 사용한다. 정확한 RTX 신원·driver profile과
보존해야 할 입력/디스크/PCI 연결을 먼저 검증하고, TextOut/GraphicsConsole 소비자만
해제하며 NVIDIA GOP는 유지한다. 전후 그래프와 파일 로그, 입력 protocol, Windows 인계를
확인해야 한다. R1 기록 자체는 R2의 실행 성공 근거가 아니다.

## R2 콘솔 소비자 해제 시험

이 빌드는 **언락하지 않는다**. 정확한 RTX GOP child에 연결된 TextOut 소비자와
GraphicsConsole만 순서대로 해제한다. NVIDIA GOP, NVIDIA PCI owner, 공유 EDID와
별도 EDID-only child는 해제 대상이 아니다. 물리 GOP는 1개인 상태를 유지해야 한다.

- R1과 같은 ASUS BIOS 3057 / RTX 3090 FE / 단일 활성 RTX 출력 조건을 사용한다.
- 기존 AMD 출력 경로는 `GU_SINGLE_RTX_CONSOLE`이 없는 빌드에서 그대로 유지된다.
- GPU PCI config와 GOP interface·mode·framebuffer·정보·전체 경로를 고정하고,
  정확히 세 소비자 edge 외의 전체 active graph가 바뀌면 정지한다.
- 해제 시작 후 화면 출력 함수를 호출하지 않는다. 파일 로그 오류·부분 해제·입력
  protocol 오류/경고는 재연결·리셋·Windows 강행 없이 정지한다.
- 사용자 요청으로 T/Enter 요구를 제거했다. F8 항목 선택 후 5초간 Esc를 받으며,
  무입력이면 자동 시험한다. 해제 후 Reset과 ReadKeyStroke 1회의 성공 또는
  NOT_READY만 허용한다. 실제 사람의 키 입력·키보드 하드웨어 반응을 검증한 것이 아니다.
- 파일 닫기를 마친 후 마지막 검증과 Windows StartImage 사이에는 출력·파일 I/O가 없다.

로컬 빌드 및 검증:

```powershell
.\research\headless\build-r2.ps1 -Clang 'C:\TOOLS\LLVM20\bin\clang.exe' `
  -LldLink 'C:\TOOLS\LLVM20\bin\lld-link.exe' -Capture 'U:\RTX3090-UNLOCK\DIAG02.TXT'
.\research\headless\register-observe.ps1 -ConsoleR2 -Register
```

이미 Configure한 별도 ESP/Windows ESP의 로컬 설정이 필요하다. 등록은 검토된 로컬
EFI 해시만 허용하며 다른 파티션 구성에는 그대로 사용할 수 없다. 기존 항목은
보존하고 **GPU R2 Auto Test - NO UNLOCK**을 기존 순서의 마지막에 추가한다.
기본 Auto 항목과 BootNext는 바꾸지 않으며 재부팅도 하지 않는다.

이전 수동 R2가 이미 등록된 연구 PC에서는 새 항목 등록 대신
`.\research\headless\update-r2-auto.ps1`을 사용한다. 기존 R2 파일과 등록 정보를
백업하고 `R2-AUTO.EFI`를 별도로 배치한 뒤, 해당 R2 항목의 경로와 이름만 변경한다.

실제 시험은 사용자가 다음 순서로 한다.

1. 작업을 저장하고 완전 종료 후 다시 켠다. 케이블과 BIOS는 R1 성공 상태를 유지한다.
2. F8에서 **GPU R2 Auto Test - NO UNLOCK**을 선택한다.
3. **아무 키도 누르지 않고 기다린다.** 5초 후 콘솔 소비자 해제·상태 검사·Windows
   인계를 자동 진행한다. 초기 5초 안의 Esc는 아무것도 해제하지 않고 Windows로
   넘어가므로 시험 성공으로 세지 않는다.
4. Windows에 돌아오면 새 `RTX3090-UNLOCK/R2C00.TXT` 이후 번호의 로그를 확인한다.
   전후 캡처와 각 해제 상태, `r2-input-protocol-probe-passed-not-human-liveness`,
   최종 result를 함께 판정한다.
5. 선택 후 1분 이상 진행되지 않으면 전원을 끄고 F8의 **Windows Boot Manager**로
   복귀한다. 기존 Auto 항목은 AMD 출력이 없으면 중단될 수 있으므로 복구에 쓰지 않는다.

자동판 호스트 재현·음성 경로 검사 575개와 PE 검증을 통과했다. 이는 실제 firmware에서의
해제 성공 증거가 아니다. R2의 실기 성공 여부와 마지막 GOP 제거(R3)는 아직 미확인이다.

2026-10-24 처음에는 수동판 `R2-CONSOLE.EFI` 20,480 bytes를 별도 설치하고 F8 항목을
등록했다. 설치본 SHA256은
`a4363159b2ed4088ed84f96cd0a0e0d424843d4dd992c50c58cf732fd7854aad`다.
기존 모든 항목·우선순위의 순서와 Auto/UNLOCK-AUTO/OBSERVE 파일 해시 보존,
BootNext 부재와 새 경로·설치 파일 해시를 검증했다. BCD 백업과 장치별 등록 정보는
로컬에만 보존한다. 소스·설치 전 독립 검토에서 blocker는 없었으며, 에이전트가
재부팅하거나 실제 GPU 해제를 실행하지 않았다. 기존 콘솔 경로 회귀 검사 291개,
diagnostic 검사 35개, 오프라인 분석기 13개와 등록 transaction 복구 검사를 통과했다.

같은 날 사용자의 추가 키 입력 제거 요청으로 `R2-AUTO.EFI` 19,968 bytes를 별도
설치했다. SHA256은 `dada135fbaf8fa19ac1e627668e63387ce5387bf63054d3e3adfa7ca76824c67`이다.
기존 R2 항목만 **GPU R2 Auto Test - NO UNLOCK**과 새 경로로 바꾸고, BootOrder·
다른 항목·기존 수동 R2 파일·기존 Auto/OBSERVE 해시를 보존한 것을 검증했다.
변경 전 BCD·수동 EFI·등록 상태를 백업했고 독립 소스 검토에서도 설치 blocker는 없었다.
자동판의 실제 부팅·콘솔 해제·Windows 복귀는 다음 사용자의 시험으로 확인해야 한다.
