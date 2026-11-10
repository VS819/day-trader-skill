"""--market in: NSE India (IST, rupees, .NS symbols) across the day-trade flow.

The bars here are synthetic, built in the test (no Yahoo call), so the numbers are exact and
anyone can rerun them. The US tests elsewhere prove the default did not move."""

import datetime
import io
import json
import os
import random
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from _load import load

DAY = "2026-11-12"          # a Thursday; NSE is open
HOLIDAY = "2026-11-10"      # Diwali Balipratipada: NSE closed


def utc_ts(day, hh, mm):
    """IST wall clock -> epoch seconds (IST is UTC+5:30 all year)."""
    d = datetime.date.fromisoformat(day)
    utc = datetime.datetime(d.year, d.month, d.day, hh, mm) - datetime.timedelta(hours=5, minutes=30)
    return int((utc - datetime.datetime(1970, 1, 1)).total_seconds())


def one_session(sym="RELIANCE.NS", closes=(1440.0, 1446.0, 1438.0, 1447.0, 1451.2, 1455.0, 1453.0)):
    """5-minute bars from 9:15 IST. The 15-minute range (9:15, 9:20, 9:25) is 1436.20 to 1448.00."""
    t0 = utc_ts(DAY, 9, 15)
    ts, o, h, l, c, v = [], [], [], [], [], []
    prev = closes[0] - 2
    for i, x in enumerate(closes):
        ts.append(t0 + 300 * i)
        o.append(prev)
        c.append(x)
        h.append(max(prev, x) + 1.0)
        l.append(min(prev, x) - 1.0)
        v.append(100000)
        prev = x
    h[:3], l[:3] = [1448.0, 1447.0, 1446.5], [1436.2, 1437.0, 1436.5]
    return {"chart": {"result": [{
        "meta": {"symbol": sym, "currency": "INR", "dataGranularity": "5m", "regularMarketTime": ts[-1] + 300,
                 "regularMarketPrice": closes[-1], "previousClose": 1430.0},
        "timestamp": ts, "indicators": {"quote": [{"open": o, "high": h, "low": l, "close": c, "volume": v}]}}],
        "error": None}}


def sixty_days(sym="RELIANCE.NS", sessions=30, today_bars=5, seed=7):
    """A seeded random walk: `sessions` full NSE sessions (75 five-minute bars) before DAY, plus
    today's first bars."""
    rng = random.Random(seed)
    closed = {"2026-10-02", "2026-10-20", HOLIDAY}
    days, d = [], datetime.date.fromisoformat(DAY)
    while len(days) < sessions + 1:
        if d.weekday() < 5 and d.isoformat() not in closed:
            days.append(d.isoformat())
        d -= datetime.timedelta(days=1)
    days.reverse()
    ts, o, h, l, c, v, p = [], [], [], [], [], [], 1400.0
    for day in days:
        t0 = utc_ts(day, 9, 15)
        for i in range(today_bars if day == DAY else 75):
            op, p = p, max(1.0, p * (1 + rng.gauss(0, 0.0025)))
            ts.append(t0 + 300 * i)
            o.append(round(op, 2))
            c.append(round(p, 2))
            h.append(round(max(op, p) * 1.001, 2))
            l.append(round(min(op, p) * 0.999, 2))
            v.append(100000)
    return {"chart": {"result": [{
        "meta": {"symbol": sym, "currency": "INR", "dataGranularity": "5m", "regularMarketTime": ts[-1] + 300},
        "timestamp": ts, "indicators": {"quote": [{"open": o, "high": h, "low": l, "close": c, "volume": v}]}}],
        "error": None}}, c[-1]


def run(mod, argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = mod.main(argv)
    return code, out.getvalue(), err.getvalue()


class InTmp(unittest.TestCase):
    def setUp(self):
        self.old = os.getcwd()
        self.dir = tempfile.mkdtemp()
        os.chdir(self.dir)
        os.makedirs("trader")
        self.env = os.environ.pop("TRADER_MARKET", None)

    def tearDown(self):
        os.chdir(self.old)
        shutil.rmtree(self.dir)
        if self.env is not None:
            os.environ["TRADER_MARKET"] = self.env

    def write(self, path, doc):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)


class ChoosingTheMarket(InTmp):
    def test_us_is_the_default(self):
        m = load("trader-exit", "exit")
        self.assertEqual(m.choose_market(["plan"]), ["plan"])
        self.assertEqual(m.MARKET["code"], "us")
        self.assertEqual(m.OPEN, datetime.time(9, 30))

    def test_flag_anywhere_env_or_config(self):
        m = load("trader-exit", "exit")
        self.assertEqual(m.choose_market(["plan", "--market", "in", "--write"]), ["plan", "--write"])
        self.assertEqual(m.MARKET["code"], "in")
        self.assertEqual((m.OPEN, m.CLOSE, m.EARLY), (datetime.time(9, 15), datetime.time(15, 30), None))
        m = load("trader-exit", "exit")
        os.environ["TRADER_MARKET"] = "NSE"
        try:
            m.choose_market([])
        finally:
            del os.environ["TRADER_MARKET"]
        self.assertEqual(m.MARKET["code"], "in")
        m = load("trader-exit", "exit")
        self.write("trader/config.json", {"market": "in"})
        m.choose_market([])
        self.assertEqual(m.MARKET["code"], "in")

    def test_an_unknown_market_is_refused(self):
        code, _, err = run(load("trader-exit", "exit"), ["--market", "lse", "show"])
        self.assertEqual(code, 1)
        self.assertIn("--market is us or in", err)

    def test_symbols(self):
        m = load("trader-entry", "entry")
        m.set_market("in")
        self.assertEqual(m.market_symbol("reliance"), "RELIANCE.NS")
        self.assertEqual(m.market_symbol("TCS.BO"), "TCS.BO")
        self.assertEqual(m.url_symbol("m&m"), "M%26M.NS")
        m.set_market("us")
        self.assertEqual(m.yahoo_symbol("BRK.B"), "BRK-B")


