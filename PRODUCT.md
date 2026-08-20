# 个人日韩机票低价雷达 — 完整产品文档

> 版本：v2.0  
> 日期：2026-08-20  
> 使用者：个人  
> 运行环境：Windows  
> 文档性质：完整交付规格，不是路线图

---

## 1. 产品定义

这是一个安装后可以长期自动运行的个人机票工具。

用户配置一次：

- 从杭州 HGH 或上海浦东 PVG 出发；
- 去日本或韩国；
- 2 名成人；
- 最多请 2 天假；
- 旅行 2 至 4 晚；
- 各目的地能接受的价格。

程序随后自动：

1. 查询未来 45 天的往返价格；
2. 找出低价日期；
3. 查询具体往返航班；
4. 判断能否下班后赶上、需要请几天假；
5. 计算杭州到机场的接驳成本；
6. 保存价格历史；
7. 判断当前是否值得提醒；
8. 通过 PushPlus 推送到安卓手机；
9. 提供可直接打开的 Google Flights 搜索链接；
10. 在 Windows 重启后自动继续运行。

系统只负责发现和解释好价。用户打开页面后自行确认价格并购买。

---

## 2. 完整产品形态

~~~text
TOML 配置
    ↓
fli 查询 Google Flights
    ↓
个人规则判断
    ↓
SQLite 保存历史
    ↓
好价等级与去重
    ↓
PushPlus 安卓通知
~~~

只使用：

- Python 3.12；
- fli；
- SQLite；
- PushPlus；
- Windows 任务计划程序。

不使用：

- faresnipe；
- swoop；
- fast-flights；
- JiPiao；
- flights_monitor；
- 浏览器自动化；
- Web 服务和 Dashboard；
- Redis、PostgreSQL、消息队列或微服务。

选择 fli 是因为它同时提供灵活日期价格和具体航班查询。其余项目不再进入运行依赖，避免重复 Provider、兼容冲突和额外维护。

---

## 3. 用户规则

### 3.1 出发机场

| 机场 | 接驳成本 | 从杭州到机场 | 机场缓冲 |
|---|---:|---:|---:|
| HGH | 0 元 | 60 分钟 | 120 分钟 |
| PVG | 两人合计 260 元 | 210 分钟 | 150 分钟 |

以上均可在配置中修改。

PVG 票价必须加上杭州往返上海的接驳成本后再与 HGH 比较。

### 3.2 目的地

日本：

~~~text
NRT, HND, KIX, FUK, NGO, CTS, OKA
~~~

韩国：

~~~text
ICN, GMP, CJU, PUS
~~~

默认重点：

~~~text
KIX, NRT, HND, ICN, GMP, CJU
~~~

### 3.3 航班偏好

- 2 名成人；
- 经济舱；
- 往返；
- 去程和返程均直飞；
- 2 至 4 晚；
- 有效旅行时间不少于 48 小时；
- 最多占用 2 个工作日。

### 3.4 工作和请假

默认工作时间：

~~~text
周一至周五
09:00 至 18:00
~~~

法定节假日和调休工作日由配置覆盖。

请假天数根据完整出行区间计算：

~~~text
出行开始
  = 去程起飞时间
  - 到出发机场接驳时间
  - 机场缓冲时间

出行结束
  = 返程落地时间
  + 从出发机场回杭州的接驳时间
~~~

将出行区间转换为 Asia/Shanghai 时区后，与每天的工作时段求交集。发生交集的工作日计为请假一天。

这样可以自然处理：

- 周五下班后出发，不请周五；
- 周五下午出发，需要请周五；
- 周一早上仍未回到杭州，需要请周一；
- PVG 晚班因接驳时间不足而赶不上；
- 周五加周一、周四加周五等不同组合。

不硬编码固定请假组合，只判断实际占用的工作日。

### 3.5 有效旅行时间

~~~text
有效旅行时间
  = 返程起飞时间
  - 去程落地时间
  - 到达机场进城惩罚
  - 返程前去机场惩罚
~~~

默认单程机场惩罚：

| 机场 | 分钟 |
|---|---:|
| HND | 45 |
| NRT | 90 |
| KIX | 70 |
| ICN | 70 |
| GMP | 35 |
| CJU | 30 |
| 其他 | 90 |

