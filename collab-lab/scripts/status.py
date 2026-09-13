#!/usr/bin/env python -u
# -*- coding: utf-8 -*-
"""
status.py —— 一屏状态：把"agent 在干嘛、工程与方法学各占多少"压成一屏给人看

## 和另外两个交付物的分工（不要重复）

| 交付物 | 治什么 | 形态 |
|---|---|---|
| `DIGEST-<块>.md` | **这一次实验说明什么** | 单块，字符预算硬 |
| `MAP.md` | **我走过了什么、下一步往哪走** | 长文，按人提问顺序组织 |
| **本脚本的输出** | **此刻我在哪、配比如何、该我决定什么** | 一屏，按目的与块组织 |

前两者都假设人愿意读几百到几万字节。本脚本假设**人只有 30 秒**。

## 设计约束（硬）

- 目标长度 **≤ 45 行**；超了就是没提炼出重点（同 `digest-card.md` 的精神）
- **先姿态后内容**：先说"我们在哪、目的守不守得住"，再说细节
- 每个"需要你决定"的条目必须带**你会拿到什么 / 你要花什么**
- 术语剥离：给人看的行里不出现自造术语（同 `human-facing-output.md` §3.5）
- 数字来自**可核对的文件**，不来自记忆

## 用法

```bash
python scripts/status.py --charter CHARTER.md --ledgers ledgers/ \
  --protocols protocols/ runs/ --decisions DECISIONS.md
```
"""
import argparse
import re
import sys
from pathlib import Path

# 复用 goal_guard 的解析器，避免两套口径。
# ⚠️ 凡是**两个脚本消费同一份文本**的解析，都必须只有一处定义：
#    各写一份会导致"改了一边、另一边静默失效"（本轮实测过，见 goal_guard.py 的注释）。
sys.path.insert(0, str(Path(__file__).resolve().parent))
# 输出兜底（import 即生效）：这一屏是"人脸"，它同样**不许因为一个字印不出来就崩**
# —— 见 subproc.py 的"写的一侧"。这里显式 import，因为 status 不调用子进程。
import subproc  # noqa: E402,F401
try:
    from goal_guard import (parse_goals, parse_ledgers, parse_protocols,
                            split_theory_entries, FIELD_RE, GOAL_RE,
                            BLOCK_GOAL_RE, BLOCK_THEORY_RE,
                            AVAILABILITY_RE, DUE_BLOCK_RE, DEMOTED_TO_RE)
except Exception:  # pragma: no cover
    print("无法导入 goal_guard.py（两脚本必须同目录）")
    raise

GOAL_CN = {
    "basis": "解决实际问题",
    "method": "方法洞见",
    "bridge": "从实践长出理论课题",
}
MAX_LINES = 45
# BLOCK_GOAL_RE / BLOCK_THEORY_RE 从 goal_guard 导入 —— 此处**不要**再定义一份，
# 否则本地副本会遮蔽导入的那份，两边又会分裂（本轮实测过这个坑）。


def cn(tag):
    return GOAL_CN.get(tag, tag)


def md_plain(s: str) -> str:
    """去掉**加粗**标记 —— 一屏是控制台文本，`**` 不会渲染，只会变成噪声。"""
    return s.replace("**", "")


def _cut(s: str, n: int) -> str:
    """按字符截断，并保证反引号成对（截断最容易切开一对 `` ` ``）。"""
    if len(s) <= n:
        return s
    t = s[:n]
    if t.count("`") % 2:
        t += "`"
    return t + "…"


