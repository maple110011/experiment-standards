#!/usr/bin/env python -u
# -*- coding: utf-8 -*-
r"""`conflict_scan.py` 的 fixtures：把"什么算分歧"这个定义钉死。

## 为什么需要它

这个脚本按设计**不做裁定、也不设退出码语义**（它只聚合与呈现），
所以"它有没有坏"不能靠退出码看 —— **只能靠内容**。
而它的核心判定只有一句：

    variants = {tuple(sorted(hit)) for hit in 每方向命中的正则集合}
    分歧 ⟺ 命中集合的**种类数 > 1**

⇒ "分歧"在这里的定义是"**各方向报出的答案变体集合不同**"，
**不是**"答案在语义上互相矛盾"。这个区别很容易被读错（人会以为它在判对错），
所以用 fixtures 把它固定下来，包括一个**容易误读的边界情形**：

    armA 只报变体 1；armB 同时报变体 1 与变体 2  ⇒ **算分歧**（一侧多报了一种变体）

## 场景（三正三反，反向对照必须存在）

| 场景 | 构造 | 期望 |
|---|---|---|
| `conflict` | 两方向各报一种不同变体 | 报 `出现分歧` 且计数为 1 |
| `superset` | 一侧报两种（含另一侧那种） | **仍报分歧**（定义如此） |
| `agree` | 两方向都只报同一种 | **不报**分歧，计数 0 |
| `no_hit` | 问题谁都没命中 | 打印"（无命中"，且不计入分歧 |
| `discover` | `--discover` | 按量纲分组，两个取值都在 |
| `missing_runs` | `--runs` 指向不存在的目录 | 退出码 2（不是 traceback） |

用法：`python scripts/test_conflict_scan_fixtures.py`
"""
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import subproc  # noqa: E402
SCRIPT = HERE / "conflict_scan.py"

QUESTIONS = {"噪声下界该报多少": [r"9\s*分", r"14\s*[-~]\s*20\s*分"]}


def build(root: Path, arm_a: str, arm_b: str):
    for arm, text in (("armA", arm_a), ("armB", arm_b)):
        d = root / "runs" / arm / "outputs"
        d.mkdir(parents=True, exist_ok=True)
        (d / "answer.md").write_text(text, encoding="utf-8")
    q = root / "questions.json"
    q.write_text(json.dumps(QUESTIONS, ensure_ascii=False), encoding="utf-8")
    return q


def run(root: Path, q: Path, *extra):
    cmd = [sys.executable, str(SCRIPT), "--runs", str(root / "runs"), "--questions", str(q)]
    cmd += list(extra)
    r = subproc.run_text(cmd)
    return r.returncode, r.stdout


def main():
    base = HERE / "_conflict_fixtures_tmp"
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    print("=" * 78)
    print("conflict_scan fixtures（钉住「什么算分歧」的定义 + 反向对照）")
    print("=" * 78)
    ok = True
    try:
        cases = [
            # 名称,        armA,               armB,                 期望分歧
            ("conflict", "噪声下界取 9 分。", "噪声下界取 14-20 分。", True),
            ("superset", "噪声下界取 9 分。",
             "噪声下界取 9 分；也可能落 14-20 分。", True),
            ("agree", "噪声下界取 9 分。", "结论：噪声下界 9 分。", False),
            ("no_hit", "什么都没提。", "也没有。", None),
        ]
        for name, a, b, want in cases:
            root = base / name
            root.mkdir()
            q = build(root, a, b)
            code, out = run(root, q)
            flagged = "出现分歧" in out
            if want is None:
                good = (not flagged) and ("（无命中" in out) and ("0 个出现" in out)
                shown = f"报分歧={flagged} 报无命中={'（无命中' in out}"
            else:
                # 计数也要断言：第一版只钉了 flag，于是"计数器坏了"抓不到
                # （变异 M24 的第一次尝试就是这么漏的）。
                want_n = "1 个出现" if want else "0 个出现"
                good = (flagged == want) and (want_n in out) and (code == 0)
                shown = f"报分歧={flagged}（期望 {want}）  {want_n}={want_n in out}"
            print(f"{'PASS' if good else 'FAIL'}  {name:10s} 退出码 {code}（期望 0）  {shown}")
            if not good:
                for line in out.splitlines():
                    if "分歧" in line or "命中" in line or "个问题" in line:
                        print(f"        | {line.strip()[:92]}")
            ok &= good

        # 方向名必须被列出来（否则"回原始产出核对"这条设计就落空了）
        root = base / "conflict"
        q = root / "questions.json"
        code, out = run(root, q)
        names = ("armA" in out) and ("armB" in out)
        print(f"{'PASS' if names else 'FAIL'}  arm_names  两个方向名都被列出={names}")
        ok &= names

        # --discover：按量纲分组
        code, out = run(root, q, "--discover")
        disc = (code == 0) and ("[分]" in out) and ("9 分" in out) and ("14-20 分" in out)
        print(f"{'PASS' if disc else 'FAIL'}  discover   退出码 {code}（期望 0）  "
              f"按量纲分组且两个取值都在={disc}")
        ok &= disc

        # 不存在的目录：退出码 2，不是 traceback
        cmd = [sys.executable, str(SCRIPT), "--runs", str(base / "nope"), "--discover"]
        r = subproc.run_text(cmd)
        graceful = (r.returncode == 2) and ("找不到目录" in (r.stdout + r.stderr))
        print(f"{'PASS' if graceful else 'FAIL'}  missing_runs 退出码 {r.returncode}"
              f"（期望 2）  可读消息={graceful}")
        ok &= graceful
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("-" * 78)
    print("conflict_scan fixtures 结果:", "全部通过" if ok else "有 FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
