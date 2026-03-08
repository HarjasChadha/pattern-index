# ════════════════════════════════════════════════════════════════════
# Cell 17 — Export to GitHub (Paper Trading Setup)
# ════════════════════════════════════════════════════════════════════
#
# Run this cell ONCE after Cell 16.
# It:
#   1. Writes params.json with all optimised parameters
#   2. Seeds data/history.json with the full historical run
#      so your dashboard has a rich chart from day 1
#   3. Downloads both files for you to push to GitHub
#
# After running this cell, follow the SETUP GUIDE printed below.
# You never need to open Colab again after that.
# ════════════════════════════════════════════════════════════════════

import json, os
from pathlib import Path
from google.colab import files as colab_files

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

# ── 2. Write params.json ──────────────────────────────────────────
params = {
    "index_label"    : idx_label,
    "nse_slug"       : nse_slug,
    "pe_lookback"    : int(FP[0]),
    "pe_floor"       : float(FP[1]),
    "pe_ceiling"     : float(FP[2]),
    "dd_threshold"   : float(FP[3]),
    "ma_lookback"    : int(FP[4]),
    "initial_capital": 100000.0,
}
Path('/content/params.json').write_text(json.dumps(params, indent=2))
print(f"✅ params.json written")
print(json.dumps(params, indent=2))

# ── 3. Seed history.json from the historical sim data ─────────────
#    Uses the full_metrics run from Cell 14 (variable M)
#    M[0] = Optimisation, M[1] = Validation, M[2] = Historical
#    We use ALL three periods merged in date order to seed the chart.

print(f"\n⏳ Seeding history from historical sim data...")

DEBT_DAILY     = 0.065 / 252
INITIAL_CAPITAL= 100000.0
TC             = 0.001

# Rebuild a clean history list from df_master + the sim results
# We use the Optimisation daily log since it has the most recent data
# but we want ALL history — so we replay the sim over the full df_master

import numpy as np

all_prices = df_master['Index_Price'].values.astype(np.float64)
all_pe     = df_master['PE'].values.astype(np.float64)
all_nav    = df_master['NAV'].values.astype(np.float64)
all_dates  = df_master['Date'].values
n          = len(all_prices)

PE_LB = int(FP[0]); PE_FL = float(FP[1]); PE_CE = float(FP[2])
DD_TH = float(FP[3]); MA_LB = int(FP[4])

def sma(arr, idx, lb):
    if idx < lb - 1: return None
    return float(np.mean(arr[idx-lb+1:idx+1]))

def roll_pct(arr, idx, lb):
    if idx < lb: return None
    w = arr[idx-lb:idx+1]
    return float(np.sum(w < arr[idx]) / len(w))

def roll_dd_idx(arr, idx, lb=252):
    start = max(0, idx-lb+1)
    w = arr[start:idx+1]
    peak = np.max(w)
    return float((arr[idx]-peak)/peak) if peak > 0 else 0.0

history = []
pv = INITIAL_CAPITAL
bv = INITIAL_CAPITAL
asset = 'EQUITY'
units = pv / all_prices[0]
bv_units = bv / all_prices[0]
all_pv_vals = [pv]
all_bv_vals = [bv]

