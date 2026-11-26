#!/usr/bin/env python3
"""
Pattern Index — Daily Updater  v3.1  (ETF Edition)
Runs via GitHub Actions after market close (weekdays ~3:50 PM IST = 10:20 UTC)

Data sources:
  - ETF prices (MIDCAPIETF/IICP, GOLDBEES, EBBETF0431) : yfinance + Yahoo chart meta fallback
  - Midcap 150 Index price                            : yfinance / Yahoo chart meta / Screener.in
  - Midcap 150 Index PE                               : Screener.in
"""

import datetime
import json
import math
import os
from pathlib import Path

import numpy as np
import pytz
import requests

IST = pytz.timezone('Asia/Kolkata')
TC = 0.001
USER_AGENT = 'Mozilla/5.0'


def is_valid_price(val):
    if val is None or isinstance(val, bool):
        return False
    try:
        f = float(val)
    except (TypeError, ValueError):
        return False
    return math.isfinite(f) and f > 0


def sanitize_json(obj):
    if isinstance(obj, dict):
        return {k: sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_json(v) for v in obj]
    if isinstance(obj, (float, np.floating)):
        f = float(obj)
        return f if math.isfinite(f) else None
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


def _fetch_yahoo_chart_price(ticker, target_date=None):
    """Fetch finite close/regularMarketPrice from Yahoo Finance chart API."""
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=5d&interval=1d'
    r = requests.get(url, headers={'User-Agent': USER_AGENT}, timeout=15)
    r.raise_for_status()
    payload = r.json()
    results = (payload.get('chart') or {}).get('result') or []
    if not results:
        return None, None
    res = results[0]
    meta = res.get('meta') or {}
    timestamps = res.get('timestamp') or []
    quotes = ((res.get('indicators') or {}).get('quote') or [{}])[0]
    closes = quotes.get('close') or []

    by_date = {}
    for ts, close in zip(timestamps, closes):
        if is_valid_price(close):
            dt_str = datetime.datetime.fromtimestamp(ts, IST).strftime('%Y-%m-%d')
            by_date[dt_str] = float(close)

    # Yahoo often emits close=None for today's unfinalized bar while meta.regularMarketPrice is current
    rmp = meta.get('regularMarketPrice')
    rmt = meta.get('regularMarketTime')
    if is_valid_price(rmp) and rmt is not None:
        meta_date = datetime.datetime.fromtimestamp(rmt, IST).strftime('%Y-%m-%d')
        by_date.setdefault(meta_date, float(rmp))

    if not by_date:
        return None, None
    if target_date is not None:
        if target_date in by_date:
            return by_date[target_date], target_date
        return None, None
    latest_date = max(by_date)
    return by_date[latest_date], latest_date


def _extract_yf_latest(hist, target_date=None):
    if hist is None or hist.empty or 'Close' not in hist:
        return None, None
    idx = hist.index
    if idx.tz is None:
        idx = idx.tz_localize('UTC')
    idx = idx.tz_convert(IST)

    by_date = {}
    for ts, close in zip(idx, hist['Close']):
        if is_valid_price(close):
            by_date[str(ts.date())] = float(close)

    if not by_date:
        return None, None
    if target_date is not None:
        if target_date in by_date:
            return by_date[target_date], target_date
        return None, None
    latest_date = max(by_date)
    return by_date[latest_date], latest_date


def fetch_etf_price(ticker):
    price, date_str = None, None
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        hist = t.history(period='5d')
        price, date_str = _extract_yf_latest(hist)
    except Exception as e:
        print(f"  ⚠  {ticker} yfinance history: {e}")

    # Also check Yahoo chart endpoint (catches today's meta price when daily close bar is NaN)
    try:
        c_price, c_date = _fetch_yahoo_chart_price(ticker)
        if is_valid_price(c_price) and (date_str is None or (c_date and c_date > date_str)):
            price, date_str = c_price, c_date
    except Exception as e:
        if price is None:
            print(f"  ❌ {ticker}: {e}")

    if is_valid_price(price) and date_str:
        print(f"  ✅ {ticker}: {price:.4f}  ({date_str})")
        return float(price), date_str

    print(f"  ⚠  {ticker}: no valid price")
    return None, None


