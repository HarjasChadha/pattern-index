# Pattern Index — Complete Fix Guide
## All problems, all edits, in exact order

---

## WHAT IS BROKEN (Summary)

| # | Problem | Where to fix |
|---|---------|-------------|
| 1 | Dashboard shows "SMALLCAP 250" instead of "MIDCAP 150" | `params.json` on GitHub |
| 2 | Portfolio starts from 2020 — should start from TODAY | Cell 17 in Colab + `dashboard.html` |
| 3 | T+2 settlement ignored — switches asset immediately | Cell 17 in Colab + `updater.py` |
| 4 | Data only goes to Dec 31 2025 — need Jan 1 to Mar 8 2026 | New data files to download |
| 5 | Colab has no instructions for >2 NAV files or >6 PE files | Cell 4 already handles this — NO change needed |
| 6 | Gold MA uses 20-day — math doc says 50-day | Cell 17 in Colab + `updater.py` |

---

## GOOD NEWS FIRST: The file upload code is ALREADY FINE

Your Cell 4 (upload) and Cell 5 (merge) already handle ANY number of NAV files and PE files.
They loop over all uploaded files and concatenate them.
You just need to upload the new files alongside the old ones.

---

## STEP 1 — Download the missing data (Jan 1 2026 → Mar 8 2026)

You need 3 updated files. Do all of this BEFORE opening Colab.

### 1A — Price file (Investing.com)
1. Go to: https://in.investing.com/indices/nifty-midcap-150-historical-data
2. Set date range: **01/01/2019 → 09/03/2026** (the full range)
3. Download CSV
4. Save as: `Price_MID.csv`

> ⚠️ Download the FULL range from 2019, not just the new bit.
> This replaces your old price file with one complete file.

### 1B — Gold NAV file (SBI Gold Direct Growth)
You already have:
- `NAV_2019-01-01_to_2023-01-01.xlsx`
- `NAV_2023-01-02_to_2025-12-31.xlsx`

You need ONE MORE file covering Jan 1 2026 → today:
1. Go to: https://www.sbimf.com/en-us/nav-history
2. Search: "SBI Gold Fund Direct Plan Growth"
3. Select date range: 01/01/2026 → 08/03/2026
4. Download as Excel
5. Save as: `NAV_2026-01-01_to_2026-03-08.xlsx`

### 1C — PE files (NSE)
You already have PE files for 2020–2025 (6 files).
You need ONE MORE file for 2026:
1. Go to: https://www.niftyindices.com/reports/historical-data
2. Under "PE/PB/Dividend Yield" select **NIFTY MIDCAP 150**
3. Date range: **01 Jan 2026 → 08 Mar 2026**
4. Download CSV
5. Save as: `NIFTY MIDCAP 150_Historical_PE_PB_DIV_Data_0101026to08032026.csv`

---

## STEP 2 — Run Colab with updated data

1. Open your Colab notebook
2. Run **Cell 1** (installs) and **Cell 2** (parsers) — no changes needed
3. Run **Cell 3** (upload UI) — it will ask you to upload 3 batches:
   - **Price:** Upload the ONE new complete price file `Price_MID.csv`
   - **NAV:** Upload ALL THREE NAV files together (Ctrl+click all 3)
   - **PE:** Upload ALL SEVEN PE files together (Ctrl+click all 7)
4. Run **Cell 4** (parse & merge) — it handles any number automatically
5. Run **Cell 5** (date intersection) — verify the range now shows up to **Mar 8 2026**
6. Run **Cells 6–16** normally (parameter optimisation — no changes needed)
7. For **Cell 17**, you need to REPLACE it entirely — see Step 3 below

---

## STEP 3 — Replace Cell 17 entirely

Delete your current Cell 17 and paste this new version.

Key changes from the old Cell 17:
- Portfolio starts from TODAY (Mar 9 2026), not 2020
- Historical data is stored as `lookback_data` (raw prices only, no portfolio value)
- T+2 settlement is properly modelled
- Gold MA uses 50-day (not 20-day) as per the math doc
- `params.json` gets a `gold_ma_lookback: 50` field

