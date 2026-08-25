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
import os, random, json, hashlib
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


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


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
        self._write_sha256_sidecar(path)
        if is_best:
            best_path = os.path.join(self.save_dir, "ckpt_best.tar")
            torch.save(ckpt, best_path)
            self._write_sha256_sidecar(best_path)
        self._cleanup()
        return path

    def _write_sha256_sidecar(self, path):
        """写 .sha256 sidecar, 防止 checkpoint 静默损坏。"""
        try:
            with open(path + ".sha256", "w") as f:
                f.write(_sha256_file(path))
        except Exception:
            pass

    def _available_checkpoints(self):
        try:
            files = [f for f in os.listdir(self.save_dir)
                     if f.startswith("ckpt_epoch") and f.endswith(".tar")]
        except FileNotFoundError:
            return []
        return sorted(files, key=self._epoch_key, reverse=True)

    @staticmethod
    def _epoch_key(f):
        try:
            return int(f.split("epoch")[1].split(".")[0])
        except Exception:
            return -1

    def load(self, path=None):
        """加载 checkpoint。path=None 时从最新到最旧尝试, 损坏自动回退。"""
        if path is None:
            candidates = [os.path.join(self.save_dir, f)
                          for f in self._available_checkpoints()]
        else:
            candidates = [path]
        if not candidates:
            return None
        for cand in candidates:
            try:
                ckpt = torch.load(cand, map_location="cpu", weights_only=False)
                self.best_val_metric = ckpt.get("best_val_metric", self.best_val_metric)
                self.best_epoch = ckpt.get("best_epoch", 0)
                return ckpt
            except Exception as e:
                print(f"⚠️ Checkpoint 损坏 ({cand}): {e}, 尝试下一个")
        print("⚠️ 无可用 checkpoint, 从头训练")
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
        files = [f for f in os.listdir(self.save_dir)
                 if f.startswith("ckpt_epoch") and f.endswith(".tar")]
        files.sort(key=self._epoch_key, reverse=True)
        for f in files[self.keep_recent_n:]:
            path = os.path.join(self.save_dir, f)
            os.remove(path)
            try:
                os.remove(path + ".sha256")
            except OSError:
                pass