该值只用于比较行程质量，不作为真实交通时间承诺。

---

## 4. 价格口径

必须同时保存和展示：

~~~text
每人往返机票价
两人机票总价
杭州到出发机场接驳成本
两人门到门交通总成本
门到门人均成本
~~~

计算：

~~~text
两人门到门交通总成本
  = 两人机票总价 + 接驳成本

门到门人均成本
  = 两人门到门交通总成本 / 2
~~~

所有好价判断使用“门到门人均成本”，避免 PVG 裸票便宜但实际总成本更高。

价格是查询时的快照。通知必须标明查询时间，并提醒用户打开页面后价格可能变化。

---

## 5. 扫描流程

### 5.1 第一步：日期价格粗筛

对每个：

~~~text
出发机场 × 目的地 × 2/3/4 晚
~~~

调用 fli 的 SearchDates，查询未来 45 天价格日历。

禁止把 45 天展开成每天一次网络请求。

每条路线保留：

- 最低价的 2 个日期组合；
- 低于目标价 110% 的日期组合；
- 最近已经发送提醒但仍未出发的日期组合。

所有候选合并去重后，最多执行 30 次具体航班查询。

### 5.2 第二步：具体航班

对候选日期调用 fli 的 SearchFlights。

每次详细查询只保留符合以下条件的结果：

- 往返航段完整；
- 去程、返程均直飞；
- 价格和币种明确；
- 2 至 4 晚；
- 请假不超过 2 天；
- 有效旅行时间不少于 48 小时；
- 可以生成对应 Google Flights 搜索链接。

日期价格不能直接触发通知。只有取得具体航班时间后，才能判断请假、接驳和有效旅行时间。

### 5.3 运行频率

完整扫描每 2 小时运行一次，并增加正负 10% 的随机偏移。

不做动态频率、不为个别低价启动额外高频扫描。

单轮限制：

~~~text
最多 72 次日期价格查询
最多 30 次具体航班查询
~~~

超过限制的低优先级路线留到下一轮。

---

## 6. 航班数据

程序内部统一为以下结构：

~~~python
@dataclass(frozen=True)
class FlightSegment:
    origin: str
    destination: str
    departure_at: datetime
    arrival_at: datetime
    carrier_code: str
    flight_number: str | None


@dataclass(frozen=True)
class ItineraryQuote:
    provider: str
    outbound: tuple[FlightSegment, ...]
    inbound: tuple[FlightSegment, ...]
    price_per_person: Decimal
    total_price: Decimal
    currency: str
    booking_url: str
    observed_at: datetime
~~~

要求：

- datetime 必须带时区；
- fli 对象只能出现在 adapter 内；
- 业务代码只使用 ItineraryQuote；
- Provider 返回异常不能变成空结果；
- booking_url 使用确定的 Google Flights 搜索深链；
- 不依赖 fli 的 booking-options 解析。

航班签名由以下内容生成：

~~~text
出发机场
目的地机场
去程航班号与起飞时间
返程航班号与起飞时间
~~~

价格不进入签名。

航班号缺失时，使用承运人、机场、起飞和落地时间生成签名。

---

## 7. 好价判断

不使用机器学习，也不使用难以解释的综合公式。

每个目的地配置一个“门到门人均目标价”。

示例：

| 目的地 | 目标价 |
|---|---:|
| KIX | 1,650 元 |
| NRT | 1,850 元 |
| HND | 1,950 元 |
| ICN | 1,650 元 |
| GMP | 1,650 元 |
| CJU | 1,350 元 |

历史基线使用相同：

~~~text
出发机场
目的地机场
出发日期
返程日期
直飞条件
~~~

最近 21 天价格的中位数。至少有 5 条历史记录时才使用历史比较。

等级规则：

### EXCELLENT

满足任一条件：

~~~text
当前门到门人均成本 <= 目标价的 80%

或

历史样本充足
且当前价格 <= 历史中位数的 75%
~~~

### GREAT

满足任一条件：

~~~text
当前门到门人均成本 <= 目标价

或

历史样本充足
且当前价格 <= 历史中位数的 85%
~~~

### GOOD

~~~text
当前门到门人均成本 <= 目标价的 110%
且有效旅行时间 >= 60 小时
~~~

其他结果只保存，不通知。

