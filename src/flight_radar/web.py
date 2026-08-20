from __future__ import annotations

import json
import logging
import math
import os
import re
import subprocess
import sys
import threading
import tomllib
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .config import load_config
from .notifier import EmailNotifier

logger = logging.getLogger(__name__)

SUPPORTED_ORIGINS = ("HGH", "PVG")
SUPPORTED_DESTINATIONS = (
    "KIX",
    "NRT",
    "HND",
    "ICN",
    "GMP",
    "CJU",
    "PUS",
    "FUK",
    "NGO",
    "CTS",
    "OKA",
)
MAX_BODY_BYTES = 1024 * 1024


def _raw_config(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def _toml_array(values: list[Any]) -> str:
    return "[" + ", ".join(_toml_value(value) for value in values) + "]"


def _number(value: Any, field: str, *, minimum: float = 0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} 必须是数字") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} 必须是有限数字")
    if number < minimum:
        raise ValueError(f"{field} 不能小于 {minimum}")
    return number


def _integer(value: Any, field: str, *, minimum: int = 0, maximum: int = 10000) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} 必须是整数") from exc
    if number < minimum or number > maximum:
        raise ValueError(f"{field} 必须在 {minimum} 到 {maximum} 之间")
    return number


def _date_list(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field} 格式不正确")
    result: list[str] = []
    for item in value:
        raw = str(item).strip()
        try:
            date.fromisoformat(raw)
        except ValueError as exc:
            raise ValueError(f"{field} 中的日期必须是 YYYY-MM-DD") from exc
        result.append(raw)
    return result


def _code(value: Any, field: str) -> str:
    code = str(value).strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", code):
        raise ValueError(f"{field} 必须是三位机场代码")
    return code


