"""
运行环境采集 — 每次实验必须记录硬件信息以便跨设备比较。

支持 CUDA / ROCm(HIP, 含海光 DCU) / MPS / CPU-only 四种后端。
修复了旧版的 total_mem -> total_memory 崩溃问题; 在 DCU 上会记录
gcnArchName 与 torch.version.hip, 而不是误标 compute_capability。

用法:
    from environment_capture import capture_environment
    import json
    env = capture_environment()
    json.dump(env, open("environment.json", "w"), indent=2, ensure_ascii=False, default=str)
"""
import os, platform, sys, json, subprocess
import torch


def _cpu_model():
    """尽量返回可读的 CPU 型号; platform.processor() 在 Linux 上常为 x86_64。"""
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.lower().startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "Unknown"


def _gpu_device_dict(props):
    dev = {
        "name": props.name,
        "vram_total_gb": round(props.total_memory / (1024**3), 1),
    }
    # ROCm/DCU (海光等) 用 gcnArchName; NVIDIA CUDA 用 major.minor
    gcn = getattr(props, "gcnArchName", None)
    if gcn:
        dev["gcn_arch"] = gcn
    else:
        dev["compute_capability"] = f"{props.major}.{props.minor}"
    return dev


def capture_environment():
    env = {
        "platform": platform.platform(),
        "hostname": platform.node(),
        "python_version": sys.version,
        "cpu": {"model": _cpu_model()},
        "gpu": {
            "available": torch.cuda.is_available(),
            "count": torch.cuda.device_count() if torch.cuda.is_available() else 0,
        },
        "packages": {"torch": torch.__version__},
    }
    # 常用科学计算/BDL 包版本 (已安装才记录)
    for _pkg in ["numpy", "scipy", "sklearn", "pandas", "pyro", "laplace"]:
        try:
            _mod = __import__(_pkg)
            env["packages"][_pkg] = getattr(_mod, "__version__", "unknown")
        except Exception:
            pass
    env["python_impl"] = platform.python_implementation()
    env["python_executable"] = sys.executable

    # CPU/RAM/磁盘 (psutil 可选)
    try:
        import psutil
        env["cpu"]["physical_cores"] = psutil.cpu_count(logical=False)
        env["cpu"]["logical_cores"] = psutil.cpu_count(logical=True)
        env["cpu"]["ram_total_gb"] = round(psutil.virtual_memory().total / (1024**3), 1)
        env["disk_free_gb"] = round(psutil.disk_usage(".").free / (1024**3), 1)
    except ImportError:
        pass

    # 加速器后端: CUDA / HIP(ROCm/DCU) / MPS / CPU
    is_cuda_build = torch.version.cuda is not None
    is_hip_build = getattr(torch.version, "hip", None) is not None
    mps_available = False
    try:
        mps_available = torch.backends.mps.is_available()
    except Exception:
        pass

    if is_cuda_build:
        env["gpu"]["backend"] = "cuda"
    elif is_hip_build:
        env["gpu"]["backend"] = "hip"
    elif mps_available:
        env["gpu"]["backend"] = "mps"
    else:
        env["gpu"]["backend"] = "cpu"

    if torch.cuda.is_available():
        for i in range(torch.cuda.device_count()):
            env["gpu"][f"device_{i}"] = _gpu_device_dict(
                torch.cuda.get_device_properties(i)
            )

    env["torch_config"] = {
        "cuda_version": torch.version.cuda,
        "hip_version": getattr(torch.version, "hip", None),
        "mkldnn_available": torch.backends.mkldnn.is_available(),
        "mps_available": mps_available,
    }

    # ROCm/DTK 环境变量 (海光 DCU 等) + 驱动版本
    rocm_env = {}
    for _k in ["DTKROOT", "HIP_PATH", "AMDGPU_TARGETS", "ROCM_PATH"]:
        _v = os.environ.get(_k)
        if _v:
            rocm_env[_k] = _v
    if rocm_env:
        env["rocm_env"] = rocm_env
    if getattr(torch.version, "hip", None):
        try:
            _drv = subprocess.run(["hy-smi", "--showdriverversion"],
                                  capture_output=True, text=True, timeout=10)
            if _drv.returncode == 0:
                _drv_line = [l for l in _drv.stdout.splitlines() if "Driver Version" in l]
                if _drv_line:
                    env["rocm_env"]["hy_smi_driver_version"] = _drv_line[0].strip()
                else:
                    env["rocm_env"]["hy_smi_driver_version"] = _drv.stdout.strip().splitlines()[-1]
        except Exception:
            pass

    try:
        import google.colab
        env["runtime"] = "Colab"
    except ImportError:
        env["runtime"] = "Local"
    return env


if __name__ == "__main__":
    print(json.dumps(capture_environment(), indent=2, ensure_ascii=False, default=str))
