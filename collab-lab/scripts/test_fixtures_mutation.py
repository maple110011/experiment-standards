#!/usr/bin/env python -u
# -*- coding: utf-8 -*-
"""变异测试：确认 fixtures 真能拦住回归（不是"只会说 OK"）。

## 为什么需要它

`test_guard_fixtures.py` 与 `test_status_fixtures.py` 会在行为改变时报 FAIL。
但**它们自己**也可能是摆设 —— 比如断言写得太松、或场景根本没覆盖到那条路径
（本轮实测就发生过两次：`PROTOCOL-P-1.md` 因块号不足两位而一个块都没被识别；
`early` 场景因为补了 Q/T 台账而**没测到"零入账"这条路径**）。

所以对 fixtures 本身做**变异测试**：故意改坏被测对象，要求 fixtures 报 FAIL。

**15 个变异，每个对应一次真实发生过的失效**（分四类）：

| 类 | 变异 | 它拦的错 |
|---|---|---|
| 假警报 | M1 去掉"未开工"检测、M2 早期阈值改 0 | 新课题/早期被误诊为偏离 |
| 解析器分裂 | M3 `BLOCK_GOAL_RE` 永不匹配、M4 `BLOCK_THEORY_RE` 永不匹配 | 脚本照样跑、只是某栏**悄悄变空** |
| 比较写反 | M5 证伪核对、M10 挂起逾期 | 两个并排场景各挂一个，单场景抓不到 |
| 检查失效 | M6–M8 第 3 档分流三条路径、M11 挂起缺到期日、M12 挂起检查整体移除、M13 可用性字段语法、M15 一屏的挂起标记 | 漏报（"检查写坏"与"检查被删"是两回事） |
| **报告通道** | **M9 子进程编码注入、M14 自身输出兜底** | **检查自己崩掉** ⇒ 看起来像环境问题，于是被绕过 |

⚠️ **变异测试自己也会静默失效**（本轮实测两次，都记在对应变异的注释里）：
- M9 第一版只是"不再设置变量"，而变异测试自己的环境里**已经有**那两个变量
  ⇒ 语义没变，却报"变异后退出码 0"，看起来像"fixtures 没拦住"；
- `--self-test` 的负样例断言第一版用宽松匹配（`"挂起" and "到期"`），
  而"缺字段"的提示里同时在**示范怎么写** ⇒ 断言恒真 ⇒ M13 抓不到。
  **修法**：断言要匹配规则独有的措辞，并且要能通过"把规则删掉后断言变假"这一关。

由 `check_collab_artifacts.py --mutation-test` 调用；改动任一脚本后应重跑。
"""
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import subproc  # noqa: E402  （子进程编码只有这一处定义，见 subproc.py）
GUARD = HERE / "goal_guard.py"
CHECKER = HERE / "check_collab_artifacts.py"
FIX_GUARD = HERE / "test_guard_fixtures.py"
FIX_STATUS = HERE / "test_status_fixtures.py"
FIX_STALE = HERE / "test_theory_staleness_fixtures.py"
FIX_TRIAGE = HERE / "test_triage_fixtures.py"
FIX_SUSP = HERE / "test_suspension_fixtures.py"
FIX_NF = HERE / "test_noise_floor_fixtures.py"
FIX_CS = HERE / "test_conflict_scan_fixtures.py"
FIX_FM = HERE / "test_frontmatter_fixtures.py"
FIX_DEC = HERE / "test_decisions_fixtures.py"
FIX_PKG = HERE / "test_package_fixtures.py"
# 第五个自证型目标：`check_run_integrity.py --self-test`（五个并排场景）
RUNINT_SELFTEST = "RUNINT_SELFTEST"
# 第六个自证型目标：`eval_structural_assertions.py --self-test`（五个并排场景）
EVALASSERT_SELFTEST = "EVALASSERT_SELFTEST"
# 第七个自证型目标：`make_blind_pair.py --self-test`（六个并排场景）
BLIND_SELFTEST = "BLIND_SELFTEST"
# 第八个自证型目标：`check_doc_structure.py --self-test`（三个并排场景）
DOC_SELFTEST = "DOC_SELFTEST"
# 第九个自证型目标：`check_submission.py --self-test`（六个并排场景 + 六个代码包场景）
SUB_SELFTEST = "SUB_SELFTEST"
# 第十个自证型目标：`check_package_repro.py --self-test`（四个并排场景 + 数据不被删）
PKGREPRO_SELFTEST = "PKGREPRO_SELFTEST"
# 第十一个自证型目标：`check_genericity.py --self-test`（六个并排场景）
GENERICITY_SELFTEST = "GENERICITY_SELFTEST"

# 特殊目标：不是 fixture 脚本，而是产物校验器自己的 `--self-test`。
# 立这个标记的原因：`--self-test` 里对**负样例**的断言（"故意违规必须被拒收"）
# 此前没有任何变异测试覆盖 —— 把某条规则删掉，负样例少报一条，
# 而那一条恰恰是靠 `must_catch` 才看得见。故让它也能被变异。
SELFTEST = "SELFTEST"
# 第二个自证型目标：`check_console_safe.py --self-test`（四个并排用例）
CONSOLE_SELFTEST = "CONSOLE_SELFTEST"
# 第三个自证型目标：`artifact_index.py --self-test`（四个并排场景）
ARTIFACT_SELFTEST = "ARTIFACT_SELFTEST"
# 第四个自证型目标：`claim_repro.py --self-test`（三场景）
CLAIM_SELFTEST = "CLAIM_SELFTEST"