def read_block_goals(protos):
    """每个协议块声明推进哪些目的；顺便取它的编号与理论链接。"""
    out = []
    for num, name, path in protos:
        try:
            t = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        goals = BLOCK_GOAL_RE.findall(t)
        tm = BLOCK_THEORY_RE.search(t)
        title = ""
        m = re.search(r"^##\s*一句话主张\s*\n+(.+)$", t, re.M)
        if m:
            title = m.group(1).strip()[:34]
        out.append({"num": num, "name": name, "goals": goals,
                    "theory": tm.group(1) if tm else None, "title": title})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--charter", required=True)
    ap.add_argument("--ledgers", nargs="+", required=True)
    ap.add_argument("--protocols", nargs="*", default=[])
    ap.add_argument("--decisions", default=None)
    ap.add_argument("--theory-ledger", default=None)
    ap.add_argument("--recent", type=int, default=4, help="回看最近几块")
    args = ap.parse_args()

    L = []   # 输出行
    charter = Path(args.charter)
    protos = parse_protocols([Path(p) for p in args.protocols])
    blocks = read_block_goals(protos)
    entries = parse_ledgers([Path(p) for p in args.ledgers])
    goals = parse_goals(charter) if charter.exists() else None

    # ---------- 0. 状态一行 ----------
    # 人第一眼看的是"我们在哪、守不守得住"，所以这一行必须在最前，且必须来自可核对的文件。
    headline = None
    if charter.exists():
        ct0 = charter.read_text(encoding="utf-8")
        m0 = re.search(r"<headline>(.*?)</headline>", ct0, re.S)
        if m0:
            # ⚠️ 把 `**加粗**` 去掉再印。理由：一屏是**控制台文本**，`**` 不会渲染，
            #    它只会让人读到一堆星号（"看不懂输出"正是本 skill 要治的症状之一）。
            #    行内代码的 `` ` `` 保留 —— 它标的是文件名/命令，反引号本身有信息。
            headline = " ".join(m0.group(1).split()).replace("**", "")
    if headline:
        L.append("状态：" + headline)
    if goals:
        L.append("目的（来自 CHARTER）：" + " / ".join(cn(g) for g in goals))
    else:
        L.append("[!] 没有读到 CHARTER 的 <goals> —— 没有参照物，无法判定配比")

    # ---------- 1. 配比：工程 vs 方法学 ----------
    L.append("")
    L.append("■ 这几轮在干嘛（按协议块自己的声明；越新在右）")
    tail = blocks[-args.recent:] if blocks else []
    if tail:
        # 不并排显示目的与标题：宽列中文混排在等宽终端上会被读成一团（本脚本开发时实测）。
        # 改为按目的分组，标题只作缩进副行、且极短。
        by_goal = {}
        for b in tail:
            key = tuple(b["goals"]) if b["goals"] else ("（未声明）",)
            by_goal.setdefault(key, []).append(b)
        for key, bs in by_goal.items():
            label = "/".join(cn(x) for x in key)
            nums = "、".join(f"P-{b['num']}" for b in bs)
            # 块的「理论链接」按块列出：它同时是"为什么这么做"的答案，
            # 也是让 BLOCK_THEORY_RE 的解析真的被使用的地方
            # —— 否则那段解析会变成死代码，而**死代码无法被测出回归**
            #（本轮变异测试 M4 就是这样暴露的）。
            links = "、".join(f"P-{b['num']}→{b['theory']}" for b in bs if b["theory"])
            extra = f"。理论链接：{links}" if links else ""
            L.append(f"   {label}：{len(bs)} 块（{nums}）{extra}")
        eng = sum(1 for b in tail if b["goals"] == ["basis"])
        meth = sum(1 for b in tail if any(x in ("method", "bridge") for x in b["goals"]))
        L.append(f"   → 最近 {len(tail)} 块：纯工程 {eng} 块、含方法学 {meth} 块")
        if eng == len(tail) and len(tail) >= 3:
            L.append("   [!] 连续纯工程 —— 方法学目的未被推进（守卫会 FAIL）")
    else:
        L.append("   （没有协议块）")

    # ---------- 2. 目的健康度 ----------
    L.append("")
    L.append("■ 目的健康度（台账条目数 = 该目的被沉淀了多少）")
    if goals:
        per = {g: [e for e in entries if e["tag"] == g] for g in goals}
        for g in goals:
            n = len(per[g])
            newest = max((e["mtime"] for e in per[g]), default=0)
            since = sum(1 for _, _, p in protos if p.stat().st_mtime > newest) if newest else len(protos)
            flag = ""
            if g in ("method", "bridge") and since >= (3 if g == "method" else 4):
                flag = "  [!] 该目的最后入账之后又有 %d 块" % since
            L.append(f"   {cn(g):<14s} {n:>2d} 条{flag}")
    # 无标记条目
    untagged = [e for e in entries if not e["tag"]]
    if untagged:
        L.append(f"   [!] {len(untagged)} 条台账未打目的标记，无法计入配比")

    # ---------- 2b. 协议块的预注册状态（事前 / 事后）----------
    # 立此的原因：13 个块里 5 个是事后补记，而**从文件本身看不出来**
    # （只能读散文找 "ex-post"，那个词还会出现在引用别人的句子里）。
    # 这一行直接回答"这套预注册有多少是真的"，属于人脸该看的东西。
    if getattr(args, "protocols", None):
        blocks = []
        for d in args.protocols:
            dp = Path(d)
            if dp.is_dir():
                blocks += [p for p in sorted(dp.rglob("*.md"))]
            elif dp.exists() and dp.suffix.lower() == ".md":
                blocks.append(dp)
        pre = post = unknown = 0
        for b in blocks:
            try:
                txt = b.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            m = re.search(r"^预注册[:：]\s*(\**)\s*(事前|事后)", txt, re.M)
            if m is None:
                unknown += 1
            elif m.group(2) == "事前":
                pre += 1
            else:
                post += 1
        if blocks:
            L.append("")
            L.append(f"■ 预注册状态（{len(blocks)} 个协议块）")
            L.append(f"   事前预注册 {pre} 块；事后补记 {post} 块"
                     + (f"；未声明 {unknown} 块" if unknown else "")
                     + ("   ← 事后补记意味着判据可能是在看到结果之后才写下的"
                        if post else ""))

    # ---------- 3. 理论闭环（theory → experiment） ----------
    L.append("")
    L.append("■ 理论闭环（有方向 → 有实验 → 有回填）")
    if args.theory_ledger:
        tp = Path(args.theory_ledger)
        if tp.exists():
            tentries = split_theory_entries(tp.read_text(encoding="utf-8"))
            rows = []
            for tid, blob in sorted(tentries.items()):
                m = FIELD_RE["成熟度"].search(blob)
                mat = m.group(1) if m else "?"
                u = FIELD_RE["被用于"].search(blob)
                used = (u.group(1).strip() if u else "")
                has_exit = bool(used) and not used.startswith("无")
                # 可用性：只有 `挂起` 才印出来 —— 它是**有到期日的例外状态**，
                # 人必须一眼看见（"这条现在不能用，什么时候必须处置"）。
                # `可用` 是常态，印出来只是噪声（这一屏的预算只有 45 行）。
                #
                # ⚠️ 用 `[...]` 而不是 emoji（第一版用了 ⏳）：cp936 印不出 emoji，
                #    于是它会被兜底成 `?` —— **人脸那一屏上出现一个 `?` 是噪声**。
                #    "兜底不崩"不等于"看着没问题"，后者要自己挑字符。
                av = AVAILABILITY_RE.search(blob)
                mark, live = "", True
                if av and av.group(1) == "挂起":
                    due = DUE_BLOCK_RE.search(av.group(2))
                    mark = f"  [挂起→P-{due.group(1)}]" if due else "  [挂起·无到期!]"
                elif av and av.group(1) == "已降级":
                    dst = DEMOTED_TO_RE.search(av.group(2))
                    mark = f"  [已降级→{dst.group(1) if dst else '?'}]"
                    live = False
                rows.append((tid, mat, has_exit, mark, live))
            # 汇总**只统计活条目**：第 20 轮实测到"共 1 条、已有出口 2 条"这种自相矛盾，
            # 原因是把已降级的 T-1 也算进了"已有出口"。
            closed = sum(1 for _, _, e, _, live in rows if e and live)
            dirs = sum(1 for _, m, _, _, live in rows if m == "具体方向" and live)
            for tid, mat, e, mk, live in rows:
                label = mat if live else "已降级"
                L.append(f"   {tid}  {label:<10s} 出口：{'有' if e else '无'}{mk}")
            L.append(f"   → 活条目中 成熟度=具体方向 {dirs} 条，已有出口 {closed} 条"
                     + ("（另有已降级条目，见上）"
                        if any(not live for _, _, _, _, live in rows) else ""))
            blocked = [t for t, m, e, _, live in rows if live and m == "具体方向" and not e]
            if blocked:
                L.append(f"   [!] {'、'.join(blocked)} 可执行却没人做 —— 这是"
                         "「理论在收藏」的形态")
        else:
            L.append("   （未找到理论台账）")
    else:
        L.append("   （未指定 --theory-ledger）")

    # ---------- 4. 该你决定什么 ----------
    #
    # ⚠️ 这里此前**把 agent 自己的待办也列成"该你决定"**（判定条件是
    #    `"**待" in line or "待回改" in line`）—— 实测一屏上出现过
    #    「此前"门控增量仅 1.1%"的表述需加注」，那是我自己的待办，不是用户的决定。
    #    **把 agent 的活推给人，比不写更坏**：人会以为自己漏了一件该做的事。
    # ⇒ 现在分成两段：**只有状态含「等你」的行**才进"该你决定"，并带上三件套；
    #    agent 自己的未完成项另起一段，标题就写明"不是你要决定的"。
    L.append("")
    L.append("■ 该你决定 / 只有你能推进的")
    pend, mine = [], []
    if args.decisions:
        dp = Path(args.decisions)
        if dp.exists():
            rows = [ln for ln in dp.read_text(encoding="utf-8").splitlines()
                    if ln.startswith("|")]
            header = [c.strip() for c in rows[0].strip("|").split("|")] if rows else []
            col = {n: (header.index(n) if n in header else None)
                   for n in ("决定", "状态", "你会拿到什么", "你要花什么", "前置条件")}
            for line in rows[2:]:
                cells = [md_plain(c.strip()) for c in line.strip("|").split("|")]
                if len(cells) < 3 or col["状态"] is None or col["状态"] >= len(cells):
                    continue
                status = cells[col["状态"]]
                what = _cut(cells[col["决定"]], 46) if col["决定"] is not None else ""

                def cell(name, n=44):
                    i = col[name]
                    return _cut(cells[i], n) if (i is not None and i < len(cells)) else ""

                if "等你" in status:
                    pend.append((what, cell("你会拿到什么"), cell("你要花什么"),
                                 cell("前置条件")))
                elif any(k in status for k in ("待回改", "待补", "待定", "待做")):
                    mine.append(what)
    if pend:
        for what, got, cost, pre in pend[:3]:
            L.append(f"   · {what}")
            L.append(f"       拿到：{got}")
            L.append(f"       花掉：{cost}")
            L.append(f"       前置：{pre}")
    else:
        L.append("   · （没有要你决定的事）")
    if mine:
        L.append("")
        L.append("■ agent 自己的未完成项（**不是你要决定的**）")
        for w in mine[:3]:
            L.append(f"   · {w}")

    # ---------- 5. 缺口 ----------
    L.append("")
    L.append("■ 已知缺口（可核对的文件里写着「待」「未知」「无来源」的）")
    gaps, done = [], 0
    if charter.exists():
        ct = charter.read_text(encoding="utf-8")
        m = re.search(r"##\s*\d*\.?\s*当前未知(.*?)(?=\n##|\Z)", ct, re.S)
        if m:
            # ⚠️ **先把一条列表项的续行并回同一条**。
            #    实测（第 31 轮）：一个带删除线的多行条目，其**续行**（如
            #    "P1 反例 = 293 / 267 / 220…"）不含 `~~`，于是被判成一条**独立缺口**
            #    印在一屏上 —— 人读到的是一个没头没尾的片段。
            #    这类"按行判断、而内容是多行"的解析缺陷在 status.py 里出现过多次
            #    （同 goal_guard 的"解析器分裂"教训）：**判定必须以"条目"为单位，不是以"行"为单位。**
            #
            # ⚠️ 判定"是不是新条目"必须用 `标记 + 空白`，**不能只看首字符**：
            #    `*` 既是项目符号、又是 markdown 加粗的开头 ⇒ 行首的 `**已落定…**`
            #    会被当成一条**新项目**。实测（第 31 轮）：一条多行条目的续行以 `**` 开头，
            #    于是它的续行被拆成两条独立"缺口"印在一屏上 —— 人读到的是
            #    「已落定（第 20 轮…）」和「P1 反例 = 293 / 267 / 220」，两条都没头没尾。
            BULLET_RE = re.compile(r"^([-*·+])(\s|$)")
            bullets, cur = [], None
            for raw in m.group(1).splitlines():
                s = raw.strip()
                if BULLET_RE.match(s):
                    if cur is not None:
                        bullets.append(cur)
                    cur = BULLET_RE.sub("", s, count=1).strip()
                elif cur is not None and s:
                    cur += " " + s
            if cur is not None:
                bullets.append(cur)
            for item in bullets:
                if not item or item.startswith(("（", "(")):
                    continue
                if item.endswith("：") or item.endswith(":"):
                    continue
                # ⚠️ **划掉的（`~~…~~`）是"已落定"，不属于"已知缺口"。**
                #    实测（第 31 轮）：这一节里混着 4 条带删除线的历史条目，
                #    既占掉一屏的 4 行、又让"缺口"这个词变得不真 ——
                #    人读到一堆带星号的历史，会以为缺口很多而其实只剩 3 条。
                #    ⇒ 已落定的并成一句"另有 N 条已划掉"。
                if "~~" in item:
                    done += 1
                    continue
                gaps.append(_cut(item, 60))
    for g in gaps:
        L.append(f"   · {g}")
    if done:
        L.append(f"   （另有 {done} 条已划掉 = **已落定**，不在此列；全文见 CHARTER 第 3 节 / MAP）")
    if not gaps:
        L.append("   （CHARTER 未列当前未知）")

    # ---------- 输出 + 硬预算自检 ----------
    #
    # ⚠️ 设计教训（本脚本开发时实测）：第一版把每个区块都截断（`gaps[:4]` 等），
    # 结果 **45 行预算永远触发不了** —— 一个无法触发的预算等于没有预算，
    # 校验器只会说 OK。所以这里改成：先按预算分配每块可用的行数，
    # 超出的部分**显式计入行数**并标"（还有 N 条未列）"，让预算真的会爆。
    over = []
    if len(L) > MAX_LINES:
        over = list(range(MAX_LINES, len(L)))
        hidden = len(over)
        L = L[:MAX_LINES]
        L.append(f"   …（还有 {hidden} 行被预算截断 —— 这正是「没提炼出重点」的信号）")

    print("=" * 74)
    print("一屏状态（≤ %d 行预算）" % MAX_LINES)
    print("=" * 74)
    for line in L:
        print(line)
    print("-" * 74)
    n = len(L)
    status = "OK" if not over else "超预算"
    print(f"{n} 行 / 预算 {MAX_LINES} 行  → {status}")
    if over:
        print("=> 超预算不是「稍微超一点」，是没提炼出重点。重写，别把负担转给人。")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
