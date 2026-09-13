#!/usr/bin/env python -u
# -*- coding: utf-8 -*-
r"""按 skill-creator 的规则校验各 skill 的 `SKILL.md` frontmatter。

## 本脚本第 23 轮的重写：它此前**没有退出码**

原版本是"模块级脚本"—— 没有 `main()`、没有 `return`，判定只体现在**打印出来的
`PASS/FAIL` 三行**上。于是它在任何自动化里都是**恒成功**的：
`python scripts/validate_frontmatter.py && echo ok` 永远 `ok`；
`--self-test` 里也没法断言它。

这正是"会产出判定但判定无法被消费"的形态（与 `M-7` 的"文档纪律拦不住"同族，
只是这里更隐蔽：**它看起来像在检查，而且真的会打印 FAIL**）。
⇒ 重写为：`check_skill()` 返回 (problems, notes)，`main()` 按"有没有 problems"给退出码。

## 顺带修的第二处：路径硬编码

原版本把仓库根写成绝对路径 `E:\software\ss\...`，换个位置就**三个 skill 全报
"SKILL.md not found"**。现在根目录由**脚本位置**推导，也可用 `--root` 覆盖。

## 校验规则（来自 skill-creator）

`name` 必须 kebab-case、≤64 字符、不以 `-` 开头结尾、不含 `--`；
`description` ≤1024 字符、不含尖括号；frontmatter 必须是 YAML 字典；
键必须在 `ALLOWED` 里。`argument-hint` 是**宿主（DSH）扩展键**，登记为已知扩展而非违规。

用法：
    python scripts/validate_frontmatter.py                # 校验本仓库的三个 skill
    python scripts/validate_frontmatter.py <skill 目录>... # 校验指定目录
    python scripts/validate_frontmatter.py --self-test    # fixtures（见同目录 test_frontmatter_fixtures.py）
退出码：0 = 全部 PASS；1 = 有 FAIL；2 = 用法错误。
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

import yaml

# 输出兜底（见 subproc.py 的第三条纪律：报告本身不能崩）
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

ALLOWED = {'name', 'description', 'license', 'allowed-tools', 'metadata', 'compatibility'}
# 宿主（DSH）扩展键：登记为已知，不算违规，但会单独提示
DSH_EXTENSIONS = {'argument-hint'}

FRONTMATTER_RE = re.compile(r'^---\n(.*?)\n---', re.DOTALL)


def check_skill(skill_dir: pathlib.Path):
    """返回 (problems, notes)。**不打印、不 exit** —— 这样 fixtures 能直接断言它。"""
    problems: list[str] = []
    notes: list[str] = []
    skill_md = skill_dir / 'SKILL.md'
    if not skill_md.exists():
        return ['SKILL.md not found'], notes
    content = skill_md.read_text(encoding='utf-8')

    if not content.startswith('---'):
        problems.append('No YAML frontmatter found')
    m = FRONTMATTER_RE.match(content)
    if not m:
        problems.append('Invalid frontmatter format')
        fm = {}
    else:
        try:
            fm = yaml.safe_load(m.group(1))
            if not isinstance(fm, dict):
                problems.append('Frontmatter must be a YAML dictionary')
                fm = {}
        except yaml.YAMLError as e:
            problems.append(f'Invalid YAML in frontmatter: {type(e).__name__}')
            fm = {}

        unexpected = set(fm) - ALLOWED
        hard_unexpected = unexpected - DSH_EXTENSIONS
        if hard_unexpected:
            problems.append(f"Unexpected key(s): {', '.join(sorted(hard_unexpected))}")
        if unexpected & DSH_EXTENSIONS:
            # ---- 宿主扩展键：**登记为已知，但必须把代价说出来**（第 39 轮补）----
            #
            # 立此的原因：`argument-hint` 是本宿主（DSH）用的扩展键，本校验器一直把它
            # 登记为"已知而非违规"。但第 39 轮实测：**上游打包器（skill-creator 的
            # `package_skill.py`）会因此拒收整个 skill** ——
            # `Validation failed: Unexpected key(s): argument-hint`。
            # ⇒ **"我们自己查得过"不等于"生态里打得开"。** 两个校验器对同一个文件
            #   给出了相反的判定，而这件事此前没有任何地方会提醒。
            # 实测结论：**只剥掉这一个键，上游打包就通过**（exit 0）⇒ 冲突只有这一处，
            # 且它是一个**可解释的取舍**，不是 skill 坏了。
            notes.append(
                "宿主扩展键 " + "/".join(sorted(unexpected & DSH_EXTENSIONS))
                + "（DSH 用）⚠️ 但**上游 `package_skill.py` 会因此拒收**"
                  "（它只认 name/description/license/allowed-tools/metadata/compatibility）。"
                  "要分发给上游工具就先剥掉它 —— 剥掉后实测打包通过。")

        if 'name' not in fm:
            problems.append("Missing 'name'")
        else:
            n = str(fm['name']).strip()
            if not re.match(r'^[a-z0-9-]+$', n):
                problems.append(f"Name '{n}' should be kebab-case")
            elif n.startswith('-') or n.endswith('-') or '--' in n:
                problems.append(f"Name '{n}' cannot start/end with hyphen or contain '--'")
            elif len(n) > 64:
                problems.append(f'Name too long ({len(n)})')

        if 'description' not in fm:
            problems.append("Missing 'description'")
        else:
            d = str(fm['description']).strip()
            if '<' in d or '>' in d:
                problems.append('Description cannot contain angle brackets')
            if len(d) > 1024:
                problems.append(f'Description too long ({len(d)} > 1024)')
            else:
                notes.append(f'description {len(d)}/1024 字符')

    body = content[m.end():] if m else content
    n_body = len(body.splitlines())
    notes.append('正文 %d 行' % n_body)

    # ---- 篇幅预算（第 38 轮补）----
    #
    # 立此的原因：SKILL.md 是**每次触发都进上下文**的那一层，它自己有预算。
    # 而本 skill 立文治的正是"信息量超过人的带宽" —— **skill 自己不该成为那个过载源**。
    # 实测：这东西一路长到 **653 行**（方法论的建议是 <500），而**没有任何东西会报**。
    # 修法是把两份明细下沉到 `references/`、SKILL.md 只留索引。
    #
    # 为什么 500 只算 WARN、600 才 FAIL：方法论说的是"<500 理想"，
    # 而"理想"不该判成错误；但超过 600 就已经是它要治的那个病了。
    if n_body > 600:
        problems.append(f'正文 {n_body} 行 > 600 —— 这一层是**每次触发都进上下文**的，'
                        '它自己超预算就等于"skill 成了过载源"。'
                        '把明细下沉到 references/，正文只留索引与指针')
    elif n_body > 500:
        notes.append(f'WARN 正文 {n_body} 行 > 500（方法论建议 <500）—— '
                     '该考虑把明细下沉到 references/ 了')

    # ---- 孤儿 reference（第 38 轮补）----
    #
    # 没被任何文档引用的 `references/*.md` 就是**没人会读的文件** ——
    # 与"产出包里的文件没被入口点名"是同一个病（`LESSONS-general` B53）。
    ref_dir = skill_dir / 'references'
    if ref_dir.is_dir():
        all_text = '\n'.join(p.read_text(encoding='utf-8', errors='replace')
                             for p in skill_dir.rglob('*.md'))
        orphans = [p.name for p in sorted(ref_dir.glob('*.md'))
                   if p.name not in content and all_text.count(p.name) <= 1]
        if orphans:
            problems.append(f'孤儿 reference（没有任何文档引用它们 ⇒ 没人会读）：{orphans}')
        else:
            notes.append(f'references/ 下 {len(list(ref_dir.glob("*.md")))} 份都被引用')
    return problems, notes


def default_targets(root: pathlib.Path):
    """本仓库的三个 skill。根目录由脚本位置推导（`scripts/` 的上一级是 skill，
    再上一级是仓库根）—— 不再硬编码盘符。"""
    return [root / 'collab-lab', root, root / 'bayes-dl-dcu']


def main() -> int:
    ap = argparse.ArgumentParser(description='校验 skill 的 SKILL.md frontmatter')
    ap.add_argument('targets', nargs='*', help='要校验的 skill 目录；不给则校验本仓库的三个')
    ap.add_argument('--root', default=None, help='仓库根（默认由脚本位置推导）')
    args = ap.parse_args()

    here = pathlib.Path(__file__).resolve().parent          # .../collab-lab/scripts
    root = pathlib.Path(args.root).resolve() if args.root else here.parent.parent
    targets = [pathlib.Path(t) for t in args.targets] or default_targets(root)

    print(f'{"结果":6s} {"skill":24s} 说明')
    print('-' * 80)
    n_fail = 0
    for t in targets:
        label = t.name if t.resolve() != root.resolve() else root.name + '(根)'
        problems, notes = check_skill(t)
        tag = 'PASS' if not problems else 'FAIL'
        if problems:
            n_fail += 1
        print(f'{tag:6s} {label:24s} {"; ".join(notes)}')
        for pb in problems:
            print(f'{"":6s} {"":24s} x {pb}')
    print('-' * 80)
    print('注：argument-hint 为宿主扩展键，三个 skill 一致，登记为已知而非违规。')
    if not targets:
        print('FAIL  没有可校验的目标')
        return 2
    print(f'{"PASS" if not n_fail else "FAIL"}  {len(targets)} 个目标，{n_fail} 个不合格')
    return 0 if not n_fail else 1


if __name__ == '__main__':
    sys.exit(main())
