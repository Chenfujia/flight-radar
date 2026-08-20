# Flight Radar

个人日韩往返机票低价雷达。程序可在 Linux 服务器或 Windows 本机运行，通过 fli 查询 Google Flights，使用 SQLite 保存历史，并通过 PushPlus 安卓 App 推送好价。

Linux 服务器是推荐运行方式：后台由 systemd 常驻，SQLite、日志和每日备份都保存在项目目录，不需要单独数据库服务。

## Linux 服务器部署

需要 Python 3.11+、uv 和 systemd。把仓库放到服务器后执行：

~~~bash
cd /path/to/flight-radar
./setup.sh
./install-systemd.sh
~~~

安装脚本会创建 `~/.config/flight-radar/flight-radar.env`（权限 600）并安装 `flight-radar.service`。PushPlus Token 可以直接在配置页面保存，也可以编辑这个文件：

~~~bash
nano ~/.config/flight-radar/flight-radar.env
# PUSHPLUS_TOKEN=你的 PushPlus token
sudo systemctl restart flight-radar
sudo systemctl status flight-radar
sudo journalctl -u flight-radar -f
~~~

配置页面只监听服务器本机，不直接暴露到公网。先启动页面：

~~~bash
./.venv/bin/python -m flight_radar.cli ui
~~~

在本地电脑另开终端建立 SSH 隧道，再访问 `http://127.0.0.1:8765`：

~~~bash
ssh -N -L 8765:127.0.0.1:8765 用户名@服务器地址
~~~

页面保存的 Linux Token 会写入上述 `flight-radar.env`；如果后台服务已经在运行，保存后执行 `sudo systemctl restart flight-radar` 让服务重新读取 Token。不要把 8765 端口直接开放到公网。

## Windows 使用

需要 Python 3.11+、uv 和一个 PushPlus token。

~~~powershell
.\setup.ps1
notepad .\config\radar.toml
$env:PUSHPLUS_TOKEN = "你的 PushPlus token"
uv run flight-radar doctor
uv run flight-radar scan
.\install-task.ps1
~~~

安装任务后，程序会在 Windows 登录时后台启动并定时扫描。

常用命令：

~~~powershell
uv run flight-radar scan
uv run flight-radar watch
uv run flight-radar deals
uv run flight-radar doctor
uv run flight-radar ui
~~~

`ui` 会启动一个只监听本机的轻量配置页面，打开终端显示的地址即可用表单配置出发机场、目的地、目标价、请假规则和 PushPlus。保存后会直接更新 `config/radar.toml`，页面还可以发送测试通知和启动一次后台扫描。也可以直接双击运行 `config.ps1`。

真实查询、价格和通知都可能受 Google Flights 与 PushPlus 当前服务状态影响。默认测试不访问网络。

产品和业务规则见 PRODUCT.md。
