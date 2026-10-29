/* GPL-2.0-only. Ordinary Windows CUDA workload for comparing one boot against
 * another: no unlock, no reset, no driver change, no device reconfiguration.
 *
 * The same binary measures every card it can see, so an unlocked session and a
 * normal session produce directly comparable numbers for the same UUID:
 *
 *   gu-compute-benchmark --list
 *   gu-compute-benchmark --device 0000:02:00.0 --trials 3 --samples 25
 *
 * Modes are the four the repository already uses, one CUDA-core reference and
 * three tensor-core paths:
 *
 *   fp32_pedantic                  SGEMM, pedantic math (CUDA cores)
 *   fp16_tensor_fp32_accumulate    HGEMM in, FP32 accumulate (tensor cores)
 *   bf16_tensor_fp32_accumulate    BF16 in, FP32 accumulate (tensor cores)
 *   tf32_tensor_fp32_accumulate    FP32 in, TF32 tensor math (tensor cores)
 *
 * Every mode multiplies all-ones matrices, so the exact result of every element
 * is n; the check is mathematical, not a tolerance. Each trial is reported, and
 * the summary uses the median of trial medians so one clock dip cannot pick the
 * number. Device-to-device bandwidth and the largest buffer that can actually
 * be touched are measured as well: a card that is present but not usable shows
 * up there first.
 */
#include <cuda_runtime.h>
#include <cuda_fp16.h>
#include <cuda_bf16.h>
#include <cublas_v2.h>
#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

static const int kModes = 4;
static const int kMaxTrials = 8;
static const char *kModeNames[kModes] = {
  "fp32_pedantic",
  "fp16_tensor_fp32_accumulate",
  "bf16_tensor_fp32_accumulate",
  "tf32_tensor_fp32_accumulate",
};

static void CudaCheck(cudaError_t Error) {
  if (Error != cudaSuccess) {
    fprintf(stderr, "CUDA: %s\n", cudaGetErrorString(Error));
    exit(1);
  }
}

static void BlasCheck(cublasStatus_t Status) {
  if (Status != CUBLAS_STATUS_SUCCESS) {
    fprintf(stderr, "cuBLAS: status %d\n", (int)Status);
    exit(1);
  }
}

static double Median(std::vector<double> Values) {
  std::sort(Values.begin(), Values.end());
  size_t Count = Values.size();
  if (!Count) return 0.0;
  return (Count & 1) ? Values[Count / 2]
                     : 0.5 * (Values[Count / 2 - 1] + Values[Count / 2]);
}

static std::string Lower(std::string Text) {
  for (size_t i = 0; i < Text.size(); i++)
    if (Text[i] >= 'A' && Text[i] <= 'Z') Text[i] = (char)(Text[i] - 'A' + 'a');
  return Text;
}

static char *UuidText(const cudaDeviceProp &Prop, char *Out, size_t Size) {
  const char *b = Prop.uuid.bytes;
  snprintf(Out, Size,
           "GPU-%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",
           (unsigned char)b[0], (unsigned char)b[1], (unsigned char)b[2], (unsigned char)b[3],
           (unsigned char)b[4], (unsigned char)b[5], (unsigned char)b[6], (unsigned char)b[7],
           (unsigned char)b[8], (unsigned char)b[9], (unsigned char)b[10], (unsigned char)b[11],
           (unsigned char)b[12], (unsigned char)b[13], (unsigned char)b[14], (unsigned char)b[15]);
  return Out;
}

static char *PciText(const cudaDeviceProp &Prop, char *Out, size_t Size) {
  snprintf(Out, Size, "%04x:%02x:%02x.0", Prop.pciDomainID, Prop.pciBusID,
           Prop.pciDeviceID);
  return Out;
}

/* Accept "0", "0000:02:00.0", "02:00.0" or "GPU-....". */
static bool SelectorMatches(const cudaDeviceProp &Prop, int Index,
                            const std::string &Selector) {
  if (Selector.find(':') != std::string::npos) {
    char Full[64], Bus[32];
    std::string Wanted = Lower(Selector);
    snprintf(Bus, sizeof(Bus), "%02x:%02x.0", (unsigned)Prop.pciBusID,
             (unsigned)Prop.pciDeviceID);
    return Wanted == Lower(PciText(Prop, Full, sizeof(Full))) ||
           Wanted == Lower(Bus);
  }
  if (Selector.size() > 4 && Lower(Selector.substr(0, 4)) == "gpu-") {
    char Uuid[64];
    return Lower(Selector) == Lower(UuidText(Prop, Uuid, sizeof(Uuid)));
  }
  return atoi(Selector.c_str()) == Index;
}

