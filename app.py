import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import pytz

# --- 1. SETUP HALAMAN ---
st.set_page_config(layout="wide", page_title="SMC Scalping Pro")

# --- 2. CORE LOGIC (SMC ENGINE) ---
def process_data(df):
    # 1. RSI & ATR
    df['delta'] = df['close'].diff()
    df['gain'] = (df['delta'].where(df['delta'] > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    df['loss'] = (-df['delta'].where(df['delta'] < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    df['rs'] = df['gain'] / df['loss']
    df['RSI'] = 100 - (100 / (1 + df['rs']))
    
    # ATR
    df['tr'] = np.maximum(df['high'] - df['low'], 
                          np.maximum(abs(df['high'] - df['close'].shift()), 
                                     abs(df['low'] - df['close'].shift())))
    df['ATR'] = df['tr'].ewm(span=14).mean()

    # 2. DETEKSI FVG (Fair Value Gap)
    # Kita butuh data Shifted untuk membandingkan candle i, i-1, i-2
    # Candle i (Current formation), Gap ada di antara i (low/high) dan i-2 (high/low)
    
    # Bullish FVG: Low[i] > High[i-2]
    df['fvg_bull_cond'] = (df['low'] > df['high'].shift(2)) & (df['close'] > df['open'])
    df['bull_top'] = df['low']            # Batas Atas Zona Buy
    df['bull_bot'] = df['high'].shift(2)  # Batas Bawah Zona Buy
    
    # Bearish FVG: High[i] < Low[i-2]
    df['fvg_bear_cond'] = (df['high'] < df['low'].shift(2)) & (df['close'] < df['open'])
    df['bear_top'] = df['low'].shift(2)   # Batas Atas Zona Sell
    df['bear_bot'] = df['high']           # Batas Bawah Zona Sell

    return df

def get_data(symbol, timeframe):
    exchange = ccxt.indodax()
    ticker = exchange.fetch_ticker(symbol)
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=150) # Limit kecil agar loading cepat untuk scalping
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize('UTC').dt.tz_convert('Asia/Jakarta')
    return df, ticker

# --- 3. VISUALISASI & DASHBOARD ---
st.sidebar.header("⚡ SMC Scalper")
symbol = st.sidebar.selectbox("Market", ['BTC/IDR', 'ETH/IDR', 'SOL/IDR', 'DOGE/IDR', 'XRP/IDR', 'SHIB/IDR', 'PEPE/IDR'])
timeframe = st.sidebar.selectbox("Timeframe", ['15m', '1h', '4h'])

st.title(f"Scalping Terminal: {symbol}")

@st.fragment(run_every=30)
def render_dashboard(sym, tf):
    try:
        df_raw, ticker = get_data(sym, tf)
        df = process_data(df_raw)
        
        # Data Terkini
        curr_price = float(ticker['last'])
        curr_rsi = df['RSI'].iloc[-1]
        curr_atr = df['ATR'].iloc[-1]
        
        # --- ALGORITMA PENCARIAN SINYAL ---
        # Kita cari FVG valid TERAKHIR (Closest to Price)
        
        signal_status = "WAITING..."
        signal_color = "#777"
        entry_zone_text = "-"
        sl_text = "-"
        tp_text = "-"
        
        # Ambil 5 FVG Bullish & Bearish terakhir
        last_bulls = df[df['fvg_bull_cond']].tail(5)
        last_bears = df[df['fvg_bear_cond']].tail(5)
        
        active_fvg = None
        fvg_type = None
        
        # Cek apakah harga ada di dalam zona Bullish FVG?
        for idx, row in last_bulls.iterrows():
            # Jika harga masuk area (Retest)
            if row['bull_bot'] <= curr_price <= row['bull_top']*1.01: # Toleransi 1%
                if curr_rsi < 50: # Konfirmasi RSI
                    signal_status = "SCALP BUY (RETEST)"
                    signal_color = "#00e676"
                    active_fvg = row
                    fvg_type = "bull"
        
        # Cek Bearish
        for idx, row in last_bears.iterrows():
            if row['bear_bot']*0.99 <= curr_price <= row['bear_top']:
                if curr_rsi > 50:
                    signal_status = "SCALP SELL (RETEST)"
                    signal_color = "#ff1744"
                    active_fvg = row
                    fvg_type = "bear"

        # --- PLAN GENERATOR ---
        def fmt(x): return f"{x:,.0f}".replace(",", ".")
        
        if active_fvg is not None:
            if fvg_type == "bull":
                entry_top = active_fvg['bull_top']
                entry_bot = active_fvg['bull_bot']
                entry_zone_text = f"{fmt(entry_bot)} - {fmt(entry_top)}"
                
                sl_val = entry_bot - (1.5 * curr_atr)
                risk = active_fvg['bull_top'] - sl_val
                tp_val = active_fvg['bull_top'] + (risk * 2) # RR 1:2
                
                sl_text = fmt(sl_val)
                tp_text = fmt(tp_val)
                
            else:
                entry_top = active_fvg['bear_top']
                entry_bot = active_fvg['bear_bot']
                entry_zone_text = f"{fmt(entry_bot)} - {fmt(entry_top)}"
                
                sl_val = entry_top + (1.5 * curr_atr)
                risk = sl_val - active_fvg['bear_bot']
                tp_val = active_fvg['bear_bot'] - (risk * 2)
                
                sl_text = fmt(sl_val)
                tp_text = fmt(tp_val)
        
        # Jika Waiting, tampilkan FVG terdekat sebagai "Next Zone"
        elif not last_bulls.empty:
             latest = last_bulls.iloc[-1]
             entry_zone_text = f"Next Buy: {fmt(latest['bull_bot'])}-{fmt(latest['bull_top'])}"
        
        # --- UI HTML ---
        st.markdown(f"""
        <style>
            .main-grid {{ display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 8px; margin-bottom: 10px; }}
            .plan-grid {{ display: grid; grid-template-columns: 1.5fr 1fr 1fr 1fr; gap: 8px; margin-bottom: 15px; }}
            .box {{ background: #1e1e1e; border: 1px solid #333; padding: 12px; border-radius: 6px; text-align: center; }}
            .sig-box {{ background: {signal_color}20; border: 2px solid {signal_color}; padding: 12px; border-radius: 6px; text-align: center; }}
            .lbl {{ font-size: 10px; color: #bbb; font-weight: bold; margin-bottom: 4px; }}
            .val {{ font-size: 16px; color: white; font-weight: bold; }}
            .val-lg {{ font-size: 18px; color: {signal_color}; font-weight: 900; }}
        </style>
        
        <div class="main-grid">
            <div class="sig-box"><div class="lbl">SIGNAL STATUS</div><div class="val-lg">{signal_status}</div></div>
            <div class="box"><div class="lbl">HARGA RUNNING</div><div class="val" style="color:#f1c40f">Rp {fmt(curr_price)}</div></div>
            <div class="box"><div class="lbl">RSI MOMENTUM</div><div class="val">{curr_rsi:.1f}</div></div>
            <div class="box"><div class="lbl">VOLATILITY (ATR)</div><div class="val">{curr_atr:,.0f}</div></div>
        </div>
        
        <div class="plan-grid">
            <div class="box" style="border-top:3px solid #2979ff">
                <div class="lbl">ENTRY ZONE (FVG AREA)</div>
                <div class="val" style="color:#2979ff; font-size:14px">{entry_zone_text}</div>
            </div>
            <div class="box" style="border-top:3px solid #ff1744">
                <div class="lbl">STOP LOSS</div>
                <div class="val" style="color:#ff1744">{sl_text}</div>
            </div>
            <div class="box" style="border-top:3px solid #00e676">
                <div class="lbl">TAKE PROFIT</div>
                <div class="val" style="color:#00e676">{tp_text}</div>
            </div>
            <div class="box">
                <div class="lbl">CONFIRMATION</div>
                <div class="val" style="font-size:12px">{'✅ RSI OK' if (fvg_type=='bull' and curr_rsi<50) or (fvg_type=='bear' and curr_rsi>50) else '⚠️ WAIT RSI'}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # --- CHARTING (CLEAN FVG AREAS) ---
        fig = make_subplots(rows=1, cols=1)
        
        # 1. Candlestick
        fig.add_trace(go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Price'))
        
        # 2. Draw FVG Boxes (Last 3 only)
        # Helper untuk gambar kotak
        def draw_fvg_box(row, type_fvg):
            t_start = row['timestamp']
            # Proyeksi kotak ke kanan (sampai candle terakhir + 5 candle depan)
            t_end = df['timestamp'].iloc[-1] + timedelta(minutes=15*5) # Estimasi visual
            
            if type_fvg == 'bull':
                y0, y1 = row['bull_bot'], row['bull_top']
                color = "rgba(0, 230, 118, 0.15)" # Hijau Transparan
                line_col = "rgba(0, 230, 118, 0.5)"
                label = f"FVG UP\n{y0:,.0f}"
            else:
                y0, y1 = row['bear_bot'], row['bear_top']
                color = "rgba(255, 23, 68, 0.15)" # Merah Transparan
                line_col = "rgba(255, 23, 68, 0.5)"
                label = f"FVG DOWN\n{y1:,.0f}"

            # Add Rectangle Shape
            fig.add_shape(type="rect",
                x0=t_start, y0=y0, x1=t_end, y1=y1,
                fillcolor=color, line=dict(color=line_col, width=1),
            )
            # Add Text Label (Di tengah kotak)
            fig.add_trace(go.Scatter(
                x=[t_start], y=[(y0+y1)/2],
                mode="text", text=[label], textposition="middle right",
                textfont=dict(size=9, color=line_col), showlegend=False
            ))

        # Loop 3 terakhir agar chart bersih
        for i, row in df[df['fvg_bull_cond']].tail(3).iterrows():
            draw_fvg_box(row, 'bull')
            
        for i, row in df[df['fvg_bear_cond']].tail(3).iterrows():
            draw_fvg_box(row, 'bear')

        # Layout
        fig.update_layout(
            height=550, 
            template="plotly_dark", 
            margin=dict(l=0,r=50,t=30,b=0), # Right margin untuk label
            xaxis_rangeslider_visible=False,
            title=dict(text="SMC Liquidity Zones", font=dict(size=12, color="#555"))
        )
        st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"Menunggu data pasar... ({e})")

render_dashboard(symbol, timeframe)
