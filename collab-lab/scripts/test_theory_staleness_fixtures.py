#!/usr/bin/env python -u
# -*- coding: utf-8 -*-
r"""守卫的"证伪条件待核对"场景（两个并排场景，只需 mtime 不同）。

## 为什么单独一个文件

这条检查（判据 4）是**代理信号**，它的全部逻辑就在一句比较里：
「该条目的实验出口已运行，而理论台账在此之后未被修订」。
**正因为逻辑极简，它最容易在后续改动中被静默破坏**（比如有人把比较方向写反）。

所以做两个**除 mtime 外完全相同**的场景：
  `young` —— 台账比出口**新** ⇒ **不应**报"待核对证伪"（要求未修订才是信号）
  `stale` —— 台账比出口**旧** ⇒ **应**报

两场景并排，任何"把比较写反/写坏"的改动都会让其中一个失败 ——
这是**单个场景做不到的**（单场景下把比较恒真或恒假都能"通过"）。

用法：`python scripts/test_theory_staleness_fixtures.py`
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import subproc  # noqa: E402  （子进程编码只有这一处定义，见 subproc.py）
GUARD = HERE / "goal_guard.py"
T0 = 1_700_000_000

CHARTER = """# CHARTER — 证伪核对场景

<headline>证伪核对场景</headline>

<goals>
- `basis`: 解决实际问题
- `method`: 方法洞见
- `bridge`: 从实践长出理论课题
</goals>
"""

LEDGER_M = """# methods

## M-1 [method] 探针条目

等级: 薄

主张: 探针

适用边界: 探针

复现: 1 次

被用于: 无

推翻条件: 探针
"""

# 理论条目：成熟度=具体方向，且**有**被用于（出口）
LEDGER_T = """# theory

## T-1 [bridge] 探针条目

现象: 探针现象

证据: 等级: 薄

缺口: 探针缺口

理论问题: 为什么 X 在 Y 下失效？

成熟度: 具体方向

方向A: 探针方向 A

方向B: 探针方向 B

区分实验: 探针区分实验

被用于: `P-PROBE-002`

什么能证伪: 探针证伪条件（这是本检查要提示回头核对的那一栏）
"""

BLOCK = """# PROTOCOL-P-PROBE-{n:03d}

## 一句话主张
探针块 {n}

## 本块推进哪个目的
- 目的：`{goal}`

## 本块服务于哪条理论条目

| 项 | 内容 |
|---|---|
| 理论条目 | `{theory}` |
| 检验哪条方向 | 探针 |
| 若结果如此则降级 | 探针 |
"""


def build(root: Path, theory_mtime: float, block_mtime: float):
    (root / "ledgers").mkdir(parents=True, exist_ok=True)
    (root / "protocols").mkdir(parents=True, exist_ok=True)
    (root / "CHARTER.md").write_text(CHARTER, encoding="utf-8")
    (root / "DECISIONS.md").write_text("# DECISIONS\n", encoding="utf-8")
    m = root / "ledgers" / "methods-probe.md"
    m.write_text(LEDGER_M, encoding="utf-8")
    os.utime(m, (block_mtime, block_mtime))
    t = root / "ledgers" / "theory-probe.md"
    t.write_text(LEDGER_T, encoding="utf-8")
    os.utime(t, (theory_mtime, theory_mtime))
    # 两块：第一块 basis，第二块 method 且服务 T-1（与被用于一致）
    for i, (goal, th) in enumerate((("basis", "无"), ("method", "T-1")), start=1):
        p = root / "protocols" / f"PROTOCOL-P-PROBE-{i:03d}.md"
        p.write_text(BLOCK.replace("{n:03d}", f"{i:03d}").replace("{n}", str(i))
                     .replace("{goal}", goal).replace("{theory}", th), encoding="utf-8")
        os.utime(p, (block_mtime, block_mtime))


def run_guard(root: Path):
    cmd = [sys.executable, str(GUARD),
           "--charter", str(root / "CHARTER.md"),
           "--ledgers", str(root / "ledgers"),
           "--protocols", str(root / "protocols"),
           "--decisions", str(root / "DECISIONS.md"),
           "--theory-ledger", str(root / "ledgers" / "theory-probe.md")]
    r = subproc.run_text(cmd)
    return r.returncode, r.stdout


SCENARIOS = [
    # 名称,    台账 mtime,  块 mtime,     是否应报"待核对证伪"
    ("young", T0 + 1000, T0, False),
    ("stale", T0, T0 + 1000, True),
]


def main():
    base = HERE / "_staleness_fixtures_tmp"
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    print("=" * 74)
    print("守卫「证伪条件待核对」场景（并排两场景，只差 mtime）")
    print("=" * 74)
    ok = True
    try:
        for name, tm, bm, should_report in SCENARIOS:
            root = base / name
            root.mkdir()
            build(root, tm, bm)
            code, out = run_guard(root)
            reported = "待核对证伪" in out
            good = (reported == should_report)
            print(f"{'PASS' if good else 'FAIL'}  {name:6s} 报出待核对={reported}"
                  f"（期望 {should_report}）  退出码 {code}")
            if not good:
                ok = False
                for line in out.splitlines():
                    if "证伪" in line or "理论闭环" in line:
                        print(f"        | {line.strip()[:96]}")
            ok &= good
        print("-" * 74)
        print("staleness fixtures 结果:", "全部通过" if ok else "有 FAIL")
    finally:
        shutil.rmtree(base, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
