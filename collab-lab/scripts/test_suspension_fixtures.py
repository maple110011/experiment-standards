#!/usr/bin/env python -u
# -*- coding: utf-8 -*-
r"""守卫的「挂起到期」场景（五个并排场景，只差"可用性"字段与块数）。

## 为什么单独一个文件

这是「降级判据」第 4 条（退化的问题转换）的机械形式，见
`references/theory-ladder.md`。它要拦的形态**在本仓库真实发生过**：

> 一条 T- 的证伪条件被触发两次，每次都是"把表述改弱到反例不再适用"；
> 第三次改写产生的新预测被自己否掉后，处置是给它挂一句
> "**不要把'保留 ≥2 层'当作可用判据**" —— 然后留在台账里。
> 旧的三条降级判据（入场判据）**一条都不命中它**。

## 五个场景，四条路径各自隔离

| 场景 | `可用性` | 协议块 | 期望 |
|---|---|---|---|
| `usable` | `可用` | P-001..002 | **不报**（无假阳性控制） |
| `no-deadline` | `挂起（起始 P-001）` | P-001..002 | 报 **`挂起无到期`** |
| `in-time` | `挂起（起始 P-001；到期 P-003）` | P-001..002 | **不报**（未到期） |
| `expired-at-due` | `挂起（起始 P-001；到期 P-002）` | P-001..002 | 报 **`挂起逾期`** |
| `expired-by-new-block` | `挂起（起始 P-001；到期 P-002）` | P-001..003 | 报 **`挂起逾期`** |

`in-time` 与 `expired-at-due` 的**块完全相同，只差到期号** ——
任何"把 `>=` 写成 `>`/`<`"的改动都会让其中一个失败（`>` 会让 `expired-at-due` 漏报）。
`expired-by-new-block` 再证明**驱动逾期的是块号而不是 mtime 或墙钟**。
只报"挂起"两字不够：两个失败路径的**提示语必须不同**，否则修起来会找错地方。

**`到期 P-n` 的语义**：处置必须在 **P-n 这一块内**完成。
守卫是每轮结束跑的，所以 `>= n` 就在"跑完 P-n 的那一次守卫"上报 ——
若写成 `> n`，到期日会被静默顺延一整个块，而"到期日可以静默顺延"正是要治的病。

用法：`python scripts/test_suspension_fixtures.py`
"""
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import subproc  # noqa: E402  （子进程编码只有这一处定义，见 subproc.py）
GUARD = HERE / "goal_guard.py"

CHARTER = """# CHARTER — 挂起到期场景

<headline>挂起到期场景</headline>

<goals>
- `basis`: 解决实际问题
- `method`: 方法洞见
- `bridge`: 从实践长出理论课题
</goals>
"""

LEDGER_Q = """# problem

## Q-1 [basis] 探针事实

证据: 等级 稳定

事实: 探针

影响: 探针

被用于: 无

什么能改: 探针
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

# 理论条目：成熟度取「可研究的问题」——让守卫的判据 1/2（只对「具体方向」生效）
# 不参与，从而**这一屏里唯一可能出现的理论类输出就是挂起检查**。
LEDGER_T = """# theory

## T-1 [bridge] 探针条目

现象: 探针现象

证据: 等级: 薄

缺口: 探针缺口

张力: 探针张力含数字 0.40

理论问题: 为什么 X 在 Y 下失效？

成熟度: 可研究的问题

可用性: {avail}

方向A: 探针方向 A

方向B: 探针方向 B

被用于: 无

什么能证伪: 探针证伪条件
"""

BLOCK = """# PROTOCOL-P-PROBE-{n:03d}

## 一句话主张
探针块 {n}

## 本块推进哪个目的
- 目的：`{goal}`

## 本块服务于哪条理论条目

