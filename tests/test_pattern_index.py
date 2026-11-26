import copy
import datetime
import json
import math
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import app as flask_app  # noqa: E402
import updater  # noqa: E402


def _reject_nan_constant(val):
    raise ValueError(f"Invalid JSON constant: {val}")


def _make_history(n_lookback=140, n_live=3, seed_last=False):
    base_date = datetime.date(2026, 1, 1)
    lb = []
    for k in range(n_lookback):
        dt = str(base_date + datetime.timedelta(days=k))
        lb.append({
            "date": dt,
            "pe": 25.0 + (k % 10) * 0.5,
            "pe_pct": 50.0,
            "index_price": 20000.0 + k * 10,
            "price_ma": 20000.0,
            "iicp_price": 20.0 + k * 0.01,
            "gold_price": 100.0 + k * 0.1,
            "debt_price": 1400.0 + k * 0.1,
            "gold_ma": 100.0,
            "triggers": 0,
        })
    lr = []
    for idx, row in enumerate(lb[-n_live:]):
        r = dict(row)
        is_seed = seed_last and idx == n_live - 1
        r.update({
            "asset": "EQUITY",
            "t_pe_floor": False,
            "t_pe_ceiling": False,
            "t_dd": False,
            "t_ma": False,
            "signal": "STAY EQUITY",
            "settlement_state": "NORMAL",
            "pending_target": None,
            "portfolio_value": 100000.0 if is_seed else 101234.56 + idx * 100,
            "benchmark_value": 100000.0 if is_seed else 101500.00 + idx * 100,
            "benchmark_dd": 0.0,
            "portfolio_dd": 0.0,
            "is_live": True,
        })
        lr.append(r)
    return {"lookback_data": lb, "live_rows": lr}


PARAMS = {
    "index_label": "MIDCAP 150",
    "pe_lookback": 126,
    "pe_floor": 0.15,
    "pe_ceiling": 0.8,
    "dd_threshold": 0.2,
    "ma_lookback": 20,
    "gold_ma_lookback": 50,
    "initial_capital": 100000.0,
}