def validate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize the JSON payload submitted by the config page."""
    if not isinstance(payload, dict):
        raise ValueError("配置内容格式不正确")

    profile = payload.get("profile", {})
    work = payload.get("work", {})
    trip = payload.get("trip", {})
    flight = payload.get("flight", {})
    scanner = payload.get("scanner", {})
    alerts = payload.get("alerts", {})
    smtp = payload.get("smtp", {})
    origins_payload = payload.get("origins", [])
    destinations_payload = payload.get("destinations", [])
    targets_payload = payload.get("target_price", {})
    penalties_payload = payload.get("airport_penalty_minutes", {})

    if not isinstance(profile, dict) or not isinstance(work, dict) or not isinstance(trip, dict):
        raise ValueError("基础配置格式不正确")
    if (
        not isinstance(flight, dict)
        or not isinstance(scanner, dict)
        or not isinstance(alerts, dict)
        or not isinstance(smtp, dict)
    ):
        raise ValueError("高级配置格式不正确")
    if not isinstance(origins_payload, list) or not origins_payload:
        raise ValueError("至少配置一个出发机场")
    if not isinstance(destinations_payload, list) or not destinations_payload:
        raise ValueError("至少选择一个目的地")
    if not isinstance(targets_payload, dict) or not isinstance(penalties_payload, dict):
        raise ValueError("价格或机场耗时配置格式不正确")

    origins: list[dict[str, Any]] = []
    enabled_origins = 0
    seen_origins: set[str] = set()
    for raw in origins_payload:
        if not isinstance(raw, dict):
            raise ValueError("出发机场配置格式不正确")
        code = _code(raw.get("code"), "出发机场")
        if code in seen_origins:
            raise ValueError(f"出发机场重复：{code}")
        seen_origins.add(code)
        enabled = bool(raw.get("enabled", False))
        if enabled:
            enabled_origins += 1
        origins.append(
            {
                "code": code,
                "enabled": enabled,
                "transfer_cost_total_cny": _number(
                    raw.get("transfer_cost_total_cny", 0), f"{code} 接驳费用"
                ),
                "transfer_minutes": _integer(
                    raw.get("transfer_minutes", 0), f"{code} 接驳时间", maximum=1440
                ),
                "airport_buffer_minutes": _integer(
                    raw.get("airport_buffer_minutes", 0), f"{code} 机场缓冲", maximum=720
                ),
            }
        )
    if enabled_origins == 0:
        raise ValueError("至少启用一个出发机场")

    destinations: list[str] = []
    for raw in destinations_payload:
        code = _code(raw, "目的地")
        if code not in SUPPORTED_DESTINATIONS:
            raise ValueError(f"暂不支持目的地：{code}")
        if code not in destinations:
            destinations.append(code)

    target_price: dict[str, float] = {}
    for code in destinations:
        if code not in targets_payload:
            raise ValueError(f"请填写 {code} 的目标价格")
        target_price[code] = _number(targets_payload[code], f"{code} 目标价格", minimum=1)

    penalties: dict[str, int] = {}
    for raw_code, raw_value in penalties_payload.items():
        code = "default" if str(raw_code).lower() == "default" else _code(raw_code, "机场代码")
        penalties[code] = _integer(raw_value, f"{code} 机场耗时", maximum=720)
    penalties.setdefault("default", 90)

    timezone = str(profile.get("timezone", "Asia/Shanghai")).strip()
    if not timezone:
        raise ValueError("时区不能为空")
    currency = str(flight.get("currency", "CNY")).strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("币种必须是三位字母")
    smtp_host = str(smtp.get("host", "smtp.qq.com")).strip()
    if not smtp_host:
        raise ValueError("SMTP 服务器不能为空")
    smtp_password_env = str(
        smtp.get("password_env", "FLIGHT_RADAR_SMTP_PASSWORD")
    ).strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", smtp_password_env):
        raise ValueError("SMTP 密码环境变量名不正确")

    normalized = {
        "profile": {
            "timezone": timezone,
            "passengers": _integer(profile.get("passengers", 2), "出行人数", minimum=1, maximum=9),
        },
        "work": {
            "start": str(work.get("start", "09:00")),
            "end": str(work.get("end", "18:00")),
            "max_leave_days": _integer(work.get("max_leave_days", 2), "最多请假天数", maximum=30),
        },
        "trip": {
            "search_horizon_days": _integer(
                trip.get("search_horizon_days", 45), "查询未来天数", minimum=1, maximum=365
            ),
            "min_nights": _integer(trip.get("min_nights", 2), "最少晚数", minimum=1, maximum=30),
            "max_nights": _integer(trip.get("max_nights", 4), "最多晚数", minimum=1, maximum=30),
            "min_effective_hours": _integer(
                trip.get("min_effective_hours", 48), "最少有效旅行小时", maximum=720
            ),
        },
        "flight": {
            "currency": currency,
            "nonstop_only": bool(flight.get("nonstop_only", True)),
        },
        "origins": origins,
        "destinations": destinations,
        "target_price": target_price,
        "airport_penalty_minutes": penalties,
        "scanner": {
            "interval_minutes": _integer(
                scanner.get("interval_minutes", 120), "扫描间隔", minimum=5, maximum=1440
            ),
            "max_calendar_queries": _integer(
                scanner.get("max_calendar_queries", 72), "日期查询上限", minimum=1, maximum=500
            ),
            "max_detail_queries": _integer(
                scanner.get("max_detail_queries", 30), "详细查询上限", minimum=1, maximum=100
            ),
            "jitter_ratio": _number(scanner.get("jitter_ratio", 0.10), "随机抖动比例"),
        },
        "alerts": {
            "meaningful_drop_ratio": _number(
                alerts.get("meaningful_drop_ratio", 0.05), "降价通知比例"
            ),
        },
        "smtp": {
            "host": smtp_host,
            "port": _integer(smtp.get("port", 465), "SMTP 端口", minimum=1, maximum=65535),
            "ssl": bool(smtp.get("ssl", True)),
            "username": str(smtp.get("username", "")).strip(),
            "recipient": str(smtp.get("recipient", "")).strip(),
            "password_env": smtp_password_env,
        },
        "calendar": {
            "holidays": _date_list(payload.get("holidays", []), "节假日"),
            "forced_workdays": _date_list(payload.get("forced_workdays", []), "调休工作日"),
        },
    }
    if normalized["trip"]["min_nights"] > normalized["trip"]["max_nights"]:
        raise ValueError("最少晚数不能大于最多晚数")
    if normalized["work"]["start"] >= normalized["work"]["end"]:
        raise ValueError("工作开始时间必须早于结束时间")
    if normalized["scanner"]["jitter_ratio"] > 0.5:
        raise ValueError("随机抖动比例不能大于 0.5")
    if normalized["alerts"]["meaningful_drop_ratio"] > 1:
        raise ValueError("降价通知比例必须在 0 到 1 之间")
    return normalized


def serialize_payload(payload: dict[str, Any]) -> str:
    """Serialize the normalized page payload without writing any secret."""
    data = validate_payload(payload)
    lines: list[str] = []

    def section(name: str) -> None:
        if lines:
            lines.append("")
        lines.append(f"[{name}]")

    section("profile")
    lines.append(f"timezone = {_toml_value(data['profile']['timezone'])}")
    lines.append(f"passengers = {data['profile']['passengers']}")
    section("work")
    lines.append(f"start = {_toml_value(data['work']['start'])}")
    lines.append(f"end = {_toml_value(data['work']['end'])}")
    lines.append(f"max_leave_days = {data['work']['max_leave_days']}")
    section("trip")
    for key, value in data["trip"].items():
        lines.append(f"{key} = {value}")
    section("flight")
    lines.append(f"currency = {_toml_value(data['flight']['currency'])}")
    lines.append(f"nonstop_only = {_toml_value(data['flight']['nonstop_only'])}")
    for origin in data["origins"]:
        section(f"origins.{origin['code']}")
        lines.append(f"enabled = {_toml_value(origin['enabled'])}")
        lines.append(f"transfer_cost_total_cny = {origin['transfer_cost_total_cny']:g}")
        lines.append(f"transfer_minutes = {origin['transfer_minutes']}")
        lines.append(f"airport_buffer_minutes = {origin['airport_buffer_minutes']}")
    section("destinations")
    lines.append(f"enabled = {_toml_array(data['destinations'])}")
    section("target_price")
    for code in data["destinations"]:
        lines.append(f"{code} = {data['target_price'][code]:g}")
    section("airport_penalty_minutes")
    for code, value in data["airport_penalty_minutes"].items():
        lines.append(f"{code} = {value}")
    section("scanner")
    for key, value in data["scanner"].items():
        lines.append(f"{key} = {value:g}" if isinstance(value, float) else f"{key} = {value}")
    section("alerts")
    lines.append(f"meaningful_drop_ratio = {data['alerts']['meaningful_drop_ratio']:g}")
    section("smtp")
    lines.append(f"host = {_toml_value(data['smtp']['host'])}")
    lines.append(f"port = {data['smtp']['port']}")
    lines.append(f"ssl = {_toml_value(data['smtp']['ssl'])}")
    lines.append(f"username = {_toml_value(data['smtp']['username'])}")
    lines.append(f"recipient = {_toml_value(data['smtp']['recipient'])}")
    lines.append(f"password_env = {_toml_value(data['smtp']['password_env'])}")
    section("calendar")
    lines.append(f"holidays = {_toml_array(data['calendar']['holidays'])}")
    lines.append(f"forced_workdays = {_toml_array(data['calendar']['forced_workdays'])}")
    return "\n".join(lines) + "\n"


def config_payload(path: Path) -> dict[str, Any]:
    raw = _raw_config(path)
    profile = raw.get("profile", {})
    work = raw.get("work", {})
    trip = raw.get("trip", {})
    flight = raw.get("flight", {})
    scanner = raw.get("scanner", {})
    alerts = raw.get("alerts", {})
    smtp = raw.get("smtp", {})
    origins_raw = raw.get("origins", {})
    origin_codes = list(dict.fromkeys([*SUPPORTED_ORIGINS, *origins_raw.keys()]))
    origins = []
    for code in origin_codes:
        item = origins_raw.get(code, {})
        origins.append(
            {
                "code": code,
                "enabled": bool(item.get("enabled", False)),
                "transfer_cost_total_cny": item.get("transfer_cost_total_cny", 0),
                "transfer_minutes": item.get("transfer_minutes", 0),
                "airport_buffer_minutes": item.get("airport_buffer_minutes", 0),
            }
        )
    selected = [str(item).upper() for item in raw.get("destinations", {}).get("enabled", [])]
    targets_raw = raw.get("target_price", {})
    destination_options = list(
        dict.fromkeys([*SUPPORTED_DESTINATIONS, *selected, *[str(key).upper() for key in targets_raw]])
    )
    return {
        "profile": {
            "timezone": profile.get("timezone", "Asia/Shanghai"),
            "passengers": profile.get("passengers", 2),
        },
        "work": {
            "start": work.get("start", "09:00"),
            "end": work.get("end", "18:00"),
            "max_leave_days": work.get("max_leave_days", 2),
        },
        "trip": {
            "search_horizon_days": trip.get("search_horizon_days", 45),
            "min_nights": trip.get("min_nights", 2),
            "max_nights": trip.get("max_nights", 4),
            "min_effective_hours": trip.get("min_effective_hours", 48),
        },
        "flight": {
            "currency": flight.get("currency", "CNY"),
            "nonstop_only": flight.get("nonstop_only", True),
        },
        "origins": origins,
        "destination_options": destination_options,
        "destinations": selected,
        "target_price": {str(key).upper(): value for key, value in targets_raw.items()},
        "airport_penalty_minutes": {
            str(key).upper() if str(key).lower() != "default" else "default": value
            for key, value in raw.get("airport_penalty_minutes", {}).items()
        },
        "scanner": {
            "interval_minutes": scanner.get("interval_minutes", 120),
            "max_calendar_queries": scanner.get("max_calendar_queries", 72),
            "max_detail_queries": scanner.get("max_detail_queries", 30),
            "jitter_ratio": scanner.get("jitter_ratio", 0.10),
        },
        "alerts": {"meaningful_drop_ratio": alerts.get("meaningful_drop_ratio", 0.05)},
        "smtp": {
            "host": smtp.get("host", "smtp.qq.com"),
            "port": smtp.get("port", 465),
            "ssl": smtp.get("ssl", True),
            "username": smtp.get("username", ""),
            "recipient": smtp.get("recipient", ""),
            "password_env": str(smtp.get("password_env", "FLIGHT_RADAR_SMTP_PASSWORD")),
            "password_configured": bool(
                os.getenv(str(smtp.get("password_env", "FLIGHT_RADAR_SMTP_PASSWORD")))
            ),
        },
        "holidays": raw.get("calendar", {}).get("holidays", []),
        "forced_workdays": raw.get("calendar", {}).get("forced_workdays", []),
    }


def save_config(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    normalized = validate_payload(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(serialize_payload(normalized), encoding="utf-8")
    temporary.replace(path)
    load_config(path)
    return normalized


def _persist_posix_secret(environment_name: str, secret: str, environment_file: Path | None = None) -> str:
    environment_file = environment_file or Path(
        os.getenv(
            "FLIGHT_RADAR_ENV_FILE",
            str(Path.home() / ".config" / "flight-radar" / "flight-radar.env"),
        )
    ).expanduser()
    environment_file.parent.mkdir(parents=True, exist_ok=True)
    existing = environment_file.read_text(encoding="utf-8") if environment_file.exists() else ""
    lines = existing.splitlines()
    replacement = f"{environment_name}={secret}"
    replaced = False
    output: list[str] = []
    for line in lines:
        if line.lstrip().startswith(f"{environment_name}="):
            if not replaced:
                output.append(replacement)
                replaced = True
            continue
        output.append(line)
    if not replaced:
        output.append(replacement)
    temporary = environment_file.with_suffix(environment_file.suffix + ".tmp")
    temporary.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    temporary.replace(environment_file)
    try:
        environment_file.chmod(0o600)
    except OSError:
        logger.warning("无法设置 SMTP 密码环境文件权限：%s", environment_file)
    return f"已保存到 {environment_file}"


def persist_user_secret(environment_name: str, secret: str) -> str:
    secret = secret.strip()
    if not secret or len(secret) > 512:
        raise ValueError("SMTP 授权码不能为空")
    if any(character in secret for character in "\r\n"):
        raise ValueError("SMTP 授权码格式不正确")
    os.environ[environment_name] = secret
    if os.name != "nt":
        return _persist_posix_secret(environment_name, secret)
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, environment_name, 0, winreg.REG_SZ, secret)
    except OSError as exc:
        raise RuntimeError("无法写入当前用户环境变量") from exc
    return "已保存到当前 Windows 用户环境变量"


UI_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>机票雷达配置</title>
  <style>
    :root { color-scheme: light; --ink:#17202a; --muted:#6b7280; --line:#e5e7eb; --blue:#2563eb; --blue-soft:#eff6ff; --bg:#f5f7fb; --card:#fff; --green:#15803d; }
    * { box-sizing: border-box; }
    body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.55 system-ui,-apple-system,"Microsoft YaHei",sans-serif; }
    .wrap { max-width:1020px; margin:0 auto; padding:28px 18px 56px; }
    header { display:flex; justify-content:space-between; align-items:flex-start; gap:20px; margin-bottom:20px; }
    h1 { margin:0 0 4px; font-size:28px; letter-spacing:-.03em; }
    h2 { margin:0 0 16px; font-size:18px; }
    h3 { margin:0 0 4px; font-size:15px; }
    p { margin:4px 0; }
    .sub { color:var(--muted); }
    .status { text-align:right; color:var(--muted); font-size:13px; }
    .status strong { color:var(--green); }
    .card { background:var(--card); border:1px solid var(--line); border-radius:16px; padding:20px; margin:14px 0; box-shadow:0 5px 18px rgba(15,23,42,.035); }
    .grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:14px; }
    .grid.two { grid-template-columns:repeat(2,minmax(0,1fr)); }
    label { display:flex; flex-direction:column; gap:5px; color:#374151; font-size:13px; }
    input, select, textarea { width:100%; border:1px solid #d1d5db; border-radius:9px; padding:9px 10px; background:#fff; color:var(--ink); font:inherit; }
    input:focus, select:focus, textarea:focus { outline:3px solid #dbeafe; border-color:var(--blue); }
    input[type=checkbox] { width:18px; height:18px; accent-color:var(--blue); }
    .check { flex-direction:row; align-items:center; gap:8px; padding-top:26px; }
    .origin-grid, .dest-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }
    .origin, .destination { border:1px solid var(--line); border-radius:12px; padding:14px; }
    .origin-top, .dest-top { display:flex; align-items:center; justify-content:space-between; margin-bottom:12px; }
    .origin-top label, .dest-top label { flex-direction:row; align-items:center; font-weight:650; font-size:15px; }
    .hint { color:var(--muted); font-size:12px; }
    .actions { display:flex; flex-wrap:wrap; gap:10px; align-items:center; position:sticky; bottom:12px; background:rgba(245,247,251,.9); padding-top:8px; }
    button { border:0; border-radius:9px; padding:10px 16px; cursor:pointer; background:var(--blue); color:#fff; font:600 14px inherit; }
    button.secondary { background:#e5e7eb; color:#1f2937; }
    button.green { background:#15803d; }
    button:disabled { opacity:.55; cursor:wait; }
    #message { min-height:24px; margin-left:4px; color:#374151; }
    .notice { background:var(--blue-soft); border:1px solid #bfdbfe; border-radius:10px; padding:10px 12px; color:#1e40af; font-size:13px; }
    @media (max-width:720px) { .grid,.grid.two,.origin-grid,.dest-grid { grid-template-columns:1fr 1fr; } header { display:block; } .status { text-align:left; margin-top:8px; } }
    @media (max-width:480px) { .grid,.grid.two,.origin-grid,.dest-grid { grid-template-columns:1fr; } .wrap { padding:20px 12px 42px; } }
  </style>
</head>
<body>
  <main class="wrap">
    <header>
      <div><h1>机票雷达配置</h1><p class="sub">设置一次，程序按规则自动扫描并推送好价。</p></div>
      <div class="status">邮件通知：<strong id="email-status">检查中</strong><br><span id="scan-status">尚未启动扫描</span></div>
    </header>
    <form id="config-form">
      <section class="card"><h2>出行和请假</h2>
        <div class="grid">
          <label>出行人数<input id="passengers" type="number" min="1" max="9"></label>
          <label>最多请假天数<input id="max-leave-days" type="number" min="0" max="30"></label>
          <label>查询未来天数<input id="horizon" type="number" min="1" max="365"></label>
          <label>最少有效旅行小时<input id="min-effective-hours" type="number" min="0" max="720"></label>
          <label>最少旅行晚数<input id="min-nights" type="number" min="1" max="30"></label>
          <label>最多旅行晚数<input id="max-nights" type="number" min="1" max="30"></label>
          <label>工作开始<input id="work-start" type="time"></label>
          <label>工作结束<input id="work-end" type="time"></label>
        </div>
        <p class="hint">程序会把机场接驳和机场缓冲时间一起算进请假判断。</p>
      </section>
      <section class="card"><h2>出发机场</h2><div id="origins" class="origin-grid"></div></section>
      <section class="card"><h2>目的地和目标价</h2><p class="hint">目标价按每人门到门总成本判断。勾选后才会查询该目的地。</p><div id="destinations" class="dest-grid"></div></section>
      <section class="card"><h2>扫描偏好</h2>
        <div class="grid two">
          <label>扫描间隔（分钟）<input id="interval" type="number" min="5" max="1440"></label>
          <label>同价降价通知比例（%）<input id="drop-ratio" type="number" min="0" max="100" step="1"></label>
          <label class="check"><input id="nonstop" type="checkbox">只接受直飞</label>
          <label class="check"><input id="jitter" type="checkbox">扫描时间随机抖动</label>
        </div>
        <p class="hint">详细查询上限和日期查询上限保持程序安全默认值，不在页面中反复调整。</p>
      </section>
      <section class="card"><h2>节假日和调休</h2>
        <div class="grid two">
          <label>法定假日（每行一个日期）<textarea id="holidays" rows="5" placeholder="2026-10-01"></textarea></label>
          <label>调休工作日（每行一个日期）<textarea id="forced-workdays" rows="5" placeholder="2026-10-10"></textarea></label>
        </div>
      </section>
      <section class="card"><h2>安卓邮件通知</h2>
        <div class="notice">程序使用普通 SMTP 发邮件，安卓邮箱 App 会收到通知。邮箱授权码不会写进 radar.toml 或 GitHub；Linux 保存到当前用户的 flight-radar.env（权限 600），Windows 保存到当前用户环境变量。</div>
        <div class="grid">
          <label>SMTP 服务器<input id="smtp-host" type="text" placeholder="smtp.qq.com"></label>
          <label>SMTP 端口<input id="smtp-port" type="number" min="1" max="65535"></label>
          <label class="check"><input id="smtp-ssl" type="checkbox">SSL 连接（465）</label>
          <label>发件邮箱<input id="smtp-username" type="email" placeholder="你的邮箱"></label>
          <label>收件邮箱<input id="smtp-recipient" type="email" placeholder="可填自己的邮箱"></label>
          <label>邮箱授权码<input id="smtp-password" type="password" autocomplete="off" placeholder="留空表示不修改"></label>
        </div>
        <p class="hint">不要填邮箱登录密码，填写邮箱后台生成的 SMTP 授权码/应用专用密码。发件和收件可以是同一个邮箱。</p>
      </section>
      <div class="actions">
        <button type="submit">保存配置</button>
        <button type="button" class="secondary" id="reload">重新读取</button>
        <button type="button" class="green" id="test-notify">发送测试通知</button>
        <button type="button" class="secondary" id="start-scan">立即扫描</button>
        <span id="message"></span>
      </div>
    </form>
  </main>
  <script>
    let state = null;
    let timer = null;
    const $ = id => document.getElementById(id);
    const escapeHtml = value => String(value).replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
    const lines = value => String(value || '').split(/\r?\n/).map(x => x.trim()).filter(Boolean);
    async function api(path, options = {}) {
      const response = await fetch(path, {headers:{'Content-Type':'application/json'}, ...options});
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.message || '请求失败');
      return body;
    }
    function show(message, error = false) { $('message').textContent = message; $('message').style.color = error ? '#b91c1c' : '#374151'; }
    function render(data) {
      state = data;
      $('passengers').value = data.profile.passengers;
      $('max-leave-days').value = data.work.max_leave_days;
      $('horizon').value = data.trip.search_horizon_days;
      $('min-effective-hours').value = data.trip.min_effective_hours;
      $('min-nights').value = data.trip.min_nights;
      $('max-nights').value = data.trip.max_nights;
      $('work-start').value = data.work.start;
      $('work-end').value = data.work.end;
      $('interval').value = data.scanner.interval_minutes;
      $('drop-ratio').value = Number(data.alerts.meaningful_drop_ratio) * 100;
      $('nonstop').checked = data.flight.nonstop_only;
      $('jitter').checked = Number(data.scanner.jitter_ratio) > 0;
      $('holidays').value = Array.isArray(data.holidays) ? data.holidays.join('\n') : lines(data.holidays).join('\n');
      $('forced-workdays').value = Array.isArray(data.forced_workdays) ? data.forced_workdays.join('\n') : lines(data.forced_workdays).join('\n');
      $('smtp-host').value = data.smtp.host;
      $('smtp-port').value = data.smtp.port;
      $('smtp-ssl').checked = data.smtp.ssl;
      $('smtp-username').value = data.smtp.username;
      $('smtp-recipient').value = data.smtp.recipient;
      $('email-status').textContent = data.smtp.password_configured && data.smtp.username && data.smtp.recipient ? '已配置' : '未配置';
      $('email-status').style.color = data.smtp.password_configured && data.smtp.username && data.smtp.recipient ? '#15803d' : '#b45309';
      $('origins').innerHTML = data.origins.map(origin => `<div class="origin"><div class="origin-top"><label><input data-origin="${escapeHtml(origin.code)}" type="checkbox" ${origin.enabled ? 'checked' : ''}> ${escapeHtml(origin.code)}</label><span class="hint">接驳设置</span></div><div class="grid"><label>接驳总费用<input data-cost="${escapeHtml(origin.code)}" type="number" min="0" value="${origin.transfer_cost_total_cny}"></label><label>接驳分钟<input data-transfer="${escapeHtml(origin.code)}" type="number" min="0" value="${origin.transfer_minutes}"></label><label>机场缓冲<input data-buffer="${escapeHtml(origin.code)}" type="number" min="0" value="${origin.airport_buffer_minutes}"></label></div></div>`).join('');
      $('destinations').innerHTML = data.destination_options.map(code => `<div class="destination"><div class="dest-top"><label><input data-destination="${escapeHtml(code)}" type="checkbox" ${data.destinations.includes(code) ? 'checked' : ''}> ${escapeHtml(code)}</label><input data-target="${escapeHtml(code)}" type="number" min="1" value="${data.target_price[code] || ''}" placeholder="目标价"></div><span class="hint">每人门到门目标价（元）</span></div>`).join('');
    }
    function collect() {
      const origins = [...document.querySelectorAll('[data-origin]')].map(box => { const code = box.dataset.origin; return {code, enabled:box.checked, transfer_cost_total_cny:Number(document.querySelector(`[data-cost="${code}"]`).value), transfer_minutes:Number(document.querySelector(`[data-transfer="${code}"]`).value), airport_buffer_minutes:Number(document.querySelector(`[data-buffer="${code}"]`).value)}; });
      const destinations = [...document.querySelectorAll('[data-destination]:checked')].map(box => box.dataset.destination);
      const target_price = {}; [...document.querySelectorAll('[data-target]')].forEach(input => { if (input.value !== '') target_price[input.dataset.target] = Number(input.value); });
      return {profile:{timezone:state.profile.timezone, passengers:Number($('passengers').value)}, work:{start:$('work-start').value,end:$('work-end').value,max_leave_days:Number($('max-leave-days').value)}, trip:{search_horizon_days:Number($('horizon').value),min_nights:Number($('min-nights').value),max_nights:Number($('max-nights').value),min_effective_hours:Number($('min-effective-hours').value)}, flight:{currency:state.flight.currency,nonstop_only:$('nonstop').checked}, origins,destinations,target_price,airport_penalty_minutes:state.airport_penalty_minutes,scanner:{interval_minutes:Number($('interval').value),max_calendar_queries:state.scanner.max_calendar_queries,max_detail_queries:state.scanner.max_detail_queries,jitter_ratio:$('jitter').checked ? 0.1 : 0},alerts:{meaningful_drop_ratio:Number($('drop-ratio').value)/100},smtp:{host:$('smtp-host').value,port:Number($('smtp-port').value),ssl:$('smtp-ssl').checked,username:$('smtp-username').value,recipient:$('smtp-recipient').value,password_env:state.smtp.password_env},holidays:lines($('holidays').value),forced_workdays:lines($('forced-workdays').value)};
    }
    async function load() { try { render(await api('/api/config')); show('已读取当前配置'); } catch (error) { show(error.message, true); } }
    $('config-form').addEventListener('submit', async event => { event.preventDefault(); try { await api('/api/config', {method:'POST',body:JSON.stringify(collect())}); const password = $('smtp-password').value.trim(); let passwordMessage = ''; if (password) { const result = await api('/api/smtp/password', {method:'POST',body:JSON.stringify({password})}); passwordMessage = result.message || ''; $('smtp-password').value = ''; } await load(); show(passwordMessage || '配置已保存'); } catch (error) { show(error.message, true); } });
    $('reload').addEventListener('click', load);
    $('test-notify').addEventListener('click', async () => { try { $('test-notify').disabled = true; await api('/api/email/test', {method:'POST',body:'{}'}); show('测试邮件已发送，请查看邮箱 App'); } catch (error) { show(error.message, true); } finally { $('test-notify').disabled = false; } });
    $('start-scan').addEventListener('click', async () => { try { $('start-scan').disabled = true; await api('/api/scan', {method:'POST',body:'{}'}); show('扫描已在后台启动'); pollStatus(); } catch (error) { show(error.message, true); } finally { $('start-scan').disabled = false; } });
    async function pollStatus() { try { const result = await api('/api/scan/status'); $('scan-status').textContent = result.running ? '扫描进行中' : (result.returncode === null ? '尚未启动扫描' : `上次扫描结束：${result.returncode === 0 ? '成功' : '失败'}`); if (result.running) { clearTimeout(timer); timer = setTimeout(pollStatus, 3000); } } catch (_) {} }
    load(); pollStatus();
  </script>
</body>
</html>"""


