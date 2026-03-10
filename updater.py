#!/usr/bin/env python3
"""
Pattern Index - Daily Updater
Runs via GitHub Actions after market close (weekdays ~4 PM IST = 10:30 UTC).
Fetches NSE price/PE + Gold NAV, updates history.json, commits back.
"""

import json, os, time, datetime, requests
import numpy as np
from pathlib import Path

# Load params
with open('params.json') as f:
    P = json.load(f)

PE_LB      = P['pe_lookback']
PE_FL      = P['pe_floor']
PE_CE      = P['pe_ceiling']
DD_TH      = P['dd_threshold']
MA_LB      = P['ma_lookback']
GOLD_MA_LB = P.get('gold_ma_lookback', 50)
TC         = 0.001
DEBT_DAILY = 0.065 / 252
INITIAL_CAPITAL = P.get('initial_capital', 100000.0)
NSE_SLUG    = P['nse_slug']
INDEX_LABEL = P['index_label']

TODAY     = datetime.date.today()
TODAY_STR = str(TODAY)

print(f"\n{'='*55}")
print(f"  Pattern Index Updater - {TODAY_STR} ({INDEX_LABEL})")
print(f"{'='*55}")

# Weekend check
if TODAY.weekday() >= 5:
    print(f"Weekend - skipping.")
    exit(0)

# Load history.json
history_path = Path('data/history.json')
if not history_path.exists():
    print("ERROR: data/history.json not found. Re-run Cell 17 in Colab.")
    exit(1)

raw = json.loads(history_path.read_text())

if isinstance(raw, list):
    print("WARNING: Old flat history.json format detected. Please re-run Cell 17 in Colab.")
    lookback_data = raw
    live_rows = []
    legacy_mode = True
else:
    lookback_data = raw.get('lookback_data', [])
    live_rows = raw.get('live_rows', [])
    legacy_mode = False

# Check if today already exists in live_rows only
# (lookback_data may already have today from a previous partial run)
live_dates = [r['date'] for r in live_rows]
if TODAY_STR in live_dates:
    print(f"Today ({TODAY_STR}) already in live_rows - skipping.")
    exit(0)

print(f"  Lookback rows : {len(lookback_data)}")
print(f"  Live rows     : {len(live_rows)}")
print(f"  Last lookback : {lookback_data[-1]['date'] if lookback_data else 'none'}")
print(f"  Last live     : {live_rows[-1]['date'] if live_rows else 'none'}")


def scrape_nse():
    """
    Fetch latest closing price and PE from Screener.in.
    Screener always shows the last market close — perfect for our 11:30 PM run.
    Returns (price, pe, date_str).
    """
    try:
        from bs4 import BeautifulSoup
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        r = requests.get(
            'https://www.screener.in/company/NMIDCAP150/',
            headers=headers, timeout=15
        )
        soup = BeautifulSoup(r.text, 'html.parser')

        price, pe = None, None

        # Screener renders ratios as <ul class="company-ratios"> <li> items
        # Each <li> has a <span class="name"> label and a <span class="number"> value
        for li in soup.select('ul.company-ratios li'):
            name_tag = li.find('span', class_='name')
            num_tag  = li.find('span', class_='number')
            if not name_tag or not num_tag:
                continue
            label = name_tag.get_text(strip=True).lower()
            val   = num_tag.get_text(strip=True).replace(',', '').replace('₹', '').replace('%', '').strip()
            try:
                if 'current price' in label and price is None:
                    price = float(val)
                if label in ('p/e', 'pe', 'stock p/e', 'price to earning') and pe is None:
                    pe = float(val)
            except ValueError:
                pass

        # Fallback: the big price shown at top of page (outside the ratios list)
        if price is None:
            for tag in soup.select('#top h2, .company-price, [class*="price"]'):
                txt = tag.get_text(strip=True).replace(',', '').replace('₹', '')
                try:
                    candidate = float(txt)
                    if 5000 < candidate < 100000:  # sanity range for MIDCAP 150 index
                        price = candidate
                        break
                except ValueError:
                    pass

        # Fallback PE: look for any li containing 'p/e' text
        if pe is None:
            for li in soup.select('li'):
                txt = li.get_text(separator=' ', strip=True).lower()
                if 'p/e' in txt or 'price to earning' in txt:
                    nums = []
                    for t in li.find_all(['span', 'strong', 'b']):
                        try:
                            nums.append(float(t.get_text(strip=True).replace(',', '')))
                        except ValueError:
                            pass
                    if nums:
                        pe = nums[0]
                        break

        if price and pe:
            print(f"  Screener ok: price={price}, pe={pe}")
            return price, pe, TODAY_STR
        else:
            print(f"  Screener parse failed: price={price}, pe={pe}")
            # Print a snippet of the page to help debug
            print(f"  Page snippet: {r.text[2000:2500]}")
            return None, None, None

    except Exception as e:
        print(f"  Screener failed: {e}")
        return None, None, None


