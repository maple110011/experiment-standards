#!/usr/bin/env python3
"""评测噪声下界估计器 (evaluation noise floor).

摘要卡里的「不确定度」字段不能是形容词。本脚本把一个评分公式换算成
「该榜上最小的可检测改进量」，让:

  - 小于下界的改进一律记 `薄`，不得写成结论;
  - 阈值附近的抖动可以被识别为噪声而不是信号。

用法
----
1) 蒙特卡洛 (只需知道公式与测试集规模, 不需要标签):

    python score_noise_floor.py --n-test 510 --formula recall_exp_fpr \
        --tau 0.05 --k 3 --pos-ratio 0.03,0.15 --pos-grid 25

2) 精确枚举 (已知 P/N 时, 直接给出分数分布的各分位数):

    python score_noise_floor.py --n-test 510 --pos 41 --formula recall_exp_fpr \
        --tau 0.05 --k 3 --enumerate

公式按 `--formula` 选择, 也可用 `--expr` 传 Python 表达式(变量 recall/fpr/acc/auc)。
本脚本只做估计, 不替你判断。
"""

from __future__ import annotations

import argparse
import math


# --------------------------------------------------------------------------- #
# 评分公式
# --------------------------------------------------------------------------- #
def score_recall_exp_fpr(recall: float, fpr: float, tau: float, k: float) -> float:
    """`100 * min(1, recall * exp(k * (tau - fpr)))` —— **召回×指数惩罚型**公式。

    形状是"召回越高越好、假正率以指数代价被惩罚"，100 是满分截断。
    本 skill 的首个实例用的就是这个形状（其 `k` / `τ` 由那个课题给定）；
    换一个课题若公式不同，用 `--expr` 直接传表达式，或往 `FORMULAS` 里加一条。
    """
    return 100.0 * min(1.0, recall * math.exp(k * (tau - fpr)))


def score_f1(recall: float, fpr: float, tau: float, k: float, precision: float = 1.0) -> float:
    """占位: F1 型公式(需要 precision, 默认取 1.0 以便对照量级)。"""
    if precision + recall <= 0:
        return 0.0
    return 200.0 * precision * recall / (precision + recall)


FORMULAS = {
    "recall_exp_fpr": score_recall_exp_fpr,
    "f1": score_f1,
}


def make_scorer(args):
    if args.expr:
        code = compile(args.expr, "<expr>", "eval")

        def _scorer(recall, fpr, tau, k):
            return float(eval(code, {"math": math, "__builtins__": {}},
                              {"recall": recall, "fpr": fpr, "tau": tau, "k": k}))

        return _scorer
    return FORMULAS[args.formula]


# --------------------------------------------------------------------------- #
# 精确分布: 在 (TP, FP) 网格上枚举
# --------------------------------------------------------------------------- #
def enumerate_grid(n_pos: int, n_neg: int, scorer, tau: float, k: float,
                   recall_support: float = 1.0):
    """返回 {(score): (tp, fp, recall, fpr)} 的完整枚举。

    recall_support < 1 时只枚举 recall 达到该比例以上的区域, 用于观察"召回损失换低 FPR"
    的权衡带。完整的 2^n 不可行, 因此在 (TP, FP) 网格上枚举后按分数聚合。
    """
    cells = []
    tp_min = math.ceil(recall_support * n_pos) if n_pos else 0
    for tp in range(tp_min, n_pos + 1):
        recall = tp / n_pos if n_pos else 0.0
        for fp in range(0, n_neg + 1):
            fpr = fp / n_neg if n_neg else 0.0
            cells.append((tp, fp, recall, fpr, scorer(recall, fpr, tau, k)))
    return cells


def top_cells(cells, n: int = 12):
    return sorted(cells, key=lambda c: -c[4])[:n]


