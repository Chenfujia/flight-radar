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
uv run flight-radar ui
~~~

`ui` 会启动一个只监听本机的轻量配置页面，打开终端显示的地址即可用表单配置出发机场、目的地、目标价、请假规则和 PushPlus。保存后会直接更新 `config/radar.toml`，页面还可以发送测试通知和启动一次后台扫描。也可以直接双击运行 `config.ps1`。

真实查询、价格和通知都可能受 Google Flights 与 PushPlus 当前服务状态影响。默认测试不访问网络。

产品和业务规则见 PRODUCT.md。