class TheClock(InTmp):
    def test_ist_has_no_daylight_saving(self):
        a = load("trader-alerts", "alerts")
        a.set_market("in")
        for utc in (datetime.datetime(2026, 1, 5, 4, 0), datetime.datetime(2026, 7, 6, 4, 0)):
            self.assertEqual(a.to_eastern(utc), utc + datetime.timedelta(hours=5, minutes=30))
        local = datetime.datetime(2026, 11, 12, 9, 15)
        self.assertEqual(a.eastern_to_utc(local), datetime.datetime(2026, 11, 12, 3, 45))

    def test_nse_holiday_and_session(self):
        a = load("trader-alerts", "alerts")
        code, out, _ = run(a, ["--market", "in", "clock", "--now", HOLIDAY + " 10:00"])
        self.assertIn("NSE closed, NSE holiday: Diwali Balipratipada", out)
        self.assertIn("Next open: 2026-11-11 09:15 Mumbai", out)
        code, out, _ = run(load("trader-alerts", "alerts"), ["--market", "in", "clock", "--now", DAY + " 10:00"])
        self.assertIn("NSE OPEN", out)
        self.assertIn("09:15 to 15:30", out)

    def test_the_2026_list_is_the_circular(self):
        a = load("trader-alerts", "alerts")
        self.assertEqual(len(a.NSE_HOLIDAYS), 16)   # 15 in NSE/FAOP/71777, plus the Jan 15 election day
        self.assertTrue(all(datetime.date.fromisoformat(d).weekday() < 5 for d in a.NSE_HOLIDAYS))
        a.set_market("in")
        self.assertIn("no NSE holiday list for 2027", a.holiday_note(datetime.date(2027, 1, 4)))


class TheFlow(InTmp):
    """scanner -> entry -> exit -> budget -> risk -> broker, on one synthetic NSE morning."""

    def setUp(self):
        super().setUp()
        os.makedirs("bars")
        self.write("bars/RELIANCE.NS.json", one_session())
        self.write("trader/config.json", {"market": "in", "budget": 50000, "max_loss_per_trade_usd": 300,
                                          "max_order_usd": 40000, "max_daily_loss_usd": 900, "paper": True})

    def test_entry_triggers_on_the_first_close_above_the_range(self):
        code, out, _ = run(load("trader-entry", "entry"),
                           ["check", "reliance", "--offline", "bars", "--now", DAY + " 09:51", "--write"])
        self.assertIn("Opening range 9:15-9:30: high Rs 1448.00, low Rs 1436.20", out)
        self.assertIn("TRIGGERED 9:40 AM at Rs 1451.20", out)
        self.assertNotIn("$", out)
        with open("trader/entry.json") as fh:
            e = json.load(fh)
        self.assertEqual((e["symbol"], e["status"], e["price"]), ("RELIANCE.NS", "triggered", 1451.2))

    def test_not_open_yet_says_9_15(self):
        _, out, _ = run(load("trader-entry", "entry"), ["check", "RELIANCE", "--offline", "bars",
                                                        "--now", DAY + " 09:05"])
        self.assertIn("the NSE opens at 9:15", out)

    def plan(self):
        run(load("trader-entry", "entry"), ["check", "RELIANCE", "--offline", "bars", "--now", DAY + " 09:41",
                                            "--write"])
        return run(load("trader-exit", "exit"), ["plan", "--write", "--now", DAY + " 09:41"])

    def test_exit_plan_in_rupees_flat_by_15_10(self):
        code, out, _ = self.plan()
        self.assertEqual(code, 0, out)
        self.assertIn("Stop          Rs 1,442.10  opening-range midpoint", out)
        self.assertIn("Target        Rs 1,469.40  2R", out)
        self.assertIn("Flat by       15:10 IST", out)
        with open("trader/plan.json") as fh:
            p = json.load(fh)
        self.assertEqual((p["market"], p["symbol"], p["flat_by"]), ("in", "RELIANCE.NS", "15:10"))

    def test_budget_risk_broker(self):
        self.plan()
        code, out, _ = run(load("trader-budget", "size"), ["--write", "--now", DAY + " 09:41"])
        self.assertEqual(code, 0, out)
        self.assertIn("25 shares of RELIANCE.NS = Rs 36,280", out)
        self.assertIn("intraday (MIS) order on NSE", out)
        with open("trader/orders.json") as fh:
            o = json.load(fh)["orders"][0]
        self.assertEqual((o["exchange"], o["product"], o["qty"], o["plan"]["market"]), ("NSE", "MIS", "25", "in"))

        code, out, _ = run(load("trader-risk", "check"), ["--now", DAY + " 09:41"])
        self.assertEqual(code, 0, out)
        self.assertIn("PASS  #1 buy RELIANCE.NS 25 shares", out)
        self.assertIn("at 2026-11-12 09:41 Mumbai", out)

        code, out, _ = run(load("trader-risk", "check"), ["--now", DAY + " 09:20", "--no-write"])
        self.assertEqual(code, 1)
        self.assertIn("no new entries before 09:30 Mumbai", out)
        code, out, _ = run(load("trader-risk", "check"), ["--now", HOLIDAY + " 10:00", "--no-write"])
        self.assertIn("the market is closed today", out)

        code, out, _ = run(load("trader-broker", "ticket"), ["show", "--now", DAY + " 09:42"])
        self.assertIn("you place it yourself", out)
        self.assertIn("No Indian broker connector in this pack yet, so Claude will not place this", out)
        self.assertNotIn("place_stock_order", out)

    def test_a_plan_for_one_market_is_refused_by_the_other(self):
        self.plan()
        code, _, err = run(load("trader-budget", "size"), ["--market", "us", "--now", DAY + " 09:41"])
        self.assertEqual(code, 1)
        self.assertIn("the plan is for the in market (NSE) but this run is for NYSE", err)

    def test_risk_wants_an_indian_symbol(self):
        c = load("trader-risk", "check")
        c.set_market("in")
        order = {"symbol": "TSLA", "side": "buy", "qty": "1", "type": "market", "time_in_force": "day",
                 "order_class": "bracket", "take_profit_limit_price": "110", "stop_loss_stop_price": "95",
                 "plan": {"entry": 100, "stop": 95, "target": 110}}
        res = c.check([order], {"budget": 50000, "max_loss_per_trade_usd": 300, "max_order_usd": 40000},
                      now=datetime.datetime(2026, 11, 12, 5, 0), prices={})
        self.assertIn("does not look like an NSE or BSE stock", " ".join(res["results"][0]["reasons"]))


