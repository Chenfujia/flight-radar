import tomllib

import pytest

from flight_radar.config import load_config
from flight_radar.web import save_config, serialize_payload, validate_payload


def _payload() -> dict:
    return {
        "profile": {"timezone": "Asia/Shanghai", "passengers": 2},
        "work": {"start": "09:00", "end": "18:00", "max_leave_days": 2},
        "trip": {
            "search_horizon_days": 45,
            "min_nights": 2,
            "max_nights": 4,
            "min_effective_hours": 48,
        },
        "flight": {"currency": "CNY", "nonstop_only": True},
        "origins": [
            {
                "code": "HGH",
                "enabled": True,
                "transfer_cost_total_cny": 0,
                "transfer_minutes": 60,
                "airport_buffer_minutes": 120,
            },
            {
                "code": "PVG",
                "enabled": False,
                "transfer_cost_total_cny": 260,
                "transfer_minutes": 210,
                "airport_buffer_minutes": 150,
            },
        ],
        "destinations": ["KIX", "ICN"],
        "target_price": {"KIX": 1650, "ICN": 1650},
        "airport_penalty_minutes": {"KIX": 70, "ICN": 70, "default": 90},
        "scanner": {
            "interval_minutes": 120,
            "max_calendar_queries": 72,
            "max_detail_queries": 30,
            "jitter_ratio": 0.1,
        },
        "alerts": {"meaningful_drop_ratio": 0.05},
        "holidays": ["2026-10-01"],
        "forced_workdays": ["2026-10-10"],
    }


def test_config_page_payload_round_trips_as_toml():
    parsed = tomllib.loads(serialize_payload(_payload()))
    assert parsed["destinations"]["enabled"] == ["KIX", "ICN"]
    assert parsed["origins"]["PVG"]["enabled"] is False
    assert parsed["target_price"]["KIX"] == 1650
    assert parsed["calendar"]["holidays"] == ["2026-10-01"]


def test_save_config_writes_a_loadable_config(tmp_path):
    path = tmp_path / "config" / "radar.toml"
    save_config(path, _payload())
    config = load_config(path)
    assert config.destinations == ("KIX", "ICN")
    assert config.origin_for("HGH").enabled is True
    with pytest.raises(KeyError):
        config.origin_for("PVG")


def test_config_page_rejects_when_every_origin_is_disabled():
    payload = _payload()
    for origin in payload["origins"]:
        origin["enabled"] = False
    with pytest.raises(ValueError, match="至少启用一个出发机场"):
        validate_payload(payload)