```python
# ════════════════════════════════════════════════════════════════════
# Cell 17 — Export to GitHub (Paper Trading Setup) — FIXED VERSION
# ════════════════════════════════════════════════════════════════════

import json, os
import numpy as np
import pandas as pd
from pathlib import Path
from google.colab import files as colab_files

TODAY = pd.Timestamp.today().normalize()

# ── 1. Auto-detect index from upload filename ─────────────────────
_fname = price_filepath.upper()
if   'SMALLCAP' in _fname or 'SMCAP' in _fname: idx_label = 'SMALLCAP 250'; nse_slug = 'NIFTY%20SMALLCAP%20250'
elif 'MIDCAP'   in _fname or 'MID'   in _fname: idx_label = 'MIDCAP 150';   nse_slug = 'NIFTY%20MIDCAP%20150'
elif 'NIFTY50'  in _fname or 'LARGECAP' in _fname: idx_label = 'NIFTY 50';  nse_slug = 'NIFTY%2050'
elif 'NIFTY100' in _fname:                       idx_label = 'NIFTY 100';   nse_slug = 'NIFTY%20100'
else:
    idx_label = price_filepath.rsplit('.',1)[0].replace('Price ','').replace('_',' ').strip().upper()
    nse_slug  = idx_label.replace(' ','%20')

print(f"📊 Index detected: {idx_label}")

# ── 2. Parameters ─────────────────────────────────────────────────
PE_LB   = int(FP[0])
PE_FL   = float(FP[1])
PE_CE   = float(FP[2])
DD_TH   = float(FP[3])
MA_LB   = int(FP[4])
GOLD_MA_LB    = 50          # FIXED: math doc says 50-day Gold MA
DEBT_DAILY    = 0.065 / 252
INITIAL_CAPITAL = 100000.0
TC = 0.001

params = {
    "index_label"     : idx_label,
    "nse_slug"        : nse_slug,
    "pe_lookback"     : PE_LB,
    "pe_floor"        : PE_FL,
    "pe_ceiling"      : PE_CE,
    "dd_threshold"    : DD_TH,
    "ma_lookback"     : MA_LB,
    "gold_ma_lookback": GOLD_MA_LB,
    "initial_capital" : INITIAL_CAPITAL,
}
Path('/content/params.json').write_text(json.dumps(params, indent=2))
print(f"✅ params.json written")
print(json.dumps(params, indent=2))

# ── 3. Build helper functions ─────────────────────────────────────
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

# ── 4. Build lookback_data (raw history for indicator calculation) ─
# This is ALL historical rows — just raw market data, NO portfolio values.
# The dashboard uses this silently to compute MAs and percentiles.

all_prices = df_master['Index_Price'].values.astype(np.float64)
all_pe     = df_master['PE'].values.astype(np.float64)
all_nav    = df_master['NAV'].values.astype(np.float64)
all_dates  = df_master['Date'].values
n          = len(all_prices)

lookback_data = []
for i in range(n):
    date_str = str(pd.Timestamp(all_dates[i]).date())
    pe_pct   = roll_pct(all_pe, i, PE_LB)
    p_ma     = sma(all_prices, i, MA_LB)
    g_ma     = sma(all_nav, i, GOLD_MA_LB)
    dd       = roll_dd(all_prices, i, 252)

    tc = 0
    if pe_pct is not None:
        if pe_pct < PE_FL: tc += 1
        if pe_pct > PE_CE: tc += 1
    if dd < -abs(DD_TH): tc += 1
    if p_ma is not None and all_prices[i] < p_ma: tc += 1

    lookback_data.append({
        "date"     : date_str,
        "pe"       : round(float(all_pe[i]), 2),
        "pe_pct"   : round(pe_pct * 100, 2) if pe_pct is not None else None,
        "price"    : round(float(all_prices[i]), 2),
        "price_ma" : round(p_ma, 2) if p_ma is not None else None,
        "gold_nav" : round(float(all_nav[i]), 4),
        "gold_ma"  : round(g_ma, 4) if g_ma is not None else None,
        "triggers" : tc,
    })

print(f"\n✅ lookback_data built — {len(lookback_data)} rows")
print(f"   Range: {lookback_data[0]['date']} → {lookback_data[-1]['date']}")

# ── 5. Build live_rows — portfolio tracking starts TODAY ──────────
# Today's row is built from the LAST row of lookback_data.
# The portfolio starts fresh at INITIAL_CAPITAL.
# T+2 settlement state: we record pending transitions.

last = lookback_data[-1]
tc_today = last['triggers']
p_today  = last['price']
nav_today = last['gold_nav']
g_ma_today = last['gold_ma']

# Determine today's signal
if tc_today >= 2:
    target_asset = 'GOLD' if (g_ma_today and nav_today > g_ma_today) else 'DEBT'
    signal_today = f"EXIT EQUITY → {target_asset}"
else:
    target_asset = 'EQUITY'
    signal_today = "STAY EQUITY"

# Starting position: we start in EQUITY today (paper trading begins now)
# If signal fires today, T+2 settlement means:
#   Day 0 (today): signal detected, still in EQUITY
#   Day 1 (tomorrow): sell EQUITY → CASH
#   Day 2 (day after): buy target asset
# So today we are always EQUITY with portfolio = INITIAL_CAPITAL

live_rows = [{
    "date"              : str(TODAY.date()),
    "pe"                : last['pe'],
    "pe_pct"            : last['pe_pct'],
    "price"             : last['price'],
    "price_ma"          : last['price_ma'],
    "gold_nav"          : last['gold_nav'],
    "gold_ma"           : last['gold_ma'],
    "asset"             : "EQUITY",
    "triggers"          : tc_today,
    "signal"            : signal_today,
    "settlement_state"  : "SIGNAL_DAY" if tc_today >= 2 else "NORMAL",
    "pending_target"    : target_asset if tc_today >= 2 else None,
    "portfolio_value"   : INITIAL_CAPITAL,
    "benchmark_value"   : INITIAL_CAPITAL,
    "benchmark_dd"      : 0.0,
    "portfolio_dd"      : 0.0,
    "is_live"           : True,
}]

print(f"\n✅ live_rows seeded — starting from {TODAY.date()}")
print(f"   Starting asset : EQUITY")
print(f"   Starting capital: ₹{INITIAL_CAPITAL:,.0f}")
print(f"   Today's signal : {signal_today}")
if tc_today >= 2:
    print(f"   ⚠️  Signal fired today! T+2 settlement:")
    print(f"      Tomorrow    → sell EQUITY, sit in CASH")
    print(f"      Day after   → buy {target_asset}")

# ── 6. Write history.json ─────────────────────────────────────────
output = {
    "lookback_data": lookback_data,
    "live_rows"    : live_rows,
}

os.makedirs('/content/data', exist_ok=True)
Path('/content/data/history.json').write_text(json.dumps(output, indent=2))
print(f"\n✅ data/history.json written")
print(f"   lookback_data : {len(lookback_data)} rows (raw market data, no portfolio)")
print(f"   live_rows     : {len(live_rows)} rows (portfolio tracking from today)")

# ── 7. Download both files ────────────────────────────────────────
print("\n📦 Downloading files...")
colab_files.download('/content/params.json')
colab_files.download('/content/data/history.json')

print(f"""
{'═'*62}
  ✅ DONE — next steps:
{'═'*62}
1. Upload params.json to your GitHub repo (replace existing)
2. Upload data/history.json to your GitHub repo (replace existing)
3. Also update updater.py (see the fix guide for the new version)
4. Push all changes
5. Trigger the workflow manually to test

  Final params:
    Index        : {idx_label}
    PE Lookback  : {PE_LB} days
    PE Floor     : {PE_FL:.0%}
    PE Ceiling   : {PE_CE:.0%}
    DD Threshold : {DD_TH:.0%}
    MA Lookback  : {MA_LB} days
    Gold MA      : {GOLD_MA_LB} days (FIXED from 20 → 50)
{'═'*62}
""")
```

