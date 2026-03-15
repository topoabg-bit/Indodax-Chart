import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
import pytz

# --- 1. KONFIGURASI ---
st.set_page_config(layout="wide", page_title="SMC Liquidity Fix")

# --- 2. SMC ENGINE (REVISI: VECTORIZED CALCULATION) ---
def calculate_smc_logic(df):
    # A. Indikator Dasar
    # RSI (14)
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # ATR (14) untuk Stop Loss
    df['tr0'] = abs(df['high'] - df['low'])
    df['tr1'] = abs(df['high'] - df['close'].shift())
    df['tr2'] = abs(df['low'] - df['close'].shift())
    df['TR'] = df[['tr0', 'tr1', 'tr2']].max(axis=1)
    df['ATR'] = df['TR'].ewm(span=14, adjust=False).mean()

    # B. Identifikasi Swing High/Low (Fractals)
    df['is_swing_low'] = (
        (df['low'] < df['low'].shift(1)) & (df['low'] < df['low'].shift(2)) &
        (df['low'] < df['low'].shift(-1)) & (df['low'] < df['low'].shift(-2))
    )
    df['is_swing_high'] = (
        (df['high'] > df['high'].shift(1)) & (df['high'] > df['high'].shift(2)) &
        (df['high'] > df['high'].shift(-1)) & (df['high'] > df['high'].shift(-2))
    )
    
    # Forward fill untuk referensi stop loss (Menyimpan level swing terakhir di memori)
    df['prev_swing_low'] = df['low'].where(df['is_swing_low']).ffill().shift(1)
    df['prev_swing_high'] = df['high'].where(df['is_swing_high']).ffill().shift(1)

    # C. Deteksi FVG (Fair Value Gap) - FIXED
    # Kita pre-calculate nilai shift di sini agar tidak error 'numpy float' nanti
    df['high_shift2'] = df['high'].shift(2) # High candle ke-1
    df['low_shift2'] = df['low'].shift(2)   # Low candle ke-1
    
    # Bullish FVG: Low Candle 3 > High Candle 1
    # Gap Area: Bottom = High Candle 1, Top = Low Candle 3
    df['is_fvg_bull'] = (df['low'] > df['high_shift2']) & (df['close'] > df['open'])
    
    # Bearish FVG: High Candle 3 < Low Candle 1
    # Gap Area: Top = Low Candle 1, Bottom = High Candle 3
    df['is_fvg_bear'] = (df['high'] < df['low_shift2']) & (df['close'] < df['open'])

    # --- D. LOGIKA SCANNING ---
    # Ambil data terakhir untuk validasi real-time
    current_rsi = df['RSI'].iloc[-1]
    current_price = df['close'].iloc[-1]
    current_low = df['low'].iloc[-1]
    current_high = df['high'].iloc[-1]
    atr = df['ATR'].iloc[-1]
    
    signal = "WAIT"
    entry = 0.0
    stop_loss = 0.0
    tp1 = 0.0
    tp2 = 0.0
    
    # 1. SETUP BUY (SMC)
    # Cari FVG Bullish terakhir yang VALID
    bull_fvgs = df[df['is_fvg_bull']]
    
    if not bull_fvgs.empty:
        last_fvg_idx = bull_fvgs.index[-1]
        # Ambil batas FVG dari kolom yang sudah di-shift (Bukan shift manual)
        fvg_top = df.loc[last_fvg_idx, 'low']          # Low candle pembentuk
        fvg_bot = df.loc[last_fvg_idx, 'high_shift2']  # High candle 2 bar sebelumnya
        
        # Syarat: Harga masuk ke zona FVG (Retest) DAN RSI Oversold/Mulai Naik
        # Kita beri toleransi sedikit untuk retest
        if (current_low <= fvg_top) and (current_rsi < 50) and (current_rsi > 20):
            signal = "SMC BUY"
            entry = current_price
            
            # SL di bawah Swing Low struktur terakhir
            sl_ref = df['prev_swing_low'].iloc[-1]
            # Jika swing low terlalu jauh/dekat, gunakan ATR sebagai backup
            if pd.isna(sl_ref) or sl_ref > entry: 
                sl_ref = entry - (2 * atr)
            
            stop_loss = sl_ref - (0.5 * atr) # Buffer sedikit
            
            risk = entry - stop_loss
            tp1 = entry + (risk * 1.5)
            tp2 = df['prev_swing_high'].iloc[-1] 
            if pd.isna(tp2) or tp2 < entry: tp2 = entry + (risk * 3)

    # 2. SETUP SELL (SMC)
    bear_fvgs = df[df['is_fvg_bear']]
    
    if not bear_fvgs.empty:
        last_fvg_idx = bear_fvgs.index[-1]
        fvg_bot_zone = df.loc[last_fvg_idx, 'high']
        fvg_top_zone = df.loc[last_fvg_idx, 'low_shift2']
        
        if (current_high >= fvg_bot_zone) and (current_rsi > 50) and (current_rsi < 80):
            signal = "SMC SELL"
            entry = current_price
            
            sl_ref = df['prev_swing_high'].iloc[-1]
            if pd.isna(sl_ref) or sl_ref < entry:
                sl_ref = entry + (2 * atr)
                
            stop_loss = sl_ref + (0.5 * atr)
            
            risk = stop_loss - entry
            tp1 = entry - (risk * 1.5)
            tp2 = df['prev_swing_low'].iloc[-1]
            if pd.isna(tp2) or tp2 > entry: tp2 = entry - (risk * 3)

    return df, signal, entry, stop_loss, tp1, tp2

