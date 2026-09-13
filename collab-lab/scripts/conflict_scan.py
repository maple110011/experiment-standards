#!/usr/bin/env python3
"""跨产出目录扫描：把多个 run 当成一个调查团来读，找出同一问题上的答案分歧。

用途（对应 references/experiment-map.md §2）
-------------------------------------------
生成 `QUESTION-MAP.md` / `CONTRADICTIONS.md` 的原料。**不要靠 agent 自由发挥写地图**
——那会产出又一份汇报。正确做法是先机械扫描出"同一问题上的答案变体"，
再由人/agent 对每个冲突写裁定（多数冲突不是真矛盾，而是同一个词指不同的量）。

用法
----
    # 1) 准备问题清单（JSON）：每个问题给一组"答案变体的正则"
    python scripts/conflict_scan.py --questions questions.json --runs runs/ --out scan.txt

    # 2) 没有清单时，先扫"数值型断言"的分布，人工挑出可疑问题
    python scripts/conflict_scan.py --runs runs/ --discover --out scan.txt

questions.json 格式::

    {
      "噪声下界该报多少": ["9\\\\s*分", "14\\\\s*[-~]\\\\s*20", "区间"],
      "设备可用数": ["18\\\\s*台", "20\\\\s*台"]
    }

设计要点
--------
- 只做**聚合与呈现**，不做裁定：裁定必须由人/agent 给出依据（哪个可复算）。
- 输出里每个变体都附**命中的 run**，便于回原始产出核对。
- `--discover` 会列出候选数值断言，用于发现"你没想到要问的问题"。
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from collections import defaultdict

TEXT_EXT = {'.md', '.txt', '.log', '.json', '.csv', '.py', '.ps1'}
# 候选数值断言：整数/小数（**含区间**）+ 可选单位或百分号。
# ⚠️ 第 23 轮的修正：原版只认 `\d+`，于是 `14-20 分` 被报成 `20 分`
#    —— **下界被丢掉**，而 `14-20 分` 与 `18-20 分` 会显示成同一个断言，
#    正好掩盖掉最该被发现的"口径不同"。写 fixtures 时被第 7 个场景抓到。
NUM_RE = re.compile(
    r'\b\d+(?:\.\d+)?(?:\s*[-~～]\s*\d+(?:\.\d+)?)?'
    r'\s*(?:%|分|片|台|列|行|个事件|倍|分钟|小时|天)\b')
# 量纲 = 去掉数字与连接符之后的单位部分（`14-20 分` 与 `9 分` 归到同一组）
UNIT_STRIP_RE = re.compile(r'[\d.\s\-~～]')


def iter_outputs(runs: pathlib.Path):
    """产出目录（含 outputs/ 的目录）-> 文本拼接。"""
    for d in sorted(runs.rglob('outputs')):
        if not d.is_dir():
            continue
        chunks = []
        for p in d.rglob('*'):
            if p.is_file() and p.suffix.lower() in TEXT_EXT:
                try:
                    chunks.append(p.read_text(encoding='utf-8', errors='replace'))
                except Exception:
                    pass
        if chunks:
            yield d, '\n'.join(chunks)


def label(d: pathlib.Path, runs: pathlib.Path) -> str:
    try:
        rel = d.relative_to(runs)
        return str(rel.parent) if rel.name == 'outputs' else str(rel)
    except ValueError:
        return str(d)


def scan_questions(runs: pathlib.Path, questions: dict) -> str:
    per_q = defaultdict(dict)
    arms = []
    for d, blob in iter_outputs(runs):
        name = label(d, runs)
        arms.append(name)
        for q, pats in questions.items():
            hit = [p for p in pats if re.search(p, blob)]
            if hit:
                per_q[q][name] = hit

    out = ['=' * 96,
           '跨方向答案变体扫描（原料，非裁定）',
           '=' * 96,
           f'扫描到的产出目录: {len(arms)}']
    for a in arms:
        out.append(f'    {a}')

    conflicting = 0
    for q in questions:
        arm_hits = per_q.get(q, {})
        variants = {tuple(sorted(v)) for v in arm_hits.values()}
        flag = '  <== 出现分歧' if len(variants) > 1 else ''
        if len(variants) > 1:
            conflicting += 1
        out.append('')
        out.append(f'### {q}{flag}')
        if not arm_hits:
            out.append('    （无命中：可能没人问过这个问题，或提问措辞不同）')
            continue
        allv = sorted({p for v in arm_hits.values() for p in v})
        out.append(f'    出现过的答案变体（{len(allv)} 种）: {allv}')
        for arm, v in sorted(arm_hits.items()):
            out.append(f'      {arm:44s} -> {v}')

    out += ['', '-' * 96,
            f'{len(questions)} 个问题中，{conflicting} 个出现「不同方向给出不同答案」。',
            '',
            '下一步（必须人工/agent 完成，脚本不能做）:',
            '  1. 对每个分歧写「分歧类型」: 真矛盾 | 同一个词指不同的量 | 口径不同 | 一方算错',
            '  2. 写「裁定」与「裁定依据（哪个可复算）」',
            '  3. 写「该冲突暴露了什么流程缺陷」—— 这一栏才是台账的价值所在',
            '']
    return '\n'.join(out)


def discover(runs: pathlib.Path, top: int) -> str:
    """发现候选问题：把数值断言按"出现它的方向集合"聚类。"""
    by_assert = defaultdict(set)
    for d, blob in iter_outputs(runs):
        name = label(d, runs)
        for m in NUM_RE.finditer(blob):
            by_assert[m.group(0).strip()].add(name)

    out = ['=' * 96,
           '候选数值断言（用于发现你没想到要问的问题）',
           '=' * 96,
           '读法：同一量纲下出现多个不同数值 => 可能有分歧或口径不同。',
           '']
    # 按单位分组
    grouped = defaultdict(list)
    for a, dirs in by_assert.items():
        unit = UNIT_STRIP_RE.sub('', a)
        grouped[unit].append((a, len(dirs)))

    for unit, items in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
        if len(items) < 2:
            continue
        items.sort(key=lambda kv: -kv[1])
        shown = items[:top]
        out.append(f'[{unit or "无单位"}] {len(items)} 个不同取值')
        for a, n in shown:
            out.append(f'    {a:>16s}  出现在 {n} 个方向')
        if len(items) > top:
            out.append(f'    … 另有 {len(items) - top} 个')
        out.append('')
    return '\n'.join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description='跨方向答案变体扫描')
    ap.add_argument('--runs', required=True, help='包含多个 run 的根目录（会递归找 outputs/）')
    ap.add_argument('--questions', help='问题清单 JSON（问题名 -> 答案正则数组）')
    ap.add_argument('--discover', action='store_true', help='改为列出候选数值断言')
    ap.add_argument('--top', type=int, default=12, help='--discover 时每个量纲显示几个')
    ap.add_argument('--out', help='输出文件；不给则打印到 stdout')
    args = ap.parse_args()

    runs = pathlib.Path(args.runs)
    if not runs.exists():
        print(f'找不到目录: {runs}', file=sys.stderr)
        return 2

    if args.discover:
        text = discover(runs, args.top)
    else:
        if not args.questions:
            print('需要 --questions 或 --discover', file=sys.stderr)
            return 2
        qp = pathlib.Path(args.questions)
        if not qp.exists():
            print(f'找不到问题清单: {qp}', file=sys.stderr)
            return 2
        # 用 utf-8-sig：Windows 上 PowerShell 的 Set-Content -Encoding UTF8 会写 BOM，
        # 而 json.loads 不接受 BOM。这不是使用者的错，脚本该自己处理。
        try:
            questions = json.loads(qp.read_text(encoding='utf-8-sig'))
        except json.JSONDecodeError as e:
            print(f'问题清单不是合法 JSON: {e}', file=sys.stderr)
            print('提示：值必须是"正则数组"，反斜杠要写两次（如 "9\\\\s*分"）', file=sys.stderr)
            return 2
        text = scan_questions(runs, questions)

    if args.out:
        pathlib.Path(args.out).write_text(text, encoding='utf-8')
        print(f'已写 {args.out}（{len(text):,} 字符）')
    else:
        print(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