def scrape_gold_nav():
    """Fetch latest Gold ETF NAV. Returns (nav, nav_date_str)."""
    try:
        r = requests.get('https://api.mfapi.in/mf/119598', timeout=10)
        data = r.json()
        nav_data = data['data']
        nav      = float(nav_data[0]['nav'])
        nav_date = nav_data[0]['date']  # format: DD-Mon-YYYY
        print(f"  Gold NAV ok: {nav} (date: {nav_date})")
        return nav, nav_date
    except Exception as e:
        print(f"  Gold NAV failed: {e}")
        return None, None


# Fetch live data
price_today, pe_today, _ = scrape_nse()
nav_today, nav_date = scrape_gold_nav()

if price_today is None or pe_today is None:
    print("FATAL: Could not fetch NSE data. Exiting.")
    exit(1)

if nav_today is None:
    print("FATAL: Could not fetch Gold NAV. Exiting.")
    exit(1)

# ── Freshness check ────────────────────────────────────────────────
# If NSE returns the exact same price as the last known row, it's serving
# stale data (common overnight). Abort so we don't write a bad row.
if lookback_data:
    last_lb_price = lookback_data[-1]['price']
    last_lb_date  = lookback_data[-1]['date']
    if price_today == last_lb_price and last_lb_date != TODAY_STR:
        print(f"STALE DATA: NSE price ({price_today}) matches last row ({last_lb_date}).")
        print(f"NSE API not yet updated for today. Exiting without writing.")
        exit(0)

# Build arrays for indicator calculation
all_historical = lookback_data + [r for r in live_rows if r['date'] != TODAY_STR]

prices_arr = np.array([r['price']    for r in all_historical] + [price_today], dtype=np.float64)
pe_arr     = np.array([r['pe']       for r in all_historical] + [pe_today],    dtype=np.float64)
nav_arr    = np.array([r['gold_nav'] for r in all_historical] + [nav_today],   dtype=np.float64)
n = len(prices_arr)
i = n - 1


def sma(arr, idx, lb):
    if idx < lb - 1:
        return None
    return float(np.mean(arr[idx-lb+1:idx+1]))


def roll_pct(arr, idx, lb):
    if idx < lb:
        return None
    w = arr[idx-lb:idx+1]
    return float(np.sum(w < arr[idx]) / len(w))


def roll_dd(arr, idx, lb=252):
    start = max(0, idx-lb+1)
    w = arr[start:idx+1]
    peak = np.max(w)
    return float((arr[idx]-peak)/peak) if peak > 0 else 0.0


pe_pct = roll_pct(pe_arr, i, PE_LB)
p_ma   = sma(prices_arr, i, MA_LB)
g_ma   = sma(nav_arr, i, GOLD_MA_LB)
dd     = roll_dd(prices_arr, i, 252)

t_pe_floor   = (pe_pct is not None) and (pe_pct < PE_FL)
t_pe_ceiling = (pe_pct is not None) and (pe_pct > PE_CE)
t_dd         = dd < -abs(DD_TH)
t_ma         = (p_ma is not None) and (price_today < p_ma)
tc           = sum([t_pe_floor, t_pe_ceiling, t_dd, t_ma])