def get_data(symbol, timeframe):
    exchange = ccxt.indodax()
    ticker = exchange.fetch_ticker(symbol)
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=200)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize('UTC').dt.tz_convert('Asia/Jakarta')
    return df, ticker

# --- 3. UI DASHBOARD ---
st.sidebar.header("SMC Sniper Setup")
symbol = st.sidebar.selectbox("Pilih Koin", ['BTC/IDR', 'ETH/IDR', 'SOL/IDR', 'DOGE/IDR', 'XRP/IDR', 'SHIB/IDR'])
timeframe = st.sidebar.selectbox("Timeframe", ['15m', '1h', '4h', '1d'])

st.title(f"SMC Market Structure: {symbol}")

@st.fragment(run_every=60)
def show_dashboard(sym, tf):
    try:
        df_raw, ticker = get_data(sym, tf)
        df, signal, entry, sl, tp1, tp2 = calculate_smc_logic(df_raw)
        
        curr = float(ticker['last'])
        vol = float(ticker['baseVolume'])
        rsi_val = df['RSI'].iloc[-1]
        
        # Warna Sinyal
        sig_col = "#888"
        sig_bg = "#1e1e1e"
        if "BUY" in signal:
            sig_col = "#00e676"
            sig_bg = "rgba(0, 255, 0, 0.15)"
        elif "SELL" in signal:
            sig_col = "#ff1744"
            sig_bg = "rgba(255, 0, 0, 0.15)"

        # Format Rupiah
        def fmt(x): return f"{x:,.0f}".replace(",", ".") if x > 0 else "-"
        
        # HTML CSS Isolated
        st.markdown(f"""
        <style>
            .stat-grid {{ display: grid; grid-template-columns: 1.5fr 1fr 1fr 1fr; gap: 8px; margin-bottom: 15px; }}
            .plan-grid {{ display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 8px; margin-bottom: 20px; }}
            .box {{ background: #1e1e1e; border: 1px solid #333; padding: 10px; border-radius: 6px; text-align: center; }}
            .sig-box {{ background: {sig_bg}; border: 2px solid {sig_col}; padding: 10px; border-radius: 6px; text-align: center; }}
            .lbl {{ font-size: 10px; color: #aaa; font-weight: bold; text-transform: uppercase; margin-bottom: 4px; }}
            .val {{ font-size: 15px; color: white; font-weight: bold; }}
            .val-lg {{ font-size: 18px; color: {sig_col}; font-weight: 900; }}
        </style>
        
        <div class="stat-grid">
            <div class="sig-box"><div class="lbl">STATUS</div><div class="val-lg">{signal}</div></div>
            <div class="box"><div class="lbl">HARGA</div><div class="val" style="color:#f1c40f">Rp {fmt(curr)}</div></div>
            <div class="box"><div class="lbl">RSI (14)</div><div class="val">{rsi_val:.1f}</div></div>
            <div class="box"><div class="lbl">VOLUME</div><div class="val">{vol:,.0f}</div></div>
        </div>
        
        <div class="plan-grid">
            <div class="box" style="border-top:3px solid #f1c40f"><div class="lbl">ENTRY ZONE</div><div class="val" style="color:#f1c40f">Rp {fmt(entry)}</div></div>
            <div class="box" style="border-top:3px solid #ff1744"><div class="lbl">STOP LOSS</div><div class="val" style="color:#ff1744">Rp {fmt(sl)}</div></div>
            <div class="box" style="border-top:3px solid #00e676"><div class="lbl">TP 1 (1:1.5)</div><div class="val" style="color:#00e676">Rp {fmt(tp1)}</div></div>
            <div class="box" style="border-top:3px solid #2979ff"><div class="lbl">TP 2 (LIQ)</div><div class="val" style="color:#2979ff">Rp {fmt(tp2)}</div></div>
        </div>
        """, unsafe_allow_html=True)
        
        # CHART
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.75, 0.25])
        
        # Candle
        fig.add_trace(go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Harga'), row=1, col=1)
        
        # Markers Likuiditas
        sw_low = df[df['is_swing_low']]
        sw_high = df[df['is_swing_high']]
        fig.add_trace(go.Scatter(x=sw_low['timestamp'], y=sw_low['low'], mode='markers', marker=dict(symbol='triangle-up', color='yellow', size=5), name='Swing Low'), row=1, col=1)
        fig.add_trace(go.Scatter(x=sw_high['timestamp'], y=sw_high['high'], mode='markers', marker=dict(symbol='triangle-down', color='orange', size=5), name='Swing High'), row=1, col=1)
        
        # FVG Zones (Hanya 3 Terakhir agar chart bersih)
        bull_fvgs = df[df['is_fvg_bull']].tail(3)
        if not bull_fvgs.empty:
            # Visualisasi FVG dengan garis putus-putus vertikal di candle pembentuk
            fig.add_trace(go.Scatter(x=bull_fvgs['timestamp'], y=bull_fvgs['low'], mode='markers', marker=dict(symbol='line-ew', color='#00e676', size=15, line_width=2), name='Bullish FVG'), row=1, col=1)

        # RSI
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['RSI'], line=dict(color='#b0bec5'), name='RSI'), row=2, col=1)
        fig.add_hline(y=30, line_dash="dash", line_color="green", row=2, col=1)
        fig.add_hline(y=70, line_dash="dash", line_color="red", row=2, col=1)
        
        fig.update_layout(height=600, template="plotly_dark", margin=dict(l=0,r=0,t=30,b=0), xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True)
        
    except Exception as e:
        st.error(f"Error: {e}")

show_dashboard(symbol, timeframe)
