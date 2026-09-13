#!/usr/bin/env python -u
# -*- coding: utf-8 -*-
"""
goal_guard.py —— 目标守卫：机械检测"agent 是否偏离了声明过的目的"

## 为什么需要它（立此脚本的那次失效）

在一个真实会话里，agent 连续两轮完全投入**竞赛工程**（提交探测、提分），
期间**方法学台账零更新**。偏离是**静默**发生的：没有任何机制在运行时提醒。
事后复盘发现根因是**没有目标宣言**（`CHARTER.md` 不存在），于是"偏离"没有参照物。

文档纪律拦不住这件事 —— 一个只在"有人维护它"时才起作用的规矩，必然在忙碌时失效。
所以这里把它做成脚本：**每轮结束跑一次，机械报出配比与陈旧度。**

## 输入

1. `--charter`：目标宣言，必须含 `<goals>` 块，每行形如 `` - `tag`: 描述 ``
2. `--ledgers`：台账目录（或单文件）。条目标题形如
   `## M-3 [method] 主张……` / `### Q-1 [basis] 事实……`
   方括号里的 tag 就是它推进的目的；**缺 tag 会被报出来**
3. `--protocols`：协议块目录（可多次给）。文件名里的编号定义"块顺序"
4. `--decisions`：决策日志（可选），用来抓"封存/撤销"这类状态变化

## 输出

- 每个目的的**条目数**与**最近一次推进发生在第几块**
- **连续多少块没有推进某目的**（默认阈值：方法 ≥3 报警、桥梁 ≥4 报警）
- **台账陈旧度**：文件 mtime 与最新协议块的差距
- 未打 tag 的台账条目清单

退出码：0 = 无偏离；1 = 有 WARN；2 = 有 FAIL（偏离已确认）。
"""
import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

# 输出兜底：import 本模块即把 sys.stdout/stderr 的 errors 设为 replace。
# 立此 import 的失效（实测）：给本条判据 5 加了一句含 `⇒`（U+21D2）的提示，
# 而 cp936 里**没有这个字符** ⇒ `UnicodeEncodeError` ⇒
# **守卫在"报告失败"的那一行崩掉**（exit 1 + traceback，而不是 exit 2 + FAIL）。
# 一个"只在控制台能编码你写的字时才报得出错"的守卫，等于没有守卫。
sys.path.insert(0, str(Path(__file__).resolve().parent))
import subproc  # noqa: E402,F401

GOAL_RE = re.compile(r"^\s*[-*]\s*`([A-Za-z0-9_\-]+)`\s*[:：]\s*(.+?)\s*$")
ENTRY_RE = re.compile(r"^\s{0,3}#{2,4}\s*([QMT]-\d+)\s*(?:\[([A-Za-z0-9_\-]+)\])?\s*(.*)$")
PROTO_RE = re.compile(r"(\d{2,})")

DEFAULT_THRESHOLDS = {"method": 3, "bridge": 4}


class Report:
    def __init__(self):
        self.rows = []

    def add(self, level, item, detail):
        self.rows.append((level, item, detail))

    def emit(self):
        order = {"FAIL": 0, "WARN": 1, "OK": 2, "INFO": 3}
        rows = sorted(self.rows, key=lambda r: order.get(r[0], 9))
        width = max([len(i) for _, i, _ in rows] + [12])
        for lv, item, detail in rows:
            print(f"{lv:5s} {item:<{width}s} {detail}")
        fails = sum(1 for lv, _, _ in self.rows if lv == "FAIL")
        warns = sum(1 for lv, _, _ in self.rows if lv == "WARN")
        infos = sum(1 for lv, _, _ in self.rows if lv == "INFO")
        print("-" * 78)
        print(f"FAIL {fails}   WARN {warns}   INFO {infos}")
        if fails:
            print("\n⇒ 已确认偏离：先回到 CHARTER 第 0 节，说明下一步推进哪个目的。")
            return 2
        if warns:
            print("\n⇒ 有偏离迹象：本轮结束前处理，或显式记录「本轮不推进 X，因为…」。")
            return 1
        return 0


def parse_goals(charter: Path):
    text = charter.read_text(encoding="utf-8")
    m = re.search(r"<goals>(.*?)</goals>", text, re.S)
    if not m:
        return None
    goals = {}
    for line in m.group(1).splitlines():
        g = GOAL_RE.match(line)
        if g:
            goals[g.group(1)] = g.group(2)
    return goals


