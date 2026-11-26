#!/usr/bin/env python3
r"""kaggle_setup_token.py - 把 Kaggle API token 写进 ~/.kaggle/access_token 并验证.

为什么需要：Kaggle 的 OAuth 登录（kaggle auth login）需要你在终端里粘贴浏览器
给出的验证码，DSH 的 shell 不方便做交互；而 API token 只需要把 token 存进
~/.kaggle/access_token（单行字符串）即可，CLI 会自动读取。

用法（token 已复制到剪贴板，推荐，token 不会出现在对话里）:
    python pfn-compute-research/scripts/kaggle_setup_token.py
从文件读取:
    python pfn-compute-research/scripts/kaggle_setup_token.py --from-file C:\path\token.txt
从旧的 kaggle.json 读取（username/key 格式）:
    python pfn-compute-research/scripts/kaggle_setup_token.py --from-json C:\Users\...\Downloads\kaggle.json
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

CFG = Path.home() / ".kaggle"
TOKEN_FILE = CFG / "access_token"


def read_clipboard() -> str:
    for cmd in (["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
                ["powershell", "-NoProfile", "-Command", "Get-Clipboard"]):
        try:
            p = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace", timeout=30)
            txt = (p.stdout or "").strip()
            if txt:
                return txt
        except Exception:
            continue
    return ""


def clean_token(raw: str) -> str:
    txt = (raw or "").strip().strip('"').strip("'")
    txt = txt.replace("\r", "").replace("\n", "").strip()
    return txt


def looks_like_token(t: str) -> bool:
    if not (16 <= len(t) <= 4096):
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9._~+/=-]+", t))


def verify() -> tuple[bool, str]:
    try:
        p = subprocess.run([sys.executable, "-m", "kaggle", "quota", "--format", "json"],
                           capture_output=True, encoding="utf-8", errors="replace", timeout=180)
    except Exception as e:
        return False, "调用 kaggle CLI 失败: %s" % e
    out = (p.stdout or "") + (p.stderr or "")
    m = re.search(r"\{.*\}", out, re.S)
    if p.returncode == 0 and m:
        try:
            quota = json.loads(m.group(0))
            return True, json.dumps(quota, ensure_ascii=False, indent=2)
        except Exception:
            pass
    return False, out.strip()[:1200]


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-file", help="从文本文件读取 token")
    ap.add_argument("--from-json", help="从 kaggle.json（username/key）读取")
    args = ap.parse_args()

    if args.from_json:
        data = json.loads(Path(args.from_json).read_text(encoding="utf-8-sig"))
        token = clean_token(data.get("key") or data.get("token") or "")
        print("从 kaggle.json 读取到用户名:", data.get("username"), "| key 长度:", len(token))
    elif args.from_file:
        token = clean_token(Path(args.from_file).read_text(encoding="utf-8", errors="replace"))
    else:
        token = clean_token(read_clipboard())
        print("剪贴板读取长度:", len(token))

    if not token:
        print("[FAIL] 没读到 token。请先在 https://www.kaggle.com/settings/api 生成 token 并复制到剪贴板。")
        return 2
    if not looks_like_token(token):
        print("[FAIL] 读到的内容不像 token（含空格/换行或长度不对）。长度=%d，开头=%r" % (len(token), token[:6]))
        return 2

    CFG.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(token + "\n", encoding="utf-8")
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except Exception:
        pass
    print("已写入:", TOKEN_FILE, "（%d 字符）" % len(token))

    ok, msg = verify()
    print("== 验证结果 ==")
    print(("OK: " if ok else "FAIL: ") + msg)
    if ok:
        print()
        print("下一步：")
        print("  python pfn-compute-research/scripts/kaggle_job.py doctor")
        print("  bash pfn-compute-research/scripts/stage1_kaggle.sh")
        return 0
    print()
    print("如果验证失败：")
    print("  1) 确认 token 是 https://www.kaggle.com/settings/api 里最新生成的（重新生成会作废旧 token）")
    print("  2) 如果页面下载的是 kaggle.json，用 --from-json 重新执行")
    print("  3) 如果 token 含特殊字符被截断，改存成文件再用 --from-file")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
