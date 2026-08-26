"""
metrics.py — 贝叶斯深度学习的不确定度与校准指标。

与 experiment_recorder 配合：先保存预测分布（save_probs / save_regression_predictions /
save_samples_npz），再用本模块计算 ECE / NLL / Brier / sharpness / coverage。

用法:
    from metrics import ece_classification, nll_classification, brier_score
    from metrics import ece_regression, nll_regression, coverage, sharpness_regression

指标口径 (与 references/output-spec.md、bayes-dl-dcu 协议一致):
    - 分类: acc, NLL, Brier, ECE (top-label), sharpness (max_prob - 1/C)
    - 回归: RMSE, MAE, NLL (Gaussian), coverage95, sharpness95, ECE (多置信水平)
"""
import numpy as np


def _to_np(x):
    if hasattr(x, "detach"):
        x = x.detach()
    if hasattr(x, "cpu"):
        x = x.cpu()
    return np.asarray(x, dtype=np.float64)


# ---------------------------------------------------------------------------
# 分类
# ---------------------------------------------------------------------------
def nll_classification(probs, y_true, eps=1e-12):
    """负对数似然 (分类): -mean(log p(y_i))。probs 形状 (N, C)。"""
    probs = _to_np(probs)
    y = np.asarray(y_true).reshape(-1).astype(np.int64)
    p = np.clip(probs[np.arange(len(y)), y], eps, 1.0)
    return float(-np.mean(np.log(p)))


def brier_score(probs, y_true):
    """Brier 分数: mean(||p - onehot(y)||^2)。"""
    probs = _to_np(probs)
    y = np.asarray(y_true).reshape(-1).astype(np.int64)
    C = probs.shape[-1]
    onehot = np.eye(C)[y]
    return float(np.mean(np.sum((probs - onehot) ** 2, axis=-1)))


def ece_classification(probs, y_true, n_bins=10):
    """top-label ECE: 按置信度等宽分箱, ECE = sum(|acc - conf| * 箱占比)。"""
    probs = _to_np(probs)
    y = np.asarray(y_true).reshape(-1)
    conf = probs.max(-1)
    pred = probs.argmax(-1)
    acc = (pred == y).astype(np.float64)
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    bin_ids = np.digitize(conf, bins[1:-1])
    ece = 0.0
    for b in range(n_bins):
        m = bin_ids == b
        if m.sum() > 0:
            ece += (m.sum() / len(y)) * abs(acc[m].mean() - conf[m].mean())
    return float(ece)


def sharpness_classification(probs):
    """sharpness = mean(max_prob - 1/C)。越小越尖锐 (越"自信")。"""
    probs = _to_np(probs)
    C = probs.shape[-1]
    return float(np.mean(probs.max(-1) - 1.0 / C))


# ---------------------------------------------------------------------------
# 回归
# ---------------------------------------------------------------------------
_Z = {0.5: 0.6745, 0.8: 1.2816, 0.9: 1.6449, 0.95: 1.9600}


def rmse(mean, y_true):
    mean = _to_np(mean).reshape(-1)
    y = np.asarray(y_true).reshape(-1)
    return float(np.sqrt(np.mean((mean - y) ** 2)))


def mae(mean, y_true):
    mean = _to_np(mean).reshape(-1)
    y = np.asarray(y_true).reshape(-1)
    return float(np.mean(np.abs(mean - y)))


def nll_regression(mean, var, y_true):
    """高斯负对数似然: 0.5 * (log(2*pi*var) + (y-mean)^2 / var)。"""
    mean = _to_np(mean).reshape(-1)
    var = np.maximum(_to_np(var).reshape(-1), 1e-12)
    y = np.asarray(y_true).reshape(-1)
    return float(np.mean(0.5 * (np.log(2 * np.pi * var) + (y - mean) ** 2 / var)))


def coverage(mean, var, y_true, level=0.95):
    """经验覆盖率: 真实值落在 [mean - z*std, mean + z*std] 内的比例。"""
    mean = _to_np(mean).reshape(-1)
    var = _to_np(var).reshape(-1)
    y = np.asarray(y_true).reshape(-1)
    std = np.sqrt(np.maximum(var, 0.0))
    z = _Z[level]
    lo, hi = mean - z * std, mean + z * std
    return float(np.mean((y >= lo) & (y <= hi)))


def sharpness_regression(mean, var, y_true, level=0.95):
    """预测区间平均宽度 (2*z*std 的均值)。越小越尖锐。"""
    mean = _to_np(mean).reshape(-1)
    var = _to_np(var).reshape(-1)
    std = np.sqrt(np.maximum(var, 0.0))
    z = _Z[level]
    return float(np.mean(2 * z * std))


def ece_regression(mean, var, y_true, levels=(0.5, 0.8, 0.9, 0.95)):
    """回归 ECE: 各置信水平下 |经验覆盖率 - 名义覆盖率| 的平均值。

    返回 dict, 包含 coverage_<level> 与 ece。
    """
    out = {}
    for lv in levels:
        out[f"coverage_{lv}"] = coverage(mean, var, y_true, lv)
    out["ece"] = float(np.mean([abs(out[f"coverage_{lv}"] - lv) for lv in levels]))
    return out
