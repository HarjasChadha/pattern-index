"""
Pattern Index — Daily Updater
Runs at 3:35 PM IST via GitHub Actions.
Reads params from params.json, scrapes NSE + Gold NAV,
computes signals, appends to data/history.json,
sends Telegram alert.
"""

import json, os, time, requests, numpy as np
from datetime import datetime, date
from zoneinfo import ZoneInfo
from pathlib import Path

IST       = ZoneInfo("Asia/Kolkata")
DATA_DIR  = Path("data")
HIST_FILE = DATA_DIR / "history.json"
PARAM_FILE= Path("params.json")
DATA_DIR.mkdir(exist_ok=True)

# ── Load params (written by the Colab export cell) ────────────────
with open(PARAM_FILE) as f:
    CFG = json.load(f)

INDEX_LABEL    = CFG["index_label"]
NSE_SLUG       = CFG["nse_slug"]
PE_LOOKBACK    = int(CFG["pe_lookback"])
PE_FLOOR       = float(CFG["pe_floor"])
PE_CEILING     = float(CFG["pe_ceiling"])
DD_THRESHOLD   = float(CFG["dd_threshold"])
MA_LOOKBACK    = int(CFG["ma_lookback"])
INITIAL_CAPITAL= float(CFG.get("initial_capital", 100000))
TC             = 0.001
DEBT_DAILY     = 0.065 / 252
SBI_GOLD_AMFI  = "119598"

# ── Telegram (from GitHub secrets → env vars) ─────────────────────
TG_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TG_CHAT  = os.environ.get("TELEGRAM_CHAT_ID", "")

# ─────────────────────────────────────────────────────────────────
# Scrapers
# ─────────────────────────────────────────────────────────────────

def scrape_nse(slug):
    session = requests.Session()
    hdrs = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
        "Accept": "application/json",
        "Referer": "https://www.nseindia.com/",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        session.get("https://www.nseindia.com/", headers=hdrs, timeout=15)
        time.sleep(2)
        url = f"https://www.nseindia.com/api/equity-stockIndices?index={slug}"
        r   = session.get(url, headers=hdrs, timeout=15)
        d   = r.json().get("data", [{}])[0]
        pe    = float(d.get("pe") or 0)
        price = float(d.get("last") or d.get("previousClose") or 0)
        if pe > 0 and price > 0:
            return pe, price
    except Exception as e:
        print(f"NSE attempt 1 failed: {e}")

    # Fallback — allIndices
    try:
        session.get("https://www.nseindia.com/", headers=hdrs, timeout=15)
        time.sleep(2)
        r2 = session.get("https://www.nseindia.com/api/allIndices",
                         headers=hdrs, timeout=15)
        target = slug.replace("%20", " ").upper()
        for item in r2.json().get("data", []):
            if (item.get("indexSymbol","").upper() == target or
                item.get("index","").upper() == target):
                pe    = float(item.get("pe") or 0)
                price = float(item.get("last") or item.get("previousClose") or 0)
                if pe > 0 and price > 0:
                    return pe, price
    except Exception as e:
        print(f"NSE attempt 2 failed: {e}")

    return None, None


def fetch_gold_nav():
    try:
        r = requests.get(f"https://api.mfapi.in/mf/{SBI_GOLD_AMFI}", timeout=15)
        item = r.json()["data"][0]
        return float(item["nav"]), item["date"]
    except Exception as e:
        print(f"Gold NAV failed: {e}")
        return None, None

# ─────────────────────────────────────────────────────────────────
# Indicator helpers
# ─────────────────────────────────────────────────────────────────

def pe_pctile(hist_pe, today_pe, lookback):
    window = list(hist_pe[-(lookback - 1):]) + [today_pe]
    if len(window) < 2:
        return None
    return round(sum(v < today_pe for v in window) / len(window) * 100, 2)

def sma(series, n):
    w = list(series[-n:])
    return round(float(np.mean(w)), 4) if len(w) >= n else None

