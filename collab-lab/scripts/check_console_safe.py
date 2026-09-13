#!/usr/bin/env python -u
# -*- coding: utf-8 -*-
r"""check_console_safe.py —— 脚本的输出必须能在控制台的编码里印出来
（或者显式加兜底），否则它会**在报告那一行崩掉**。

## 为什么需要它（立此脚本的那次失效：真丢了一整轮计算）

一个跑了 **327 秒**的合成扫描，在最后的"打印自检"那一行抛
`UnicodeEncodeError`（`⓪` U+24EA 在 cp936 里不存在），而它的 JSON 结果
**写在报告之后** ⇒ **整轮 6480 格 × 5 种子的计算全部丢失**，只能重跑。

这和 `subproc.py` 治的是**同一个病的第二个现场**：
上一轮修好的是 **skill 自己的脚本**（`goal_guard.py` / `check_collab_artifacts.py`），
而**工作区里那些真正产出实验数据的脚本**没有被覆盖 —— 偏偏它们才是跑得最久的。

## 判据（机械、精确，不用启发式识别"这行是不是报告"）

对每个 `.py` 文件：
1. 取出**字符串字面量**里的所有非 ASCII 字符（注释不算 —— 注释不会被执行，也不会被打印）；
2. 若这些字符**都能**用控制台编码编出来 ⇒ **PASS**；
3. 否则，看文件里有没有**输出兜底**（`reconfigure(...)` + `errors="replace"`）
   —— 有 ⇒ **PASS（已兜底，不可编码的字降级成 `?`）**；没有 ⇒ **FAIL**，报出码位与行号。

**为什么不检查"报告里那些字印得好看不好看"**：兜底会把 `⇒` 印成 `?`。
"不崩"与"好看"是两件事；本脚本只管**不崩**，好看由人看着改。
（这一条写下来是因为我自己第一版用了 emoji `⏳`，兜底后成了一个孤零零的 `?`。）

## 它**不**检查什么（说清楚，免得被当成全覆盖）

- **不检查"结果是否先落盘再打印"**：那是个顺序要求，静态不可判定
  （哪一行才是"报告"？`print` 也可能是进度条）。这条纪律写在
  `references/human-facing-output.md`，**是文档纪律，本脚本不假装能查它**。
- **不检查 stdout 之外的东西**（日志文件、异常文本里的字符）。

用法：
    python scripts/check_console_safe.py <file.py> [more.py ...]
    python scripts/check_console_safe.py --encoding cp936 <file.py>
退出码：0 = 全部通过；1 = 有 FAIL；2 = 用法错误。
"""
from __future__ import annotations

import argparse
import ast
import io
import locale
import re
import sys
import tokenize
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import subproc  # noqa: E402,F401  （自身输出也不许崩；见 subproc.py）

# 输出兜底的两种可接受写法（只看语义特征，不要求逐字相同）：
#   ① 本文件自己 `reconfigure(errors="replace")`；
#   ② `import subproc` —— 它在 import 时就给本进程装上兜底（见 subproc.py 的第三条纪律）。
#      skill 自己的脚本走的是 ②，工作区里的一次性脚本可以直接抄 ① 的三行。
HARDEN_PAT = re.compile(r"reconfigure\s*\([^)]*errors\s*=\s*['\"]replace['\"]"
                        r"|^\s*import\s+subproc\b", re.S | re.M)


def console_encoding() -> str:
    """控制台的编码 —— **不能**用会被环境变量污染的那个函数。

    ⚠️ 立此实现的失效（本脚本第一版踩的）：用 `locale.getpreferredencoding(False)`，
    它在 **`PYTHONUTF8=1` 下返回 `utf-8`**（UTF-8 模式的语义就是覆盖区域编码）。
    于是这条检查在**被 `subproc.run_text` 调用**时（那里会注入 `PYTHONUTF8=1`）
    把 `⇒` 判成"能编出来" ⇒ 自证里的 `no_harden` 用例判出 True ⇒ **自证自己失败**；
    而**单独手工跑同一个脚本**又是对的 —— 典型的"两种调用方式行为不同"。
    `locale.getencoding()`（3.11+）明确**忽略 UTF-8 模式**，返回真正的区域编码。
    """
    try:
        if hasattr(locale, "getencoding"):
            return locale.getencoding()
        return locale.getpreferredencoding(False) or "utf-8"
    except Exception:
        return "utf-8"