class _RadarServer(ThreadingHTTPServer):
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], config_path: Path):
        super().__init__(address, _RequestHandler)
        self.config_path = config_path
        self.project_root = config_path.parent.parent
        self._scan_lock = threading.Lock()
        self._scan_process: subprocess.Popen[Any] | None = None
        self._scan_started_at: str | None = None

    def scan_status(self) -> dict[str, Any]:
        with self._scan_lock:
            process = self._scan_process
            return {
                "running": bool(process and process.poll() is None),
                "pid": process.pid if process else None,
                "started_at": self._scan_started_at,
                "returncode": process.poll() if process else None,
            }

    def start_scan(self) -> dict[str, Any]:
        with self._scan_lock:
            if self._scan_process and self._scan_process.poll() is None:
                raise RuntimeError("扫描已经在运行")
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            self._scan_process = subprocess.Popen(
                [sys.executable, "-m", "flight_radar.cli", "--config", str(self.config_path), "scan"],
                cwd=self.project_root,
                env=os.environ.copy(),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creation_flags,
            )
            self._scan_started_at = __import__("datetime").datetime.now().isoformat(timespec="seconds")
            return self.scan_status()


class _RequestHandler(BaseHTTPRequestHandler):
    server: _RadarServer

    def log_message(self, format: str, *args: Any) -> None:
        logger.debug("config-ui %s", format % args)

    def _write(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        self._write(status, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def _body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("请求体大小不正确") from exc
        if length <= 0 or length > MAX_BODY_BYTES:
            raise ValueError("请求体大小不正确")
        raw = self.rfile.read(length)
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("请求内容必须是 JSON 对象")
        return payload

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/":
                self._write(200, "text/html; charset=utf-8", UI_HTML.encode("utf-8"))
            elif path == "/api/config":
                self._json(200, config_payload(self.server.config_path))
            elif path == "/api/scan/status":
                self._json(200, self.server.scan_status())
            else:
                self._json(404, {"message": "页面不存在"})
        except Exception as exc:
            logger.exception("config UI GET failed")
            self._json(500, {"message": str(exc)})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self._body()
            if path == "/api/config":
                save_config(self.server.config_path, payload)
                self._json(200, {"message": "配置已保存"})
            elif path == "/api/smtp/password":
                config = load_config(self.server.config_path)
                message = persist_user_secret(
                    config.smtp_password_env, str(payload.get("password", ""))
                )
                self._json(200, {"message": message})
            elif path == "/api/email/test":
                config = load_config(self.server.config_path)
                notifier = EmailNotifier(
                    config.smtp_host,
                    config.smtp_port,
                    config.smtp_ssl,
                    config.smtp_username,
                    config.smtp_recipient,
                    config.smtp_password_env,
                )
                if not notifier.configured:
                    raise ValueError("请先填写 SMTP 服务器、发件/收件邮箱和授权码")
                notifier.send("✈️ 机票雷达测试", "配置页测试邮件已发送。")
                self._json(200, {"message": "测试邮件已发送"})
            elif path == "/api/scan":
                self._json(202, self.server.start_scan())
            else:
                self._json(404, {"message": "接口不存在"})
        except ValueError as exc:
            self._json(400, {"message": str(exc)})
        except RuntimeError as exc:
            self._json(409, {"message": str(exc)})
        except Exception as exc:
            logger.exception("config UI POST failed")
            self._json(500, {"message": str(exc)})


def run_ui(config_path: Path, host: str = "127.0.0.1", port: int = 8765) -> int:
    config_path = config_path.resolve()
    load_config(config_path)
    server = _RadarServer((host, port), config_path)
    print(f"配置页面：http://{host}:{port}")
    print("按 Ctrl+C 停止配置页面")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("配置页面已停止")
    finally:
        process = server._scan_process
        if process and process.poll() is None:
            process.terminate()
        server.server_close()
    return 0