class UpdaterTests(unittest.TestCase):
    def test_price_validation_and_indicators_ignore_nan(self):
        for bad in (None, float("nan"), float("inf"), float("-inf"), 0, -5, True, "bad"):
            self.assertFalse(updater.is_valid_price(bad))
        self.assertTrue(updater.is_valid_price(100.5))

        arr = np.array([10.0, 20.0, float("nan"), 30.0, 40.0])
        self.assertIsNone(updater.sma(arr, 4, 3))
        self.assertAlmostEqual(updater.sma(np.array([10.0, 20.0, 30.0]), 2, 3), 20.0)
        self.assertAlmostEqual(updater.roll_dd(arr, 4, 5), 0.0)

    def test_rejects_nan_market_input(self):
        raw = _make_history()
        with self.assertRaises(ValueError):
            updater.process_update(
                raw,
                PARAMS,
                {
                    "date": "2026-06-01",
                    "iicp_price": 22.0,
                    "gold_price": float("nan"),
                    "debt_price": 1420.0,
                    "index_price": 22000.0,
                    "pe": 28.0,
                },
            )

    def test_skips_duplicate_and_stale_holiday(self):
        raw = _make_history()
        last = raw["live_rows"][-1]

        res, info = updater.process_update(
            raw,
            PARAMS,
            {
                "date": last["date"],
                "iicp_price": last["iicp_price"],
                "gold_price": last["gold_price"],
                "debt_price": last["debt_price"],
                "index_price": last["index_price"],
                "pe": last["pe"],
            },
        )
        self.assertIsNone(res)
        self.assertTrue(info["skipped"])

        # Same rounded ETF prices on a holiday date
        res2, info2 = updater.process_update(
            raw,
            PARAMS,
            {
                "date": "2026-06-01",
                "iicp_price": last["iicp_price"] + 1e-7,
                "gold_price": last["gold_price"] + 1e-7,
                "debt_price": last["debt_price"] + 1e-7,
                "index_price": last["index_price"],
                "pe": last["pe"],
            },
        )
        self.assertIsNone(res2)
        self.assertTrue(info2["skipped"])

    def test_overwrites_seed_row(self):
        raw = _make_history(seed_last=True)
        seed_date = raw["live_rows"][-1]["date"]
        res, info = updater.process_update(
            raw,
            PARAMS,
            {
                "date": seed_date,
                "iicp_price": 25.0,
                "gold_price": 120.0,
                "debt_price": 1430.0,
                "index_price": 23000.0,
                "pe": 28.0,
            },
        )
        self.assertIsNotNone(res)
        self.assertFalse(info["skipped"])
        self.assertEqual(res["live_rows"][-1]["date"], seed_date)
        self.assertEqual(res["live_rows"][-1]["gold_price"], 120.0)

    def test_t2_settlement_transitions_and_tc(self):
        raw = _make_history()
        # Drop index price below MA20 and spike PE above 80th percentile -> 2 triggers -> EXIT EQUITY -> GOLD
        d1 = "2026-06-01"
        raw, s1 = updater.process_update(
            raw,
            PARAMS,
            {
                "date": d1,
                "iicp_price": 21.0,
                "gold_price": 150.0,  # > gold_ma
                "debt_price": 1420.0,
                "index_price": 15000.0,  # < MA20 AND dd > 20%
                "pe": 40.0,  # > ceiling
            },
        )
        self.assertEqual(s1["new_settlement"], "SIGNAL_DAY")
        self.assertEqual(s1["new_asset"], "EQUITY")
        self.assertEqual(s1["signal"], "EXIT EQUITY → GOLD")

        d2 = "2026-06-02"
        raw, s2 = updater.process_update(
            raw,
            PARAMS,
            {
                "date": d2,
                "iicp_price": 21.1,
                "gold_price": 150.5,
                "debt_price": 1420.5,
                "index_price": 15050.0,
                "pe": 40.0,
            },
        )
        self.assertEqual(s2["new_settlement"], "PENDING_BUY")
        self.assertEqual(s2["new_asset"], "CASH")

        d3 = "2026-06-03"
        raw, s3 = updater.process_update(
            raw,
            PARAMS,
            {
                "date": d3,
                "iicp_price": 21.2,
                "gold_price": 155.0,
                "debt_price": 1421.0,
                "index_price": 15100.0,
                "pe": 40.0,
            },
        )
        self.assertEqual(s3["new_settlement"], "NORMAL")
        self.assertEqual(s3["new_asset"], "GOLD")
        self.assertEqual(s3["signal"], "BOUGHT GOLD")
        # Day 2 sold EQUITY (+0.1/21.0 MTM) with 0.1% TC; day 3 bought GOLD with 0.1% TC
        pv_d1 = raw["live_rows"][-3]["portfolio_value"]
        pv_d2_expected = round((pv_d1 / 21.0 * 21.1) * 0.999, 2)
        pv_d3_expected = round(pv_d2_expected * 0.999, 2)
        self.assertAlmostEqual(raw["live_rows"][-2]["portfolio_value"], pv_d2_expected, places=2)
        self.assertAlmostEqual(raw["live_rows"][-1]["portfolio_value"], pv_d3_expected, places=2)

    def test_dedupe_history_rows_removes_overlap(self):
        raw = _make_history(n_lookback=10, n_live=4)
        deduped = updater.dedupe_history_rows(raw["lookback_data"], raw["live_rows"])
        self.assertEqual(len(deduped), 10)
        self.assertEqual([r["date"] for r in deduped], sorted(r["date"] for r in deduped))

    def test_yahoo_chart_uses_meta_when_today_close_is_none(self):
        fake_payload = {
            "chart": {
                "result": [{
                    "meta": {
                        "regularMarketPrice": 100.96,
                        "regularMarketTime": int(
                            datetime.datetime(2026, 11, 26, 15, 30, tzinfo=updater.IST).timestamp()
                        ),
                    },
                    "timestamp": [
                        int(datetime.datetime(2026, 11, 25, 9, 15, tzinfo=updater.IST).timestamp()),
                        int(datetime.datetime(2026, 11, 26, 9, 15, tzinfo=updater.IST).timestamp()),
                    ],
                    "indicators": {"quote": [{"close": [100.11, None]}]},
                }]
            }
        }

        class FakeResp:
            def raise_for_status(self): pass
            def json(self): return fake_payload

        with patch.object(updater.requests, "get", return_value=FakeResp()):
            price, dt = updater._fetch_yahoo_chart_price("GOLDBEES.NS")
            self.assertAlmostEqual(price, 100.96)
            self.assertEqual(dt, "2026-11-26")
            self.assertEqual(updater._fetch_yahoo_chart_price("GOLDBEES.NS", target_date="2026-11-25")[0], 100.11)
            self.assertEqual(updater._fetch_yahoo_chart_price("GOLDBEES.NS", target_date="2026-11-24"), (None, None))


