import pytest

from mcp_stats.stats_api import StatsAPI


def _window(team, period, to_min, line, press, formation="4-4-2"):
    to_ms = int(to_min * 60_000)
    return {"kind": "window", "window_id": f"w-{team}-{period}-{to_min}", "team_id": team,
            "period": period, "from_ms": to_ms - 300_000, "to_ms": to_ms,
            "values": {"line_height_m": line, "pressing_per_min": press, "press_size": 1.0,
                       "formation_out": formation, "formation_in": "2-4-4", "style_dial": 50.0,
                       "control_share": 0.5, "chaos": 60.0, "length_m": 40.0, "width_m": 45.0},
            "network": {"edges": [{"from": "NGU-04", "to": "NGU-08", "passes": 6, "danger": 0.1}]},
            "routes": {"chances": 2, "lanes": {"left": 0.5, "centre": 0.5, "right": 0.0},
                       "players": {"NGU-09": 2}}}


@pytest.fixture
def api(data):
    data.windows = ([_window("NGU", 1, m, 40.0, 3.0) for m in (6, 10, 14)]
                    + [_window("NGU", 2, m, 34.0, 3.0, "3-5-2") for m in (60, 65, 70)]
                    + [_window("NGU", 2, m, 26.0, 2.0, "4-4-1") for m in (72, 74, 78, 85)])
    return StatsAPI(data)


AS_OF_74 = (2, 74 * 60_000)


def test_cut_off_never_returns_data_after_as_of(api):
    """LLD §14: tools called with as_of = 74:00 return nothing after it."""
    r = api.line_height("NGU", 60, 90, AS_OF_74)
    assert r["windows"] == 4 and "w-NGU-2-85" not in r["window_ids"]  # 65, 70, 72, 74
    assert api.line_height("NGU", 75, 90, AS_OF_74)["windows"] == 0
    goals = api.recent_events("RIV", 5, (1, 1_000_000))["events"]
    assert goals == []  # the 23' goal hasn't happened at 16:40


def test_compare_periods_reports_the_difference(api):
    r = api.compare_periods("Northgate United", 60, 70, 70, 74, AS_OF_74)
    m = r["measures"]
    assert m["line_height_m"] == {"a": 34.0, "b": 26.0, "difference": -8.0}
    assert m["formation_out"] == {"a": "3-5-2", "b": "4-4-1"}
    assert r["window_ids"]


def test_normal_style_is_minutes_5_to_15(api):
    assert api.normal_style("NGU", AS_OF_74)["line_height_m"] == 40.0


def test_match_state(api):
    s = api.match_state(AS_OF_74)
    assert s["score"] == {"RIV": 1, "NGU": 0}
    assert s["cards"] == {"NGU_red": 1}
    assert s["conditions"]["weather"] == "heavy_rain"


def test_unknown_team_is_an_error(api):
    with pytest.raises(ValueError):
        api.line_height("XYZ", 0, 90, AS_OF_74)


def test_names_not_ids_in_network_and_routes(api):
    assert api.passing_network("NGU", 60, 74, AS_OF_74)["top_links"][0]["from"] == "Bo Ngu4"
    assert api.chance_routes("NGU", 60, 74, AS_OF_74)["players"][0]["player"] == "Bo Ngu9"