# --------------------------------------------------------------------------- #
# 蒙特卡洛: 分数分布 -> 可检测改进量
# --------------------------------------------------------------------------- #
def monte_carlo(n_test: int, pos_ratio: float, tau: float, k: float, scorer,
                trials: int, seed: int):
    import numpy as np

    rng = np.random.default_rng(seed)
    n_pos = int(round(n_test * pos_ratio))
    n_neg = n_test - n_pos

    # 让模型比随机略好: recall 在 [0.5, 0.95], FPR 在 [0, 0.15] 采样
    recalls = rng.uniform(0.50, 0.95, trials)
    fprs = rng.uniform(0.00, 0.15, trials)

    scores = np.array([scorer(r, f, tau, k) for r, f in zip(recalls, fprs)])

    # 单次翻转: recall +-1/P, fpr +-1/N
    flip = []
    for r, f in zip(recalls, fprs):
        for dr in (1.0 / n_pos, -1.0 / n_pos):
            for df in (1.0 / n_neg, -1.0 / n_neg):
                flip.append(abs(scorer(r, f, tau, k) - scorer(r + dr, f + df, tau, k)))
    flip = np.array(flip)

    # 真实改进 N 格命中后的分数增量(固定 recall 增益, FPR 不变)
    improved = np.array([scorer(r + 1.0 / n_pos, f, tau, k) - scorer(r, f, tau, k)
                         for r, f in zip(recalls, fprs)])

    return {
        "n_pos": n_pos,
        "n_neg": n_neg,
        "score_mean": float(scores.mean()),
        "score_p05": float(np.percentile(scores, 5)),
        "score_p95": float(np.percentile(scores, 95)),
        "flip_delta_p50": float(np.percentile(flip, 50)),
        "flip_delta_p95": float(np.percentile(flip, 95)),
        "one_positive_recall_gain": float(np.percentile(improved, 50)),
        "one_fp_penalty": float(np.percentile(
            [scorer(r, f, tau, k) - scorer(r, f + 1.0 / n_neg, tau, k)
             for r, f in zip(recalls, fprs)], 50)),
        "fpr_step": 1.0 / n_neg,
    }


# --------------------------------------------------------------------------- #
def fmt(x, nd=3):
    return f"{x:.{nd}f}"


def _parse_pos_ratio(spec: str):
    """解析 `--pos-ratio`，并把坏输入变成**可读的用法错误**而不是 traceback。

    立此函数的实测原因：原版写 `lo, hi = (float(v) for v in spec.split(","))`，
    于是 `--pos-ratio 0.05`（只给一个数）抛 `ValueError: not enough values to unpack`
    —— 一个 3 行的 traceback 摆在用户面前，看起来像脚本坏了，实际是参数写错。
    （同族：`--pos == --n-test` 会让 `1/n_neg` 除零 ⇒ 也是 traceback。）
    """
    parts = [p for p in spec.replace("，", ",").split(",") if p.strip()]
    if len(parts) != 2:
        raise ValueError(f"--pos-ratio 需要两个数（lo,hi），收到 {len(parts)} 个：{spec!r}")
    try:
        lo, hi = (float(p) for p in parts)
    except ValueError:
        raise ValueError(f"--pos-ratio 必须是数字：{spec!r}")
    if not (0.0 < lo <= hi < 1.0):
        raise ValueError(f"--pos-ratio 需满足 0 < lo ≤ hi < 1，收到 {lo}, {hi}")
    return lo, hi


