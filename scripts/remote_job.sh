#!/usr/bin/env bash
# =====================================================================
# remote_job.sh —— 用 SSH 在远端跑长作业的最小作业协议（CANNLab job 的 ssh 版）
#
# 为什么需要：本机 DSH 的 job（ops_bash run_in_background）会随会话结束被清理，
#   长时间训练必须由远端自己托管。本脚本把「提交 / 查状态 / 看日志 / 终止 / 传文件」
#   封装成一条命令；远端只需要 bash + setsid + 一个可写目录，不装任何东西。
#
# 用法:
#   bash remote_job.sh doctor --host H
#   bash remote_job.sh submit --host H --name N --file run.sh [--workdir DIR]
#   bash remote_job.sh status --host H --name N
#   bash remote_job.sh logs   --host H --name N [--tail 100] [--stream stderr]
#   bash remote_job.sh list   --host H
#   bash remote_job.sh stop   --host H --name N
#   bash remote_job.sh ship   --host H LOCAL REMOTE
#   bash remote_job.sh fetch  --host H REMOTE LOCAL
#
# 全局选项:
#   --local        在本机执行，只用于冒烟自测（配合 --base 指定临时目录）。
#                  注意 Windows/MSYS 下 pid 判活跨 shell 不可靠，alive/查重会失真；
#                  语义正确性以 Linux 远端为准。
#   --base DIR     远端作业根目录，默认 $HOME/jobs
#   --ssh-opts     额外的 ssh 参数，如 "-p 11042 -i ~/.ssh/id_ed25519"
#
# 远端作业目录（每个作业一个；状态一律 .tmp + mv 原子替换）:
#   $BASE/<name>/  cmd.sh  inner.sh  status  pid  exit_code
#                  started_at  finished_at  stdout.log  stderr.log
#
# status: running / finished / failed / killed / missing
# 成功判据: state=finished 且 exit_code=0（pid 用 kill -0 判活，不靠 alive 猜）
# =====================================================================
set -u

LOCAL=0
HOST=""
BASE='$HOME/jobs'
SSH_EXTRA=""
CMD=""
NAME=""
FILE=""
WORKDIR='$HOME'
TAILN=120
STREAM="stdout"
A=""
B=""

die() { printf '[FAIL] %s\n' "$*" >&2; exit 1; }
say() { printf '%s\n' "$*"; }
q()   { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"; }
need() { [ -n "$2" ] || die "$1 缺少参数"; }

[ $# -gt 0 ] || { sed -n '2,34p' "$0"; exit 1; }
CMD="$1"; shift
while [ $# -gt 0 ]; do
  case "$1" in
    --host)     [ $# -ge 2 ] || die "--host 需要值";   HOST="$2"; shift 2 ;;
    --base)     [ $# -ge 2 ] || die "--base 需要值";   BASE="$2"; shift 2 ;;
    --ssh-opts) [ $# -ge 2 ] || die "--ssh-opts 需要值"; SSH_EXTRA="$2"; shift 2 ;;
    --local)    LOCAL=1; shift ;;
    --name)     [ $# -ge 2 ] || die "--name 需要值";   NAME="$2"; shift 2 ;;
    --file)     [ $# -ge 2 ] || die "--file 需要值";   FILE="$2"; shift 2 ;;
    --workdir)  [ $# -ge 2 ] || die "--workdir 需要值"; WORKDIR="$2"; shift 2 ;;
    --tail)     [ $# -ge 2 ] || die "--tail 需要值";   TAILN="$2"; shift 2 ;;
    --stream)   [ $# -ge 2 ] || die "--stream 需要值"; STREAM="$2"; shift 2 ;;
    -h|--help)  sed -n '2,32p' "$0"; exit 0 ;;
    -*)         die "未知参数: $1" ;;
    *)          if [ -z "$A" ]; then A="$1"; else B="$1"; fi; shift ;;
  esac
done

if [ "$LOCAL" = "0" ]; then
  [ -n "$HOST" ] || die "缺少 --host（或加 --local 在本机自测）"
fi
case "$CMD" in
  submit|status|logs|stop)
    printf '%s' "$NAME" | grep -Eq '^[A-Za-z0-9._-]+$' || die "--name 只能用字母数字 . _ -" ;;
esac

# ----- 传输层：远端脚本 = 变量前导 + 静态正文，经 stdin 送给 bash -s，不拼引号 -----
run_remote() { # $1=前导（已转义） $2=正文
  if [ "$LOCAL" = "1" ]; then
    { printf '%s\n' "$1"; printf '%s\n' "$2"; } | bash -s
  else
    { printf '%s\n' "$1"; printf '%s\n' "$2"; } | ssh $SSH_EXTRA "$HOST" bash -s
  fi
}
put_file() { # $1=本地 $2=远端
  if [ "$LOCAL" = "1" ]; then cp -f "$1" "$2"
  else ssh $SSH_EXTRA "$HOST" "cat > $(q "$2")" < "$1"; fi
}

