import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
import pytz

# --- 1. KONFIGURASI PAGE ---
st.set_page_config(layout="wide", page_title="Indodax Scalper: Golden Pullback")

# --- 2. FUNGSI DATA & INDIKATOR ---
def get_data(symbol, tf):
    exchange = ccxt.indodax()
    try:
        # Ambil 500 candle agar EMA 200 akurat di TF kecil (1m)
        ohlcv = exchange.fetch_ohlcv(symbol, tf, limit=500)
        if not ohlcv:
            return pd.DataFrame(), None
            
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        # Konversi waktu ke WIB
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize('UTC').dt.tz_convert('Asia/Jakarta')
        ticker = exchange.fetch_ticker(symbol)
        return df, ticker
    except Exception as e:
        st.error(f"Gagal mengambil data ({tf}): {e}")
        return pd.DataFrame(), None

def calculate_strategy(df):
    if df.empty: return df
    
    # A. Trend Filter (The Golden Line)
    df['EMA_50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['EMA_200'] = df['close'].ewm(span=200, adjust=False).mean()
    
    # B. Momentum (Stochastic RSI)
    period = 14
    smoothK = 3
    smoothD = 3
    
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    
    stoch_rsi = (rsi - rsi.rolling(period).min()) / (rsi.rolling(period).max() - rsi.rolling(period).min())
    df['K'] = stoch_rsi.rolling(smoothK).mean() * 100 
    df['D'] = df['K'].rolling(smoothD).mean()
    
    # C. Volatilitas (ATR) untuk SL/TP
    df['tr'] = np.maximum(df['high'] - df['low'], 
               np.maximum(abs(df['high'] - df['close'].shift()), abs(df['low'] - df['close'].shift())))
    df['ATR'] = df['tr'].ewm(span=14).mean()
    
    # D. Volume Filter
    df['Vol_MA'] = df['volume'].rolling(20).mean()
    df['Vol_Valid'] = df['volume'] > df['Vol_MA']

    # --- ENGINE SINYAL ---
    df['signal'] = "WAIT"
    
    # Loop 3 candle terakhir untuk deteksi crossing yang baru terjadi
    # Kita pakai iloc[-1] (candle aktif) dan iloc[-2] (candle confirm)
    
    last = df.index[-1]
    prev = df.index[-2]
    
    # Data Candle Terakhir
    close = df.loc[last, 'close']
    ema200 = df.loc[last, 'EMA_200']
    k_now = df.loc[last, 'K']
    d_now = df.loc[last, 'D']
    k_prev = df.loc[prev, 'K']
    d_prev = df.loc[prev, 'D']
    vol_ok = df.loc[last, 'Vol_Valid']
    
    # LOGIKA BUY (Golden Pullback)
    # 1. Trend Aman: Harga > EMA 200
    # 2. Momentum: Stoch RSI Cross UP (K memotong D ke atas)
    # 3. Area: Terjadi di area Oversold (< 40) atau Netral (Pullback)
    if (close > ema200) and (k_prev < d_prev) and (k_now > d_now) and (k_now < 50):
        df.loc[last, 'signal'] = "SCALP BUY"
        
    # LOGIKA SELL
    # 1. Trend Turun: Harga < EMA 200
    # 2. Momentum: Stoch RSI Cross DOWN
    # 3. Area: Terjadi di area Overbought (> 60)
    elif (close < ema200) and (k_prev > d_prev) and (k_now < d_now) and (k_now > 50):
        df.loc[last, 'signal'] = "SCALP SELL"
        
    return df

# --- 3. DASHBOARD ---
st.sidebar.header("⚡ Scalping Dashboard")
symbol = st.sidebar.selectbox("Aset Kripto", ['BTC/IDR', 'ETH/IDR', 'SOL/IDR', 'DOGE/IDR', 'XRP/IDR', 'SHIB/IDR', 'PEPE/IDR'])

# Timeframe yang didukung Indodax (5m dihapus karena error)
valid_timeframes = ['1m', '15m', '30m', '1h', '4h', '1d']
timeframe = st.sidebar.selectbox("Timeframe", valid_timeframes)

st.title(f"Scalper: {symbol} | TF {timeframe}")

@st.fragment(run_every=60)
def show_dashboard(sym, tf):
    # 1. Ambil & Olah Data
    df, ticker = get_data(sym, tf)
    if df.empty: return
    
    df = calculate_strategy(df)
    
    # 2. Variabel Realtime
    curr_price = float(ticker['last'])
    vol = float(ticker['baseVolume'])
    signal = df['signal'].iloc[-1]
    atr = df['ATR'].iloc[-1]
    ema200 = df['EMA_200'].iloc[-1]
    
    # 3. Tentukan Status Trend
    is_uptrend = curr_price > ema200
    trend_txt = "UPTREND (BULLISH)" if is_uptrend else "DOWNTREND (BEARISH)"
    trend_col = "#00e676" if is_uptrend else "#ff1744"
    
    # 4. Hitung Plan (Jika ada Sinyal)
    sig_bg = "#1e1e1e"
    sig_col = "#777"
    entry_txt, sl_txt, tp_txt = "-", "-", "-"
    
    if "BUY" in signal:
        sig_bg = "rgba(0, 255, 0, 0.2)"
        sig_col = "#00e676"
        entry_txt = f"Rp {curr_price:,.0f}"
        
        # SL = Swing Low atau 2x ATR (Jaga jarak aman)
        sl_val = curr_price - (2 * atr)
        # TP = RR 1:1.5 (Scalping cepat)
        tp_val = curr_price + (3 * atr)
        
        sl_txt = f"Rp {sl_val:,.0f}"
        tp_txt = f"Rp {tp_val:,.0f}"
        
    elif "SELL" in signal:
        sig_bg = "rgba(255, 0, 0, 0.2)"
        sig_col = "#ff1744"
        entry_txt = f"Rp {curr_price:,.0f}"
        
        sl_val = curr_price + (2 * atr)
        tp_val = curr_price - (3 * atr)
        
        sl_txt = f"Rp {sl_val:,.0f}"
        tp_txt = f"Rp {tp_val:,.0f}"

    # Format Angka
    def fmt(x): return f"{x:,.0f}".replace(",", ".")

    # --- LAYOUT VISUAL ---
    st.markdown(f"""
    <style>
        .grid-market {{ display: grid; grid-template-columns: 1.5fr 1fr 1fr 1fr; gap: 8px; margin-bottom: 10px; }}
        .grid-plan {{ display: grid; grid-template-columns: 1fr 1fr 1fr 1.5fr; gap: 8px; margin-bottom: 20px; }}
        .box {{ background: #1e1e1e; border: 1px solid #333; padding: 10px; border-radius: 6px; text-align: center; }}
        .sig-box {{ background: {sig_bg}; border: 2px solid {sig_col}; padding: 10px; border-radius: 6px; text-align: center; }}
        .lbl {{ font-size: 10px; color: #aaa; margin-bottom: 4px; font-weight: bold; text-transform: uppercase; }}
        .val {{ font-size: 15px; font-weight: bold; color: white; }}
        .val-lg {{ font-size: 18px; font-weight: 900; color: {sig_col}; }}
    </style>
    
    <!-- BARIS 1: INFO PASAR -->
    <div class="grid-market">
        <div class="sig-box">
            <div class="lbl">SINYAL SCALPING</div>
            <div class="val-lg">{signal}</div>
        </div>
        <div class="box">
            <div class="lbl">HARGA SAAT INI</div>
            <div class="val" style="color:#f1c40f">Rp {fmt(curr_price)}</div>
        </div>
        <div class="box">
            <div class="lbl">TREND FILTER (EMA 200)</div>
            <div class="val" style="color:{trend_col}">{trend_txt}</div>
        </div>
        <div class="box">
            <div class="lbl">VOLATILITAS (ATR)</div>
            <div class="val">{fmt(atr)}</div>
        </div>
    </div>

    <!-- BARIS 2: TRADING PLAN -->
    <div class="grid-plan">
        <div class="box" style="border-top: 3px solid #2979ff">
            <div class="lbl">ENTRY POINT</div>
            <div class="val" style="color:#2979ff">{entry_txt}</div>
        </div>
        <div class="box" style="border-top: 3px solid #00e676">
            <div class="lbl">TAKE PROFIT</div>
            <div class="val" style="color:#00e676">{tp_txt}</div>
        </div>
        <div class="box" style="border-top: 3px solid #ff1744">
            <div class="lbl">STOP LOSS</div>
            <div class="val" style="color:#ff1744">{sl_txt}</div>
        </div>
        <div class="box">
            <div class="lbl">MOMENTUM STOCH-RSI</div>
            <div class="val" style="font-size:13px">
                K: {df['K'].iloc[-1]:.1f} | D: {df['D'].iloc[-1]:.1f} <br>
                <span style="color:{'#00e676' if df['K'].iloc[-1] > df['D'].iloc[-1] else '#ff1744'}">
                    {'BULLISH CROSS' if df['K'].iloc[-1] > df['D'].iloc[-1] else 'BEARISH CROSS'}
                </span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # --- CHART ---
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
    
    # 1. Harga & EMA
    fig.add_trace(go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Price'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['EMA_200'], line=dict(color='yellow', width=2), name='EMA 200 (Trend)'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['EMA_50'], line=dict(color='cyan', width=1), name='EMA 50'), row=1, col=1)
    
    # Penanda Sinyal
    buys = df[df['signal'] == "SCALP BUY"]
    sells = df[df['signal'] == "SCALP SELL"]
    
    if not buys.empty:
        fig.add_trace(go.Scatter(x=buys['timestamp'], y=buys['low'], mode='markers', marker=dict(symbol='triangle-up', size=12, color='#00e676'), name='Buy Signal'), row=1, col=1)
    if not sells.empty:
        fig.add_trace(go.Scatter(x=sells['timestamp'], y=sells['high'], mode='markers', marker=dict(symbol='triangle-down', size=12, color='#ff1744'), name='Sell Signal'), row=1, col=1)

    # 2. Stoch RSI
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['K'], line=dict(color='#00e676', width=1.5), name='Stoch K'), row=2, col=1)
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['D'], line=dict(color='#ff1744', width=1.5), name='Stoch D'), row=2, col=1)
    
    # Area Momentum
    fig.add_hrect(y0=20, y1=80, fillcolor="rgba(255,255,255,0.05)", line_width=0, row=2, col=1)
    fig.add_hline(y=20, line_dash="dot", line_color="gray", row=2, col=1)
    fig.add_hline(y=80, line_dash="dot", line_color="gray", row=2, col=1)
    
    fig.update_layout(height=600, template="plotly_dark", margin=dict(l=0,r=0,t=10,b=0), xaxis_rangeslider_visible=False)
    st.plotly_chart(fig, use_container_width=True)

show_dashboard(symbol, timeframe)
