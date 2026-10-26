# 향후 장비 검증 기록

[English](VALIDATION.en.md)

사용자가 별도로 계획하는 테스트의 기록 양식이다. 부하나 EFI 실행을 시작하거나 지원을
승인하는 문서가 아니다. 기존 자료만 제출해도 되며 모르는 항목을 채우려고 재실험하지 않는다.
호스트 fixture와 합성 빌드는 소프트웨어 검증으로 구분한다.

## 실행마다 환경 연결

물리 카드와 VBIOS 변경 이력, PCI/subsystem, 보드/BIOS, 소스 commit과 로컬 diff,
EFI hash, 컴파일러, 실제 모니터 케이블과 다른 GPU를 기록한다. Windows에 iGPU가
표시되거나 display-active 값이 있다는 이유로 사전 부팅 소유권을 확정하지 않는다.
BIOS나 화면 연결이 바뀐 capture들을 하나의 상태처럼 합치지 않는다.

원시 PROM·드라이버 이미지·펌웨어·개인 경로·디스크 식별자는 비공개로 보존한다.
공유 전 검토한 메타데이터와 hash를 사용한다. 타인이 준 EFI나 archive 자체가 안전 증거는 아니다.

## 근거 단계 구분

| 단계 | 남길 근거 | 입증하지 못하는 항목 |
|---|---|---|
| Windows inventory | 수집기 버전, 완료 여부, 모델/드라이버 | 사전 부팅 안전·언락 호환성 |
| 진단 관측 | 소스/빌드, PCI command, read status, 구조, 내용 완결 | driver detach, 파일 close 성공, 언락 성공 |
| Transaction | 초기/목표 selector, 실패 단계, containment, mappings/retained/cleanup | Windows 복구·성능 향상 |
| Windows 복구 | 화면·드라이버 상태, 부팅 전환, 오류 코드 | 계산 정확도·장기 안정성 |
| 동일 조건 전후 측정 | 같은 카드/실행물/라이브러리/protocol/설정, 수치 검증·완전한 결과 | 다른 앱·다른 장비의 향상률 |

`capture-complete=1`은 마지막 flush·close보다 먼저 기록된다. marker만으로 영구 저장,
최종 정리 또는 Windows 인계를 확인할 수 없다. source/build와 연결되지 않은 성공 로그는
제보로 남긴다.

## 다음 계산 성능 측정

[벤치마크 절차](BENCHMARK.ko.md)와 비교 도구를 사용한다. 새 protocol에는 strict FP32,
FP16/FP32 누산, BF16/FP32 누산, TF32/FP32 누산이 포함된다. strict FP32 대조군과
출력이나 누산 자료형이 FP32인 Tensor Core 경로를 구분한다.

행렬 크기, warmup/sample/process 횟수, CUDA/cuBLAS·드라이버 버전, 정밀도 정책,
GPU·클록·전력·온도·백그라운드 부하, 소스/빌드 hash를 기록한다. 일치하는 전후만 비교한다.
PyTorch나 다른 카드의 수치는 참고 자료이며 우리 cuBLAS 전후 향상률이 아니다.
서로 다른 protocol version을 섞지 않는다.

벤치마크를 자동 예약하지 않는다. 실제 측정은 사용자의 다음 테스트까지 보류하며
현재 GPU 작업을 중단하지 않는다.

## 향후 테스트 세션의 수명주기 표

각 전환을 따로 계획했을 때만 같은 형식으로 기존 근거를 남긴다. 미확인·미실험은 유효한 결과다.

| 전환 | 구분할 내용 |
|---|---|
| 완전 종료/cold boot | 초기 selector, 실행 경로, 최종 드라이버·화면·계산 근거 |
| Warm restart | 상태 유지인지 새 transaction인지 구분; cold 상태를 추정하지 않음 |
| 절전 | 가능하면 S3/S0 저전력 대기 구분, resume와 이후 근거 |
| 최대절전 | 절전과 별도 기록; 초기화 여부와 재적용 안전성을 동일시하지 않음 |
| Driver restart/TDR | 별도 작업; 이 표가 자동 reset·복구 helper 실행을 뜻하지 않음 |

성공뿐 아니라 반복 횟수·실패·취소를 기록한다. 다른 구현의 절전 제보를 이 프로젝트의
지원 보장으로 옮기지 않는다. 표를 기록해도 자동 재시도·selector 쓰기·부팅 설정 변경은 하지 않는다.