所有等级仍必须先通过直飞、请假和有效旅行时间过滤。低价不能绕过行程可行性。

同等级排序：

1. 门到门人均成本更低；
2. 有效旅行时间更长；
3. 请假天数更少；
4. 出发日期更近。

---

## 8. 通知与去重

### 8.1 发送条件

同一个航班签名只在以下情况发送：

1. 第一次达到 GOOD、GREAT 或 EXCELLENT；
2. 等级上升；
3. 相比上次已通知价格下降至少 5%。

不会因为时间过去或程序重启而重复提醒。

### 8.2 PushPlus 消息

示例：

~~~text
🔥 大阪 GREAT

PVG → KIX · 春秋直飞
9/12 周六 02:15 → 05:30
9/15 周二 20:30 → 22:15

¥1,299 / 人
两人机票：¥2,598
杭州到浦东：约 ¥260
门到门交通：约 ¥2,858

近期中位：¥1,720 / 人
当前低约 24%
请假：周一、周二，共 2 天
有效旅行：约 82 小时

查询时间：8/20 14:30
价格为搜索快照，请打开页面确认

[打开 Google Flights]
~~~

通知必须包含：

- 路线、日期和航班时间；
- 航司和是否直飞；
- 每人价格；
- 两人机票总价；
- 接驳成本和门到门总成本；
- 请假日期；
- 有效旅行时间；
- 好价原因；
- 查询时间；
- 搜索链接。

用户在安卓手机安装 PushPlus App、登录并允许通知后，程序通过其 app 渠道发送消息。

请求：

~~~text
POST https://www.pushplus.plus/send
channel = app
template = markdown
~~~

PushPlus token 只从环境变量 PUSHPLUS_TOKEN 读取，不能写入配置和日志。

---

## 9. SQLite

只保留一张业务表 `fare_history`，每次详细航班查询都追加一条记录。它同时保存价格历史、规则计算结果和通知状态，不再拆分日期价格表、告警表或扫描运行表。

~~~text
id, signature, provider
origin, destination, departure_date, return_date
departure_at, outbound_arrival_at, return_departure_at, return_arrival_at
airline, flight_numbers
price_per_person, fare_total, transfer_total, door_to_door_total
effective_price_per_person, currency
leave_days, effective_hours, deal_level, reasons
booking_url, observed_at, notified_at
~~~

建立两个索引：按航班签名和时间查询历史，按路线和日期查询历史。

数据库启动设置：

~~~sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA busy_timeout = 5000;
~~~

数据库连接必须明确关闭，确保 Windows 不残留文件锁。

每天使用 SQLite backup API 自动备份一次，保留最近 14 份。

---

## 10. 配置文件

文件：config/radar.toml

~~~toml
[profile]
timezone = "Asia/Shanghai"
passengers = 2

[work]
start = "09:00"
end = "18:00"
max_leave_days = 2

[trip]
search_horizon_days = 45
min_nights = 2
max_nights = 4
min_effective_hours = 48

[flight]
currency = "CNY"
nonstop_only = true

[origins.HGH]
enabled = true
transfer_cost_total_cny = 0
transfer_minutes = 60
airport_buffer_minutes = 120

[origins.PVG]
enabled = true
transfer_cost_total_cny = 260
transfer_minutes = 210
airport_buffer_minutes = 150

[destinations]
enabled = ["KIX", "NRT", "HND", "FUK", "NGO", "CTS", "OKA",
           "ICN", "GMP", "CJU", "PUS"]

[target_price]
KIX = 1650
NRT = 1850
HND = 1950
ICN = 1650
GMP = 1650
CJU = 1350
FUK = 1700
NGO = 1700
CTS = 2200
OKA = 1900
PUS = 1500

[airport_penalty_minutes]
HND = 45
NRT = 90
KIX = 70
ICN = 70
GMP = 35
CJU = 30
default = 90

[scanner]
interval_minutes = 120
max_calendar_queries = 72
max_detail_queries = 30
jitter_ratio = 0.10

[alerts]
meaningful_drop_ratio = 0.05

[pushplus]
endpoint = "https://www.pushplus.plus/send"
channel = "app"
token_env = "PUSHPLUS_TOKEN"

[calendar]
holidays = []
forced_workdays = []
~~~

