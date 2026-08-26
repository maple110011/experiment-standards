"""
experiment_recorder.py — 一般性大型实验记录工具。

与具体实验领域无关，适用于任何 PyTorch/Python 训练任务。设计目标:
  实验跑完后无需重跑即可回答:
  1. 跑的是什么代码?         -> code/ 代码快照 + sha256 + git commit
  2. 什么配置/数据/环境?      -> run_manifest.json + dataset_info
  3. 中间发生了什么?         -> events.jsonl + errors.log
  4. 每个 epoch/step 指标?    -> training/<method>_metrics.csv
  5. 预测分布还在不在?        -> predictions/*_probs.npy 或 *_samples.npz
  6. 长跑中途挂了丢了什么?     -> results_partial.json 每完成一部分立即落盘
  7. 模型与显存消耗?          -> model_summary() + gpu_memory()

用法:
    from experiment_recorder import make_run_dir, log_event, log_epoch, \
        update_results_json, save_probs, save_regression_predictions, \
        save_samples_npz, save_split_indices, update_shift_results_json, \
        save_temperature_scaling, save_model_weights, gpu_memory, model_summary

    run_dir = make_run_dir(
        "runs", "my_experiment",
        config=CONFIG, args=vars(args),
        code_paths=[__file__, "model.py", "data.py"],
        dataset_info={"n_train": 1000, "n_test": 200},
        notes="第一次正式训练",
    )
    log_event(run_dir, "data_loaded", n_train=1000)
    ...
    log_epoch(run_dir, "MAP", epoch, loss=0.1, val_acc=0.9)
    update_results_json(run_dir, "results_partial.json", "MAP", {"acc": 0.9})
    save_probs(run_dir, "MAP", probs, y_true, num_classes)
"""
import os, sys, json, csv, hashlib, shutil, time, subprocess
from datetime import datetime

# TensorBoard 写入器缓存 (run_dir -> SummaryWriter)
_TB_WRITERS = {}


# ---------------------------------------------------------------------------
# 基础
# ---------------------------------------------------------------------------
def now_iso():
    return datetime.now().isoformat()