# (名称, 目标文件, 旧的片段(正则), 新的片段, 该跑哪个 fixtures)
MUTATIONS = [
    ("M1 去掉守卫的未开工检测（新课题会收到假警报）",
     GUARD, r"def detect_fresh_start\(", "def _disabled_detect_fresh_start(", FIX_GUARD),
    ("M2 守卫早期阈值改 0（早期被当成偏离）",
     GUARD, r"EARLY_BLOCKS = 3", "EARLY_BLOCKS = 0", FIX_GUARD),
    ("M3 BLOCK_GOAL_RE 永不匹配（解析器分裂：协议块栏悄悄变空）",
     GUARD, r'BLOCK_GOAL_RE = re\.compile\(r"[^"]*"\)',
     'BLOCK_GOAL_RE = re.compile(r"(?!)")', FIX_STATUS),
    ("M4 BLOCK_THEORY_RE 永不匹配（解析器分裂：理论出口栏悄悄变空）",
     GUARD, r'BLOCK_THEORY_RE = re\.compile\(r"[^"]*"\)',
     'BLOCK_THEORY_RE = re.compile(r"(?!)")', FIX_STATUS),
    # M5 把"台账比出口旧才报"写反 ⇒ young 场景会误报、stale 场景不报。
    # 并排两场景能抓住它；单场景抓不住（若只有一个场景，把比较恒真或恒假都能"通过"）。
    ("M5 证伪核对比较写反（young 误报 / stale 漏报）",
     GUARD, r"if ledger_mt < max\(ex_mtimes\):",
     "if ledger_mt > max(ex_mtimes):", FIX_STALE),
    # M6 让"第 3 档"的识别永不匹配 ⇒ control_ok 仍通过（它本来就合法），
    # 但 missing_triage 会**漏报** ⇒ fixtures 失败。这正是"漏报"类回归。
    ("M6 第3档识别失效（缺分流节会被漏报）",
     CHECKER, r'if len\(cells\) >= 3 and re\.fullmatch\(r"\\\*\{0,2\}3\\\*\{0,2\}", cells\[2\]\):',
     'if False:', FIX_TRIAGE),
    # M7 让"可扫必须有扫描范围"这条永不触发 ⇒ no_range 漏报。
    ("M7 可扫的扫描范围检查失效（no_range 漏报）",
     CHECKER, r'if len\(cells\) >= 3 and cells\[1\]\.strip\(\) == "可扫":',
     'if False:', FIX_TRIAGE),
    # M8 让"分流表必须标出小类"永不触发 ⇒ no_kind 漏报。
    ("M8 分流小类检查失效（no_kind 漏报）",
     CHECKER, r'if triage_ok == 0:', 'if False:', FIX_TRIAGE),
    # M9 去掉子进程的 UTF-8 环境注入 ⇒ 子进程按 cp936 写中文，父进程按 utf-8 读，
    # 断言里的中文字串**全部读不到**。这正是本仓库 `--self-test` 带 traceback 死掉
    # 的那个失效；只不过现在有 errors="replace" 兜底，形态从"崩溃"降级成"报 FAIL"。
    #
    # ⚠️ 变异必须**同时摘掉环境里的这两个变量**，不能只是"不设置"：
    #    变异测试自己是被 `subproc.run_inherit` 启起来的，它的 `os.environ` 里
    #    已经带着 `PYTHONIOENCODING=utf-8` —— 只改"不设置"等于什么都没改。
    #    （第一版就是这么写的：M9 静默变成无效变异，而且当时还看不出来，
    #      本行注释即那次记录 —— 这是"变异测试自己也需要被验证"的又一个实例。）
    ("M9 子进程编码注入失效（读不到子进程的中文输出）",
     HERE / "subproc.py",
     r'    env = dict\(os\.environ\)\n'
     r'    env\["PYTHONIOENCODING"\] = "utf-8"\n'
     r'    env\["PYTHONUTF8"\] = "1"\n',
     '    env = {k: v for k, v in os.environ.items()\n'
     '           if k not in ("PYTHONIOENCODING", "PYTHONUTF8")}\n',
     FIX_SUSP),
    # M10 把"块号 ≥ 到期号才算逾期"写反 ⇒ in-time 误报、expired-at-due 漏报。
    # 并排场景（块完全相同、只差到期号）能抓住它；单场景抓不住。
    ("M10 挂起逾期比较写反（in-time 误报 / expired 漏报）",
     GUARD, r"if n >= due_num", "if n < due_num", FIX_SUSP),
    # M11 让"挂起必须写到期日"这条永不触发 ⇒ no-deadline 漏报。
    ("M11 挂起缺到期日的检查失效（no-deadline 漏报）",
     GUARD, r"if due is None:", "if False:", FIX_SUSP),
    # M12 把整条判据 5 摘掉 ⇒ 三条挂起路径全部漏报。
    # 单独为它设一条变异，是因为"整段检查被删掉"与"其中一条分支坏掉"是两回事：
    # 前者连字段缺失的 WARN 都会变成主输出，后者只是静默漏一条。
    ("M12 挂起检查整体移除（三条路径全漏）",
     GUARD, r"a = AVAILABILITY_RE\.search\(blob\)",
     'a = None  # 判据 5 已移除', FIX_SUSP),
    # M13 让"挂起必须带到期块"的**字段语法**检查失效 ⇒ 负样例少报一条，
    # 而 `--self-test` 的 must_catch 断言就是为它写的 ⇒ 自检必须失败。
    ("M13 可用性字段语法检查失效（负样例少报一条）",
     CHECKER, r"elif a\.group\(1\) == \"挂起\" and DUE_BLOCK_RE\.search\(a\.group\(2\)\) is None:",
     "elif False:", SELFTEST),
    # M14 去掉"自身输出兜底" ⇒ 守卫的 FAIL 提示里那个 `⇒` 在 cp936 控制台上
    # **印不出来**，于是它在"报告失败"的那一行抛 UnicodeEncodeError 崩掉
    # （exit 1 + traceback，而不是 exit 2 + FAIL）。
    # 与 M9 是同一个病的两半：M9 是"读不到子进程的话"，M14 是"说不出自己的话"。
    ("M14 自身输出兜底失效（守卫在报告失败时崩掉）",
     HERE / "subproc.py", r"for s in \(sys\.stdout, sys\.stderr\):", "for s in ():",
     FIX_SUSP),
    # M15 让 status 侧的"挂起"解析失效 ⇒ 那一屏**照样跑、照样输出**，
    # 只是 `[挂起→P-nn]` 标记悄悄消失（与 M3/M4 同一个形态）。
    ("M15 一屏的挂起标记解析失效（标记悄悄消失）",
     HERE / "status.py", r"av = AVAILABILITY_RE\.search\(blob\)", "av = None",
     FIX_STATUS),
    # M16 让"不可编码字符"的检查恒不触发 ⇒ 无兜底的坏脚本会被判 PASS，
    # 而 `--self-test` 的 `no_harden` 用例正是为它写的 ⇒ 自证必须失败。
    ("M16 控制台安全检查失效（无兜底的脚本被判 PASS）",
     HERE / "check_console_safe.py", r"    if not found:", "    if True:",
     CONSOLE_SELFTEST),
    # M17 让"降级必须有去向"这条永不触发 ⇒ demoted-no-target 漏报。
    ("M17 降级去向检查失效（demoted-no-target 漏报）",
     GUARD, r'elif a\.group\(1\) == "已降级":', "elif False:", FIX_SUSP),
    # M18 让"块→T 悬空引用"这条永不触发 ⇒ dangling-ref 漏报。
    # 这一条管的是**反方向**的引用：判据 3 只看 T→块。
    ("M18 悬空理论引用检查失效（dangling-ref 漏报）",
     GUARD, r"            if t not in entries:", "            if False:", FIX_SUSP),
    # M19 让校验器侧的"降级必须有去向"永不触发 ⇒ 负样例 T-4 少报一条 ⇒ 自检失败。
    ("M19 校验器侧的降级去向检查失效（负样例少报一条）",
     CHECKER,
     r'elif a\.group\(1\) == "已降级" and DEMOTED_TO_RE\.search\(a\.group\(2\)\) is None:',
     "elif False:", SELFTEST),
    # M20 让一屏的"已降级"标记失效 ⇒ demoted 场景漏报。
    # 与 M15（挂起标记）成对：**两种"不能用"的状态各有一条**，
    # 否则"这一屏还看得出一条条目已经死了吗"就没人守。
    ("M20 一屏的降级标记失效（已降级条目看着像活的）",
     HERE / "status.py", r'elif av and av\.group\(1\) == "已降级":', "elif False:",
     FIX_STATUS),
    # M21 让"未解析引用"的收集恒为空 ⇒ 脚本照样跑、照样生成 INDEX，
    # 只是**判定永远通过** —— 这正是"一个只会说 OK 的检查器"的形态。
    ("M21 未解析引用检查失效（引用完整性永远通过）",
     HERE / "artifact_index.py",
     r"    dangling = \{n: v for n, v in refs\.items\(\)",
     "    dangling = {}  # 变异：\n    _ = {n: v for n, v in refs.items()",
     ARTIFACT_SELFTEST),
    # M22 让"≥2 档必须有判据优先级"永不触发 ⇒ multi_tier_bad 漏报。
    # 立这条的实测代价：`P-BOILER-012` 的三档判据里，O3 依赖一个**跑之前没定义**的量
    # （"口径差的区间"）⇒ 结论对，但"按判据成立"站不住。
    # M29 让「事后归因」标记**永不生效** ⇒ posthoc 场景不再印那行 INFO。
    # 立此的实测代价（第 29 轮）：`P-BOILER-018` 跑出一个反直觉读数（折间差异不是噪声、
    # 而是符号翻转），它**逼出了** `T-3`，而 T-3 写在块之后 ⇒ 块里来不及声明。
    # 机制当时只有两种结局：FAIL（把链接删掉，隐藏一条真实的证据依赖）或静默通过。
    # 现在是第三种：**声明 + 标明事后**，并印进输出。若这行 INFO 会消失，第三种就退化回第二种。
    ("M29 「事后归因」标记永不生效（事后链接不再被印出）",
     HERE / "goal_guard.py", r'        if ph:', '        if False:', FIX_GUARD),
    # M30 把"只有声明 T- 的那一行带标记才算"放宽成"整块文本里出现即豁免" ⇒
    # escape 场景（正常声明 T-1、正文提了一句事后归因）会**多出**那行 INFO。
    # 这一条是 M29 的反向安全带：放宽与"全部放行"必须能被区分开。
    ("M30 事后归因标记放宽到整块（正常链接被误标为事后）",
     HERE / "goal_guard.py", r'        for line in THEORY_LINE_RE\.findall\(t\):',
     "        for line in ([t] if POSTHOC_MARK in t else []):", FIX_GUARD),
    # M33 到期块正则退回"只认短名"（`P-?\d+`）⇒ 长块名 `P-PROBE-003` 被判成"没写到期日"。
    # 立此的实测代价（第 30 轮）：真实工作区的块名是 `P-BOILER-021`，而正则写成短名形式时，
    # `挂起（到期 P-BOILER-021）` 会被报成"没有到期日的挂起 = 永久免于证伪" ——
    # 而那条挂起写得完全正确。**误报最坏的地方是逼人把合规的写法改坏。**
    ("M33 到期块正则只认短名（长块名被判成无到期日）",
     HERE / "goal_guard.py", r'\(\?:P-\[A-Za-z0-9_\\-\]\*\?\)\?', '', FIX_SUSP),
    # M34 决策卡的"拿到的必须可核对"恒真 ⇒ vague 场景漏报（"可能有用 / 一些额度"也能过）。
    # 立此的实测代价（第 31 轮）：那条唯一的待决定原本只写"信息量大" ——
    # 那是 agent 的判断，不是给人算账的信息；人据此无法决定值不值得花。
    ("M34 「拿到什么必须可核对」恒真（vague 漏报）",
     CHECKER, r'        if what and what not in \("—", "-"\) and not re\.search',
     '        if False and not re.search', FIX_DEC),
    # M35 "等你"的判定退回"只要状态里有「待」就算" ⇒ 已生效的行也被逼着补三件套。
    # 这一条是 M34 的反向安全带：约束**扩散到不需要它的行**同样是失效。
    ("M35 「等你」判定放宽成「含待就算」（settled 被误报）",
     CHECKER, r'        if "等你" not in status:', '        if "待" not in status:',
     FIX_DEC),
    # M36 决策表不设边界（`|` 行一直吃到底）⇒ 出厂模板里另两张表被当成决策行。
    # 立此的实测代价（第 31 轮）：这个形态是我**真写过**的一版（"文件里所有 `|` 行都算"），
    # 而抓到它的正是"把出厂模板当输入"那条 fixture —— 在此之前没人喂过模板。
    ("M36 决策表不设边界（模板里另两张表被当成决策行）",
     CHECKER, r'        if not ln\.startswith\("\|"\):', "        if False:", FIX_DEC),
    # M37 空产出的检查永不触发 ⇒ "这次测量没发生"被当成可打分。
    # 立此的实测代价（第 32 轮）：`iteration-2/eval-1/with_skill` 就是空的，
    # 而成绩单把它记成"无产出"而不是"重跑"。
    # ⚠️ 这里**不能**用 `^` 锚定行首：变异用的是 `re.sub(pat, ...)`，没开 MULTILINE，
    # `^` 只匹配整段字符串的开头 ⇒ 模式永远匹配不到，变异静默失效（本轮实测）。
    ("M37 空产出检查失效（空 run 被判可打分）",
     HERE / "check_run_integrity.py", r'    if not got:', "    if False:",
     RUNINT_SELFTEST),
    # M38 只比 `run-*/outputs` 之间、不看 arm 层的副本 ⇒ 第 32 轮那个真实事故漏报。
    # （这一版是我**真写过**的第一版；自证的 two_copies 场景当场抓到它。）
    ("M38 副本比对漏掉 arm 层（真实事故形态漏报）",
     HERE / "check_run_integrity.py",
     r'    cds = \[arm_dir / "outputs"\] \+ sorted\(arm_dir\.glob\("run-\*/outputs"\)\)',
     "    cds = sorted(arm_dir.glob('run-*/outputs'))", RUNINT_SELFTEST),
    # M39 把"委托给 skill 自己校验器"这一步改成恒真 ⇒ 协议块是否符合规范**不再被检查**。
    # 立此的实测代价（第 33 轮）：一致性断言的全部价值就在这一步 ——
    # 它让"协议块合规"这件事**只有一处定义**；改成恒真之后，
    # 一份缺「停止规则」的块也会被判"符合约定"。
    ("M39 委托校验器恒真（缺节的块被判符合约定）",
     HERE / "eval_structural_assertions.py", r'        ok2 = \(r\.returncode == 0\)',
     "        ok2 = True", EVALASSERT_SELFTEST),
    # M40 把"行为"类并进"约定"类（= 旧成绩单犯的错：一个百分数混两类）。
    # 这一条守的不是某个断言，而是**报告的形状** —— 混类会让"约定差值"看起来像"能力提升"。
    # 抓它的是自证里的一条不变量：**两类必须同时存在且都非空**（否则两臂根本没有可比维度）。
    #
    # ⚠️ 模式必须**一次跨过全部两处** `"behavior"`。第一版只替换第一处，
    #    而第 34 轮又加了 B2 这条行为断言 ⇒ 两类**没有塌缩**，形状不变量当然不响，
    #    变异就被报成"未被抓到"。⇒ **变异必须真的把目标性质破坏掉**，
    #    "打了补丁"不等于"改变了被测性质"（同 B28 ②：一个场景两条路径 = 两条都没隔离）。
    ("M40 两类度量被混成一类（约定差值冒充能力提升）",
     HERE / "eval_structural_assertions.py",
     r'"behavior"([\s\S]*?)"behavior"', '"convention"\\1"convention"',
     EVALASSERT_SELFTEST),
    # M41 去标识之后的**泄漏自检**失效 ⇒ 盲评不盲而没人知道。
    # 立此的实测代价（第 34 轮）：真实产出里就有一行 `without_skill` 路径 ——
    # 那一行会让评判者一眼认出"哪份是没有 skill 的"。抓它的是"非文本泄漏"那条场景。
    ("M41 泄漏自检失效（盲评不盲而无人知）",
     HERE / "make_blind_pair.py", r'            if tok\.encode\("utf-8"\) in raw:',
     "            if False:", BLIND_SELFTEST),
    # M42 允许把映射文件写进盲评目录（= 把答案放进卷子）。
    ("M42 映射文件可写进盲评目录（答案进卷子）",
     HERE / "make_blind_pair.py",
     r'    if mapping\.resolve\(\)\.is_relative_to\(out\.resolve\(\)\):',
     "    if False:", BLIND_SELFTEST),
    # M43 去标识这一步被跳过 ⇒ 臂名原样留在文本里（泄漏自检应当报出来）。
    ("M43 去标识被跳过（臂名原样留在产出里）",
     HERE / "make_blind_pair.py", r'                        t = t\.replace\(tok, "<ARM>"\)',
     "                        pass", BLIND_SELFTEST),
    # M44 入口"点名其余文件"的检查失效 ⇒ 9 个文件平级摆着也算合规。
    # 立此的实测代价（第 35 轮）：skill 臂的摘要卡只点名了 8 个文件里的 1 个 ——
    # 人读完入口仍不知道包里有什么，而"更完整"就这样变成了"接手更慢"。
    ("M44 入口点名检查失效（文件平级摆着也算合规）",
     CHECKER, r'    unnamed = \[p for p in others if p\.name not in text',
     "    unnamed = []\n    _ = [p for p in others if p.name not in text",
     FIX_PKG),
    # M45 "两个入口等于没有入口"失效 ⇒ 两个摘要卡也放行。
    ("M45 多入口检查失效（两个入口也放行）",
     CHECKER, r'    if len\(entries\) > 1:', "    if False:", FIX_PKG),
    # M46 编号"缺号"检查失效 ⇒ 标题被吃掉也无人知（本轮我真犯过两次）。
    ("M46 编号缺号检查失效（标题被吃掉也无人知）",
     HERE / "check_doc_structure.py",
     r'        missing = \[n for n in range\(1, max\(nums\) \+ 1\) if n not in nums\]',
     "        missing = []", DOC_SELFTEST),
    # M47 工作区入口"点名每份根文档"的检查失效 ⇒ 6 份 .md 抢着当入口也算合规。
    # 立此的实测代价（第 36 轮）：这个工作区根目录真有 6 份 `.md`
    # （最长的 1482 行）而没有任何东西规定先读哪个 —— 即"丧失把握"在工作区尺度的形态。
    ("M47 工作区入口点名检查失效（多份文档抢入口也算合规）",
     CHECKER, r'    unnamed = \[p for p in others if p\.name not in text\]\n    if unnamed:\n        rep\.fail\("入口点名"',
     '    unnamed = []\n    if unnamed:\n        rep.fail("入口点名"', FIX_PKG),
    # M48 "先读哪个"的检查失效 ⇒ 有入口但没告诉人从哪开始。
    ("M48 先读声明检查失效（入口不说从哪开始）",
     CHECKER, r'    if not first:', "    if False:", FIX_PKG),
    # M49 提交包"判 1 片数 == 声明的 k"检查失效 ⇒ 策略参数写错也放行。
    # 立此的实测代价（第 37 轮）：提交是**不可逆**的，而额度是这个课题唯一的稀缺资源；
    # 此前"包对不对"只靠一次临时自查 —— 我自己顺手写的 inline 读取就因为编码取错
    # 列整体错位，报出一个**完全伪造的结论**（"判 1 的片数 0"）。
    ("M49 提交包片数检查失效（策略参数写错也放行）",
     HERE / "check_submission.py",
     r'    if expect_pos is not None and n_pos != expect_pos:', "    if False:",
     SUB_SELFTEST),
    # M50 zip 与磁盘 csv 的**逐字节一致**检查失效 ⇒ "打包后又改了 csv"这种事静默通过。
    ("M50 zip 一致性检查失效（打包后又改 csv 无人知）",
     HERE / "check_submission.py", r'                    if inner != raw:', "                    if False:",
     SUB_SELFTEST),
    # M51 SKILL.md 的**篇幅预算**失效 ⇒ 正文一路长回去而无人知。
    # 立此的实测代价（第 38 轮）：SKILL.md 长到 653 行（方法论建议 <500），
    # 而它是**每次触发都进上下文**的那一层 —— skill 自己成了它要治的那个过载源。
    ("M51 篇幅预算失效（正文一路长回去无人知）",
     HERE / "validate_frontmatter.py", r'    if n_body > 600:', "    if False:",
     FIX_FM),
    # M52 孤儿 reference 检查失效 ⇒ references/ 里出现没人会读的文件而无人知。
    ("M52 孤儿 reference 检查失效（没人引用的文件静默堆积）",
     HERE / "validate_frontmatter.py", r'        if orphans:', "        if False:",
     FIX_FM),
    # M31 人面过时检查永不触发 ⇒ stale_head 漏报。
    # 立此的实测代价（第 29 轮）：`<headline>` 停在第 27 轮，而 28/29 轮已经
    # 换掉了头号结论的支持链、还新开了一条理论条目 —— 而**没有任何东西会报**。
    # 这正是本 skill 立文的症状：人读到的"现在在哪"落后于实际进展。
    ("M31 人面过时检查失效（stale_head 漏报）",
     HERE / "goal_guard.py", r'            if hit is None:', '            if False:',
     FIX_GUARD),
    # M32 人面长度预算失效 ⇒ long_head 漏报。
    # 行数预算管不住"一整段话"（一段只算 1 行）⇒ 单段必须也有预算。
    ("M32 人面长度预算失效（long_head 漏报）",
     HERE / "goal_guard.py", r'        if len\(head\) > HEADLINE_MAX:', '        if False:',
     FIX_GUARD),
    # M27 让"期望串"的判据恒真 ⇒ 复现失败也报 PASS（一个只会说 OK 的检查器）。
    # M28 解析前悄悄把 BOM 抹掉 ⇒ 带 BOM 的脚本被判 PASS（BOM 必须判不合格）。
    # 形态选得很具体：第 28 轮我用 PowerShell 往返改横幅，**两次**都被加了 BOM，
    # 而 Python 照跑不误 ⇒ 整个仓库只有这一层静态检查会炸。
    # 若这里能被绕过，BOM 就重新变回"跑起来了，应该没事"。
    ("M28 解析前抹掉 BOM（带 BOM 的脚本被判 PASS）",
     HERE / "check_console_safe.py", r'    tree = ast\.parse\(src\)',
     "    tree = ast.parse(src.replace(chr(0xFEFF), ''))", CONSOLE_SELFTEST),
    ("M27 期望串判据恒真（复现失败也报 PASS）",
     HERE / "claim_repro.py", r'    if c\["expect"\] not in out:',
     '    if False:', CLAIM_SELFTEST),
    # M26 让"声明了稀缺资源就必须写杠杆上界"永不触发 ⇒ res_no_lever 漏报。
    # 立此的实测代价：`P-BOILER-009` 花了 3 次提交额度，事前没人算过"最多能换来什么"。
    ("M26 杠杆上界检查失效（res_no_lever 漏报）",
     CHECKER, r'        if not val\.startswith\("无"\):', "        if False:",
     FIX_TRIAGE),
    # M23 去掉 noise_floor 的常数截断（`min(1.0, ...)` = 100 分上限）
    # ⇒ exact_golden 的"首个 Δ<0 出现在 FP=23"与 cap_100 都会失败。
    ("M23 赛题公式的满分截断失效（FP=23 锚点错位）",
     HERE / "score_noise_floor.py", r"100\.0 \* min\(1\.0,", "100.0 * (",
     FIX_NF),
    # M24 让"分歧"的定义恒为单一变体 ⇒ flag 与**计数**同时失效（conflict/superset 漏报）。
    # ⚠️ 第一版打在计数器那一行上，抓不住 —— 因为 fixtures 当时只钉了 flag，
    #    而 flag 是**另一个**表达式。变异要打在"共用的那个定义"上。
    ("M24 分歧判定失效（conflict / superset 漏报）",
     HERE / "conflict_scan.py",
     r"variants = \{tuple\(sorted\(v\)\) for v in arm_hits\.values\(\)\}",
     "variants = {()}", FIX_CS),
    # M25 让 frontmatter 的尖括号检查永不触发 ⇒ angle 反例漏报。
    ("M25 description 尖括号检查失效（angle 反例漏报）",
     HERE / "validate_frontmatter.py", r"if '<' in d or '>' in d:",
     "if False:", FIX_FM),
    ("M22 多档判据优先级检查失效（multi_tier_bad 漏报）",
     CHECKER, r'    tiers = sorted\(\{int\(m\) for m in re\.findall',
     "    tiers = []  # 变异\n    _ = sorted({int(m) for m in re.findall",
     FIX_TRIAGE),
    # ---- M53–M59：第 41 轮补的"代码包那一半"（提交的代码必须复现提交的结果）----
    # 立这一组的实测代价：一次踩了三份包（两份已提交）。README 的运行命令是**从上一个包
    # 复制来的**，`predict.py` 的 `default=34` 也是复制的 —— 照 README 重现得到的是
    # 别的包的 34 个正类，而不是自己的 11 / 150。三份的 `predict.py` 静态看一条毛病都没有，
    # 所以这一组的每一条都必须由"真跑一遍"或"记录对不上"来抓，而不是由更严的静态规则来抓。
    # M53 README 命令唯一性失效 ⇒ two_cmds 漏报（复现者不知道该跑哪条）。
    ("M53 README 命令唯一性检查失效（two_cmds 漏报）",
     HERE / "check_package_repro.py", r"        if len\(cmds\) > 1:", "        if False:",
     PKGREPRO_SELFTEST),
    # M54 逐行比对恒判相同 ⇒ mismatch 漏报（**这就是 B/D 那个缺陷本身**）。
    ("M54 复现结果比对失效（复现≠提交也报 PASS）",
     HERE / "check_package_repro.py", r"    if g == w:", "    if True:",
     PKGREPRO_SELFTEST),
    # M55 依赖版本检查失效 ⇒ code_no_versions 漏报（规范要求"对应版本"）。
    ("M55 依赖版本检查失效（无版本的依赖静默通过）",
     HERE / "check_submission.py", r"            if bare:", "            if False:",
     SUB_SELFTEST),
    # M56 复现记录**过期**检查失效 ⇒ 改了 csv 忘了重跑也照样通过。
    ("M56 复现记录过期检查失效（记录对的是旧 csv 也放行）",
     HERE / "check_submission.py",
     r'                if rec\.get\("submitted_sha256"\) and rec\["submitted_sha256"\] != now:',
     "                if False:", SUB_SELFTEST),
    # M57 `required=True` 参数必须写进 README 命令 —— 这一条失效则 code_req_arg 漏报。
    ("M57 required 参数检查失效（照说明跑必然报缺参数也放行）",
     HERE / "check_submission.py", r'if v\["required"\] and k not in cmd', "if False",
     SUB_SELFTEST),
    # M58 复现记录**缺失**检查失效 ⇒ "根本没跑过"这件事重新变得可以沉默。
    ("M58 复现记录缺失检查失效（没跑过也放行）",
     HERE / "check_submission.py", r"        if not rec_path\.exists\(\):", "        if False:",
     SUB_SELFTEST),
    # M59 代码包侧的 README 命令唯一性失效（与 M53 不同文件：M53 管"跑的那一侧"，
    # M59 管"静态核的那一侧"——两侧各自都能独立失效，所以各钉一条）。
    ("M59 静态侧的 README 命令唯一性失效（code_two_cmds 漏报）",
     HERE / "check_submission.py", r"        if len\(cmds\) > 1:", "        if False:",
     SUB_SELFTEST),
    # ---- M60–M63：第 42 轮补的"机制层通用性"（skill 不许依赖具体课题）----
    # 立这一组的实测代价：用户问"skill 里是不是有竞赛特化的内容"，一扫 **49/60 个文件命中实例词**，
    # 其中真正致命的只是判据层那一小撮（代码字符串常量、模板正文）。
    # 这一组的四条**分别**钉住"判据层"与"证据层"的界线还能不能立住。
    # M60 docstring 豁免失效 ⇒ 连"注释里讲实例代价"都会被当成耦合 ⇒ doc_only 场景失败。
    # （这条最要紧：界线一旦倒向"什么都不许提"，规则就会退化成没有代价的口号。）
    ("M60 docstring/注释豁免失效（把证据也当耦合报出来）",
     HERE / "check_genericity.py", r"    skip = docstring_nodes\(tree\)", "    skip = set()",
     GENERICITY_SELFTEST),
    # M61 代码字符串常量的扫描失效 ⇒ coupled 场景（写死实例列名）漏报。
    ("M61 代码字符串扫描失效（写死实例列名漏报）",
     HERE / "check_genericity.py", r"            if tok in value:", "            if False:",
     GENERICITY_SELFTEST),
    # M62 豁免标记失效 ⇒ 有理由的例外被判成耦合 ⇒ exempt 场景失败。
    ("M62 豁免标记失效（有理由的例外被误报）",
     HERE / "check_genericity.py",
     r'OK_RE = re\.compile\(r"#\\s\*genericity-ok\\s\*:\\s\*\\S\+"\)',
     'OK_RE = re.compile(r"(?!)")', GENERICITY_SELFTEST),
    # M63 模板的占位符豁免失效 ⇒ `<例如：切片 ID>` 这种填写示例被误报 ⇒ tmpl_placeholder 失败。
    ("M63 占位符豁免失效（填写示例被误报成耦合）",
     HERE / "check_genericity.py", r"        stripped = PLACEHOLDER_RE\.sub\(\"\", ln\)",
     "        stripped = ln", GENERICITY_SELFTEST),
]


