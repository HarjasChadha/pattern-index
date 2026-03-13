#!/usr/bin/env python3
"""
Pattern Index — Daily Updater  v3.0  (ETF Edition)
Runs via GitHub Actions after market close (weekdays ~11:30 PM IST = 18:00 UTC)

Data sources:
  - ETF prices (IICP, GOLDBEES, EBBETF0431) : yfinance
  - Midcap 150 Index price                   : yfinance (fallback: Screener)
  - Midcap 150 Index PE                      : Screener.in
"""

import json, os, datetime, requests
import numpy as np
from pathlib import Path

# ── Load params ────────────────────────────────────────────────────
with open('params.json') as f:
    P = json.load(f)

PE_LB        = P['pe_lookback']
PE_FL        = P['pe_floor']
PE_CE        = P['pe_ceiling']
DD_TH        = P['dd_threshold']
MA_LB        = P['ma_lookback']
GOLD_MA_LB   = P.get('gold_ma_lookback', 50)
TC           = 0.001
INITIAL_CAPITAL = P.get('initial_capital', 100000.0)
INDEX_LABEL  = P.get('index_label', 'MIDCAP 150')

EQUITY_TICKER = P.get('equity_etf', 'IICP')      + '.NS'
GOLD_TICKER   = P.get('gold_etf',   'GOLDBEES')   + '.NS'
DEBT_TICKER   = P.get('debt_etf',   'EBBETF0431') + '.NS'

TODAY     = datetime.date.today()
TODAY_STR = str(TODAY)

print(f"\n{'='*58}")
print(f"  Pattern Index Updater v3.0 — {TODAY_STR}")
print(f"  {INDEX_LABEL} | ETF tracking mode")
print(f"{'='*58}")

if TODAY.weekday() >= 5:
    print("Weekend — skipping.")
    exit(0)

# ── Load history.json ─────────────────────────────────────────────
history_path = Path('data/history.json')
if not history_path.exists():
    print("ERROR: data/history.json not found.")
    exit(1)

raw = json.loads(history_path.read_text())
if isinstance(raw, list):
    print("ERROR: Old flat history.json format. Re-run Cell 17 in Colab.")
    exit(1)

lookback_data = raw.get('lookback_data', [])
live_rows     = raw.get('live_rows', [])

# Check if today already exists — but allow overwriting seed rows.
# Cell 17 seeds live_rows with today at initial_capital before any real data.
# We detect this and overwrite rather than skip.
existing_today = [r for r in live_rows if r['date'] == TODAY_STR]
if existing_today:
    row = existing_today[0]
    # A seed row: portfolio/benchmark both exactly equal initial capital
    # Real data will differ by even 1 paisa after mark-to-market
    is_seed = (
        abs(row.get('portfolio_value', 0) - INITIAL_CAPITAL) < 0.01 and
        abs(row.get('benchmark_value', 0) - INITIAL_CAPITAL) < 0.01
    )
    if is_seed:
        print(f"Today ({TODAY_STR}) is a seed row — overwriting with live data.")
        live_rows = [r for r in live_rows if r['date'] != TODAY_STR]
    else:
        print(f"Today ({TODAY_STR}) already has live data — skipping.")
        exit(0)

print(f"  Lookback rows : {len(lookback_data)}")
print(f"  Live rows     : {len(live_rows)}")


# ── Data fetchers ─────────────────────────────────────────────────
def fetch_etf_price(ticker):
    try:
        import yfinance as yf
        import pytz
        IST = pytz.timezone('Asia/Kolkata')
        hist = yf.Ticker(ticker).history(period='5d')
        if hist.empty:
            print(f"  ⚠  {ticker}: empty")
            return None
        # Convert index to IST so date() gives the correct Indian trading date
        hist.index = hist.index.tz_convert(IST)
        price = float(hist['Close'].iloc[-1])
        date  = str(hist.index[-1].date())
        print(f"  ✅ {ticker}: {price:.4f}  ({date})")
        return price
    except Exception as e:
        print(f"  ❌ {ticker}: {e}")
        return None


