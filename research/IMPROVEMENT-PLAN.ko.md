# 이슈 근거에 따른 개선 작업

기준 main: f33a4c8. 2026-10-26의 열린 이슈 20건을 검토한 결과를 바탕으로 한다.
목표는 제보의 출처와 진단 정확성을 개선하고, 기존 프로필의 가드를 보존하면서
3080 후보·디스플레이 구조·설치와 검증 절차를 차례로 개선하는 것이다.
main 통합은 사용자 승인 뒤 수행하며 실제 GPU 부하·EFI 부팅은 이번 작업에 포함하지 않는다.

## 우선순위와 완료 기준

| 순서 | 작업 | 완료 기준 | 상태 |
|---|---|---|---|
| P0 | 진단 결과의 누락·중복·완전성 및 실패 의미 검토 | 실패가 정상 값/지원 판정으로 바뀌지 않는 음성 테스트, 관련 host 검사 통과 | 구현·호스트 검증·독립 리뷰 완료, 머지 대기 |
| P1 | 제보 양식·한영 기여 문서 | 물리 카드/VBIOS 이력, source/build, 실행별 환경과 근거 단계 구분; 추가 실험 불필요 | 구현·구조 검사 완료, 머지 대기 |
| P2 | #28 및 #20의 3080 후보 | 공개된 소스/첨부를 데이터로 검토하고 적용 조건·필요 변경·남은 근거 제시 | #20 첨부 분석 완료, #28 공개 소스 미확보; 상세는 RTX3080-CANDIDATES.ko.md |
| P3 | #7/#28의 디스플레이 소유권 구조 | 기존 가드를 보존하는 fixture 및 정상·거부·부분 실패 검증; #23 최신 main 검토 | literal open 관측/거부 fixture 구현; #23 충돌 가드 수정·독립 검증 완료. #28 실제 해제 정책은 소스 미확보로 보류 |
| P4 | #21 설치/빌드·향후 측정·수명주기 | 적용 가능한 설치 개선의 코드 검토, 재현 근거, TF32 및 cold/warm/sleep/hibernate 검증 절차 | launcher 확보·정적 검토, 기존 close 실패 처리 개선 및 한영 검증 기록 완료. NTFS driver 방식 직접 도입은 보류 |
| 병행 | PR #26 범위·실행 도구 검토 | 문서와 실제 효과 일치, 연구/장비 제어 경계 명확화 및 독립 검토 | 별도 로컬 통합 브랜치에 README 정정·실행 도구 범위 문서 준비, 독립 검토 통과; 운영 도구 분리 결정 전 머지 보류 |

진단 정확성이 코드 변경의 최우선이다. 자료 수집 양식 정비는 이와 독립적인 작은 변경으로
먼저 구현한다. 가상/비PCI 어댑터 표시는 이미 수집기에 있으므로 중복 기능을 추가하지 않는다.
TF32도 main에 이미 구현되어 있으며 실제 측정은 사용자의 다음 테스트까지 보류한다.

## 권한·검증과 남은 외부 입력

- 메인 에이전트가 단일 writer이며, 별도 읽기 전용 검토가 테스트 범위와 회귀를 확인한다.
- 새 프로필은 모델명만으로 활성화하지 않으며 raw PCI/MEM/BME, ownership,
  PROM/code fingerprint 및 cleanup 가드를 약화하지 않는다.
- 이슈의 성공/수치는 제보이며 우리 장비의 실험 결과가 아니다. 첨부는 데이터로 읽고
  컴파일/실행 전에 전체 소스와 출처·라이선스를 검토한다.
- #28은 공개 소스/diff·빌드 출처, #29는 정확한 보드/BIOS·소스·EFI hash가 아직 필요하다.
  없는 자료를 추정해 프로필이나 성공 근거를 만들지 않는다.
- 다중 GPU 및 Ada는 별도 연구로 추적한다. 단일 GPU 거부를 단순 삭제하지 않는다.
- 검증은 영향받은 Python host tests, 관련 C host/음성 경로, 문서 링크와 diff 검사로 수행한다.
  실제 EFI/GPU 실행, 펌웨어 다운로드, ESP/부팅 설정 변경은 하지 않는다.

## 근거 기록