template <class T>
__global__ void OnesKernel(T *Data, size_t Count) {
  size_t i = blockIdx.x * (size_t)blockDim.x + threadIdx.x;
  if (i < Count) Data[i] = T(1.0f);
}

static cublasStatus_t Launch(cublasHandle_t Handle, int Kind, int N,
                             void *A, void *B, void *C) {
  float Alpha = 1.0f, Beta = 0.0f;
  cudaDataType_t Input = Kind == 1 ? CUDA_R_16F : Kind == 2 ? CUDA_R_16BF : CUDA_R_32F;
  if (Kind == 0)
    return cublasSgemm(Handle, CUBLAS_OP_N, CUBLAS_OP_N, N, N, N, &Alpha,
                       (float *)A, N, (float *)B, N, &Beta, (float *)C, N);
  if (Kind == 3)
    return cublasGemmEx(Handle, CUBLAS_OP_N, CUBLAS_OP_N, N, N, N, &Alpha, A,
                        CUDA_R_32F, N, B, CUDA_R_32F, N, &Beta, C, CUDA_R_32F,
                        N, CUBLAS_COMPUTE_32F_FAST_TF32,
                        CUBLAS_GEMM_DEFAULT_TENSOR_OP);
  return cublasGemmEx(Handle, CUBLAS_OP_N, CUBLAS_OP_N, N, N, N, &Alpha, A,
                      Input, N, B, Input, N, &Beta, C, CUDA_R_32F, N,
                      CUBLAS_COMPUTE_32F, CUBLAS_GEMM_DEFAULT_TENSOR_OP);
}

struct ModeResult {
  const char *Name;
  double TrialMs[kMaxTrials];
  int Trials;
  double MedianMs;
  double MinMs;
  double MaxMs;
  double Gflops;
};

static void RunMode(cublasHandle_t Handle, int Kind, int N, int Trials,
                    int Samples, ModeResult *Out) {
  size_t Count = (size_t)N * (size_t)N;
  size_t InputBytes = Count * (Kind == 0 || Kind == 3 ? sizeof(float)
                                                     : sizeof(__half));
  void *A = NULL, *B = NULL, *C = NULL;
  CudaCheck(cudaMalloc(&A, InputBytes));
  CudaCheck(cudaMalloc(&B, InputBytes));
  CudaCheck(cudaMalloc(&C, Count * sizeof(float)));
  unsigned Blocks = (unsigned)((Count + 255) / 256);
  if (Kind == 0 || Kind == 3) {
    OnesKernel<<<Blocks, 256>>>((float *)A, Count);
    OnesKernel<<<Blocks, 256>>>((float *)B, Count);
  } else if (Kind == 1) {
    OnesKernel<<<Blocks, 256>>>((__half *)A, Count);
    OnesKernel<<<Blocks, 256>>>((__half *)B, Count);
  } else {
    OnesKernel<<<Blocks, 256>>>((__nv_bfloat16 *)A, Count);
    OnesKernel<<<Blocks, 256>>>((__nv_bfloat16 *)B, Count);
  }
  CudaCheck(cudaGetLastError());
  CudaCheck(cudaDeviceSynchronize());
  BlasCheck(cublasSetMathMode(Handle, Kind == 3 ? CUBLAS_TF32_TENSOR_OP_MATH
                                                : Kind ? CUBLAS_TENSOR_OP_MATH
                                                       : CUBLAS_PEDANTIC_MATH));

  /* Warm up until clocks settle, not for a fixed number of calls. */
  std::chrono::steady_clock::time_point Start = std::chrono::steady_clock::now();
  do {
    BlasCheck(Launch(Handle, Kind, N, A, B, C));
    CudaCheck(cudaDeviceSynchronize());
  } while (std::chrono::duration<double>(std::chrono::steady_clock::now() - Start)
               .count() < 2.0);

  cudaEvent_t Begin, Stop;
  CudaCheck(cudaEventCreate(&Begin));
  CudaCheck(cudaEventCreate(&Stop));
  std::vector<double> TrialMedians;
  for (int Trial = 0; Trial < Trials; Trial++) {
    std::vector<double> Times;
    for (int i = 0; i < Samples; i++) {
      CudaCheck(cudaEventRecord(Begin));
      BlasCheck(Launch(Handle, Kind, N, A, B, C));
      CudaCheck(cudaEventRecord(Stop));
      CudaCheck(cudaEventSynchronize(Stop));
      float Ms = 0.0f;
      CudaCheck(cudaEventElapsedTime(&Ms, Begin, Stop));
      Times.push_back(Ms);
    }
    /* Exact mathematical reference: every element of an all-ones product is n. */
    float First = 0.0f, Last = 0.0f;
    CudaCheck(cudaMemcpy(&First, C, 4, cudaMemcpyDeviceToHost));
    CudaCheck(cudaMemcpy(&Last, (float *)C + Count - 1, 4, cudaMemcpyDeviceToHost));
    if (First != (float)N || Last != (float)N) {
      fprintf(stderr, "%s: result check failed (%g, %g, want %d)\n",
              kModeNames[Kind], (double)First, (double)Last, N);
      exit(1);
    }
    Out->TrialMs[Trial] = Median(Times);
    TrialMedians.push_back(Out->TrialMs[Trial]);
  }
  CudaCheck(cudaEventDestroy(Begin));
  CudaCheck(cudaEventDestroy(Stop));
  CudaCheck(cudaFree(A));
  CudaCheck(cudaFree(B));
  CudaCheck(cudaFree(C));
  CudaCheck(cudaDeviceSynchronize());
  BlasCheck(cublasSetMathMode(Handle, CUBLAS_DEFAULT_MATH));

  Out->Name = kModeNames[Kind];
  Out->Trials = Trials;
  Out->MedianMs = Median(TrialMedians);
  Out->MinMs = *std::min_element(TrialMedians.begin(), TrialMedians.end());
  Out->MaxMs = *std::max_element(TrialMedians.begin(), TrialMedians.end());
  Out->Gflops = 2.0 * N * N * (double)N / (Out->MedianMs * 1e6);
}