for i in range(n):
    p   = all_prices[i]
    nav = all_nav[i]
    pe  = all_pe[i]

    # Indicators
    pe_pct  = roll_pct(all_pe, i, PE_LB)
    p_ma    = sma(all_prices, i, MA_LB)
    g_ma    = sma(all_nav, i, MA_LB)
    dd      = roll_dd_idx(all_prices, i, 252)

    # Triggers
    tc = 0
    if pe_pct is not None:
        if pe_pct < PE_FL: tc += 1
        if pe_pct > PE_CE: tc += 1
    if dd < -abs(DD_TH): tc += 1
    if p_ma is not None and p < p_ma: tc += 1

    # Target asset (T+0 signal, T+1 execute — simplified to same-day here for seeding)
    if asset == 'EQUITY':
        tgt = ('GOLD' if (g_ma and nav > g_ma) else 'DEBT') if tc >= 2 else 'EQUITY'
        signal = f"EXIT EQUITY → {tgt}" if tc >= 2 else "STAY EQUITY"
    elif asset == 'GOLD':
        if g_ma and nav < g_ma and tc >= 2: tgt = 'DEBT'; signal = 'GOLD → DEBT'
        elif tc < 2: tgt = 'EQUITY'; signal = 'GOLD → EQUITY (recovery)'
        else: tgt = 'GOLD'; signal = 'STAY GOLD'
    elif asset == 'DEBT':
        tgt = 'EQUITY' if tc < 2 else 'DEBT'
        signal = 'DEBT → EQUITY (recovery)' if tc < 2 else 'STAY DEBT'
    else:
        tgt = 'EQUITY'; signal = 'DEFAULT'

    # Mark to market
    if asset == 'EQUITY': pv = units * p
    elif asset == 'GOLD':  pv = units * nav
    elif asset == 'DEBT':  pv = pv * (1 + DEBT_DAILY)
    bv = bv_units * p

    if tgt != asset:
        pv *= (1 - TC)
        if tgt == 'EQUITY': units = pv / p
        elif tgt == 'GOLD': units = pv / nav
        else: units = 0

    asset = tgt
    all_pv_vals.append(pv)
    all_bv_vals.append(bv)
    bm_dd_val = round((bv - max(all_bv_vals)) / max(all_bv_vals) * 100, 4) if max(all_bv_vals) > 0 else 0
    pf_dd_val = round((pv - max(all_pv_vals)) / max(all_pv_vals) * 100, 4) if max(all_pv_vals) > 0 else 0

    history.append({
        "date"            : str(pd.Timestamp(all_dates[i]).date()),
        "pe"              : round(float(pe), 2),
        "pe_pct"          : round(pe_pct * 100, 2) if pe_pct else None,
        "price"           : round(float(p), 2),
        "price_ma"        : round(p_ma, 2) if p_ma else None,
        "gold_nav"        : round(float(nav), 4),
        "gold_ma"         : round(g_ma, 4) if g_ma else None,
        "asset"           : asset,
        "triggers"        : tc,
        "benchmark_dd"    : bm_dd_val,
        "portfolio_dd"    : pf_dd_val,
        "portfolio_value" : round(pv, 2),
        "benchmark_value" : round(bv, 2),
        "signal"          : signal,
    })

os.makedirs('/content/data', exist_ok=True)
Path('/content/data/history.json').write_text(json.dumps(history, indent=2))
print(f"✅ data/history.json written — {len(history)} rows seeded")

# ── 4. Download both files ────────────────────────────────────────
print("\n📦 Downloading files...")
colab_files.download('/content/params.json')
colab_files.download('/content/data/history.json')

# ── 5. Print setup guide ──────────────────────────────────────────
print(f"""
{'═'*62}
  🚀  SETUP GUIDE — do this ONCE, never touch again
{'═'*62}

STEP 1 — Create a free GitHub repo
  • Go to github.com → New repository
  • Name it: pattern-index
  • Set it to PUBLIC (required for free Railway deploy)
  • Don't add any files yet

STEP 2 — Upload the repo files
  Download the full project zip from the chat.
  Then either:
  a) Drag & drop all files into the GitHub repo web UI, OR
  b) git clone and push from your terminal

  The file structure must be exactly:
    pattern-index/
    ├── app.py
    ├── updater.py
    ├── requirements.txt
    ├── Procfile
    ├── params.json          ← the file you just downloaded
    ├── data/
    │   └── history.json     ← the file you just downloaded
    ├── templates/
    │   └── dashboard.html
    └── .github/
        └── workflows/
            └── daily_update.yml

STEP 3 — Add GitHub Secrets (for Telegram)
  In your GitHub repo → Settings → Secrets → Actions:
  Add these 2 secrets:
    TELEGRAM_TOKEN     = (your bot token from @BotFather)
    TELEGRAM_CHAT_ID   = (your chat ID from @userinfobot)

  To create the Telegram bot:
    1. Open Telegram, search @BotFather
    2. Send: /newbot  → follow prompts → copy the token
    3. Search @userinfobot → send any message → copy your ID

STEP 4 — Deploy dashboard on Railway (free)
  • Go to railway.app → New Project → Deploy from GitHub repo
  • Select your pattern-index repo
  • Railway auto-detects the Procfile and deploys
  • Click the generated URL — your dashboard is live!

STEP 5 — Done
  GitHub Actions runs updater.py every weekday at 3:35 PM IST.
  It commits the new row to history.json.
  Railway serves the dashboard from that file.
  Telegram sends you a message.
  You do nothing.

  Dashboard URL: your-app.up.railway.app
  Final params:
    Index        : {idx_label}
    PE Lookback  : {int(FP[0])} days
    PE Floor     : {float(FP[1]):.0%}
    PE Ceiling   : {float(FP[2]):.0%}
    DD Threshold : {float(FP[3]):.0%}
    MA Lookback  : {int(FP[4])} days
{'═'*62}
""")
