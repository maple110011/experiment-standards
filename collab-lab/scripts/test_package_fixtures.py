#!/usr/bin/env python -u
# -*- coding: utf-8 -*-
r"""产出包 fixtures —— **一个包必须只有一个入口，且入口把其余文件都点名**。

治的是用户最初那句话里最直白的一条："**五分钟内知道发生了什么、下一步做什么**"。

第 35 轮实测（同一个任务的两臂）：

| 臂 | 文件数 | 入口 | 结果 |
|---|---|---|---|
| 无 skill | 2 | **没有**入口 | 两个文件平级摆着，人不知道该先读哪个 |
| 有 skill | 9 | 有 1 个摘要卡（自身合规） | **但入口只点名了 8 个其余文件中的 1 个** ⇒ 人读完入口仍不知道包里有什么 |

⇒ 两臂都不过，而**有 skill 那一臂的失败更值得记**：它具备"入口"的**形式**，
却没有做入口唯一该做的那件事 —— **把包收口**。
"更完整"于是直接变成"接手更慢"，而 skill 的验收标准 #1 恰恰是五分钟测试。

## 五个并排场景

| 场景 | 造的是什么 | 期望 |
|---|---|---|
| `good` | 1 个入口，点名了其余全部文件 | **PASS** |
| `no_entry` | 3 个文件平级，没有入口 | 报 `没有入口` |
| `two_entries` | 2 个 `DIGEST-*` | 报 `两个入口` |
| `unnamed` | 1 个入口，但有文件没被点名 | 报 `没有被入口点名` |
| `entry_bad` | 入口自身不合规（缺「待你回答」等） | 报摘要卡的问题 |

⚠️ `good` 是**反向**场景：它保证检查不是"一律 FAIL"（`B28` 第 ② 项）。

跑法：`python scripts/test_package_fixtures.py`（由 `--self-test` 调用）
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import subproc  # noqa: E402
CHECKER = HERE / "check_collab_artifacts.py"

# 一份**合规**的摘要卡（字段与预算都过）。照 `assets/samples/DIGEST-sample-000.md` 的结构写，
# 但内容最小化 —— 这里测的是"包"的规则，不是摘要卡的内容质量。
GOOD_DIGEST = """# DIGEST-P-TEST-001

## 结论
测试用的最小摘要卡，强度标签：薄。

## 对比
| 项 | 本块 | 基线 | 不确定度 |
|---|---|---|---|
| 主指标 | 0.71 | 0.68 | ±0.05 |

## 意外
无（覆盖 2/2 项，未检查 0 项）

## 机制
1. 实现问题：测试用。

## 堵点
1. 停在测试上（已排除：数据问题、口径问题）。

## 开放
1. 还需要什么（什么能解决它：再跑一次）。

## 决策卡
自荐：GO。理由：测试。风险：无。

## 待你回答
**要不要继续？**
- [ ] 继续
- [ ] 停止
"""

SCENARIOS = []


def _mk(base: Path, name: str, files: dict):
    d = base / name
    d.mkdir(parents=True)
    for fn, txt in files.items():
        p = d / fn
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt, encoding="utf-8")
    return d


ENTRY_NAMES_ALL = GOOD_DIGEST.replace(
    "## 待你回答",
    "## 本包其它文件\n- `CHARTER.md`：章程\n- `PROTOCOL-P-TEST-001.md`：协议块\n\n## 待你回答")


def main() -> int:
    base = HERE / "_package_fixtures_tmp"
    if base.exists():
        shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True)
    print("=" * 78)
    print("产出包 fixtures（5 个场景：入口唯一 + 入口点名其余文件）")
    print("=" * 78)

    cases = [
        ("good", {"DIGEST-P-TEST-001.md": ENTRY_NAMES_ALL,
                  "CHARTER.md": "# CHARTER", "PROTOCOL-P-TEST-001.md": "# P"}, 0,
         None),
        ("no_entry", {"CHARTER.md": "# C", "PROTOCOL-P-TEST-001.md": "# P",
                      "notes.md": "n"}, 1, "没有入口"),
        ("two_entries", {"DIGEST-A.md": GOOD_DIGEST, "DIGEST-B.md": GOOD_DIGEST,
                         "CHARTER.md": "# C"}, 1, "两个入口"),
        ("unnamed", {"DIGEST-P-TEST-001.md": GOOD_DIGEST, "CHARTER.md": "# C",
                     "PROTOCOL-P-TEST-001.md": "# P"}, 1, "没有被入口点名"),
        ("entry_bad", {"DIGEST-P-TEST-001.md": "# 空的\n\n只有一行",
                       "CHARTER.md": "# C"}, 1, "摘要卡"),
    ]
    ok = True
    try:
        for name, files, exp_code, must in cases:
            d = _mk(base, name, files)
            r = subproc.run_text([sys.executable, str(CHECKER), "--package", str(d)])
            code = r.returncode
            hit = (must is None) or any(must in ln for ln in r.stdout.splitlines())
            good = (code == exp_code) and hit
            ok &= good
            print(f"{'PASS' if good else 'FAIL'}  {name:12s} 退出码 {code}"
                  f"（期望 {exp_code}）"
                  + (f"  命中 {must!r}={hit}" if must else ""))
            if not good:
                for ln in r.stdout.splitlines():
                    if ln.strip().startswith("x "):
                        print(f"        | {ln.strip()[:100]}")

        # ---------- 同族的第二条规则：**工作区入口**（`--workspace-entry`）----------
        print("-" * 78)
        print("工作区入口（必须点名根目录每份 .md + 声明先读哪个 + ≤120 行）")
        print("-" * 78)
        WS_CASES = [
            # 名字, 根目录文档, 入口正文, 期望码, 期望字样
            ("ws_good", ["CHARTER.md", "MAP.md"],
             "先读 `CHARTER.md`。\n也看 `MAP.md`。\n", 0, None),
            ("ws_unnamed", ["CHARTER.md", "MAP.md"],
             "先读 `CHARTER.md`。\n", 1, "没有被入口点名"),
            ("ws_no_first", ["CHARTER.md", "MAP.md"],
             "`CHARTER.md` 与 `MAP.md` 都在这。\n", 1, "先读哪个"),
            ("ws_too_long", ["CHARTER.md"],
             "先读 `CHARTER.md`。\n" + "填充行。\n" * 130, 1, "入口长度"),
        ]
        for name, docs, body, exp_code, must in WS_CASES:
            d = base / name
            d.mkdir(parents=True)
            for doc in docs:
                (d / doc).write_text("# x", encoding="utf-8")
            (d / "ENTRY.md").write_text(body, encoding="utf-8")
            r = subproc.run_text([sys.executable, str(CHECKER),
                                  "--workspace-entry", str(d / "ENTRY.md")])
            code = r.returncode
            hit = (must is None) or any(must in ln for ln in r.stdout.splitlines())
            good = (code == exp_code) and hit
            ok &= good
            print(f"{'PASS' if good else 'FAIL'}  {name:14s} 退出码 {code}"
                  f"（期望 {exp_code}）"
                  + (f"  命中 {must!r}={hit}" if must else ""))
            if not good:
                for ln in r.stdout.splitlines():
                    if ln.strip().startswith("x "):
                        print(f"        | {ln.strip()[:100]}")
    finally:
        shutil.rmtree(base, ignore_errors=True)
    print("-" * 78)
    print("package fixtures 结果:", "全部通过" if ok else "有 FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