def run_fixtures(script):
    if str(script) == SELFTEST:
        r = subproc.run_text([sys.executable, str(CHECKER), "--self-test"])
    elif str(script) == CONSOLE_SELFTEST:
        r = subproc.run_text([sys.executable, str(HERE / "check_console_safe.py"),
                              "--self-test"])
    elif str(script) == ARTIFACT_SELFTEST:
        r = subproc.run_text([sys.executable, str(HERE / "artifact_index.py"),
                              "--self-test"])
    elif str(script) == CLAIM_SELFTEST:
        r = subproc.run_text([sys.executable, str(HERE / "claim_repro.py"),
                              "--self-test"])
    elif str(script) == RUNINT_SELFTEST:
        r = subproc.run_text([sys.executable, str(HERE / "check_run_integrity.py"),
                              "--self-test"])
    elif str(script) == EVALASSERT_SELFTEST:
        r = subproc.run_text([sys.executable, str(HERE / "eval_structural_assertions.py"),
                              "--self-test"])
    elif str(script) == BLIND_SELFTEST:
        r = subproc.run_text([sys.executable, str(HERE / "make_blind_pair.py"),
                              "--self-test"])
    elif str(script) == DOC_SELFTEST:
        r = subproc.run_text([sys.executable, str(HERE / "check_doc_structure.py"),
                              "--self-test"])
    elif str(script) == SUB_SELFTEST:
        r = subproc.run_text([sys.executable, str(HERE / "check_submission.py"),
                              "--self-test"])
    elif str(script) == PKGREPRO_SELFTEST:
        r = subproc.run_text([sys.executable, str(HERE / "check_package_repro.py"),
                              "--self-test"])
    elif str(script) == GENERICITY_SELFTEST:
        r = subproc.run_text([sys.executable, str(HERE / "check_genericity.py"),
                              "--self-test"])
    else:
        r = subproc.run_text([sys.executable, str(script)])
    return r.returncode, r.stdout


