#!/usr/bin/env python -u
# -*- coding: utf-8 -*-
r"""artifact_index.py —— 产物索引 + 引用完整性检查。

## 它治的是哪一句话

> "我**无法利用** agent 所写代码产出的结果和数据。"

这句话有两个成因，一个是"文件没留下"（已在别处治），另一个是**"留下了但我不知道它在哪"**。
本仓库的工作区里现在有 200+ 个产物文件，名字是 `T1_v4_permutation_scan.json`、
`predictions_004b/fold_07.npz`、`P-BOILER-010-sensitivity.log` 这种 ——
**文档用散文提到它们的名字，而"提到"与"存在"之间没有任何机械关系。**

实测（第 21 轮第一次跑本脚本）：活文档里有 **5 处点名了不存在的文件**，
其中 3 处是同一类**命名漂移**：文档写 `LEDGER-theory-bdl-boundary.md`，
而工作区里的活台账叫 `theory-bdl-boundary.md`（模板/样张带 `LEDGER-` 前缀，活台账不带）。
**人按文档去找那个文件，是找不到的** —— 而没人会为此报错。

## 三个桶（不是一个"对不对"）

对每一条引用，只有三种结局，**必须分开报**，因为处理方式完全不同：

| 桶 | 含义 | 处理 |
|---|---|---|
| **未解析** | 任何根里都没有这个名字 | **FAIL** —— 要么改引用，要么写进豁免表（带理由） |
| **只在历史快照里** | 只在被排除的目录（如 `iteration-2/`、`_salvage/`）里存在 | INFO —— 引用没错，但它**不在活工作集里** |
| **仓库外输入** | 只在 `--root` 给的外部根里（skill 目录 / 竞赛数据 / 参考文献） | INFO —— **这正好回答了"这个数字的输入在哪"** |

⇒ 第二、三桶不是错误，而是"这个数字从哪来"的答案。把它们和错误混在一起报，
就会训练人忽略整个输出（`LESSONS-general` D4：校验器误报比不报更糟）。

## 豁免表是**显式清单**，不是启发式

`EXTERNAL` 里逐条列出"名字找不到但引用合法"的情况，**每条写理由**。
理由与 `check_collab_artifacts.py` 的规则可执行性清单一致：
**一份会过时的启发式比一份需要维护的显式清单更危险** —— 前者静默漏检，后者漏了看得见。

## 它产出两份东西

1. **判定**（退出码）：未解析引用 = 0 ⇒ `0`；否则 `1`。
2. **`INDEX.md`**（默认写在 `--out`）：把"活产物 → 谁引用它"列成一张表，
   并按目录折叠成组（如 `predictions_004b/fold_*.npz ×11`），
   这样"某个数字背后的文件"可以**一眼查到**。
   还列出**无人引用的产物**（孤儿）—— 它们不是错误，但值得你决定留还是删。

用法：
    python scripts/artifact_index.py --workspace <工作区> \
        --root <skill 目录> --root <竞赛数据目录> --out INDEX.md
退出码：0 = 无未解析引用；1 = 有未解析引用；2 = 用法错误。
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import subproc  # noqa: E402,F401  （自身输出也不许崩）

# 默认不参与"活文档"扫描的目录（历史评测快照 / 数据集暂存 / 字节码）
DEFAULT_EXCLUDE = ("iteration-2", "_salvage", "_dataset", "__pycache__",
                   ".ipynb_checkpoints")

# 被文档点名的候选：扩展名白名单。
# ⚠️ 末尾的 `(?![\w])` 是必须的：没有它 `events.jsonl` 会被切成 `events.json`
#    （第一版就这么漏出了一个假悬空引用）。
REF_RE = re.compile(r"[A-Za-z0-9_\-]+\.(?:py|json|jsonl|log|csv|npz|md|txt|html|zip|png)(?![\w])")

# 文档 → 产物 的引用里，这些名字找不到但**合法**。每条必须有理由。
EXTERNAL = {
    "content_list.json": "MinerU 抽取中间产物，在参考文献目录里（--root 可覆盖）",
    "_content_list.json": "同上（MinerU 的临时命名）",
    "_model.json": "同上",
    "layout.json": "同上",
    "aggregate_benchmark.py": "skill-creator 自带的评测脚本，不在本仓库",
    "quick_validate.py": "skill-creator 自带的校验脚本，不在本仓库",
    "generate_review.py": "skill-creator 自带的评审页生成脚本，不在本仓库",
    "package_skill.py": "skill-creator 自带的打包脚本（`python -m scripts.package_skill <skill>`）"
                        "—— 第 39 轮引用它是为了记录「上游打包器拒收 argument-hint」这个冲突，"
                        "不是为了指向本仓库的文件",
    "eval_metadata.json": "skill-creator 的评测元数据，不在本仓库",
    "events.jsonl": "experiment-standards 记录包规范的**约定名**（同 run_manifest.json），"
                    "引用它是为了说明产出规范，不是为了指向本仓库的某个文件",
    "full.md": "MinerU 抽取的全文中间产物（约定名，与 content_list.json 同族），"
               "在参考文献目录里；引用它是为了说明抽取流程，不是指向本仓库的文件",
}


def collect_files(roots, exclude_names):
    """返回 (全部名字集合, 活文件列表, 只在历史快照里的名字集合, 只在外部根里的名字)。

    判定顺序很重要：**活 → 历史 → 外部 → 未解析**，因为"它在哪"正是我们要报的信息。
    """
    live, hist, ext = set(), set(), set()
    live_files = []
    for i, r in enumerate(roots):
        if not r.exists():
            continue
        for p in r.rglob("*"):
            if not p.is_file():
                continue
            if any(e in p.parts for e in exclude_names):
                hist.add(p.name)
                continue
            if i == 0:
                live.add(p.name)
                live_files.append(p)
            else:
                ext.add(p.name)
    allnames = live | hist | ext
    return allnames, live_files, hist, ext, live


def scan_refs(docs, exclude_names):
    """返回 {名字: {文档相对路径}}，只扫活文档。"""
    refs = defaultdict(set)
    for d in docs:
        txt = d.read_text(encoding="utf-8", errors="replace")
        for m in REF_RE.finditer(txt):
            name = m.group(0)
            before = txt[max(0, m.start() - 1):m.start()]
            # `*`/`/` = 通配符或路径片段；`.` = 它只是更长点号名字的尾巴。
            # ⚠️ 第三条是第一版漏的：`PROTOCOL.template.md` 会被切成 `template.md`，
            #    于是报出一个**假**悬空引用（真文件 `PROTOCOL.template.md` 在 skill 里）。
            #    校验器误报比不报更糟（D4），所以这一条必须显式挡掉。
            if before in ("*", "/", "\\", "."):
                continue
            refs[name].add(str(d))
    return refs


def group_name(rel: str, n: int) -> str:
    return f"{rel} ×{n}"


def write_index(out: Path, ws: Path, roots, exclude_names, refs, live_files,
                hist, ext, allow, dangling):
    """生成给人看的索引。**两条可读性纪律**（都是第一版实测后补的）：

    1. **路径相对化**：第一版打的是绝对 Windows 路径，一屏几十个
       本机绝对路径前缀（`<工作区>\\...\\`）⇒ 没人能扫。仓库外的文件用 `↗` 标出来。
    2. **按"有没有人引用"分组，而不是按目录字母序**：
       无人引用的东西按**目录折叠成一行**（`_grader-verify/x/ ← 19 个文件，无人引用`），
       否则草稿目录会把真正重要的那几行挤到屏幕外。
       人的问题是"这个数字背后的文件在哪"，所以**被引用多的排前面**。
    """
    def rel(p: Path) -> str:
        for r in roots:
            try:
                return str(p.relative_to(r)).replace("\\", "/")
            except ValueError:
                continue
        return str(p).replace("\\", "/")
    def mark(p: Path) -> str:
        return f"`{rel(p)}`" if p.is_relative_to(ws) else f"`↗ {rel(p)}`"

    def is_core(relpath: str) -> bool:
        """"核心文档" = 人真会去读的那几份（目标/地图/决策/台账/协议块）。

        立这条的实测原因：第一版按"引用总数"排序，结果前 17 行全是 5 个提交包里
        **互相引用**的 `README.md`/`predict.py`（一个 6 元团）⇒ 真正要找的
        `T1_block_grid.py`（被 5 份核心文档引用）被挤到第 18 行。
        **"被引用次数多"不等于"重要"——要问的是"被谁引用"。**
        """
        rp = relpath.replace("\\", "/")
        if rp.count("/") == 0:
            return True                      # 工作区根上的文档都算核心
        return (rp.startswith("ledgers/") or rp.startswith("literature/")
                or "/protocols/" in rp)

    by_name = defaultdict(list)
    for f in live_files:
        if any(e in f.parts for e in exclude_names) or f.name == out.name:
            continue
        by_name[f.name].append(f)

    # 按目录+名字模式折叠
    groups = defaultdict(list)
    for name, paths in by_name.items():
        for p in paths:
            m = re.match(r"^(.*?)(\d+)(\.[A-Za-z0-9]+)$", p.name)
            key = (rel(p.parent), (m.group(1) + "*" + m.group(3)) if m else p.name)
            groups[key].append(p)

    def referrers(key, paths):
        names = {Path(key[1]).name, paths[0].name}
        who = set()
        for nm in names:
            who |= refs.get(nm, set())
        # 去掉自引用（文档引用自己不算"有人引用它"）
        return {w for w in who if Path(w).name != paths[0].name}

    cited, orphan_rows, orphan_dirs = [], [], defaultdict(int)
    for key, paths in groups.items():
        who = referrers(key, paths)
        label = f"`{key[0]}/{key[1]}`" if key[0] != "." else f"`{key[1]}`"
        if len(paths) > 1:
            label += f" ×{len(paths)}"
        if who:
            core = sorted(w for w in who if is_core(str(Path(w).relative_to(ws))
                                                     if Path(w).is_relative_to(ws) else w))
            cited.append((len(core), len(who), label, core, sorted(who - set(core))))
        else:
            orphan_dirs[key[0]] += len(paths)

    L = []
    L.append("# INDEX —— 活产物清单与引用关系（**本文件由脚本生成，不要手改**）")
    L.append("")
    L.append("> 生成命令：`python scripts/artifact_index.py --workspace <工作区> "
             "--root <skill> --root <竞赛数据> --out INDEX.md`")
    L.append("> 它回答一个具体问题：**这个数字背后的文件在哪、谁在引用它。**")
    L.append(f"> 活产物 {sum(len(v) for v in by_name.values())} 个文件；"
             f"其中被文档引用的 {len(cited)} 组。")
    L.append("> 排序按**核心文档**（目标/地图/决策/台账/协议块）的引用数 —— "
             "被多少份草稿互相引用不算重要。")
    L.append("")

    L.append("## 1. 被核心文档引用的产物 → 谁引用它（**先看这个**）")
    L.append("")
    L.append("| 产物 | 核心文档 | 另有 |")
    L.append("|---|---|---|")
    for _, _, label, core, others in sorted(cited, key=lambda x: (-x[0], -x[1], x[2])):
        shown = "、".join(f"`{rel(Path(w))}`" for w in core[:6])
        if len(core) > 6:
            shown += f" 等 {len(core)} 份"
        L.append(f"| {label} | {shown or '—'} | {len(others)} 份 |")
    L.append("")

    L.append("## 2. 没有任何核心文档引用的目录（**不是错误**：留着还是删掉，由你定）")
    L.append("")
    L.append("| 目录 | 未被核心文档引用的文件数 |")
    L.append("|---|---|")
    for d, n in sorted(orphan_dirs.items(), key=lambda kv: -kv[1]):
        L.append(f"| `{d}/` | {n} |")
    L.append("")

    L.append("## 3. 被点名、但**不在活工作集里**的名字（不是错误，是「它从哪来」的答案）")
    L.append("")
    L.append("| 名字 | 在哪 | 引用它的活文档 |")
    L.append("|---|---|---|")
    for name in sorted(refs):
        if name in by_name:
            continue
        if name in hist:
            where = "**只在历史快照里**（`iteration-2/`、`_salvage/` 等）"
        elif name in ext:
            where = "**仓库外**（`--root` 给的外部根）"
        elif name in allow:
            where = f"**豁免**：{allow[name]}"
        else:
            where = "**哪里都没有 ⇒ 未解析引用（FAIL）**"
        L.append(f"| `{name}` | {where} | "
                 f"{'、'.join('`%s`' % rel(Path(w)) for w in sorted(refs[name]))} |")
    L.append("")

    if dangling:
        L.append("## 4. 未解析引用（必须修）")
        L.append("")
        for name in sorted(dangling):
            L.append(f"- `{name}` ← "
                     f"{'、'.join('`%s`' % rel(Path(w)) for w in sorted(refs[name]))}")
        L.append("")
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    return len(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="产物索引 + 引用完整性检查")
    ap.add_argument("--workspace", required=False, default=".")
    ap.add_argument("--root", action="append", default=[],
                    help="额外根（skill 目录 / 竞赛数据 / 参考文献）；可重复")
    ap.add_argument("--exclude", action="append", default=list(DEFAULT_EXCLUDE),
                    help="不作为活文档/活产物的目录名；可重复")
    ap.add_argument("--out", default="INDEX.md")
    ap.add_argument("--prune", action="store_true",
                    help="顺手删掉 INDEX.md 的旧副本之外的**空目录**（默认不删任何东西）")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        return _self_test()

    ws = Path(args.workspace).resolve()
    if not ws.exists():
        print(f"FAIL  工作区不存在：{ws}")
        return 2
    # **skill 目录永远是外部根**（自动加入，不需要人记得传）。
    # 立此的原因（第 28 轮实跑记录）：我按 `--root iteration-3` 跑了一次，
    # 于是 16 条"未解析引用"里有 12 条其实是**工作区文档在引用 skill 自己的东西**
    # （`references/theory-ladder.md`、`scripts/goal_guard.py`、`SKILL.md`…）。
    # 这不是启发式，是**结构事实**：collab-lab 的工作区按设计就要引用本 skill 的判据文件
    # ⇒ 让它依赖"人记得加 --root"，等于把一条必然成立的引用登记成待修的错误。
    # 而误报最坏的后果不是浪费一次运行，是**训练人忽略整个报告**（D4）。
    skill_root = Path(__file__).resolve().parent.parent
    extra = [Path(r).resolve() for r in args.root]
    roots = [ws]
    for r in [skill_root] + extra:
        if r not in roots:
            roots.append(r)
    exclude = tuple(args.exclude)
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = (Path.cwd() / out_path).resolve()

    # 活文档 = 工作区里、不在被排除目录下的 .md
    #
    # ⚠️ **必须把生成出来的索引自己排除掉**。第一版没排，于是第二趟跑的时候
    #    `INDEX.md` 里复述的"未解析引用清单"被当成了**新的**引用 ⇒
    #    同一个问题换个出处再报一次（而且指向 INDEX.md 自己）。
    #    这类"生成的报告又喂回检查器"的回路，凡是"脚本身兼产物"的地方都会出现。
    live_docs = []
    for p in ws.rglob("*.md"):
        if not p.is_file():
            continue
        if any(e in p.parts for e in exclude):
            continue
        if p.resolve() == out_path:
            continue
        live_docs.append(p)

    allnames, live_files, hist, ext, live = collect_files(roots, exclude)
    refs = scan_refs(live_docs, exclude)
    allow = dict(EXTERNAL)
    dangling = {n: v for n, v in refs.items()
                if n not in allnames and n not in allow}

    print("=" * 78)
    print(f"产物索引与引用完整性：工作区 {ws}")
    print(f"  活文档 {len(live_docs)} 份；活产物名字 {len(live)} 个；"
          f"外部根 {len(roots)-1} 个")
    for r in roots[1:]:
        tag = "（skill 目录，自动加入）" if r == skill_root else ""
        print(f"        └ 外部根：{r}{tag}")
    print("=" * 78)
    only_hist = sorted(n for n in refs if n not in live and n in hist)
    only_ext = sorted(n for n in refs if n not in live and n not in hist and n in ext)
    allowed = sorted(n for n in refs if n not in allnames and n in allow)
    print(f"  INFO  只在历史快照里：{len(only_hist)} 个"
          + (f"（如 {', '.join(only_hist[:3])}…）" if only_hist else ""))
    print(f"  INFO  仓库外输入    ：{len(only_ext)} 个"
          + (f"（如 {', '.join(only_ext[:3])}…）" if only_ext else ""))
    print(f"  INFO  显式豁免      ：{len(allowed)} 个"
          + (f"（{', '.join(allowed)}）" if allowed else ""))
    if dangling:
        print()
        print(f"  FAIL  **未解析引用 {len(dangling)} 个**（文档点名了，但哪里都找不到）：")
        for n in sorted(dangling):
            print(f"          `{n}` ← {'、'.join(sorted(dangling[n]))}")
    else:
        print()
        print("  PASS  未解析引用 0 个")

    n = write_index(Path(args.out), ws, roots, exclude, refs, live_files,
                    hist, ext, allow, dangling)
    print()
    print(f"  已写 {args.out}（{n} 行）")
    print("-" * 78)
    if dangling:
        print("⇒ 有未解析引用。按顺序试三步：①改引用（名字漂移最常见）；"
              "②它其实在某个**已知根**里 ⇒ 补 `--root`"
              "（skill 目录已自动加入；竞赛数据/参考文献目录要自己传）；"
              "③确实不在任何地方 ⇒ 写进 `artifact_index.py` 的 EXTERNAL 并给理由。")
        return 1
    print("⇒ 通过：活文档点名的每个文件都能找到（或在豁免表里带理由）。")
    return 0


def _self_test() -> int:
    """五个并排场景：**未解析必须报 / 外部根可解 / 豁免带理由 / 全齐不该报**。

    单场景抓不住"检查恒真或恒假"（`B28` 第 ② 项）；四个场景里有两个是"不该报"，
    所以任何"一律报 FAIL"或"一律报 PASS"的改动都会被抓住。

    临时目录写在脚本旁边（不用 `tempfile`：Windows 沙箱下它在清理时会 chmod 失败，
    见 `check_console_safe.py` 的同一条注释）。
    """
    import shutil
    print("=" * 78)
    print("artifact_index 自证（五个并排场景）")
    print("=" * 78)
    base = Path(__file__).resolve().parent / "_artifact_index_tmp"
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    ok = True
    try:
        # 场景 1：文档点名了一个哪里都没有的文件 ⇒ 必须报
        w1 = base / "dangling"
        (w1 / "docs").mkdir(parents=True)
        (w1 / "docs" / "MAP.md").write_text("见 `nowhere.log` 与 `exists.py`。\n", encoding="utf-8")
        (w1 / "exists.py").write_text("print(1)\n", encoding="utf-8")
        r1 = _run(w1, [])
        # 断言必须落在**未解析引用那一段**里：宽松地断言"整份输出含这个名字"
        # 会被别的表格蒙对（`check_collab_artifacts` 的负样例断言就踩过这个坑）。
        hit = "nowhere.log" in _dangling_section(r1)
        print(f"{'PASS' if hit else 'FAIL'}  场景1 未解析引用被报出={hit}")
        ok &= hit

        # 场景 2：同样点名，但文件在 --root 给的外部根里 ⇒ 不该报
        w2 = base / "external_root"
        (w2 / "docs").mkdir(parents=True)
        (w2 / "docs" / "MAP.md").write_text("见 `data.csv`。\n", encoding="utf-8")
        extroot = base / "ext"
        extroot.mkdir(parents=True)
        (extroot / "data.csv").write_text("a,b\n", encoding="utf-8")
        r2 = _run(w2, [str(extroot)])
        good = "data.csv" not in _dangling_section(r2)
        print(f"{'PASS' if good else 'FAIL'}  场景2 外部根里的文件不被误报={good}")
        ok &= good

        # 场景 3：豁免表里的名字 ⇒ 不该报
        w3 = base / "allowlisted"
        (w3 / "docs").mkdir(parents=True)
        (w3 / "docs" / "MAP.md").write_text("见 `layout.json`。\n", encoding="utf-8")
        r3 = _run(w3, [])
        good = "layout.json" not in _dangling_section(r3)
        print(f"{'PASS' if good else 'FAIL'}  场景3 显式豁免的名字不被误报={good}")
        ok &= good

        # 场景 4：全都引用得到 ⇒ 退出码 0
        w4 = base / "clean"
        (w4 / "docs").mkdir(parents=True)
        (w4 / "docs" / "MAP.md").write_text("见 `thing.json`。\n", encoding="utf-8")
        (w4 / "thing.json").write_text("{}", encoding="utf-8")
        r4 = _run(w4, [])
        good = ("PASS  未解析引用 0 个" in r4)
        print(f"{'PASS' if good else 'FAIL'}  场景4 全齐时不报={good}")
        ok &= good

        # 场景 5：工作区文档引用 **skill 自己的文件** ⇒ 不该报（skill 目录是自动外部根）。
        # 这一条治的是本脚本自己的头号误报：第 28 轮实跑时 16 条"未解析"里 12 条属于此类。
        w5 = base / "cites_skill"
        (w5 / "docs").mkdir(parents=True)
        (w5 / "docs" / "CHARTER.md").write_text("判据见 `subproc.py`。\n", encoding="utf-8")
        r5 = _run(w5, [])
        good = ("subproc.py" not in _dangling_section(r5))
        print(f"{'PASS' if good else 'FAIL'}  场景5 引用 skill 目录里的文件不被误报={good}")
        ok &= good
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("-" * 78)
    print("artifact_index 自证结果:", "全部通过" if ok else "有 FAIL")
    return 0 if ok else 1


def _run(ws: Path, roots):
    cmd = [sys.executable, str(Path(__file__).resolve()),
           "--workspace", str(ws), "--out", str(ws / "INDEX.md")]
    for r in roots:
        cmd += ["--root", r]
    return subproc.run_text(cmd).stdout


def _dangling_section(out: str) -> str:
    """只取"未解析引用"那一段 —— 避免给"这个文件存在吗"这类字样误判。"""
    i = out.find("**未解析引用")
    return out[i:] if i >= 0 else ""


if __name__ == "__main__":
    sys.exit(main())
