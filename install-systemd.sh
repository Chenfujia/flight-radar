#!/usr/bin/env bash
set -Eeuo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python_bin="$project_root/.venv/bin/python"
service_name="flight-radar"
unit_file="/etc/systemd/system/${service_name}.service"

if [[ ! -x "$python_bin" ]]; then
  echo "未找到 $python_bin，请先运行 ./setup.sh。" >&2
  exit 1
fi

if [[ "${EUID}" -ne 0 ]]; then
  if ! command -v sudo >/dev/null 2>&1; then
    echo "安装 systemd 服务需要 root 权限，请用 root 或安装 sudo 后重试。" >&2
    exit 1
  fi
  exec sudo --preserve-env=PATH "$0" "$@"
fi

service_user="${SUDO_USER:-${USER:-root}}"
if ! id "$service_user" >/dev/null 2>&1; then
  echo "无法确定服务用户：$service_user" >&2
  exit 1
fi
service_home="$(getent passwd "$service_user" | cut -d: -f6)"
if [[ -z "$service_home" || ! -d "$service_home" ]]; then
  echo "无法确定 $service_user 的 home 目录。" >&2
  exit 1
fi

env_dir="$service_home/.config/flight-radar"
env_file="$env_dir/flight-radar.env"
install -d -m 700 -o "$service_user" -g "$(id -gn "$service_user")" "$env_dir"
if [[ ! -f "$env_file" ]]; then
  printf '# PushPlus 安卓通知 Token（不要提交到 GitHub）\nPUSHPLUS_TOKEN=\n' > "$env_file"
fi
chown "$service_user":"$(id -gn "$service_user")" "$env_file"
chmod 600 "$env_file"

tmp_unit="$(mktemp)"
trap 'rm -f "$tmp_unit"' EXIT
cat > "$tmp_unit" <<EOF
[Unit]
Description=Flight Radar personal low-fare scanner
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=$service_user
WorkingDirectory=$project_root
ExecStart=$python_bin -m flight_radar.cli watch
EnvironmentFile=-$env_file
Environment=PYTHONUNBUFFERED=1
UMask=0077
Restart=always
RestartSec=30
PrivateTmp=true
NoNewPrivileges=true
TimeoutStopSec=20

[Install]
WantedBy=multi-user.target
EOF
install -m 644 "$tmp_unit" "$unit_file"
systemctl daemon-reload
systemctl enable --now "$service_name.service"

echo "Linux 服务已安装并启动：$service_name"
echo "查看状态：sudo systemctl status $service_name"
echo "查看日志：sudo journalctl -u $service_name -f"
echo "配置页面请用 SSH 隧道访问，不要直接暴露 8765 端口："
echo "  ssh -N -L 8765:127.0.0.1:8765 $service_user@服务器地址"
echo "然后在服务器另开终端运行：$python_bin -m flight_radar.cli ui"