def _fetch_screener_ratios():
    from bs4 import BeautifulSoup
    r = requests.get(
        'https://www.screener.in/company/NMIDCAP150/',
        headers={'User-Agent': USER_AGENT},
        timeout=15,
    )
    r.raise_for_status()
    return BeautifulSoup(r.text, 'html.parser')


def fetch_index_price(target_date=None):
    stale_candidate = None
    for ticker in ['^NIFTYMIDCAP150', 'NIFTYMIDCAP150.NS']:
        try:
            import yfinance as yf
            hist = yf.Ticker(ticker).history(period='5d')
            p, d = _extract_yf_latest(hist, target_date=target_date)
            if is_valid_price(p):
                print(f"  ✅ Index ({ticker}): {p:.2f}  ({d})")
                return float(p)
            if stale_candidate is None:
                sp, sd = _extract_yf_latest(hist)
                if is_valid_price(sp):
                    stale_candidate = (sp, sd, ticker)
        except Exception:
            pass

        try:
            cp, cd = _fetch_yahoo_chart_price(ticker, target_date=target_date)
            if is_valid_price(cp):
                print(f"  ✅ Index ({ticker} chart): {cp:.2f}  ({cd})")
                return float(cp)
            if stale_candidate is None:
                sp, sd = _fetch_yahoo_chart_price(ticker)
                if is_valid_price(sp):
                    stale_candidate = (sp, sd, ticker)
        except Exception:
            pass

    # Screener fallback (also used when Yahoo index daily bar lags behind target_date)
    try:
        soup = _fetch_screener_ratios()
        for li in soup.select('ul#top-ratios li, ul.company-ratios li'):
            name = li.find('span', class_='name')
            num = li.find('span', class_='number')
            if name and num and 'current price' in name.get_text(strip=True).lower():
                price = float(num.get_text(strip=True).replace(',', '').replace('₹', ''))
                if is_valid_price(price):
                    print(f"  ✅ Index (Screener): {price:.2f}")
                    return price
    except Exception as e:
        print(f"  ❌ Index Screener fallback: {e}")

    if stale_candidate is not None and target_date is None:
        sp, sd, ticker = stale_candidate
        print(f"  ⚠  Index ({ticker} fallback): {sp:.2f}  ({sd})")
        return float(sp)

    return None


def fetch_pe():
    try:
        soup = _fetch_screener_ratios()
        for li in soup.select('ul#top-ratios li, ul.company-ratios li'):
            name = li.find('span', class_='name')
            num = li.find('span', class_='number')
            if not name or not num:
                continue
            label = name.get_text(strip=True).lower()
            if label in ('p/e', 'pe', 'stock p/e', 'price to earning'):
                pe = float(num.get_text(strip=True).replace(',', ''))
                if is_valid_price(pe):
                    print(f"  ✅ PE (Screener): {pe}")
                    return pe
        # Wider fallback
        for li in soup.select('li'):
            txt = li.get_text(separator=' ', strip=True).lower()
            if 'p/e' in txt or 'price to earning' in txt:
                for t in li.find_all(['span', 'strong', 'b']):
                    try:
                        v = float(t.get_text(strip=True).replace(',', ''))
                        if 5 < v < 200 and math.isfinite(v):
                            print(f"  ✅ PE (fallback): {v}")
                            return v
                    except ValueError:
                        pass
        print("  ❌ PE not found on Screener")
        return None
    except Exception as e:
        print(f"  ❌ Screener PE: {e}")
        return None


def _finite_arr(arr):
    a = np.asarray(arr, dtype=np.float64)
    return a[np.isfinite(a)]


def sma(arr, idx, lb):
    if idx < lb - 1:
        return None
    w = _finite_arr(arr[idx - lb + 1 : idx + 1])
    if len(w) < lb:
        return None
    return float(np.mean(w))


def roll_pct(arr, idx, lb):
    if idx < lb:
        return None
    cur = float(arr[idx])
    if not math.isfinite(cur):
        return None
    w = _finite_arr(arr[idx - lb : idx + 1])
    if len(w) <= lb // 2:
        return None
    return float(np.sum(w < cur) / len(w))


