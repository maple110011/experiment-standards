#!/usr/bin/env python -u
# -*- coding: utf-8 -*-
"""
test_guard_fixtures.py —— 可重跑的"守卫场景"自检

## 为什么需要它（立此脚本的直接原因）

上一轮我用一个**一次性**的干净场景演练，抓到了守卫的"早期误诊"并修掉了。
但那个演练**没有留下来** —— 下次改守卫时，它不会被重跑，
于是同样的误诊可以再犯一次。

这与"45 行预算永远触发不了"是同一类错误：
**一次性验证等于没有验证。**

## 四个场景（每个都对应一次真实的失效或一次真实的状态）

| 场景 | 期望 | 它防的是什么回归 |
|---|---|---|
| `fresh`  只有 CHARTER，无块无台账 | 退出码 0，报"未开工" | 新课题一开始就收到假警报 |
| `early`  2 块，`basis`/`bridge` 无台账 | 退出码 1（WARN，非 FAIL） | 早期被当成偏离 |
| `drift`  8 块，台账停在很久以前 | 退出码 2，报"偏离 method" | **真偏离被放过**（修早期误诊最容易引入的副作用） |
| `clean`  块与台账齐平、闭环完整 | 退出码 0 | 正常状态被误报 |

**mtime 用 `os.utime` 显式设置，不用 `sleep`** —— 让结果确定且秒级完成。

## 用法

```bash
python scripts/test_guard_fixtures.py          # 由 check_collab_artifacts.py --self-test 调用
```
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import subproc  # noqa: E402  （子进程编码只有这一处定义，见 subproc.py）
GUARD = HERE / "goal_guard.py"

T0 = 1_700_000_000          # 基准时间戳（2023-11-14），全部用显式 mtime

CHARTER = """# CHARTER — fixtures 用

<headline>{headline}</headline>

<goals>
- `basis`: 解决实际问题 —— 测试
- `method`: 方法洞见 —— 测试
- `bridge`: 从理论回到实验 —— 测试
</goals>

## 4. 当前未知

- 待测项 A `?`
"""

LEDGER_M = """# methods

## M-1 [method] 测试条目

等级: 薄

主张: 测试主张

适用边界: 测试边界

复现: 1 次

被用于: 无

推翻条件: 测试推翻条件
"""

LEDGER_Q = """# problem

## Q-1 [basis] 测试事实

证据: `fixtures`

等级: 稳定

事实: 测试事实

影响: 测试影响

被用于: 无

什么能改: 测试
"""

LEDGER_T = """# theory

## T-1 [bridge] 测试理论条目

现象: 测试现象

证据: 等级: 薄

缺口: 测试缺口

理论问题: 为什么 X 在 Y 下失效？

成熟度: 具体方向

可用性: 可用

方向A: 测试方向 A

方向B: 测试方向 B

区分实验: 测试区分实验

被用于: `P-TEST-{last:03d}`

什么能证伪: 测试证伪条件
"""

BLOCK = """# PROTOCOL-P-{n:03d}

## 一句话主张
测试块 {n}

## 本块推进哪个目的
- 目的：`{goal}`

## 本块服务于哪条理论条目

