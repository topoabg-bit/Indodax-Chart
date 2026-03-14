import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
import pytz

# --- 1. KONFIGURASI ---
st.set_page_config(layout="wide", page_title="SMC Liquidity Hunter")

# --- 2. SMC ENGINE (LOGIC INTI) ---
def calculate_smc_logic(df):
    # A. Indikator Dasar
    # RSI (14)
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # ATR (14) untuk Stop Loss Dinamis
    df['tr0'] = abs(df['high'] - df['low'])
    df['tr1'] = abs(df['high'] - df['close'].shift())
    df['tr2'] = abs(df['low'] - df['close'].shift())
    df['TR'] = df[['tr0', 'tr1', 'tr2']].max(axis=1)
    df['ATR'] = df['TR'].ewm(span=14, adjust=False).mean()

    # B. Identifikasi Swing High/Low (Fractals 5 Candle)
    # Swing Low: Candle tengah lebih rendah dari 2 kiri dan 2 kanan
    df['is_swing_low'] = (
        (df['low'] < df['low'].shift(1)) & (df['low'] < df['low'].shift(2)) &
        (df['low'] < df['low'].shift(-1)) & (df['low'] < df['low'].shift(-2))
    )
    # Swing High
    df['is_swing_high'] = (
        (df['high'] > df['high'].shift(1)) & (df['high'] > df['high'].shift(2)) &
        (df['high'] > df['high'].shift(-1)) & (df['high'] > df['high'].shift(-2))
    )
    
    # Propagasi nilai Swing terakhir ke baris berikutnya (Forward fill) untuk referensi likuiditas
    df['prev_swing_low'] = df['low'].where(df['is_swing_low']).ffill().shift(1)
    df['prev_swing_high'] = df['high'].where(df['is_swing_high']).ffill().shift(1)

    # C. Deteksi FVG (Fair Value Gap)
    # Bullish FVG: Gap antara High Candle-1 dan Low Candle-3
    df['fvg_bull_top'] = df['low'].shift(-1) # Candle masa depan (karena shift logic) - disesuaikan logic array
    df['fvg_bull_bot'] = df['high'].shift(1)
    df['is_fvg_bull'] = (df['low'] > df['high'].shift(2)) & (df['close'] > df['open']) # Logic Simplified: Gap Exist
    
    # Bearish FVG
    df['is_fvg_bear'] = (df['high'] < df['low'].shift(2)) & (df['close'] < df['open'])

    # --- D. LOGIKA SINYAL (SCANNING) ---
    df['signal_action'] = "WAIT"
    df['signal_reason'] = ""
    
    # Iterasi manual untuk logika sequence (Sweep -> FVG -> Entry)
    # Kita hanya cek 10 candle terakhir untuk efisiensi real-time
    last_idx = df.index[-1]
    
    current_rsi = df['RSI'].iloc[-1]
    current_price = df['close'].iloc[-1]
    atr = df['ATR'].iloc[-1]
    
    # Setup Variables
    signal = "WAIT"
    entry = 0
    stop_loss = 0
    tp1 = 0
    tp2 = 0
    
    # 1. SETUP BUY (SMC)
    # Syarat: RSI baru keluar dari Oversold (<35) + Harga menyentuh area FVG Bullish terakhir
    
    # Cari FVG Bullish terdekat yang valid
    last_fvg_bull_idx = df[df['is_fvg_bull']].index[-1] if df['is_fvg_bull'].any() else None
    
    if last_fvg_bull_idx:
        fvg_top = df.loc[last_fvg_bull_idx, 'low'] # Low candle ke-3 (Current candle di logic FVG)
        fvg_bot = df.loc[last_fvg_bull_idx, 'high'].shift(2) # High candle ke-1
        
        # Cek apakah harga sekarang sedang retest FVG ini?
        # Dan RSI Bullish (Baru naik dari 30)
        if (df['low'].iloc[-1] <= fvg_top) and (current_rsi < 45) and (current_rsi > 25):
            signal = "SMC BUY"
            entry = current_price
            
            # SL: Swing Low Terakhir - (1.5 x ATR)
            last_sw_low = df['prev_swing_low'].iloc[-1]
            stop_loss = last_sw_low - (1.5 * atr)
            
            # TP Calculation
            risk = entry - stop_loss
            tp1 = entry + (risk * 1.5) # Rasio 1:1.5
            tp2 = df['prev_swing_high'].iloc[-1] # Target Likuiditas (High sebelumnya)

    # 2. SETUP SELL (SMC)
    # Cari FVG Bearish
    last_fvg_bear_idx = df[df['is_fvg_bear']].index[-1] if df['is_fvg_bear'].any() else None
    
    if last_fvg_bear_idx:
        fvg_bot = df.loc[last_fvg_bear_idx, 'high'] 
        
        # Cek Retest + RSI Overbought
        if (df['high'].iloc[-1] >= fvg_bot) and (current_rsi > 55) and (current_rsi < 75):
            signal = "SMC SELL"
            entry = current_price
            
            last_sw_high = df['prev_swing_high'].iloc[-1]
            stop_loss = last_sw_high + (1.5 * atr)
            
            risk = stop_loss - entry
            tp1 = entry - (risk * 1.5)
            tp2 = df['prev_swing_low'].iloc[-1]

    return df, signal, entry, stop_loss, tp1, tp2

