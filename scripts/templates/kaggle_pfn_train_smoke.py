#!/usr/bin/env python3
"""kaggle_pfn_train_smoke.py - 在 Kaggle T4 上训练一个极小的 PFN（不依赖 TabPFN 权重）.

目的：验证「远程 GPU 上跑 PFN 训练循环」这条路是通的，而不是只跑了一次矩阵乘。
先验：y = a * sin(b x + c) + 噪声，(a,b,c) 每个 batch 随机采样；
模型：小 Transformer，上下文点 (x,y) 作为 token，查询点 (x,0) 预测 y；
不落任何 TabPFN 权重，所以不受 license 限制。

推送：
  python pfn-compute-research/scripts/kaggle_job.py submit --name pfn-train \
      --file pfn-compute-research/scripts/templates/kaggle_pfn_train_smoke.py --timeout-seconds 1800
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
LOG_LINES = []


def log(*args, **kwargs):
    """打印并把内容记进 run.log；不替换 sys.stdout，避免 Kaggle 的 notebook 捕获器被打断。"""
    print(*args, **kwargs)
    LOG_LINES.append(" ".join(str(a) for a in args))


def env_snapshot():
    def q(cmd):
        try:
            p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
            return (p.stdout or p.stderr or "").strip()[:1500]
        except Exception as e:
            return "ERR %s" % e
    env = {
        "timestamp": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "hostname": platform.node(),
        "platform": platform.platform(),
        "python": sys.version,
        "cpu_count": os.cpu_count(),
        "gpu": q("nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader"),
    }
    try:
        import torch
        env["torch"] = torch.__version__
        env["cuda_available"] = bool(torch.cuda.is_available())
        env["cuda_device_name"] = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
    except Exception as e:
        env["torch_error"] = str(e)
    return env


def make_batch(torch, bs=32, n_ctx=64, n_q=64, device="cuda"):
    x_ctx = torch.rand(bs, n_ctx, device=device) * 4 - 2
    x_q = torch.rand(bs, n_q, device=device) * 4 - 2
    a = torch.rand(bs, 1, device=device) * 2.5 + 0.5
    b = torch.rand(bs, 1, device=device) * 2.5 + 0.5
    c = torch.rand(bs, 1, device=device) * 6.283
    y_ctx = a * torch.sin(b * x_ctx + c) + 0.05 * torch.randn_like(x_ctx)
    y_q = a * torch.sin(b * x_q + c) + 0.05 * torch.randn_like(x_q)
    return x_ctx, y_ctx, x_q, y_q


class TinyPFN(object):
    pass


def build_model(torch, d=128, layers=4, heads=4):
    import torch.nn as nn

    class TinyPFNModule(nn.Module):
        def __init__(self):
            super().__init__()
            self.inp = nn.Linear(2, d)
            enc = nn.TransformerEncoderLayer(d_model=d, nhead=heads, dim_feedforward=256,
                                             batch_first=True, dropout=0.0)
            self.enc = nn.TransformerEncoder(enc, num_layers=layers)
            self.out = nn.Linear(d, 1)

        def forward(self, x_ctx, y_ctx, x_q):
            ctx = self.inp(torch.stack([x_ctx, y_ctx], dim=-1))
            qry = self.inp(torch.stack([x_q, torch.zeros_like(x_q)], dim=-1))
            tokens = torch.cat([ctx, qry], dim=1)
            h = self.enc(tokens)
            return self.out(h[:, x_ctx.shape[1]:, :]).squeeze(-1)

    return TinyPFNModule()


def main():
    result = {"exit_code": 0, "ok": True}
    try:
        import torch
        log("== kaggle tiny-PFN training smoke ==", flush=True)
        result["environment"] = env_snapshot()
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA 不可用")
        torch.manual_seed(0)
        model = build_model(torch).cuda()
        n_params = sum(p.numel() for p in model.parameters())
        log("params: %.2fM" % (n_params / 1e6), flush=True)
        opt = torch.optim.AdamW(model.parameters(), lr=1e-3)
        steps = 400
        losses = []
        t0 = time.time()
        for step in range(steps):
            x_ctx, y_ctx, x_q, y_q = make_batch(torch)
            pred = model(x_ctx, y_ctx, x_q)
            loss = torch.nn.functional.mse_loss(pred, y_q)
            opt.zero_grad()
            loss.backward()
            opt.step()
            losses.append(float(loss.detach()))
            if step % 50 == 0:
                log("step %4d loss %.5f" % (step, losses[-1]), flush=True)
        torch.cuda.synchronize()
        elapsed = time.time() - t0
        first = sum(losses[:20]) / 20
        last = sum(losses[-20:]) / 20
        peak_mb = torch.cuda.max_memory_allocated() / 1024 ** 2
        metrics = {
            "steps": steps,
            "params_m": round(n_params / 1e6, 3),
            "loss_first20": round(first, 5),
            "loss_last20": round(last, 5),
            "loss_reduction_pct": round(100 * (1 - last / first), 2),
            "seconds": round(elapsed, 2),
            "sec_per_step": round(elapsed / steps, 4),
            "peak_vram_mb": round(peak_mb, 1),
            "gpu": torch.cuda.get_device_name(0),
        }
        log("METRICS " + json.dumps(metrics, ensure_ascii=False), flush=True)
        result["metrics"] = metrics
        if last >= first:
            raise RuntimeError("loss 没有下降（first=%.5f last=%.5f）" % (first, last))
        with open(os.path.join(WORK, "metrics.csv"), "w", encoding="utf-8") as f:
            f.write(",".join(metrics.keys()) + "\n")
            f.write(",".join(str(v) for v in metrics.values()) + "\n")
        result["environment"].update(env_snapshot())
    except Exception:
        tb = traceback.format_exc()
        log(tb, flush=True)
        result.update({"exit_code": 1, "ok": False, "error": tb[-4000:]})
    finally:
        with open(os.path.join(WORK, "environment.json"), "w", encoding="utf-8") as f:
            json.dump(result.get("environment", {}), f, ensure_ascii=False, indent=2, default=str)
        with open(os.path.join(WORK, "result.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
        log("result.json:", json.dumps({k: result.get(k) for k in ("exit_code", "ok")}), flush=True)
        with open(os.path.join(WORK, "run.log"), "w", encoding="utf-8") as f:
            f.write("\n".join(LOG_LINES) + "\n")


if __name__ == "__main__":
    main()  # 不调用 sys.exit：Kaggle 的脚本 notebook 把 SystemExit 当成异常，可能把状态标成 ERROR
