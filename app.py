import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import requests

# ==========================================
# --- 1. KONFIGURASI & SETUP ---
# ==========================================
st.set_page_config(layout="wide", page_title="Indodax Pro V8.5")

# --- TELEGRAM SETTINGS ---
def send_telegram(message):
    # GANTI TOKEN DAN CHAT ID ANDA
    BOT_TOKEN = "TOKEN_BOT_ANDA_DISINI"
    CHAT_ID = "CHAT_ID_ANDA_DISINI"
    
    if "TOKEN_BOT" in BOT_TOKEN: return 
        
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    params = {'chat_id': CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    try:
        requests.get(url, params=params, timeout=3)
    except: pass

# ==========================================
# --- 2. DATA ENGINE ---
# ==========================================
def get_data(symbol, tf):
    exchange = ccxt.indodax()
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, tf, limit=500)
        if not ohlcv: return pd.DataFrame(), None
        
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize('UTC').dt.tz_convert('Asia/Jakarta')
        
        ticker = exchange.fetch_ticker(symbol)
        return df, ticker
    except Exception as e:
        st.error(f"Data Error: {e}")
        return pd.DataFrame(), None

def get_orderbook_analysis(symbol):
    try:
        exchange = ccxt.indodax()
        ob = exchange.fetch_order_book(symbol, limit=50) # Deep scan 50
        
        bids = pd.DataFrame(ob['bids'], columns=['price', 'volume'])
        max_bid = bids.loc[bids['volume'].idxmax()]
        
        asks = pd.DataFrame(ob['asks'], columns=['price', 'volume'])
        max_ask = asks.loc[asks['volume'].idxmax()]
        
        return {
            'buy_wall_price': max_bid['price'], 'buy_wall_vol': max_bid['volume'],
            'sell_wall_price': max_ask['price'], 'sell_wall_vol': max_ask['volume'],
            'bids_df': bids.head(10), 'asks_df': asks.head(10)
        }
    except: return None

# ==========================================
# --- 3. INDIKATOR (SUPERTREND FIXED) ---
# ==========================================
def process_indicators(df):
    if df.empty: return df
    
    # Standard Indicators
    df['EMA_200'] = df['close'].ewm(span=200, adjust=False).mean()
    df['MACD'] = df['close'].ewm(span=12).mean() - df['close'].ewm(span=26).mean()
    df['Signal'] = df['MACD'].ewm(span=9).mean()
    df['Hist'] = df['MACD'] - df['Signal']
    
    # ATR & Volatility
    df['tr'] = np.maximum(df['high'] - df['low'], 
               np.maximum(abs(df['high'] - df['close'].shift()), abs(df['low'] - df['close'].shift())))
    df['ATR'] = df['tr'].ewm(span=14).mean()
    
    # --- FIX: ISI DATA KOSONG AGAR SUPERTREND MUNCUL ---
    df['ATR'] = df['ATR'].bfill() 
    
    # Volume & Candles
    df['Vol_MA'] = df['volume'].rolling(20).mean()
    df['Vol_Spike'] = df['volume'] > (df['Vol_MA'] * 1.5)
    
    df['Bull_Engulf'] = (df['close'] > df['open']) & (df['close'] > df['open'].shift(1)) & (df['open'] < df['close'].shift(1))
    df['Bear_Engulf'] = (df['close'] < df['open']) & (df['close'] < df['open'].shift(1)) & (df['open'] > df['close'].shift(1))
    
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))

    # --- SUPERTREND CALCULATION (ROBUST) ---
    st_mul = 3.0
    
    # Inisialisasi Kolom
    df['st_upper'] = ((df['high'] + df['low']) / 2) + (st_mul * df['ATR'])
    df['st_lower'] = ((df['high'] + df['low']) / 2) - (st_mul * df['ATR'])
    df['supertrend'] = df['st_upper']
    df['st_dir'] = 1
    
    # Loop (Mulai index 1)
    for i in range(1, len(df)):
        curr_close = df['close'].iloc[i]
        prev_close = df['close'].iloc[i-1]
        
        # Logic Upper Band
        if df['st_upper'].iloc[i] < df['st_upper'].iloc[i-1] or prev_close > df['st_upper'].iloc[i-1]:
            df.at[df.index[i], 'st_upper'] = df['st_upper'].iloc[i]
        else:
            df.at[df.index[i], 'st_upper'] = df['st_upper'].iloc[i-1]
            
        # Logic Lower Band
        if df['st_lower'].iloc[i] > df['st_lower'].iloc[i-1] or prev_close < df['st_lower'].iloc[i-1]:
            df.at[df.index[i], 'st_lower'] = df['st_lower'].iloc[i]
        else:
            df.at[df.index[i], 'st_lower'] = df['st_lower'].iloc[i-1]
            
        # Logic Trend Switch
        prev_dir = df['st_dir'].iloc[i-1]
        if prev_dir == 1:
            if curr_close < df['st_lower'].iloc[i]:
                df.at[df.index[i], 'st_dir'] = -1
                df.at[df.index[i], 'supertrend'] = df['st_upper'].iloc[i]
            else:
                df.at[df.index[i], 'st_dir'] = 1
                df.at[df.index[i], 'supertrend'] = df['st_lower'].iloc[i]
        elif prev_dir == -1:
            if curr_close > df['st_upper'].iloc[i]:
                df.at[df.index[i], 'st_dir'] = 1
                df.at[df.index[i], 'supertrend'] = df['st_lower'].iloc[i]
            else:
                df.at[df.index[i], 'st_dir'] = -1
                df.at[df.index[i], 'supertrend'] = df['st_upper'].iloc[i]
                
    return df

