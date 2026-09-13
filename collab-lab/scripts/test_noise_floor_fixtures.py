#!/usr/bin/env python -u
# -*- coding: utf-8 -*-
r"""`score_noise_floor.py` 的 fixtures：把这个**估计器**钉在可手算的锚点上。

## 为什么它值得一组 fixtures（不是"补个形式"）

全项目的 MDE 判据都建立在它输出的两个数上：**噪声下界 ≈0.05** 与
**一个事件的分辨率 ≈0.1**（`CHARTER.md` 第 4 节、各协议块的"最小可检测效应"）。
如果这个估计器悄悄坏了，**所有"改进小于下界 ⇒ 记薄"的判断都会一起失效**，
而且失效方式会是"数字照印、只是不对"。

所以 fixtures 钉的不是"脚本能跑"，而是**两件可手算的事**：

1. **赛题公式的实现**：`100·min(1, recall·exp(k(τ−fpr)))`。
   取 `n_test=510, P=41, τ=0.05, k=3` ⇒ `N=469`。
   `recall=1` 时分数被 `min(1,·)` 截断在 100，而截断条件是 `fpr ≤ τ`
   ⇔ `fp/469 ≤ 0.05` ⇔ **`fp ≤ 23`**。
   ⇒ **第 23 行是最后一个仍得满分的 FP，`FP 23->24` 那一步必须第一次转负。**
   这个数字不依赖任何随机性，改坏公式或改坏枚举边界都会立刻被抓住。
2. **输入护栏**：坏参数要给"用法错误"（退出码 2、可读消息），**不是 traceback**。
   原版在 `--pos == --n-test` 时除零、`--pos-ratio` 只给一个数时解包失败 ——
   两者都是把内部错误直接摔在用户脸上。

反向对照：`agree`/`invariants` 两个场景是"**不该报错**"的一侧，
所以任何"一律 exit 2"或"一律 traceback"的改动都会失败（`B28` 第 ② 项）。

用法：`python scripts/test_noise_floor_fixtures.py`
"""
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import subproc  # noqa: E402  （子进程编码只有这一处定义）
SCRIPT = HERE / "score_noise_floor.py"

BASE = ["--n-test", "510", "--tau", "0.05", "--k", "3"]


def run(extra):
    r = subproc.run_text([sys.executable, str(SCRIPT)] + BASE + extra)
    return r.returncode, r.stdout, r.stderr


def sweep_rows(out):
    """从 FP 扫描表里取出 [(fp_from, delta)]，按出现顺序。"""
    rows = []
    for line in out.splitlines():
        m = re.search(r"FP\s+(\d+)->\d+.*?Δ=\s*([+-][\d.]+)", line)
        if m:
            rows.append((int(m.group(1)), float(m.group(2))))
    return rows


def main():
    print("=" * 78)
    print("score_noise_floor fixtures（公式锚点 + 输入护栏；含「不该报错」的反向对照）")
    print("=" * 78)
    ok = True

    # ---- 1. 精确枚举：可手算的锚点 ----
    code, out, err = run(["--pos", "41", "--enumerate"])
    step_fpr = "FPR 步长 = 1/N = 0.00213" in out
    step_rec = "recall 步长 = 1/P = 0.02439" in out
    rows = sweep_rows(out)
    first_neg = next((fp for fp, d in rows if d < 0), None)
    anchor = (code == 0 and step_fpr and step_rec and first_neg == 23)
    print(f"{'PASS' if anchor else 'FAIL'}  exact_golden  退出码 {code}（期望 0）  "
          f"1/N={step_fpr} 1/P={step_rec}  首个 Δ<0 出现在 FP={first_neg}（手算应为 23）")
    if not anchor:
        for line in out.splitlines()[-4:]:
            print(f"        | {line.strip()[:92]}")
    ok &= anchor

    # ---- 2. 满分上限：score 必须出现 100.00，且不得出现 >100 ----
    # ⚠️ 第一版写成 `not re.search(r"\b1\d\d\.\d\d\b", out)` —— 而 `100.00` 自己
    #    就匹配那个模式 ⇒ 断言恒假。正确写法是"取出所有两位小数，断言最大值 ≤ 100"。
    vals = [float(v) for v in re.findall(r"\b\d+\.\d{2}\b", out)]
    cap = ("100.00" in out) and bool(vals) and (max(vals) <= 100.0 + 1e-9)
    print(f"{'PASS' if cap else 'FAIL'}  cap_100       满分出现 100.00 且无超出={cap}"
          + (f"（最大 {max(vals):.2f}）" if vals else ""))
    ok &= cap

    # ---- 3. 蒙特卡洛：不变量（不是"能不能跑"，而是算式对不对）----
    code2, out2, err2 = run(["--pos-ratio", "0.03,0.15", "--pos-grid", "4", "--trials", "200"])
    pairs = re.findall(r"^\s*(\d+)\s+(\d+)\s+([\d.]+)\s", out2, re.M)
    inv_ok = bool(pairs) and all(
        abs(float(step) - 1.0 / int(n_neg)) < 5e-6 for _, n_neg, step in pairs)
    print(f"{'PASS' if inv_ok else 'FAIL'}  mc_invariants 退出码 {code2}（期望 0）  "
          f"{len(pairs)} 行，每行『FPR步长 == 1/N』={inv_ok}")
    if not inv_ok:
        for line in out2.splitlines()[-4:]:
            print(f"        | {line.strip()[:92]}")
    ok &= (code2 == 0 and inv_ok)

    # ---- 4/5. 输入护栏：坏参数给退出码 2 + 可读消息，**不许 traceback** ----
    for name, extra, want in (
            ("bad_pos", ["--pos", "510", "--enumerate"], "0 < pos < n_test"),
            ("bad_ratio", ["--pos-ratio", "0.05"], "--pos-ratio"),
            ("bad_grid", ["--pos-grid", "1"], "--pos-grid")):
        code3, out3, err3 = run(extra)
        graceful = (code3 == 2) and (want in (out3 + err3)) and ("Traceback" not in err3)
        print(f"{'PASS' if graceful else 'FAIL'}  {name:13s} 退出码 {code3}（期望 2）  "
              f"含『{want}』={'是' if want in (out3+err3) else '否'}  "
              f"无 traceback={'是' if 'Traceback' not in err3 else '否'}")
        if not graceful:
            print(f"        | {(err3 or out3).strip().splitlines()[-1][:92]}")
        ok &= graceful

    print("-" * 78)
    print("noise_floor fixtures 结果:", "全部通过" if ok else "有 FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