def roll_dd(arr, idx, lb=252):
    cur = float(arr[idx])
    if not math.isfinite(cur):
        return 0.0
    start = max(0, idx - lb + 1)
    w = _finite_arr(arr[start : idx + 1])
    if len(w) == 0:
        return 0.0
    peak = float(np.max(w))
    return float((cur - peak) / peak) if peak > 0 else 0.0


def etf_price_for(asset, iicp_price, gold_price, debt_price):
    return {'EQUITY': iicp_price, 'GOLD': gold_price, 'DEBT': debt_price}.get(asset)


def prev_etf_price(row, asset):
    return {
        'EQUITY': row.get('iicp_price', row.get('price')),
        'GOLD': row.get('gold_price', row.get('gold_nav')),
        'DEBT': row.get('debt_price'),
    }.get(asset)


def is_seed_row(row, initial_capital):
    pv = row.get('portfolio_value')
    bv = row.get('benchmark_value')
    if not is_valid_price(pv) or not is_valid_price(bv):
        return False
    return abs(pv - initial_capital) < 0.01 and abs(bv - initial_capital) < 0.01


def dedupe_history_rows(lookback_data, live_rows, exclude_date=None):
    merged = {}
    for r in lookback_data:
        dt = r.get('date')
        if dt and dt != exclude_date:
            merged[dt] = r
    for r in live_rows:
        dt = r.get('date')
        if dt and dt != exclude_date:
            merged[dt] = r
    return [merged[dt] for dt in sorted(merged)]


def derive_iicp_fallback(lookback_data, index_price):
    if not is_valid_price(index_price):
        return None
    for row in reversed(lookback_data):
        iicp_v = row.get('iicp_price')
        idx_v = row.get('index_price')
        if is_valid_price(iicp_v) and is_valid_price(idx_v):
            ratio = float(iicp_v) / float(idx_v)
            val = round(float(index_price) * ratio, 4)
            print(f"  ℹ  IICP derived from index ratio ({ratio:.6f}): {val}")
            return val
    val = round(float(index_price) * 0.001036, 4)
    print(f"  ℹ  IICP derived from hardcoded ratio (0.001036): {val}")
    return val


