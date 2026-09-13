#!/usr/bin/env python -u
# -*- coding: utf-8 -*-
r"""「第 3 档决定的分流」校验的场景 fixtures。

## 为什么需要它

`check_protocol` 里的第 3 档分流检查有三条**独立的**失败路径：
  a. 有第 3 档行，但缺少分流节
  b. 有分流节，但没有任何行标出「可扫 / 不可扫」
  c. 某行标为「可扫」，却没写扫描范围（不含数字）

**一个"合法 / 非法"两场景对只能证明"检查会响"**，不能定位是哪条路径失效了。
所以这里做 **4 个场景**：三个各隔离一条失败路径，加一个"无第 3 档 ⇒ 不应误报"的对照。

判据的前提：**协议块必须先是合法的**（字段齐全、判据含数字），否则失败会被字段检查
掩盖、定位不到分流逻辑。故本 fixtures 从一个最小合法块出发，只改变分流那一处。

用法：`python scripts/test_triage_fixtures.py`
"""
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import subproc  # noqa: E402  （子进程编码只有这一处定义，见 subproc.py）
CHECKER = HERE / "check_collab_artifacts.py"

# 最小合法协议块：字段齐全、判据含数字、无占位符。
# TRIAGE_ROW 为第 3 档决定行；BLOCK_TABLE 为分流表（可为空）。
BASE = """# PROTOCOL-P-TRI-001

{prelude}
## 块号
`P-TRI-001`

## 一句话主张
测试主张：本块检验一个可被推翻的命题。

## 为什么是这一步
它改变"该不该做 X"这个决策。

## 本块推进哪个目的
- 目的：`method`

## 本块服务于哪条理论条目

| 项 | 内容 |
|---|---|
| 理论条目 | `无` |
| 检验哪条方向 | — |

## 既有证据
- `Q-1`（稳定）：测试

## 建模决定与依据

| 决定 | 取值 | 档位 | 依据 / 范围戳 | 若走第2档：可证伪的预测 |
|---|---|---|---|---|
| 阈值取法 | 0.5 | {tier} | 测试依据 | 测试预测 |

{triage}
## 主指标
`AUC = P(正例得分 > 负例得分)`，决策区 = 得分前 40%。

## 最小可检测效应
噪声下界 0.05；一个事件分辨率 0.1。

## 对照
实验组与对照组只差"是否融合"一处。

## 成功判据
增量 > 0.02。

## 失败判据
增量 ≤ 0.01。

## 绝不能声称
不能声称该结论与决策区定义无关。

## 停止规则
λ 网格不收敛时停止。

## 预期成本
零训练；复用已落盘预测。
"""

TRIAGE_HEAD = "### 第 3 档决定的分流\n\n| 第 3 档决定 | 小类 | 若可扫：扫描范围 / 若不可扫：汇报日期 |\n|---|---|---|\n"
TRIAGE_GOOD = TRIAGE_HEAD + "| 阈值取法 | 可扫 | pct ∈ {20,30,40,50}% |\n\n"
TRIAGE_NO_KIND = TRIAGE_HEAD + "| 阈值取法 | 待定 | 待定 |\n\n"
TRIAGE_NO_RANGE = TRIAGE_HEAD + "| 阈值取法 | 可扫 | 扫一遍看看 |\n\n"

# ---- 多档判据：两场景（有优先级 / 没优先级）----
# 立这两场景的失效（第 22 轮 `P-BOILER-012` 实测）：三档判据互不互斥也不穷尽，
# 实测结果落在缝里 ⇒ "哪一档成立"由解释者决定。修法是**强制写一行** `判据优先级:`。
# ⚠️ 必须是**字段形式**（`判据优先级:` 开头）而不是标题形式 ——
#    检查要的是一行可机械定位的字段，与 `成熟度:` / `可用性:` 同一约定。
#    （第一版写成 `## 判据优先级` 标题，于是"有优先级"的场景被误判为没有。）
MULTI_TIER_OK = """判据优先级: O1 > O2 > O3；O1 与 O2 互斥（以 between 是否回到 ≥0.50 分界），O3 覆盖「区间跨线」的情形。

## 成功判据
O1 或 O2（见上）。
"""
MULTI_TIER_BAD = """## 成功判据
若 O1 则降级；若 O2 则保留；否则 O3。
"""

PRELUDE_OK = "预注册: 事前\n稀缺资源: 无\n杠杆上界: 不适用（测试）\n"

