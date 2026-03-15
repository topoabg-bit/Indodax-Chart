import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
import pytz

# --- 1. KONFIGURASI UTAMA ---
st.set_page_config(layout="wide", page_title="Indodax Scalper: Trend & Momentum")

# --- 2. ENGINE INDIKATOR ---
def calculate_indicators(df):
    # A. Trend Filter (EMA 200 & EMA 50)
    df['EMA_50'] = df['close'].ewm(span=50, adjust=False).mean()
    df['EMA_200'] = df['close'].ewm(span=200, adjust=False).mean()
    
    # B. Momentum (Stochastic RSI) - Early Signal
    # Setelan Scalping: 14, 3, 3
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
    
    # C. Volume Flow
    df['Vol_MA'] = df['volume'].rolling(20).mean()
    df['Vol_Spike'] = df['volume'] > df['Vol_MA']
    
    # D. ATR untuk Stop Loss Dinamis
    df['tr'] = np.maximum(df['high'] - df['low'], 
               np.maximum(abs(df['high'] - df['close'].shift()), abs(df['low'] - df['close'].shift())))
    df['ATR'] = df['tr'].ewm(span=14).mean()
    
    return df

def detect_signals(df):
    df['signal'] = "WAIT"
    df['entry_price'] = 0.0
    
    # Loop scanning candle terakhir (Realtime)
    last_idx = df.index[-1]
    prev_idx = df.index[-2]
    
    # Ambil Data
    close = df['close'].iloc[-1]
    ema200 = df['EMA_200'].iloc[-1]
    k_now = df['K'].iloc[-1]
    d_now = df['D'].iloc[-1]
    k_prev = df['K'].iloc[-2]
    d_prev = df['D'].iloc[-2]
    vol_ok = df['Vol_Spike'].iloc[-1]
    
    # --- LOGIKA BUY (SCALPING) ---
    # 1. Trend: Harga DIATAS EMA 200 (Wajib Uptrend)
    # 2. Momentum: Stoch RSI Cross UP di area Oversold (< 20) atau area Bullish
    # 3. Volume: Ada ledakan volume
    if (close > ema200) and (k_prev < d_prev) and (k_now > d_now) and (k_now < 40) and vol_ok:
        df.loc[last_idx, 'signal'] = "SCALP BUY"
        df.loc[last_idx, 'entry_price'] = close

    # --- LOGIKA SELL (SCALPING) ---
    # 1. Trend: Harga DIBAWAH EMA 200 (Wajib Downtrend)
    # 2. Momentum: Stoch RSI Cross DOWN di area Overbought (> 80) atau area Bearish
    elif (close < ema200) and (k_prev > d_prev) and (k_now < d_now) and (k_now > 60) and vol_ok:
        df.loc[last_idx, 'signal'] = "SCALP SELL"
        df.loc[last_idx, 'entry_price'] = close
        
    return df

def get_data(symbol, tf):
    exchange = ccxt.indodax()
    # Ambil 300 candle untuk EMA 200 yang akurat
    ohlcv = exchange.fetch_ohlcv(symbol, tf, limit=300)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize('UTC').dt.tz_convert('Asia/Jakarta')
    return df, exchange.fetch_ticker(symbol)

# --- 3. VISUALISASI DASHBOARD ---
st.sidebar.header("🚀 Scalping Master Settings")
symbol = st.sidebar.selectbox("Pilih Koin", ['BTC/IDR', 'ETH/IDR', 'SOL/IDR', 'DOGE/IDR', 'XRP/IDR', 'SHIB/IDR', 'PEPE/IDR'])
timeframe = st.sidebar.selectbox("Timeframe", ['5m', '15m', '1h'])

st.title(f"Scalping Master: {symbol} ({timeframe})")