class DataAndAppTests(unittest.TestCase):
    def test_history_json_strictly_valid(self):
        text = (REPO_ROOT / "data" / "history.json").read_text()
        data = json.loads(text, parse_constant=_reject_nan_constant)
        lb = data["lookback_data"]
        lr = data["live_rows"]
        self.assertGreater(len(lb), 1500)
        self.assertGreater(len(lr), 170)

        for name, rows in [("lookback_data", lb), ("live_rows", lr)]:
            dates = [r["date"] for r in rows]
            self.assertEqual(dates, sorted(dates), f"{name} dates not sorted")
            self.assertEqual(len(dates), len(set(dates)), f"{name} has duplicate dates")
            for r in rows:
                for k in ("pe", "index_price", "iicp_price", "gold_price", "debt_price"):
                    if k in r:
                        self.assertTrue(updater.is_valid_price(r[k]), f"{name} {r['date']} bad {k}={r[k]}")

        for r in lr:
            self.assertTrue(updater.is_valid_price(r["portfolio_value"]), f"Bad pv on {r['date']}")
            self.assertTrue(updater.is_valid_price(r["benchmark_value"]), f"Bad bv on {r['date']}")
            self.assertTrue(math.isfinite(r["portfolio_dd"]), f"Bad pdd on {r['date']}")
            self.assertTrue(math.isfinite(r["benchmark_dd"]), f"Bad bdd on {r['date']}")

    def test_flask_endpoints(self):
        client = flask_app.app.test_client()
        for path in ("/", "/charts", "/charts.html"):
            with client.get(path) as resp:
                self.assertEqual(resp.status_code, 200, path)

        for path in ("/api/data", "/api/latest", "/data/history.json", "/params.json"):
            resp = client.get(path)
            self.assertEqual(resp.status_code, 200, path)
            payload = json.loads(resp.get_data(as_text=True), parse_constant=_reject_nan_constant)
            self.assertIsNotNone(payload)

        api_data = json.loads(client.get("/api/data").get_data(as_text=True))
        self.assertIn("lookback_data", api_data["history"])
        self.assertIn("live_rows", api_data["history"])
        self.assertGreater(len(api_data["history"]["lookback_data"]), 1500)

        # Even if load_data returns NaN, server serializes null instead of invalid JSON NaN
        poisoned = copy.deepcopy({"lookback_data": [], "live_rows": [{"portfolio_value": float("nan")}]})
        with patch.object(flask_app, "load_data", return_value=poisoned):
            resp = client.get("/api/data")
            parsed = json.loads(resp.get_data(as_text=True), parse_constant=_reject_nan_constant)
            self.assertIsNone(parsed["history"]["live_rows"][0]["portfolio_value"])


if __name__ == "__main__":
    unittest.main()