def unencodable(text: str, enc: str) -> list[str]:
    bad = []
    for ch in text:
        if ord(ch) < 128:
            continue
        try:
            ch.encode(enc)
        except UnicodeEncodeError:
            bad.append(ch)
    return bad


def docstring_spans(tree: ast.AST, src: str) -> list[tuple[int, int, int, int]]:
    """模块/类/函数**文档字符串**的 (lineno, end_lineno, col, end_col)。

    文档字符串是字符串字面量，但**不会被打印**；把它算进来会产生误报
    （而"校验器误报比不报更糟"，见 LESSONS-general D4）。
    """
    spans = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            c = first.value
            spans.append((c.lineno, getattr(c, "end_lineno", c.lineno),
                          c.col_offset, getattr(c, "end_col_offset", c.col_offset)))
    return spans


def in_spans(tok, spans) -> bool:
    for (l0, l1, c0, c1) in spans:
        if l0 <= tok.start[0] and tok.end[0] <= l1:
            return True
    return False


STRING_TYPES = {tokenize.STRING}
for _n in ("FSTRING_MIDDLE", "FSTRING_START", "FSTRING_END"):
    if hasattr(tokenize, _n):
        STRING_TYPES.add(getattr(tokenize, _n))


def check_file(path: Path, enc: str) -> bool:
    src = path.read_text(encoding="utf-8")
    hardened = bool(HARDEN_PAT.search(src))
    try:
        tree = ast.parse(src)
    except SyntaxError as e:
        print(f"FAIL  {path.name}: 语法错误，无法解析（{e}）")
        # BOM 是**最常见的那个原因**，而且最容易被误判成"文件内容坏了"。
        # 它的来路通常不是人写坏，而是**工具往返**：PowerShell
        # `Set-Content -Encoding UTF8`（含 `-NoNewline`）会加 BOM。
        # Python 仍能运行带 BOM 的脚本 ⇒ 只有做静态分析的这一层会炸（LESSONS D3b）。
        if src.startswith("\ufeff"):
            print("      ⇒ 文件开头有 **UTF-8 BOM**（U+FEFF）。内容没坏，只是多了 3 个字节。")
            print("         修法（按字节去掉，别用编辑器猜）：")
            print("           python -c \"import pathlib;p=pathlib.Path('X.py');"
                  "b=p.read_bytes();p.write_bytes(b[3:] if b[:3]==b'\\xef\\xbb\\xbf' else b)\"")
            print("         更根本的：**不要用 PowerShell 往返改 Python 源码**。")
        return False
    spans = docstring_spans(tree, src)

    found: list[tuple[int, str]] = []      # (行号, 字符)
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type not in STRING_TYPES:
                continue
            if in_spans(tok, spans):
                continue
            for ch in unencodable(tok.string, enc):
                found.append((tok.start[0], ch))
    except tokenize.TokenError as e:
        print(f"FAIL  {path.name}: 无法完整分词（{e}）")
        return False

    if not found:
        print(f"PASS  {path.name}: 打印用的字符串在 {enc} 里都能编出来")
        return True
    cps = sorted({f"U+{ord(c):04X}" for _, c in found})
    if hardened:
        print(f"PASS  {path.name}: 有 {len(found)} 处不可编码字符（{' '.join(cps)}），"
              f"但文件里有输出兜底 ⇒ 会降级成 `?` 而不是崩")
        return True
    print(f"FAIL  {path.name}: {len(found)} 处不可打印字符（{' '.join(cps)}）且**没有输出兜底**")
    print("      ⇒ 它会在打印那一行抛 UnicodeEncodeError。二选一：")
    print("         ① 改成能在该编码里印出来的字（例如 `⇒` → `=>`、`⓪` → `[0]`）；")
    print("         ② 在文件顶部加兜底：")
    print("            for _s in (sys.stdout, sys.stderr):")
    print("                try: _s.reconfigure(errors=\"replace\")")
    print("                except Exception: pass")
    for ln, ch in found[:8]:
        print(f"         L{ln}: {ch!r} (U+{ord(ch):04X})")
    if len(found) > 8:
        print(f"         … 另有 {len(found)-8} 处")
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="检查脚本的输出能否在控制台编码里印出来")
    ap.add_argument("files", nargs="*")
    ap.add_argument("--encoding", default=None,
                    help="控制台编码（默认取 locale.getpreferredencoding()）")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    enc = args.encoding or console_encoding()

    if args.self_test:
        return _self_test(enc)
    if not args.files:
        # 无参数 = **lint 本 skill 自己的脚本**（这是它最常被用到的形态）
        files = sorted(str(p) for p in (Path(__file__).resolve().parent).glob("*.py"))
        if not files:
            ap.print_help()
            return 2
        args.files = files
    print("=" * 74)
    print(f"控制台编码 {enc}：字符串字面量里不可编码的字符（文档字符串不算）")
    print("=" * 74)
    ok = True
    for f in args.files:
        p = Path(f)
        if not p.exists():
            print(f"FAIL  {p}: 不存在")
            ok = False
            continue
        ok &= check_file(p, enc)
    print("-" * 74)
    print("结果:", "全部通过" if ok else "有 FAIL")
    return 0 if ok else 1


