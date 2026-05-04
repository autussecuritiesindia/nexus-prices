from flask import Flask, request, jsonify
from flask_cors import CORS
import yfinance as yf
import pandas as pd
from pandas_datareader import data as pdr
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)

INDICES_MAP = {
    '^nsei':'^NSEI','^bsesn':'^BSESN','^nsebank':'^NSEBANK','^cnxit':'^CNXIT',
    '^cnxpharma':'^CNXPHARMA','^cnxauto':'^CNXAUTO','^cnxfmcg':'^CNXFMCG',
    '^cnxmetal':'^CNXMETAL','^cnxpsubn':'^CNXPSUBANK','^cnxsc':'^CNXSC',
    '^cnxmidcap':'NIFTY_MIDCAP_100.NS','^indiavix':'^INDIAVIX',
    '^spx':'^GSPC','^ndx':'^NDX','^dji':'^DJI','^n225':'^N225','^hsi':'^HSI',
    '^dax':'^GDAXI','^ftse':'^FTSE','^ssec':'000001.SS','^fchi':'^FCHI',
    'usd/inr':'USDINR=X','eur/inr':'EURINR=X','gbp/inr':'GBPINR=X',
    'xau/usd':'GC=F','xag/usd':'SI=F','cl.f':'CL=F','btc/usd':'BTC-USD',
}
SYMBOL_FIXES = {'GVT&D':'GETD.NS','GET&D':'GETD.NS','GVT&D.NS':'GETD.NS','GET&D.NS':'GETD.NS'}

def safe_float(v):
    try:
        f = float(v)
        return round(f, 4) if f == f else None
    except Exception:
        return None

def fetch_yf_download(yahoo_sym):
    try:
        end = datetime.utcnow() + timedelta(days=1)
        start = end - timedelta(days=7)
        df = yf.download(yahoo_sym, start=start, end=end, progress=False,
                         auto_adjust=False, threads=False)
        if df is None or df.empty or 'Close' not in df.columns:
            return None
        closes = df['Close'].dropna()
        if closes.empty:
            return None
        price = float(closes.iloc[-1])
        prev = float(closes.iloc[-2]) if len(closes) > 1 else price
        if price <= 0:
            return None
        return {
            'price': round(price, 4),
            'prevClose': round(prev, 4),
            'changeAbs': round(price - prev, 4),
            'changePct': round((price - prev) / prev * 100, 4) if prev > 0 else 0,
        }
    except Exception as e:
        print(f'[yf.download WARN] {yahoo_sym}: {e}')
        return None

def fetch_yf_fastinfo(yahoo_sym):
    try:
        t = yf.Ticker(yahoo_sym)
        info = t.fast_info
        price = safe_float(info.last_price)
        prev = safe_float(info.previous_close)
        if not price or price <= 0:
            return None
        base = prev if prev and prev > 0 else price
        return {
            'price': price,
            'prevClose': base,
            'changeAbs': round(price - base, 4),
            'changePct': round((price - base) / base * 100, 4) if base > 0 else 0,
        }
    except Exception as e:
        print(f'[fast_info WARN] {yahoo_sym}: {e}')
        return None

def stooq_symbol(sym, market):
    s = sym.lower()
    if market == 'us':
        base = s.split('.')[0]
        return f'{base}.us'
    if s.endswith('.ns') or s.endswith('.bo'):
        return s.replace('.ns', '.in').replace('.bo', '.in')
    if s.startswith('^'):
        return None
    return s

def fetch_stooq(sym, market):
    stooq_sym = stooq_symbol(sym, market)
    if not stooq_sym:
        return None
    try:
        end = datetime.utcnow()
        start = end - timedelta(days=10)
        df = pdr.DataReader(stooq_sym, 'stooq', start, end)
        if df is None or df.empty:
            return None
        df = df.sort_index()
        price = float(df['Close'].iloc[-1])
        prev = float(df['Close'].iloc[-2]) if len(df) > 1 else price
        if price <= 0:
            return None
        return {
            'price': round(price, 4),
            'prevClose': round(prev, 4),
            'changeAbs': round(price - prev, 4),
            'changePct': round((price - prev) / prev * 100, 4) if prev > 0 else 0,
        }
    except Exception as e:
        print(f'[stooq WARN] {stooq_sym}: {e}')
        return None

def fetch_info(sym, yahoo_sym, market=''):
    for fn in (fetch_yf_download, fetch_yf_fastinfo):
        r = fn(yahoo_sym)
        if r:
            return r, 'yfinance'
    r = fetch_stooq(sym, market)
    if r:
        return r, 'stooq'
    return None, None

@app.route('/')
def root():
    return jsonify({'ok': True, 'service': 'nexus-prices', 'endpoints': ['/health','/prices?s=SYM&market=us','/indices?s=^spx']})

@app.route('/health')
def health():
    return jsonify({'ok': True, 'service': 'nexus-prices', 'version': 1})

@app.route('/indices')
def indices():
    p = request.args.get('s','').strip()
    if not p: return jsonify({'ok': False, 'error': 'Missing s='}), 400
    requested = [s.strip().lower() for s in p.split(',') if s.strip()]
    data = []
    for req in requested:
        ysym = INDICES_MAP.get(req)
        if not ysym: continue
        r, src = fetch_info(req, ysym, '')
        if r:
            data.append({'sym':req,'val':r['price'],'chg':r['changeAbs'],
                         'pct':r['changePct'],'prevClose':r['prevClose'],'source':src})
    if not data: return jsonify({'ok': False, 'error': 'No data'})
    return jsonify({'ok': True, 'count': len(data), 'data': data})

@app.route('/prices')
def prices():
    p = request.args.get('s','').strip()
    market = request.args.get('market','').lower()
    if not p: return jsonify({'ok': False, 'error': 'Missing s='}), 400
    symbols = [s.strip() for s in p.split(',') if s.strip()]
    data = []
    for sym in symbols:
        fixed = SYMBOL_FIXES.get(sym, sym)
        if market == 'us':
            yahoo_sym = fixed
        elif '.' not in fixed and '=' not in fixed and not fixed.startswith('^'):
            yahoo_sym = fixed + '.NS'
        else:
            yahoo_sym = fixed
        r, src = fetch_info(sym, yahoo_sym, market)
        if not r and market != 'us':
            r2, src2 = fetch_info(sym, yahoo_sym.replace('.NS','.BO'), market)
            if r2: r, src = r2, src2
        if r:
            data.append({'symbol':sym,'yahoo':yahoo_sym,'price':r['price'],
                         'prevClose':r['prevClose'],'changeAbs':r['changeAbs'],
                         'changePct':r['changePct'],'source':src})
    if not data: return jsonify({'ok': False, 'error': 'No data from any source'})
    return jsonify({'ok': True, 'count': len(data), 'data': data})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
