#!/usr/bin/env python -u
# -*- coding: utf-8 -*-
r"""status.py 的场景 fixtures —— 补齐"只覆盖了守卫"的缺口。

## 为什么单独需要它（不是一个对称性动作）

`status.py` 从 `goal_guard.py` 导入解析器，但它**曾经自己复制过一份**
`BLOCK_THEORY_RE` 与 `BLOCK_GOAL_RE`。守卫侧改过一次正则（`[:：]` → `[:：|\]]`），
副本没同步 —— 而 status.py **照样跑、照样输出**，只是那段信息悄悄变空。

**这类"共享解析器版本分裂"的 bug 是静默的**：没有异常、没有报错，只是某一栏变成空。
所以断言必须直接检查**那一段有没有真的被解析出来**，而不是"脚本没崩"。

## 场景（复用 test_guard_fixtures 的构造器，保持两边语义一致）

| 场景 | 断言 |
|---|---|
| `fresh` 只有 CHARTER | 退出码 0；输出含 `<headline>` 里的文字 |
| `clean` 4 块 + 齐备台账 | 退出码 0；**协议块被识别**（"方法洞见：N 块"）；理论出口被列出 |
| `early` 2 块 + 只有 method 台账 | 退出码 0；**仍识别到 2 块**；警示未入账的目的数 |
| 缺 CHARTER | 不崩溃、明确报"没有读到 <goals>" |
| 膨胀 CHARTER | **退出码 1**（45 行预算真会爆） |

用法：`python scripts/test_status_fixtures.py`（由 --self-test 调用）
"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATUS = HERE / "status.py"
sys.path.insert(0, str(HERE))
import subproc  # noqa: E402  （子进程编码只有这一处定义，见 subproc.py）
import test_guard_fixtures as fx  # noqa: E402


def run_status(root: Path, theory: Path | None = None, charter: Path | None = None):
    cmd = [sys.executable, str(STATUS),
           "--charter", str(charter or (root / "CHARTER.md")),
           "--ledgers", str(root / "ledgers"),
           "--protocols", str(root / "protocols"),
           "--decisions", str(root / "DECISIONS.md")]
    if theory is not None:
        cmd += ["--theory-ledger", str(theory)]
    r = subproc.run_text(cmd)
    return r.returncode, r.stdout


def main():
    base = HERE / "_status_fixtures_tmp"
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)

    print("=" * 74)
    print("status.py 场景 fixtures（6 个场景）")
    print("=" * 74)
    ok = True
    try:
        # --- fresh：只有 CHARTER ---
        root = base / "fresh"
        root.mkdir()
        fx.build(root, "fresh", 0, fx.T0, fx.T0)
        code, out = run_status(root, theory=root / "ledgers" / "theory-x.md")
        hit = "fixtures 场景：fresh" in out
        good = (code == 0 and hit)
        print(f"{'PASS' if good else 'FAIL'}  fresh    退出码 {code}（期望 0）"
              f"  <headline> 被引用={hit}")
        ok &= good

        # --- clean：4 块 + 齐备台账 + 理论闭环 ---
        root = base / "clean"
        root.mkdir()
        fx.build(root, "clean", 4, fx.T0 + 1000, fx.T0, with_q_bridge=True,
                 with_decisions=True)
        theo = root / "ledgers" / "theory-x.md"
        code, out = run_status(root, theory=theo)
        # 严格断言"解析器真的工作"：既要看到分组标题，也要看到**正确的块数**，
        # 还要看到**块→理论的映射**（后者是 BLOCK_THEORY_RE 的唯一用途，
        # 不查它就会漏掉"该正则失效但脚本照跑"的静默回归 —— 变异测试 M4 暴露过）。
        has_blocks = ("方法洞见：4 块" in out) or ("解决实际问题：4 块" in out)
        has_exit = "出口：有" in out
        has_link = "理论链接：" in out and "→T-1" in out
        good = (code == 0 and has_blocks and has_exit and has_link)
        print(f"{'PASS' if good else 'FAIL'}  clean    退出码 {code}（期望 0）"
              f"  4 块={has_blocks}  理论出口={has_exit}  块→理论映射={has_link}")
        if not good:
            for line in out.splitlines():
                if "■" in line or "块" in line or "出口" in line:
                    print(f"        | {line.strip()[:92]}")
        ok &= good

        # --- early：2 块，只有 method 台账 ---
        root = base / "early"
        root.mkdir()
        fx.build(root, "early", 2, fx.T0, fx.T0 + 1000)
        code, out = run_status(root, theory=root / "ledgers" / "theory-x.md")
        has_blocks = "解决实际问题：" in out or "方法洞见：" in out
        good = (code == 0 and has_blocks)
        print(f"{'PASS' if good else 'FAIL'}  early    退出码 {code}（期望 0）"
              f"  仍识别到 2 块={has_blocks}")
        ok &= good

        # --- 缺 CHARTER：必须不崩且说清楚 ---
        root = base / "nocharter"
        root.mkdir()
        fx.build(root, "nocharter", 0, fx.T0, fx.T0)
        missing = root / "NOPE.md"
        code, out = run_status(root, theory=root / "ledgers" / "theory-x.md",
                              charter=missing)
        hit = "没有读到" in out
        good = (code == 0 and hit)
        print(f"{'PASS' if good else 'FAIL'}  缺CHARTER 退出码 {code}（期望 0）"
              f"  明确报错={hit}")
        ok &= good

        # --- 膨胀 CHARTER：预算必须爆 ---
        root = base / "fat"
        root.mkdir()
        fx.build(root, "fat", 0, fx.T0, fx.T0)
        ct = (root / "CHARTER.md").read_text(encoding="utf-8")
        ct += "\n".join(f"- 未知项 {i}（填充以推过预算）" for i in range(60))
        (root / "CHARTER.md").write_text(ct, encoding="utf-8")
        code, out = run_status(root, theory=root / "ledgers" / "theory-x.md")
        good = (code == 1)
        print(f"{'PASS' if good else 'FAIL'}  膨胀CHARTER 退出码 {code}（期望 1，预算会爆）")
        ok &= good

        # --- suspended：理论条目处于「挂起（到期 P-003）」 ---
        # 立此场景的失效：`可用性` 是新人脸信息（"这条现在不能用，什么时候必须处置"），
        # 它靠 status.py 从 goal_guard **import** 的 AVAILABILITY_RE / DUE_BLOCK_RE 解析。
        # 一旦这两条正则的 import 断掉或改名，status 会**照样跑、照样输出**，
        # 只是那个标记**悄悄消失** —— 与 M3/M4 的"解析器版本分裂"是同一个形态。
        root = base / "suspended"
        root.mkdir()
        fx.build(root, "clean", 4, fx.T0 + 1000, fx.T0, with_q_bridge=True,
                 with_decisions=True)
        tp = root / "ledgers" / "theory-x.md"
        tp.write_text(tp.read_text(encoding="utf-8")
                      .replace("可用性: 可用", "可用性: 挂起（到期 P-003）"),
                      encoding="utf-8")
        code, out = run_status(root, theory=tp)
        hit = "[挂起→P-003]" in out
        good = (code == 0 and hit)
        print(f"{'PASS' if good else 'FAIL'}  suspended 退出码 {code}（期望 0）"
              f"  挂起+到期被印出={hit}")
        if not good:
            for line in out.splitlines():
                if "T-1" in line or "挂起" in line:
                    print(f"        | {line.strip()[:92]}")
        ok &= good

        # --- demoted：理论条目处于「已降级（→ M-3）」 ---
        # 与 suspended 成对：两者都是"不能用的状态"，但一个要到期日、一个要去向。
        # 而且它检验**汇总不把已降级条目算进活条目**（第 20 轮实测到
        # "共 1 条、已有出口 2 条"这种自相矛盾，就是这么来的）。
        root = base / "demoted"
        root.mkdir()
        fx.build(root, "clean", 4, fx.T0 + 1000, fx.T0, with_q_bridge=True,
                 with_decisions=True)
        tp = root / "ledgers" / "theory-x.md"
        tp.write_text(tp.read_text(encoding="utf-8")
                      .replace("可用性: 可用", "可用性: 已降级（→ M-3）"),
                      encoding="utf-8")
        code, out = run_status(root, theory=tp)
        hit = ("[已降级→M-3]" in out) and ("活条目中" in out)
        good = (code == 0 and hit)
        print(f"{'PASS' if good else 'FAIL'}  demoted   退出码 {code}（期望 0）"
              f"  降级+去向被印出={hit}")
        if not good:
            for line in out.splitlines():
                if "T-1" in line or "活条目" in line:
                    print(f"        | {line.strip()[:92]}")
        ok &= good

        print("-" * 74)
        print("status fixtures 结果:", "全部通过" if ok else "有 FAIL")
    finally:
        shutil.rmtree(base, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