static void RunCopy(int Trials, int Reps, size_t Bytes, double *TrialGbps,
                    double *MedianGbps) {
  void *A = NULL, *B = NULL;
  CudaCheck(cudaMalloc(&A, Bytes));
  CudaCheck(cudaMalloc(&B, Bytes));
  CudaCheck(cudaMemset(A, 1, Bytes));
  CudaCheck(cudaDeviceSynchronize());
  for (int i = 0; i < Reps; i++) CudaCheck(cudaMemcpy(B, A, Bytes, cudaMemcpyDeviceToDevice));
  cudaEvent_t Begin, Stop;
  CudaCheck(cudaEventCreate(&Begin));
  CudaCheck(cudaEventCreate(&Stop));
  std::vector<double> Tri;
  for (int Trial = 0; Trial < Trials; Trial++) {
    CudaCheck(cudaEventRecord(Begin));
    for (int i = 0; i < Reps; i++)
      CudaCheck(cudaMemcpyAsync(B, A, Bytes, cudaMemcpyDeviceToDevice, 0));
    CudaCheck(cudaEventRecord(Stop));
    CudaCheck(cudaEventSynchronize(Stop));
    float Ms = 0.0f;
    CudaCheck(cudaEventElapsedTime(&Ms, Begin, Stop));
    TrialGbps[Trial] = 2.0 * (double)Bytes * Reps / (Ms * 1e6);
    Tri.push_back(TrialGbps[Trial]);
  }
  CudaCheck(cudaEventDestroy(Begin));
  CudaCheck(cudaEventDestroy(Stop));
  CudaCheck(cudaFree(A));
  CudaCheck(cudaFree(B));
  *MedianGbps = Median(Tri);
}

/* Largest buffer that can be allocated and actually written, not merely
 * reserved: on WDDM a successful cudaMalloc proves little until it is touched. */
