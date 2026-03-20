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
st.set_page_config(layout="wide", page_title="Indodax Scalper V8.7 Classic")

# --- TELEGRAM SETTINGS ---
def send_telegram(message):
    # GANTI DENGAN TOKEN & CHAT ID ANDA
    BOT_TOKEN = "TOKEN_BOT_ANDA_DISINI" 
    CHAT_ID = "CHAT_ID_ANDA_DISINI"
    
    if "TOKEN_BOT" in BOT_TOKEN: return 
        
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    params = {'chat_id': CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    try:
        requests.get(url, params=params, timeout=3)
    except: pass

# ==========================================
# --- 2. DATA ENGINE (OHLCV & ORDERBOOK) ---
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
        st.error(f"Koneksi Indodax Error: {e}")
        return pd.DataFrame(), None

def get_orderbook_analysis(symbol):
    try:
        exchange = ccxt.indodax()
        # Deep Scan 50 antrian
        ob = exchange.fetch_order_book(symbol, limit=50)
        
        bids = pd.DataFrame(ob['bids'], columns=['price', 'volume'])
        max_bid_idx = bids['volume'].idxmax()
        wall_buy_price = bids.iloc[max_bid_idx]['price']
        wall_buy_vol = bids.iloc[max_bid_idx]['volume']
        
        asks = pd.DataFrame(ob['asks'], columns=['price', 'volume'])
        max_ask_idx = asks['volume'].idxmax()
        wall_sell_price = asks.iloc[max_ask_idx]['price']
        wall_sell_vol = asks.iloc[max_ask_idx]['volume']
        
        return {
            'buy_wall_price': wall_buy_price,
            'buy_wall_vol': wall_buy_vol,
            'sell_wall_price': wall_sell_price,
            'sell_wall_vol': wall_sell_vol,
            'bids_df': bids.head(10), 
            'asks_df': asks.head(10)
        }
    except: return None

# ==========================================
# --- 3. INDIKATOR (SUPERTREND FIXED) ---
# ==========================================
def process_indicators(df):
    if df.empty: return df
    
    # Basic
    df['EMA_200'] = df['close'].ewm(span=200, adjust=False).mean()
    
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['Hist'] = df['MACD'] - df['Signal']
    
    # ATR
    df['tr'] = np.maximum(df['high'] - df['low'], 
               np.maximum(abs(df['high'] - df['close'].shift()), abs(df['low'] - df['close'].shift())))
    df['ATR'] = df['tr'].ewm(span=14).mean()
    df['ATR'] = df['ATR'].bfill() # Fix NaN di awal
    
    # Volume
    df['Vol_MA'] = df['volume'].rolling(20).mean()
    df['Vol_Spike'] = df['volume'] > (df['Vol_MA'] * 1.5) 
    
    # Candles
    df['Bull_Engulf'] = (df['close'] > df['open']) & (df['close'] > df['open'].shift(1)) & (df['open'] < df['close'].shift(1))
    df['Bear_Engulf'] = (df['close'] < df['open']) & (df['close'] < df['open'].shift(1)) & (df['open'] > df['close'].shift(1))
    
    # RSI
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # --- SUPERTREND LOGIC ---
    st_mul = 3
    df['st_upper'] = ((df['high'] + df['low']) / 2) + (st_mul * df['ATR'])
    df['st_lower'] = ((df['high'] + df['low']) / 2) - (st_mul * df['ATR'])
    df['supertrend'] = df['st_upper']
    df['st_dir'] = 1 
    
    for i in range(1, len(df)):
        curr_close = df['close'].iloc[i]
        prev_close = df['close'].iloc[i-1]
        
        if df['st_upper'].iloc[i] < df['st_upper'].iloc[i-1] or prev_close > df['st_upper'].iloc[i-1]:
            df.at[df.index[i], 'st_upper'] = df['st_upper'].iloc[i]
        else:
            df.at[df.index[i], 'st_upper'] = df['st_upper'].iloc[i-1]
            
        if df['st_lower'].iloc[i] > df['st_lower'].iloc[i-1] or prev_close < df['st_lower'].iloc[i-1]:
            df.at[df.index[i], 'st_lower'] = df['st_lower'].iloc[i]
        else:
            df.at[df.index[i], 'st_lower'] = df['st_lower'].iloc[i-1]
            
        if df['st_dir'].iloc[i-1] == 1:
            if curr_close < df['st_lower'].iloc[i]:
                df.at[df.index[i], 'st_dir'] = -1
                df.at[df.index[i], 'supertrend'] = df['st_upper'].iloc[i]
            else:
                df.at[df.index[i], 'st_dir'] = 1
                df.at[df.index[i], 'supertrend'] = df['st_lower'].iloc[i]
        elif df['st_dir'].iloc[i-1] == -1:
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
                zones.append({'type': 'DEMAND', 'top': prev['high'], 'bot': prev['low'], 'time': prev['timestamp'], 'color': 'rgba(41,182,246,0.2)', 'line': 'rgba(41,182,246,0.8)'})
            elif curr['close'] < curr['open'] and prev['close'] > prev['open']:
                zones.append({'type': 'SUPPLY', 'top': prev['high'], 'bot': prev['low'], 'time': prev['timestamp'], 'color': 'rgba(255,167,38,0.2)', 'line': 'rgba(255,167,38,0.8)'})
            
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
        
        safe_buy = row['RSI'] < 70
        safe_sell = row['RSI'] > 30
        macd_buy = prev['MACD'] < prev['Signal'] and row['MACD'] > row['Signal']
        macd_sell = prev['MACD'] > prev['Signal'] and row['MACD'] < row['Signal']
        trigger = row['Bull_Engulf'] or row['Vol_Spike']
        entry = row['close']
        min_profit = 0.008 
        
        hit_zone = False
        if row['MACD'] > row['Signal'] and trigger and safe_buy:
            for z in zones:
                if z['type'] == 'DEMAND' and z['time'] < row['timestamp']:
                    if row['low'] <= z['top']*1.015 and row['high'] >= z['bot']:
                        sl = z['bot'] - row['ATR']
                        tp = z['top'] + ((z['top'] - z['bot']) * 2.0)
                        if (tp - entry)/entry > min_profit:
                            df.loc[df.index[i], 'sig_buy'] = True
                            history.append({'Waktu': row['timestamp'], 'Tipe': 'BUY (Zone)', 'Entry': entry, 'SL': sl, 'TP': tp, 'Status': 'Active'})
                            hit_zone = True
                        break
        
        if not hit_zone and macd_buy and safe_buy:
            sl = row['low'] - (row['ATR']*1.5)
            tp = entry + (entry - sl)*1.5
            if (tp - entry)/entry > min_profit:
                df.loc[df.index[i], 'sig_buy'] = True
                history.append({'Waktu': row['timestamp'], 'Tipe': 'BUY (Momtm)', 'Entry': entry, 'SL': sl, 'TP': tp, 'Status': 'Active'})
                
        if macd_sell and safe_sell:
             sl = row['high'] + (row['ATR']*1.5)
             tp = entry - (sl - entry)*1.5
             if (entry - tp)/entry > min_profit:
                 df.loc[df.index[i], 'sig_sell'] = True
                 history.append({'Waktu': row['timestamp'], 'Tipe': 'SELL', 'Entry': entry, 'SL': sl, 'TP': tp, 'Status': 'Active'})

    return df, history

# ==========================================
# --- 6. DASHBOARD UTAMA ---
# ==========================================
st.sidebar.header("🎛️ Scalper V8.7")
symbol = st.sidebar.selectbox("Pair", ['BTC/IDR', 'ETH/IDR', 'SOL/IDR', 'DOGE/IDR', 'XRP/IDR', 'SHIB/IDR', 'USDT/IDR'])
timeframe = st.sidebar.selectbox("Timeframe", ['1m', '15m', '30m', '1h', '4h'])
st.title(f"Scalper Pro: {symbol} ({timeframe})")

@st.fragment(run_every=60)
def dashboard(sym, tf):
    df, ticker = get_data(sym, tf)
    if df.empty: return
    
    df = process_indicators(df)
    zones = detect_zones(df)
    df, history = generate_signals(df, zones)
    ob_data = get_orderbook_analysis(sym)
    
    # Realtime Vars
    curr = float(ticker['last'])
    vol = float(ticker['baseVolume'])
    rsi_val = df['RSI'].iloc[-1]
    
    st_dir = df['st_dir'].iloc[-1]
    trend_txt = "BULLISH 🟢" if st_dir == 1 else "BEARISH 🔴"
    trend_col = "#00e676" if st_dir == 1 else "#ff1744"

    # Notifikasi
    if 'last_alert_time' not in st.session_state:
        st.session_state['last_alert_time'] = None
    
    status_txt = "WAITING..."
    sig_col = "#777"
    entry_plan, tp_plan, sl_plan = "-", "-", "-"
    
    if history:
        last_sig = history[-1]
        if last_sig['Waktu'] == df['timestamp'].iloc[-1]:
            if st.session_state['last_alert_time'] != last_sig['Waktu']:
                st.session_state['last_alert_time'] = last_sig['Waktu']
                msg = f"⚠️ SIGNAL: {sym}\nType: {last_sig['Tipe']}\nPrice: {last_sig['Entry']}"
                send_telegram(msg)
                st.toast("Signal Sent!", icon="🚀")
                
            if 'BUY' in last_sig['Tipe']:
                status_txt = last_sig['Tipe']
                sig_col = "#00e676"
            elif 'SELL' in last_sig['Tipe']:
                status_txt = last_sig['Tipe']
                sig_col = "#ff1744"
            entry_plan = f"Rp {last_sig['Entry']:,.0f}"
            tp_plan = f"Rp {last_sig['TP']:,.0f}"
            sl_plan = f"Rp {last_sig['SL']:,.0f}"

    def fmt(x): return f"{x:,.0f}".replace(",", ".")

    # --- CLASSIC V8.2 LAYOUT (RESTORED) ---
    st.markdown(f"""
    <style>
        .row-1 {{ display: grid; grid-template-columns: 1.5fr 1fr 1fr 1fr 1fr; gap: 8px; margin-bottom: 10px; }}
        .row-2 {{ display: grid; grid-template-columns: 1fr 1fr 1fr 1fr 1.2fr; gap: 8px; margin-bottom: 20px; }}
        .box {{ background: #1e1e1e; border: 1px solid #333; padding: 8px; border-radius: 6px; text-align: center; }}
        .sig-box {{ background: {sig_col}20; border: 2px solid {sig_col}; padding: 8px; border-radius: 6px; text-align: center; }}
        .lbl {{ font-size: 9px; color: #aaa; font-weight: bold; margin-bottom: 3px; text-transform: uppercase; }}
        .val {{ font-size: 14px; font-weight: bold; color: white; }}
        .val-lg {{ font-size: 18px; font-weight: 900; color: {sig_col}; }}
    </style>

    <div class="row-1">
        <div class="sig-box"><div class="lbl">STATUS</div><div class="val-lg">{status_txt}</div></div>
        <div class="box"><div class="lbl">HARGA</div><div class="val" style="color:#f1c40f">Rp {fmt(curr)}</div></div>
        <div class="box"><div class="lbl">LOW 24J</div><div class="val" style="color:#ff1744">{fmt(ticker['low'])}</div></div>
        <div class="box"><div class="lbl">HIGH 24J</div><div class="val" style="color:#00e676">{fmt(ticker['high'])}</div></div>
        <div class="box"><div class="lbl">VOLUME</div><div class="val">{fmt(vol)}</div></div>
    </div>

    <div class="row-2">
        <div class="box" style="border-top: 3px solid #29b6f6"><div class="lbl">ENTRY PLAN</div><div class="val" style="color:#29b6f6">{entry_plan}</div></div>
        <div class="box" style="border-top: 3px solid #00e676"><div class="lbl">TAKE PROFIT</div><div class="val" style="color:#00e676">{tp_plan}</div></div>
        <div class="box" style="border-top: 3px solid #ff1744"><div class="lbl">STOP LOSS</div><div class="val" style="color:#ff1744">{sl_plan}</div></div>
        <div class="box"><div class="lbl">RSI (MOMENTUM)</div><div class="val"><span style="color:{'#ff1744' if rsi_val > 70 else '#00e676' if rsi_val < 30 else 'white'}">{rsi_val:.0f}</span></div></div>
        <div class="box"><div class="lbl">TREND (ST)</div><div class="val" style="color:{trend_col}">{trend_txt}</div></div>
    </div>
    """, unsafe_allow_html=True)

    # --- PLOT CHART (ZOOM 60 CANDLE FIXED) ---
    range_end = df['timestamp'].iloc[-1] + timedelta(minutes=15)
    range_start = df['timestamp'].iloc[-60] # Kunci 60 candle
    
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.75, 0.25])
    
    fig.add_trace(go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Price'), row=1, col=1)
    
    # Supertrend Split (Agar garis warna tidak nyambung)
    st_bull = df.copy()
    st_bull.loc[st_bull['st_dir'] == -1, 'supertrend'] = np.nan
    st_bear = df.copy()
    st_bear.loc[st_bear['st_dir'] == 1, 'supertrend'] = np.nan
    
    fig.add_trace(go.Scatter(x=st_bull['timestamp'], y=st_bull['supertrend'], line=dict(color='#00e676', width=2), name='ST Bull'), row=1, col=1)
    fig.add_trace(go.Scatter(x=st_bear['timestamp'], y=st_bear['supertrend'], line=dict(color='#ff1744', width=2), name='ST Bear'), row=1, col=1)
    
    for z in zones:
        end_t = df['timestamp'].iloc[-1] + timedelta(hours=4)
        fig.add_shape(type="rect", x0=z['time'], y0=z['bot'], x1=end_t, y1=z['top'], 
                      fillcolor=z['color'], line_color=z['line'], line_width=1, row=1, col=1)

    if ob_data:
        fig.add_hline(y=ob_data['buy_wall_price'], line_dash="dash", line_color="#00e676", annotation_text="BUY WALL", row=1, col=1)
        fig.add_hline(y=ob_data['sell_wall_price'], line_dash="dash", line_color="#ff1744", annotation_text="SELL WALL", row=1, col=1)
    
    if df['sig_buy'].any():
        fig.add_trace(go.Scatter(x=df[df['sig_buy']]['timestamp'], y=df[df['sig_buy']]['low'], mode='markers', marker=dict(symbol='triangle-up', size=12, color='#00e676'), name='Buy'), row=1, col=1)
    
    fig.add_trace(go.Bar(x=df['timestamp'], y=df['Hist'], marker_color=np.where(df['Hist']<0, '#ff1744', '#00e676')), row=2, col=1)
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['MACD'], line=dict(color='#2962ff'), name='MACD'), row=2, col=1)
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['Signal'], line=dict(color='#ff9100'), name='Signal'), row=2, col=1)
    
    fig.update_layout(
        height=600, 
        template="plotly_dark", 
        margin=dict(l=0,r=50,t=0,b=0), 
        xaxis=dict(range=[range_start, range_end], rangeslider=dict(visible=True), type="date"), # SLIDER AKTIF
        xaxis2=dict(range=[range_start, range_end], type="date"),
        showlegend=False
    )
    st.plotly_chart(fig, use_container_width=True)
    
    # --- TABLE LAYOUT ---
    st.markdown("### 📋 Analisa Teknikal & Orderbook")
    c1, c2 = st.columns(2)
    
    with c1:
        st.caption("🟦 Demand & 🟧 Supply Zones")
        if zones:
            z_list = [[ "🟦 DEMAND" if z['type']=='DEMAND' else "🟧 SUPPLY", f"{fmt(z['bot'])} - {fmt(z['top'])}", z['time'].strftime('%H:%M') ] for z in reversed(zones[-5:])]
            st.table(pd.DataFrame(z_list, columns=["Tipe", "Harga", "Waktu"]))
            
    with c2:
        st.caption("📊 Riwayat Sinyal")
        if history:
            h_df = pd.DataFrame(history).iloc[::-1]
            h_df['Entry'] = h_df['Entry'].apply(lambda x: fmt(x))
            h_df['Waktu'] = h_df['Waktu'].dt.strftime('%H:%M')
            st.dataframe(h_df[['Waktu', 'Tipe', 'Entry', 'Status']], use_container_width=True, hide_index=True, height=200)

    st.divider()
    st.markdown("### 🧱 Deep Orderbook (50 Ticks)")
    if ob_data:
        bc1, bc2 = st.columns(2)
        with bc1:
            st.success(f"🛡️ **Bids (Antrian Beli)** | Wall: **{fmt(ob_data['buy_wall_price'])}**")
            st.dataframe(ob_data['bids_df'].style.format({"price": "{:,.0f}", "volume": "{:,.2f}"}), use_container_width=True, hide_index=True)
        with bc2:
            st.error(f"🧱 **Asks (Antrian Jual)** | Wall: **{fmt(ob_data['sell_wall_price'])}**")
            st.dataframe(ob_data['asks_df'].style.format({"price": "{:,.0f}", "volume": "{:,.2f}"}), use_container_width=True, hide_index=True)

dashboard(symbol, timeframe)