read -r -d '' BODY_SUBMIT <<'SH'
mkdir -p "$JDIR" || { echo "[FAIL] 建目录失败: $JDIR"; exit 91; }
if [ -f "$JDIR/status" ] && [ "$(cat "$JDIR/status" 2>/dev/null)" = "running" ]; then
  p="$(cat "$JDIR/pid" 2>/dev/null || true)"
  if [ -n "$p" ] && kill -0 "$p" 2>/dev/null; then
    echo "[FAIL] 同名作业还在跑: $NAME (pid $p)；先 stop 或换个 --name"; exit 92
  fi
fi
rm -f "$JDIR/exit_code" "$JDIR/finished_at" "$JDIR/pid"
cat > "$JDIR/inner.sh" <<'INNER'
#!/usr/bin/env bash
set -u
JDIR="$1"; WORKDIR="$2"
printf '%s' "$$" > "$JDIR/.pid.tmp" && mv "$JDIR/.pid.tmp" "$JDIR/pid"
cd "$WORKDIR" 2>/dev/null || cd "$JDIR" || exit 90
bash "$JDIR/cmd.sh" > "$JDIR/stdout.log" 2> "$JDIR/stderr.log"
rc=$?
printf '%s' "$rc" > "$JDIR/.ec.tmp" && mv "$JDIR/.ec.tmp" "$JDIR/exit_code"
date '+%Y-%m-%dT%H:%M:%S%z' > "$JDIR/.ft.tmp" && mv "$JDIR/.ft.tmp" "$JDIR/finished_at"
printf 'finished' > "$JDIR/.st.tmp" && mv "$JDIR/.st.tmp" "$JDIR/status"
INNER
chmod +x "$JDIR/inner.sh" "$JDIR/cmd.sh" 2>/dev/null || true
printf 'running' > "$JDIR/.st.tmp" && mv "$JDIR/.st.tmp" "$JDIR/status"
date '+%Y-%m-%dT%H:%M:%S%z' > "$JDIR/.sd.tmp" && mv "$JDIR/.sd.tmp" "$JDIR/started_at"
if command -v setsid >/dev/null 2>&1; then
  setsid bash "$JDIR/inner.sh" "$JDIR" "$WORKDIR" > /dev/null 2>&1 < /dev/null &
else
  nohup bash "$JDIR/inner.sh" "$JDIR" "$WORKDIR" > /dev/null 2>&1 < /dev/null &
fi
# 等 pid 落盘（最多 5 秒）：没起来就明确报错，不要留一个"running 但没进程"的假状态
i=0
while [ "$i" -lt 10 ]; do
  [ -s "$JDIR/pid" ] && break
  sleep 0.5
  i=$((i + 1))
done
if [ ! -s "$JDIR/pid" ]; then
  printf 'failed' > "$JDIR/.st.tmp" && mv "$JDIR/.st.tmp" "$JDIR/status"
  echo "[FAIL] 进程没有起来（$JDIR/pid 缺失）。多半是远端 shell 退出时把子进程带走了，"
  echo "       确认远端有 setsid 或换登录方式；现场：$JDIR"
  exit 94
fi
echo "submitted: $NAME -> $JDIR"
echo "status=$(cat "$JDIR/status" 2>/dev/null || echo missing) pid=$(cat "$JDIR/pid" 2>/dev/null || echo -)"
SH

read -r -d '' BODY_STATUS <<'SH'
if [ ! -d "$JDIR" ]; then echo "name=$NAME"; echo "state=missing"; exit 0; fi
st() { cat "$JDIR/$1" 2>/dev/null || true; }
p="$(st pid)"; ec="$(st exit_code)"; state="$(st status)"
alive=no; [ -n "$p" ] && kill -0 "$p" 2>/dev/null && alive=yes
[ -n "$state" ] || state=missing
[ -n "$p" ] || p='-'
[ -n "$ec" ] || ec='-'
echo "name=$NAME"
echo "state=$state"
echo "alive=$alive"
echo "pid=$p"
echo "exit_code=$ec"
echo "started_at=$(st started_at)"
echo "finished_at=$(st finished_at)"
if [ "$state" = "running" ] && [ "$alive" = "no" ]; then
  echo "hint=进程已不在且没有 exit_code：多半被 kill/OOM/平台回收，看 stderr.log"
fi
SH

read -r -d '' BODY_LOGS <<'SH'
f="$JDIR/$STREAM.log"
[ -f "$f" ] || { echo "[FAIL] 没有 $f（作业没提交，或 --stream 不是 stdout/stderr）"; exit 93; }
echo "== $f (tail $TAILN) =="
tail -n "$TAILN" "$f"
SH