target_price 表示包含出发机场接驳分摊后的门到门人均目标价。

---

## 11. 命令

只提供 5 个命令。

~~~bash
flight-radar init
~~~

创建配置、数据和日志目录，不覆盖已有文件。

~~~bash
flight-radar scan
~~~

立即执行一轮真实扫描。

~~~bash
flight-radar watch
~~~

每 2 小时持续扫描，支持 Ctrl+C 正常退出。

~~~bash
flight-radar deals
~~~

从 SQLite 显示当前 GOOD、GREAT、EXCELLENT，不发网络请求。

~~~bash
flight-radar doctor
~~~

检查配置、PushPlus token、数据库、fli 版本、最近扫描结果，发送一条测试通知，并执行一条受限的真实查询。

---

## 12. Windows 交付

交付目录必须包含：

~~~text
flight-radar/
├── setup.ps1
├── start.ps1
├── install-task.ps1
├── pyproject.toml
├── uv.lock
├── config/
│   └── radar.example.toml
├── src/
├── tests/
├── data/
└── logs/
~~~

### setup.ps1

一次完成：

1. 检查 Python 3.12 和 uv；
2. 按 uv.lock 安装依赖；
3. 创建 config/radar.toml；
4. 创建 data、backups、logs；
5. 运行数据库迁移；
6. 运行 doctor。

### start.ps1

启动 flight-radar watch。

### install-task.ps1

创建当前用户的 Windows 任务计划：

- 用户登录时启动；
- 失败后 1 分钟重启；
- 不启动重复实例；
- 工作目录指向安装目录；
- 调用 start.ps1；
- 不把 PushPlus token 写进任务命令行。

用户实际使用步骤：

~~~text
1. 运行 setup.ps1
2. 修改 config/radar.toml
3. 在安卓安装 PushPlus App，登录并允许通知
4. 设置 PUSHPLUS_TOKEN
5. 运行 install-task.ps1
6. 无需再打开程序，等待手机提醒
~~~

---

## 13. 错误处理

错误类别：

~~~text
RATE_LIMITED
NETWORK_ERROR
TIMEOUT
SCHEMA_DRIFT
BAD_RESPONSE
CONFIG_ERROR
UNKNOWN
~~~

规则：

- 单条路线失败不终止其他路线；
- Provider 失败不记为无票；
- 失败结果不参与历史中位数；
- 连续 3 轮扫描失败时发送一次 PushPlus 故障提醒；
- 恢复成功后发送一次恢复提醒；
- 429 时等待下一轮，不提高请求频率；
- schema drift 时停止扫描并明确告警；
- PushPlus 失败写日志，不回滚已保存价格；
- 每轮完成后关闭网络客户端和 SQLite 连接。

日志使用 INFO，单文件最大 10 MB，保留 3 个文件。

日志禁止输出 PushPlus token、Cookie、完整环境变量和上游完整响应。

---

## 14. 项目结构

~~~text
src/flight_radar/
├── cli.py
├── config.py
├── domain.py
├── fli_adapter.py
├── planner.py
├── scanner.py
├── deals.py
├── storage.py
├── notifier.py
~~~

各文件职责：

| 文件 | 职责 |
|---|---|
| cli.py | 5 个命令 |
| config.py | TOML 读取和校验 |
| domain.py | 航班和报价数据结构 |
| fli_adapter.py | SearchDates、SearchFlights 转换 |
| planner.py | 请假、接驳、有效时间 |
| scanner.py | 两步扫描和请求上限 |
| deals.py | 目标价、历史价和等级 |
| storage.py | 单表历史、通知状态、备份 |
| notifier.py | PushPlus 消息和故障通知 |

不再拆更多层。

运行依赖：

~~~text
flights
httpx
~~~

flights 是 punitarani/fli 的发行包名，Python 导入名是 fli。

标准库使用 sqlite3、tomllib、argparse、logging 和 zoneinfo。

---

## 15. 测试要求

默认测试完全离线。

必须覆盖：

### 个人规则

- 周五下班后出发不算周五请假；
- 周五下午出发算周五请假；
- PVG 接驳导致晚班赶不上；
- 周一回到杭州过晚算周一请假；
- 调休工作日正确覆盖；
- 超过 2 天请假被淘汰；
- 有效旅行时间计算正确。