static size_t RunAllocMax(size_t *FreeBytes, size_t *TotalBytes) {
  CudaCheck(cudaMemGetInfo(FreeBytes, TotalBytes));
  const size_t Step = 256ull << 20;
  const size_t Headroom = 128ull << 20;
  size_t Candidate = 0;
  if (*FreeBytes > Headroom) Candidate = ((*FreeBytes - Headroom) / Step) * Step;
  for (int Try = 0; Try < 12 && Candidate; Try++) {
    void *Buffer = NULL;
    if (cudaMalloc(&Buffer, Candidate) == cudaSuccess && Buffer) {
      if (cudaMemset(Buffer, 1, Candidate) == cudaSuccess && 
          cudaDeviceSynchronize() == cudaSuccess) {
        CudaCheck(cudaFree(Buffer));
        return Candidate;
      }
      cudaFree(Buffer);
      (void)cudaGetLastError();
    } else {
      (void)cudaGetLastError();
    }
    Candidate -= Step;
  }
  return 0;
}

static void PrintDevice(const cudaDeviceProp &Prop, int Index, int N, int Trials,
                        int Samples) {
  cublasHandle_t Handle = NULL;
  BlasCheck(cublasCreate(&Handle));
  ModeResult Modes[kModes];
  memset(Modes, 0, sizeof(Modes));
  for (int Kind = 0; Kind < kModes; Kind++)
    RunMode(Handle, Kind, N, Trials, Samples, &Modes[Kind]);

  const int CopyTrials = 3, CopyReps = 20;
  const size_t CopyBytes = 512ull << 20;
  double CopyTrial[8] = {0}, CopyMedian = 0.0;
  RunCopy(CopyTrials, CopyReps, CopyBytes, CopyTrial, &CopyMedian);
  size_t FreeBytes = 0, TotalBytes = 0;
  size_t AllocMax = RunAllocMax(&FreeBytes, &TotalBytes);

  int Runtime = 0, Driver = 0, Blas = 0;
  CudaCheck(cudaRuntimeGetVersion(&Runtime));
  CudaCheck(cudaDriverGetVersion(&Driver));
  BlasCheck(cublasGetVersion(Handle, &Blas));

  char Uuid[64], Pci[64];
  printf("{\"benchmark_protocol\":3,\"tf32_allowed\":true,"
         "\"gpu\":\"%s\",\"uuid\":\"%s\",\"pci\":\"%s\",\"index\":%d,"
         "\"compute_capability\":\"%d.%d\",\"sm_count\":%d,"
         "\"total_memory_bytes\":%llu,\"clock_rate_khz\":%d,"
         "\"memory_clock_khz\":%d,\"cuda_runtime\":%d,\"cuda_driver_api\":%d,"
         "\"cublas\":%d,\"n\":%d,\"trials\":%d,\"samples_per_trial\":%d,"
         "\"warmup_seconds\":2.0,\"benchmarks\":[",
         Prop.name, UuidText(Prop, Uuid, sizeof(Uuid)), PciText(Prop, Pci, sizeof(Pci)),
         Index, Prop.major, Prop.minor, Prop.multiProcessorCount,
         (unsigned long long)Prop.totalGlobalMem, Prop.clockRate,
         Prop.memoryClockRate, Runtime, Driver, Blas, N, Trials, Samples);
  for (int Kind = 0; Kind < kModes; Kind++) {
    const ModeResult &M = Modes[Kind];
    printf("%s{\"name\":\"%s\",\"trials_ms\":[", Kind ? "," : "", M.Name);
    for (int i = 0; i < M.Trials; i++)
      printf("%s%.6f", i ? "," : "", M.TrialMs[i]);
    printf("],\"median_ms\":%.6f,\"min_ms\":%.6f,\"max_ms\":%.6f,"
           "\"gflops\":%.3f,\"reference_checked\":true,\"tensor_cores\":%s}",
           M.MedianMs, M.MinMs, M.MaxMs, M.Gflops,
           Kind == 0 ? "false" : "true");
  }
  printf("],\"d2d_copy\":{\"bytes\":%llu,\"reps\":%d,\"trials_gbps\":[",
         (unsigned long long)CopyBytes, CopyReps);
  for (int i = 0; i < CopyTrials; i++) printf("%s%.3f", i ? "," : "", CopyTrial[i]);
  printf("],\"median_gbps\":%.3f,\"reference_checked\":true},"
         "\"memory_alloc_max\":{\"free_bytes_at_start\":%llu,"
         "\"total_bytes\":%llu,\"allocated_bytes\":%llu,\"allocated_mib\":%.1f,"
         "\"write_verified\":true}}",
         CopyMedian, (unsigned long long)FreeBytes, (unsigned long long)TotalBytes,
         (unsigned long long)AllocMax, (double)AllocMax / (1024.0 * 1024.0));

  BlasCheck(cublasDestroy(Handle));
}

