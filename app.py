import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import pytz
import requests  # <--- PERLU INSTALL: pip install requests

# --- 1. KONFIGURASI ---
st.set_page_config(layout="wide", page_title="Scalper V6 + Telegram Notif")

# --- 2. FUNGSI KIRIM TELEGRAM ---
def send_telegram(message):
    # --- ISI DATA BOT ANDA DISINI ---
    BOT_TOKEN = "7992906337:AAGPstFckZsaMmabZDA6m_EauP-aTqQxlZQ" 
    CHAT_ID = "8107526630"
    # --------------------------------
    
    if BOT_TOKEN == "7992906337:AAGPstFckZsaMmabZDA6m_EauP-aTqQxlZQ":
        return # Belum disetting
        
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    params = {'chat_id': CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    try:
        requests.get(url, params=params, timeout=5)
    except:
        pass

# --- 3. ENGINE DATA & INDIKATOR (SAMA SEPERTI SEBELUMNYA) ---
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
        st.error(f"Koneksi Error: {e}")
        return pd.DataFrame(), None

def process_indicators(df):
    if df.empty: return df
    df['EMA_200'] = df['close'].ewm(span=200, adjust=False).mean()
    
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['Hist'] = df['MACD'] - df['Signal']
    
    df['tr'] = np.maximum(df['high'] - df['low'], 
               np.maximum(abs(df['high'] - df['close'].shift()), abs(df['low'] - df['close'].shift())))
    df['ATR'] = df['tr'].ewm(span=14).mean()
    
    df['Vol_MA'] = df['volume'].rolling(20).mean()
    df['Vol_Spike'] = df['volume'] > df['Vol_MA']
    
    df['Bull_Engulf'] = (df['close'] > df['open']) & (df['close'] > df['open'].shift(1)) & \
                        (df['open'] < df['close'].shift(1))
    df['Bear_Engulf'] = (df['close'] < df['open']) & (df['close'] < df['open'].shift(1)) & \
                        (df['open'] > df['close'].shift(1))
    return df

def detect_zones(df):
    zones = []
    vol_ma = df['volume'].rolling(20).mean()
    body = (df['close'] - df['open']).abs()
    avg_body = body.rolling(20).mean()
    start = max(0, len(df) - 150)
    
    for i in range(start, len(df)-2):
        curr = df.iloc[i]
        prev = df.iloc[i-1]
        is_impulse = (curr['volume'] > vol_ma.iloc[i]) and (body.iloc[i] > avg_body.iloc[i])
        
        if is_impulse and curr['close'] > curr['open'] and prev['close'] < prev['open']:
            zones.append({
                'type': 'DEMAND', 'top': prev['high'], 'bot': prev['low'], 'time': prev['timestamp'],
                'color': 'rgba(41, 182, 246, 0.3)', 'line': 'rgba(41, 182, 246, 0.8)'
            })
        elif is_impulse and curr['close'] < curr['open'] and prev['close'] > prev['open']:
            zones.append({
                'type': 'SUPPLY', 'top': prev['high'], 'bot': prev['low'], 'time': prev['timestamp'],
                'color': 'rgba(255, 167, 38, 0.3)', 'line': 'rgba(255, 167, 38, 0.8)'
            })
    
    active = []
    for z in zones:
        future = df[df['timestamp'] > z['time']]
        if future.empty: active.append(z)
        elif z['type'] == 'DEMAND':
            if not (future['close'] < z['bot']).any(): active.append(z)
        else:
            if not (future['close'] > z['top']).any(): active.append(z)
    return active

def generate_signals(df, zones):
    history = []
    df['sig_buy'] = False
    df['sig_sell'] = False
    start = max(0, len(df) - 100)
    
    for i in range(start, len(df)):
        row = df.iloc[i]
        if row['MACD'] > row['Signal'] and (row['Bull_Engulf'] or row['Vol_Spike']):
            for z in zones:
                if z['type'] == 'DEMAND' and z['time'] < row['timestamp']:
                    if row['low'] <= z['top']*1.005 and row['high'] >= z['bot']:
                        sl = z['bot'] - row['ATR']
                        tp = z['top'] + ((z['top'] - sl) * 2)
                        df.loc[df.index[i], 'sig_buy'] = True
                        history.append({'Waktu': row['timestamp'], 'Tipe': 'BUY', 'Entry': row['close'], 'SL': sl, 'TP': tp})
                        break
                        
        if row['MACD'] < row['Signal'] and (row['Bear_Engulf'] or row['Vol_Spike']):
            for z in zones:
                if z['type'] == 'SUPPLY' and z['time'] < row['timestamp']:
                    if row['high'] >= z['bot']*0.995 and row['low'] <= z['top']:
                        sl = z['top'] + row['ATR']
                        tp = z['bot'] - ((sl - z['bot']) * 2)
                        df.loc[df.index[i], 'sig_sell'] = True
                        history.append({'Waktu': row['timestamp'], 'Tipe': 'SELL', 'Entry': row['close'], 'SL': sl, 'TP': tp})
                        break
    return df, history

# --- 4. DASHBOARD + LOGIKA NOTIFIKASI ---
st.sidebar.header("🎛️ Scalping Controller")
symbol = st.sidebar.selectbox("Pair", ['BTC/IDR', 'ETH/IDR', 'SOL/IDR', 'DOGE/IDR', 'XRP/IDR', 'SHIB/IDR'])
timeframe = st.sidebar.selectbox("Timeframe", ['1m', '15m', '30m', '1h', '4h'])

st.title(f"Scalping Pro: {symbol} ({timeframe})")

@st.fragment(run_every=60)
def dashboard(sym, tf):
    df, ticker = get_data(sym, tf)
    if df.empty: return
    df = process_indicators(df)
    zones = detect_zones(df)
    df, history = generate_signals(df, zones)
    
    # Vars
    curr = float(ticker['last'])
    vol = float(ticker['baseVolume'])
    high24 = float(ticker['high'])
    low24 = float(ticker['low'])
    atr = df['ATR'].iloc[-1]
    ema200 = df['EMA_200'].iloc[-1]
    
    # --- LOGIKA NOTIFIKASI TELEGRAM (ANTI SPAM) ---
    # Kita gunakan Session State untuk menyimpan waktu sinyal terakhir yg dikirim
    if 'last_alert_time' not in st.session_state:
        st.session_state['last_alert_time'] = None

    status_txt = "WAITING..."
    sig_col = "#777"
    entry_plan, tp_plan, sl_plan = "-", "-", "-"
    
    if history:
        last_sig = history[-1]
        # Cek apakah sinyal terjadi di candle terakhir
        if last_sig['Waktu'] == df['timestamp'].iloc[-1]:
            
            is_new_signal = False
            if st.session_state['last_alert_time'] != last_sig['Waktu']:
                is_new_signal = True
                st.session_state['last_alert_time'] = last_sig['Waktu']
            
            if last_sig['Tipe'] == 'BUY':
                status_txt = "BUY SIGNAL"
                sig_col = "#00e676"
                msg_header = "🟢 *BUY SIGNAL DETECTED!*"
            else:
                status_txt = "SELL SIGNAL"
                sig_col = "#ff1744"
                msg_header = "🔴 *SELL SIGNAL DETECTED!*"
                
            entry_plan = f"Rp {last_sig['Entry']:,.0f}"
            tp_plan = f"Rp {last_sig['TP']:,.0f}"
            sl_plan = f"Rp {last_sig['SL']:,.0f}"
            
            # KIRIM PESAN JIKA BARU
            if is_new_signal:
                pesan = f"""
{msg_header}
Asset: {sym} ({tf})
Price: {entry_plan}
TP: {tp_plan}
SL: {sl_plan}
Time: {last_sig['Waktu'].strftime('%H:%M')}
"""
                send_telegram(pesan)
                st.toast(f"Sinyal Terkirim ke Telegram!", icon="🚀")

    # Helper Format
    def fmt(x): return f"{x:,.0f}".replace(",", ".")

    # --- LAYOUT ---
    st.markdown(f"""
    <style>
        .row-1 {{ display: grid; grid-template-columns: 1.5fr 1fr 1fr 1fr 1fr; gap: 8px; margin-bottom: 10px; }}
        .row-2 {{ display: grid; grid-template-columns: 1fr 1fr 1fr 1fr 1fr; gap: 8px; margin-bottom: 20px; }}
        .box {{ background: #1e1e1e; border: 1px solid #333; padding: 8px; border-radius: 6px; text-align: center; }}
        .sig-box {{ background: {sig_col}20; border: 2px solid {sig_col}; padding: 8px; border-radius: 6px; text-align: center; }}
        .lbl {{ font-size: 9px; color: #aaa; font-weight: bold; margin-bottom: 3px; text-transform: uppercase; }}
        .val {{ font-size: 14px; font-weight: bold; color: white; }}
        .val-lg {{ font-size: 18px; font-weight: 900; color: {sig_col}; }}
    </style>

    <div class="row-1">
        <div class="sig-box"><div class="lbl">STATUS SINYAL</div><div class="val-lg">{status_txt}</div></div>
        <div class="box"><div class="lbl">HARGA</div><div class="val" style="color:#f1c40f">Rp {fmt(curr)}</div></div>
        <div class="box"><div class="lbl">LOW 24J</div><div class="val" style="color:#ff1744">{fmt(low24)}</div></div>
        <div class="box"><div class="lbl">HIGH 24J</div><div class="val" style="color:#00e676">{fmt(high24)}</div></div>
        <div class="box"><div class="lbl">VOLUME</div><div class="val">{fmt(vol)}</div></div>
    </div>

    <div class="row-2">
        <div class="box" style="border-top: 3px solid #29b6f6"><div class="lbl">ENTRY PLAN</div><div class="val" style="color:#29b6f6">{entry_plan}</div></div>
        <div class="box" style="border-top: 3px solid #00e676"><div class="lbl">TAKE PROFIT</div><div class="val" style="color:#00e676">{tp_plan}</div></div>
        <div class="box" style="border-top: 3px solid #ff1744"><div class="lbl">STOP LOSS</div><div class="val" style="color:#ff1744">{sl_plan}</div></div>
        <div class="box"><div class="lbl">VOLATILITY</div><div class="val">{fmt(atr)}</div></div>
        <div class="box"><div class="lbl">TREND</div><div class="val" style="color:{'#00e676' if curr > ema200 else '#ff1744'}">{'BULL' if curr > ema200 else 'BEAR'}</div></div>
    </div>
    """, unsafe_allow_html=True)
    
    # Chart & Tables (Sama seperti V6)
    rng_end = df['timestamp'].iloc[-1] + timedelta(minutes=15)
    rng_start = df['timestamp'].iloc[-60]
    
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.75, 0.25])
    fig.add_trace(go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Price'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['EMA_200'], line=dict(color='yellow', width=2), name='EMA 200'), row=1, col=1)
    
    for z in zones:
        end_t = df['timestamp'].iloc[-1] + timedelta(hours=4)
        fig.add_shape(type="rect", x0=z['time'], y0=z['bot'], x1=end_t, y1=z['top'], fillcolor=z['color'], line_color=z['line'], line_width=1, row=1, col=1)
    
    if df['sig_buy'].any():
        fig.add_trace(go.Scatter(x=df[df['sig_buy']]['timestamp'], y=df[df['sig_buy']]['low'], mode='markers', marker=dict(symbol='triangle-up', size=12, color='#00e676'), name='Buy'), row=1, col=1)
    if df['sig_sell'].any():
        fig.add_trace(go.Scatter(x=df[df['sig_sell']]['timestamp'], y=df[df['sig_sell']]['high'], mode='markers', marker=dict(symbol='triangle-down', size=12, color='#ff1744'), name='Sell'), row=1, col=1)

    fig.add_trace(go.Bar(x=df['timestamp'], y=df['Hist'], marker_color=np.where(df['Hist']<0, '#ff1744', '#00e676')), row=2, col=1)
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['MACD'], line=dict(color='#2962ff'), name='MACD'), row=2, col=1)
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['Signal'], line=dict(color='#ff9100'), name='Signal'), row=2, col=1)
    
    fig.update_layout(height=550, template="plotly_dark", margin=dict(l=0,r=50,t=0,b=0), xaxis_range=[rng_start, rng_end], xaxis2_range=[rng_start, rng_end], xaxis_rangeslider_visible=False)
    st.plotly_chart(fig, use_container_width=True)
    
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("📋 Supply & Demand")
        if zones:
            z_data = [[f"{'🟦 DEMAND' if z['type']=='DEMAND' else '🟧 SUPPLY'}", f"Rp {fmt(z['bot'])} - {fmt(z['top'])}", z['time'].strftime('%H:%M')] for z in reversed(zones[-5:])]
            st.table(pd.DataFrame(z_data, columns=["Tipe", "Range Harga", "Waktu"]))
    with col2:
        st.subheader("📊 Histori Sinyal")
        if history:
            h_df = pd.DataFrame(history).iloc[::-1]
            st.dataframe(h_df[['Waktu', 'Tipe', 'Entry', 'TP']].style.format({"Entry": "Rp {:,.0f}", "TP": "Rp {:,.0f}"}), use_container_width=True)

dashboard(symbol, timeframe)