| 项 | 内容 |
|---|---|
| 理论条目 | `{theory}`{thnote} |
| 检验哪条方向 | 测试 |
| 若结果如此则降级 | 测试 |
{extra}
"""


def build(root: Path, name: str, n_blocks: int, ledger_mtime: float,
          block_mtime: float, with_q_bridge: bool = False,
          block_goals=None, with_decisions: bool = False,
          theory_decl: str = "linked", extra: str = "",
          headline: str = None):
    (root / "ledgers").mkdir(parents=True, exist_ok=True)
    (root / "protocols").mkdir(parents=True, exist_ok=True)
    # 人面（<headline>）默认**点名最新块**：判据 8 要求它不能过时。
    # 不点名最新块时守卫会（正确地）报 FAIL —— 那是 stale_head 场景要测的。
    hl = headline if headline is not None else (
        f"fixtures 场景：{name}；最新块 P-TEST-{n_blocks:03d}")
    (root / "CHARTER.md").write_text(
        CHARTER.replace("{headline}", hl), encoding="utf-8")
    if with_decisions:
        (root / "DECISIONS.md").write_text(
            "# DECISIONS\n\n| 日期 | 块号 | 决定 | 谁定的 | 理由 | 状态 |\n"
            "|---|---|---|---|---|---|\n| fixtures | - | 测试 | agent | 测试 | 生效 |\n",
            encoding="utf-8")
    if n_blocks > 0:
        (root / "ledgers" / "methods-x.md").write_text(LEDGER_M, encoding="utf-8")
        os.utime(root / "ledgers" / "methods-x.md", (ledger_mtime, ledger_mtime))
        if with_q_bridge:
            (root / "ledgers" / "problem-x.md").write_text(LEDGER_Q, encoding="utf-8")
            # 理论条目的「被用于」必须指向**真实存在且双向一致**的块，
            # 否则守卫会（正确地）报单向链接。
            (root / "ledgers" / "theory-x.md").write_text(
                LEDGER_T.replace("{last:03d}", f"{n_blocks:03d}"), encoding="utf-8")
            for f in ("problem-x.md", "theory-x.md"):
                os.utime(root / "ledgers" / f, (ledger_mtime, ledger_mtime))
    goals = block_goals or (["basis"] * n_blocks)
    for i in range(1, n_blocks + 1):
        # 文件名必须含 >=2 位数字：守卫用 PROTOCOL_RE = (\d{2,}) 取块号。
        # （fixtures 第一次运行时就因为写了 `PROTOCOL-P-1.md` 而一个块都没被识别到 ——
        #  这条命名约定此前没写在文档里，现已补进 references/goal-persistence.md。）
        p = root / "protocols" / f"PROTOCOL-P-TEST-{i:03d}.md"
        # 最后一块必须声明服务 T-1：理论条目的「被用于」写的就是它，
        # 两侧不一致时守卫会（正确地）报"单向链接不算链接"。
        #
        # `theory_decl` 的三档（第 29 轮新增后两档）：
        #   "linked"  = 块里写 `T-1` ⇒ 双向一致，干净；
        #   "none"    = 块里写 `无` 但台账「被用于」指向它 ⇒ **必须**报单向链接；
        #   "posthoc" = 块里写 `T-1`（事后归因）⇒ 不算 FAIL，但**必须**印出 INFO。
        # 立后两档的原因：本仓库真出现过"块跑完才逼出理论条目"（`P-BOILER-018` → `T-3`），
        # 而当时的机制只有两种结局：FAIL（删链接）或静默通过；两者都会丢掉"这条链接
        # 不是事前预注册的"这个信息。
        if i == n_blocks and with_q_bridge:
            if theory_decl == "none":
                th, note = "无", ""
            elif theory_decl == "posthoc":
                th, note = "T-1", "（**事后归因**：块跑完才逼出该理论条目）"
            else:
                th, note = "T-1", ""
        else:
            th, note = "无", ""
        p.write_text(BLOCK.replace("{n:03d}", f"{i:03d}").replace("{n}", str(i))
                     .replace("{goal}", goals[i - 1]).replace("{theory}", th)
                     .replace("{thnote}", note)
                     .replace("{extra}", extra if i == n_blocks else ""),
                     encoding="utf-8")
        os.utime(p, (block_mtime, block_mtime))


def run_guard(root: Path):
    led = root / "ledgers"
    theo = led / "theory-x.md"
    cmd = [sys.executable, str(GUARD),
           "--charter", str(root / "CHARTER.md"),
           "--ledgers", str(led),
           "--protocols", str(root / "protocols"),
           "--decisions", str(root / "DECISIONS.md")]
    if theo.exists():
        cmd += ["--theory-ledger", str(theo)]
    r = subproc.run_text(cmd)
    return r.returncode, r.stdout


SCENARIOS = [
    # 名称,    块数, 台账mtime,      块mtime,        需要Q/T, 需要DECISIONS, 期望码, 期望出现的字样,
    #                                                                              理论声明档, 不得出现的字样
    # fresh：什么都没有 —— 新课题的第一步，绝不能报"偏离"
    ("fresh", 0, T0, T0, False, False, 0, ["未开工"], "linked", []),
    # early：只有 method 台账，**basis/bridge 零入账**；块比台账新（方法学滞后）但块数 <3
    #        ⇒ 零入账只记 WARN、且带"项目早期"字样，不升 FAIL
    ("early", 2, T0, T0 + 1000, False, False, 1, ["项目早期", "零入账"], "linked", []),
    # drift：块数 >=3 且方法学滞后 ⇒ 升 FAIL。这条防的是"修早期误诊把真偏离也放过"
    ("drift", 8, T0, T0 + 1000, True, False, 2, ["偏离 method"], "linked", []),
    # clean：齐备且一致 ⇒ 必须干净（含 DECISIONS.md，否则会被一条 WARN 拉到退出码 1）
    ("clean", 4, T0 + 1000, T0, True, True, 0, ["FAIL 0"], "linked", []),
    # oneway：台账「被用于」指向最后一块，而那一块写的是 `无` ⇒ **必须**报单向链接
    #         （这一条是"放宽事后归因"的安全带：没有它，放宽就可能变成"全部放行"）
    ("oneway", 4, T0 + 1000, T0, True, True, 2, ["单向链接"], "none", []),
    # posthoc：同样的单向形态，但块里标了「事后归因」⇒ 不算 FAIL，**必须**印出 INFO
    ("posthoc", 4, T0 + 1000, T0, True, True, 0, ["理论链接(事后)"], "posthoc", []),
    # escape：**对抗场景（反向断言）**。块**正常声明** `T-1`（双向一致 ⇒ 干净、退出码 0），
    #         但正文别处提了一句"事后归因"。若标记判定被放宽成"整块文本里出现即豁免"，
    #         这一条会**多出**一行 INFO —— 必须**不出现**。
    #         立此的理由：放宽一个 FAIL 条件时，必须同时有"不该被放宽"的反向场景，
    #         否则"放宽"与"全部放行"在 fixtures 上无法区分（`B28` 第 ② 项）。
    ("escape", 4, T0 + 1000, T0, True, True, 0, ["FAIL 0"], "linked",
     ["理论链接(事后)"]),
    # stale_head：块已经到 004，而人面还停在第 001 块 ⇒ **必须**报"人面过时"。
    # 立此的实测原因：`status.py` 把 <headline> 印在一屏顶部，而此前没有任何东西
    # 检查它是不是过时的 —— 实测它停在第 27 轮，而 28/29 轮已经换掉了头号结论的支持链。
    # 这正是本 skill 立文的症状：**人读到的"现在在哪"落后于实际进展**。
    ("stale_head", 4, T0 + 1000, T0, True, True, 2, ["人面过时"], "linked", [],
     "fixtures：人面停在第 001 块（过时）"),
    # long_head：人面点名了最新块，但**一整段 800 字** ⇒ **必须**报"人面过长"。
    # 立此的原因：一屏的**行数预算可以被一整段话绕过**（一段只算 1 行）。
    ("long_head", 4, T0 + 1000, T0, True, True, 2, ["人面过长"], "linked", [],
     "fixtures：人面点名 P-TEST-004 但很长。" + "这句话用来把长度推过预算。" * 80),
]


def main():
    # 用临时目录建场景；沙箱下系统 TEMP 可能不可写，故退到 HERE/_fixtures_tmp
    base = HERE / "_fixtures_tmp"
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    print("=" * 74)
    print("守卫场景 fixtures 自检（9 个场景，mtime 显式设定，无 sleep；含 1 个反向断言）")
    print("=" * 74)
    ok = True
    try:
        for (name, n, lm, bm, needqt, needdec, exp_code, must_contain,
             tdecl, must_not, *rest) in SCENARIOS:
            root = base / name
            root.mkdir()
            hl = rest[0] if rest else None
            # escape 场景：正常声明 T-1，但在正文别处提到"事后归因" ⇒ 不得因此豁免
            extra = ("> 注：本块的部分读数是**事后归因**得到的，写在这里只为说明来源。"
                     if name == "escape" else "")
            build(root, name, n, lm, bm, with_q_bridge=needqt,
                  with_decisions=needdec, theory_decl=tdecl, extra=extra,
                  headline=hl)
            code, out = run_guard(root)
            hits = [s for s in must_contain if s in out]
            bad = [s for s in must_not if s in out]
            good = (code == exp_code) and len(hits) == len(must_contain) and not bad
            print(f"{'PASS' if good else 'FAIL'}  {name:8s} 退出码 {code}（期望 {exp_code}）"
                  f"  命中字样 {hits}"
                  + (f"  ⚠️ 不该出现却出现了 {bad}" if bad else ""))
            if not good:
                ok = False
                for line in out.splitlines():
                    if re.search(r"FAIL|WARN|偏离|未开工|项目早期", line):
                        print(f"        | {line.strip()[:100]}")
        print("-" * 74)
        print("fixtures 结果:", "全部通过" if ok else "有 FAIL（守卫行为已变，需检查）")
    finally:
        shutil.rmtree(base, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