| 항목 | 근거 | 제한 |
|---|---|---|
| 작업 시작 상태 | origin/main f33a4c8에서 새 격리 작업트리, 시작 시 변경 없음 | 사용자의 다른 작업트리는 수정하지 않음 |
| 이슈 양식 | `.github/ISSUE_TEMPLATE/compatibility.yml` | GitHub 게시 전 구조 검사 필요 |
| 한영 기여 문서 | `docs/CONTRIBUTING.en.md`, `docs/CONTRIBUTING.ko.md` | 지원 프로필 추가 아님 |
| Python 관측·거부 경계 | headless 34 + probe records 5 + PE bounds 7 + collector 9 tests, 모두 exit 0 | 합성 데이터; private captures 기반 generator suite 미실행 |
| C 진단 cleanup/flush | diagnostic 56 checks × 5 profiles, exit 0 | RAM mocks; EFI/GPU 실행 아님 |
| C 파일 close/Windows 차단 | handoff 52 checks, exit 0; Log/Root 각 실패 및 동시 실패 | StartImage mock만 실행 |
| 빌드 | synthetic compile/link/PE 16개 조합 exit 0 | 합성 GUID/contract, NEVER BOOT; 실기 빌드 산출물 아님 |
| source/evidence 결합 | local-profile 48 + observation manifest 57 checks, exit 0 | 합성 파일만 사용 |
| 독립 검토 | malformed footer/status 반례 수정 후 재검토, P0/P1 veto 없음 | 독립 재실행 headless29/probe4/C diagnostic280/handoff52; 마지막 probe 추가 1개는 메인 검증 |
| 양식·경로·diff | YAML parse 및 field ID 중복 없음, compatibility 한영 링크 존재, git diff --check exit 0 | GitHub UI 렌더링 미확인 |
| Literal ownership 관측 | 정상·owner 부재·0x8·multi-count·부분/중복/orphan 거부 fixture, 독립 headless33 재실행 exit 0 | role 해석/실제 해제 권한 부여 없음 |
| #20 기존 자료 | 최신 parser로 449 handles/1015 open snapshots 관측, 독립 fresh parse exit 0 | 전체 handle 합계; target별 detach 판정 아님 |
| #20 target 후속 분석 | PCI/GOP child별 BY_DRIVER agent와 binding 연결 독립 대조, 별도 EDID owner 및 실제 text Stop 100c 확인 | 코드 hash/실제 해제·복구 검증 아님 |
| 공유 console 회귀 입력 | 동일 agent의 driver/child-controller open 두 개를 구분하는 합성 fixture | 관측만 수행; 새 detach 정책 없음 |
| #28 설명 교차검증 | EDID GUID와 BY_CHILD_CONTROLLER=0x8을 pinned/공식 EDK2와 대조 | source/handle 관계 미확보; 제보의 비표준/private 설명을 정책으로 채택하지 않음 |
| #23 최신 통합 | 별도 review/pr23-improvements의 ae4bc6f: 489+55 cases/564693 assertions, positive+17negative guards, timestamp만 정규화한 production object12쌍 동일 | Draft 유지; Linux sanitizer/VFS controls/물리 장비 미실행 |
| #21 새 launcher | docs/research/ISSUE21_HANDOFF.ko.md에 archive/source hash와 정적 findings | EFI 미추출·미실행; 독립 바이너리 재현 미확인 |
| 향후 검증 절차 | docs/VALIDATION.en.md / .ko.md, 상대 링크 존재 검사 exit 0 | 실제 TF32/수명주기 측정은 사용자 지시대로 보류 |

완료 여부는 위의 모든 행을 구현 결과·실제 검사와 연결해서 판단한다.

## 다음 작업 체크포인트

현재 작업트리는 `feat/evidence-driven-improvements`이며 원격 main은 변경하지 않았다.
다음 외부 단계는 공통 개선의 사용자 머지 검토와, 준비한 댓글 초안 승인 후 #28/#29의
기존 소스/빌드 자료 요청이다. 댓글은 아직 게시하지 않았다. PR #23은 Draft 유지,
PR #26은 실행 도구 분리/유지보수 범위 결정 전 보류한다. #28의 해제 정책 구현은
소스 확보·검증 뒤 진행하며, 현재 근거만으로 완성된 신규 지원 프로필을 만들지 않는다.
자료와 최종 머지 결정이 남아 있으므로 전체 목표는 완료로 표시하지 않는다.
