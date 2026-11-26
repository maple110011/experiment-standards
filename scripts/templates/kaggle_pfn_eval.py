#!/usr/bin/env python3
"""kaggle_pfn_eval.py - 在 Kaggle T4 上跑一个最小的 TabPFN 评测（真机验证用）.

它做四件事：
1. 安装 tabpfn（走 Kaggle 的互联网）；
2. 确认 GPU 可用；
3. 在 2 个小型 OpenML 数据集上做 fit/predict，记录 accuracy / ROC-AUC / 耗时；
4. 写 /kaggle/working/{environment.json, metrics.csv, run.log, result.json}。

推送方式：
  python pfn-compute-research/scripts/kaggle_job.py submit --name pfn-eval \
      --file pfn-compute-research/scripts/templates/kaggle_pfn_eval.py --timeout-seconds 3600
"""
import json
import os
import platform
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone

WORK = "/kaggle/working"
os.makedirs(WORK, exist_ok=True)

# 注意：不要在 Kaggle 的 kernel 里替换 sys.stdout / sys.stderr。
# Kaggle 的 notebook 执行器依赖标准输出捕获，替换后会把本来成功的 kernel 标成 ERROR
# （本仓库 2026-11-26 实测踩到过）。日志直接 print，Kaggle 会自动收集成 kernel log。


def sh(cmd, timeout=300):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    out = ((p.stdout or "") + (p.stderr or "")).strip()
    print("$ %s\n%s" % (cmd, out[-1200:]), flush=True)
    return p.returncode, out


def capture_env():
    def q(cmd):
        try:
            p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
            return (p.stdout or p.stderr or "").strip()[:2000]
        except Exception as e:
            return "ERR %s" % e
    env = {
        "timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "hostname": platform.node(),
        "platform": platform.platform(),
        "python": sys.version,
        "cpu_count": os.cpu_count(),
        "gpu": q("nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader"),
        "working_disk": q("df -h /kaggle/working | tail -1"),
    }
    try:
        import torch
        env["torch"] = torch.__version__
        env["cuda_available"] = bool(torch.cuda.is_available())
        env["cuda_device_count"] = torch.cuda.device_count()
        env["cuda_device_name"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
    except Exception as e:
        env["torch_error"] = str(e)
    try:
        import tabpfn
        env["tabpfn"] = getattr(tabpfn, "__version__", "unknown")
    except Exception as e:
        env["tabpfn_error"] = str(e)
    return env


def load_dataset(name):
    from sklearn.datasets import fetch_openml
    ds = fetch_openml(name, version=1, as_frame=True, parser="auto")
    X = ds.data.copy()
    y = ds.target
    # 目标编码成 0/1 整数（两个数据集都是二分类）
    if str(y.dtype) in ("object", "category"):
        y = y.astype("category").cat.codes.astype(int)
    else:
        y = y.astype(int)
    # 类别特征统一成 category dtype / 数值列保持原样
    for c in X.columns:
        if str(X[c].dtype) in ("object", "category"):
            X[c] = X[c].astype("category")
    return X, y


def eval_one(name, seed=0):
    from sklearn.metrics import accuracy_score, roc_auc_score
    from sklearn.model_selection import train_test_split
    from tabpfn import TabPFNClassifier

    t0 = time.time()
    X, y = load_dataset(name)
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=seed, stratify=y)
    clf = TabPFNClassifier(device="cuda", random_state=seed)
    clf.fit(Xtr, ytr)
    pred = clf.predict(Xte)
    acc = float(accuracy_score(yte, pred))
    auc = None
    try:
        proba = clf.predict_proba(Xte)
        auc = float(roc_auc_score(yte, proba[:, 1]))
    except Exception as e:
        print("AUC skip:", e, flush=True)
    row = {
        "dataset": name,
        "n_train": int(len(Xtr)),
        "n_test": int(len(Xte)),
        "n_features": int(X.shape[1]),
        "accuracy": round(acc, 4),
        "roc_auc": round(auc, 4) if auc is not None else None,
        "seconds": round(time.time() - t0, 2),
    }
    print("RESULT " + json.dumps(row, ensure_ascii=False), flush=True)
    return row


def main():
    result = {"exit_code": 0, "ok": True}
    try:
        print("== kaggle pfn eval ==", flush=True)
        result["environment"] = capture_env()
        # TabPFN 2.x 的本地权重需要一次性接受 license 并设置 TABPFN_TOKEN。
        # 在 Kaggle 上推荐用 Secrets：Add-ons -> Secrets 添加 TABPFN_TOKEN。
        token = os.environ.get("TABPFN_TOKEN")
        if not token:
            try:
                from kaggle_secrets import UserSecretsClient
                token = UserSecretsClient().get_secret("TABPFN_TOKEN")
            except Exception as e:
                print("读取 Kaggle Secret TABPFN_TOKEN 失败: %s" % e, flush=True)
        if token:
            os.environ["TABPFN_TOKEN"] = token
            print("TABPFN_TOKEN: 已设置（长度 %d）" % len(token), flush=True)
        else:
            raise RuntimeError(
                "缺少 TABPFN_TOKEN：先在 https://ux.priorlabs.ai 登录并接受 license，"
                "从 Account 复制 API Key，然后在 Kaggle 内核的 Add-ons -> Secrets 里添加 "
                "标签 TABPFN_TOKEN（或改用不需要权重的 kaggle_pfn_train_smoke.py）")
        print("== pip install tabpfn ==", flush=True)
        rc, out = sh("python -m pip install -q --no-cache-dir tabpfn", timeout=900)
        if rc != 0:
            raise RuntimeError("pip install tabpfn 失败（rc=%d）" % rc)
        import torch
        import tabpfn
        print("torch=%s cuda=%s tabpfn=%s" % (torch.__version__, torch.cuda.is_available(), getattr(tabpfn, "__version__", "?")), flush=True)
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA 不可用")

        rows = []
        for name in ("credit-g", "diabetes"):
            rows.append(eval_one(name))
        result["metrics"] = rows
        with open(os.path.join(WORK, "metrics.csv"), "w", encoding="utf-8") as f:
            keys = ["dataset", "n_train", "n_test", "n_features", "accuracy", "roc_auc", "seconds"]
            f.write(",".join(keys) + "\n")
            for r in rows:
                f.write(",".join(str(r.get(k)) for k in keys) + "\n")
        result["environment"].update(capture_env())
    except Exception:
        tb = traceback.format_exc()
        print(tb, flush=True)
        result.update({"exit_code": 1, "ok": False, "error": tb[-4000:]})
    finally:
        with open(os.path.join(WORK, "environment.json"), "w", encoding="utf-8") as f:
            json.dump(result.get("environment", {}), f, ensure_ascii=False, indent=2, default=str)
        with open(os.path.join(WORK, "result.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        print("result.json:", json.dumps({k: result.get(k) for k in ("exit_code", "ok")}), flush=True)
        with open(os.path.join(WORK, "run.log"), "w", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False, indent=2, default=str)[:200000] + "\n")
    return result.get("exit_code", 1)


if __name__ == "__main__":
    main()
    sys.exit(0)  # kernel 本身正常结束，成败由 result.json 表达