def main():
    ap = argparse.ArgumentParser(description="评测噪声下界估计器")
    ap.add_argument("--n-test", type=int, required=True, help="测试集规模(切片/样本数)")
    ap.add_argument("--tau", type=float, default=0.05, help="评分公式中的容忍阈值")
    ap.add_argument("--k", type=float, default=3.0, help="指数惩罚系数")
    ap.add_argument("--formula", default="recall_exp_fpr", choices=sorted(FORMULAS))
    ap.add_argument("--expr", default=None, help="自定义评分表达式, 变量: recall/fpr/tau/k")
    ap.add_argument("--pos", type=int, default=None, help="已知正类数 -> 精确枚举")
    ap.add_argument("--pos-ratio", default="0.03,0.15",
                    help="未知正类数时的扫描区间, 逗号分隔")
    ap.add_argument("--pos-grid", type=int, default=25, help="扫描点数")
    ap.add_argument("--trials", type=int, default=4000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--enumerate", action="store_true", help="精确枚举 (需 --pos)")
    args = ap.parse_args()

    # ---- 输入护栏：坏参数给"用法错误"（退出码 2），不给 traceback ----
    if args.n_test <= 0:
        ap.error("--n-test 必须为正")
    if args.pos_grid < 2:
        ap.error("--pos-grid 至少为 2")
    if args.enumerate:
        if args.pos is None:
            ap.error("--enumerate 需要 --pos")
        if not (0 < args.pos < args.n_test):
            ap.error(f"--pos 必须满足 0 < pos < n_test（收到 pos={args.pos}, "
                     f"n_test={args.n_test}）—— 否则负类数为 0，FPR 无定义")
    try:
        ratio_lo, ratio_hi = _parse_pos_ratio(args.pos_ratio)
    except ValueError as e:
        ap.error(str(e))

    scorer = make_scorer(args)
    print("=" * 74)
    print("评测噪声下界估计")
    print("=" * 74)
    print(f"公式       : {args.expr or args.formula}    tau={args.tau}  k={args.k}")
    print(f"测试集规模 : {args.n_test}")

    if args.enumerate:
        if args.pos is None:
            ap.error("--enumerate 需要 --pos")
        n_pos = args.pos
        n_neg = args.n_test - n_pos
        cells = enumerate_grid(n_pos, n_neg, scorer, args.tau, args.k)
        best = top_cells(cells, 10)
        print(f"\n正类 P={n_pos}  负类 N={n_neg}   FPR 步长 = 1/N = {fmt(1/n_neg, 5)}")
        print(f"recall 步长 = 1/P = {fmt(1/n_pos, 5)}\n")
        print("分数最高的 (TP,FP) 组合:")
        print(f"  {'TP':>5} {'FP':>5} {'recall':>8} {'fpr':>8} {'score':>8}")
        for tp, fp, r, f, s in best:
            print(f"  {tp:>5} {fp:>5} {r:>8.4f} {f:>8.4f} {s:>8.2f}")

        # 同一 TP 下, FP 变 1 的分数代价
        print("\n单个假阳性 (FP+1) 的分数代价 (取分数最优行的 recall):")
        r0 = best[0][2]
        for fp in range(0, min(n_neg, 25)):
            s0 = scorer(r0, fp / n_neg, args.tau, args.k)
            s1 = scorer(r0, (fp + 1) / n_neg, args.tau, args.k)
            print(f"  FP {fp:>3}->{fp+1:<3} fpr {fp/n_neg:.4f}->{(fp+1)/n_neg:.4f}  "
                  f"score {s0:6.2f} -> {s1:6.2f}   Δ={s1-s0:+.2f}")
        return 0

    lo, hi = ratio_lo, ratio_hi
    ratios = [lo + (hi - lo) * i / max(1, args.pos_grid - 1) for i in range(args.pos_grid)]
    print(f"\n正类比例扫描 {lo:.3f}..{hi:.3f}")
    print(f"  {'P':>4} {'N':>5} {'FPR步长':>9} {'1FP代价':>9} {'1TP收益':>9} "
          f"{'单次翻转p50':>11} {'单次翻转p95':>11}")
    rows = []
    for ratio in ratios:
        res = monte_carlo(args.n_test, ratio, args.tau, args.k, scorer,
                          args.trials, args.seed)
        rows.append(res)
        print(f"  {res['n_pos']:>4} {res['n_neg']:>5} {res['fpr_step']:>9.5f} "
              f"{res['one_fp_penalty']:>9.2f} {res['one_positive_recall_gain']:>9.2f} "
              f"{res['flip_delta_p50']:>11.2f} {res['flip_delta_p95']:>11.2f}")

    print("\n" + "-" * 74)
    print("读法:")
    print("  * 1FP代价 = 多报一个假阳性带来的分数变化(正数=涨分, 说明 fpr 已在 tau 之下);")
    print("  * 单次翻转 p50/p95 = 一个预测翻转造成的分数抖动范围;")
    print("  * 小于「单次翻转 p95」的改进不构成证据, 记 `薄`;")
    print("  * 需要 N 个独立正确翻转才能站住的改进量, 用它反推协议块的样本量要求。")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
