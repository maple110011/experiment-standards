#!/usr/bin/env python3
"""check_links.py - 校验仓库内 Markdown 的相对链接是否都能解析.

只检查相对路径链接（跳过 http(s)/mailto/#/tel）；锚点只取 # 前的路径部分。
用法（仓库根目录）：python scripts/check_links.py [--root DIR]
退出码：0 全通过；1 有断链。
"""
import argparse
import os
import re
import sys

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "vendor"}
PATTERN = re.compile(r"\[[^\]]*\]\(([^)\s]+)")


def iter_markdown(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.lower().endswith(".md"):
                yield os.path.join(dirpath, name)


def check(root):
    bad = []
    total = 0
    for path in iter_markdown(root):
        text = open(path, encoding="utf-8", errors="replace").read()
        for match in PATTERN.finditer(text):
            target = match.group(1).strip().rstrip(")")
            if re.match(r"^(https?:|mailto:|#|tel:)", target):
                continue
            total += 1
            frag = target.split("#")[0]
            if not frag:
                continue
            resolved = os.path.normpath(os.path.join(os.path.dirname(path), frag))
            if not os.path.exists(resolved):
                bad.append((os.path.relpath(path, root), target))
    return total, bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    args = ap.parse_args()
    root = os.path.abspath(args.root)
    total, bad = check(root)
    print(f"检查 {total} 条相对链接，断链 {len(bad)} 条")
    for rel, target in bad:
        print(f"  BROKEN  {rel} -> {target}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