def parse_ledgers(paths):
    """返回 entries = [{id, tag, title, file, mtime}]"""
    files = []
    for p in paths:
        if p.is_dir():
            files += sorted(p.rglob("*.md"))
        elif p.exists():
            files.append(p)
    entries = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        for line in text.splitlines():
            m = ENTRY_RE.match(line)
            if m:
                entries.append({"id": m.group(1), "tag": m.group(2),
                                "title": m.group(3).strip(), "file": f.name,
                                "mtime": f.stat().st_mtime})
    return entries


def parse_protocols(paths):
    """返回按编号排序的 [(num, name, path)]"""
    out = []
    for p in paths:
        if not p.exists():
            continue
        files = sorted(p.rglob("*")) if p.is_dir() else [p]
        for f in files:
            if not f.is_file() or f.suffix.lower() not in (".md", ".json", ".yaml", ".yml"):
                continue
            m = PROTO_RE.search(f.name)
            if m:
                out.append((int(m.group(1)), f.name, f))
    return sorted(out, key=lambda x: x[0])


def parse_decision_row(path: Path):
    return path.exists()


# --------------------------------------------------------------------------- #
# 理论 → 实验 的闭环审计（见 references/theory-to-experiment.md）
# --------------------------------------------------------------------------- #
THEORY_ENTRY_RE = re.compile(r"^\s{0,3}#{2,4}\s*(T-\d+)\b")
FIELD_RE = {
    # ⚠️ **不要锚定行尾**：台账会写成 `成熟度: 具体方向（降级前的最后状态）`，
    #    锚定 `\s*$` 会让它**静默失配** ⇒ 守卫的判据 1/2（都以成熟度为门）**整段不执行**，
    #    而 status 那一屏会显示 `?`。第 20 轮实测：T-1 降级后正好触发这个形态。
    #    放宽后只会让守卫**多查**，不会漏查。
    "成熟度": re.compile(r"^成熟度[:：]\s*(初步观察|可研究的问题|具体方向)", re.M),
    "区分实验": re.compile(r"^区分实验[:：]", re.M),
    "被用于": re.compile(r"^被用于[:：]\s*(.+)$", re.M),
}
# 可用性：`可用` / `挂起（到期 P-<块号>）` / `已降级（→ M-<号>）`。
# 见 references/theory-ladder.md「降级判据」第 4 条 —— **挂起是允许的，没有到期日的挂起不是**。
# `已降级` 是第三种状态：条目已按降级规程搬进方法台账；**保留标题**只为
# 保住协议块的指向 + 让降级在"原位置"可见。它**必须有去向**（`→ M-nn`），
# 否则就是"删了但没留痕"。
#
# ⚠️ **本正则是"可用性"字段的唯一定义**：`check_collab_artifacts.py` 从这里 import，
#    不许在别处再写一份（同 `BLOCK_GOAL_RE` 的理由：副本会静默分裂）。
#    允许字段值被 `**` 包住 —— 台账是 markdown，人会顺手加粗，这不是违规。
AVAILABILITY_RE = re.compile(r"^可用性[:：]\s*\**\s*(可用|挂起|已降级)\s*(.*)$", re.M)
# 到期块的编号。⚠️ **必须接受"完整块名"，不只是 `P-011` 这种短名**：
# 块名可能带主题段（形如 `P-<主题>-019`，文件名 `PROTOCOL-P-<主题>-019.md`），
# 而这条正则原先写成 `P-?\s*(\d{1,4})` —— 它把完整块名判成"没写到期块"。
# 实测代价（某轮）：一条挂起按预注册的停止规则写成 `挂起（到期 P-<主题>-021）`，
# 于是校验器与守卫**同时**报"没有到期日的挂起 = 永久免于证伪" ——
# 而那条挂起写得完全正确。**误报的代价不是多跑一次，是逼人把合规的写法改坏**
# （最省事的"修法"是把完整块名改成短名 `P-021`，那样到期日就指向一个不存在的块）。
DUE_BLOCK_RE = re.compile(r"到期\s*`?(?:P-[A-Za-z0-9_\-]*?)?(\d{1,4})`?")
DEMOTED_TO_RE = re.compile(r"(?:→|->|=>)\s*`?(M-\d+)`?")
LINK_RE = re.compile(r"P-[A-Za-z0-9_\-]*\d+")
# 「本块服务于哪条理论条目」既可能是 `理论条目: T-1`，也可能写在表格里
# `| 理论条目 | \`T-1\` |` —— 模板用的是后者，所以两种都要认。
BLOCK_THEORY_RE = re.compile(r"理论条目\s*[:：|\]]\s*`?(T-\d+)`?")
# 「事后归因」标记：块**跑完之后**才逼出来的理论条目，块里根本来不及声明它。
#
# ⚠️ 立此的原因（某轮实测）：一个块跑出一个反直觉读数（折间差异**不是**噪声，
#    而是符号翻转），这个读数**逼出了**一条新理论条目 `T-3`；而 `T-3` 写在块之后 ⇒
#    块里不可能"事前声明服务于 T-3"。守卫判据 3a 于是报 FAIL（单向链接）。
#    但把链接从台账里删掉是**更坏**的处理 —— 那会隐藏一条真实的证据依赖。
#    ⇒ 正解是**允许声明，但要求标明它是事后归因**，并把它印进守卫输出（INFO），
#       让"哪些理论链接不是事前预注册的"这件事**看得见**，而不是要么 FAIL、要么静默通过。
POSTHOC_MARK = "事后归因"
# `<headline>` 的单段长度预算（字符）。行数预算管不住一整段话，见判据 8 的说明。
HEADLINE_MAX = 700
# 取"声明了 T-x 的那一行"，用来判断这一行的链接是不是标了事后归因。
THEORY_LINE_RE = re.compile(r"^.*理论条目.*$", re.M)
# 协议块声明的目的（`- 目的：\`method\``）。
#
# ⚠️ 本正则与上面两条一起**供 status.py 导入使用**，不要在别处再写一份。
#    理由是本轮实测到的一类静默失效：`BLOCK_THEORY_RE` 曾在 guard 侧
#    从 `[:：]` 改成 `[:：|\]]`，而 status.py 里的**副本**没有同步 ——
#    它照样跑、照样输出，只是那一段信息悄悄变成了空。
#    ⇒ 两个脚本消费同一份文本时，解析器必须只有一处定义。
BLOCK_GOAL_RE = re.compile(r"目的[:：]\s*`([A-Za-z0-9_\-]+)`")