def main():
    print("=" * 74)
    print("变异测试：fixtures 必须能拦住这些回归")
    print("=" * 74)
    ok = True
    for script, label in ((FIX_GUARD, "守卫 fixtures"), (FIX_STATUS, "一屏 fixtures"),
                          (FIX_STALE, "证伪核对 fixtures"), (FIX_TRIAGE, "第3档分流 fixtures"),
                          (FIX_SUSP, "挂起到期 fixtures"), (SELFTEST, "产物校验器 --self-test"),
                          (CONSOLE_SELFTEST, "控制台安全 --self-test"),
                          (ARTIFACT_SELFTEST, "产物索引 --self-test"),
                          (FIX_NF, "噪声下界 fixtures"), (FIX_CS, "冲突扫描 fixtures"),
                          (FIX_FM, "frontmatter fixtures"), (FIX_DEC, "决策日志 fixtures"),
                          (FIX_PKG, "产出包 fixtures"),
                          (RUNINT_SELFTEST, "评测产出完整性 --self-test"),
                          (EVALASSERT_SELFTEST, "评测机械断言 --self-test"),
                          (BLIND_SELFTEST, "盲评对去标识 --self-test"),
                          (DOC_SELFTEST, "散文文件结构 --self-test"),
                          (SUB_SELFTEST, "提交包核对 --self-test"),
                          (PKGREPRO_SELFTEST, "代码包自复现 --self-test"),
                          (GENERICITY_SELFTEST, "机制层通用性 --self-test"),
                          (CLAIM_SELFTEST, "头条数字复现 --self-test")):
        code, _ = run_fixtures(script)
        print(f"  基线 {label}: 退出码 {code}（期望 0）")
        ok &= (code == 0)

    for name, target, pat, repl, fix in MUTATIONS:
        orig = target.read_text(encoding="utf-8")
        mutated = re.sub(pat, repl, orig, count=1)
        if mutated == orig:
            print(f"  FAIL  {name}: 变异未生效（模式没匹配到）—— 测试无效")
            ok = False
            continue
        target.write_text(mutated, encoding="utf-8")
        try:
            code, out = run_fixtures(fix)
        finally:
            target.write_text(orig, encoding="utf-8")
        caught = (code != 0)
        print(f"  {'PASS' if caught else 'FAIL'}  {name}: 变异后退出码 {code}（应 != 0）")
        if not caught:
            ok = False
            for line in out.splitlines():
                if line.startswith(("FAIL", "PASS")):
                    print(f"        | {line.strip()[:92]}")

    restored = (GUARD.read_text(encoding="utf-8").startswith("#!/usr/bin/env python"))
    codes = [run_fixtures(s)[0] for s, _ in
             ((FIX_GUARD, ""), (FIX_STATUS, ""), (FIX_STALE, ""), (FIX_TRIAGE, ""),
              (FIX_SUSP, ""), (SELFTEST, ""), (CONSOLE_SELFTEST, ""),
              (ARTIFACT_SELFTEST, ""), (FIX_NF, ""), (FIX_CS, ""), (FIX_FM, ""),
              (FIX_DEC, ""), (CLAIM_SELFTEST, ""))]
    print(f"  {'PASS' if all(c == 0 for c in codes) else 'FAIL'}  复原后十三个检查: "
          f"退出码 {codes}（期望 {[0]*13}）")
    ok &= all(c == 0 for c in codes)

    print("-" * 74)
    print("变异测试结果:", "有效（fixtures 真能拦住回归）" if ok else "无效或有问题")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