def process_update(raw, params, market_data):
    """Pure state-machine + indicator update given validated market_data dict.

    Returns (updated_history_dict, summary_dict) or (None, skip_reason_dict).
    """
    pe_lb = params['pe_lookback']
    pe_fl = params['pe_floor']
    pe_ce = params['pe_ceiling']
    dd_th = params['dd_threshold']
    ma_lb = params['ma_lookback']
    gold_ma_lb = params.get('gold_ma_lookback', 50)
    initial_capital = params.get('initial_capital', 100000.0)

    trade_date = market_data['date']
    iicp_price = market_data['iicp_price']
    gold_price = market_data['gold_price']
    debt_price = market_data['debt_price']
    index_price = market_data['index_price']
    pe_today = market_data['pe']

    for name, val in [
        ('IICP', iicp_price),
        ('GOLDBEES', gold_price),
        ('EBBETF', debt_price),
        ('Index price', index_price),
        ('PE', pe_today),
    ]:
        if not is_valid_price(val):
            raise ValueError(f"Invalid or missing {name}: {val!r}")

    lookback_data = list(raw.get('lookback_data', []))
    live_rows = list(raw.get('live_rows', []))

    existing_today = [r for r in live_rows if r.get('date') == trade_date]
    if existing_today:
        if is_seed_row(existing_today[0], initial_capital):
            print(f"Today ({trade_date}) is a seed row — overwriting with live data.")
            live_rows = [r for r in live_rows if r.get('date') != trade_date]
        else:
            return None, {'skipped': True, 'reason': f'Today ({trade_date}) already has live data'}

    # Stale/holiday data guard (compare rounded values to avoid float precision mismatch)
    if live_rows:
        last_live = live_rows[-1]
        if (
            last_live.get('date') != trade_date
            and is_valid_price(last_live.get('iicp_price'))
            and is_valid_price(last_live.get('gold_price'))
            and is_valid_price(last_live.get('debt_price'))
            and round(iicp_price, 4) == round(last_live['iicp_price'], 4)
            and round(gold_price, 4) == round(last_live['gold_price'], 4)
            and round(debt_price, 4) == round(last_live['debt_price'], 4)
        ):
            return None, {
                'skipped': True,
                'reason': f"STALE: all ETF prices match {last_live['date']}",
            }

    all_rows = dedupe_history_rows(lookback_data, live_rows, exclude_date=trade_date)
    idx_arr = np.array(
        [r.get('index_price', r.get('price')) for r in all_rows] + [index_price],
        dtype=np.float64,
    )
    pe_arr = np.array([r.get('pe') for r in all_rows] + [pe_today], dtype=np.float64)
    gold_arr = np.array(
        [r.get('gold_price', r.get('gold_nav')) for r in all_rows] + [gold_price],
        dtype=np.float64,
    )
    i = len(idx_arr) - 1

    pe_pct = roll_pct(pe_arr, i, pe_lb)
    p_ma = sma(idx_arr, i, ma_lb)
    g_ma = sma(gold_arr, i, gold_ma_lb)
    dd = roll_dd(idx_arr, i, 252)

    t_pe_floor = (pe_pct is not None) and (pe_pct < pe_fl)
    t_pe_ceiling = (pe_pct is not None) and (pe_pct > pe_ce)
    t_dd = dd < -abs(dd_th)
    t_ma = (p_ma is not None) and (index_price < p_ma)
    tc = sum([t_pe_floor, t_pe_ceiling, t_dd, t_ma])

    if live_rows:
        last_live = live_rows[-1]
        current_asset = last_live['asset']
        current_pv = last_live['portfolio_value']
        if not is_valid_price(current_pv):
            raise ValueError(
                f"Corrupted previous portfolio_value on {last_live.get('date')}: {current_pv!r}"
            )
        settlement_state = last_live.get('settlement_state', 'NORMAL')
        pending_target = last_live.get('pending_target', None)
    else:
        current_asset = 'EQUITY'
        current_pv = initial_capital
        settlement_state = 'NORMAL'
        pending_target = None

    if live_rows and current_asset != 'CASH':
        prev = live_rows[-1]
        prev_p = prev_etf_price(prev, current_asset)
        cur_p = etf_price_for(current_asset, iicp_price, gold_price, debt_price)
        if is_valid_price(prev_p) and is_valid_price(cur_p):
            new_pv = float(prev['portfolio_value']) / float(prev_p) * float(cur_p)
        else:
            new_pv = float(current_pv)
    elif current_asset == 'CASH':
        new_pv = float(current_pv)
    else:
        new_pv = float(initial_capital)

    if live_rows:
        bv0 = live_rows[0]['benchmark_value']
        bv0_p = prev_etf_price(live_rows[0], 'EQUITY')
        if not is_valid_price(bv0_p):
            bv0_p = iicp_price
        new_bv = float(bv0) / float(bv0_p) * float(iicp_price)
    else:
        new_bv = float(initial_capital)

    if settlement_state == 'NORMAL':
        if tc >= 2 and current_asset == 'EQUITY':
            target = 'GOLD' if (g_ma is not None and gold_price > g_ma) else 'DEBT'
            new_settlement, new_target = 'SIGNAL_DAY', target
            signal, new_asset = f"EXIT EQUITY → {target}", current_asset
        elif tc >= 2 and current_asset == 'GOLD' and g_ma is not None and gold_price < g_ma:
            new_settlement, new_target = 'SIGNAL_DAY', 'DEBT'
            signal, new_asset = 'GOLD → DEBT', current_asset
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

    all_pv = [r['portfolio_value'] for r in live_rows if is_valid_price(r.get('portfolio_value'))] + [new_pv]
    all_bv = [r['benchmark_value'] for r in live_rows if is_valid_price(r.get('benchmark_value'))] + [new_bv]
    max_pv = max(all_pv)
    max_bv = max(all_bv)
    pf_dd = round((new_pv - max_pv) / max_pv * 100, 4) if max_pv > 0 else 0.0
    bm_dd = round((new_bv - max_bv) / max_bv * 100, 4) if max_bv > 0 else 0.0

    new_live_row = {
        'date': trade_date,
        'pe': round(float(pe_today), 2),
        'pe_pct': round(pe_pct * 100, 2) if pe_pct is not None else None,
        'index_price': round(float(index_price), 2),
        'price_ma': round(p_ma, 2) if p_ma is not None else None,
        'iicp_price': round(float(iicp_price), 4),
        'gold_price': round(float(gold_price), 4),
        'debt_price': round(float(debt_price), 4),
        'gold_ma': round(g_ma, 4) if g_ma is not None else None,
        'asset': new_asset,
        'triggers': tc,
        't_pe_floor': t_pe_floor,
        't_pe_ceiling': t_pe_ceiling,
        't_dd': t_dd,
        't_ma': t_ma,
        'signal': signal,
        'settlement_state': new_settlement,
        'pending_target': new_target,
        'portfolio_value': round(new_pv, 2),
        'benchmark_value': round(new_bv, 2),
        'benchmark_dd': bm_dd,
        'portfolio_dd': pf_dd,
        'is_live': True,
    }
    live_rows.append(new_live_row)

    lookback_data = [r for r in lookback_data if r.get('date') != trade_date]
    lookback_data.append({
        'date': trade_date,
        'pe': round(float(pe_today), 2),
        'pe_pct': round(pe_pct * 100, 2) if pe_pct is not None else None,
        'index_price': round(float(index_price), 2),
        'price_ma': round(p_ma, 2) if p_ma is not None else None,
        'iicp_price': round(float(iicp_price), 4),
        'gold_price': round(float(gold_price), 4),
        'debt_price': round(float(debt_price), 4),
        'gold_ma': round(g_ma, 4) if g_ma is not None else None,
        'triggers': tc,
    })

    updated = sanitize_json({'lookback_data': lookback_data, 'live_rows': live_rows})
    summary = {
        'skipped': False,
        'date': trade_date,
        'pe_pct': pe_pct,
        'p_ma': p_ma,
        'g_ma': g_ma,
        'dd': dd,
        'tc': tc,
        't_pe_floor': t_pe_floor,
        't_pe_ceiling': t_pe_ceiling,
        't_dd': t_dd,
        't_ma': t_ma,
        'signal': signal,
        'new_asset': new_asset,
        'new_pv': new_pv,
        'new_bv': new_bv,
        'new_settlement': new_settlement,
        'live_count': len(live_rows),
    }
    return updated, summary