SCENARIOS = [
    # 名称,        档位列,  分流节,          期望通过
    ("control_ok",   "3",   TRIAGE_GOOD,     True),    # 合法：有第3档 + 完整分流
    ("no_tier3",     "1",   "",              True),    # 对照：无第3档 ⇒ 不该要求分流
    ("missing_triage", "3", "",              False),   # 失败路径 a
    ("no_kind",      "3",   TRIAGE_NO_KIND,  False),   # 失败路径 b
    ("no_range",     "3",   TRIAGE_NO_RANGE, False),   # 失败路径 c
    ("multi_tier_ok",  "1", MULTI_TIER_OK,   True),    # 有优先级行 ⇒ 不该报
    ("multi_tier_bad", "1", MULTI_TIER_BAD,  False),   # 三档但无优先级行 ⇒ 必须报
]

# ---- 预注册 / 稀缺资源 / 杠杆上界：四场景（三条失败路径 + 一对照）----
PRELUDE_CASES = [
    # 名称,              prelude,                                       extra,  期望通过
    ("pre_ok",           PRELUDE_OK,                                     "",     True),
    ("pre_missing",      "稀缺资源: 无\n杠杆上界: 不适用（测试）\n",    "",     False),
    ("res_missing",      "预注册: 事前\n杠杆上界: 不适用（测试）\n",    "",     False),
    ("res_no_lever",     "预注册: 事前\n稀缺资源: 提交额度 ×1\n",       "",     False),
    ("res_with_lever",   "预注册: 事前\n稀缺资源: 提交额度 ×1\n杠杆上界: 3 分\n", "", True),
]


def build(root: Path, name: str, tier: str, triage: str, prelude: str = PRELUDE_OK,
          extra: str = "") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    p = root / "PROTOCOL-P-TRI-001.md"
    body = (BASE.replace("{tier}", tier).replace("{triage}", triage)
            .replace("{prelude}", prelude + extra))
    p.write_text(body, encoding="utf-8")
    return p


def run_checker(path: Path):
    r = subproc.run_text([sys.executable, str(CHECKER), "--protocol", str(path)])
    return r.returncode, r.stdout


def main():
    base = HERE / "_triage_fixtures_tmp"
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    print("=" * 76)
    print("「第 3 档分流」+「多档判据优先级」+「预注册/稀缺资源/杠杆上界」fixtures")
    print("=" * 76)
    ok = True
    try:
        for name, tier, triage, should_pass in SCENARIOS:
            root = base / name
            p = build(root, name, tier, triage)
            code, out = run_checker(p)
            passed = (code == 0)
            good = (passed == should_pass)
            # 取出与本检查相关的报错行，便于定位
            triage_msgs = [l.strip()[2:].strip() for l in out.splitlines()
                           if l.strip().startswith(("x ", "✓ "))
                           and ("第3档分流" in l or "多档判据" in l)]
            print(f"{'PASS' if good else 'FAIL'}  {name:16s} 通过={passed}"
                  f"（期望 {should_pass}）"
                  + (f"  报错={triage_msgs[0][:52]}" if triage_msgs else ""))
            if not good:
                ok = False
                for l in out.splitlines():
                    if l.strip().startswith(("x ", "✓ ")):
                        print(f"        | {l.strip()[:96]}")
            ok &= good
        # ---- 预注册 / 稀缺资源 / 杠杆上界 ----
        print()
        print("  「预注册 / 稀缺资源 / 杠杆上界」四条路径：")
        for name, prelude, extra, should_pass in PRELUDE_CASES:
            root = base / f"pre_{name}"
            p = build(root, name, "1", "", prelude=prelude, extra=extra)
            code, out = run_checker(p)
            passed = (code == 0)
            good = (passed == should_pass)
            msgs = [l.strip()[2:].strip() for l in out.splitlines()
                    if l.strip().startswith(("x ", "✓ "))]
            print(f"{'PASS' if good else 'FAIL'}  {name:16s} 通过={passed}"
                  f"（期望 {should_pass}）"
                  + (f"  报错={msgs[0][:46]}" if msgs else ""))
            if not good:
                for l in out.splitlines():
                    if l.strip().startswith(("x ", "✓ ")):
                        print(f"        | {l.strip()[:92]}")
            ok &= good

        print("-" * 76)
        print("triage fixtures 结果:", "全部通过" if ok else "有 FAIL")
    finally:
        shutil.rmtree(base, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
