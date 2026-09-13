#!/usr/bin/env -S python -u
# -*- coding: utf-8 -*-
r"""check_genericity.py —— **机制层不许依赖具体课题**。

## 它治的是哪一句话

> "作为一个 skill，它应该是普适的。"

用户提出这个疑虑时，本 skill 已经在**一个具体竞赛**里跑了几十轮。风险有两种，形状完全不同：

| 形态 | 例子 | 后果 | 本脚本管不管 |
|---|---|---|---|
| **耦合** | 代码里写死 `ID_KEYS = ("切片 ID", "故障判断")`、默认数据根写死课题名 | 换一个课题，脚本**直接跑错或跑不了** | **管** |
| **证据** | 注释里写"某次三份提交的 README 命令是复制的，交 11 片复现成 34 片" | 换课题照样成立，而且**这正是规则有说服力的原因** | **不管**（且应当保留） |

把两者混为一谈会走向两个坏结局：要么"清洗"掉全部具体经验（规则变成空洞口号，
本 skill 的 `B7/B8` 早就说过：**被证伪的结论会复活，因为没人记得代价**）；
要么放任耦合（skill 换个课题就废）。

## 判据（只查"判据层"，不查文档）

1. `scripts/*.py` 里**非 docstring 的字符串常量**不得含实例专有词
   —— 字符串常量就是"代码在运行时真正依赖的那个名字"；
2. `assets/templates/*.md` 的正文不得含实例专有词（`<...>` 占位符内豁免
   —— 那是给人看的填写示例）；
3. **模块/类/函数 docstring、以及 `#` 注释，一律不查** —— 证据允许、而且应当留在那里；
4. 确有必要的例外，在**同一行或上一行**写 `# genericity-ok: <理由>`。
   给豁免开口子是故意的：**有理由的例外看得见，比偷偷绕过强**（与 `B27` 的"显式登记"同一条纪律）。

## 它为什么必须是脚本，而不是一次人工清理

"这次我洗干净了"不是机制：下一个课题的教训会再被写进代码，而下一次没人会想起要洗。
⇒ 判据：**这条规则现在靠什么被强制执行？** 答不出，就等于没有。

用法：
    python scripts/check_genericity.py [--skill <skill 目录>] [--json]
    python scripts/check_genericity.py --self-test
退出码：0 = 机制层干净；1 = 有耦合（列出来）；2 = 用法错误。
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent

sys.path.insert(0, str(HERE))
import subproc  # noqa: E402,F401  （输出兜底：本脚本自己也不许崩）

# 实例专有词：换一个课题就完全不成立的那些（**不含** top_k / Recall / 额度 这类通用词）。
#
# ⚠️ 这份表**本身就必须写出实例词**，否则查不出任何东西 —— 所以它是本检查的
#    **合法例外**，用豁免标记显式声明（这正是本脚本设计的那个口子，见模块 docstring 第 4 条）。
#    注意：豁免的是**这一份判词表**，不是"凡是出现实例词都可以豁免"。
INSTANCE_TOKENS = (
    "锅炉", "结垢", "中石化", "稠油", "注汽", "热采", "预警", "风险预测",  # genericity-ok: 判词表本身
    "boiler", "BOILER", "切片 ID", "切片ID", "故障判断",  # genericity-ok: 判词表本身
)
# 豁免标记：同一行或上一行
OK_RE = re.compile(r"#\s*genericity-ok\s*:\s*\S+")
# 只在"判据层"扫：脚本里的字符串常量 + 模板正文
SCAN_GLOBS = ("scripts/*.py", "assets/templates/*.md")
PLACEHOLDER_RE = re.compile(r"<[^<>\n]*>")


def docstring_nodes(tree: ast.AST) -> set:
    """收集所有 docstring 常量节点的 id（它们**不查**：那是文档，是证据该待的地方）。"""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                out.add(id(body[0].value))
    return out


def scan_python(path: Path) -> list:
    """返回 [(行号, 命中词, 片段)]，只看非 docstring 的字符串常量。"""
    src = path.read_text(encoding="utf-8", errors="replace")
    lines = src.splitlines()
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        return [(e.lineno or 0, "（语法错误，无法静态扫描）", str(e))]
    skip = docstring_nodes(tree)
    hits = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if id(node) in skip:
            continue
        # 占位符里的内容是**填写示例**，不算耦合 —— 这条豁免对模板与脚本**一视同仁**
        # （脚本里也可能有"要写进模板的示例文本"）。`ID_KEYS = ("切片 ID",)` 这种**没有** `<>`
        # 的真实默认值照样会被抓住，所以放宽这里不会漏掉真正的耦合。
        value = PLACEHOLDER_RE.sub("", node.value)
        for tok in INSTANCE_TOKENS:
            if tok in value:
                ln = node.lineno
                ctx = "\n".join(lines[max(0, ln - 2):ln])       # 上一行 + 本行
                if OK_RE.search(ctx):
                    continue
                hits.append((ln, tok, node.value.strip()[:70]))
                break
    return hits


def scan_template(path: Path) -> list:
    """模板正文：先把 `<...>` 占位符挖掉，再找实例词。"""
    hits = []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    for i, ln in enumerate(lines, 1):
        stripped = PLACEHOLDER_RE.sub("", ln)
        for tok in INSTANCE_TOKENS:
            if tok not in stripped:
                continue
            ctx = "\n".join(lines[max(0, i - 2):i])      # 上一行 + 本行
            if OK_RE.search(ctx):
                break
            hits.append((i, tok, ln.strip()[:70]))
            break
    return hits


def scan(skill: Path) -> dict:
    found = {}
    for pat in SCAN_GLOBS:
        for p in sorted(skill.glob(pat)):
            hits = scan_python(p) if p.suffix == ".py" else scan_template(p)
            if hits:
                found[p.relative_to(skill).as_posix()] = hits
    return found


def main() -> int:
    ap = argparse.ArgumentParser(description="机制层通用性检查（实例耦合 vs 允许的证据）")
    ap.add_argument("--skill", default=str(SKILL))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return _self_test()
    skill = Path(args.skill)
    found = scan(skill)
    n = sum(len(v) for v in found.values())
    if args.json:
        print(json.dumps({"skill": str(skill), "hits": found, "count": n},
                         ensure_ascii=False, indent=1))
        return 1 if n else 0
    print("=" * 84)
    print(f"通用性检查：{skill}")
    print("=" * 84)
    print("  扫的是**判据层**：scripts/*.py 的非 docstring 字符串常量 + templates 正文")
    print("  不扫：docstring、# 注释、references/、assets/samples/ —— 那些地方允许引用具体课题")
    print(f"  规则：实例专有词 {len(INSTANCE_TOKENS)} 个；例外需写 `# genericity-ok: <理由>`")
    print("-" * 84)
    if not found:
        print("⇒ 机制层干净：脚本与模板都不依赖任何具体课题。")
        return 0
    for f, hits in found.items():
        print(f"  x {f}（{len(hits)} 处）")
        for ln, tok, frag in hits[:12]:
            print(f"      第 {ln} 行  命中「{tok}」  {frag}")
        if len(hits) > 12:
            print(f"      …… 另有 {len(hits)-12} 处")
    print("-" * 84)
    print(f"⇒ {n} 处实例耦合：把它们改成**参数 / 注册表条目 / 自动识别**，")
    print("   或者在确实必要处写 `# genericity-ok: <理由>`。")
    return 1


def _self_test() -> int:
    """五个并排场景。**关键是后两个**：它们证明本检查分得清"耦合"与"证据"。"""
    print("=" * 84)
    print("check_genericity 自证（五个并排场景）")
    print("=" * 84)
    import shutil
    import tempfile

    base = Path(tempfile.gettempdir()) / f"gen_selftest_{id(object())}"

    def build(case: str, py: dict, tmpl: str = "") -> Path:
        """每个场景**各建一个根**：共用根会让场景互相污染（第一版就是这么错的）。"""
        root = base / case
        (root / "scripts").mkdir(parents=True, exist_ok=True)
        if tmpl:
            (root / "assets" / "templates").mkdir(parents=True, exist_ok=True)
            (root / "assets" / "templates" / "T.template.md").write_text(tmpl, encoding="utf-8")
        for name, body in py.items():
            (root / "scripts" / name).write_text(body, encoding="utf-8")
        return root

    cases = [
        # ① 干净：代码层没有任何实例词
        ("clean", {"clean.py": 'import argparse\n'
                              'ap = argparse.ArgumentParser()\n'
                              'ap.add_argument("--id-col", default=None)\n'}, "", 0, 0),
        # ② 耦合：字符串常量里写死实例列名 ⇒ 必须报
        #    （这几行是**故意造出来的耦合样例**，必须含实例词才测得到检测能力 ⇒ 豁免）
        ("coupled", {"coupled.py": 'ID_KEYS = ("切片 ID", "id")\n'  # genericity-ok: 自证用的耦合样例
                     }, "", 1, 1),
        # ③ 只是文档：docstring 与 # 注释里提到实例 ⇒ **必须通过**
        ("doc_only", {"doc_only.py": '"""某锅炉课题里，切片 ID 那列曾经认错。"""\n'  # genericity-ok: 自证样例
                                     'X = 1  # 锅炉课题的教训：列名要可配\n'}, "", 0, 0),
        # ④ 有理由的例外：带豁免标记 ⇒ **必须通过**
        ("exempt", {"exempt.py":
                    '# genericity-ok: 首个实例的公式名，作为注册表里的一个条目保留\n'
                    'NAME = "中石化稠油热采公式"\n'}, "", 0, 0),
        # ⑤ 模板：实例词只出现在 `<...>` 占位符里 ⇒ **必须通过**
        ("tmpl_placeholder", {},
         "| 字段 | 说明 |\n|---|---|\n| <列名> | <例如：切片 ID> |\n", 0, 0),
        # ⑥ 模板：实例词写在正文里 ⇒ 必须报（同样是**故意造的样例** ⇒ 豁免）
        ("tmpl_body", {}, "| 列名 | 就是切片 ID 那一列 |\n", 1, 1),  # genericity-ok: 自证样例
    ]
    ok = True
    try:
        for name, py, tmpl, n_expect, exp_code in cases:
            root = build(name, py, tmpl)
            found = scan(root)
            flat = [(f, tok) for f, hs in found.items() for _, tok, _ in hs]
            code = 1 if flat else 0
            good = (len(flat) == n_expect) and (code == exp_code)
            ok &= good
            shown = f"{flat[0][1]}" if flat else "—"
            print(f"{'PASS' if good else 'FAIL'}  {name:18s} 命中 {len(flat)}（期望 {n_expect}）"
                  f"  退出码 {code}（期望 {exp_code}）  首个命中：{shown}")
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("-" * 84)
    print("check_genericity 自证结果:", "全部通过" if ok else "有 FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