| 项 | 内容 |
|---|---|
| 理论条目 | {theory} |
| 检验哪条方向 | 无 |
| 若结果如此则降级 | 无 |
"""


def build(root: Path, avail: str, n_blocks: int, theory_ref: str = "无",
          last_theory_ref: str | None = None):
    """`theory_ref` = 每块声明的理论条目；`last_theory_ref` 只改最后一块
    （用来造"悬空引用"：块声明了一个台账里不存在的 T-x）。"""
    (root / "ledgers").mkdir(parents=True, exist_ok=True)
    (root / "protocols").mkdir(parents=True, exist_ok=True)
    (root / "CHARTER.md").write_text(CHARTER, encoding="utf-8")
    (root / "DECISIONS.md").write_text("# DECISIONS\n", encoding="utf-8")
    (root / "ledgers" / "problem-probe.md").write_text(LEDGER_Q, encoding="utf-8")
    (root / "ledgers" / "methods-probe.md").write_text(LEDGER_M, encoding="utf-8")
    (root / "ledgers" / "theory-probe.md").write_text(
        LEDGER_T.replace("{avail}", avail), encoding="utf-8")
    for i in range(1, n_blocks + 1):
        ref = theory_ref
        if last_theory_ref is not None and i == n_blocks:
            ref = last_theory_ref
        p = root / "protocols" / f"PROTOCOL-P-PROBE-{i:03d}.md"
        p.write_text(BLOCK.replace("{n:03d}", f"{i:03d}").replace("{n}", str(i))
                     .replace("{goal}", "basis" if i == 1 else "method")
                     .replace("{theory}", ref),
                     encoding="utf-8")


def run_guard(root: Path):
    cmd = [sys.executable, str(GUARD),
           "--charter", str(root / "CHARTER.md"),
           "--ledgers", str(root / "ledgers"),
           "--protocols", str(root / "protocols"),
           "--decisions", str(root / "DECISIONS.md"),
           "--theory-ledger", str(root / "ledgers" / "theory-probe.md")]
    r = subproc.run_text(cmd)
    return r.returncode, r.stdout


def read_console_text(data: bytes) -> str:
    """把子进程的**原始字节**按"人会在控制台上看到的样子"解出来。

    这里不能假定编码：父进程若是被 `subproc.run_text` 启起来的，`PYTHONIOENCODING`
    已在环境里（子进程写 UTF-8）；而**真实的命令行调用没有这个变量**，子进程会写
    控制台编码（本机 cp936）。两种都试，只要有一种能读出中文就算"人读得到"。
    """
    for enc in ("cp936", "utf-8"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def run_guard_bare_console(root: Path):
    """**故意不给**任何编码环境变量地跑守卫 —— 复现用户在 PowerShell 里的真实调用。

    这条路径与 `run_guard` 的差别只有一个：环境里没有 `PYTHONIOENCODING`。
    立它的失效（实测）：守卫的 FAIL 提示里有一个 `⇒`（U+21D2），cp936 里没有这个
    字符 ⇒ 它在"报告失败"的那一行抛 `UnicodeEncodeError` **崩掉**（exit 1 + traceback，
    而不是 exit 2 + FAIL）。而经过 `run_guard`（注入了 UTF-8）是**测不出这个**的
    —— 这条 fixture 的存在就是为了让那个差别不被漏掉。
    """
    raw_env = {k: v for k, v in os.environ.items()
               if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}
    cmd = [sys.executable, str(GUARD),
           "--charter", str(root / "CHARTER.md"),
           "--ledgers", str(root / "ledgers"),
           "--protocols", str(root / "protocols"),
           "--decisions", str(root / "DECISIONS.md"),
           "--theory-ledger", str(root / "ledgers" / "theory-probe.md")]
    import subprocess as _sp
    r = _sp.run(cmd, capture_output=True, env=raw_env)
    return r.returncode, read_console_text(r.stdout), read_console_text(r.stderr)


# (名称, 可用性字段值, 块数, 期望的提示语子串; None = 不应报任何挂起/降级问题)
#
# `in-time` 与 `expired-at-due` 的**块完全相同（都是 P-001..002），只差到期号**
# —— 这一对专门钉住 `>=` 与 `>` 的区别：把判定写成 `>`，`expired-at-due` 会漏报。
# （第一版确实写成了 `>`，而且当时的 fixtures 抓不到它，因为两个场景的块数也不同。
#   这是"并排场景必须只差被测的那一个变量"的又一次实测。）
#
# `demoted-*` 是第 20 轮加的第三种状态（`已降级`）：**降级不是删除**，
# 条目要留在原位置、而且必须写出去向；`dangling` 检查反方向的引用（块→T）。
SCENARIOS = [
    ("usable", "可用", 2, None),
    ("no-deadline", "挂起（起始 P-001）", 2, "挂起无到期"),
    ("in-time", "挂起（起始 P-001；到期 P-003）", 2, None),
    ("expired-at-due", "挂起（起始 P-001；到期 P-002）", 2, "挂起逾期"),
    ("expired-by-new-block", "挂起（起始 P-001；到期 P-002）", 3, "挂起逾期"),
    # 长块名（`P-PROBE-003`）必须与短名（`P-003`）**同等识别**。
    # 立此的实测原因（第 30 轮）：真实工作区的块名是 `P-BOILER-019`，
    # 而 DUE_BLOCK_RE 当时写成 `P-?\s*(\d{1,4})` ⇒ `挂起（到期 P-BOILER-021）` 被
    # 判成"没有到期日的挂起"。**误报最坏的地方是逼人把合规写法改坏** ——
    # 最省事的"修法"是把它改成 `P-021`，那样到期日就指向一个不存在的块。
    ("in-time-longname", "挂起（起始 P-PROBE-001；到期 P-PROBE-003）", 2, None),
    ("expired-longname", "挂起（起始 P-PROBE-001；到期 P-PROBE-002）", 2, "挂起逾期"),
    ("demoted-ok", "已降级（→ M-1）", 2, None),
    ("demoted-no-target", "已降级", 2, "降级无去向"),
]


def main():
    base = HERE / "_suspension_fixtures_tmp"
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    print("=" * 74)
    print("守卫「挂起到期」场景（判据 4 的机械形式：挂起必须有到期日，到期必须处置）")
    print("=" * 74)
    ok = True
    try:
        for name, avail, n_blocks, expect in SCENARIOS:
            root = base / name
            root.mkdir()
            build(root, avail, n_blocks)
            code, out = run_guard(root)
            marks = ("挂起无到期", "挂起逾期", "降级无去向")
            if expect is None:
                good = not any(m in out for m in marks)
                shown = "无挂起/降级告警"
            else:
                good = expect in out
                shown = "报出 " + ("、".join(m for m in marks if m in out) or "（无）")
            print(f"{'PASS' if good else 'FAIL'}  {name:22s} {shown}"
                  f"（期望 {'无告警' if expect is None else expect}）  退出码 {code}")
            if not good:
                ok = False
                for line in out.splitlines():
                    if any(m[:2] in line for m in marks):
                        print(f"        | {line.strip()[:96]}")
            ok &= good

        # 悬空引用：块声明了台账里**不存在**的 T-9。
        # 立此场景的失效：判据 3 只管 T→块，**块→T 这一向此前无人看** ——
        # 第 20 轮降级 T-1 时若直接删标题，`P-007`/`009`/`011` 就成了悬空引用而没人报。
        root = base / "dangling-ref"
        root.mkdir()
        build(root, "可用", 2, last_theory_ref="`T-9`")
        code, out = run_guard(root)
        hit = "悬空理论引用" in out
        print(f"{'PASS' if hit else 'FAIL'}  {'dangling-ref':22s} "
              f"{'报出悬空引用' if hit else '**漏报**（块声明了不存在的 T-9）'}  退出码 {code}")
        if not hit:
            ok = False
        ok &= hit

        # 额外一条：**不给编码环境**时的真实控制台路径（上面那条测不到它）。
        root = base / "bare-console"
        root.mkdir()
        build(root, "挂起（起始 P-001；到期 P-002）", 2)
        code, out, err = run_guard_bare_console(root)
        speakable = ("挂起逾期" in out) and code == 2
        print(f"{'PASS' if speakable else 'FAIL'}  {'bare-console':22s} "
              f"退出码 {code}（期望 2）；"
              f"{'报出了 FAIL' if '挂起逾期' in out else '没报出 FAIL'}"
              f"{'' if not err.strip() else '；stderr 有 traceback'}")
        if not speakable:
            ok = False
            for line in err.splitlines()[-3:]:
                print(f"        | {line.strip()[:96]}")

        print("-" * 74)
        print("suspension fixtures 结果:", "全部通过" if ok else "有 FAIL")
    finally:
        shutil.rmtree(base, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