def sha256_file(path, block=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(block), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def get_git_commit(path):
    try:
        out = subprocess.run(
            ["git", "-C", path, "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# 代码快照
# ---------------------------------------------------------------------------
def snapshot_code(code_paths, dest_dir):
    """把实际运行的代码文件/目录复制到 dest_dir/code/ 并返回 {相对路径: sha256}。"""
    code_dir = os.path.join(dest_dir, "code")
    os.makedirs(code_dir, exist_ok=True)
    records = {}
    for path in code_paths or []:
        path = os.path.abspath(path)
        if os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git", ".mplcache")]
                for f in files:
                    if f.endswith((".pyc", ".tar", ".gz", ".pt", ".png", ".jpg", ".npy", ".npz")):
                        continue
                    src = os.path.join(root, f)
                    rel = os.path.relpath(src, path)
                    dst = os.path.join(code_dir, os.path.basename(path), rel)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)
                    records[os.path.join(os.path.basename(path), rel)] = sha256_file(src)
        elif os.path.isfile(path):
            dst = os.path.join(code_dir, os.path.basename(path))
            shutil.copy2(path, dst)
            records[os.path.basename(path)] = sha256_file(path)
    return records


# ---------------------------------------------------------------------------
# run 目录与 manifest
# ---------------------------------------------------------------------------
def make_run_dir(base_dir, experiment, config=None, args=None, code_paths=None,
                 dataset_info=None, env=None, notes="", run_id=None):
    """创建标准 run 目录并写入 run_manifest.json。返回 run_dir。"""
    run_id = run_id or datetime.now().strftime("run_%Y%m%d_%H%M%S_%f")
    run_dir = os.path.join(os.path.abspath(base_dir), str(experiment), run_id)
    for sub in ("checkpoints", "predictions", "training", "figures", "tb"):
        os.makedirs(os.path.join(run_dir, sub), exist_ok=True)

    if env is None:
        try:
            # 优先从同目录的 environment_capture 导入
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from environment_capture import capture_environment
            env = capture_environment()
        except Exception as e:
            env = {"capture_error": str(e)}

    git_commit = None
    for p in (code_paths or []):
        git_commit = get_git_commit(os.path.dirname(os.path.abspath(p)))
        if git_commit:
            break
    if not git_commit:
        git_commit = get_git_commit(os.getcwd())

    manifest = {
        "run_id": run_id,
        "experiment": experiment,
        "timestamp": now_iso(),
        "host": os.uname().nodename if hasattr(os, "uname") else None,
        "git_commit": git_commit,
        "config": config or {},
        "args": args or {},
        "dataset_info": dataset_info or {},
        "environment": env,
        "code_files": snapshot_code(code_paths or [], run_dir),
        "notes": notes,
    }
    with open(os.path.join(run_dir, "run_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False, default=str)
    return run_dir


# ---------------------------------------------------------------------------
# 日志 / 事件 / 错误
# ---------------------------------------------------------------------------
def log_event(run_dir, event_type, **data):
    line = {"timestamp": now_iso(), "event": event_type, **data}
    with open(os.path.join(run_dir, "events.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")
    return line


def log_exception(run_dir, exc_info=None):
    """把异常堆栈写入 errors.log, 返回 message。"""
    import traceback
    msg = traceback.format_exc() if exc_info is None else "".join(traceback.format_exception(*exc_info))
    log_error(run_dir, "EXCEPTION\n" + msg)
    return msg


def log_error(run_dir, message):
    with open(os.path.join(run_dir, "errors.log"), "a", encoding="utf-8") as f:
        f.write(f"{now_iso()} [ERROR] {message}\n")


def _tb_writer(run_dir):
    """获取 run_dir 对应的 TensorBoard writer (惰性创建)。"""
    try:
        from torch.utils.tensorboard import SummaryWriter
    except Exception:
        return None
    if run_dir not in _TB_WRITERS:
        _TB_WRITERS[run_dir] = SummaryWriter(log_dir=os.path.join(run_dir, "tb"))
    return _TB_WRITERS[run_dir]


def log_epoch(run_dir, method_name, epoch, **metrics):
    """追加一行训练指标到 training/<method>_metrics.csv, 同时写 TensorBoard。"""
    path = os.path.join(run_dir, "training", f"{method_name}_metrics.csv")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fields = ["epoch"] + sorted(metrics.keys())
    need_header = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if need_header:
            w.writeheader()
        w.writerow({"epoch": epoch, **metrics})
    writer = _tb_writer(run_dir)
    if writer is not None:
        for k, v in metrics.items():
            if isinstance(v, (int, float)):
                scope = "val" if str(k).startswith("val_") else "train"
                writer.add_scalar(f"{scope}/{method_name}/{k}", float(v), int(epoch))
        writer.flush()


def log_scalar(run_dir, tag, value, step):
    """直接写一个 TensorBoard 标量。"""
    writer = _tb_writer(run_dir)
    if writer is not None:
        writer.add_scalar(tag, float(value), int(step))
        writer.flush()


def close_tb(run_dir):
    """关闭 run_dir 的 TensorBoard writer (可选)。"""
    writer = _TB_WRITERS.pop(run_dir, None)
    if writer is not None:
        try:
            writer.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 结果 / 预测保存
# ---------------------------------------------------------------------------
def update_results_json(run_dir, filename, method_name, result):
    """增量写入部分结果: 每完成一个方法/阶段立即落盘。"""
    path = os.path.join(run_dir, filename)
    data = {}
    if os.path.exists(path):
        try:
            with open(path) as f:
                data = json.load(f)
        except Exception:
            pass
    if "methods" not in data:
        data["methods"] = {}
    data["methods"][method_name] = result
    data["last_updated"] = now_iso()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


def update_shift_results_json(run_dir, shift_name, method_name, result):
    """增量写入分布偏移/OOD 评估结果到 evaluation_shift.json。"""
    path = os.path.join(run_dir, "evaluation_shift.json")
    data = {}
    if os.path.exists(path):
        try:
            with open(path) as f:
                data = json.load(f)
        except Exception:
            pass
    if "shifts" not in data:
        data["shifts"] = {}
    data["shifts"].setdefault(shift_name, {})[method_name] = result
    data["last_updated"] = now_iso()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


def save_temperature_scaling(run_dir, method_name, temperature, before, after, extra=None):
    """记录后校准 (temperature scaling / variance calibration) 结果。"""
    path = os.path.join(run_dir, "calibration_temperature.json")
    data = {}
    if os.path.exists(path):
        try:
            with open(path) as f:
                data = json.load(f)
        except Exception:
            pass
    entry = {"temperature": temperature, "before": before, "after": after}
    if extra:
        entry.update(extra)
    data[method_name] = entry
    data["last_updated"] = now_iso()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)


def save_probs(run_dir, method_name, probs, y_true, num_classes, extra=None):
    """保存后验预测概率与真实标签 (可复算任意指标)。"""
    import numpy as np
    pred_dir = os.path.join(run_dir, "predictions")
    os.makedirs(pred_dir, exist_ok=True)
    np.save(os.path.join(pred_dir, f"{method_name}_probs.npy"), np.asarray(probs, dtype=np.float32))
    np.save(os.path.join(pred_dir, f"{method_name}_ytrue.npy"), np.asarray(y_true))
    meta = {
        "method": method_name, "saved_at": now_iso(),
        "probs_shape": list(np.asarray(probs).shape),
        "num_classes": num_classes,
        "y_true_shape": list(np.asarray(y_true).shape),
    }
    if extra:
        meta.update(extra)
    with open(os.path.join(pred_dir, f"{method_name}_meta.json"), "w") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False, default=str)


def save_regression_predictions(run_dir, method_name, mean, var, y_true, extra=None):
    """保存回归预测均值与方差 (可复算 RMSE/coverage/NLL/calibration 等)。"""
    import numpy as np
    pred_dir = os.path.join(run_dir, "predictions")
    os.makedirs(pred_dir, exist_ok=True)
    np.save(os.path.join(pred_dir, f"{method_name}_mean.npy"), np.asarray(mean, dtype=np.float32))
    np.save(os.path.join(pred_dir, f"{method_name}_var.npy"), np.asarray(var, dtype=np.float32))
    np.save(os.path.join(pred_dir, f"{method_name}_ytrue.npy"), np.asarray(y_true))
    meta = {
        "method": method_name, "saved_at": now_iso(),
        "mean_shape": list(np.asarray(mean).shape),
        "var_shape": list(np.asarray(var).shape),
        "y_true_shape": list(np.asarray(y_true).shape),
    }
    if extra:
        meta.update(extra)
    with open(os.path.join(pred_dir, f"{method_name}_reg_meta.json"), "w") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False, default=str)


def save_samples_npz(run_dir, method_name, samples, y_true, extra=None):
    """保存后验预测原始样本 (比概率更完整)。"""
    import numpy as np
    pred_dir = os.path.join(run_dir, "predictions")
    os.makedirs(pred_dir, exist_ok=True)
    np.savez_compressed(
        os.path.join(pred_dir, f"{method_name}_samples.npz"),
        samples=np.asarray(samples), y_true=np.asarray(y_true),
    )
    meta = {
        "method": method_name, "saved_at": now_iso(),
        "samples_shape": list(np.asarray(samples).shape),
        "y_true_shape": list(np.asarray(y_true).shape),
    }
    if extra:
        meta.update(extra)
    with open(os.path.join(pred_dir, f"{method_name}_samples_meta.json"), "w") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False, default=str)


def save_split_indices(run_dir, train_idx, val_idx, test_idx, extra=None):
    """保存数据切分索引, 保证以后可以精确重建切分。"""
    import numpy as np
    path = os.path.join(run_dir, "split_indices.npz")
    np.savez_compressed(
        path,
        train_idx=np.asarray(train_idx), val_idx=np.asarray(val_idx),
        test_idx=np.asarray(test_idx),
    )
    if extra:
        with open(os.path.join(run_dir, "split_indices_meta.json"), "w") as f:
            json.dump(extra, f, indent=2, ensure_ascii=False, default=str)
    return path


# ---------------------------------------------------------------------------
# 模型 / 硬件
# ---------------------------------------------------------------------------
def plot_regression_calibration(run_dir, method_name, mean, var, y_true, levels=(0.5,0.8,0.9,0.95)):
    """回归校准曲线: 名义覆盖率 vs 经验覆盖率, 保存到 figures/。"""
    import numpy as np
    mean = np.asarray(mean).reshape(-1); var = np.asarray(var).reshape(-1); y = np.asarray(y_true).reshape(-1)
    std = np.sqrt(np.maximum(var, 1e-12))
    z = {0.5:0.674, 0.8:1.282, 0.9:1.645, 0.95:1.96}
    xs = [lv for lv in levels]; ys = []
    for lv in levels:
        zz = z[lv]; lo = mean - zz*std; hi = mean + zz*std
        ys.append(float(np.mean((y >= lo) & (y <= hi))))
    fig_dir = os.path.join(run_dir, "figures"); os.makedirs(fig_dir, exist_ok=True)
    path = os.path.join(fig_dir, f"calibration_{method_name}.png")
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.figure(figsize=(5,5))
        plt.plot([0,1],[0,1],'--',color='gray',label='perfect')
        plt.plot(xs, ys, 'o-', label=method_name)
        plt.xlabel('nominal coverage'); plt.ylabel('empirical coverage')
        plt.legend(); plt.grid(alpha=0.3); plt.title(f'Regression calibration: {method_name}')
        plt.savefig(path, dpi=100); plt.close()
    except Exception:
        pass
    return path


def plot_reliability_diagram(run_dir, method_name, probs, y_true, num_classes=None, n_bins=10):
    """画 reliability diagram (置信度 vs 真实准确率) 并保存到 figures/。"""
    import numpy as np
    probs = np.asarray(probs)
    y_true = np.asarray(y_true)
    if num_classes is None:
        num_classes = probs.shape[-1] if probs.ndim == 2 else 2
    conf = probs.max(-1) if probs.ndim == 2 else probs
    pred = probs.argmax(-1) if probs.ndim == 2 else (probs > 0.5).astype(np.int64)
    acc = (pred == y_true).astype(np.float32)
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    bin_ids = np.digitize(conf, bins[1:-1])
    fig_dir = os.path.join(run_dir, "figures"); os.makedirs(fig_dir, exist_ok=True)
    path = os.path.join(fig_dir, f"reliability_{method_name}.png")
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        xs = []; ys = []
        for b in range(n_bins):
            m = bin_ids == b
            if m.sum() > 0:
                xs.append(float(conf[m].mean())); ys.append(float(acc[m].mean()))
        plt.figure(figsize=(5,5))
        plt.plot([0,1],[0,1],'--',color='gray',label='perfect')
        plt.plot(xs, ys, 'o-', label=method_name)
        plt.xlabel('confidence'); plt.ylabel('accuracy'); plt.legend(); plt.grid(alpha=0.3)
        plt.title(f'Reliability: {method_name}')
        plt.savefig(path, dpi=100); plt.close()
    except Exception:
        pass
    return path


def save_model_weights(run_dir, method_name, model_or_state, filename=None, is_best=True):
    """保存模型权重到 checkpoints/。可传 model (有 state_dict) 或 state_dict。"""
    import torch
    ckpt_dir = os.path.join(run_dir, "checkpoints")
    os.makedirs(ckpt_dir, exist_ok=True)
    state = model_or_state.state_dict() if hasattr(model_or_state, "state_dict") else model_or_state
    filename = filename or (f"{method_name}_best.pt" if is_best else f"{method_name}_final.pt")
    path = os.path.join(ckpt_dir, filename)
    torch.save(state, path)
    return path


def model_summary(model):
    """返回模型参数量与每层形状。"""
    total = 0
    shapes = {}
    for name, p in model.named_parameters():
        shapes[name] = list(p.shape)
        total += p.numel()
    return {"total_params": total, "trainable_params": total, "param_shapes": shapes}


def gpu_memory(device="cuda"):
    """返回当前 CUDA/DCU 显存使用 (GB)。无 GPU 返回 None。"""
    try:
        import torch
        if device == "cuda" and torch.cuda.is_available():
            return {
                "allocated_gb": round(torch.cuda.memory_allocated() / 1024**3, 3),
                "reserved_gb": round(torch.cuda.memory_reserved() / 1024**3, 3),
            }
    except Exception:
        pass
    return None


def dataset_summary(X=None, y=None, **extra):
    """返回数据集形状/类型/类别分布等概要。X,y 可以是 numpy 或 torch.Tensor。"""
    info = dict(extra)
    for name, arr in (("X", X), ("y", y)):
        if arr is None:
            continue
        try:
            import numpy as np
            a = arr.cpu().numpy() if hasattr(arr, "cpu") else np.asarray(arr)
            info[f"{name}_shape"] = list(a.shape)
            info[f"{name}_dtype"] = str(a.dtype)
            if name == "y":
                info["y_unique"] = np.unique(a).tolist()[:20]
        except Exception:
            pass
    return info