def roll_dd(prices, lookback=252):
    w = list(prices[-lookback:])
    if not w:
        return 0.0
    peak = max(w)
    return (w[-1] - peak) / peak if peak > 0 else 0.0

# ─────────────────────────────────────────────────────────────────
# Load / save history
# ─────────────────────────────────────────────────────────────────

def load_history():
    if HIST_FILE.exists():
        with open(HIST_FILE) as f:
            return json.load(f)
    return []

def save_history(rows):
    with open(HIST_FILE, "w") as f:
        json.dump(rows, f, indent=2, default=str)

# ─────────────────────────────────────────────────────────────────
# Signal logic (mirrors run_sim exactly)
# ─────────────────────────────────────────────────────────────────

def compute(history, today_pe, today_price, today_gold):
    h_pe    = [r["pe"]       for r in history] + [today_pe]
    h_price = [r["price"]    for r in history] + [today_price]
    h_gold  = [r["gold_nav"] for r in history] + [today_gold]

    pe_pct  = pe_pctile(h_pe[:-1],    today_pe,    PE_LOOKBACK)
    p_ma    = sma(h_price, MA_LOOKBACK)
    g_ma    = sma(h_gold,  MA_LOOKBACK)
    dd      = roll_dd(h_price, 252)

    tc = 0
    if pe_pct is not None:
        if pe_pct / 100 < PE_FLOOR:    tc += 1
        if pe_pct / 100 > PE_CEILING:  tc += 1
    if dd < -abs(DD_THRESHOLD):        tc += 1
    if p_ma is not None and today_price < p_ma:
        tc += 1

    cur = history[-1]["asset"] if history else "EQUITY"

    if cur == "EQUITY":
        if tc >= 2:
            tgt    = "GOLD" if (g_ma and today_gold > g_ma) else "DEBT"
            signal = f"EXIT EQUITY → {tgt}"
        else:
            tgt    = "EQUITY"
            signal = "STAY EQUITY"
    elif cur == "GOLD":
        if g_ma and today_gold < g_ma and tc >= 2:
            tgt = "DEBT";   signal = "GOLD → DEBT"
        elif tc < 2:
            tgt = "EQUITY"; signal = "GOLD → EQUITY (recovery)"
        else:
            tgt = "GOLD";   signal = "STAY GOLD"
    elif cur == "DEBT":
        if tc < 2:
            tgt = "EQUITY"; signal = "DEBT → EQUITY (recovery)"
        else:
            tgt = "DEBT";   signal = "STAY DEBT"
    else:
        tgt = "EQUITY"; signal = "DEFAULT → EQUITY"

    # Portfolio value
    if not history:
        prev_pv    = INITIAL_CAPITAL
        prev_bv    = INITIAL_CAPITAL
        prev_price = today_price
        prev_gold  = today_gold
        prev_asset = "EQUITY"
    else:
        prev       = history[-1]
        prev_pv    = prev["portfolio_value"]
        prev_bv    = prev["benchmark_value"]
        prev_price = prev["price"]
        prev_gold  = prev["gold_nav"]
        prev_asset = cur

    bv = prev_bv * (today_price / prev_price) if prev_price > 0 else prev_bv

    if   prev_asset == "EQUITY": pv = prev_pv * (today_price / prev_price) if prev_price > 0 else prev_pv
    elif prev_asset == "GOLD":   pv = prev_pv * (today_gold  / prev_gold)  if prev_gold  > 0 else prev_pv
    elif prev_asset == "DEBT":   pv = prev_pv * (1 + DEBT_DAILY)
    else:                        pv = prev_pv
    if tgt != cur:
        pv *= (1 - TC)

    all_bv = [r["benchmark_value"]  for r in history] + [bv]
    all_pv = [r["portfolio_value"]  for r in history] + [pv]
    bm_dd  = round((bv - max(all_bv)) / max(all_bv) * 100, 4) if max(all_bv) > 0 else 0
    pf_dd  = round((pv - max(all_pv)) / max(all_pv) * 100, 4) if max(all_pv) > 0 else 0

    return dict(
        date             = str(date.today()),
        pe               = round(today_pe,    2),
        pe_pct           = pe_pct,
        price            = round(today_price, 2),
        price_ma         = p_ma,
        gold_nav         = round(today_gold,  4),
        gold_ma          = g_ma,
        asset            = tgt,
        triggers         = tc,
        benchmark_dd     = bm_dd,
        portfolio_dd     = pf_dd,
        portfolio_value  = round(pv, 2),
        benchmark_value  = round(bv, 2),
        signal           = signal,
    )