# ==========================================
# --- 4. DETEKSI SUPPLY DEMAND ---
# ==========================================
def detect_zones(df):
    zones = []
    vol_ma = df['volume'].rolling(20).mean()
    body = (df['close'] - df['open']).abs()
    avg_body = body.rolling(20).mean()
    
    for i in range(max(0, len(df)-200), len(df)-2):
        curr = df.iloc[i]
        prev = df.iloc[i-1]
        if (curr['volume'] > vol_ma.iloc[i]) and (body.iloc[i] > avg_body.iloc[i]):
            if curr['close'] > curr['open'] and prev['close'] < prev['open']:
                zones.append({'type': 'DEMAND', 'top': prev['high'], 'bot': prev['low'], 'time': prev['timestamp'], 'color': 'rgba(41,182,246,0.2)'})
            elif curr['close'] < curr['open'] and prev['close'] > prev['open']:
                zones.append({'type': 'SUPPLY', 'top': prev['high'], 'bot': prev['low'], 'time': prev['timestamp'], 'color': 'rgba(255,167,38,0.2)'})
    
    active = []
    for z in zones:
        future = df[df['timestamp'] > z['time']]
        if future.empty: active.append(z)
        elif z['type'] == 'DEMAND':
            if not (future['low'] < z['bot']).any(): active.append(z)
        else:
            if not (future['high'] > z['top']).any(): active.append(z)
    return active

# ==========================================
# --- 5. LOGIKA SINYAL ---
# ==========================================
def generate_signals(df, zones):
    history = []
    df['sig_buy'] = False
    df['sig_sell'] = False
    
    for i in range(max(1, len(df)-100), len(df)):
        row = df.iloc[i]
        prev = df.iloc[i-1]
        
        # Syarat Dasar
        safe_buy = row['RSI'] < 70
        macd_buy = prev['MACD'] < prev['Signal'] and row['MACD'] > row['Signal']
        trigger = row['Bull_Engulf'] or row['Vol_Spike']
        entry = row['close']
        min_profit = 0.008 # 0.8% Fee Guard
        
        # 1. Zone Strategy
        hit_zone = False
        if row['MACD'] > row['Signal'] and trigger and safe_buy:
            for z in zones:
                if z['type'] == 'DEMAND' and z['time'] < row['timestamp']:
                    if row['low'] <= z['top']*1.015 and row['high'] >= z['bot']:
                        tp = z['top'] + ((z['top'] - z['bot']) * 2.0)
                        if (tp - entry)/entry > min_profit:
                            df.loc[df.index[i], 'sig_buy'] = True
                            history.append({'Waktu': row['timestamp'], 'Tipe': 'BUY (Zone)', 'Entry': entry, 'TP': tp, 'Status': 'Active'})
                            hit_zone = True
                        break
        
        # 2. Momentum Strategy
        if not hit_zone and macd_buy and safe_buy:
            sl = row['low'] - (row['ATR']*1.5)
            tp = entry + (entry - sl)*1.5
            if (tp - entry)/entry > min_profit:
                df.loc[df.index[i], 'sig_buy'] = True
                history.append({'Waktu': row['timestamp'], 'Tipe': 'BUY (Momtm)', 'Entry': entry, 'TP': tp, 'Status': 'Active'})
                
        # Sederhana Sell untuk Spot (Indikasi keluar)
        if prev['MACD'] > prev['Signal'] and row['MACD'] < row['Signal']:
             df.loc[df.index[i], 'sig_sell'] = True
             history.append({'Waktu': row['timestamp'], 'Tipe': 'SELL', 'Entry': entry, 'TP': 0, 'Status': 'Exit'})

    return df, history

