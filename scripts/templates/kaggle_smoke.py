#!/usr/bin/env python3
"""kaggle_smoke.py - Kaggle 闭环验证用的冒烟 kernel（阶段 1 用）.

它做四件事：
1. 采集运行环境（谁、哪台机器、什么卡、什么版本），落 environment.json；
2. 打印一份人能读的摘要到 run.log；
3. 写一段最简单的 GPU 计算，证明卡真的能算；
4. 无论成功失败都写 result.json（含 exit_code），让 DSH 侧的 fetch 能判定成功。

推上去：
  python pfn-compute-research/scripts/kaggle_job.py submit --name smoke --file pfn-compute-research/scripts/templates/kaggle_smoke.py
"""
import json
import os
import platform
import subprocess
import sys
import traceback
from datetime import datetime, timezone

WORK = "/kaggle/working"


def sh(cmd):
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        return (p.stdout or p.stderr or "").strip()[:2000]
    except Exception as e:
        return "ERR %s: %s" % (type(e).__name__, e)


def main():
    log_lines = []
    def log(msg):
        print(msg, flush=True)
        log_lines.append(str(msg))

    env = {
        "timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "hostname": platform.node(),
        "user": os.environ.get("USER") or os.environ.get("USERNAME"),
        "platform": platform.platform(),
        "python": sys.version,
        "cwd": os.getcwd(),
        "nvidia_smi_L": sh("nvidia-smi -L"),
        "nvidia_smi_query": sh("nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader"),
        "cpu_count": os.cpu_count(),
        "working_disk": sh("df -h /kaggle/working | tail -1"),
    }
    try:
        import torch
        env["torch"] = torch.__version__
        env["cuda_available"] = bool(torch.cuda.is_available())
        env["cuda_device_count"] = torch.cuda.device_count()
        if torch.cuda.is_available():
            env["cuda_device_name"] = torch.cuda.get_device_name(0)
        else:
            env["torch_fallback"] = "torch 已装但 cuda 不可用"
    except Exception as e:
        env["torch_error"] = "%s: %s" % (type(e).__name__, e)
        try:
            env["torch"] = sh("python -c \"import torch;print(torch.__version__)\"")
        except Exception:
            pass

    log("== kaggle smoke ==")
    for k, v in env.items():
        log("%-20s %s" % (k + ":", v))
    log("writable: %s" % os.access(WORK, os.W_OK))

    gpu_math = None
    try:
        import torch
        if torch.cuda.is_available():
            a = torch.randn(1024, 1024, device="cuda")
            b = torch.randn(1024, 1024, device="cuda")
            c = a @ b
            torch.cuda.synchronize()
            gpu_math = {"matmul_1024_ok": True, "checksum": float(c[0, 0].item())}
            log("gpu matmul 1024x1024: OK checksum=%.6f" % gpu_math["checksum"])
        else:
            gpu_math = {"matmul_1024_ok": False, "reason": "cuda_available=False"}
    except Exception as e:
        gpu_math = {"matmul_1024_ok": False, "reason": "%s: %s" % (type(e).__name__, e)}
        log("gpu matmul FAILED: %s" % gpu_math["reason"])

    env["gpu_math"] = gpu_math
    with open(os.path.join(WORK, "environment.json"), "w", encoding="utf-8") as f:
        json.dump(env, f, ensure_ascii=False, indent=2, default=str)
    with open(os.path.join(WORK, "run.log"), "w", encoding="utf-8") as f:
        f.write("\n".join(log_lines) + "\n")
    return env, gpu_math


if __name__ == "__main__":
    os.makedirs(WORK, exist_ok=True)
    result = {"exit_code": 0, "ok": True, "name": "kaggle_smoke"}
    try:
        env, gpu = main()
        result["environment"] = env
        result["gpu_matmul"] = gpu
        if not (env.get("cuda_available") and gpu and gpu.get("matmul_1024_ok")):
            result["ok"] = False
            result["error"] = "GPU 不可用或矩阵乘失败：cuda_available=%s" % env.get("cuda_available")
            result["exit_code"] = 3
    except Exception:
        tb = traceback.format_exc()
        print(tb, flush=True)
        result.update({"exit_code": 1, "ok": False, "error": tb[-2000:]})
        try:
            with open(os.path.join(WORK, "run.log"), "a", encoding="utf-8") as f:
                f.write(tb)
        except Exception:
            pass
    with open(os.path.join(WORK, "result.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print("result.json:", json.dumps({k: result[k] for k in ("exit_code", "ok")}))
    sys.exit(0)  # 让 kernel 本身"成功"结束；真实成败由 result.json 的 exit_code 表达
