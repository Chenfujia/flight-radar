# Flight Radar

个人日韩往返机票低价雷达。程序在 Windows 本地运行，通过 fli 查询 Google Flights，使用 SQLite 保存历史，并通过 PushPlus 安卓 App 推送好价。

## 使用

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
~~~

真实查询、价格和通知都可能受 Google Flights 与 PushPlus 当前服务状态影响。默认测试不访问网络。

产品和业务规则见 PRODUCT.md。
