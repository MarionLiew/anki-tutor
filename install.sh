#!/usr/bin/env bash
# AnkiTutor one-line installer.
#   bash <(curl -fsSL https://raw.githubusercontent.com/MarionLiew/anki-tutor/main/install.sh)
# Idempotent: safe to re-run. Never writes to another user's data dirs.
set -euo pipefail

REPO="https://github.com/MarionLiew/anki-tutor.git"
DEFAULT_HOME="${ANKI_TUTOR_HOME:-$HOME/.anki-tutor}"

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m   ✓ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m   ! %s\033[0m\n' "$*"; }

step "AnkiTutor 安装 (target: $DEFAULT_HOME)"
mkdir -p "$DEFAULT_HOME"

# 1. clone or pull
if [ -d "$DEFAULT_HOME/.git" ]; then
  step "更新已有仓库…"
  git -C "$DEFAULT_HOME" pull --ff-only || warn "pull 失败，沿用本地版本"
else
  step "克隆仓库…"
  git clone "$REPO" "$DEFAULT_HOME" || { echo "克隆失败: $REPO"; exit 1; }
fi

# 2. ensure runtime dirs
for d in state library/sources library/parsed library/manifests library/index; do
  mkdir -p "$DEFAULT_HOME/$d"
done

# 3. python deps
step "安装 Python 依赖…"
PY="${PYTHON:-python3}"
if command -v pip3 >/dev/null 2>&1; then
  pip3 install --quiet -r "$DEFAULT_HOME/requirements.txt" || warn "依赖安装失败，解析 PDF/DOCX 可能不可用"
else
  warn "未找到 pip3，跳过依赖安装"
fi

# 4. health check (AnkiConnect)
step "检查 AnkiConnect (localhost:8765)…"
if curl -s -m 3 -X POST http://127.0.0.1:8765 \
     -d '{"action":"version","version":6}' >/dev/null 2>&1; then
  ok "AnkiConnect 已连接"
  ok "AnkiConnect 在线 — 可执行: $PY \"$DEFAULT_HOME/src/cli.py\" ensure"
else
  warn "AnkiConnect 未连接。请："
  warn "  1) 启动桌面 Anki，并安装插件 AnkiConnect (Code 2055492159)"
  warn "  2) 插件监听默认 127.0.0.1:8765"
  warn "  Anki 启动后一切 CRUD/复习自动可用；未连接时脚本会明确标出“未持久化”"
fi

ok "完成。开始使用:"
cat <<'USAGE'
  cd ~/.anki-tutor
  python3 src/cli.py ensure        # 建牌组 + 模型（幂等）
  python3 src/cli.py health        # 确认连接
  python3 src/cli.py ingest 资料   # 摄入资料 → 候选概念
  python3 src/cli.py due --limit 3 # 到期概念
USAGE