# Flight Radar 开发约束

- 这是个人工具，可在 Linux 服务器或 Windows 本地运行，运行状态保存在本地 SQLite。
- fli 是唯一行情 Provider，不引入第二套航班抓取框架。
- 不使用浏览器自动化，不绕过 CAPTCHA 或站点限制。
- 默认测试不能访问真实 Google Flights 或 PushPlus。
- Provider 类型必须在 fli_adapter.py 内转换为本项目 domain 类型。
- 价格通知必须经过 fare_history 的 signature 和 notified_at 去重。
- PushPlus token 只从环境变量读取。
- 所有 SQLite 连接必须明确关闭，保证服务重启和备份时不残留文件锁。
