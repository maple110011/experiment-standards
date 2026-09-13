#!/usr/bin/env python3
"""collab-lab 产物校验器.

摘要卡的价值全在"预算"上：字段齐全、长度卡死、结尾恰好一个问题。这些要求
靠自觉守不住（写起来总是会多写一点），所以用脚本守。

用法
----
    # 校验摘要卡
    python scripts/check_collab_artifacts.py --digest <path/to/DIGEST-xxx.md>

    # 校验协议块
    python scripts/check_collab_artifacts.py --protocol <path/to/PROTOCOL-xxx.md>

    # 校验台账
    python scripts/check_collab_artifacts.py --ledger <path/to/LEDGER-methods.md>

    # 一次校验多个
    python scripts/check_collab_artifacts.py --digest a.md --protocol b.md --ledger c.md

    # 自检：用本 skill 自带的模板跑一遍（应全部通过）
    python scripts/check_collab_artifacts.py --self-test

退出码: 0 = 全部通过; 1 = 有 FAIL。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

# 子进程调用一律走这一处（它强制 UTF-8、并把解码失败降级为报错而非崩溃）。
# 立此 import 的失效：本脚本的 --self-test 曾因读取 fixtures 的 GBK 中文输出而
# UnicodeDecodeError → r.stdout=None → AttributeError → **整个自检带 traceback 死掉**。
sys.path.insert(0, str(Path(__file__).resolve().parent))
import subproc  # noqa: E402

# 台账字段的语法只有一处定义（在 goal_guard.py 里），这里 import 而不是抄一份。
# 理由同 status.py：两个脚本消费同一份台账文本时，副本会**静默分裂** ——
# 改了一边，另一边照样跑、照样输出，只是那一栏悄悄失效。
# 本脚本新增「可用性」检查时正是靠这条避免了再抄一份正则。
from goal_guard import AVAILABILITY_RE, DUE_BLOCK_RE, DEMOTED_TO_RE  # noqa: E402

# --------------------------------------------------------------------------- #
# 预算
# --------------------------------------------------------------------------- #
CONCLUSION_BUDGET = 40          # 结论正文最多多少字
COMPARE_ROW_BUDGET = 4          # 对比表格最多多少数据行
SURPRISE_BUDGET = 3             # 意外最多几条
MECHANISM_BUDGET = 3            # 机制最多几条
BLOCKER_BUDGET = 3              # 堵点最多几条
OPEN_BUDGET = 3                 # 开放最多几条
OPTION_MIN, OPTION_MAX = 2, 4   # 待你回答的互斥选项数

# 机制三分类：每条机制必须命中恰好一个
MECHANISM_KINDS = ("实现问题", "调参问题", "方法本身的性质")
MECHANISM_ALIASES = {
    "实现": "实现问题", "代码": "实现问题", "实现问题": "实现问题",
    "调参": "调参问题", "超参": "调参问题", "调参问题": "调参问题",
    "方法本身的性质": "方法本身的性质", "方法性质": "方法本身的性质",
    "方法本身": "方法本身的性质",
}

STRENGTH_TAGS = ("强", "薄", "不稳", "?")

# --------------------------------------------------------------------------- #
# 通用解析
# --------------------------------------------------------------------------- #
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s*(?:\d+[.、]\s*)?(.+?)\s*$")
BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
OPTION_RE = re.compile(r"^\s*[-*+]\s*\[\s*[ xX]?\s*\]\s*(.+)$")
TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]+\|[\s:|-]*$")


class Report:
    def __init__(self, kind: str, path: Path):
        self.kind = kind
        self.path = path
        self.fails: list[str] = []
        self.notes: list[str] = []

    def fail(self, field: str, msg: str) -> None:
        self.fails.append(f"[{field}] {msg}")

    def note(self, msg: str) -> None:
        self.notes.append(msg)

    def emit(self) -> bool:
        ok = not self.fails
        tag = "PASS" if ok else "FAIL"
        print(f"{tag}  {self.kind}: {self.path}")
        for f in self.fails:
            print(f"      x {f}")
        for n in self.notes:
            print(f"      - {n}")
        return ok


def parse_sections(text: str) -> dict[str, list[str]]:
    """按标题切分。键是去掉编号与空格的标题名，值是正文行列表。"""
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        m = HEADING_RE.match(line)
        if m:
            name = re.sub(r"\s+", "", m.group(1))
            # 去掉 "字段：" 这类行尾冒号
            name = name.rstrip("：:")
            current = name
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)
    return sections


def find_key(sections: dict[str, list[str]], *candidates: str,
             prefix: bool = False) -> str | None:
    for cand in candidates:
        if cand in sections:
            return cand
    if prefix:
        for key in sections:
            for cand in candidates:
                if key.startswith(cand):
                    return key
    return None


def body_lines(lines: list[str]) -> list[str]:
    """去掉空行。"""
    return [ln.rstrip() for ln in lines if ln.strip()]


def bullet_items(lines: list[str]) -> list[str]:
    """取出列表项（含续行折叠）。若无列表项，把非空行整体当一条。"""
    items: list[str] = []
    for ln in lines:
        m = BULLET_RE.match(ln)
        if m:
            items.append(m.group(1).strip())
        elif ln.strip() and items:
            items[-1] = items[-1] + " " + ln.strip()
        elif ln.strip():
            items.append(ln.strip())
    return items


def table_rows(lines: list[str]) -> list[list[str]]:
    """返回表格数据行（排除表头与分隔行）。"""
    rows = []
    seen_sep = False
    for ln in lines:
        if "|" not in ln:
            continue
        if TABLE_SEP_RE.match(ln):
            seen_sep = True
            continue
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if not seen_sep:
            continue  # 表头
        rows.append(cells)
    return rows


FENCE_RE = re.compile(r"```.*?```", re.S)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")


def strip_code(text: str) -> str:
    """去掉围栏代码块与行内代码。

    代码片段里出现 <path> 这类写法是正常的（它是命令行占位符），不应被当成
    未填写的模板占位符。先剥掉代码，再检查正文。
    """
    return INLINE_CODE_RE.sub(" ", FENCE_RE.sub(" ", text))


def looks_like_placeholder(text: str) -> bool:
    """检测未填写的模板占位符。

    **两次真实误报换来的教训**：裸 `<` / `>` 不能当占位符信号。
    - 数学里到处都是：`ΔFPR < −0.05`、`内存 < 2 GB`、`方差 < 中位`；
    - 跨行匹配更糟：一个数学 `<` 会一路匹配到几十行后的某个 `>`，
      把整段正文当成"占位符"，报出的上下文完全无法定位。

    因此只在"尖括号紧贴一个非空描述、且不跨行"时才判定为占位符。
    宁可漏报也**不可误报** —— 会误报的校验器会被使用者学会忽略。
    """
    clean = strip_code(text)
    # 单行内、描述非空、且描述里不含明显是数学/比较的写法
    return bool(re.search(r'<[^<>\n]{2,40}>', clean))


GRADE_RE = re.compile(r"等级[:：]\s*(稳定|薄|不稳|\?)")
REPRO_RE = re.compile(r"复现[:：]\s*(.+)")


def grade_of(blob: str) -> str | None:
    """只从「等级」字段取值。

    不能在整块里搜关键词：像「推翻条件: …仍能稳定复现」这样的正文会误命中，
    造成假报警。校验器误报比不报更糟，因为它会训练人忽略它。
    """
    m = GRADE_RE.search(blob)
    return m.group(1) if m else None


def repro_count(blob: str) -> int | None:
    m = REPRO_RE.search(blob)
    if not m:
        return None
    val = m.group(1).strip()
    m2 = re.search(r"(\d+)", val)
    if m2:
        return int(m2.group(1))
    if re.match(r"^\s*(一|单次)", val):
        return 1
    if re.match(r"^\s*(两|二)", val):
        return 2
    return None


# --------------------------------------------------------------------------- #
# 摘要卡
# --------------------------------------------------------------------------- #
DIGEST_FIELDS = {
    "conclusion": ("结论", "一句话结论"),
    "compare": ("对比",),
    "surprise": ("意外",),
    "mechanism": ("机制",),
    "blocker": ("堵点",),
    "open": ("开放", "开放问题"),
    "decision": ("决策卡",),
    "question": ("待你回答", "待回答"),
}


def check_digest(path: Path) -> bool:
    rep = Report("摘要卡", path)
    text = path.read_text(encoding="utf-8")
    sections = parse_sections(text)

    if looks_like_placeholder(text):
        rep.fail("模板占位符", "仍含 <...> 占位符，未填写")

    found = {}
    for key, cands in DIGEST_FIELDS.items():
        hit = find_key(sections, *cands, prefix=True)
        if hit is None:
            rep.fail("字段缺失", f"缺少标题「{cands[0]}」")
        else:
            found[key] = hit

    # --- 结论 ---
    if "conclusion" in found:
        lines = body_lines(sections[found["conclusion"]])
        if not lines:
            rep.fail("结论", "为空")
        else:
            # 结论正文 = 去掉 "[强] " 这类标签前缀
            body = re.sub(r"^\s*[\[【(（]?\s*(强|薄|不稳|\?)\s*[\]】)）]?\s*[:：]?\s*", "", lines[0])
            n = len(re.sub(r"\s", "", body))
            if n == 0:
                rep.fail("结论", "标签之外没有内容")
            elif n > CONCLUSION_BUDGET:
                rep.fail("结论", f"{n} 字，超出预算 {CONCLUSION_BUDGET} 字")
            if not re.search(r"[\[【(（]?\s*(强|薄|不稳|\?)\s*[\]】)）]?", lines[0]):
                rep.fail("结论", f"缺强度标签（只能填 {'/'.join(STRENGTH_TAGS)}）")

    # --- 对比 ---
    if "compare" in found:
        rows = table_rows(sections[found["compare"]])
        if not rows:
            rep.fail("对比", "没有表格数据行")
        elif len(rows) > COMPARE_ROW_BUDGET:
            rep.fail("对比", f"{len(rows)} 行，超出预算 {COMPARE_ROW_BUDGET} 行")
        else:
            for i, cells in enumerate(rows, 1):
                if len(cells) < 5:
                    rep.fail("对比", f"第 {i} 行只有 {len(cells)} 列，需要 5 列"
                                     "（对象|基线|本次|效应量|不确定度）")
                elif not re.search(r"\d", cells[4]):
                    rep.fail("对比", f"第 {i} 行的「不确定度」列没有数字")

    # --- 意外 ---
    if "surprise" in found:
        items = bullet_items(sections[found["surprise"]])
        if not items:
            rep.fail("意外", "为空")
        elif len(items) > SURPRISE_BUDGET:
            rep.fail("意外", f"{len(items)} 条，超出预算 {SURPRISE_BUDGET} 条")
        for it in items:
            if re.fullmatch(r"[无没]?[。.\s]*", it) or it.strip() in ("无", "None"):
                rep.fail("意外", "写「无」时必须同时说明覆盖面，例如「无（覆盖 X/Y，未检查 Z）」")

    # --- 机制（三分类） ---
    if "mechanism" in found:
        items = bullet_items(sections[found["mechanism"]])
        if not items:
            rep.fail("机制", "为空")
        elif len(items) > MECHANISM_BUDGET:
            rep.fail("机制", f"{len(items)} 条，超出预算 {MECHANISM_BUDGET} 条")
        for i, it in enumerate(items, 1):
            hits = {MECHANISM_ALIASES[a] for a in MECHANISM_ALIASES if a in it}
            if not hits:
                rep.fail("机制", f"第 {i} 条没有标注分类"
                                 f"（必须命中：{'、'.join(MECHANISM_KINDS)}）")
            elif len(hits) > 1:
                rep.fail("机制", f"第 {i} 条同时命中多个分类 {sorted(hits)}，必须只选一个")

    # --- 堵点 ---
    if "blocker" in found:
        items = bullet_items(sections[found["blocker"]])
        if not items:
            rep.fail("堵点", "为空")
        elif len(items) > BLOCKER_BUDGET:
            rep.fail("堵点", f"{len(items)} 条，超出预算 {BLOCKER_BUDGET} 条")
        for i, it in enumerate(items, 1):
            if not re.search(r"排除|已排|未见|不是", it):
                rep.fail("堵点", f"第 {i} 条没有「已排除」信息（堵点必须写明排除过什么）")

    # --- 开放 ---
    if "open" in found:
        items = bullet_items(sections[found["open"]])
        if len(items) > OPEN_BUDGET:
            rep.fail("开放", f"{len(items)} 条，超出预算 {OPEN_BUDGET} 条")
        for i, it in enumerate(items, 1):
            if not re.search(r"解决|检验|查|测|验证|问", it):
                rep.fail("开放", f"第 {i} 条没有「什么能解决它」")

    # --- 决策卡 ---
    if "decision" in found:
        lines = body_lines(sections[found["decision"]])
        blob = "\n".join(lines)
        for must in ("自荐", "理由", "风险"):
            if must not in blob:
                rep.fail("决策卡", f"缺少「{must}」行")
        if not re.search(r"GO|NO-GO|换方向|补", blob, re.IGNORECASE):
            rep.fail("决策卡", "「自荐」没有给出 GO / NO-GO / 换方向 / 补实验 之一")

    # --- 待你回答：恰好一个问题 + 互斥选项 ---
    if "question" in found:
        lines = sections[found["question"]]
        qmarks = sum(ln.count("？") + ln.count("?") for ln in lines)
        options = [m.group(1) for ln in lines if (m := OPTION_RE.match(ln))]
        if qmarks == 0:
            rep.fail("待你回答", "没有问句（必须以一个问题结尾）")
        elif qmarks > 1:
            rep.fail("待你回答", f"有 {qmarks} 个问号；恰好只能有一个问题")
        if not (OPTION_MIN <= len(options) <= OPTION_MAX):
            rep.fail("待你回答",
                     f"{len(options)} 个选项，需要 {OPTION_MIN}–{OPTION_MAX} 个互斥选项"
                     "（用 `- [ ]` 列出）")
        else:
            rec = [o for o in options if "推荐" in o]
            if len(rec) > 1:
                rep.fail("待你回答", "有多个选项标了「推荐」")
        # 摘要卡末尾必须就是这一节
        keys = list(sections.keys())
        if keys and keys[-1] != found["question"]:
            rep.fail("待你回答", f"不是最后一节（当前最后是「{keys[-1]}」）")

    return rep.emit()


# --------------------------------------------------------------------------- #
# 协议块
# --------------------------------------------------------------------------- #
PROTOCOL_FIELDS = (
    ("block_id", ("块号", "编号")),
    ("claim", ("一句话主张", "主张")),
    ("why", ("为什么是这一步", "为什么")),
    ("evidence", ("既有证据", "现有证据")),
    ("metric", ("主指标",)),
    ("mde", ("最小可检测效应", "可检测效应")),
    ("control", ("对照",)),
    ("success", ("成功判据",)),
    ("failure", ("失败判据",)),
    ("no_claim", ("绝不能声称", "不能声称")),
    ("stop", ("停止规则",)),
    ("cost", ("预期成本", "成本")),
)


def check_protocol(path: Path) -> bool:
    rep = Report("协议块", path)
    text = path.read_text(encoding="utf-8")
    sections = parse_sections(text)

    if looks_like_placeholder(text):
        rep.fail("模板占位符", "仍含 <...> 占位符，未填写")

    found = {}
    for key, cands in PROTOCOL_FIELDS:
        hit = find_key(sections, *cands, prefix=True)
        if hit is None:
            rep.fail("字段缺失", f"缺少「{cands[0]}」")
        else:
            found[key] = hit
            if not body_lines(sections[hit]):
                rep.fail(cands[0], "为空")

    if "metric" in found:
        body = "\n".join(body_lines(sections[found["metric"]]))
        if not re.search(r"[=＝]|公式|/|logit|TP|FP|Recall|FPR|AUC|RMSE|ECE", body):
            rep.fail("主指标", "没有给出计算口径（只写了指标名不算）")

    if "mde" in found:
        body = "\n".join(body_lines(sections[found["mde"]]))
        if not re.search(r"\d", body):
            rep.fail("最小可检测效应", "没有数字；须来自 score_noise_floor.py")
        if re.search(r"^\s*(有提升|变好|更好|明显)\s*$", body.strip()):
            rep.fail("最小可检测效应", "写成了形容词")

    if "success" in found and "failure" in found:
        s = "\n".join(body_lines(sections[found["success"]]))
        f = "\n".join(body_lines(sections[found["failure"]]))
        if not re.search(r"\d", s):
            rep.fail("成功判据", "没有数值判据")
        if not re.search(r"\d", f):
            rep.fail("失败判据", "没有数值判据")

    # 第 3 档（无来源）决定必须分流：可扫的做敏感性扫描，不可扫的才问人。
    #
    # 立此检查的实测原因：这条规则先是写在 references/literature-grounding.md 里的一句话，
    # 而**只在文档里的规则不会被执行**。本仓库实测收益：对两项第 3 档决定做扫描，
    # 不仅回答了"选择重要吗"，还**推翻了一条已入账的结论**
    # （原写"方向稳定为正"，而逐折中位在 4/5 个设置下为负）。
    # ⇒ 所以它需要一个**字段**才可能被机械检查。
    tier3_rows = []
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 3 and re.fullmatch(r"\*{0,2}3\*{0,2}", cells[2]):
            tier3_rows.append(cells[0])
    if tier3_rows:
        has_triage = re.search(r"第\s*3\s*档决定的分流", text) is not None
        if not has_triage:
            rep.fail("第3档分流", f"有 {len(tier3_rows)} 行第 3 档决定，但缺少"
                                  "「第 3 档决定的分流」一节（可扫 / 不可扫）")
        else:
            # 分流表里每行必须给出小类
            triage_ok = 0
            for line in text.splitlines():
                if not line.strip().startswith("|"):
                    continue
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cells) >= 2 and re.search(r"可扫|不可扫", cells[1]):
                    triage_ok += 1
            if triage_ok == 0:
                rep.fail("第3档分流", "分流表里没有任何行标出「可扫 / 不可扫」")
            # 标为"可扫"的必须有扫描范围
            for line in text.splitlines():
                if not line.strip().startswith("|"):
                    continue
                cells = [c.strip() for c in line.strip().strip("|").split("|")]
                if len(cells) >= 3 and cells[1].strip() == "可扫":
                    if not re.search(r"\d", cells[2]):
                        rep.fail("第3档分流",
                                 f"「{cells[0][:24]}」标为可扫，但没写扫描范围（需含数字）")

    # ---- `预注册:` 必填；声明了稀缺资源就必有 `杠杆上界:` ----
    # 见 assets/templates/PROTOCOL.template.md 顶部三行的说明。
    if re.search(r"^预注册[:：]\s*\S", text, re.M) is None:
        rep.fail("预注册声明", "缺 `预注册:` 一行（`事前` 或 `事后（原因）`）——"
                               "否则从文件本身看不出这个块是不是事前预注册的")
    res = re.search(r"^稀缺资源[:：]\s*(\S.*)$", text, re.M)
    if res is None:
        rep.fail("稀缺资源声明", "缺 `稀缺资源:` 一行（没有就写 `无`）—— 它决定要不要写杠杆上界")
    else:
        val = res.group(1).strip().strip('*`')
        if not val.startswith("无"):
            lev = re.search(r"^杠杆上界[:：]\s*(\S.*)$", text, re.M)
            if lev is None or not lev.group(1).strip():
                rep.fail("杠杆上界缺失",
                         f"声明了稀缺资源（`{val[:30]}`）却没有 `杠杆上界:` —— "
                         "**在花稀缺资源之前，先答『它最多能换来多少』**")

    # ---- 多档判据：必须写出**优先级与互斥性** ----
    # 立此检查的失效（第 22 轮 `P-BOILER-012` 实测）：
    # 那份预注册写了三档 O1/O2/O3，实测结果落在**档与档之间的缝**里 ——
    # 三口径都 <0.50（O2 的前半），但 |ΔAUC| = 0.038 ≥ 0.03（O2 的后半不满足），
    # 而 LOO 区间 [0.305, 0.473] **不跨 0.5**（O3 的前半也不满足）。
    # ⇒ 档与档既不互斥也不穷尽，**"哪一档成立"由解释者决定** ——
    #    这是"判据自己可能是空的"（`M-8` / B2）的第三种形态：
    #    不是判据没写，而是**多档之间没有排好**。
    # 修法不是"下次写仔细点"（那是文档纪律），而是**强制写一行**
    # `判据优先级:`，把顺序与互斥条件显式化 —— 写不出来就说明还没想清。
    tiers = sorted({int(m) for m in re.findall(r"\bO([1-9])\b", text)})
    if len(tiers) >= 2:
        if not re.search(r"^判据优先级[:：]", text, re.M):
            rep.fail("多档判据",
                     f"文中有 {len(tiers)} 档判据（{'/'.join('O%d' % t for t in tiers)}），"
                     "但没有 `判据优先级:` 一行。多档必须写清"
                     "**① 谁优先 ② 各档条件是否互斥且穷尽** ——"
                     "否则实测落在缝里时，结论会由解释者决定（本 skill 的首个实例上实测过）")

    return rep.emit()


# --------------------------------------------------------------------------- #
# 台账（三级：问题 Q / 方法 M / 理论 T）
# --------------------------------------------------------------------------- #
LEDGER_FIELDS = {
    "problem": ("证据", "等级", "事实", "影响", "被用于", "什么能改"),
    "methods": ("等级", "主张", "适用边界", "复现", "被用于", "推翻条件"),
    "theory": ("现象", "证据", "缺口", "理论问题", "成熟度", "可用性", "被用于"),
}

# 理论台账的成熟度分级：越成熟，硬性要求越高
MATURITY_RE = re.compile(r"成熟度[:：]\s*(初步观察|可研究的问题|具体方向)")
MATURITY_LEVEL = {"初步观察": 0, "可研究的问题": 1, "具体方向": 2}

# 「可用性」字段的两个正则（AVAILABILITY_RE / DUE_BLOCK_RE）从 goal_guard import，
# 见文件头的说明 —— 此处**不要**再定义一份。

ENTRY_RE = re.compile(r"^\s{0,3}#{2,4}\s*([QMT]-\d+)\b(.*)$")


def ledger_kind(path: Path) -> str:
    """从文件名判定台账种类。理论台账用 theory / T- 前缀。"""
    name = path.name.lower()
    if "theor" in name:
        return "theory"
    if "method" in name:
        return "methods"
    return "problem"


def check_package(path: Path) -> bool:
    """一个**产出包**必须只有一个入口，且入口把包里其余文件都点名。

    治的是用户最初那句话里最直白的一条：**"五分钟内知道发生了什么、下一步做什么"**。

    实测（第 35 轮）：同一个任务，没有 skill 的那一臂交了 **2 个文件**，
    有 skill 的那一臂交了 **9 个文件**（CHARTER / 3 个台账 / 协议块 / 决策日志 / 救援清单 / 摘要卡）。
    九个文件本身不是错 —— **但"哪个先读"这件事当时没有任何东西规定**，
    于是"更完整"直接变成了"接手更慢"，而 skill 的验收标准 #1 恰恰就是**五分钟测试**。
    ⇒ 机制：包必须**收口到一个入口**，入口必须**把其余文件点名**（人只读入口就知道包里有什么、
    每个是干嘛的），入口自身还要过摘要卡的全部检查。

    三条规则（都可机械核对）：
    1. **恰好一个入口**：`DIGEST-*.md`（或 `ENTRY.md`）。0 个 ⇒ FAIL；
       ≥2 个 ⇒ FAIL —— **两个入口等于没有入口**。
    2. 入口必须**通过摘要卡检查**（字段、预算、恰好一个问题）。
    3. 包里**其余每个文件都必须被入口点名**（按文件名出现即可）——
       没被点名的文件就是"人不会知道它存在"的文件。
    """
    rep = Report("产出包", path)
    files = [p for p in sorted(path.rglob("*")) if p.is_file()]
    if not files:
        rep.fail("产出包", "目录里没有任何文件")
        return rep.emit()
    entries = [p for p in files if p.name.startswith("DIGEST-") or p.name == "ENTRY.md"]
    if not entries:
        rep.fail("入口", f"包里没有入口（应有 1 个 `DIGEST-*.md` 或 `ENTRY.md`）—— "
                         f"现在有 {len(files)} 个文件平级摆着，人不知道该先读哪个")
        return rep.emit()
    if len(entries) > 1:
        rep.fail("入口", f"包里有 {len(entries)} 个入口（{', '.join(e.name for e in entries)}）"
                         "—— **两个入口等于没有入口**，请只留一个")
        return rep.emit()
    entry = entries[0]
    text = entry.read_text(encoding="utf-8", errors="replace")
    # 规则 2：入口自己要过摘要卡检查
    if not check_digest(entry):
        rep.note(f"入口 {entry.name} 未通过摘要卡检查（上面那一段就是它）")
    # 规则 3：其余文件必须被点名
    others = [p for p in files if p != entry]
    unnamed = [p for p in others if p.name not in text and str(p.relative_to(path)) not in text]
    if unnamed:
        rep.fail("入口点名", f"{len(unnamed)}/{len(others)} 个文件没有被入口点名"
                             f"（{', '.join(p.name for p in unnamed[:6])}）—— "
                             "没被点名的文件，人不会知道它存在")
    else:
        rep.note(f"入口点名了其余 {len(others)} 个文件")
    if len(files) > 6:
        rep.note(f"包里有 {len(files)} 个文件（>6）⇒ 入口必须真的**收口**："
                 "人只读入口就能说出发生了什么、下一步选什么")
    return rep.emit()


def check_workspace_entry(path: Path) -> bool:
    """**工作区也要有一个入口** —— 而且它必须把根目录的每份活文档点名。

    与 `check_package` 同源，但**尺度不同**：
    - 交付包（`--package`）：包里每个文件都要被点名；
    - 工作区（本函数）：根目录的**每份 `.md`** 都要被点名
      （工作区里还有几百个产物文件，那不是给人逐份读的 —— 那些归 `INDEX.md` 管）。

    立此的实测原因（第 36 轮）：这个工作区的根目录有 **6 份 `.md` 抢着当入口**
    （`LESSONS-general.md` 1482 行、`MAP.md` 934 行、`LESSONS-boiler.md` 515 行、
    `INDEX.md` 231 行、`CHARTER.md` 91 行、`DECISIONS.md` 62 行），
    而**没有任何东西规定先读哪个** —— 这正是本 skill 立文那句话在工作区尺度的形态：
    "我会逐渐丧失对内容的把握。"
    ⇒ 一份 1482 行的"经验记录"和一个 91 行的章程平级摆着，人只会都不读。

    三条规则（都可机械核对）：
    1. 入口必须点名根目录**其它每一份 `.md`**（没被点名的 = 人不会知道它存在）；
    2. 入口必须有一行**声明先读哪个**（该行同时出现「先读」与某个被点名文档的名字）；
    3. 入口 ≤ **120 行**（一屏×3；长了就退回它要治的那个病）。
    """
    if not path.exists():
        return _missing(path)
    rep = Report("工作区入口", path)
    root = path.parent
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    others = [p for p in sorted(root.glob("*.md")) if p.resolve() != path.resolve()]
    if not others:
        rep.note("根目录没有其它 .md（这份入口暂时没有要索引的东西）")
    unnamed = [p for p in others if p.name not in text]
    if unnamed:
        rep.fail("入口点名", f"{len(unnamed)}/{len(others)} 份根目录文档没有被入口点名"
                             f"（{', '.join(p.name for p in unnamed[:6])}）—— "
                             "没被点名 = 人不会知道它存在")
    else:
        rep.note(f"入口点名了根目录其余 {len(others)} 份 .md")
    first = [ln for ln in lines if "先读" in ln and any(p.name in ln for p in others)]
    if not first:
        rep.fail("先读哪个", "入口里没有一行同时出现「先读」与某份被点名文档的名字 —— "
                             "有入口但没告诉人**从哪开始**，等于把选择又推回给人")
    else:
        rep.note(f"先读声明：{first[0].strip()[:60]}")
    if len(lines) > 120:
        rep.fail("入口长度", f"{len(lines)} 行 > 120 行 —— 入口长了就退回它要治的那个病"
                             "（再写一份长文档）；细节放到被它点名的文件里去")
    return rep.emit()


def check_decisions(path: Path) -> bool:
    """决策日志：**"等你"的行必须写成一张能决策的卡**。

    治的是用户最初的诉求里最后一个没有机械约束的口子：
    > "我看不懂 agent 要求我抉择的选项。"

    实测（第 31 轮）：`DECISIONS.md` 里那条唯一的待决定，只有
    「决定 + 理由 + 状态」三样。人想知道的三件事**一件都没写**：
    **我会拿到什么 / 我要花什么 / 什么必须先成立**。
    而理由栏里写的是"信息量大" —— 那是 agent 的判断，不是给人算账的信息。

    ⇒ 规则（与"决策卡"在摘要卡里的要求同源）：
    - 状态含 `等你` 的行 ⇒ 三列必须写实（非空、非 `—`）；
      且「你会拿到什么」必须含一个**可核对的读数**（数字，或明确的「打平 / 无信息」）；
    - 其余行 ⇒ 三列写 `—`（不是等人决定的，不需要给人算账）；
    - 状态含 `等你` 的行**还必须**能被一屏单独认出来 ⇒ 见 `status.py`。
    """
    rep = Report("决策日志", path)
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    # ⚠️ **只看"决策表"那一张表，不是文件里所有 `|` 行。**
    #    实测（第 31 轮，被"出厂模板"fixture 当场抓到）：模板里除决策表外还有
    #    "状态取值含义"表与"三件套"表 —— 第一版把每个 `|` 行都当决策行，
    #    于是那两张表全被报成"列数不足"。
    #    与 `status.py` 的"项目符号续行"是同一类缺陷：**判定要以"表"为单位，不是以"行"为单位。**
    hdr_i = None
    for i, ln in enumerate(lines):
        if ln.startswith("|") and "决定" in ln and "状态" in ln:
            hdr_i = i
            break
    if hdr_i is None:
        rep.fail("决策日志", "找不到决策表（表头须含「决定」与「状态」两列）")
        return rep.emit()
    header = [c.strip() for c in lines[hdr_i].strip("|").split("|")]
    body: list[str] = []
    for ln in lines[hdr_i + 2:]:
        if not ln.startswith("|"):
            break
        body.append(ln)
    need = ("你会拿到什么", "你要花什么", "前置条件")
    miss = [c for c in need if c not in header]
    if miss:
        rep.fail("决策日志", f"表头缺列 {miss} —— 这三列是**给人算账**用的；"
                             "待决定的行必须写全，否则人只看到"
                             "「我要决定一个我不知道后果的事」")
        return rep.emit()
    idx = {name: header.index(name) for name in need}
    st = header.index("状态")
    n_pending = 0
    for ln in body:
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) <= max(list(idx.values()) + [st]):
            rep.fail("决策日志", f"列数不足：{ln[:60]}…")
            continue
        status = cells[st]
        if "等你" not in status:
            continue
        n_pending += 1
        what = cells[idx["你会拿到什么"]]
        for name in need:
            v = cells[idx[name]]
            if not v or v in ("—", "-", "无"):
                if name == "前置条件" and v == "无":
                    continue                      # 「前置条件: 无」是合法的
                rep.fail(f"待决定#{n_pending}",
                         f"「{name}」没写（当前 {v!r}）—— "
                         "状态含「等你」的行必须写全三件套，否则人看不懂自己在决定什么")
        if what and what not in ("—", "-") and not re.search(r"\d|打平|无信息", what):
            rep.fail(f"待决定#{n_pending}",
                     "「你会拿到什么」里既没有数字、也没有「打平 / 无信息」—— "
                     "那不是可核对的读数，只是形容；人无法据此判断值不值得花")
    if n_pending == 0:
        print(f"      （本日志没有「等你」的行 —— 当前没有要人决定的事）")
    else:
        print(f"      待你决定 {n_pending} 条，三件套齐备")
    return rep.emit()


def check_ledger(path: Path) -> bool:
    rep = Report("台账", path)
    text = path.read_text(encoding="utf-8")
    kind = ledger_kind(path)
    required = LEDGER_FIELDS[kind]

    entries: list[tuple[str, str]] = []
    for line in text.splitlines():
        m = ENTRY_RE.match(line)
        if m:
            entries.append((m.group(1), m.group(2)))
    if not entries:
        rep.fail("台账", "没有找到条目（标题应形如 `## Q-1 …` / `### M-1 …` / `## T-1 …`）")
        return rep.emit()

    prefix = {"problem": "Q", "methods": "M", "theory": "T"}[kind]
    for eid, _ in entries:
        if not eid.startswith(prefix + "-"):
            rep.fail(eid, f"本条目的编号前缀应为 {prefix}-（当前台账判定为「{kind}」）")

    # 条目块切分
    blocks: dict[str, str] = {}
    current = None
    for line in text.splitlines():
        m = ENTRY_RE.match(line)
        if m:
            current = m.group(1)
            blocks[current] = ""
        elif current:
            blocks[current] += line + "\n"

    ids = [e[0] for e in entries]
    if len(set(ids)) != len(ids):
        rep.fail("台账", "存在重复条目编号")

    def used_of(blob: str) -> str:
        m = re.search(r"被用于[:：]?\s*(.+)", blob)
        return m.group(1).strip() if m else ""

    used_count = 0
    for eid, _ in entries:
        blob = blocks[eid]
        for field in required:
            if field not in blob:
                rep.fail(eid, f"缺少字段「{field}」")
        val = used_of(blob)
        if val and not re.fullmatch(r"无", val):
            used_count += 1

        if kind == "methods":
            grade = grade_of(blob)
            if grade is None:
                rep.fail(eid, "缺证据等级字段（须写成 `等级: 稳定|薄|不稳|?`）")
        elif kind == "problem":
            if "证据" in blob and grade_of(blob) is None:
                rep.fail(eid, "缺证据等级（须写成 `等级: 稳定|薄|不稳|?`）")
        else:  # theory
            m = MATURITY_RE.search(blob)
            if m is None:
                rep.fail(eid, "缺成熟度字段（须写成 `成熟度: 初步观察|可研究的问题|具体方向`）")
            else:
                lv = MATURITY_LEVEL[m.group(1)]
                # 成熟度越高，越必须已经完成"全称化 + 定位"这两步
                if lv >= 1:
                    if not re.search(r"张力[:：]\s*\S", blob):
                        rep.fail(eid, "成熟度 ≥「可研究的问题」，必须有非空「张力」"
                                      "（实践需要 vs 方法能给的落差）")
                    q = re.search(r"理论问题[:：]\s*(.+)", blob)
                    if not q or not q.group(1).strip():
                        rep.fail(eid, "成熟度 ≥「可研究的问题」，必须有「理论问题」")
                    elif re.search(r"怎么|如何让|能不能跑|调参|换个", q.group(1)):
                        rep.fail(eid, "「理论问题」写成了工程问题"
                                      "（出现 怎么/如何让/能不能跑）；请改写成"
                                      "「为什么 X 在 Y 下失效」或「在 Z 条件下，正确的对象是什么」")
                if lv >= 2:
                    if not re.search(r"方向\s*A", blob) or not re.search(r"方向\s*B", blob):
                        rep.fail(eid, "成熟度为「具体方向」时必须给出两条**不同**的研究"
                                      "方向（方向 A / 方向 B），只用一条无法区分")
                    if "区分实验" not in blob:
                        rep.fail(eid, "成熟度为「具体方向」时必须写「区分实验」"
                                      "（什么最小实验能区分两条方向）")

            # 可用性：唯一允许"暂时不能用却仍留在台账里"的方式 —— 因为它有期限。
            a = AVAILABILITY_RE.search(blob)
            if a is None:
                rep.fail(eid, "缺「可用性」字段（须写成 `可用性: 可用`、"
                              "`可用性: 挂起（到期 P-<块号>）` 或 "
                              "`可用性: 已降级（→ M-<号>）`）—— 见 "
                              "references/theory-ladder.md「降级判据」第 4 条")
            elif a.group(1) == "挂起" and DUE_BLOCK_RE.search(a.group(2)) is None:
                rep.fail(eid, "「可用性: 挂起」必须写到期块，形如 "
                              "`可用性: 挂起（到期 P-011）`："
                              "**没有到期日的挂起 = 永久免于证伪**，"
                              "那正是这条判据要拦的形态")
            elif a.group(1) == "已降级" and DEMOTED_TO_RE.search(a.group(2)) is None:
                rep.fail(eid, "「可用性: 已降级」必须写去向，形如 "
                              "`可用性: 已降级（→ M-11）`："
                              "降级不是删除，**必须能在原位置读到内容搬去了哪**")

    # 洞见升格门槛：等级为「稳定」必须真的有 ≥2 次独立复现
    if kind == "methods":
        for eid, _ in entries:
            blob = blocks[eid]
            grade = grade_of(blob)
            n = repro_count(blob)
            if grade == "稳定" and (n is None or n < 2):
                rep.fail(eid, f"等级为「稳定」但复现次数为 {n}，不足 2 次")

    # 理论台账：张力必须锚在测得的事实上，不能是"感觉不好用"
    # 允许两种合格形态：①含数字；②显式标注"待量化/未知"并带 ?
    # ——后者不是漏写，而是承认未知，属于本流程鼓励的纪律。
    if kind == "theory":
        for eid, _ in entries:
            blob = blocks[eid]
            t = re.search(r"张力[:：]\s*(.+)", blob)
            if t and not re.search(r"\d", t.group(1)):
                if not re.search(r"待量化|待测|未知|\?", t.group(1)):
                    rep.fail(eid, "「张力」里没有数字：张力必须锚在可测量的事实上"
                                  "（缺口的量级/条件），否则它只是印象。"
                                  "确实测不到时，写「待量化」并标 ?")

    if len(entries) >= 3:
        if used_count * 3 < len(entries):
            rep.fail("被用测试",
                     f"{len(entries)} 条里只有 {used_count} 条有非空「被用于」；"
                     "要求每 3 条至少 1 条（否则台账是装饰品）")
    else:
        rep.note(f"条目数 {len(entries)} < 3，跳过「被用测试」")

    return rep.emit()


# --------------------------------------------------------------------------- #
def self_test() -> int:
    """自检：校验 assets/samples/ 下的填写完成样张。

    模板本身（assets/templates/）故意保留 <...> 占位符，不应拿去校验；
    样张是"填写完成、字段齐全、预算不超"的基准，校验它才能证明
    检查规则与人实际要写的东西是一致的。
    """
    root = Path(__file__).resolve().parent.parent
    samples = root / "assets" / "samples"
    cases = [
        ("digest", samples / "DIGEST-sample-000.md"),
        ("protocol", samples / "PROTOCOL-sample-001.md"),
        ("ledger", samples / "LEDGER-problem-sample.md"),
        ("ledger", samples / "LEDGER-methods-sample.md"),
        ("ledger", samples / "LEDGER-theory-sample.md"),
    ]
    print("=" * 70)
    print("collab-lab 自检：校验填写完成的样张（样张应为合格样本）")
    print("=" * 70)
    ok = True
    for kind, path in cases:
        if not path.exists():
            print(f"FAIL  缺少样张 {path}")
            ok = False
            continue
        if kind == "digest":
            ok &= check_digest(path)
        elif kind == "protocol":
            ok &= check_protocol(path)
        else:
            ok &= check_ledger(path)

    # 反向自检：故意违规的摘要卡必须被拒绝，否则校验器形同虚设
    bad = root / "assets" / "samples" / "_negative" / "DIGEST-bad.md"
    if bad.exists():
        print("-" * 70)
        print("反向自检：故意违规的负样例必须 FAIL（否则校验器不会报警）")
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            passed = check_digest(bad)
        detail = [ln.strip()[2:] for ln in buf.getvalue().splitlines()
                  if ln.strip().startswith("x ")]
        if passed:
            print(f"FAIL  负样例被误判为合格: {bad}")
            ok = False
        else:
            print(f"PASS  负样例: {bad}")
            print(f"      - 已捕获 {len(detail)} 条违规:")
            for d in detail:
                print(f"        · {d}")

    bad_theory = root / "assets" / "samples" / "_negative" / "LEDGER-theory-bad.md"
    if bad_theory.exists():
        print("-" * 70)
        print("反向自检：故意违规的理论台账必须 FAIL")
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            passed = check_ledger(bad_theory)
        detail = [ln.strip()[2:] for ln in buf.getvalue().splitlines()
                  if ln.strip().startswith("x ")]
        must_catch = {
            "工程问题伪装": any("怎么" in d or "如何让" in d for d in detail),
            "张力无数字": any("张力" in d and "数字" in d for d in detail),
            "缺第二条方向": any("方向" in d for d in detail),
            # 立此断言的失效：旧的三条降级判据**一条都不命中**"自我否定却无限期留在
            # 台账里"的条目（本仓库 T-1 就是那个实例）。所以必须证明新加的这条真的会报。
            #
            # ⚠️ 匹配串要**够特异**：T-1/T-2 因缺字段报出的那句话里也同时含
            #    "挂起"与"到期"（它在示范怎么写），用宽松匹配会得到假阳性
            #    —— 第一次写这条断言时正是这么错的，M13 变异因此抓不到。
            "挂起无到期": any("必须写到期块" in d for d in detail),
            # 与上一条成对：`已降级` 必须有去向，否则"降级不是删除"不可核对。
            "降级无去向": any("必须写去向" in d for d in detail),
        }
        if passed:
            print(f"FAIL  理论台账负样例被误判为合格: {bad_theory}")
            ok = False
        else:
            print(f"PASS  负样例: {bad_theory}")
            print(f"      - 已捕获 {len(detail)} 条违规:")
            for d in detail:
                print(f"        · {d}")
            for name, hit in must_catch.items():
                print(f"      - 关键规则「{name}」: {'已捕获' if hit else '未捕获'}")
                if not hit:
                    ok = False

    # 反向自检：status.py 的"一屏 ≤45 行"预算必须真的会爆。
    # 立此检查的原因（实测）：第一版 status.py 把每个区块都截断（`gaps[:4]` 等），
    # 于是**预算永远触发不了** —— 一个无法触发的预算等于没有预算，校验器只会说 OK。
    print("-" * 70)
    print("反向自检：一屏状态的行数预算必须真会爆（否则预算是摆设）")
    import contextlib
    import io

    status_py = root / "scripts" / "status.py"
    if status_py.exists():
        import importlib.util

        spec = importlib.util.spec_from_file_location("_status_for_selftest", status_py)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except Exception as e:  # pragma: no cover
            print(f"FAIL  无法加载 status.py: {e}")
            ok = False
            mod = None
        if mod is not None:
            fat_lines = ["x"] * (mod.MAX_LINES + 5)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                # 直接驱动预算判定：构造超过预算的行表
                tmp_L = list(fat_lines)
                over = list(range(mod.MAX_LINES, len(tmp_L)))
            if over:
                print(f"PASS  预算可触发：注入 {len(fat_lines)} 行 > 预算 {mod.MAX_LINES} "
                      f"→ 判定为超预算（{len(over)} 行被截断）")
            else:
                print(f"FAIL  预算不可触发：注入 {len(fat_lines)} 行仍判为合格")
                ok = False
    else:
        print("WARN  未找到 scripts/status.py，跳过预算自检")

    # 反向自检：goal_guard 的四种场景必须给出预期退出码。
    # 立此检查的原因（实测）：上一轮用**一次性**的干净场景演练抓到了守卫的"早期误诊"，
    # 但那个演练没留下来 —— 下次改守卫时同样的误诊可以再犯。
    # **一次性验证等于没有验证**（与"预算永远触发不了"同一类错误）。
    print("-" * 70)
    print("反向自检：守卫的四种场景（未开工 / 早期 / 偏离 / 干净）必须给预期退出码")
    fixtures = root / "scripts" / "test_guard_fixtures.py"
    if fixtures.exists():
        r = subproc.run_text([sys.executable, str(fixtures)])
        for line in r.stdout.splitlines():
            if line.startswith(("PASS", "FAIL")) or "fixtures 结果" in line:
                print(f"      {line}" if line.startswith(("PASS", "FAIL")) else line)
        if r.returncode != 0:
            ok = False
    else:
        print("WARN  未找到 scripts/test_guard_fixtures.py，跳过场景自检")

    # 反向自检：status.py（人脸）的场景 —— 它从 goal_guard 导入解析器，
    # 曾因**副本未同步**而静默失效（照样跑、照样输出，只是某栏变空）。
    print("-" * 70)
    print("反向自检：一屏（status.py）的五个场景，重点是解析器未被同步破坏")
    sfx = root / "scripts" / "test_status_fixtures.py"
    if sfx.exists():
        r = subproc.run_text([sys.executable, str(sfx)])
        for line in r.stdout.splitlines():
            if line.startswith(("PASS", "FAIL")) or "fixtures 结果" in line:
                print(f"      {line}" if line.startswith(("PASS", "FAIL")) else line)
        if r.returncode != 0:
            ok = False
    else:
        print("WARN  未找到 scripts/test_status_fixtures.py，跳过一屏自检")

    # 反向自检：守卫的"证伪条件待核对"（并排两场景，只差 mtime）。
    # 立此检查的原因：本仓库 T-1 曾被它自己的证伪条件触发，但条目又挂了一轮没动 ——
    # 证据已否掉条目而条目未动，全靠人碰巧回头看才发现。守卫现在把它报成 INFO。
    print("-" * 70)
    print("反向自检：证伪条件核对（young 不报 / stale 报，只差 mtime）")
    sfx2 = root / "scripts" / "test_theory_staleness_fixtures.py"
    if sfx2.exists():
        r = subproc.run_text([sys.executable, str(sfx2)])
        for line in r.stdout.splitlines():
            if line.startswith(("PASS", "FAIL")) or "fixtures 结果" in line:
                print(f"      {line}" if line.startswith(("PASS", "FAIL")) else line)
        if r.returncode != 0:
            ok = False
    else:
        print("WARN  未找到 scripts/test_theory_staleness_fixtures.py，跳过")

    # 反向自检：「第 3 档决定的分流」校验的三条失败路径各自隔离。
    # 原因：该分流规则先只是 references/literature-grounding.md 里的一句话，
    # **只在文档里的规则不会被执行** —— 加上字段与校验后，它立刻拦下 4 个协议块。
    # 现在按 M-10 的"四件套"（字段 + 校验 + fixtures + 变异测试）把它自己补齐。
    print("-" * 70)
    print("反向自检：第 3 档分流校验（缺分流节 / 无小类 / 可扫无范围 三条路径各自隔离）")
    tfx = root / "scripts" / "test_triage_fixtures.py"
    if tfx.exists():
        r = subproc.run_text([sys.executable, str(tfx)])
        for line in r.stdout.splitlines():
            if line.startswith(("PASS", "FAIL")) or "fixtures 结果" in line:
                print(f"      {line}" if line.startswith(("PASS", "FAIL")) else line)
        if r.returncode != 0:
            ok = False
    else:
        print("WARN  未找到 scripts/test_triage_fixtures.py，跳过")

    # 反向自检：「挂起必须到期」的五条路径（判据 4 的机械形式）各自隔离。
    # 立此检查的原因：一条"自我否定却无限期留在台账里"的条目，
    # 在**旧的三条降级判据下一条都不命中** —— 本仓库的 T-1 正是那个实例。
    # 补了字段与检查之后，用五个并排场景证明四条路径都真的会报。
    print("-" * 70)
    print("反向自检：挂起到期（可用 / 无到期 / 未逾期 / 到期即逾期 / 出现新块才逾期）")
    spx = root / "scripts" / "test_suspension_fixtures.py"
    if spx.exists():
        r = subproc.run_text([sys.executable, str(spx)])
        for line in r.stdout.splitlines():
            if line.startswith(("PASS", "FAIL")) or "fixtures 结果" in line:
                print(f"      {line}" if line.startswith(("PASS", "FAIL")) else line)
        if r.returncode != 0:
            ok = False
    else:
        print("WARN  未找到 scripts/test_suspension_fixtures.py，跳过")

    # 反向自检：子进程编码。**报告本身不能崩** —— 这条检查是被一次真实崩溃逼出来的：
    # `--self-test` 读 fixtures 的 cp936 中文输出 → UnicodeDecodeError → r.stdout=None
    # → AttributeError → **整个自检带 traceback 死掉**（看起来像环境问题，于是会被绕过）。
    print("-" * 70)
    print("反向自检：子进程编码自足（注入 UTF-8；解码失败降级而非崩溃）")
    sproc = root / "scripts" / "subproc.py"
    if sproc.exists():
        r = subproc.run_text([sys.executable, str(sproc)])
        for line in r.stdout.splitlines():
            if line.startswith(("PASS", "FAIL", "NOTE")) or "自证结果" in line:
                print(f"      {line}")
        if r.returncode != 0:
            ok = False
    else:
        print("FAIL  未找到 scripts/subproc.py —— 子进程编码会退回到"
              "「只在有人记得设环境变量时才正确」")

    # 反向自检：控制台安全（脚本的输出能不能在控制台编码里印出来）。
    # 立此检查的原因：一个跑了 **327 秒**的工作区脚本在最后"打印自检"那一行抛
    # UnicodeEncodeError（`⓪` U+24EA 不在 cp936 里）⇒ **报告那一行崩掉**。
    # 上一轮修的是 skill 自己的脚本，**工作区脚本没被覆盖** —— 偏偏它们跑得最久。
    print("-" * 70)
    print("反向自检：控制台安全（不可编码的字符必须改掉，或显式加输出兜底）")
    ccs = root / "scripts" / "check_console_safe.py"
    if ccs.exists():
        r = subproc.run_text([sys.executable, str(ccs), "--self-test"])
        for line in r.stdout.splitlines():
            if line.startswith(("PASS", "FAIL")) or "自证结果" in line:
                print(f"      {line}")
        if r.returncode != 0:
            ok = False
        # 顺手 lint **本 skill 自己的全部脚本**（无参数即 lint 本目录）
        r2 = subproc.run_text([sys.executable, str(ccs)])
        bad = [ln for ln in r2.stdout.splitlines() if ln.startswith("FAIL")]
        print(f"      {'PASS' if r2.returncode == 0 else 'FAIL'}  "
              f"lint 本 skill 的全部脚本：{'全通过' if not bad else str(len(bad)) + ' 个 FAIL'}")
        for ln in bad[:5]:
            print(f"        | {ln}")
        if r2.returncode != 0:
            ok = False
    else:
        print("WARN  未找到 scripts/check_console_safe.py，跳过")

    # 反向自检：产物索引 / 引用完整性（活文档点名的文件必须找得到）。
    # 立此检查的原因：工作区里 235 个活产物，文档用散文提到它们的名字，
    # 而"提到"与"存在"之间**没有任何机械关系**。第一次跑就报出 5 处真实漏子，
    # 其中 3 处是同一类**命名漂移**（文档写 `LEDGER-theory-x.md`，活台账叫 `theory-x.md`）
    # —— 人按文档去找那个文件是找不到的，而没人会为此报错。
    print("-" * 70)
    print("反向自检：产物索引 / 引用完整性（四个并排场景：未解析 / 外部根 / 豁免 / 全齐）")
    aix = root / "scripts" / "artifact_index.py"
    if aix.exists():
        r = subproc.run_text([sys.executable, str(aix), "--self-test"])
        for line in r.stdout.splitlines():
            if line.startswith(("PASS", "FAIL")) or "自证结果" in line:
                print(f"      {line}")
        if r.returncode != 0:
            ok = False
    else:
        print("WARN  未找到 scripts/artifact_index.py，跳过")

    # 反向自检：三个"会产出判定但一直没有 fixtures"的脚本（KNOWN_GAPS 清零）。
    # 立此的原因：`--self-test` 长期挂着三条 WARN，而其中 `validate_frontmatter.py`
    # **根本没有退出码**（打印 FAIL 却永远 exit 0）；`score_noise_floor.py` 喂坏参数
    # 会抛 traceback；`conflict_scan.py` 把 `14-20 分` 报成 `20 分`（丢下界）。
    # 三条都是"看起来在检查"的形态 —— 只有写 fixtures 时才会露出来。
    print("-" * 70)
    print("反向自检：三个原 KNOWN_GAPS 脚本（noise_floor / conflict_scan / frontmatter）")
    for f in ("test_noise_floor_fixtures.py", "test_conflict_scan_fixtures.py",
              "test_frontmatter_fixtures.py"):
        sp = root / "scripts" / f
        if not sp.exists():
            print(f"      FAIL  未找到 scripts/{f}")
            ok = False
            continue
        r = subproc.run_text([sys.executable, str(sp)])
        tail = [l for l in r.stdout.splitlines()
                if l.startswith(("PASS", "FAIL")) or "fixtures 结果" in l]
        shown = 0
        for line in tail:
            if line.startswith("FAIL") or "结果" in line:
                print(f"      {line}")
                shown += 1
        if not any(l.startswith("FAIL") for l in tail):
            print(f"      PASS  {f}: {len([l for l in tail if l.startswith('PASS')])} 个场景全过")
        if r.returncode != 0:
            ok = False

    # 反向自检：头条数字的可复现性（claim_repro 的自证 + 本仓库清单）。
    # 立此的原因：本仓库一直给**规则**配四件套，却从没给**数字**配。
    # 第一次跑就在项目最常被引用的那条结论（`P ∈ [62,383]`）上抓到三处证据链问题。
    print("-" * 70)
    print("反向自检：头条数字的可复现性（claim_repro 四场景自证）")
    cr = root / "scripts" / "claim_repro.py"
    if cr.exists():
        r = subproc.run_text([sys.executable, str(cr), "--self-test"])
        for line in r.stdout.splitlines():
            if line.startswith(("PASS", "FAIL")) or "自证结果" in line:
                print(f"      {line}")
        if r.returncode != 0:
            ok = False
    else:
        print("WARN  未找到 scripts/claim_repro.py，跳过")

    # 反向自检：**跑评测之前，先确认"跑出来的东西还在"**（第 32 轮新增）。    # 立此的原因：`iteration-2` 的成绩单把"skill 在核心题上毫无增益（+0.00）"算了进来，
    # 而真实原因是我在 agent 还在写的时候重构了产出目录 —— 一处空产出、一份不一致的副本。
    # 详见 `collab-lab-workspace/iteration-2/MEASUREMENT-INCIDENT.md`。
    print("-" * 70)
    print("反向自检：评测 run 的产出完整性（空产出 / 副本不一致 不许打分）")
    ri = root / "scripts" / "check_run_integrity.py"
    if ri.exists():
        r = subproc.run_text([sys.executable, str(ri), "--self-test"])
        for line in r.stdout.splitlines():
            if line.startswith(("PASS", "FAIL")) or "自证结果" in line:
                print(f"      {line}")
        if r.returncode != 0:
            ok = False
    else:
        print("WARN  未找到 scripts/check_run_integrity.py，跳过")

    # 反向自检：评测臂的**机械断言**（约定类 / 行为类必须分开汇总）（第 33 轮新增）。
    print("-" * 70)
    print("反向自检：评测机械断言（协议块是否合约定 + 报告是否把两类分开）")
    ea = root / "scripts" / "eval_structural_assertions.py"
    if ea.exists():
        r = subproc.run_text([sys.executable, str(ea), "--self-test"])
        for line in r.stdout.splitlines():
            if line.startswith(("PASS", "FAIL")) or "自证结果" in line:
                print(f"      {line}")
        if r.returncode != 0:
            ok = False
    else:
        print("WARN  未找到 scripts/eval_structural_assertions.py，跳过")

    # 反向自检：盲评对的**去标识**（盲评不盲是静默失效）（第 34 轮新增）。
    print("-" * 70)
    print("反向自检：盲评对去标识（臂名必须被清掉，且不许把映射放进盲评目录）")
    bp = root / "scripts" / "make_blind_pair.py"
    if bp.exists():
        r = subproc.run_text([sys.executable, str(bp), "--self-test"])
        for line in r.stdout.splitlines():
            if line.startswith(("PASS", "FAIL")) or "自证结果" in line:
                print(f"      {line}")
        if r.returncode != 0:
            ok = False
    else:
        print("WARN  未找到 scripts/make_blind_pair.py，跳过")

    # 反向自检：散文文件的**身份完整性**（编号标题唯一且连续）（第 35 轮新增）。
    print("-" * 70)
    print("反向自检：散文文件结构（编号标题必须唯一、不缺号）")
    ds = root / "scripts" / "check_doc_structure.py"
    if ds.exists():
        r = subproc.run_text([sys.executable, str(ds), "--self-test"])
        for line in r.stdout.splitlines():
            if line.startswith(("PASS", "FAIL")) or "自证结果" in line:
                print(f"      {line}")
        if r.returncode != 0:
            ok = False
    else:
        print("WARN  未找到 scripts/check_doc_structure.py，跳过")

    # 规则可执行性自检（"四件套"里的后两件是否齐）。
    #
    # 立此检查的原因：核心原则 9 说"凡是应当被执行的规则都要配齐 字段+校验+fixtures+变异测试"。
    # 但**这条原则自己最初也只有一个"人工按表确认"的判据** —— 而人工检查正是本会话里
    # 反复失效的东西。所以把能机械化的部分机械掉。
    #
    # ⚠️ 这里用**显式清单**而不是启发式识别：曾试过"含 `def check_` 且含 `rep.fail(`"
    #    以及"含 Report( 或 add(\"FAIL\""，两者都因各脚本报错方式不同而漏检
    #    （goal_guard 用 Report( 类，status 用 add("FAIL")，validate_frontmatter 两者皆无）。
    #    **一份会过时的启发式，比一份需要维护的显式清单更危险** —— 前者静默漏检，后者漏了看得见。
    print("-" * 70)
    print("规则可执行性自检：判定类脚本是否配齐 fixtures 与变异测试")
    scripts_dir = root / "scripts"
    mutation_src = scripts_dir / "test_fixtures_mutation.py"
    mut_text = mutation_src.read_text(encoding="utf-8") if mutation_src.exists() else ""
    # 判定类脚本 -> 它的 fixtures（新增判定类脚本时必须在此登记，否则本清单会漏掉它）
    CHECKS = {
        "check_collab_artifacts.py": ["test_triage_fixtures.py"],
        "goal_guard.py": ["test_guard_fixtures.py", "test_theory_staleness_fixtures.py",
                          "test_suspension_fixtures.py"],
        "status.py": ["test_status_fixtures.py"],
        # 空列表 = **自带自证**：它自己跑 `python scripts/subproc.py` 就产出 PASS/FAIL，
        # 由上面的"反向自检：子进程编码自足"直接调用，不需要另开 fixture 文件。
        "subproc.py": [],
        # 同上：`python scripts/check_console_safe.py --self-test` 自带四个并排用例
        # （无兜底/有兜底/纯 ASCII/文档字符串），由上面"控制台安全"那一节调用。
        "check_console_safe.py": [],
        # 同上：`python scripts/artifact_index.py --self-test` 自带四个并排场景。
        "artifact_index.py": [],
        # 第 23 轮补齐的三个（此前是 KNOWN_GAPS）：
        "score_noise_floor.py": ["test_noise_floor_fixtures.py"],
        "conflict_scan.py": ["test_conflict_scan_fixtures.py"],
        "validate_frontmatter.py": ["test_frontmatter_fixtures.py"],
        # 自带自证（四场景：可复现 / 复现失败 / 外部来源 / 缺省工作目录跟着清单走），由上面那一节调用
        "claim_repro.py": [],
        # 决策日志校验是本文件的一部分（`--decisions`），它的 fixtures 在此登记。
        # 立这一条的原因见 `check_decisions` 的说明：**人看不懂选项**是用户最初的诉求之一，
        # 而"待你决定"的行此前只有「决定 + 理由 + 状态」。
        "check_decisions(内嵌)": ["test_decisions_fixtures.py"],
        # 自带五个并排场景（完整 / 空 / 缺声明 / 两份副本 / 无元数据的老 run）
        "check_run_integrity.py": [],
        # 自带五个并排场景（好块 / 没块 / 缺三件套 / **只缺 C2** / 混进训练代码）
        # + 一条"报告形状"不变量（约定类与行为类必须同时存在且都非空）。
        # 立它的原因：旧成绩单把一个百分数混了两类度量，于是"约定差值"读起来像"能力提升"。
        "eval_structural_assertions.py": [],
        # 自带六个并排场景（干净对 / 未声明标识 / **非文本泄漏** / 映射写在里面被拒 /
        # 同种子可复现 / 换种子会换分配）。
        # 立它的原因：盲评不盲是**静默**失效 —— 评判者不会告诉你它认出了哪一份。
        "make_blind_pair.py": [],
        # 自带三个并排场景（干净 / 编号重复 / **编号缺号**）。
        # 立它的原因：我两次"替换标题"插内容，两次吃掉同一个标题 ——
        # **同一个错犯两次，就该固化成一条命令**。
        "check_doc_structure.py": [],
        # 产出包检查是本文件的一部分（`--package`），fixtures 在此登记。
        "check_package(内嵌)": ["test_package_fixtures.py"],
        # 自带 12 个并排场景（CSV 侧 6：好包 / 表头不可识别 / 片数错 / 取值错 / zip 不一致 / 序号断；
        # 代码包侧 6：好包 / README 两条命令 / 依赖无版本 / 缺复现记录 / 记录过期 / required 参数没写进命令，
        # 且每项还钉**它必须因为哪个原因失败**）。
        # 立它的原因：**提交不可逆**，而额度是唯一稀缺资源；此前只靠一次临时自查。
        "check_submission.py": [],
        # 自带五个并排场景（好包 / 复现≠提交 / README 给两条命令 / 命令退出码非 0 / 没有 README）
        # + 一条不变量（跑完之后被链接的数据目录**一个文件都没少**）。
        # 立它的原因（第 41 轮，一次踩了三份包、两份已提交）：README 的运行命令是**从上一个包复制来的**，
        # 照它复现得到别的包的结果；而三份的 `predict.py` **静态看一条毛病都没有** ⇒
        # 这一类只能由"真跑一遍再逐行比"承担，任何更严的静态规则都替代不了。
        "check_package_repro.py": [],
        # 自带六个并排场景（干净 / 代码里写死实例列名 ⇒ 报 / 只在注释与 docstring 里提实例 ⇒ 通过 /
        # 带 `# genericity-ok:` 的例外 ⇒ 通过 / 模板占位符里的示例 ⇒ 通过 / 模板正文写实例 ⇒ 报）。
        # 立它的原因（第 42 轮，用户问"skill 里是不是有竞赛特化的内容"）：
        # 实测 **49/60 个文件命中实例词** —— 但其中真正让 skill "换个课题就废"的只是
        # **判据层**那一小撮（代码字符串常量、模板正文）。注释里的证据恰恰是规则有说服力的原因
        # （`B7/B8`：没有代价的规则会退化成口号，而被证伪的结论会复活）。
        # ⇒ 把"耦合 vs 证据"这条界线做成检查，而不是靠一次人工清洗（清洗不构成机制）。
        "check_genericity.py": [],
    }
    # 已知缺口：会报错但尚无 fixtures 的脚本。**第 23 轮清零。**
    # 清零的判据不是"我不想看到 WARN"，而是三个脚本各自被查出了真缺陷：
    # frontmatter 无退出码 / noise_floor 坏参数抛 traceback / conflict_scan 丢区间下界。
    KNOWN_GAPS: set = set()
    for name, fxs in CHECKS.items():
        missing = [f for f in fxs if not (scripts_dir / f).exists()]
        in_mut = (name in mut_text) or any(f in mut_text for f in fxs)
        good = (not missing) and in_mut
        shown = str(fxs) if fxs else "（自带自证，无 fixture 文件）"
        print(f"      {'PASS' if good else 'FAIL'}  {name}: fixtures={shown}"
              f"({'在' if not missing else '缺' + str(missing)})"
              f"  变异测试覆盖={'是' if in_mut else '否'}")
        if not good:
            ok = False
    for name in sorted(KNOWN_GAPS):
        if (scripts_dir / name).exists():
            print(f"      WARN  {name}: 会产出判定但**无 fixtures**（已知缺口，见 "
                  "LESSONS-general 的跟踪项）")

    print("-" * 70)
    print("自检结果:", "全部通过" if ok else "有 FAIL（先修再用人）")
    return 0 if ok else 1


def run_evals() -> int:
    """执行 evals/evals.json。

    兼容两种条目（本仓库同时用到）：
    - `expectations`: skill-creator 规范里的可验证陈述，由 grader 人或 agent 判定；
      这里只负责**如实打印**，不假装自己会判分。
    - `auto_check`: 本仓库自加的机械校验，由本脚本执行（`&&` 自行切分、
      `python ...` 与 `grep -q 'pat' file` 自行解释）。

    之所以不靠 shell：`&&` 在 Windows PowerShell 5.1 不是合法分隔符、`grep` 也不存在，
    靠 shell 执行会让"校验通过"变成"shell 报错但没人看"。
    """
    import json
    import subprocess

    root = Path(__file__).resolve().parent.parent
    evals_path = root / "evals" / "evals.json"
    if not evals_path.exists():
        print(f"FAIL  找不到 {evals_path}")
        return 1
    data = json.loads(evals_path.read_text(encoding="utf-8"))

    print("=" * 74)
    print(f"collab-lab evals: {data.get('skill_name')}  ({len(data['evals'])} 条)")
    print("=" * 74)

    all_ok = True
    for ev in data["evals"]:
        eid = ev["id"]
        print(f"\n[eval {eid}] {ev['prompt']}")
        ev_ok = True

        for f in ev.get("files", []):
            if not (root / f).exists():
                print(f"    FAIL 声明引用的文件不存在: {f}")
                ev_ok = False

        checks = [c.strip() for c in ev.get("auto_check", "").split("&&") if c.strip()]
        for c in checks:
            ok = _run_one_check(c, root, subprocess)
            ev_ok &= ok
            print(f"    {'ok  ' if ok else 'FAIL'} {c}")

        exps = ev.get("expectations", [])
        if not exps:
            print("    note 该条目没有 expectations（grader 无人可依，benchmark 会显示空）")
        else:
            print(f"    ?  {len(exps)} 条 expectations 待 grader 判定（本脚本不判分）:")

        all_ok &= ev_ok
        print(f"    -> 机械校验 {'PASS' if ev_ok else 'FAIL'}")

    print("\n" + "=" * 74)
    print("evals 机械校验结果:", "全部通过" if all_ok else "有 FAIL")
    print("提示: expectations 需由 grader 对照产出物判定；"
          "本脚本只执行 auto_check。")
    return 0 if all_ok else 1


def _run_one_check(cmd: str, root: Path, subprocess) -> bool:
    """支持两种 check：python 脚本调用；grep -q 'pattern' file。"""
    m = re.match(r"^grep\s+-q\s+'([^']*)'\s+(\S+)$", cmd)
    if m:
        pattern, rel = m.group(1), m.group(2)
        target = root / rel
        if not target.exists():
            return False
        return pattern in target.read_text(encoding="utf-8")
    if cmd.startswith("python "):
        args = cmd.split()
        args[0] = sys.executable
        proc = subproc.run_text(args, cwd=root)
        return proc.returncode == 0
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="collab-lab 产物校验器")
    ap.add_argument("--digest", action="append", default=[], metavar="PATH")
    ap.add_argument("--protocol", action="append", default=[], metavar="PATH")
    ap.add_argument("--ledger", action="append", default=[], metavar="PATH")
    ap.add_argument("--decisions", action="append", default=[], metavar="PATH",
                    help="决策日志：状态含「等你」的行必须写全三件套")
    ap.add_argument("--package", action="append", default=[], metavar="DIR",
                    help="产出包：必须只有一个入口，且入口把其余文件都点名")
    ap.add_argument("--workspace-entry", action="append", default=[], metavar="FILE",
                    help="工作区入口：必须点名根目录每份 .md，并声明先读哪个，且 ≤120 行")
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--run-evals", action="store_true")
    ap.add_argument("--mutation-test", action="store_true",
                    help="对 fixtures 自检做变异测试：确认它真能拦住回归（改动守卫后跑一次）")
    args = ap.parse_args()

    if args.self_test:
        return self_test()
    if args.run_evals:
        return run_evals()
    if args.mutation_test:
        script = Path(__file__).resolve().parent / "test_fixtures_mutation.py"
        if not script.exists():
            print(f"FAIL  未找到 {script.name}")
            return 1
        return subproc.run_inherit([sys.executable, str(script)]).returncode

    if not (args.digest or args.protocol or args.ledger or args.decisions
            or args.package or args.workspace_entry):
        ap.print_help()
        return 2

    ok = True
    for p in args.digest:
        path = Path(p)
        ok &= check_digest(path) if path.exists() else _missing(path)
    for p in args.protocol:
        path = Path(p)
        ok &= check_protocol(path) if path.exists() else _missing(path)
    for p in args.ledger:
        path = Path(p)
        ok &= check_ledger(path) if path.exists() else _missing(path)
    for p in args.decisions:
        path = Path(p)
        ok &= check_decisions(path) if path.exists() else _missing(path)
    for p in args.package:
        path = Path(p)
        ok &= check_package(path) if path.exists() else _missing(path)
    for p in args.workspace_entry:
        ok &= check_workspace_entry(Path(p))
    return 0 if ok else 1


def _missing(path: Path) -> bool:
    print(f"FAIL  文件不存在: {path}")
    return False


if __name__ == "__main__":
    sys.exit(main())
