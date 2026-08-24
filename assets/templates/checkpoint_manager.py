"""
Checkpoint 管理器 — 定期保存 / 断点续训 / 保留最佳 / 自动清理。

用法:
    ckpt_mgr = CheckpointManager("checkpoints", keep_recent_n=3, mode="min")
    resume = ckpt_mgr.load()          # 尝试恢复最近的 checkpoint
    # 训练循环中:
    #   ckpt_mgr.save(epoch, CONFIG, model_state, opt_state, rng_state)
    # 评估后:
    #   if ckpt_mgr.update_best(epoch, val_metric):
    #       ckpt_mgr.save(..., is_best=True)

RNG 状态请使用本文件的 capture_rng_state() / restore_rng_state(),
它们会同时保存/恢复 torch、numpy 和 python random 的状态。
"""
import os, random, json
import numpy as np
import torch
from datetime import datetime


def capture_rng_state():
    """返回可 pickle 的完整 RNG 状态 (torch + numpy + python random)。"""
    return {
        "torch": torch.get_rng_state(),
        "numpy": np.random.get_state(),
        "python": random.getstate(),
    }


def restore_rng_state(state):
    if not state:
        return
    if "torch" in state and state["torch"] is not None:
        torch.set_rng_state(state["torch"])
    if "numpy" in state and state["numpy"] is not None:
        np.random.set_state(state["numpy"])
    if "python" in state and state["python"] is not None:
        random.setstate(state["python"])


class CheckpointManager:
    def __init__(self, save_dir="checkpoints", keep_recent_n=3, mode="min"):
        self.save_dir = save_dir
        self.keep_recent_n = keep_recent_n
        self.mode = mode
        self.best_val_metric = float("inf") if mode == "min" else float("-inf")
        self.best_epoch = 0
        os.makedirs(save_dir, exist_ok=True)

    def save(self, epoch, config, model_state, optimizer_state,
             rng_state, is_best=False):
        ckpt = {
            "format_version": 1,
            "epoch": epoch,
            "config": config,
            "model_state": model_state,
            "optimizer_state": optimizer_state,
            "rng_state": rng_state,
            "best_val_metric": self.best_val_metric,
            "best_epoch": self.best_epoch,
            "timestamp": datetime.now().isoformat(),
        }
        path = os.path.join(self.save_dir, f"ckpt_epoch{epoch}.tar")
        torch.save(ckpt, path)
        if is_best:
            torch.save(ckpt, os.path.join(self.save_dir, "ckpt_best.tar"))
        self._cleanup()
        return path

    def load(self, path=None):
        if path is None:
            files = sorted(
                [f for f in os.listdir(self.save_dir)
                 if f.startswith("ckpt_epoch")],
                key=lambda f: int(f.split("epoch")[1].split(".")[0])
            )
            path = os.path.join(self.save_dir, files[-1]) if files else None
        if path is None:
            return None
        try:
            ckpt = torch.load(path, map_location="cpu", weights_only=False)
            self.best_val_metric = ckpt.get("best_val_metric", self.best_val_metric)
            self.best_epoch = ckpt.get("best_epoch", 0)
            return ckpt
        except Exception as e:
            print(f"⚠️ Checkpoint 损坏 ({path}): {e}, 从头训练")
            return None

    def update_best(self, epoch, val_metric):
        if self.mode == "min":
            improved = val_metric < self.best_val_metric
        elif self.mode == "max":
            improved = val_metric > self.best_val_metric
        else:
            raise ValueError("mode must be 'min' or 'max'")
        if improved:
            self.best_val_metric = val_metric
            self.best_epoch = epoch
            return True
        return False

    def _cleanup(self):
        files = sorted(
            [f for f in os.listdir(self.save_dir)
             if f.startswith("ckpt_epoch")],
            key=lambda f: int(f.split("epoch")[1].split(".")[0]),
            reverse=True
        )
        for f in files[self.keep_recent_n:]:
            os.remove(os.path.join(self.save_dir, f))