class TheScanner(InTmp):
    def test_nse_universe_keeps_the_eq_series(self):
        os.makedirs("nse")
        with open("nse/EQUITY_L.csv", "w") as fh:
            fh.write("SYMBOL,NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, "
                     "FACE VALUE\n"
                     "RELIANCE,Reliance Industries Limited,EQ,29-NOV-1995,10,1,INE002A01018,10\n"
                     "M&M,Mahindra & Mahindra Limited,EQ,01-JAN-1990,5,1,INE101A01026,5\n"
                     "TFTCO,A Trade For Trade Limited,BE,01-JAN-2010,10,1,INE000X01010,10\n")
        code, out, _ = run(load("trader-scanner", "scan"), ["--market", "in", "universe", "--offline", "nse"])
        self.assertEqual(code, 0, out)
        self.assertIn("Kept 2 NSE stocks", out)
        with open("trader/universe-nse.txt") as fh:
            self.assertEqual(fh.read().split("\n")[:2], ["M&M.NS|Mahindra & Mahindra Limited",
                                                         "RELIANCE.NS|Reliance Industries Limited"])

    def test_orb_scan(self):
        os.makedirs("wall")
        self.write("wall/RELIANCE.NS.json", one_session())
        self.write("wall/TCS.NS.json", one_session("TCS.NS", (1440, 1444, 1441, 1443, 1442, 1440, 1441)))
        code, out, _ = run(load("trader-scanner", "scan"), ["--market", "in", "orb", "--offline", "wall",
                                                            "--now", DAY + " 09:51", "--min-price", "0",
                                                            "--min-volume", "0"])
        self.assertIn("15-minute range (9:15 to 9:30 AM)", out)
        self.assertIn("9:40 AM  RELIANCE.NS Rs 1,451.20", out)
        self.assertNotIn("TCS.NS Rs", out)


class TheTimeMachine(InTmp):
    def test_replays_the_nse_session(self):
        os.makedirs("tm")
        doc, last = sixty_days()
        self.write("tm/RELIANCE.NS-60d5m.json", doc)
        tm = load("trader-timemachine", "timemachine")
        code, out, err = run(tm, ["--market", "in", "run", "--symbol", "reliance", "--date", DAY,
                                  "--entry", "%.2f" % last, "--stop", "%.2f" % (last - 8),
                                  "--target", "%.2f" % (last + 16), "--entry-time", "9:40 AM", "--offline", "tm",
                                  "--now", DAY + " 09:41", "--replays", "500"])
        self.assertEqual(code, 0, out + err)
        self.assertEqual(tm.SESSION_BARS, 75)
        self.assertIn("9:40 AM to 3:30 PM (70 five-minute bars)", out)
        self.assertIn("last 30 full sessions", out)


if __name__ == "__main__":
    unittest.main()