### 价格与提醒

- PVG 接驳成本进入门到门价格；
- 历史不足 5 条时不使用中位数；
- GOOD、GREAT、EXCELLENT 边界正确；
- 相同航班相同价格不重复发送；
- 等级升级重新发送；
- 降价至少 5% 重新发送。

### fli Adapter

- SearchDates fixture 正确转换；
- SearchFlights fixture 正确转换；
- 往返航段、时区、币种和总价正确；
- 异常响应产生错误，不返回空列表；
- 测试日期通过固定 Clock 生成，不随时间自然过期。

### SQLite

- 空库可以初始化；
- 重启后历史和通知状态保留；
- 连接关闭后 Windows 可以删除临时数据库；
- 自动备份可以打开；
- integrity_check 通过。

完整离线流程必须验证：

~~~text
日期价格 fixture
→ 选中候选
→ 详细航班 fixture
→ 计算请假和接驳
→ 保存 SQLite
→ 判断 GREAT
→ Fake PushPlus 收到一次
→ 再运行一轮不重复通知
~~~

真实查询只由 doctor 执行一条受限路线，不进入默认测试。

---

## 16. 成品验收

以下全部通过才算交付完成：

- [ ] setup.ps1 在干净 Windows 环境成功安装；
- [ ] 用户只需修改一份 TOML 和设置 PUSHPLUS_TOKEN；
- [ ] scan 可以完成 HGH/PVG 到日韩路线查询；
- [ ] SearchDates 没有展开为每天一个请求；
- [ ] 详细查询不超过每轮 30 次；
- [ ] 具体航班时间参与请假判断；
- [ ] PVG 接驳时间和成本都参与判断；
- [ ] 价格历史写入 SQLite；
- [ ] GOOD、GREAT、EXCELLENT 规则可解释；
- [ ] PushPlus 安卓通知包含完整决策信息和可点击链接；
- [ ] 同价重复扫描不重复通知；
- [ ] 程序重启后不重复通知；
- [ ] Provider 失败不产生无票结论；
- [ ] 连续失败和恢复各只通知一次；
- [ ] 每日备份生成并只保留 14 份；
- [ ] install-task.ps1 安装后登录 Windows 自动运行；
- [ ] 连续运行 72 小时无数据库锁、无消息轰炸、无持续内存增长；
- [ ] 所有离线测试通过；
- [ ] doctor 的受限真实查询成功。

最终验收场景：

> 用户设置杭州或上海出发、日韩、未来 45 天、2 人、最多请 2 天、旅行 2 至 4 晚。程序自动运行并记录价格。某个 PVG 到 KIX 的日期出现低价，系统取得具体航班，正确计算杭州到浦东接驳、两人总价、请假日期和有效旅行时间，手机只收到一条高质量提醒。用户点击链接打开 Google Flights，自行确认并购买。程序继续运行，不需要日常维护。

---

## 17. 开发硬约束

1. 只使用 fli 一个行情源。
2. 不引入第二 Provider 或验价框架。
3. 不 Fork faresnipe。
4. 不引入浏览器自动化。
5. fli 类型不能进入业务层。
6. 日期价格不能直接触发通知。
7. Provider 错误不能变成无票。
8. SQLite 是唯一存储，只保留 `fare_history` 一张业务表。
9. SQLite 连接必须明确关闭。
10. 只保留一张业务表和必要的业务模块。
11. 默认测试禁止网络请求。
12. 时间测试必须注入 Clock。
13. 每条通知必须去重。
14. 不增加 Dashboard、Web API、插件系统或多用户能力。
15. 任何新增设计必须直接服务于“发现并提醒个人可用的日韩低价往返航班”。

---

## 18. 完成后的使用体验

~~~text
第一次：
运行 setup.ps1
修改 radar.toml
在安卓安装并登录 PushPlus
设置 PUSHPLUS_TOKEN
运行 install-task.ps1

之后：
电脑登录
  → 程序后台启动
  → 每 2 小时扫描
  → 没有好价就保持安静
  → 有好价时安卓手机收到 PushPlus 通知
  → 点击 Google Flights
  → 用户自行确认并下单
~~~

这就是完整产品。没有需要用户日常操作的后台，没有附加系统，也没有为了备用而常驻的第二套数据源。
