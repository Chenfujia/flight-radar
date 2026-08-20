#!/usr/bin/env bash
set -Eeuo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_root"

if ! command -v python3 >/dev/null 2>&1; then
  echo "未找到 python3，请安装 Python 3.11 或更高版本。" >&2
  exit 1
fi
if ! command -v uv >/dev/null 2>&1; then
  echo "未找到 uv，请先安装 uv：https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

uv sync
mkdir -p data/backups logs
if [[ ! -f config/radar.toml ]]; then
  uv run flight-radar init
fi
uv run flight-radar doctor
echo "安装完成。运行 ./install-systemd.sh 可安装 Linux 常驻服务。"
