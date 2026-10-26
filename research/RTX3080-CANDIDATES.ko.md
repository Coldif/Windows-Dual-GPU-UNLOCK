# RTX 3080 후보 검토 — 지원 프로필 아님

2026-10-26, 기준 main f33a4c8. 제보된 성공과 오프라인 관측을 구분한다.
이 문서는 EFI 실행이나 가드 우회 지침이 아니다.

## 3080 FE / ASUS Z390 — #20

[제보와 첨부](https://github.com/impacifist/Windows-GPU-UNLOCK/issues/20#issuecomment-6404367705)의
텍스트 두 파일을 다운로드해 데이터로 읽었다. diff는 적용하거나 실행하지 않았다.

| 입력 | 크기 | SHA-256 |
|---|---:|---|
| DIAG00-sanitized.txt | 315439 | 9913e7f6f88e32dd83c38edddcf4b43cfefa41cdf5685b703d9c55956b9befda |
| observe-retarget.diff.txt | 1288 | 4fab2d1bd7cfe3747c9083e1565d060e480c25caf616abdaae08d62bb0de9d01 |

첨부는 ignored `research/results/issue20-review-20261026/`에 보존하며 Git에 넣지 않는다.
이 hash는 비식별 첨부 자체의 hash다. 작성자가 기재한 비식별화 전 원본 hash와는 다르다.

수정한 fingerprint/analyze 도구로 다음을 확인했다:

- 한 target 0000:01:00.0, PCI 220610de / subsystem 161210de,
  BAR0 a2000000, chip b72000a1, memory 0x2800 MiB.
- PCI command 0x3: MEM on/BME off. 필수 MMIO 누락·실패 없음.
- SS0 74140020 / SS1 7, GFW 8b8f/3ff/10, WPR2 high 0.
- 449 handle, 물리 GOP 하나, virtual console GOP 없음, 시스템 text/input 존재.
- nvgop version 60009, size 2b700, Stop 698. EDID version 1,
  size 9000, Stop 1464. 외부 코드 이미지가 없어 코드 hash는 검증하지 않았다.
- 같은 capture에 text-out binding 세 개가 있으며 size 6e00, version 10,
  Stop 100c/1614/1a48이다. 이를 부팅 사이의 임의 변동으로 일반화하지 않는다.
- 새 literal open 요약기는 이 자료의 protocol별 open snapshot 1015개를 읽었다.
  이는 전체 handle의 합계이며 target별 detach 역할 분류가 아니다. 0x8과
  다중 OpenCount를 있는 그대로 표시하고, 누락·중복 snapshot을 거부한다.

현재 topology 분석기의 exact 3090 identity 분류에서 이 카드는 `other`이며
single_rtx_display_topology_observed=false이다. 물리 GOP 하나라는 관측과 모순되지 않는다.
모델 지원을 추가하기 위해 이 분류를 임의로 true로 바꾸지 않는다.

diff는 구버전 machine-profile.h에 관측 전용 ID branch를 추가하고 aggregate=1로
설정한다. capture의 aggregate GOP 부재와 맞지 않으며 작성자도 이 점을 명시했다.
최신 main의 checked probe, USB 경계와 source manifest를 거치지 않고 그대로 이식하지 않는다.

### Target별 소유권 후속 분석

전체 handle 합계와 별도로, 같은 비식별 capture에서 정확한 GPU PCI identity와
device-path ancestry로 물리 GOP child 하나를 찾고 open agent를 binding record와 연결했다.
아래는 각 target의 `attributes=0x10`, `OpenCount=1`, `ControllerHandle=target`인 기록이다.

| Target / protocol | 기록된 agent | Version | Image size | Stop RVA |
|---|---|---|---|---|
| GPU PCI / PciIo | nvgop-ga1xx | 0x60009 | 0x2b700 | 0x698 |
| GPU GOP child / SimpleTextOut | console-text GUID 628a497d-2bf6-4264-8741-069dbd3399d6 | 0x10 | 0x6e00 | 0x100c |
| GPU GOP child / GOP | console-gfx GUID 43e7abdd-e352-4cfb-a230-4cdc1d350e5c | 0x10 | 0x54c0 | 0x9dc |
| GPU GOP child / EdidDiscovered | EDID GUID c7a7030c-c3d8-45ee-bed9-5d9e76762953 | 0x1 | 0x9000 | 0x1464 |

각 행의 agent는 binding record 하나와 대응한다. 이 GPU의 SimpleTextOut consumer에
연결된 Stop은 0x100c이다. 전역 binding 목록의 다른 두 Stop 0x1614/0x1a48을
이 target의 대체 허용값으로 추가할 근거는 없다. 같은 text agent의 0x8 open은
공유 console을 child controller로 가리킨다. 이는 표준 BY_CHILD_CONTROLLER 값이며,
위의 BY_DRIVER consumer와 구분해 기록한다. ConOut·StdErr·ConIn은 같은 console handle이다.

EdidDiscovered에는 nvgop의 GET_PROTOCOL(0x2) 기록과 별도 EDID agent의 BY_DRIVER(0x10)
기록이 함께 있다. 따라서 #7의 “별도 EDID BY_DRIVER owner 없음” 구조와 같지 않다.
이 결과는 기존 네 역할을 검토할 수 있다는 자료이지, 현재 profile 상수나 해제 순서를
그대로 재사용할 수 있다는 검증은 아니다. 드라이버 코드 동일성, 추가 consumer의 허용 여부,
실제 Stop·cleanup·복구와 capture의 진위는 별도 근거가 필요하다.

판정: 진단 자료로 유용하나 **쓰기 프로필 승격은 보류**한다. 코드 fingerprint와
정확한 ownership/해제 정책, 장비별 firmware/layout·cleanup 근거가 부족하다.
다음 입력은 이미 보유한 자료에서 계산 가능한 비식별 코드 fingerprint와 정확한
이미지/Stop 관계, 기존 소스·빌드의 대응 근거다. 새 실행이나 원시 코드 이미지 공개는 요구하지 않는다.
공개 파일 footer로 마지막 flush/close 또는 Windows 성공을 입증하지 않는다.

## 3080 LHR / Maxsun B760M — #28

[제보](https://github.com/impacifist/Windows-GPU-UNLOCK/issues/28)는 한 cold boot의
selector 유지/FLR/Windows 복구와 matched FP16/BF16 전후 측정을 보고한다.
child open 관계, EDID 소유권 해석, 조건부 다중-count owner,
여러 text-out binding의 구분은 독립 fixture가 필요한 구조다.

`0x8`을 비표준 attribute로 설명한 제보도 정정이 필요하다.
[공식 EDK2 UefiSpec.h](https://github.com/tianocore/edk2/blob/master/MdePkg/Include/Uefi/UefiSpec.h)는
EFI_OPEN_PROTOCOL_BY_CHILD_CONTROLLER를 0x00000008로 정의하며 로컬 pinned 헤더도 같다.
비표준인지 판단할 대상은 flag 값 자체가 아니라 구체적인 Agent/Controller/Protocol 관계다.
이 때문에 기존 역할 검증을 우회하는 새 flag 예외를 현재 설명만으로 도입하지 않는다.

제보는 `1c0c34f6-d380-41fa-a049-8ad06c1a66aa`를 NVIDIA private protocol이라고
표현하지만, 이 GUID는 [공식 EDK2의 EFI_EDID_DISCOVERED_PROTOCOL_GUID](https://github.com/tianocore/edk2/blob/master/MdePkg/Include/Protocol/EdidDiscovered.h)다.
로컬 pinned EDK2 헤더도 같은 정의다. 따라서 “EdidDiscovered consumer 없음”이라는
설명과 GUID만으로 새 private-protocol 해제 정책을 만들 수 없다. 실제 handle별
OpenProtocolInformation과 source diff를 확인해야 한다. 앞선 이슈 요약의 private EDID 표현을 정정한다.

현재 공개 PR 목록에는 이 기여가 없고, 작성자 계정의 공개 저장소 목록 조회에서도
검토할 GPU/unlock 소스를 찾지 못했다. 본문은 소스 diff나 완전한 source revision을
제공하지 않는다. 따라서 제보의 가드 완화나 실행 경로를 코드로 검증하지 못했다.

판정: 다음 확장 우선 후보이나 **소스 확보 전 프로필 구현/머지 보류**.
필요 입력은 현재 main에 대한 공개 diff/PR, source/EFI 전체 hash, 기존 비식별
capture/전후 결과의 대응 관계다. 새 장비 실행 없이 기존 자료부터 검토한다.
GUID/size/version만으로 실행 코드나 Stop을 신뢰하는 변경은 그대로 받아들이지 않는다.