---

## STEP 4 — Replace `updater.py` on GitHub

This is the full rewritten `updater.py` with T+2 settlement and 50-day Gold MA:

```python
#!/usr/bin/env python3
"""
Pattern Index — Daily Updater (FIXED VERSION)
Fixes:
  - T+2 settlement properly modelled
  - Gold MA uses 50-day (not 20)
  - history.json new format: {lookback_data: [...], live_rows: [...]}
  - Portfolio starts from seeded day, not 2020
"""

import json, os, time, datetime, requests
import numpy as np
from pathlib import Path

# ── Load params ───────────────────────────────────────────────────
with open('params.json') as f:
    P = json.load(f)

PE_LB    = P['pe_lookback']
PE_FL    = P['pe_floor']
PE_CE    = P['pe_ceiling']
DD_TH    = P['dd_threshold']
MA_LB    = P['ma_lookback']
GOLD_MA_LB = P.get('gold_ma_lookback', 50)  # default 50 if old params.json
TC       = 0.001
DEBT_DAILY = 0.065 / 252
INITIAL_CAPITAL = P.get('initial_capital', 100000.0)
NSE_SLUG = P['nse_slug']
INDEX_LABEL = P['index_label']

TODAY = datetime.date.today()
TODAY_STR = str(TODAY)

print(f"\n{'='*55}")
print(f"  Pattern Index Updater — {TODAY_STR} ({INDEX_LABEL})")
print(f"{'='*55}")

# ── Weekend / holiday check ───────────────────────────────────────
if TODAY.weekday() >= 5:
    print(f"Weekend — skipping.")
    exit(0)

# ── Load history.json ─────────────────────────────────────────────
history_path = Path('data/history.json')
if not history_path.exists():
    print("ERROR: data/history.json not found. Re-run Cell 17 in Colab.")
    exit(1)

raw = json.loads(history_path.read_text())

# Support both old format (flat list) and new format (dict with keys)
if isinstance(raw, list):
    # Old flat format — migrate
    print("⚠️  Old flat history.json format detected. Please re-run Cell 17 in Colab.")
    print("    Using legacy mode for now...")
    lookback_data = raw
    live_rows = []
    legacy_mode = True
else:
    lookback_data = raw.get('lookback_data', [])
    live_rows = raw.get('live_rows', [])
    legacy_mode = False

# Check if today already exists
all_dates = [r['date'] for r in lookback_data] + [r['date'] for r in live_rows]
if TODAY_STR in all_dates:
    print(f"Today ({TODAY_STR}) already in history — skipping.")
    exit(0)

print(f"  Lookback rows : {len(lookback_data)}")
print(f"  Live rows     : {len(live_rows)}")
print(f"  Last lookback : {lookback_data[-1]['date'] if lookback_data else 'none'}")
print(f"  Last live     : {live_rows[-1]['date'] if live_rows else 'none'}")

# ── Scrape NSE for today's PE and Price ───────────────────────────
def scrape_nse():
    try:
        session = requests.Session()
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Referer': 'https://www.nseindia.com/',
        })
        session.get('https://www.nseindia.com', timeout=10)
        time.sleep(2)
        url = f'https://www.nseindia.com/api/equity-stockIndices?index={NSE_SLUG}'
        r = session.get(url, timeout=15)
        data = r.json()
        row = data['data'][0]
        price = float(row.get('lastPrice', row.get('last', 0)))
        pe    = float(row.get('pe', row.get('PE', 0)))
        print(f"  ✅ NSE: price={price}, pe={pe}")
        return price, pe
    except Exception as e:
        print(f"  ❌ NSE primary failed: {e}")
        # Fallback
        try:
            session.get('https://www.nseindia.com', timeout=10)
            time.sleep(2)
            r = session.get('https://www.nseindia.com/api/allIndices', timeout=15)
            data = r.json()
            for item in data.get('data', []):
                if INDEX_LABEL.replace(' ', '').upper() in item.get('indexSymbol','').replace(' ','').upper():
                    price = float(item.get('last', item.get('lastPrice', 0)))
                    pe    = float(item.get('pe', item.get('PE', 0)))
                    print(f"  ✅ NSE fallback: price={price}, pe={pe}")
                    return price, pe
        except Exception as e2:
            print(f"  ❌ NSE fallback failed: {e2}")
        return None, None

# ── Scrape Gold NAV ───────────────────────────────────────────────
def scrape_gold_nav():
    try:
        r = requests.get('https://api.mfapi.in/mf/119598', timeout=10)
        data = r.json()
        nav_data = data['data']
        # Get most recent NAV
        nav = float(nav_data[0]['nav'])
        nav_date = nav_data[0]['date']
        print(f"  ✅ Gold NAV: {nav} (date: {nav_date})")
        return nav
    except Exception as e:
        print(f"  ❌ Gold NAV failed: {e}")
        return None

# ── Fetch live data ───────────────────────────────────────────────
price_today, pe_today = scrape_nse()
nav_today = scrape_gold_nav()

if price_today is None or pe_today is None:
    print("FATAL: Could not fetch NSE data. Exiting without update.")
    exit(1)

if nav_today is None:
    print("FATAL: Could not fetch Gold NAV. Exiting without update.")
    exit(1)

# ── Build full price/pe/nav arrays for indicator calculation ──────
# Combine lookback_data with any existing live_rows
all_historical = lookback_data + [r for r in live_rows if r['date'] != TODAY_STR]

prices_arr = np.array([r['price']    for r in all_historical] + [price_today], dtype=np.float64)
pe_arr     = np.array([r['pe']       for r in all_historical] + [pe_today],    dtype=np.float64)
nav_arr    = np.array([r['gold_nav'] for r in all_historical] + [nav_today],   dtype=np.float64)
n = len(prices_arr)
i = n - 1  # today's index

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

# Compute indicators
pe_pct  = roll_pct(pe_arr, i, PE_LB)
p_ma    = sma(prices_arr, i, MA_LB)
g_ma    = sma(nav_arr, i, GOLD_MA_LB)
dd      = roll_dd(prices_arr, i, 252)

# Compute triggers
tc = 0
if pe_pct is not None:
    if pe_pct < PE_FL: tc += 1
    if pe_pct > PE_CE: tc += 1
if dd < -abs(DD_TH): tc += 1
if p_ma is not None and price_today < p_ma: tc += 1

print(f"\n  Indicators:")
print(f"    PE={pe_today}, PE%ile={round(pe_pct*100,1) if pe_pct else 'N/A'}%")
print(f"    Price={price_today}, MA{MA_LB}={round(p_ma,2) if p_ma else 'N/A'}")
print(f"    Gold={nav_today}, GoldMA{GOLD_MA_LB}={round(g_ma,4) if g_ma else 'N/A'}")
print(f"    DrawDown={round(dd*100,2)}%, Triggers={tc}/4")

# ── T+2 Settlement State Machine ─────────────────────────────────
# Get the last live row to know current state
if live_rows:
    last_live = live_rows[-1]
    current_asset       = last_live['asset']
    current_pv          = last_live['portfolio_value']
    current_bv          = last_live['benchmark_value']
    settlement_state    = last_live.get('settlement_state', 'NORMAL')
    pending_target      = last_live.get('pending_target', None)
    pv_units            = current_pv / last_live['price'] if current_asset == 'EQUITY' else None
    gold_units          = current_pv / last_live['gold_nav'] if current_asset == 'GOLD' else None
else:
    # First live row after seed
    current_asset       = 'EQUITY'
    current_pv          = INITIAL_CAPITAL
    current_bv          = INITIAL_CAPITAL
    settlement_state    = 'NORMAL'
    pending_target      = None
    first_live          = live_rows[0] if live_rows else lookback_data[-1]
    pv_units            = current_pv / first_live['price']
    gold_units          = None

# Benchmark: always equity
bv_start_price = lookback_data[-1]['price'] if live_rows == [] else live_rows[0]['price']
bv_start       = INITIAL_CAPITAL
bv_units_bench = bv_start / bv_start_price
current_bv_new = bv_units_bench * price_today

# Update portfolio value mark-to-market
if current_asset == 'EQUITY':
    if pv_units is None and live_rows:
        pv_units = live_rows[-1]['portfolio_value'] / live_rows[-1]['price']
    elif pv_units is None:
        pv_units = INITIAL_CAPITAL / prices_arr[-2]
    new_pv = pv_units * price_today
elif current_asset == 'GOLD':
    if gold_units is None and live_rows:
        gold_units = live_rows[-1]['portfolio_value'] / live_rows[-1]['gold_nav']
    new_pv = gold_units * nav_today
elif current_asset == 'DEBT':
    new_pv = current_pv * (1 + DEBT_DAILY)
elif current_asset == 'CASH':
    new_pv = current_pv  # cash, waiting for T+2
else:
    new_pv = current_pv

# Determine new settlement state
if settlement_state == 'NORMAL':
    # Check if signal fires today
    if tc >= 2 and current_asset == 'EQUITY':
        target = 'GOLD' if (g_ma and nav_today > g_ma) else 'DEBT'
        new_settlement = 'SIGNAL_DAY'
        new_target = target
        signal = f"EXIT EQUITY → {target} (T+2: sell tomorrow)"
        new_asset = current_asset  # still holding today
    elif tc >= 2 and current_asset == 'GOLD' and g_ma and nav_today < g_ma:
        new_settlement = 'SIGNAL_DAY'
        new_target = 'DEBT'
        signal = "GOLD → DEBT (T+2: sell tomorrow)"
        new_asset = current_asset
    elif tc < 2 and current_asset in ('GOLD', 'DEBT'):
        new_settlement = 'SIGNAL_DAY'
        new_target = 'EQUITY'
        signal = f"{current_asset} → EQUITY (T+2: sell tomorrow)"
        new_asset = current_asset
    else:
        new_settlement = 'NORMAL'
        new_target = None
        signal = f"STAY {current_asset}"
        new_asset = current_asset

elif settlement_state == 'SIGNAL_DAY':
    # T+1: sell current asset, go to CASH
    new_pv = new_pv * (1 - TC)  # sell transaction cost
    new_asset = 'CASH'
    new_settlement = 'PENDING_BUY'
    new_target = pending_target
    signal = f"SELLING {current_asset} → CASH (buying {pending_target} tomorrow)"

elif settlement_state == 'PENDING_BUY':
    # T+2: buy target asset
    new_pv = new_pv * (1 - TC)  # buy transaction cost
    new_asset = pending_target
    new_settlement = 'NORMAL'
    new_target = None
    signal = f"BOUGHT {pending_target} ✅"

else:
    new_settlement = 'NORMAL'
    new_target = None
    signal = f"STAY {current_asset}"
    new_asset = current_asset

# Compute drawdowns
all_pv_vals = [r['portfolio_value'] for r in live_rows] + [new_pv]
all_bv_vals = [r['benchmark_value'] for r in live_rows] + [current_bv_new]
pf_dd = round((new_pv - max(all_pv_vals)) / max(all_pv_vals) * 100, 4)
bm_dd = round((current_bv_new - max(all_bv_vals)) / max(all_bv_vals) * 100, 4)

# ── Build today's new live row ────────────────────────────────────
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

# ── Also add today to lookback_data for future indicator calcs ───
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

# ── Write updated history.json ────────────────────────────────────
output = {
    "lookback_data": lookback_data,
    "live_rows"    : live_rows,
}
history_path.write_text(json.dumps(output, indent=2))
print(f"\n✅ history.json updated")
print(f"   Live rows now: {len(live_rows)}")

# ── Send Telegram message ─────────────────────────────────────────
TG_TOKEN  = os.environ.get('TELEGRAM_TOKEN')
TG_CHATID = os.environ.get('TELEGRAM_CHAT_ID')

if TG_TOKEN and TG_CHATID:
    emoji = {'EQUITY':'📈','GOLD':'🥇','DEBT':'🏦','CASH':'💵'}.get(new_asset,'📊')
    msg = (
        f"*Pattern Index — {INDEX_LABEL}*\n"
        f"📅 {TODAY_STR}\n\n"
        f"{emoji} *{signal}*\n\n"
        f"PE: {pe_today} ({round(pe_pct*100,1) if pe_pct else 'N/A'}th %ile)\n"
        f"Price: ₹{price_today:,.2f}  |  MA{MA_LB}: ₹{round(p_ma,2) if p_ma else 'N/A'}\n"
        f"Gold NAV: ₹{nav_today}  |  GoldMA{GOLD_MA_LB}: ₹{round(g_ma,4) if g_ma else 'N/A'}\n"
        f"Triggers: {tc}/4  |  DD: {round(dd*100,2)}%\n\n"
        f"💼 Portfolio: ₹{new_pv:,.0f}\n"
        f"📊 Benchmark: ₹{current_bv_new:,.0f}\n"
        f"Holding: *{new_asset}*"
    )
    if new_settlement != 'NORMAL':
        msg += f"\n⏳ Settlement: {new_settlement}"

    try:
        requests.post(
            f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
            json={'chat_id': TG_CHATID, 'text': msg, 'parse_mode': 'Markdown'},
            timeout=10
        )
        print("✅ Telegram sent")
    except Exception as e:
        print(f"⚠️  Telegram failed: {e}")
else:
    print("⚠️  No Telegram secrets found — skipping")

print(f"\n{'='*55}")
print(f"  Done. Asset: {new_asset} | PV: ₹{new_pv:,.0f} | Signal: {signal}")
print(f"{'='*55}\n")
```