print(f"\n  Indicators:")
print(f"    PE={pe_today}, PE%ile={round(pe_pct*100,1) if pe_pct else 'N/A'}%")
print(f"    Price={price_today}, MA{MA_LB}={round(p_ma,2) if p_ma else 'N/A'}")
print(f"    Gold={nav_today}, GoldMA{GOLD_MA_LB}={round(g_ma,4) if g_ma else 'N/A'}")
print(f"    DrawDown={round(dd*100,2)}%, Triggers={tc}/4")
print(f"    t_pe_floor={t_pe_floor}, t_pe_ceiling={t_pe_ceiling}, t_dd={t_dd}, t_ma={t_ma}")

# T+2 Settlement State Machine
if live_rows:
    last_live        = live_rows[-1]
    current_asset    = last_live['asset']
    current_pv       = last_live['portfolio_value']
    current_bv       = last_live['benchmark_value']
    settlement_state = last_live.get('settlement_state', 'NORMAL')
    pending_target   = last_live.get('pending_target', None)
else:
    current_asset    = 'EQUITY'
    current_pv       = INITIAL_CAPITAL
    current_bv       = INITIAL_CAPITAL
    settlement_state = 'NORMAL'
    pending_target   = None

# Benchmark mark to market
if live_rows:
    bv_start_price = live_rows[0]['price']
    bv_start       = live_rows[0]['benchmark_value']
else:
    bv_start_price = lookback_data[-1]['price']
    bv_start       = INITIAL_CAPITAL

bv_units_bench = bv_start / bv_start_price
current_bv_new = bv_units_bench * price_today

# Portfolio mark to market
if current_asset == 'EQUITY':
    if live_rows:
        pv_units = live_rows[-1]['portfolio_value'] / live_rows[-1]['price']
    else:
        pv_units = INITIAL_CAPITAL / lookback_data[-1]['price']
    new_pv = pv_units * price_today
elif current_asset == 'GOLD':
    if live_rows:
        gold_units = live_rows[-1]['portfolio_value'] / live_rows[-1]['gold_nav']
    else:
        gold_units = INITIAL_CAPITAL / lookback_data[-1]['gold_nav']
    new_pv = gold_units * nav_today
elif current_asset == 'DEBT':
    new_pv = current_pv * (1 + DEBT_DAILY)
elif current_asset == 'CASH':
    new_pv = current_pv
else:
    new_pv = current_pv

# Determine new settlement state
if settlement_state == 'NORMAL':
    if tc >= 2 and current_asset == 'EQUITY':
        target = 'GOLD' if (g_ma and nav_today > g_ma) else 'DEBT'
        new_settlement = 'SIGNAL_DAY'
        new_target = target
        signal = f"EXIT EQUITY -> {target} (T+2: sell tomorrow)"
        new_asset = current_asset
    elif tc >= 2 and current_asset == 'GOLD' and g_ma and nav_today < g_ma:
        new_settlement = 'SIGNAL_DAY'
        new_target = 'DEBT'
        signal = "GOLD -> DEBT (T+2: sell tomorrow)"
        new_asset = current_asset
    elif tc < 2 and current_asset in ('GOLD', 'DEBT'):
        new_settlement = 'SIGNAL_DAY'
        new_target = 'EQUITY'
        signal = f"{current_asset} -> EQUITY (T+2: sell tomorrow)"
        new_asset = current_asset
    else:
        new_settlement = 'NORMAL'
        new_target = None
        signal = f"STAY {current_asset}"
        new_asset = current_asset

elif settlement_state == 'SIGNAL_DAY':
    new_pv = new_pv * (1 - TC)
    new_asset = 'CASH'
    new_settlement = 'PENDING_BUY'
    new_target = pending_target
    signal = f"SELLING {current_asset} -> CASH (buying {pending_target} tomorrow)"

elif settlement_state == 'PENDING_BUY':
    new_pv = new_pv * (1 - TC)
    new_asset = pending_target
    new_settlement = 'NORMAL'
    new_target = None
    signal = f"BOUGHT {pending_target}"

else:
    new_settlement = 'NORMAL'
    new_target = None
    signal = f"STAY {current_asset}"
    new_asset = current_asset

# Drawdowns
all_pv_vals = [r['portfolio_value'] for r in live_rows] + [new_pv]
all_bv_vals = [r['benchmark_value'] for r in live_rows] + [current_bv_new]
pf_dd = round((new_pv - max(all_pv_vals)) / max(all_pv_vals) * 100, 4)
bm_dd = round((current_bv_new - max(all_bv_vals)) / max(all_bv_vals) * 100, 4)

