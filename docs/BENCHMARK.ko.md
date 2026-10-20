# 같은 조건으로 성능 비교하기

측정 소스는 상위 프로젝트의 4096×4096 cuBLAS GEMM을 사용합니다. FP32 pedantic, FP16/BF16 입력과 FP32 누산·출력, 정밀도별 2초 warmup과 30 sample입니다. GPU 선택을 3090으로 바꾸고 메타데이터 확인 옵션을 추가했습니다. 결과 검증은 원본처럼 출력 첫·마지막 원소 확인에 한정됩니다.

CUDA 12.6 redist는 NVIDIA 공식 서버에서 해시·크기를 확인해 프로젝트 폴더에만 준비합니다. 드라이버·ComfyUI·시스템 PATH를 변경하지 않습니다. 다운로드 용량과 디스크 공간이 필요합니다.

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\benchmark\setup.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\benchmark\build.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\benchmark\run-benchmark.ps1 -PreflightOnly
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\benchmark\run-benchmark.ps1
```

실측 빌드는 VS2019 BuildTools MSVC14.29를 사용했습니다. 다른 위치는 `build.ps1 -VcVars <vcvars64.bat>`로 지정합니다. CUDA 12.6과 호환되는 MSVC를 사용하세요. setup은 기존 packages 폴더를 덮어쓰지 않으므로 새 디렉터리에서 처음 한 번 실행합니다.

ComfyUI·영상·녹화·다른 GPU 작업을 저장하고 종료한 뒤 측정합니다. 시작 조건은 GPU 사용률 5% 이하, VRAM 2048MiB 이하, 온도 65°C 이하입니다. 스크립트는 3회 실행을 새 `benchmark/results/시각/` 폴더에 저장합니다. 다른 프로세스를 강제 종료하지 않습니다.

언락 이전과 이후에 동일 실행물·드라이버·전력 제한·오버클럭·온도 조건을 사용하세요. 이 도구는 GPU 설정을 바꾸지 않습니다. FP16/BF16 Tensor 향상이 게임·영상·ComfyUI 전체 시간의 같은 비율 향상을 의미하지 않습니다.