def _self_test(enc: str) -> int:
    """两向自检：**没有兜底且含不可编码字符**必须 FAIL；
    同样内容**加上兜底**必须 PASS；**纯 ASCII** 必须 PASS；**带 BOM** 必须 FAIL。
    单场景抓不住"检查恒真/恒假"（`B28` 第 ② 项）。"""
    import shutil
    print("=" * 74)
    print(f"check_console_safe 自证（控制台编码 {enc}）")
    print("=" * 74)
    bad = '#!/usr/bin/env python\nimport sys\nprint("结论 ⇒ 成立")\n'
    good = ('#!/usr/bin/env python\nimport sys\n'
            'for _s in (sys.stdout,):\n'
            '    try: _s.reconfigure(errors="replace")\n'
            '    except Exception: pass\n'
            'print("结论 ⇒ 成立")\n')
    plain = '#!/usr/bin/env python\nprint("ascii only")\n'
    doc = '#!/usr/bin/env python\n"""docstring with ⇒ inside, not printed"""\nprint("ok")\n'
    # 场景 5：带 UTF-8 BOM 的脚本。内容完全正确，只是开头多了 3 个字节。
    # 立此的原因（第 28 轮实跑记录）：我用 PowerShell 往返改了两处横幅，
    # **两次都被加了 BOM**，而脚本照跑不误 ⇒ 只有这一层静态检查会炸。
    # 所以要有一条**固定住"BOM 必须判不合格"**的场景，否则"语法错误就放行"的改动没人拦。
    bom = '\ufeff#!/usr/bin/env python\nprint("ascii only")\n'
    ok = True
    # ⚠️ 临时目录写在**脚本旁边**，不用 `tempfile.TemporaryDirectory()`：
    #    在 Windows 沙箱下后者会在清理时 `chmod` 失败抛 PermissionError
    #    （本脚本第一版就是这么崩的，于是"自证"自己崩了）。其余 fixtures 也用这个写法。
    d = Path(__file__).resolve().parent / "_console_safe_tmp"
    if d.exists():
        shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True, exist_ok=True)
    try:
        for name, text, expect in (("no_harden", bad, False),
                                   ("harden", good, True),
                                   ("ascii", plain, True),
                                   ("docstring", doc, True),
                                   ("bom", bom, False)):
            p = d / f"{name}.py"
            p.write_text(text, encoding="utf-8")
            got = check_file(p, enc)
            good_ = (got == expect)
            ok &= good_
            print(f"{'PASS' if good_ else 'FAIL'}  {name:10s} 判定={got}（期望 {expect}）")
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print("-" * 74)
    print("check_console_safe 自证结果:", "全部通过" if ok else "有 FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