def fetch_index_price():
    for ticker in ['^NIFTYMIDCAP150', 'NIFTYMIDCAP150.NS']:
        try:
            import yfinance as yf, pytz
            IST = pytz.timezone('Asia/Kolkata')
            hist = yf.Ticker(ticker).history(period='5d')
            if not hist.empty:
                hist.index = hist.index.tz_convert(IST)
                price = float(hist['Close'].iloc[-1])
                print(f"  ✅ Index ({ticker}): {price:.2f}  ({str(hist.index[-1].date())})")
                return price
        except Exception:
            pass
    # Screener fallback
    try:
        from bs4 import BeautifulSoup
        r = requests.get('https://www.screener.in/company/NMIDCAP150/',
                         headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        soup = BeautifulSoup(r.text, 'html.parser')
        for li in soup.select('ul.company-ratios li'):
            name = li.find('span', class_='name')
            num  = li.find('span', class_='number')
            if name and num and 'current price' in name.get_text(strip=True).lower():
                price = float(num.get_text(strip=True).replace(',','').replace('₹',''))
                print(f"  ✅ Index (Screener fallback): {price:.2f}")
                return price
    except Exception as e:
        print(f"  ❌ Index Screener fallback: {e}")
    return None


def fetch_pe():
    try:
        from bs4 import BeautifulSoup
        r = requests.get('https://www.screener.in/company/NMIDCAP150/',
                         headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        soup = BeautifulSoup(r.text, 'html.parser')
        for li in soup.select('ul.company-ratios li'):
            name = li.find('span', class_='name')
            num  = li.find('span', class_='number')
            if not name or not num: continue
            label = name.get_text(strip=True).lower()
            if label in ('p/e', 'pe', 'stock p/e', 'price to earning'):
                pe = float(num.get_text(strip=True).replace(',',''))
                print(f"  ✅ PE (Screener): {pe}")
                return pe
        # Wider fallback
        for li in soup.select('li'):
            txt = li.get_text(separator=' ', strip=True).lower()
            if 'p/e' in txt or 'price to earning' in txt:
                for t in li.find_all(['span','strong','b']):
                    try:
                        v = float(t.get_text(strip=True).replace(',',''))
                        if 5 < v < 200:
                            print(f"  ✅ PE (fallback): {v}")
                            return v
                    except ValueError:
                        pass
        print("  ❌ PE not found on Screener")
        return None
    except Exception as e:
        print(f"  ❌ Screener PE: {e}")
        return None


# ── Fetch all ─────────────────────────────────────────────────────
print(f"\n  Fetching market data...")
iicp_price  = fetch_etf_price(EQUITY_TICKER)
gold_price  = fetch_etf_price(GOLD_TICKER)
debt_price  = fetch_etf_price(DEBT_TICKER)
index_price = fetch_index_price()
pe_today    = fetch_pe()

missing = [name for name, val in [
    ('IICP', iicp_price), ('GOLDBEES', gold_price), ('EBBETF', debt_price),
    ('Index price', index_price), ('PE', pe_today)] if val is None]
if missing:
    print(f"\nFATAL: Missing: {missing}")
    exit(1)

# Stale data guard
if lookback_data:
    last_iicp = lookback_data[-1].get('iicp_price')
    last_date = lookback_data[-1]['date']
    if last_iicp and iicp_price == last_iicp and last_date != TODAY_STR:
        print(f"\nSTALE: IICP price ({iicp_price}) matches last row ({last_date}) — exiting.")
        exit(0)


# ── Indicators ────────────────────────────────────────────────────
# Exclude today from both sources — we append today's fresh data manually below
all_rows = [r for r in lookback_data if r['date'] != TODAY_STR] + \
           [r for r in live_rows   if r['date'] != TODAY_STR]

# Prefer index_price key; fall back to old 'price' key
idx_arr  = np.array([r.get('index_price', r.get('price', 0)) for r in all_rows] + [index_price], dtype=np.float64)
pe_arr   = np.array([r['pe'] for r in all_rows] + [pe_today], dtype=np.float64)
gold_arr = np.array([r.get('gold_price', r.get('gold_nav', 0)) for r in all_rows] + [gold_price], dtype=np.float64)
n = len(idx_arr)
i = n - 1

def sma(arr, idx, lb):
    if idx < lb - 1: return None
    return float(np.mean(arr[idx-lb+1:idx+1]))

def roll_pct(arr, idx, lb):
    if idx < lb: return None
    w = arr[idx-lb:idx+1]
    return float(np.sum(w < arr[idx]) / len(w))

def roll_dd(arr, idx, lb=252):
    start = max(0, idx-lb+1)
    w = arr[start:idx+1]
    peak = np.max(w)
    return float((arr[idx]-peak)/peak) if peak > 0 else 0.0

pe_pct = roll_pct(pe_arr,  i, PE_LB)
p_ma   = sma(idx_arr,      i, MA_LB)
g_ma   = sma(gold_arr,     i, GOLD_MA_LB)
dd     = roll_dd(idx_arr,  i, 252)

t_pe_floor   = (pe_pct is not None) and (pe_pct < PE_FL)
t_pe_ceiling = (pe_pct is not None) and (pe_pct > PE_CE)
t_dd         = dd < -abs(DD_TH)
t_ma         = (p_ma is not None) and (index_price < p_ma)
tc           = sum([t_pe_floor, t_pe_ceiling, t_dd, t_ma])

print(f"\n  Indicators:")
print(f"    Index: {index_price:.2f} | MA{MA_LB}: {round(p_ma,2) if p_ma else 'N/A'}")
print(f"    PE: {pe_today} | PE%ile: {round(pe_pct*100,1) if pe_pct else 'N/A'}%")
print(f"    IICP: {iicp_price:.4f} | GOLDBEES: {gold_price:.4f} | EBBETF: {debt_price:.4f}")
print(f"    Gold MA{GOLD_MA_LB}: {round(g_ma,4) if g_ma else 'N/A'} | DD: {round(dd*100,2)}%")
print(f"    Triggers: {tc}/4  [floor={t_pe_floor}, ceil={t_pe_ceiling}, dd={t_dd}, ma={t_ma}]")


# ── State machine ─────────────────────────────────────────────────
if live_rows:
    last_live        = live_rows[-1]
    current_asset    = last_live['asset']
    current_pv       = last_live['portfolio_value']
    settlement_state = last_live.get('settlement_state', 'NORMAL')
    pending_target   = last_live.get('pending_target', None)
else:
    current_asset    = 'EQUITY'
    current_pv       = INITIAL_CAPITAL
    settlement_state = 'NORMAL'
    pending_target   = None

# Portfolio mark to market
def etf_price_for(asset):
    return {'EQUITY': iicp_price, 'GOLD': gold_price, 'DEBT': debt_price}.get(asset)

def prev_etf_price(row, asset):
    return {'EQUITY': row.get('iicp_price', row.get('price')),
            'GOLD':   row.get('gold_price', row.get('gold_nav')),
            'DEBT':   row.get('debt_price')}.get(asset)

if live_rows and current_asset != 'CASH':
    prev = live_rows[-1]
    prev_p = prev_etf_price(prev, current_asset)
    cur_p  = etf_price_for(current_asset)
    new_pv = (prev['portfolio_value'] / prev_p * cur_p) if prev_p and cur_p else current_pv
elif current_asset == 'CASH':
    new_pv = current_pv
else:
    new_pv = INITIAL_CAPITAL

# Benchmark: IICP buy-and-hold
if live_rows:
    bv0    = live_rows[0]['benchmark_value']
    bv0_p  = prev_etf_price(live_rows[0], 'EQUITY') or iicp_price
    new_bv = bv0 / bv0_p * iicp_price
else:
    new_bv = INITIAL_CAPITAL

# Signal / state transitions
if settlement_state == 'NORMAL':
    if tc >= 2 and current_asset == 'EQUITY':
        target = 'GOLD' if (g_ma and gold_price > g_ma) else 'DEBT'
        new_settlement, new_target = 'SIGNAL_DAY', target
        signal, new_asset = f"EXIT EQUITY → {target}", current_asset
    elif tc >= 2 and current_asset == 'GOLD' and g_ma and gold_price < g_ma:
        new_settlement, new_target = 'SIGNAL_DAY', 'DEBT'
        signal, new_asset = "GOLD → DEBT", current_asset
    elif tc < 2 and current_asset in ('GOLD', 'DEBT'):
        new_settlement, new_target = 'SIGNAL_DAY', 'EQUITY'
        signal, new_asset = f"{current_asset} → EQUITY", current_asset
    else:
        new_settlement, new_target = 'NORMAL', None
        signal, new_asset = f"STAY {current_asset}", current_asset

elif settlement_state == 'SIGNAL_DAY':
    new_pv = new_pv * (1 - TC)
    new_settlement, new_target = 'PENDING_BUY', pending_target
    signal, new_asset = f"SOLD → CASH (buying {pending_target} tomorrow)", 'CASH'

elif settlement_state == 'PENDING_BUY':
    new_pv = new_pv * (1 - TC)
    new_settlement, new_target = 'NORMAL', None
    signal, new_asset = f"BOUGHT {pending_target}", pending_target

else:
    new_settlement, new_target = 'NORMAL', None
    signal, new_asset = f"STAY {current_asset}", current_asset

# Drawdowns
all_pv = [r['portfolio_value'] for r in live_rows] + [new_pv]
all_bv = [r['benchmark_value'] for r in live_rows] + [new_bv]
pf_dd  = round((new_pv - max(all_pv)) / max(all_pv) * 100, 4)
bm_dd  = round((new_bv - max(all_bv)) / max(all_bv) * 100, 4)

print(f"\n  Signal: {signal}")
print(f"  Asset: {new_asset} | Portfolio: ₹{new_pv:,.2f} | Benchmark: ₹{new_bv:,.2f}")


# ── Build rows ────────────────────────────────────────────────────
new_live_row = {
    "date"             : TODAY_STR,
    "pe"               : round(pe_today, 2),
    "pe_pct"           : round(pe_pct * 100, 2) if pe_pct is not None else None,
    "index_price"      : round(index_price, 2),
    "price_ma"         : round(p_ma, 2) if p_ma is not None else None,
    "iicp_price"       : round(iicp_price, 4),
    "gold_price"       : round(gold_price, 4),
    "debt_price"       : round(debt_price, 4),
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
    "benchmark_value"  : round(new_bv, 2),
    "benchmark_dd"     : bm_dd,
    "portfolio_dd"     : pf_dd,
    "is_live"          : True,
}
live_rows.append(new_live_row)

# Overwrite any seed row for today, then append fresh data
lookback_data = [r for r in lookback_data if r['date'] != TODAY_STR]
lookback_data.append({
        "date"        : TODAY_STR,
        "pe"          : round(pe_today, 2),
        "pe_pct"      : round(pe_pct * 100, 2) if pe_pct is not None else None,
        "index_price" : round(index_price, 2),
        "price_ma"    : round(p_ma, 2) if p_ma is not None else None,
        "iicp_price"  : round(iicp_price, 4),
        "gold_price"  : round(gold_price, 4),
        "debt_price"  : round(debt_price, 4),
        "gold_ma"     : round(g_ma, 4) if g_ma is not None else None,
        "triggers"    : tc,
    })

history_path.write_text(json.dumps({"lookback_data": lookback_data, "live_rows": live_rows}, indent=2))
print(f"\n  ✅ history.json updated — live rows: {len(live_rows)}")


# ── Telegram ─────────────────────────────────────────────────────
TG_TOKEN  = os.environ.get('TELEGRAM_TOKEN')
TG_CHATID = os.environ.get('TELEGRAM_CHAT_ID')
if TG_TOKEN and TG_CHATID:
    emoji = {'EQUITY':'📈','GOLD':'🥇','DEBT':'🏦','CASH':'💵'}.get(new_asset,'—')
    msg = (
        f"*Pattern Index — {INDEX_LABEL}*\n"
        f"Date: {TODAY_STR}\n\n"
        f"{emoji} *{signal}*\n\n"
        f"PE: {pe_today} ({round(pe_pct*100,1) if pe_pct else 'N/A'}th %ile)\n"
        f"Index: {index_price:.0f} | MA{MA_LB}: {round(p_ma,0) if p_ma else 'N/A'}\n"
        f"IICP: {iicp_price:.2f} | GOLDBEES: {gold_price:.2f} | EBBETF: {debt_price:.2f}\n"
        f"Triggers: {tc}/4 | DD: {round(dd*100,2)}%\n\n"
        f"Portfolio: ₹{new_pv:,.0f} | Benchmark: ₹{new_bv:,.0f}\n"
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
        print("  ✅ Telegram sent")
    except Exception as e:
        print(f"  ❌ Telegram: {e}")
else:
    print("  No Telegram secrets — skipping")

print(f"\n{'='*58}")
print(f"  Done. Asset: {new_asset} | {signal}")
print(f"{'='*58}\n")