def main():
    with open('params.json') as f:
        P = json.load(f)

    index_label = P.get('index_label', 'MIDCAP 150')
    equity_ticker = P.get('equity_etf', 'IICP') + '.NS'
    gold_ticker = P.get('gold_etf', 'GOLDBEES') + '.NS'
    debt_ticker = P.get('debt_etf', 'EBBETF0431') + '.NS'

    today_ist = datetime.datetime.now(IST).date()
    print(f"\n{'='*58}")
    print(f"  Pattern Index Updater v3.1 — {today_ist}")
    print(f"  {index_label} | ETF tracking mode")
    print(f"{'='*58}")

    history_path = Path('data/history.json')
    if not history_path.exists():
        print("ERROR: data/history.json not found.")
        return 1

    raw = json.loads(history_path.read_text())
    if isinstance(raw, list):
        print("ERROR: Old flat history.json format. Re-run Cell 17 in Colab.")
        return 1

    lookback_data = raw.get('lookback_data', [])
    live_rows = raw.get('live_rows', [])
    print(f"  Lookback rows : {len(lookback_data)}")
    print(f"  Live rows     : {len(live_rows)}")

    print("\n  Fetching market data...")
    iicp_price, iicp_date = fetch_etf_price(equity_ticker)
    gold_price, gold_date = fetch_etf_price(gold_ticker)
    debt_price, debt_date = fetch_etf_price(debt_ticker)

    etf_dates = [d for d in (iicp_date, gold_date, debt_date) if d]
    trade_date = max(etf_dates) if etf_dates else str(today_ist)

    index_price = fetch_index_price(target_date=trade_date)
    pe_today = fetch_pe()

    if iicp_price is None and index_price is not None:
        iicp_price = derive_iicp_fallback(lookback_data, index_price)
        iicp_date = trade_date

    missing = [
        name
        for name, val in [
            ('IICP', iicp_price),
            ('GOLDBEES', gold_price),
            ('EBBETF', debt_price),
            ('Index price', index_price),
            ('PE', pe_today),
        ]
        if not is_valid_price(val)
    ]
    if missing:
        print(f"\nFATAL: Missing or invalid values: {missing}")
        return 1

    # Ensure all ETF bars belong to the same market session
    if any(d != trade_date for d in (iicp_date, gold_date, debt_date)):
        print(
            f"\nFATAL: ETF date mismatch for session {trade_date}: "
            f"IICP={iicp_date}, GOLDBEES={gold_date}, EBBETF={debt_date}"
        )
        return 1

    updated, summary = process_update(
        raw,
        P,
        {
            'date': trade_date,
            'iicp_price': iicp_price,
            'gold_price': gold_price,
            'debt_price': debt_price,
            'index_price': index_price,
            'pe': pe_today,
        },
    )

    if updated is None:
        print(f"\n{summary['reason']} — skipping.")
        return 0

    ma_lb = P['ma_lookback']
    gold_ma_lb = P.get('gold_ma_lookback', 50)
    pe_pct = summary['pe_pct']
    p_ma = summary['p_ma']
    g_ma = summary['g_ma']

    print("\n  Indicators:")
    print(f"    Date: {trade_date}")
    print(f"    Index: {index_price:.2f} | MA{ma_lb}: {round(p_ma, 2) if p_ma is not None else 'N/A'}")
    print(f"    PE: {pe_today} | PE%ile: {round(pe_pct * 100, 1) if pe_pct is not None else 'N/A'}%")
    print(f"    IICP: {iicp_price:.4f} | GOLDBEES: {gold_price:.4f} | EBBETF: {debt_price:.4f}")
    print(
        f"    Gold MA{gold_ma_lb}: {round(g_ma, 4) if g_ma is not None else 'N/A'} "
        f"| DD: {round(summary['dd'] * 100, 2)}%"
    )
    print(
        f"    Triggers: {summary['tc']}/4  "
        f"[floor={summary['t_pe_floor']}, ceil={summary['t_pe_ceiling']}, "
        f"dd={summary['t_dd']}, ma={summary['t_ma']}]"
    )
    print(f"\n  Signal: {summary['signal']}")
    print(
        f"  Asset: {summary['new_asset']} | "
        f"Portfolio: ₹{summary['new_pv']:,.2f} | Benchmark: ₹{summary['new_bv']:,.2f}"
    )

    # Strictly disallow NaN/Infinity when serializing JSON
    history_path.write_text(json.dumps(updated, indent=2, allow_nan=False))
    print(f"\n  ✅ history.json updated — live rows: {summary['live_count']}")

    tg_token = os.environ.get('TELEGRAM_TOKEN')
    tg_chatid = os.environ.get('TELEGRAM_CHAT_ID')
    if tg_token and tg_chatid:
        emoji = {'EQUITY': '📈', 'GOLD': '🥇', 'DEBT': '🏦', 'CASH': '💵'}.get(
            summary['new_asset'], '—'
        )
        msg = (
            f"*Pattern Index — {index_label}*\n"
            f"Date: {trade_date}\n\n"
            f"{emoji} *{summary['signal']}*\n\n"
            f"PE: {pe_today} ({round(pe_pct * 100, 1) if pe_pct is not None else 'N/A'}th %ile)\n"
            f"Index: {index_price:.0f} | MA{ma_lb}: {round(p_ma, 0) if p_ma is not None else 'N/A'}\n"
            f"IICP: {iicp_price:.2f} | GOLDBEES: {gold_price:.2f} | EBBETF: {debt_price:.2f}\n"
            f"Triggers: {summary['tc']}/4 | DD: {round(summary['dd'] * 100, 2)}%\n\n"
            f"Portfolio: ₹{summary['new_pv']:,.0f} | Benchmark: ₹{summary['new_bv']:,.0f}\n"
            f"Holding: *{summary['new_asset']}*"
        )
        if summary['new_settlement'] != 'NORMAL':
            msg += f"\nSettlement: {summary['new_settlement']}"
        try:
            requests.post(
                f'https://api.telegram.org/bot{tg_token}/sendMessage',
                json={'chat_id': tg_chatid, 'text': msg, 'parse_mode': 'Markdown'},
                timeout=10,
            )
            print("  ✅ Telegram sent")
        except Exception as e:
            print(f"  ❌ Telegram: {e}")
    else:
        print("  No Telegram secrets — skipping")

    print(f"\n{'='*58}")
    print(f"  Done. Asset: {summary['new_asset']} | {summary['signal']}")
    print(f"{'='*58}\n")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
