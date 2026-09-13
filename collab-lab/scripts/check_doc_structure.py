#!/usr/bin/env -S python -u
# -*- coding: utf-8 -*-
r"""check_doc_structure.py —— 散文文件的**身份完整性**：编号标题必须唯一、连续。

## 它治的是哪句话

> "我**无法利用** agent 所写代码产出的结果和数据。"

在这一层，它的形态是：**一段内容还在，但它的小节身份没了。**

实测（第 33、35 轮，**同一个错犯了两次**）：我用"把某标题替换成新内容"的方式
给 `LESSONS-general.md` 插新条目，**两次都吃掉了 `### B37.` 的标题** ——
正文还在，却成了一个没有身份的段落，挂在别的小节下面。
**没有任何东西会报**：文件照样能读、正文照样能被 grep 到、引用也还查得到。
两次都是靠临时自查（标题唯一 + 数量 + 顺序）发现的。

⇒ 判据：**同一个错犯两次，就该把它固化成一条命令**，而不是继续靠临时自查。
动作级的修法也写在这里：给散文文件插内容时，`old_string` 取**下一节的标题**，
`new_string` = **新内容 + 换行 + 同一个标题**（"我记得要补回来"不是机制）。

## 检查什么

对每个文件，按字母前缀分组（`### B37.` → 前缀 `B`、编号 37），报两件事：
1. **重复**：同一编号出现多次（通常意味着"插入时把标题复制了一遍"）；
2. **缺号**：`1..max` 里缺了某个号（**通常意味着某个标题被吃掉了**）。

用法：
    python scripts/check_doc_structure.py <文件> [<文件> ...]
    python scripts/check_doc_structure.py --self-test
退出码：0 = 结构完整；1 = 有重复或缺号；2 = 用法错误。
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import subproc  # noqa: E402,F401

HEADING_RE = re.compile(r"^#{2,4}\s+([A-Za-z]{1,3})(\d{1,3})[\.、\s]", re.M)


def analyze(path: Path):
    """返回 (按前缀分组的编号表, 问题列表)。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    groups: dict[str, list[int]] = {}
    for pre, num in HEADING_RE.findall(text):
        groups.setdefault(pre.upper(), []).append(int(num))
    problems = []
    for pre, nums in sorted(groups.items()):
        dup = sorted({n for n in nums if nums.count(n) > 1})
        if dup:
            problems.append(f"前缀 {pre}：编号重复 {dup}")
        missing = [n for n in range(1, max(nums) + 1) if n not in nums]
        if missing:
            problems.append(f"前缀 {pre}：编号缺 {missing}"
                            "（缺号通常意味着某个标题被吃掉了）")
    return groups, problems


def main() -> int:
    ap = argparse.ArgumentParser(description="散文文件的编号标题唯一性与连续性")
    ap.add_argument("files", nargs="*")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()
    if args.self_test:
        return _self_test()
    if not args.files:
        ap.print_help()
        return 2
    ok = True
    print("=" * 78)
    print("散文文件结构：编号标题必须唯一且连续")
    print("=" * 78)
    for f in args.files:
        p = Path(f)
        if not p.exists():
            print(f"FAIL  {p} 不存在")
            ok = False
            continue
        groups, problems = analyze(p)
        summary = "、".join(f"{k}:{len(v)}" for k, v in sorted(groups.items()))
        if problems:
            ok = False
            print(f"FAIL  {p}  （{summary}）")
            for x in problems:
                print(f"        x {x}")
        else:
            print(f"PASS  {p}  （{summary}）")
    print("-" * 78)
    print("⇒ 结构完整。" if ok else "⇒ 有重复或缺号：先补回标题，再继续。")
    return 0 if ok else 1


def _self_test() -> int:
    """三个并排场景：干净 / 重复 / 缺号（缺号正是"标题被吃掉"的形态）。"""
    print("=" * 78)
    print("check_doc_structure 自证（三个并排场景）")
    print("=" * 78)
    base = Path(__file__).resolve().parent / "_docstruct_tmp"
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    ok = True
    try:
        cases = [
            ("clean", "### B1. a\n\n### B2. b\n\n### B3. c\n", []),
            ("duplicate", "### B1. a\n\n### B2. b\n\n### B2. b again\n", ["重复"]),
            ("missing", "### B1. a\n\n### B3. c\n", ["缺"]),
        ]
        for name, text, must in cases:
            p = base / f"{name}.md"
            p.write_text(text, encoding="utf-8")
            groups, problems = analyze(p)
            good = (bool(problems) == bool(must)) and all(
                any(m in x for x in problems) for m in must)
            ok &= good
            print(f"{'PASS' if good else 'FAIL'}  {name:10s} problems={problems}")
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("-" * 78)
    print("check_doc_structure 自证结果:", "全部通过" if ok else "有 FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