# Build today's live row
new_row = {
    "date"             : TODAY_STR,
    "pe"               : round(pe_today, 2),
    "pe_pct"           : round(pe_pct * 100, 2) if pe_pct is not None else None,
    "price"            : round(price_today, 2),
    "price_ma"         : round(p_ma, 2) if p_ma is not None else None,
    "gold_nav"         : round(nav_today, 4),
    "gold_ma"          : round(g_ma, 4) if g_ma is not None else None,
    "asset"            : new_asset,
    "triggers"         : tc,
    "t_pe_floor"       : t_pe_floor,
    "t_pe_ceiling"     : t_pe_ceiling,
    "t_dd"             : t_dd,
    "t_ma"             : t_ma,
    "signal"           : signal,
    "settlement_state" : new_settlement,
    "pending_target"   : new_target,
    "portfolio_value"  : round(new_pv, 2),
    "benchmark_value"  : round(current_bv_new, 2),
    "benchmark_dd"     : bm_dd,
    "portfolio_dd"     : pf_dd,
    "is_live"          : True,
}

live_rows.append(new_row)

# Add today to lookback_data too (skip if already there from a previous partial run)
lookback_dates = [r['date'] for r in lookback_data]
if TODAY_STR not in lookback_dates:
    new_lookback_row = {
        "date"     : TODAY_STR,
        "pe"       : round(pe_today, 2),
        "pe_pct"   : round(pe_pct * 100, 2) if pe_pct is not None else None,
        "price"    : round(price_today, 2),
        "price_ma" : round(p_ma, 2) if p_ma is not None else None,
        "gold_nav" : round(nav_today, 4),
        "gold_ma"  : round(g_ma, 4) if g_ma is not None else None,
        "triggers" : tc,
    }
    lookback_data.append(new_lookback_row)

# Write history.json
output = {
    "lookback_data": lookback_data,
    "live_rows"    : live_rows,
}
history_path.write_text(json.dumps(output, indent=2))
print(f"\n  history.json updated - live rows now: {len(live_rows)}")

# Send Telegram
TG_TOKEN  = os.environ.get('TELEGRAM_TOKEN')
TG_CHATID = os.environ.get('TELEGRAM_CHAT_ID')

if TG_TOKEN and TG_CHATID:
    emoji = {'EQUITY': '[EQ]', 'GOLD': '[GOLD]', 'DEBT': '[DEBT]', 'CASH': '[CASH]'}.get(new_asset, '[--]')
    pe_pct_str = str(round(pe_pct * 100, 1)) if pe_pct else 'N/A'
    p_ma_str   = str(round(p_ma, 2)) if p_ma else 'N/A'
    g_ma_str   = str(round(g_ma, 4)) if g_ma else 'N/A'
    msg = (
        f"*Pattern Index - {INDEX_LABEL}*\n"
        f"Date: {TODAY_STR}\n\n"
        f"{emoji} *{signal}*\n\n"
        f"PE: {pe_today} ({pe_pct_str}th %ile)\n"
        f"Price: {price_today} | MA{MA_LB}: {p_ma_str}\n"
        f"Gold NAV: {nav_today} | GoldMA{GOLD_MA_LB}: {g_ma_str}\n"
        f"Triggers: {tc}/4 | DD: {round(dd*100,2)}%\n\n"
        f"Portfolio: {round(new_pv, 0)}\n"
        f"Benchmark: {round(current_bv_new, 0)}\n"
        f"Holding: *{new_asset}*"
    )
    if new_settlement != 'NORMAL':
        msg += f"\nSettlement: {new_settlement}"
    try:
        requests.post(
            f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
            json={'chat_id': TG_CHATID, 'text': msg, 'parse_mode': 'Markdown'},
            timeout=10
        )
        print("  Telegram sent")
    except Exception as e:
        print(f"  Telegram failed: {e}")
else:
    print("  No Telegram secrets - skipping")

print(f"\n{'='*55}")
print(f"  Done. Asset: {new_asset} | Signal: {signal}")
print(f"{'='*55}\n")