@st.fragment(run_every=60)
def main_app(sym, tf):
    try:
        # Fetch & Process
        df, ticker = get_data(sym, tf)
        df = calculate_indicators(df)
        df = detect_signals(df)
        
        # Variabel Kunci
        curr_price = float(ticker['last'])
        last_sig = df['signal'].iloc[-1]
        atr = df['ATR'].iloc[-1]
        ema_200 = df['EMA_200'].iloc[-1]
        
        # Tentukan Tren Utama
        trend_status = "UPTREND (BULLISH)" if curr_price > ema_200 else "DOWNTREND (BEARISH)"
        trend_color = "#00e676" if curr_price > ema_200 else "#ff1744"
        
        # Warna Sinyal
        sig_bg = "#1e1e1e"
        sig_col = "#aaa"
        entry_display = "-"
        sl_display = "-"
        tp_display = "-"
        
        if "BUY" in last_sig:
            sig_bg = "rgba(0, 255, 0, 0.2)"
            sig_col = "#00e676"
            entry_display = f"Rp {curr_price:,.0f}"
            sl_val = curr_price - (2 * atr) # SL Longgar (2x ATR) agar tidak kena gocek
            tp_val = curr_price + (3 * atr) # RR 1:1.5
            sl_display = f"Rp {sl_val:,.0f}"
            tp_display = f"Rp {tp_val:,.0f}"
            
        elif "SELL" in last_sig:
            sig_bg = "rgba(255, 0, 0, 0.2)"
            sig_col = "#ff1744"
            entry_display = f"Rp {curr_price:,.0f}"
            sl_val = curr_price + (2 * atr)
            tp_val = curr_price - (3 * atr)
            sl_display = f"Rp {sl_val:,.0f}"
            tp_display = f"Rp {tp_val:,.0f}"

        # Helper Format
        def fmt(x): return f"{x:,.0f}".replace(",", ".")

        # --- UI LAYOUT ---
        st.markdown(f"""
        <style>
            .grid-top {{ display: grid; grid-template-columns: 1.5fr 1fr 1fr 1fr; gap: 8px; margin-bottom: 10px; }}
            .grid-bot {{ display: grid; grid-template-columns: 1fr 1fr 1fr 1.5fr; gap: 8px; margin-bottom: 20px; }}
            .box {{ background: #1e1e1e; border: 1px solid #333; padding: 12px; border-radius: 6px; text-align: center; }}
            .sig-box {{ background: {sig_bg}; border: 2px solid {sig_col}; padding: 12px; border-radius: 6px; text-align: center; }}
            .lbl {{ font-size: 10px; color: #bbb; margin-bottom: 4px; font-weight:bold; }}
            .val {{ font-size: 16px; color: white; font-weight:bold; }}
            .val-lg {{ font-size: 20px; color: {sig_col}; font-weight:900; }}
        </style>
        
        <div class="grid-top">
            <div class="sig-box"><div class="lbl">SINYAL (EARLY)</div><div class="val-lg">{last_sig}</div></div>
            <div class="box"><div class="lbl">HARGA</div><div class="val" style="color:#f1c40f">Rp {fmt(curr_price)}</div></div>
            <div class="box"><div class="lbl">VOLUME</div><div class="val">{ticker['baseVolume']:,.0f}</div></div>
            <div class="box"><div class="lbl">TREN UTAMA (EMA 200)</div><div class="val" style="color:{trend_color}">{trend_status}</div></div>
        </div>
        
        <div class="grid-bot">
            <div class="box" style="border-top:3px solid #2979ff"><div class="lbl">ENTRY</div><div class="val" style="color:#2979ff">{entry_display}</div></div>
            <div class="box" style="border-top:3px solid #00e676"><div class="lbl">TARGET PROFIT</div><div class="val" style="color:#00e676">{tp_display}</div></div>
            <div class="box" style="border-top:3px solid #ff1744"><div class="lbl">STOP LOSS (DINAMIS)</div><div class="val" style="color:#ff1744">{sl_display}</div></div>
             <div class="box"><div class="lbl">VALIDASI</div><div class="val" style="font-size:12px">{'✅ VOL SPIKE' if df['Vol_Spike'].iloc[-1] else '⚠️ LOW VOL'} | {'✅ MOMENTUM' if (df['K'].iloc[-1] < 80 and df['K'].iloc[-1] > 20) else '⚠️ EXTREME'}</div></div>
        </div>
        """, unsafe_allow_html=True)

        # --- CHART SYSTEM ---
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
        
        # 1. Main Chart (Price + EMA)
        fig.add_trace(go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Price'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['EMA_200'], line=dict(color='yellow', width=2), name='EMA 200 (Trend)'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['EMA_50'], line=dict(color='cyan', width=1), name='EMA 50 (Fast)'), row=1, col=1)
        
        # Mark Sinyal di Chart
        buys = df[df['signal'] == "SCALP BUY"]
        sells = df[df['signal'] == "SCALP SELL"]
        if not buys.empty:
            fig.add_trace(go.Scatter(x=buys['timestamp'], y=buys['low'], mode='markers', marker=dict(symbol='triangle-up', size=12, color='#00e676'), name='BUY'), row=1, col=1)
        if not sells.empty:
            fig.add_trace(go.Scatter(x=sells['timestamp'], y=sells['high'], mode='markers', marker=dict(symbol='triangle-down', size=12, color='#ff1744'), name='SELL'), row=1, col=1)

        # 2. Subplot (Stochastic RSI)
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['K'], line=dict(color='#00e676', width=1.5), name='Stoch K'), row=2, col=1)
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['D'], line=dict(color='#ff1744', width=1.5), name='Stoch D'), row=2, col=1)
        # Garis Batas
        fig.add_hline(y=80, line_dash="dot", line_color="gray", row=2, col=1)
        fig.add_hline(y=20, line_dash="dot", line_color="gray", row=2, col=1)
        # Area Aman (Fill)
        fig.add_hrect(y0=20, y1=80, fillcolor="rgba(255,255,255,0.05)", line_width=0, row=2, col=1)

        fig.update_layout(height=600, template="plotly_dark", margin=dict(l=0,r=0,t=10,b=0), xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"Menunggu koneksi Indodax... {e}")

main_app(symbol, timeframe)
