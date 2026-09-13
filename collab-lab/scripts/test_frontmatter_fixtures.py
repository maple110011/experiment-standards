#!/usr/bin/env python -u
# -*- coding: utf-8 -*-
r"""`validate_frontmatter.py` 的 fixtures：**每条规则一条反例 + 一个正例对照**。

## 为什么它此前是"已知缺口"，以及为什么必须补

原版本**没有 `main()`、没有退出码** —— 它打印 `PASS/FAIL` 却永远 `exit 0`。
于是它在任何自动化里都是恒成功的：`... && echo ok` 永远 `ok`，
`--self-test` 里也没法断言它。**"看起来在检查、而且真的会打印 FAIL"**
比不检查更危险，因为它会让人以为这道闸门是关着的。

第 23 轮重写为 `check_skill() → (problems, notes)` + `main() → 退出码`，
**本文件就是那个改动的验收**：每条规则一个反例（必须被报出），
外加一个全合法正例（**必须不被报**，否则"一律报错"也会通过）。

## 场景

| 场景 | 构造 | 期望 |
|---|---|---|
| `ok` | name/description 全合法 | problems 为空 |
| `no_name` / `no_description` | 缺字段 | 各自被报 |
| `angle` | description 含 `<` | 报「angle brackets」 |
| `too_long` | description 1025 字符 | 报「too long」 |
| `not_kebab` | name 含下划线/大写 | 报「kebab-case」 |
| `edge_hyphen` | name 以 `-` 结尾 | 报「start/end with hyphen」 |
| `double_hyphen` | name 含 `--` | 报「contain '--'」 |
| `unknown_key` | 多一个未登记键 | 报「Unexpected key」 |
| `dsh_key` | 只有宿主扩展键 `argument-hint` | **不报**（登记为已知） |
| `bad_yaml` | frontmatter 不是 YAML 字典 | 报「must be a YAML dictionary」 |
| `no_frontmatter` | 文件不以 `---` 开头 | 报「No YAML frontmatter」 |
| `missing_file` | 目录里没有 SKILL.md | 报「SKILL.md not found」 |
| `exit_code` | CLI 跑一个坏目录 / 一个好目录 | 分别 1 / 0 |

用法：`python scripts/test_frontmatter_fixtures.py`
"""
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import subproc  # noqa: E402
from validate_frontmatter import check_skill  # noqa: E402  （直接测函数，不靠解析输出）

SCRIPT = HERE / "validate_frontmatter.py"
OK_DESC = "Use this skill when you need to keep track of a multi-round collaboration."


def skill(name="demo-skill", desc=OK_DESC, extra="", body="# demo\n", raw=None):
    if raw is not None:
        return raw
    fm = f"name: {name}\ndescription: {desc}\n{extra}"
    return f"---\n{fm}---\n\n{body}"


CASES = [
    ("ok", skill(), []),
    ("no_name", skill(raw=f"---\ndescription: {OK_DESC}\n---\n\nx\n"), ["Missing 'name'"]),
    ("no_description", skill(raw="---\nname: demo-skill\n---\n\nx\n"), ["Missing 'description'"]),
    ("angle", skill(desc="Use when X < Y and Z > W."), ["angle brackets"]),
    ("too_long", skill(desc="a" * 1025), ["Description too long"]),
    ("not_kebab", skill(name="Demo_Skill"), ["kebab-case"]),
    ("edge_hyphen", skill(name="demo-"), ["start/end with hyphen"]),
    ("double_hyphen", skill(name="demo--skill"), ["contain '--'"]),
    ("unknown_key", skill(extra="owner: me\n"), ["Unexpected key"]),
    ("dsh_key", skill(extra="argument-hint: \"[x]\"\n"), []),
    ("bad_yaml", skill(raw="---\n- just\n- a\n- list\n---\n\nx\n"),
     ["must be a YAML dictionary"]),
    ("no_frontmatter", skill(raw="# no frontmatter here\n"), ["No YAML frontmatter"]),
    # 第 38 轮补：**篇幅预算**。SKILL.md 每次触发都进上下文，它自己有预算 ——
    # 实测这东西一路长到 653 行而没有任何东西会报。
    ("body_600", skill(body="# d\n" + "填充\n" * 600), ["正文"]),
    # 反向：500–600 只算 WARN，**不许判成错误**（方法论说的是"<500 理想"，"理想"不该判错）
    ("body_520", skill(body="# d\n" + "填充\n" * 520), []),
]


def main():
    base = HERE / "_frontmatter_fixtures_tmp"
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    print("=" * 78)
    print("validate_frontmatter fixtures（每条规则一个反例 + 一个全合法正例）")
    print("=" * 78)
    ok = True
    try:
        for name, text, want in CASES:
            d = base / name
            d.mkdir()
            (d / "SKILL.md").write_text(text, encoding="utf-8")
            problems, notes = check_skill(d)
            if want:
                good = all(any(w in p for p in problems) for w in want) and bool(problems)
            else:
                good = not problems
            print(f"{'PASS' if good else 'FAIL'}  {name:16s} problems={len(problems)} "
                  f"（期望 {('报出 ' + ','.join(want)) if want else '不报'}）")
            if not good:
                for p in problems:
                    print(f"        | {p[:92]}")
            ok &= good

        # missing_file：目录里没有 SKILL.md
        d = base / "missing_file"
        d.mkdir()
        problems, _ = check_skill(d)
        good = any("not found" in p for p in problems)
        print(f"{'PASS' if good else 'FAIL'}  {'missing_file':16s} problems={len(problems)}"
              f"（期望 报出 not found）")
        ok &= good

        # 孤儿 reference：`references/x.md` 存在但没有任何文档引用它 ⇒ 没人会读
        # （与"产出包里的文件没被入口点名"同一个病：`LESSONS-general` B53）
        d = base / "orphan_ref"
        (d / "references").mkdir(parents=True)
        (d / "SKILL.md").write_text(skill(), encoding="utf-8")
        (d / "references" / "orphan.md").write_text("# 没人引用我\n", encoding="utf-8")
        problems, _ = check_skill(d)
        good = any("孤儿 reference" in p for p in problems)
        print(f"{'PASS' if good else 'FAIL'}  {'orphan_ref':16s} problems={len(problems)}"
              f"（期望 报出 孤儿 reference）")
        if not good:
            for p in problems:
                print(f"        | {p[:92]}")
        ok &= good

        # 反向：被引用的 reference **不许**被误报
        d2 = base / "cited_ref"
        (d2 / "references").mkdir(parents=True)
        (d2 / "SKILL.md").write_text(
            skill(body="# d\n\n见 [x.md](./references/x.md)\n"), encoding="utf-8")
        (d2 / "references" / "x.md").write_text("# 有人引用我\n", encoding="utf-8")
        problems2, _ = check_skill(d2)
        good = not any("孤儿" in p for p in problems2)
        print(f"{'PASS' if good else 'FAIL'}  {'cited_ref':16s} problems={len(problems2)}"
              f"（期望 不报孤儿）")
        ok &= good

        # 退出码：坏目录 ⇒ 1；好目录 ⇒ 0（**这正是原版本缺的那一半**）
        for tag, target, want_code in (("bad", base / "angle", 1), ("good", base / "ok", 0)):
            r = subproc.run_text([sys.executable, str(SCRIPT), str(target)])
            good = (r.returncode == want_code)
            print(f"{'PASS' if good else 'FAIL'}  exit_{tag:11s} 退出码 {r.returncode}"
                  f"（期望 {want_code}）")
            ok &= good
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("-" * 78)
    print("frontmatter fixtures 结果:", "全部通过" if ok else "有 FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