def split_theory_entries(text):
    """按 T- 编号切块（理论台账条目用 '## T-n …'）"""
    out = {}
    cur = None
    for line in text.splitlines():
        m = THEORY_ENTRY_RE.match(line)
        if m:
            cur = m.group(1)
            out[cur] = []
        elif cur:
            out[cur].append(line)
    return {k: "\n".join(v) for k, v in out.items()}


def audit_theory_loop(theory_path: Path, protos, rep):
    """三条判据：有方向没出口 / 陈旧 / 闭环缺失。"""
    if not theory_path.exists():
        rep.add("WARN", "理论闭环", f"未指定或不存在的理论台账：{theory_path}")
        return
    text = theory_path.read_text(encoding="utf-8")
    entries = split_theory_entries(text)
    if not entries:
        rep.add("WARN", "理论闭环", "理论台账里没有 T-* 条目")
        return

    # 协议块里声明的 T- 链接
    block_links = {}   # blockname -> set(T-x)
    posthoc_links = {}  # blockname -> set(T-x)：声明行里带「事后归因」的那些
    for num, name, path in protos:
        try:
            t = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        found = set(BLOCK_THEORY_RE.findall(t))
        if found:
            block_links[name] = found
        # 只有"声明 T- 的那一行"里出现标记才算 —— 免得正文里提一句就整块豁免。
        ph = set()
        for line in THEORY_LINE_RE.findall(t):
            if POSTHOC_MARK in line:
                ph |= set(BLOCK_THEORY_RE.findall(line))
        if ph:
            posthoc_links[name] = ph
    declared = set()
    for s in block_links.values():
        declared |= s

    # 协议块侧的块号（用于比较被用于里的编号）
    proto_nums = {n for n, _, _ in protos}
    newest_proto_mtime = max((p[2].stat().st_mtime for p in protos), default=None)

    for tid, blob in sorted(entries.items()):
        m = FIELD_RE["成熟度"].search(blob)
        mat = m.group(1) if m else None
        has_dist = bool(FIELD_RE["区分实验"].search(blob))
        u = FIELD_RE["被用于"].search(blob)
        used_raw = u.group(1).strip() if u else ""
        used_blocks = [] if used_raw.startswith("无") else LINK_RE.findall(used_raw)

        if mat == "具体方向":
            # 判据 1：有方向没出口
            if has_dist and not used_blocks:
                rep.add("WARN", f"理论无出口 {tid}",
                        "成熟度=具体方向 且写了区分实验，但「被用于: 无」"
                        "—— 设计好了却没人执行")
            # 判据 3a：被用于 指向的块必须真的链接回来
            #
            # ⚠️ `seen` 不是为了省事：`被用于` 里写两个同编号的派生名
            #    （例如 `P-<主题>-018` 与 `P-<主题>-018b`）会让同一个块被处理两次，
            #    同一句话印两遍。**报告噪声会训练人忽略整份报告**（LESSONS-general D4）
            #    ⇒ 同一 (条目, 块) 只报一次。
            seen = set()
            for b in used_blocks:
                mnum = PROTO_RE.search(b)
                bn = int(mnum.group(1)) if mnum else None
                if bn in seen:
                    continue
                seen.add(bn)
                # 找到对应块文件
                hit = [nm for n, nm, _ in protos if n == bn]
                if not hit:
                    rep.add("WARN", f"理论链接 {tid}",
                            f"「被用于」写了 {b}，但协议块目录里找不到编号 {bn}")
                    continue
                if tid not in block_links.get(hit[0], set()):
                    rep.add("FAIL", f"理论链接 {tid}",
                            f"{b} 并未在「本块服务于哪条理论条目」里声明 {tid}"
                            "（单向链接不算链接）")
                elif tid in posthoc_links.get(hit[0], set()):
                    # 声明了、但标了事后归因 ⇒ 不算 FAIL，但**必须看得见**。
                    rep.add("INFO", f"理论链接(事后) {tid}",
                            f"{b} 声明服务于 {tid} 但标为「{POSTHOC_MARK}」"
                            "—— 这条链接**不是**事前预注册的（块跑完才逼出该理论条目）；"
                            "引用它时要连这个方向一起说")
            # 判据 2：陈旧
            if newest_proto_mtime is not None and mat == "具体方向":
                mt = theory_path.stat().st_mtime
                lag = (newest_proto_mtime - mt) / 86400.0
                if lag >= 7.0 and not used_blocks:
                    rep.add("WARN", f"理论陈旧 {tid}",
                            f"理论台账落后最新协议块 {lag:.0f} 天且无出口")
        # 判据 3b：块里声明了 T-x，但 T-x 没写回该块
        for nm, ts in block_links.items():
            if tid in ts:
                mnum = PROTO_RE.search(nm)
                bn = int(mnum.group(1)) if mnum else None
                if bn is not None and not any(PROTO_RE.search(b) and
                                              int(PROTO_RE.search(b).group(1)) == bn
                                              for b in used_blocks):
                    rep.add("WARN", f"理论回填 {tid}",
                            f"{nm} 声明服务本条目，但「被用于」里没有这个块号")

        # 判据 5：挂起必须有到期日，且到期必须处置。
        # —— 这是「降级判据」第 4 条（退化的问题转换）的机械形式。
        #
        # 立此检查的实测原因：本仓库的 T-1 在第二次重写后**自己否掉了自己的结论**
        # （正文写着"不要把'保留 ≥2 层'当作可用判据"），然后就这么留在台账里。
        # 三条**入场**降级判据一条都不命中它：①它的证伪条件是实验（不是综述）；
        # ②它要的数字本课题给得出；③它挂起的是"一个还不存在的方法"，不是某条 T- 的结果。
        # ⇒ 于是"降级从不发生"这个病换了个形态又回来了：从"初步观察长期占位"
        #   变成"**自我否定长期占位**"。补的这一条是**续期**判据，不是入场判据。
        #
        # 语义：`挂起（到期 P-n）` 表示 **处置必须在 P-n 这一块内完成**。
        #   ⇒ 只要存在编号 **≥ n** 的协议块而该条仍写着 `挂起`，即逾期 ⇒ FAIL。
        #
        # ⚠️ 为什么是 `>=` 而不是 `>`（本轮实测校准出来的）：守卫是**每轮结束**跑的，
        #    所以"到 P-011 为止必须处置"必须在**跑完 P-011 的那一次守卫**上兑现。
        #    第一版写成 `>`（读作"P-n 是允许挂起的最后一个块"），结果 P-011 出现时
        #    **不报**，要等 P-012 才报 —— 那等于把到期日静默往后挪了一个整块，
        #    而"到期日可以静默顺延"恰恰是这条判据要治的病。
        #    ⇒ 校准方式：临时在真实台账旁放一个 `PROTOCOL-P-<主题>-011.md` 跑守卫，
        #      发现不报；这正是"判据自己可能是空的"（LESSONS-general B2）的又一实例。
        # 到期只有两个选项：重写成能产生**新预测**的表述（→ `可用`），或按规程降级。
        # **"再挂一轮"不是第三个选项。**
        a = AVAILABILITY_RE.search(blob)
        if a is None:
            rep.add("WARN", f"可用性缺失 {tid}",
                    "没有 `可用性:` 字段（应写成 `可用性: 可用`、"
                    "`可用性: 挂起（到期 P-<块号>）` 或 `可用性: 已降级（→ M-<号>）`）"
                    "—— 它是理论台账的必填字段，"
                    "`check_collab_artifacts.py --ledger` 会直接 FAIL")
        elif a.group(1) == "挂起":
            due = DUE_BLOCK_RE.search(a.group(2))
            if due is None:
                rep.add("FAIL", f"挂起无到期 {tid}",
                        "写了「可用性: 挂起」却**没有到期块** —— "
                        "没有到期日的挂起 = 永久免于证伪。"
                        "请补 `（到期 P-<块号>）`，或直接降级")
            else:
                due_num = int(due.group(1))
                past = [(n, nm) for n, nm, _ in protos if n >= due_num]
                if past:
                    rep.add("FAIL", f"挂起逾期 {tid}",
                            f"挂起到期于 P-{due_num:03d}，而 "
                            f"{len(past)} 个协议块（"
                            + ", ".join(f"P-{n}" for n, _ in past[:4])
                            + "）而本条**仍未处置** ⇒ 必须二选一："
                            "① 重写成能产生新预测的表述并把 `可用性` 改回 `可用`；"
                            "② 按 references/theory-ladder.md 的降级规程搬进方法台账。"
                            "**「再挂一轮」不是第三个选项。**")
        elif a.group(1) == "已降级":
            # 降级**不是删除**：条目必须在原位置留下痕迹，而且必须写出去向。
            # 立此检查的失效：若不检查去向，"已降级"就成了一句无成本的咒语 ——
            # 它让条目**免于被追问**，却没有任何东西可核对（与"挂起无到期"同构）。
            #
            # ⚠️ 这里必须是 `elif a.group(1) == "已降级"`，**不能写成 `else`**：
            #    第一版就是 `else`，于是 `可用` 也掉进这个分支，被要求"写去向" ⇒
            #    守卫对一个正常的 `可用性: 可用` 条目报 FAIL。跑一次就看见了。
            if DEMOTED_TO_RE.search(a.group(2)) is None:
                rep.add("FAIL", f"降级无去向 {tid}",
                        "写了「可用性: 已降级」却**没有写去向** —— "
                        "必须写成 `可用性: 已降级（→ M-<号>）`，"
                        "否则读者无从核对内容到底搬去哪了")

        # 判据 4：实验出口跑完了，但条目此后从未被修订
        # —— 这是"证伪条件被触发但未处置"的**代理信号**。
        #
        # ⚠️ 边界要说清楚：**本检查不判定"证伪条件是否真的被触发"**（那需要语义理解）。
        #    它只判定一个可靠的机械事实：**该条目的实验出口已经运行，而理论台账在此之后未被改动**
        #    ⇒ 值得回头确认一次"证伪条件是否已被触发、是否需要按规程重写"。
        #    立此检查的实测原因：本仓库的 T-1 曾被它自己的证伪条件触发，
        #    但条目又挂了一轮没动 —— 证据已否掉条目而条目未动，全靠人碰巧回头看才发现。
        #    因此报 INFO（提示核对），不报 FAIL：出口确认了假设时，条目**确实不需要改**。
        if newest_proto_mtime is not None and used_blocks:
            ex_mtimes = []
            for b in used_blocks:
                mnum = PROTO_RE.search(b)
                bn = int(mnum.group(1)) if mnum else None
                for n, nm2, pth in protos:
                    if n == bn:
                        ex_mtimes.append(pth.stat().st_mtime)
            if ex_mtimes:
                # 用"本条目所在台账文件"的 mtime 做比较：条目级 mtime 无法单独取
                ledger_mt = theory_path.stat().st_mtime
                if ledger_mt < max(ex_mtimes):
                    rep.add("INFO", f"待核对证伪 {tid}",
                            "其实验出口已运行，而本台账在此之后**未被修订** —— "
                            "请确认「什么能证伪」是否已被触发（若已触发，按 "
                            "references/theory-ladder.md 的处置规程重写，而不是删除）")

    # 判据 6：协议块声明了 T-x，而理论台账里没有 T-x ⇒ **悬空引用**。
    # —— 它是 M-6 说的"唯一的检测手段（让产物互相引用）"的**反方向**：
    #    判据 3 只管 T→块，**块→T 这一向此前无人看**。实测风险很具体：
    #    第 20 轮把 T-1 降级时，若直接删掉 `## T-1` 标题，`P-007`/`009`/`011` 的
    #    "本块服务于 T-1"就变成悬空 —— 而**没有任何检查会报**。
    #    ⇒ 降级时"留标题（已降级）+ 写去向"因此不是形式主义，是这条检查的前提。
    #
    # ⚠️ 放在条目循环**外面**：放里面会按条目数重复报同一条。
    for nm, ts in block_links.items():
        for t in sorted(ts):
            if t not in entries:
                rep.add("FAIL", f"悬空理论引用 {t}",
                        f"{nm} 声明服务于 {t}，但理论台账里**没有 {t}** —— "
                        "降级时不要删标题：改成 `可用性: 已降级（→ M-<号>）` 留在原位置，"
                        "或把该块的「本块服务于哪条理论条目」改指到承接条目")

    # 汇总：bridge 目的的真实推进量 = 走完闭环的条目数
    closed = 0
    for tid, blob in entries.items():
        m = FIELD_RE["成熟度"].search(blob)
        u = FIELD_RE["被用于"].search(blob)
        if m and m.group(1) == "具体方向" and u and not u.group(1).strip().startswith("无"):
            closed += 1
    total_dirs = sum(1 for blob in entries.values()
                     if (mm := FIELD_RE["成熟度"].search(blob)) and mm.group(1) == "具体方向")
    rep.add("OK" if closed else "WARN", "理论闭环",
            f"成熟度=具体方向 {total_dirs} 条，其中已有出口 {closed} 条；"
            f"协议块声明链接 {len(block_links)} 块 / {len(declared)} 条 T-")