read -r -d '' BODY_LIST <<'SH'
if [ ! -d "$BASE" ]; then echo "(空：$BASE 不存在)"; exit 0; fi
printf '%-26s %-10s %-8s %s\n' NAME STATE PID EXIT
find "$BASE" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort | while IFS= read -r d; do
  n="$(basename "$d")"
  printf '%-26s %-10s %-8s %s\n' \
    "$n" "$(cat "$d/status" 2>/dev/null || echo -)" \
    "$(cat "$d/pid" 2>/dev/null || echo -)" "$(cat "$d/exit_code" 2>/dev/null || echo -)"
done
SH

read -r -d '' BODY_STOP <<'SH'
p="$(cat "$JDIR/pid" 2>/dev/null || true)"
if [ -z "$p" ] || ! kill -0 "$p" 2>/dev/null; then
  [ -n "$p" ] || p='-'
  echo "not running（pid=$p）"
  if [ -f "$JDIR/status" ] && [ "$(cat "$JDIR/status")" = "running" ]; then
    printf 'killed' > "$JDIR/.st.tmp" && mv "$JDIR/.st.tmp" "$JDIR/status"
  fi
  exit 0
fi
kill -TERM "$p" 2>/dev/null || true
for _ in 1 2 3 4 5 6 7 8 9 10; do sleep 1; kill -0 "$p" 2>/dev/null || break; done
kill -0 "$p" 2>/dev/null && kill -KILL "$p" 2>/dev/null || true
printf 'killed' > "$JDIR/.st.tmp" && mv "$JDIR/.st.tmp" "$JDIR/status"
echo "stopped: $NAME (pid $p)"
SH

read -r -d '' BODY_DOCTOR <<'SH'
echo "== 远端体检 =="
echo "host    : $(hostname 2>/dev/null) / $(uname -srm 2>/dev/null)"
echo "user    : $(whoami 2>/dev/null)"
echo "bash    : $BASH_VERSION  setsid: $(command -v setsid || echo 无)"
echo "home    : $HOME   base: $BASE"
echo "disk    : $(df -h "$HOME" 2>/dev/null | tail -1)"
echo "python3 : $(command -v python3 || echo 无)"
for c in npu-smi nvidia-smi rocm-smi hy-smi; do
  if command -v "$c" >/dev/null 2>&1; then
    echo "card    : $c 存在 -> $("$c" -L 2>/dev/null | head -2 | tr '\n' ' ')"
  fi
done
if command -v python3 >/dev/null 2>&1; then
  python3 -c "import torch;print('torch   :',torch.__version__,'| cuda_available',torch.cuda.is_available(),'| ndev',torch.cuda.device_count())" 2>/dev/null || echo "torch   : 取不到"
fi
for u in https://www.modelscope.cn https://pypi.tuna.tsinghua.edu.cn/simple/ https://github.com; do
  c="$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "$u" 2>/dev/null)"
  [ -n "$c" ] || c=000
  echo "net     : $u -> $c"
done
SH

case "$CMD" in
  doctor)
    run_remote "BASE=$(q "$BASE")" "$BODY_DOCTOR" ;;
  submit)
    need --name "$NAME"; need --file "$FILE"
    [ -f "$FILE" ] || die "找不到 $FILE"
    run_remote "JDIR=$(q "$BASE/$NAME")" 'mkdir -p "$JDIR" || exit 91' || die "远端建目录失败"
    put_file "$FILE" "$BASE/$NAME/cmd.sh" || die "上传 cmd.sh 失败"
    run_remote "JDIR=$(q "$BASE/$NAME"); WORKDIR=$(q "$WORKDIR"); NAME=$(q "$NAME")" "$BODY_SUBMIT" ;;
  status)
    need --name "$NAME"
    run_remote "JDIR=$(q "$BASE/$NAME"); NAME=$(q "$NAME")" "$BODY_STATUS" ;;
  logs)
    need --name "$NAME"
    run_remote "JDIR=$(q "$BASE/$NAME"); TAILN=$(q "$TAILN"); STREAM=$(q "$STREAM")" "$BODY_LOGS" ;;
  list)
    run_remote "BASE=$(q "$BASE")" "$BODY_LIST" ;;
  stop)
    need --name "$NAME"
    run_remote "JDIR=$(q "$BASE/$NAME"); NAME=$(q "$NAME")" "$BODY_STOP" ;;
  ship)
    [ -n "$A" ] && [ -n "$B" ] || die "ship 需要 本地 远端 两个路径"
    if [ "$LOCAL" = "1" ]; then cp -r "$A" "$B"; else scp -q -r $SSH_EXTRA "$A" "$HOST:$B"; fi
    say "shipped: $A -> $B" ;;
  fetch)
    [ -n "$A" ] && [ -n "$B" ] || die "fetch 需要 远端 本地 两个路径"
    if [ "$LOCAL" = "1" ]; then cp -r "$A" "$B"; else scp -q -r $SSH_EXTRA "$HOST:$A" "$B"; fi
    say "fetched: $A -> $B" ;;
  *)
    die "未知子命令: $CMD" ;;
esac