# ─────────────────────────────────────────────────────────────────
# Telegram
# ─────────────────────────────────────────────────────────────────

def send_telegram(row):
    if not TG_TOKEN or not TG_CHAT:
        print("Telegram not configured — skipping.")
        return

    emoji = {"EQUITY":"📈","GOLD":"🥇","DEBT":"🏦"}.get(row["asset"], "💼")
    signal_emoji = "⚠️" if "EXIT" in row["signal"] or "→" in row["signal"].replace("STAY","") else "✅"

    msg = (
        f"*Pattern Index — {INDEX_LABEL}*\n"
        f"📅 {row['date']}\n\n"
        f"PE Ratio    : `{row['pe']}`  ({row['pe_pct']}th %ile)\n"
        f"Price       : `₹{row['price']:,}`  (MA{MA_LOOKBACK}: {row['price_ma']})\n"
        f"Gold NAV    : `₹{row['gold_nav']}`  (MA{MA_LOOKBACK}: {row['gold_ma']})\n"
        f"Triggers    : `{row['triggers']}/4`\n\n"
        f"*{signal_emoji} {row['signal']}*\n"
        f"{emoji} Holding: *{row['asset']}*\n\n"
        f"Portfolio : `₹{row['portfolio_value']:,.2f}`  (DD: {row['portfolio_dd']:+.2f}%)\n"
        f"Benchmark : `₹{row['benchmark_value']:,.2f}`  (DD: {row['benchmark_dd']:+.2f}%)\n"
        f"Outperf   : `{row['portfolio_value'] - row['benchmark_value']:+,.2f}`"
    )
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": msg, "parse_mode": "Markdown"},
            timeout=10
        )
        print("Telegram sent.")
    except Exception as e:
        print(f"Telegram failed: {e}")

# ─────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────

def main():
    today = date.today()
    print(f"\n=== Pattern Index Updater — {today} ({INDEX_LABEL}) ===")

    if today.weekday() >= 5:
        print("Weekend — skipping.")
        return

    history = load_history()

    # Skip if already done today
    if history and history[-1]["date"] == str(today):
        print("Already updated today.")
        return

    print("Scraping NSE...")
    pe, price = scrape_nse(NSE_SLUG)
    if pe is None:
        print("NSE scrape failed — aborting.")
        raise SystemExit(1)
    print(f"  PE={pe}  Price={price}")

    print("Fetching Gold NAV...")
    gold_nav, gold_date = fetch_gold_nav()
    if gold_nav is None:
        print("Gold NAV failed — aborting.")
        raise SystemExit(1)
    print(f"  NAV={gold_nav}  ({gold_date})")

    print("Computing signal...")
    row = compute(history, pe, price, gold_nav)
    print(f"  Signal: {row['signal']}  |  Asset: {row['asset']}")
    print(f"  Portfolio: ₹{row['portfolio_value']:,.2f}  Benchmark: ₹{row['benchmark_value']:,.2f}")

    history.append(row)
    save_history(history)
    print(f"Saved to {HIST_FILE}  ({len(history)} rows total)")

    send_telegram(row)
    print("Done.")

if __name__ == "__main__":
    main()