# ==========================================
# --- 6. DASHBOARD ---
# ==========================================
st.sidebar.header("🎛️ Indodax Pro V8.5")
symbol = st.sidebar.selectbox("Pair", ['BTC/IDR', 'ETH/IDR', 'SOL/IDR', 'DOGE/IDR', 'XRP/IDR', 'SHIB/IDR'])
timeframe = st.sidebar.selectbox("Timeframe", ['1m', '15m', '30m', '1h'])

@st.fragment(run_every=60)
def dashboard(sym, tf):
    df, ticker = get_data(sym, tf)
    if df.empty: return
    
    df = process_indicators(df)
    zones = detect_zones(df)
    df, history = generate_signals(df, zones)
    ob = get_orderbook_analysis(sym)
    
    # Vars
    curr = float(ticker['last'])
    st_dir = df['st_dir'].iloc[-1]
    trend_txt = "BULLISH 🟢" if st_dir == 1 else "BEARISH 🔴"
    trend_col = "#00e676" if st_dir == 1 else "#ff1744"
    
    # Notify
    if 'last_sig' not in st.session_state: st.session_state['last_sig'] = None
    if history:
        last = history[-1]
        if last['Waktu'] == df['timestamp'].iloc[-1] and st.session_state['last_sig'] != last['Waktu']:
            st.session_state['last_sig'] = last['Waktu']
            send_telegram(f"SIGNAL: {sym} {last['Tipe']} @ {last['Entry']}")
            st.toast("New Signal!", icon="🚨")

    # --- UI ---
    st.markdown(f"""
    <div style="display:grid; grid-template-columns:repeat(5,1fr); gap:10px; margin-bottom:20px;">
        <div style="background:#111; padding:10px; border-radius:5px; text-align:center; border:1px solid #333;">
            <small style="color:#888">HARGA</small><br><b style="color:#f1c40f; font-size:18px">{curr:,.0f}</b>
        </div>
        <div style="background:#111; padding:10px; border-radius:5px; text-align:center; border:1px solid {trend_col};">
            <small style="color:#888">TREND (ST)</small><br><b style="color:{trend_col}; font-size:18px">{trend_txt}</b>
        </div>
        <div style="background:#111; padding:10px; border-radius:5px; text-align:center; border:1px solid #333;">
            <small style="color:#888">RSI</small><br><b style="color:white; font-size:18px">{df['RSI'].iloc[-1]:.0f}</b>
        </div>
        <div style="background:#111; padding:10px; border-radius:5px; text-align:center; border:1px solid #333;">
            <small style="color:#888">BUY WALL</small><br><b style="color:#00e676; font-size:14px">{ob['buy_wall_price']:,.0f}</b>
        </div>
        <div style="background:#111; padding:10px; border-radius:5px; text-align:center; border:1px solid #333;">
            <small style="color:#888">SELL WALL</small><br><b style="color:#ff1744; font-size:14px">{ob['sell_wall_price']:,.0f}</b>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # --- CHART (ZOOM FIXED) ---
    # Setup Range: 60 candle terakhir secara eksplisit
    range_start = df['timestamp'].iloc[-60]
    range_end = df['timestamp'].iloc[-1] + timedelta(minutes=10) # Space kosong di kanan
    
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.05)
    
    # 1. Candle
    fig.add_trace(go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Price'), row=1, col=1)
    
    # 2. Supertrend (Pastikan Data Tidak Putus)
    # Trik: Plot semua garis, tapi warnanya dinamis.
    # Atau metode segmentasi:
    st_bull = df[df['st_dir']==1]
    st_bear = df[df['st_dir']==-1]
    
    fig.add_trace(go.Scatter(x=st_bull['timestamp'], y=st_bull['supertrend'], mode='markers', marker=dict(color='#00e676', size=3), name='ST Bull'), row=1, col=1)
    fig.add_trace(go.Scatter(x=st_bear['timestamp'], y=st_bear['supertrend'], mode='markers', marker=dict(color='#ff1744', size=3), name='ST Bear'), row=1, col=1)
    
    # 3. Zones
    for z in zones:
        fig.add_shape(type="rect", x0=z['time'], y0=z['bot'], x1=range_end + timedelta(hours=5), y1=z['top'], fillcolor=z['color'], line_width=0, row=1, col=1)
        
    # 4. Walls
    if ob:
        fig.add_hline(y=ob['buy_wall_price'], line_dash="dash", line_color="#00e676", row=1, col=1)
        fig.add_hline(y=ob['sell_wall_price'], line_dash="dash", line_color="#ff1744", row=1, col=1)
        
    # 5. Signals
    if df['sig_buy'].any():
        fig.add_trace(go.Scatter(x=df[df['sig_buy']]['timestamp'], y=df[df['sig_buy']]['low'], mode='markers', marker=dict(symbol='triangle-up', size=14, color='cyan'), name='BUY'), row=1, col=1)

    # MACD
    fig.add_trace(go.Bar(x=df['timestamp'], y=df['Hist'], marker_color='gray'), row=2, col=1)
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['MACD'], line_color='#2962ff'), row=2, col=1)
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['Signal'], line_color='#ff9100'), row=2, col=1)
    
    # --- LAYOUT SETTINGS (KUNCI ZOOM) ---
    fig.update_layout(
        height=600, 
        template="plotly_dark", 
        margin=dict(l=0,r=50,t=0,b=0),
        xaxis=dict(
            range=[range_start, range_end], # Default Zoom 60 Candle
            rangeslider=dict(visible=True), # Slider Bawah untuk Geser History
            type="date"
        ),
        xaxis2=dict(range=[range_start, range_end], type="date"),
        showlegend=False
    )
    st.plotly_chart(fig, use_container_width=True)
    
    # --- TABEL SUPPLY/DEMAND & ORDERBOOK ---
    c1, c2 = st.columns(2)
    with c1:
        st.caption("🟦 Demand & 🟧 Supply")
        if zones:
            zlist = [[ "🟦 DEMAND" if z['type']=='DEMAND' else "🟧 SUPPLY", f"{z['bot']:,.0f}-{z['top']:,.0f}"] for z in reversed(zones[-5:])]
            st.table(pd.DataFrame(zlist, columns=["Tipe", "Harga"]))
    with c2:
        st.caption("📊 Riwayat Sinyal")
        if history:
            hlist = [[h['Waktu'].strftime('%H:%M'), h['Tipe'], f"{h['Entry']:,.0f}"] for h in history[::-1]]
            st.dataframe(pd.DataFrame(hlist, columns=['Jam', 'Tipe', 'Harga']), height=150, hide_index=True)

    st.divider()
    st.caption("🧱 Deep Market Depth (50 Tick)")
    wc1, wc2 = st.columns(2)
    if ob:
        with wc1: 
            st.success(f"Bids (Wall: {ob['buy_wall_price']:,.0f})")
            st.dataframe(ob['bids_df'].style.format("{:,.0f}"), hide_index=True)
        with wc2: 
            st.error(f"Asks (Wall: {ob['sell_wall_price']:,.0f})")
            st.dataframe(ob['asks_df'].style.format("{:,.0f}"), hide_index=True)

dashboard(symbol, timeframe)