def get_data(symbol, timeframe):
    exchange = ccxt.indodax()
    ticker = exchange.fetch_ticker(symbol)
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=100)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize('UTC').dt.tz_convert('Asia/Jakarta')
    return df, ticker

# --- 3. DASHBOARD UI ---
st.sidebar.header("🛠️ SMC Setup")
symbol = st.sidebar.selectbox("Market", ['BTC/IDR', 'ETH/IDR', 'SOL/IDR', 'DOGE/IDR', 'XRP/IDR', 'SHIB/IDR', 'PEPE/IDR'])
timeframe = st.sidebar.selectbox("Timeframe", ['15m', '1h', '4h', '1d'])

st.title(f"🦅 SMC Liquidity Hunter: {symbol}")

@st.fragment(run_every=60)
def main_dashboard(sym, tf):
    try:
        # Fetch & Calculate
        df_raw, ticker = get_data(sym, tf)
        df, signal, entry, sl, tp1, tp2 = calculate_smc_logic(df_raw)
        
        # Data Realtime
        curr = float(ticker['last'])
        vol = float(ticker['baseVolume'])
        rsi_now = df['RSI'].iloc[-1]
        
        # Styling Logic
        sig_color = "#888"
        sig_bg = "#1e1e1e"
        
        if "BUY" in signal:
            sig_color = "#00e676"
            sig_bg = "rgba(0, 255, 0, 0.15)"
        elif "SELL" in signal:
            sig_color = "#ff1744"
            sig_bg = "rgba(255, 0, 0, 0.15)"
            
        # Helper Format
        def fmt(x): return f"{x:,.0f}".replace(",", ".")
        def fmt_dec(x): return f"{x:,.2f}".replace(".", ",")

        # --- HTML COMPONENT ---
        st.markdown(f"""
        <style>
            .grid-container {{ display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 10px; margin-bottom: 15px; }}
            .plan-container {{ display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 10px; margin-bottom: 20px; }}
            .card {{ background: #1e1e1e; padding: 12px; border-radius: 8px; border: 1px solid #333; text-align: center; }}
            .card-sig {{ background: {sig_bg}; padding: 12px; border-radius: 8px; border: 2px solid {sig_color}; text-align: center; }}
            
            .lbl {{ font-size: 10px; color: #aaa; text-transform: uppercase; font-weight: bold; letter-spacing: 0.5px; }}
            .val {{ font-size: 16px; color: white; font-weight: bold; }}
            .val-lg {{ font-size: 18px; color: {sig_color}; font-weight: 900; }}
            
            .badge {{ font-size: 10px; padding: 2px 6px; border-radius: 4px; background: #333; color: #fff; }}
        </style>
        
        <!-- ROW 1: MARKET STATUS -->
        <div class="grid-container">
            <div class="card-sig">
                <div class="lbl">STATUS SINYAL</div>
                <div class="val-lg">{signal}</div>
            </div>
            <div class="card">
                <div class="lbl">HARGA SAAT INI</div>
                <div class="val" style="color:#f1c40f;">Rp {fmt(curr)}</div>
            </div>
             <div class="card">
                <div class="lbl">RSI (14)</div>
                <div class="val">{fmt_dec(rsi_now)}</div>
            </div>
            <div class="card">
                <div class="lbl">VOL (24J)</div>
                <div class="val">{fmt(vol)}</div>
            </div>
        </div>
        
        <!-- ROW 2: TRADING PLAN (Hanya Muncul jika ada Sinyal) -->
        <div class="plan-container">
            <div class="card" style="border-top: 3px solid #f1c40f;">
                <div class="lbl">ENTRY (FVG REACTION)</div>
                <div class="val" style="color:#f1c40f;">{fmt(entry) if entry > 0 else "-"}</div>
            </div>
            <div class="card" style="border-top: 3px solid #ff1744;">
                <div class="lbl">STOP LOSS (1.5x ATR)</div>
                <div class="val" style="color:#ff1744;">{fmt(sl) if sl > 0 else "-"}</div>
            </div>
             <div class="card" style="border-top: 3px solid #00e676;">
                <div class="lbl">TP 1 (RASIO 1:1.5)</div>
                <div class="val" style="color:#00e676;">{fmt(tp1) if tp1 > 0 else "-"}</div>
            </div>
            <div class="card" style="border-top: 3px solid #00b0ff;">
                <div class="lbl">TP 2 (LIQUIDITY)</div>
                <div class="val" style="color:#00b0ff;">{fmt(tp2) if tp2 > 0 else "-"}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        # --- VISUALISASI CHART SMC ---
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.75, 0.25])
        
        # 1. Candlestick
        fig.add_trace(go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Price'), row=1, col=1)
        
        # 2. Swing High/Low Markers (Liquidity Points)
        sw_lows = df[df['is_swing_low']]
        sw_highs = df[df['is_swing_high']]
        
        fig.add_trace(go.Scatter(x=sw_lows['timestamp'], y=sw_lows['low'], mode='markers', marker=dict(symbol='triangle-up', color='yellow', size=6), name='Swing Low (Liq)'), row=1, col=1)
        fig.add_trace(go.Scatter(x=sw_highs['timestamp'], y=sw_highs['high'], mode='markers', marker=dict(symbol='triangle-down', color='orange', size=6), name='Swing High (Liq)'), row=1, col=1)

        # 3. FVG Visualization (Rectangle Zones)
        # Menggambar 5 FVG terakhir agar chart tidak kotor
        bullish_fvgs = df[df['is_fvg_bull']].tail(5)
        bearish_fvgs = df[df['is_fvg_bear']].tail(5)
        
        # Logic menggambar kotak FVG membutuhkan trik shape di Plotly
        # Kita pakai Scatter baris putus-putus untuk menandai zona FVG
        if not bullish_fvgs.empty:
             fig.add_trace(go.Scatter(x=bullish_fvgs['timestamp'], y=bullish_fvgs['low'], mode='markers', marker=dict(symbol='line-ns', color='rgba(0,255,0,0.5)', line_width=2, size=20), name='Bullish FVG Zone'), row=1, col=1)
        
        # 4. RSI Confirmation
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['RSI'], line=dict(color='#a4a4a4', width=1.5), name='RSI'), row=2, col=1)
        # Garis Batas 30 dan 70
        fig.add_hline(y=30, line_dash="dash", line_color="green", row=2, col=1)
        fig.add_hline(y=70, line_dash="dash", line_color="red", row=2, col=1)

        fig.update_layout(height=600, template="plotly_dark", margin=dict(l=0,r=0,t=30,b=0), xaxis_rangeslider_visible=False, title="SMC Structure Analysis")
        st.plotly_chart(fig, use_container_width=True)
        
    except Exception as e:
        st.error(f"Sedang memindai struktur pasar... ({e})")

main_dashboard(symbol, timeframe)