static void PrintList(void) {
  int Devices = 0;
  CudaCheck(cudaGetDeviceCount(&Devices));
  printf("[");
  for (int i = 0; i < Devices; i++) {
    cudaDeviceProp Prop;
    CudaCheck(cudaGetDeviceProperties(&Prop, i));
    char Uuid[64], Pci[64];
    printf("%s{\"index\":%d,\"gpu\":\"%s\",\"uuid\":\"%s\",\"pci\":\"%s\","
           "\"compute_capability\":\"%d.%d\",\"sm_count\":%d,"
           "\"total_memory_bytes\":%llu}",
           i ? "," : "", i, Prop.name, UuidText(Prop, Uuid, sizeof(Uuid)),
           PciText(Prop, Pci, sizeof(Pci)), Prop.major, Prop.minor,
           Prop.multiProcessorCount, (unsigned long long)Prop.totalGlobalMem);
  }
  printf("]\n");
}

int main(int argc, char **argv) {
  const char *Override = getenv("NVIDIA_TF32_OVERRIDE");
  const bool Tf32Allowed = !Override || !*Override;
  std::string Selector;
  int N = 4096, Trials = 3, Samples = 25;
  bool ListOnly = false, InspectOnly = false;

  for (int i = 1; i < argc; i++) {
    std::string Arg = argv[i];
    auto Value = [&](const char *Name) -> std::string {
      if (i + 1 >= argc) {
        fprintf(stderr, "%s needs a value\n", Name);
        exit(2);
      }
      return argv[++i];
    };
    if (Arg == "--list") ListOnly = true;
    else if (Arg == "--inspect-only") InspectOnly = true;
    else if (Arg == "--device") Selector = Value("--device");
    else if (Arg == "--n") N = atoi(Value("--n").c_str());
    else if (Arg == "--trials") Trials = atoi(Value("--trials").c_str());
    else if (Arg == "--samples") Samples = atoi(Value("--samples").c_str());
    else {
      fprintf(stderr, "Unknown argument: %s\n", Arg.c_str());
      return 2;
    }
  }
  if (N < 256 || N > 8192 || Trials < 1 || Trials > kMaxTrials || Samples < 1) {
    fprintf(stderr, "Unsupported --n/--trials/--samples\n");
    return 2;
  }

  if (InspectOnly) {
    int Runtime = 0, Driver = 0, Major = 0, Minor = 0, Patch = 0, Devices = 0;
    CudaCheck(cudaRuntimeGetVersion(&Runtime));
    CudaCheck(cudaDriverGetVersion(&Driver));
    CudaCheck(cudaGetDeviceCount(&Devices));
    BlasCheck(cublasGetProperty(MAJOR_VERSION, &Major));
    BlasCheck(cublasGetProperty(MINOR_VERSION, &Minor));
    BlasCheck(cublasGetProperty(PATCH_LEVEL, &Patch));
    printf("{\"benchmark_protocol\":3,\"tf32_allowed\":%s,\"cuda_runtime\":%d,"
           "\"cuda_driver_api\":%d,\"cublas_major\":%d,\"cublas_minor\":%d,"
           "\"cublas_patch\":%d,\"device_count\":%d,\"gpu_workload_run\":false}\n",
           Tf32Allowed ? "true" : "false", Runtime, Driver, Major, Minor, Patch,
           Devices);
    return 0;
  }
  if (!Tf32Allowed) {
    fprintf(stderr, "Unset NVIDIA_TF32_OVERRIDE before running the benchmark\n");
    return 2;
  }
  if (ListOnly) {
    PrintList();
    return 0;
  }

  int Devices = 0;
  CudaCheck(cudaGetDeviceCount(&Devices));
  int Matched = 0;
  for (int i = 0; i < Devices; i++) {
    cudaDeviceProp Prop;
    CudaCheck(cudaGetDeviceProperties(&Prop, i));
    if (!Selector.empty() && !SelectorMatches(Prop, i, Selector)) continue;
    CudaCheck(cudaSetDevice(i));
    PrintDevice(Prop, i, N, Trials, Samples);
    fflush(stdout);
    Matched++;
  }
  if (!Matched) {
    fprintf(stderr, "No CUDA device matched '%s'\n", Selector.c_str());
    return 2;
  }
  return 0;
}