---

## STEP 5 — Replace `dashboard.html` key section on GitHub

In `dashboard.html`, find where it reads `history.json` data and update it to use the new format. The key change is:

**Old:** reads a flat array, plots all rows as portfolio  
**New:** reads `live_rows` for portfolio chart, uses `lookback_data` only for lookback indicators

Find this section in your `dashboard.html` (the fetch/load logic) and change:

```javascript
// OLD — remove this
const history = data;

// NEW — replace with this
const history = data.live_rows || data;  // live_rows for display
const lookbackData = data.lookback_data || data;  // for indicator context
```

And the portfolio chart should only use `history` (live_rows), not the full lookback.

The table at the bottom showing "FULL HISTORY" should also only show `live_rows`.

---

## STEP 6 — Fix `params.json` on GitHub directly

Just edit `params.json` directly on GitHub (click the pencil icon) and change:

```json
{
  "index_label": "MIDCAP 150",
  "nse_slug": "NIFTY%20MIDCAP%20150",
  "pe_lookback": 252,
  "pe_floor": 0.05,
  "pe_ceiling": 0.85,
  "dd_threshold": 0.07,
  "ma_lookback": 20,
  "gold_ma_lookback": 50,
  "initial_capital": 100000.0
}
```

This fixes the "SMALLCAP 250" label immediately without waiting for Colab.

---

## ORDER OF OPERATIONS

```
1. Edit params.json on GitHub directly → fixes label immediately
2. Download new data files (Price, NAV, PE for Jan-Mar 2026)
3. Run Colab cells 1-16 with all data files uploaded
4. Run new Cell 17 → downloads params.json and history.json
5. Upload both files to GitHub (replace existing)
6. Replace updater.py on GitHub with new version above
7. Update dashboard.html to use live_rows
8. Trigger workflow manually → verify green tick
9. Check Railway dashboard
```
