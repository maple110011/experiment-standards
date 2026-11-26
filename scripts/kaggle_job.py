#!/usr/bin/env python3
"""kaggle_job.py - DSH 侧的 Kaggle 作业协议适配器.

把 Kaggle 的 kernels push / status / logs / output 包装成和
scripts/remote_job.sh 同语义的作业接口：

  submit  提交一个 kernel（等价 remote_job.sh submit）
  status  查状态（等价 status）
  logs    看日志（等价 logs；支持 -f 跟随）
  fetch   取回产物（等价 fetch）
  list    列出本地记录的作业
  quota   查本周 GPU/TPU 额度（Kaggle 特有，用来做成本护栏）
  doctor  体检：CLI、登录、配置目录、SSH、磁盘

成功判据：平台状态为完成，且取回的 result.json 里 exit_code == 0。

为什么需要这层壳：Kaggle 没有 SSH，每次运行是「一个 kernel 版本」；
本地要记住 version 与产物目录，并把平台状态翻译成统一状态机，
才能让 DSH 用同一套命令驱动 Kaggle 和其他 SSH 平台。

用法（在仓库根目录执行）:
  python scripts/kaggle_job.py doctor
  python scripts/kaggle_job.py quota
  python scripts/kaggle_job.py submit --name smoke --file job.py
  python scripts/kaggle_job.py status --name smoke --wait
  python scripts/kaggle_job.py logs   --name smoke
  python scripts/kaggle_job.py fetch  --name smoke

环境变量:
  KAGGLE_JOB_ROOT  作业状态目录的根（默认脚本所在仓库），转发器用它把状态放回调用方项目
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
# 默认用脚本所在仓库；转发器/受限环境可用 KAGGLE_JOB_ROOT 覆盖（jobstate 放回调用方项目）。
ROOT = Path(os.environ.get("KAGGLE_JOB_ROOT") or HERE.parent).resolve()
# 可选：受限沙箱里可以把 kaggle 包装到 vendor/site；普通环境用全局安装的 CLI。
VENDOR = ROOT / "vendor" / "site"
STATE_DIR = ROOT / "jobstate"
CONFIG_DIR = ROOT / ".kaggle"
SSH_DIR = ROOT / ".ssh"
ADAPTER_VERSION = "0.1.0"

TERMINAL = {"finished", "failed", "killed"}


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def ensure_import_path() -> None:
    if VENDOR.exists() and str(VENDOR) not in sys.path:
        sys.path.insert(0, str(VENDOR))


_module_cli_ok: bool | None = None


def module_cli_works() -> bool:
    """全局安装的 kaggle 能不能直接 python -m kaggle 跑（结果缓存）。"""
    global _module_cli_ok
    if _module_cli_ok is None:
        try:
            p = subprocess.run([sys.executable, "-m", "kaggle", "--version"],
                               capture_output=True, timeout=120,
                               encoding="utf-8", errors="replace")
            _module_cli_ok = p.returncode == 0
        except Exception:
            _module_cli_ok = False
    return _module_cli_ok


def cli_prefix() -> list[str]:
    """返回调用 kaggle CLI 的命令前缀。

    优先用全局安装的 kaggle（python -m kaggle）；没有时回退到
    scripts/kaggle_cli.py + workspace 的 vendor/site。绝不经过 bash：
    Windows 的 System32\bash.exe 是 WSL 存根，从 Python 子进程调用会报
    0x80070042（DSH 自己的 shell 里 MSYS bash 是好用的，但别依赖它）。
    测试时可以用 KAGGLE_CLI_CMD 覆盖成任意命令（shlex 切分）。
    """
    override = (os.environ.get("KAGGLE_CLI_CMD") or os.environ.get("KAGGLE_CLI") or "").strip()
    if override:
        # Windows 路径里的反斜杠不能被 shlex 当转义吃掉，所以用非 POSIX 模式
        return shlex.split(override, posix=(os.name != "nt"))
    if module_cli_works():
        return [sys.executable, "-m", "kaggle"]
    bootstrap = HERE / "kaggle_cli.py"
    if bootstrap.exists():
        return [sys.executable, str(bootstrap)]
    return ["kaggle"]


def kaggle_config_dir() -> Path:
    """凭据目录：默认跟随 CLI 的 ~/.kaggle；家目录不可写时回退到 workspace。"""
    env = os.environ.get("KAGGLE_CONFIG_DIR", "").strip()
    if env:
        return Path(env)
    home_cfg = Path.home() / ".kaggle"
    parent = home_cfg.parent
    try:
        if parent.exists() and os.access(parent, os.W_OK):
            return home_cfg
    except Exception:
        pass
    return CONFIG_DIR


def cli_env() -> dict:
    env = dict(os.environ)
    env.setdefault("KAGGLE_CONFIG_DIR", str(kaggle_config_dir()))
    return env


def run_cli(args: list[str], timeout: int = 300) -> tuple[int, str]:
    cmd = cli_prefix() + args
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=timeout, env=cli_env(),
                           encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return 127, "找不到 kaggle CLI：" + " ".join(cmd)
    except subprocess.TimeoutExpired:
        return 124, "kaggle CLI 超时：" + " ".join(cmd)
    out = (p.stdout or "") + (p.stderr or "")
    return p.returncode, out.strip()


def load_state(name: str) -> dict:
    f = STATE_DIR / name / "state.json"
    if not f.exists():
        die("没有名为 %s 的本地作业记录（%s）" % (name, f))
    return json.loads(f.read_text(encoding="utf-8"))


def save_state(name: str, state: dict) -> None:
    d = STATE_DIR / name
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "state.json.tmp"
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, d / "state.json")   # 原子替换：读不到写了一半的状态


def die(msg: str, code: int = 1) -> None:
    print("[FAIL] " + msg, file=sys.stderr)
    raise SystemExit(code)


def slugify(s: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s or "job"


def detect_owner() -> str | None:
    env_owner = os.environ.get("KAGGLE_USERNAME", "").strip()
    if env_owner:
        return env_owner
    rc, out = run_cli(["config", "view"], timeout=60)
    m = re.search(r"(?im)^\s*-?\s*username\s*:\s*(\S+)", out)
    if m:
        return m.group(1).strip().strip('"').strip("'")
    m = re.search(r"(?i)user(name)?\s*[:=]\s*([A-Za-z0-9_.-]+)", out)
    return m.group(2) if m else None


def extract_json(text: str):
    """从 CLI 输出里抠出第一段 JSON（CLI 会把登录提示混进 stdout/stderr）。

    kaggle quota 返回的是数组，其他命令返回对象，所以两种起始符都要认。
    """
    i = -1
    for ch in "[{":
        j = text.find(ch)
        if j >= 0 and (i < 0 or j < i):
            i = j
    if i < 0:
        return None
    close = "]" if text[i] == "[" else "}"
    j = text.rfind(close)
    if j <= i:
        return None
    try:
        return json.loads(text[i:j + 1])
    except Exception:
        return None


def is_auth_error(text: str) -> bool:
    t = text or ""
    return ("Authentication required" in t) or ("Unauthenticated" in t) or ('"code":401' in t) or ("401" in t and "auth" in t.lower())


def normalize_status(raw: str) -> str:
    """把 Kaggle 的 KernelWorkerStatus.* 翻译成统一状态。

    注意：只能拿状态词判断，不能拿整段输出做关键字匹配——kernel slug 里
    可能带 fail/error 字样（例如 failjob），否则会把 running 误判成 failed。
    """
    m = re.search(r"KernelWorkerStatus\.(\w+)", raw or "")
    if m:
        token = m.group(1).lower()
    else:
        m2 = re.search(r'(?i)status[:\s]+"?([A-Za-z_.]+)"?', raw or "")
        token = (m2.group(1) if m2 else (raw or "")).lower()
    if not token:
        return "unknown"
    if "complete" in token or "success" in token:
        return "finished"
    if "cancel" in token or "kill" in token or "abort" in token:
        return "killed"
    if "error" in token or "fail" in token:
        return "failed"
    if "running" in token or "queue" in token or "pending" in token or "submitted" in token:
        return "running"
    return "unknown"


def cmd_doctor(args) -> int:
    print("== kaggle_job doctor ==")
    print("adapter  :", ADAPTER_VERSION)
    print("python   :", sys.version.split()[0], sys.executable)
    print("repo     :", ROOT)
    print("state    :", STATE_DIR, "(exists=%s)" % STATE_DIR.exists())
    cfg = kaggle_config_dir()
    print("config   :", cfg, "(exists=%s)" % cfg.exists())
    print("vendor   :", VENDOR, "(exists=%s)" % VENDOR.exists())
    print("cli      :", " ".join(cli_prefix()))
    rc, out = run_cli(["--version"], timeout=120)
    print("cli ver  :", out.splitlines()[-1] if out else "(空)", "rc=%d" % rc)
    rc2, out2 = run_cli(["quota", "--format", "json"], timeout=120)
    quota = extract_json(out2)
    if rc2 == 0 and quota is not None:
        print("quota    :", json.dumps(quota, ensure_ascii=False)[:400])
    elif is_auth_error(out2):
        print("quota    : 未登录。先完成账号验证（kaggle auth login 或写入 .kaggle/access_token）")
    else:
        print("quota    : 不可用 ->", (out2.splitlines()[0][:200] if out2 else "(空)"))
    home_key = Path.home() / ".ssh" / "id_ed25519"
    key = home_key if home_key.exists() else SSH_DIR / "id_ed25519"
    print("ssh key  :", key, "(exists=%s)" % key.exists())
    if key.exists():
        pub = key.with_suffix(".pub")
        if not pub.exists():
            rc3, out3 = subprocess.run(["ssh-keygen", "-y", "-f", str(key)], capture_output=True, text=True).stdout, ""
            if out3:
                pub.write_text(out3, encoding="utf-8")
        if pub.exists():
            print("ssh pub  :", pub.read_text(encoding="utf-8").strip()[:70] + "...")
    freqs = shutil.disk_usage(ROOT)
    print("disk free:", "%.1f GB" % (freqs.free / 1e9))
    ok = rc == 0 and rc2 == 0 and quota is not None
    print("verdict  :", "OK" if ok else "需要登录/安装（见 scripts/README.md 的账号准备一节）")
    return 0 if ok else 1


def cmd_quota(args) -> int:
    rc, out = run_cli(["quota", "--format", "json"], timeout=120)
    quota = extract_json(out)
    if quota is not None:
        print(json.dumps(quota, ensure_ascii=False, indent=2))
        return 0
    if is_auth_error(out):
        print("[FAIL] 还没登录 Kaggle。", file=sys.stderr)
        print("  方式 A（推荐，浏览器 OAuth）: python scripts/kaggle_cli.py auth login", file=sys.stderr)
        print("  方式 B（API token）: 把 token 写进 %s" % (kaggle_config_dir() / "access_token"), file=sys.stderr)
        return 1
    print(out if out else "(无输出)")
    return rc


def cmd_submit(args) -> int:
    src = Path(args.file).resolve()
    if not src.exists():
        die("找不到作业文件：%s" % src)
    name = args.name or slugify(src.stem)
    if not re.match(r"^[A-Za-z0-9._-]+$", name):
        die("--name 只能用字母数字 . _ -")
    owner = args.owner or detect_owner()
    if not owner:
        die("拿不到 Kaggle 用户名。请加 --owner <你的用户名>，或先 kaggle auth login。")
    slug = args.slug or slugify(name)
    ref = "%s/%s" % (owner, slug)

    job_dir = STATE_DIR / name
    kernel_dir = job_dir / "kernel"
    out_dir = job_dir / "out"
    kernel_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, kernel_dir / src.name)

    meta = {
        "id": ref,
        "title": slug,
        "code_file": src.name,
        "language": "python",
        "kernel_type": "script",
        "is_private": True,
        "enable_gpu": True,
        "enable_internet": not args.no_internet,
        "dataset_sources": list(args.dataset or []),
        "kernel_sources": [],
        "competition_sources": [],
        "model_sources": [],
    }
    (kernel_dir / "kernel-metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    push = ["kernels", "push", "-p", str(kernel_dir), "--accelerator", args.accelerator]
    if args.timeout_seconds:
        push += ["-t", str(int(args.timeout_seconds))]
    print("staging:", kernel_dir)
    print("meta   :", json.dumps(meta, ensure_ascii=False))
    print("command:", " ".join(cli_prefix() + push))
    if args.dry_run:
        print("[dry-run] 没有真正提交。")
        return 0

    rc, out = run_cli(push, timeout=600)
    print(out)
    if rc != 0:
        die("kaggle kernels push 失败（rc=%d）" % rc)

    m = re.search(r"(?i)version\s+(\d+)", out) or re.search(r"/versions/(\d+)", out)
    version = int(m.group(1)) if m else None
    state = {
        "name": name, "ref": ref, "slug": slug, "version": version,
        "source": str(src), "kernel_dir": str(kernel_dir), "out_dir": str(out_dir),
        "accelerator": args.accelerator, "timeout_seconds": args.timeout_seconds,
        "submitted_at": now(), "status": "running", "raw_status": None,
        "pushed_ok": True,
    }
    save_state(name, state)
    print("submitted: %s -> %s (version=%s)" % (name, ref, version))
    print("下一步    : python %s status --name %s --wait" % (Path(__file__).name, name))
    return 0


def cmd_status(args) -> int:
    state = load_state(args.name)
    ref = state["ref"]
    deadline = time.time() + (args.wait or 0)
    while True:
        rc, out = run_cli(["kernels", "status", ref], timeout=180)
        state["last_check"] = now()
        state["raw_status"] = out.splitlines()[0] if out else ""
        status = normalize_status(out)
        state["status"] = status
        save_state(args.name, state)
        print("[%s] %s -> %s" % (state["last_check"], ref, status))
        if out:
            print(out.strip()[:800])
        if status in TERMINAL or not (args.wait and time.time() < deadline):
            if status == "finished":
                print("提示: 用 fetch 取回产物并校验 result.json 的 exit_code。")
            return 0 if status == "finished" else (1 if status in ("failed", "killed") else 2)
        time.sleep(args.interval)


def cmd_logs(args) -> int:
    state = load_state(args.name)
    cmd = ["kernels", "logs", state["ref"]]
    if args.follow:
        cmd.append("-f")
    rc, out = run_cli(cmd, timeout=3600 if args.follow else 300)
    print(out)
    return rc


def cmd_fetch(args) -> int:
    state = load_state(args.name)
    out_dir = Path(args.dest).resolve() if args.dest else Path(state["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    rc, out = run_cli(["kernels", "output", state["ref"], "-p", str(out_dir), "-o"], timeout=1800)
    print(out)
    if rc != 0:
        die("kaggle kernels output 失败（rc=%d）" % rc)
    state["fetched_at"] = now()
    state["out_dir"] = str(out_dir)
    result_file = out_dir / "result.json"
    exit_code = None
    if result_file.exists():
        try:
            r = json.loads(result_file.read_text(encoding="utf-8", errors="replace"))
            exit_code = r.get("exit_code")
            state["result"] = {k: r.get(k) for k in ("exit_code", "ok", "error", "metrics", "environment") if k in r}
        except Exception as e:
            state["result_error"] = "result.json 解析失败: %s" % e
    state["exit_code"] = exit_code
    save_state(args.name, state)
    print("产物目录:", out_dir)
    files = sorted(p.name for p in out_dir.iterdir() if p.is_file())
    print("文件    :", ", ".join(files[:30]) if files else "(空)")
    if exit_code is None:
        print("[WARN] 没有 result.json 或没有 exit_code，不能判定成功。")
        return 1
    ok = int(exit_code) == 0
    print("exit_code=%s -> %s" % (exit_code, "SUCCESS" if ok else "FAILED"))
    return 0 if ok else 1


def cmd_list(args) -> int:
    if not STATE_DIR.exists():
        print("(还没有作业记录：%s)" % STATE_DIR)
        return 0
    print("%-24s %-32s %-10s %-6s %s" % ("NAME", "REF", "STATUS", "VER", "UPDATED"))
    for d in sorted(STATE_DIR.iterdir()):
        f = d / "state.json"
        if not f.exists():
            continue
        s = json.loads(f.read_text(encoding="utf-8"))
        print("%-24s %-32s %-10s %-6s %s" % (
            s.get("name", d.name), s.get("ref", "-"), s.get("status", "-"),
            s.get("version", "-"), s.get("last_check") or s.get("submitted_at", "-")))
    return 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ensure_import_path()
    ap = argparse.ArgumentParser(description="Kaggle 作业协议适配器（DSH 远程作业）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("doctor"); p.set_defaults(func=cmd_doctor)
    p = sub.add_parser("quota"); p.set_defaults(func=cmd_quota)

    p = sub.add_parser("submit")
    p.add_argument("--name")
    p.add_argument("--file", required=True)
    p.add_argument("--slug")
    p.add_argument("--owner")
    p.add_argument("--accelerator", default="NvidiaTeslaT4")
    p.add_argument("--timeout-seconds", type=int, default=32400, help="默认 9 小时")
    p.add_argument("--dataset", action="append", help="挂载 Kaggle 数据集，可重复")
    p.add_argument("--no-internet", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_submit)

    p = sub.add_parser("status")
    p.add_argument("--name", required=True)
    p.add_argument("--wait", type=int, default=0, help="最多等待秒数，0 表示只查一次")
    p.add_argument("--interval", type=int, default=30)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("logs")
    p.add_argument("--name", required=True)
    p.add_argument("-f", "--follow", action="store_true")
    p.set_defaults(func=cmd_logs)

    p = sub.add_parser("fetch")
    p.add_argument("--name", required=True)
    p.add_argument("--dest")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("list"); p.set_defaults(func=cmd_list)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
