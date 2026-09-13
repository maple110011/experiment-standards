#!/usr/bin/env python -u
# -*- coding: utf-8 -*-
r"""决策日志 fixtures —— **"等你"的行必须写成一张能决策的卡**。

治的是用户最初的诉求里最后一个没有机械约束的口子：
> "我看不懂 agent 要求我抉择的选项。"

第 31 轮实测：那条唯一的待决定只有「决定 + 理由 + 状态」；
人想知道的**三件事一件都没写**（我会拿到什么 / 我要花什么 / 什么必须先成立），
而理由栏写的是"信息量大" —— 那是 agent 的判断，不是给人算账的信息。

## 就个并排场景

| 场景 | 造的是什么 | 期望 |
|---|---|---|
| `good` | 待决定行三件套齐备、且「拿到什么」含数字 | **PASS** |
| `no_what` | 缺「你会拿到什么」 | 报 `你会拿到什么` |
| `no_cost` | 缺「你要花什么」 | 报 `你要花什么` |
| `no_pre` | 缺「前置条件」 | 报 `前置条件` |
| `vague` | 三件套都在，但「拿到什么」只是形容词、没有数字 | 报 `可核对的读数` |
| `settled` | **没有**「等你」的行（全是已生效的） | **PASS**（不该逼人给已完成的事补三件套） |
| `no_col` | 表头就没有这三列（老格式） | 报 `表头缺列` |

⚠️ `vague` 与 `settled` 这两条是**反向**的：它们保证"检查不是一律报 FAIL"，
也保证"三件套"约束没有扩散到不需要它的行上（`B28` 第 ② 项）。

跑法：`python scripts/test_decisions_fixtures.py`（由 `--self-test` 调用）
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import subproc  # noqa: E402
CHECKER = HERE / "check_collab_artifacts.py"

HEAD_COLS = "| 日期 | 块号 | 决定 | 谁定的 | 理由 | 你会拿到什么 | 你要花什么 | 前置条件 | 状态 |"
SEP = "|---|---|---|---|---|---|---|---|---|"


def _row(what="—", cost="—", pre="—", status="生效"):
    return (f"| 本会话 | P-1 | 做一件事 | agent | 因为 | {what} | {cost} | {pre} | {status} |")


def build(path: Path, body: str, with_cols: bool = True):
    head = HEAD_COLS if with_cols else "| 日期 | 块号 | 决定 | 谁定的 | 理由 | 状态 |"
    sep = SEP if with_cols else "|---|---|---|---|---|---|"
    path.write_text(f"# DECISIONS\n\n{head}\n{sep}\n{body}\n", encoding="utf-8")


GOOD = _row("B 榜一个分数；差 > 0.05 分就能知道哪份排序更好",
            "提交额度 ×1 + 你约 5 分钟", "你还剩 ≥1 次额度", "**待执行（等你）**")
VAGUE = _row("可能有用", "一些额度", "条件合适时", "**待执行（等你）**")

SCENARIOS = [
    ("good", GOOD, True, 0, None),
    ("no_what", _row("—", "额度 ×1", "还剩 ≥1 次", "**待执行（等你）**"), True, 1,
     "你会拿到什么"),
    ("no_cost", _row("分数差 0.05", "—", "还剩 ≥1 次", "**待执行（等你）**"), True, 1,
     "你要花什么"),
    ("no_pre", _row("分数差 0.05", "额度 ×1", "—", "**待执行（等你）**"), True, 1,
     "前置条件"),
    ("vague", VAGUE, True, 1, "可核对的读数"),
    # 反向 1：没有「等你」的行 ⇒ 已完成的事不该被逼着补三件套
    ("settled", _row("—", "—", "—", "生效"), True, 0, None),
    # 反向 1b：**agent 自己的待办**（状态含「待」但**不含「等你」**）⇒ 同样不该被逼补三件套。
    #   这一条是把"等你"与"待"分开的**唯一**依据，也是 M35 变异的靶子：
    #   真实工作区里那条「此前门控增量仅 1.1% 的表述需加注（待回改）」正是这个形态 ——
    #   它是我的活，不是用户的决定。放宽成"含待就算"会让它被要求写"你会拿到什么"。
    ("agent_todo", _row("—", "—", "—", "待回改"), True, 0, None),
    # 反向 2：老格式（没有这三列）⇒ 必须报"表头缺列"，而不是静默通过
    ("no_col", _row(status="**待执行（等你）**"), False, 1, "表头缺列"),
    # 前置条件写「无」是合法的（不是"没写"）
    ("pre_none", _row("分数差 0.05", "额度 ×1", "无", "**待执行（等你）**"), True, 0, None),
]

# 场景 10（**模板场景**）：把**出厂模板本身**当输入喂给校验器。
#
# 立此的原因（第 31 轮实测）：给"决策三件套"加了强制列之后，出厂的
# `assets/templates/DECISIONS.template.md` **还是旧列**（`你选了 | 你的理由 | 破例？`）——
# 也就是**照着模板新建的工作区会被自己的校验器拒收**。
# ⇒ 模板必须与活文件同属被测面：模板漂移与代码漂移一样，会让机制从第一步就失效。
#    （同类前例：`LEDGER-` 前缀漂移、`<headline>` 过时 —— 都是"文件之间不同步"。）
TEMPLATE = HERE.parent / "assets" / "templates" / "DECISIONS.template.md"


def main() -> int:
    base = HERE / "_decisions_fixtures_tmp"
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    print("=" * 78)
    print("决策日志 fixtures（10 个场景：三件套 + 反向 + 合法「无」 + 出厂模板）")
    print("=" * 78)
    ok = True
    try:
        for name, body, cols, exp_code, must in SCENARIOS:
            p = base / f"{name}.md"
            build(p, body, with_cols=cols)
            r = subproc.run_text([sys.executable, str(CHECKER), "--decisions", str(p)])
            code = r.returncode
            hit = (must is None) or any(must in ln for ln in r.stdout.splitlines()
                                        if ln.strip().startswith(("x", "FAIL", "·", "-")))
            good = (code == exp_code) and hit
            print(f"{'PASS' if good else 'FAIL'}  {name:9s} 退出码 {code}"
                  f"（期望 {exp_code}）"
                  + (f"  命中 {must!r}={hit}" if must else ""))
            if not good:
                ok = False
                for ln in r.stdout.splitlines():
                    if "FAIL" in ln or ln.strip().startswith("x"):
                        print(f"        | {ln.strip()[:100]}")
        # 出厂模板：`<...>` 占位符换成合法值后，必须**直接通过**
        if not TEMPLATE.exists():
            print(f"FAIL  出厂模板不存在：{TEMPLATE}")
            ok = False
        else:
            p = base / "template.md"
            t = TEMPLATE.read_text(encoding="utf-8")
            for a, b in (("<课题名>", "fixtures"), ("<YYYY-MM-DD>", "2025-01-01"),
                         ("<P-XXX-001>", "P-TEST-001"), ("<做了什么决定>", "做一个决定"),
                         ("<用户 / agent（依据…）>", "用户"), ("<为什么>", "因为")):
                t = t.replace(a, b)
            p.write_text(t, encoding="utf-8")
            r = subproc.run_text([sys.executable, str(CHECKER), "--decisions", str(p)])
            good = (r.returncode == 0)
            print(f"{'PASS' if good else 'FAIL'}  template  退出码 {r.returncode}（期望 0）"
                  "  ← 出厂模板必须能直接通过自己的校验器")
            if not good:
                ok = False
                for ln in r.stdout.splitlines():
                    if "FAIL" in ln or ln.strip().startswith("x"):
                        print(f"        | {ln.strip()[:100]}")
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("-" * 78)
    print("decisions fixtures 结果:", "全部通过" if ok else "有 FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
