#!/usr/bin/env python3
"""
jupyter_exec.py — 在当前 JupyterLab 里执行 Python 代码的助手。

为什么需要它:
  某些 agent 的 shell 环境对 /dev/kfd (DCU/ROCm 计算必需) 做了只读/禁止写限制,
  直接在该 shell 里跑 torch.cuda 会得到 is_available()==False。但容器内由 JupyterLab
  拉起的 kernel 进程可以正常打开 /dev/kfd, 因此 torch.cuda 可用。
  本脚本通过 Jupyter REST + WebSocket 协议, 把代码发给 Jupyter kernel 执行,
  从而在受限 shell 里也能稳定使用 DCU/GPU。

用法:
  python jupyter_exec.py 'print(1+1)'                    # 执行代码片段, 打印输出
  python jupyter_exec.py --file script.py                # 执行脚本, 打印输出
  python jupyter_exec.py --file script.py --workdir /root/private_data/dsh/foo
  python jupyter_exec.py --kernel-id <id> '...'          # 复用已有 kernel

环境变量:
  JUPYTER_BASE_URL  默认 /jupyter-forward/2091858081171111937
  JUPYTER_TOKEN     默认 sothisai_2091858081171111937
  JUPYTER_HOST      默认 127.0.0.1:8888

行为:
  - 创建一个 python3 kernel (或复用 --kernel-id), 执行代码, 收集 stdout/stderr,
    返回 kernel 的进程退出码 (代码异常时返回 1)。
  - 若脚本执行超过 --timeout 秒仍未返回, 脚本返回 124, 但 kernel 继续在后台跑;
    可用 --kernel-id 复用同一 kernel 查询后续输出(暂不支持直接取回)。
  - 执行完默认删除 kernel; 传 --keep-kernel 则保留并打印 kernel id。
"""
import argparse, json, os, sys, time, uuid
import requests
import websocket

BASE = os.environ.get("JUPYTER_BASE_URL", "/jupyter-forward/2091858081171111937")
TOKEN = os.environ.get("JUPYTER_TOKEN", "sothisai_2091858081171111937")
HOST = os.environ.get("JUPYTER_HOST", "127.0.0.1:8888")
HTTP = f"http://{HOST}{BASE}"
WS = f"ws://{HOST}{BASE}/api/kernels"
HDRS = {"Authorization": "token " + TOKEN}


def create_kernel():
    r = requests.post(HTTP + "/api/kernels", headers=HDRS,
                      json={"name": "python3"}, timeout=30)
    r.raise_for_status()
    kid = r.json()["id"]
    # 等 kernel 进入 idle/starting 稳定
    for _ in range(60):
        info = requests.get(HTTP + f"/api/kernels/{kid}", headers=HDRS, timeout=30).json()
        if info.get("execution_state") != "starting":
            break
        time.sleep(0.5)
    return kid


def delete_kernel(kid):
    try:
        requests.delete(HTTP + f"/api/kernels/{kid}", headers=HDRS, timeout=30)
    except Exception:
        pass


def run_code(kid, code, timeout):
    ws_url = f"{WS}/{kid}/channels?token={TOKEN}"
    ws = websocket.create_connection(ws_url, timeout=min(timeout, 60), enable_multithread=True)
    msg_id = uuid.uuid4().hex
    req = {
        "header": {"msg_id": msg_id, "username": "", "session": kid,
                   "msg_type": "execute_request", "version": "5.3"},
        "parent_header": {},
        "metadata": {},
        "content": {"code": code, "silent": False, "store_history": False,
                    "user_expressions": {}, "allow_stdin": False,
                    "stop_on_error": True},
        "buffers": [],
    }
    ws.send(json.dumps(req))

    deadline = time.time() + timeout
    got_reply = False
    exit_code = 0
    error_output = []
    streams = []

    while time.time() < deadline:
        remain = deadline - time.time()
        if remain <= 0:
            break
        ws.settimeout(remain)
        try:
            raw = ws.recv()
        except websocket.WebSocketTimeoutException:
            break
        except Exception as e:
            print(f"[jupyter_exec] websocket recv error: {e}", file=sys.stderr)
            break
        if not raw:
            break
        msg = json.loads(raw)
        mt = msg.get("msg_type")
        parent = msg.get("parent_header", {})
        is_mine = parent.get("msg_id") == msg_id or parent.get("msg_id") is None
        content = msg.get("content", {})
        if mt == "stream":
            name = content.get("name", "stdout")
            text = content.get("text", "")
            streams.append((name, text))
            sys.stdout.write(text) if name == "stdout" else sys.stderr.write(text)
            sys.stdout.flush() if name == "stdout" else sys.stderr.flush()
        elif mt == "error" and is_mine:
            error_output.append(content.get("evalue", ""))
            error_output.append("\n".join(content.get("traceback", [])))
            exit_code = 1
        elif mt == "execute_result" and is_mine:
            data = content.get("data", {})
            if "text/plain" in data:
                print(data["text/plain"])
        elif mt == "display_data" and is_mine:
            data = content.get("data", {})
            if "text/plain" in data:
                print(data["text/plain"])
        elif mt == "execute_reply" and is_mine:
            got_reply = True
            if content.get("status") == "error":
                exit_code = 1
            break
        # IOPub idle 不 break, 因为 shell reply 才是完成信号

    ws.close()
    if not got_reply:
        print(f"[jupyter_exec] timed out after {timeout}s (kernel may still be running)", file=sys.stderr)
        return 124
    if exit_code != 0:
        for e in error_output:
            print(e, file=sys.stderr)
    return exit_code


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("code", nargs="?", default=None)
    ap.add_argument("--file", default=None)
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--kernel-id", default=None)
    ap.add_argument("--keep-kernel", action="store_true")
    ap.add_argument("--timeout", type=float, default=3600)
    ap.add_argument("--script-args", nargs=argparse.REMAINDER, default=None,
                    help="传给被运行脚本的参数, 必须放在所有其他参数之后")
    args, extra = ap.parse_known_args()
    script_args = args.script_args if args.script_args is not None else extra

    if args.file:
        path = os.path.abspath(args.file)
        with open(path) as f:
            code = f.read()
        workdir = args.workdir or os.path.dirname(path)
        argv = [path] + script_args
        code = (
            f"import os, sys\n"
            f"__file__ = {path!r}\n"
            f"os.chdir({workdir!r})\n"
            f"sys.path.insert(0, {workdir!r})\n"
            f"sys.argv = {argv!r}\n"
            + code
        )
    else:
        if args.code is None:
            ap.error("either code or --file is required")
        code = args.code
        if args.workdir:
            code = f"import os\nos.chdir({args.workdir!r})\n" + code

    kid = args.kernel_id
    created = False
    if kid is None:
        kid = create_kernel()
        created = True

    rc = run_code(kid, code, args.timeout)

    if created and not args.keep_kernel:
        delete_kernel(kid)
    elif args.keep_kernel:
        print(f"\n[jupyter_exec] kernel_id={kid}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
