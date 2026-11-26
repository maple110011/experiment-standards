#!/usr/bin/env python3
"""kaggle_entry.py - 通用作业入口模板（把 PFN 实验放进 Kaggle 时复制成 job.py）.

约定（与 experiment-standards 的输出规范一致）:
  /kaggle/working/run.log          完整日志（stdout 镜像）
  /kaggle/working/environment.json 运行环境（谁、哪台机器、什么卡）
  /kaggle/working/metrics.csv      逐阶段指标（可空）
  /kaggle/working/result.json      成功判据：exit_code=0

注意：Kaggle 的 /kaggle/working 上限 20GB，关机即丢；需要长期保留的产物
必须在作业里打包成 Kaggle Dataset（kaggle datasets create/version），
或者跑完后立刻用 kaggle_job.py fetch 取回。
"""
import json
import os
import platform
import subprocess
import sys
import traceback
from datetime import datetime, timezone

WORK = "/kaggle/working"


def capture_environment():
    def sh(cmd):
        try:
            p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
            return (p.stdout or p.stderr or "").strip()[:2000]
        except Exception as e:
            return "ERR %s" % e
    return {
        "timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "hostname": platform.node(),
        "platform": platform.platform(),
        "python": sys.version,
        "cpu_count": os.cpu_count(),
        "gpu": sh("nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader"),
    }


def run_experiment():
    """把真正的实验放在这里。返回一个 dict，作为 result.json 的 metrics 字段。"""
    import torch
    env = capture_environment()
    print("environment:", json.dumps(env, ensure_ascii=False))
    print("cuda:", torch.cuda.is_available(), torch.cuda.device_count())
    # TODO: 在这里调用你的评测/训练脚本，例如
    #   from my_pfn.eval import run_cc18
    #   metrics = run_cc18(...)
    return {"note": "把 run_experiment 换成你的实验", "cuda_available": torch.cuda.is_available()}


if __name__ == "__main__":
    # 不要替换 sys.stdout/stderr：Kaggle 的 notebook 执行器依赖标准输出捕获，
    # 替换后本来成功的 kernel 会被标成 ERROR（本仓库 2026-11-26 实测）。
    os.makedirs(WORK, exist_ok=True)
    result = {"exit_code": 0, "ok": True}
    try:
        result["environment"] = capture_environment()
        result["metrics"] = run_experiment()
    except Exception:
        tb = traceback.format_exc()
        print(tb)
        result.update({"exit_code": 1, "ok": False, "error": tb[-3000:]})
    finally:
        with open(os.path.join(WORK, "result.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        with open(os.path.join(WORK, "run.log"), "w", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False, indent=2, default=str)[:200000] + "\n")