def detect_fresh_start(charter, entries, protos, decisions):
    """判断"还没开工"——它与"偏离"是两件事，不能都报 FAIL。

    立此判据的原因（实测）：在一个**刚建好 CHARTER、还没有任何台账条目**的新课题上，
    守卫报出 `FAIL 台账 没有找到条目` + `⇒ 已确认偏离`。
    那是**误诊**：项目还没开始 ≠ 走偏了。而"新课题的第一步"必然是这个状态，
    所以不修的话，这套机制在**每个新课题上都会先给人一个假的警报**。

    判据（全部满足才算"未开工"）：
      · CHARTER 存在且能解析出 <goals>
      · 没有任何协议块
      · 台账条目数为 0
      · 没有 DECISIONS.md
    任一条不满足 ⇒ 不是"未开工"，按原规则判定。
    """
    if not charter.exists():
        return False
    if parse_goals(charter) is None:
        return False
    if protos:
        return False
    if entries:
        return False
    if decisions is not None and Path(decisions).exists():
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--charter", required=True)
    ap.add_argument("--ledgers", nargs="+", required=True)
    ap.add_argument("--protocols", nargs="*", default=[])
    ap.add_argument("--decisions", default=None)
    ap.add_argument("--theory-ledger", default=None,
                    help="理论台账路径；给定后审计「理论→实验」闭环（见 references/theory-to-experiment.md）")
    ap.add_argument("--threshold-method", type=int, default=DEFAULT_THRESHOLDS["method"])
    ap.add_argument("--threshold-bridge", type=int, default=DEFAULT_THRESHOLDS["bridge"])
    args = ap.parse_args()

    rep = Report()
    charter = Path(args.charter)
    if not charter.exists():
        rep.add("FAIL", "CHARTER", f"不存在：{charter} —— 没有目标宣言，无法判定偏离")
        return rep.emit()

    goals = parse_goals(charter)
    if goals is None:
        rep.add("FAIL", "CHARTER", "没有 <goals> 块（每行形如 ` - `tag`: 描述 `）")
        return rep.emit()
    if len(goals) < 2:
        rep.add("WARN", "CHARTER",
                f"只声明了 {len(goals)} 个目的。建议至少声明 basis + method（+ bridge）")

    protos = parse_protocols([Path(p) for p in args.protocols])
    entries = parse_ledgers([Path(p) for p in args.ledgers])

    # "还没开工" 与 "偏离" 是两件事 —— 前者不该报 FAIL（见 detect_fresh_start 的说明）
    if detect_fresh_start(charter, entries, protos, args.decisions):
        print("=" * 78)
        print("状态：未开工（CHARTER 已就绪，尚无协议块与台账）")
        print("=" * 78)
        print("OK    目的          " + " / ".join(goals.keys()))
        print("OK    CHARTER       <goals> 可解析")
        print("——    下一步        按工作流：步骤 1 勘察数据现实，建问题台账（>=3 条带证据等级）")
        print("-" * 78)
        print("FAIL 0   WARN 0")
        print("\n⇒ 这是正常起点，不是偏离。先做步骤 1，再回来跑本守卫。")
        return 0

    if not entries:
        rep.add("FAIL", "台账", "没有找到条目（标题应形如 `## M-3 [method] …`）")
        return rep.emit()

    # --- 0. 人面（<headline>）必须"新"且"短" ---
    #
    # 立此判据的实测原因（第 29 轮）：`status.py` 每轮把 <headline> 原样印在一屏顶部，
    # 而**没有任何东西检查它是不是过时的** —— 实测它停在第 27 轮，而第 28/29 轮
    # 已经换掉了头号结论的支持链、还新开了一条理论条目。
    # 这正是本 skill 立文的那个症状：**人读到的"现在在哪"落后于实际进展**。
    #
    # 为什么"提到最新协议块编号"是一个可用的代理信号：它不判定措辞好不好，
    # 只强制"写这段话的人**看过**最新的那个块"。与判据 4 用 mtime 做代理同一思路。
    #
    # 为什么还要限长：一屏的**行数预算可以被一整段话绕过** ——
    # 一段 2000 字的 headline 只算 1 行，预算照样通过，而人读不下去。
    # ⇒ 预算必须同时管"行数"与"单段长度"。
    ct_all = charter.read_text(encoding="utf-8", errors="replace")
    hm = re.search(r"<headline>(.*?)</headline>", ct_all, re.S)
    if not hm:
        rep.add("WARN", "人面", "CHARTER 里没有 <headline> 块 —— 一屏顶部会没有'现在在哪'")
    else:
        head = " ".join(hm.group(1).split())
        if protos:
            newest = max(n for n, _, _ in protos)
            hit = re.search(rf"P-[A-Za-z0-9_\-]*0*{newest}\b", head)
            if hit is None:
                rep.add("FAIL", "人面过时",
                        f"<headline> 没有提到最新的协议块（编号 {newest}）—— "
                        "一屏顶部说的「现在在哪」可能已经落后于实际进展；"
                        "写完新块就把它的一句话结论搬进 <headline>")
        if len(head) > HEADLINE_MAX:
            rep.add("FAIL", "人面过长",
                    f"<headline> {len(head)} 字 > 预算 {HEADLINE_MAX} 字 —— "
                    "行数预算可以被一整段话绕过（一段只算 1 行），所以单段也要限长；"
                    "把历史轮次挪出 <headline>，只留'现在在哪 / 下一步 / 要你决定什么'")

    # --- 1. tag 覆盖率 ---
    untagged = [e for e in entries if not e["tag"]]
    if untagged:
        rep.add("WARN", "台账 tag",
                f"{len(untagged)}/{len(entries)} 条没有 [goal] 标记，无法对账："
                + ", ".join(e["id"] for e in untagged[:6]))
    bad = [e for e in entries if e["tag"] and e["tag"] not in goals]
    if bad:
        rep.add("FAIL", "台账 tag",
                f"{len(bad)} 条用了未声明的目的标记 "
                + ", ".join(sorted({e['tag'] for e in bad}))
                + "；请在 CHARTER 里声明或改标记")

    per_goal = {}
    for g in goals:
        per_goal[g] = [e for e in entries if e["tag"] == g]
    # "声明了目的却零入账" 的等级取决于项目进度：
    #   块数 < EARLY_BLOCKS ⇒ WARN（早期本来就来不及每个目的都有入账）
    #   块数 >= EARLY_BLOCKS ⇒ FAIL（跑了这么多块，某个目的还是零，那是真没推进）
    # 立此分级的实测原因：新课题开工后跑守卫，basis/bridge 因"零入账"直接 FAIL，
    # 但那时项目才刚开始 —— 与"未开工误诊"是同一个根因的两种表现。
    EARLY_BLOCKS = 3
    early = len(protos) < EARLY_BLOCKS
    for g in goals:
        n = len(per_goal[g])
        if n:
            rep.add("OK", f"目的 {g}", f"{n} 条台账条目")
        else:
            rep.add("WARN" if early else "FAIL", f"目的 {g}",
                    f"{n} 条台账条目 —— 声明了目的却零入账"
                    + ("（项目早期，先记 WARN）" if early else ""))

    # --- 2. 配比与"最近一次推进" ---
    protos = parse_protocols([Path(p) for p in args.protocols])
    if not protos:
        rep.add("WARN", "协议块", "没有找到协议块，无法按块计时")
    else:
        latest_num = protos[-1][0]
        rep.add("OK", "协议块", f"{len(protos)} 块，最高编号 {latest_num}"
                + f"（{protos[-1][1]}）")

    # 用 mtime 排序把条目映射到"块区间"太脆弱；改用更稳的口径：
    # 每个目的的"最新条目 mtime" vs "最新协议块 mtime"
    if protos:
        newest_proto = max(p[2].stat().st_mtime for p in protos)
        for g in goals:
            if not per_goal[g]:
                continue
            newest_entry = max(e["mtime"] for e in per_goal[g])
            lag_days = (newest_proto - newest_entry) / 86400.0
            thr = args.threshold_method if g == "method" else args.threshold_bridge
            if lag_days > 0 and lag_days >= max(1.0, thr / 2.0):
                rep.add("WARN", f"陈旧 {g}",
                        f"该目的最新台账条目落后最新协议块 {lag_days:.1f} 天"
                        f"（阈值 {max(1.0, thr/2.0):.1f}）")

    # --- 3. 偏离检测：分两问，并把"假阳性"显式排除 ---
    #
    # 问一（管"最近有没有动"）：`method` / `bridge` 的最近台账条目是否比最新协议块更新？
    #   这两个才是会被工程挤掉的目的。落后超过阈值 ⇒ FAIL。
    # 问二（管"动的次数"）：两个目的各自距离最新块隔了几块没有入账 ⇒ 超阈值 WARN。
    #
    # ⚠️ 为什么不对 `basis` 做 FAIL：本会话实测到一个**假阳性**——
    #   补做追溯性文档（把缺口补齐、把悬空引用修好）会让台账 mtime **晚于**所有旧块，
    #   而那个"差距"衡量的是"块有多新"，不是"basis 被搁置"。
    #   故 `basis` 的差距只作信息报出，不阻塞。
    # ⚠️ 剩余的已知假阳性风险：把历史块**追溯性**补上 `[goal]` 标记，可以掩盖当时的静默。
    #   守卫不能区分"当时就打了标记"与"事后补的"。这是**已知局限**，不是可修的 bug——
    #   降低它的唯一办法是降低补标记的必要性（即一开始就别跳过闸门）。
    if protos:
        newest_block_mtime = max(p[2].stat().st_mtime for p in protos)
        enforce = {"method", "bridge"}
        for g in goals:
            es = per_goal[g]
            if not es:
                continue
            newest_entry = max(e["mtime"] for e in es)
            gap_after = [p for p in protos if p[2].stat().st_mtime > newest_entry]
            thr = args.threshold_method if g == "method" else args.threshold_bridge
            lvl = "FAIL" if (g in enforce and len(gap_after) >= thr) else "WARN"
            if len(gap_after) >= thr:
                ids = ", ".join(f"P-{p[0]}" for p in sorted(gap_after))
                if g in enforce:
                    rep.add(lvl, f"偏离 {g}",
                            f"最新台账条目之后又有 {len(gap_after)} 个协议块"
                            f"（{ids}）未给该目的入账（阈值 {thr}）")
                else:
                    rep.add("INFO", f"计数 {g}",
                            f"该目的最后一次入账后又有 {len(gap_after)} 个块（{ids}）"
                            f"—— 该目的**不阻塞**，此处仅报出供人判断")
            else:
                rep.add("OK", f"目的 {g} 新鲜度",
                        f"最后一次入账后仅 {len(gap_after)} 个新块（阈值 {thr}）")

    # 反向问：有没有"块比条目新很多、但该目的其实刚被推进"的错配（信息性）
    if protos:
        newest_block_mtime = max(p[2].stat().st_mtime for p in protos)
        for g in goals:
            if not per_goal[g]:
                continue
            newest_entry = max(e["mtime"] for e in per_goal[g])
            if newest_entry > newest_block_mtime:
                lag_days = (newest_entry - newest_block_mtime) / 86400.0
                if lag_days >= 1.0:
                    rep.add("INFO", f"追溯性入账 {g}",
                            f"该目的最新条目比最新协议块还新 {lag_days:.1f} 天"
                            "—— 说明是**事后补记**，不计入偏离判定")

    # --- 4. 决策日志 ---
    if args.decisions:
        dp = Path(args.decisions)
        rep.add("OK" if dp.exists() else "WARN", "决策日志",
                str(dp) if dp.exists() else f"不存在：{dp}（封存/撤销这类状态变化无处记录）")

    # --- 5. 理论 → 实验 的闭环审计 ---
    if args.theory_ledger:
        audit_theory_loop(Path(args.theory_ledger), protos, rep)

    # --- 6. 目的数与实操面的配比（信息性） ---
    if goals:
        tot = len(entries)
        line = "  ".join(f"{g}={len(per_goal[g])}" for g in goals)
        rep.add("OK", "配比", f"台账条目 {tot} 条：{line}")

    return rep.emit()


if __name__ == "__main__":
    sys.exit(main())
