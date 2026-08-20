from __future__ import annotations

import argparse
import logging
import random
import sys
import time as time_module
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from .config import example_config, load_config
from .fli_adapter import FliAdapter
from .notifier import PushPlusNotifier
from .scanner import Scanner
from .storage import Storage

logger = logging.getLogger("flight_radar")


def _config_path() -> Path:
    return Path.cwd() / "config" / "radar.toml"


def _setup_logging(log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if logger.handlers:
        return
    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(console)
    logger.addHandler(file_handler)


def _run_scan(config_path: Path) -> int:
    config = load_config(config_path)
    _setup_logging(config.log_path)
    with Storage(config.database_path) as storage:
        adapter = FliAdapter(config)
        notifier = PushPlusNotifier(config.pushplus_endpoint, config.pushplus_channel, config.pushplus_token_env)
        try:
            summary = Scanner(config, adapter, storage, notifier).run()
            logger.info(
                "scan complete calendar=%s detail=%s saved=%s alerts=%s errors=%s",
                summary.calendar_queries, summary.detail_queries, summary.quotes_saved,
                summary.alerts_sent, summary.errors,
            )
        finally:
            adapter.close()
    return 0


def _init() -> int:
    root = Path.cwd()
    config_path = root / "config" / "radar.toml"
    if not config_path.exists():
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(example_config(), encoding="utf-8")
        print(f"created {config_path}")
    for directory in (root / "data" / "backups", root / "logs"):
        directory.mkdir(parents=True, exist_ok=True)
    return 0


def _deals(config_path: Path) -> int:
    config = load_config(config_path)
    with Storage(config.database_path) as storage:
        rows = storage.recent_deals()
        if not rows:
            print("暂无已保存的好价")
            return 0
        for row in rows:
            print(
                f"{row['deal_level']} {row['origin']} -> {row['destination']} "
                f"{row['departure_date']} ~ {row['return_date']} "
                f"¥{Decimal(row['effective_price_per_person']):,.2f}/人 "
                f"{row['booking_url']}"
            )
    return 0


def _doctor(config_path: Path, live: bool) -> int:
    config = load_config(config_path)
    _setup_logging(config.log_path)
    print(f"config: {config.path}")
    print(f"database: {config.database_path}")
    with Storage(config.database_path) as storage:
        print(f"sqlite: {storage.integrity_check()}")
    notifier = PushPlusNotifier(config.pushplus_endpoint, config.pushplus_channel, config.pushplus_token_env)
    print(f"pushplus: {'configured' if notifier.configured else 'not configured'}")
    try:
        import fli

        print(f"fli: {getattr(fli, '__version__', 'installed')}")
    except Exception as exc:
        print(f"fli: ERROR {exc}")
        return 1
    if live:
        print("live: run flight-radar scan to perform the configured scan")
    return 0


def _watch(config_path: Path) -> int:
    config = load_config(config_path)
    _setup_logging(config.log_path)
    last_backup_date: str | None = None
    while True:
        try:
            _run_scan(config_path)
            today = datetime.now(timezone.utc).date().isoformat()
            if today != last_backup_date:
                with Storage(config.database_path) as storage:
                    backup = config.backup_dir / f"radar-{today}.sqlite3"
                    storage.backup(backup)
                last_backup_date = today
                backups = sorted(config.backup_dir.glob("radar-*.sqlite3"))
                for old in backups[:-14]:
                    old.unlink(missing_ok=True)
            delay = config.scan_interval_minutes * 60
            delay *= 1 + random.uniform(-config.jitter_ratio, config.jitter_ratio)
            logger.info("next scan in %.0f seconds", delay)
            time_module.sleep(max(30, delay))
        except KeyboardInterrupt:
            logger.info("watch stopped")
            return 0
        except Exception:
            logger.exception("watch iteration failed")
            time_module.sleep(60)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="flight-radar")
    parser.add_argument("--config", type=Path, default=None, help="配置文件路径")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("scan")
    sub.add_parser("watch")
    sub.add_parser("deals")
    doctor = sub.add_parser("doctor")
    doctor.add_argument("--live", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config_path = (args.config or _config_path()).resolve()
    if args.command == "init":
        return _init()
    if not config_path.exists():
        print(f"配置不存在：{config_path}，请先运行 flight-radar init", file=sys.stderr)
        return 2
    if args.command == "scan":
        return _run_scan(config_path)
    if args.command == "watch":
        return _watch(config_path)
    if args.command == "deals":
        return _deals(config_path)
    if args.command == "doctor":
        return _doctor(config_path, args.live)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
