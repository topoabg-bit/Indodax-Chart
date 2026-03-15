import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import pytz

# --- 1. SETUP HALAMAN ---
st.set_page_config(layout="wide", page_title="RA Trading Logic: Structure & Sweep")

# --- 2. ENGINE LOGIKA (RIZKI ADITAMA STYLE) ---

def get_market_structure(df):
    """
    Menentukan Struktur Pasar (HH, HL, LH, LL)
    Menggunakan Fractal 5 candle (2 kiri, 2 kanan)
    """
    # Identifikasi Swing High (Fractal Up)
    df['is_high'] = (df['high'] > df['high'].shift(1)) & (df['high'] > df['high'].shift(2)) & \
                    (df['high'] > df['high'].shift(-1)) & (df['high'] > df['high'].shift(-2))
    
    # Identifikasi Swing Low (Fractal Down)
    df['is_low'] = (df['low'] < df['low'].shift(1)) & (df['low'] < df['low'].shift(2)) & \
                   (df['low'] < df['low'].shift(-1)) & (df['low'] < df['low'].shift(-2))

    # Simpan nilai Swing Terakhir (Forward Fill untuk referensi real-time)
    df['last_high'] = df['high'].where(df['is_high']).ffill()
    df['last_low'] = df['low'].where(df['is_low']).ffill()
    
    return df

def get_htf_bias(symbol, current_tf):
    """
    Logika Konfirmasi Multi Time Frame (MTF)
    Jika TF 15m -> Cek TF 1h. Jika TF 1h -> Cek TF 4h.
    Bias ditentukan oleh posisi harga terhadap EMA 50 dan Struktur Terakhir.
    """
    tf_map = {'15m': '1h', '1h': '4h', '4h': '1d'}
    htf = tf_map.get(current_tf, '1d')
    
    exchange = ccxt.indodax()
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, htf, limit=100)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Simple Bias: Harga diatas EMA 50 = Bullish, Dibawah = Bearish
        ema50 = df['close'].ewm(span=50).mean().iloc[-1]
        curr = df['close'].iloc[-1]
        
        return "BULLISH" if curr > ema50 else "BEARISH", htf
    except:
        return "NEUTRAL", htf

def detect_sweep_entry(df, htf_bias):
    """
    Logika Inti Entry: LIQUIDITY SWEEP + SnD
    """
    last_idx = df.index[-1]
    curr_row = df.iloc[-1]
    prev_row = df.iloc[-2] # Candle yang baru close (konfirmasi)
    
    signal = "WAITING"
    entry_price = 0
    sl_price = 0
    tp_price = 0
    setup_valid = False
    
    # Ambil Struktur Swing Terakhir (Likuiditas)
    # Kita lihat Swing Low/High valid SEBELUM candle saat ini
    # Shift 3 karena fractal butuh 2 candle kanan untuk confirm, kita cari swing lama
    recent_swing_low = df['last_low'].iloc[-5] 
    recent_swing_high = df['last_high'].iloc[-5]
    
    if pd.isna(recent_swing_low) or pd.isna(recent_swing_high):
        return signal, 0, 0, 0, False

    # --- SKENARIO BUY (BULLISH) ---
    # Syarat:
    # 1. HTF Bias harus BULLISH
    # 2. Harga menusuk Swing Low (Sweep Liquidity)
    # 3. Tapi Close kembali diatas Swing Low (Reject)
    # 4. Terbentuk Demand Zone (Candle Merah terakhir sebelum naik)
    
    if htf_bias == "BULLISH":
        # Cek Sweep pada candle sebelumnya (prev_row) atau 2 candle lalu
        # Low candle < Swing Low TAPI Close candle > Swing Low
        is_sweep = (prev_row['low'] < recent_swing_low) and (prev_row['close'] > recent_swing_low)
        
        if is_sweep:
            signal = "BUY (LIQUIDITY SWEEP)"
            setup_valid = True
            
            # ENTRY: Di area Body candle sweep (Demand Zone)
            # Atau agresif di Open candle baru
            entry_price = prev_row['close'] 
            
            # SL: Di bawah ekor sweep (titik terendah manipulasi)
            sl_price = prev_row['low'] 
            
            # TP: RR 1:2
            risk = entry_price - sl_price
            tp_price = entry_price + (risk * 2)

    # --- SKENARIO SELL (BEARISH) ---
    elif htf_bias == "BEARISH":
        # High candle > Swing High TAPI Close candle < Swing High
        is_sweep = (prev_row['high'] > recent_swing_high) and (prev_row['close'] < recent_swing_high)
        
        if is_sweep:
            signal = "SELL (LIQUIDITY SWEEP)"
            setup_valid = True
            
            entry_price = prev_row['close']
            sl_price = prev_row['high'] # Di atas ekor sweep
            
            risk = sl_price - entry_price
            tp_price = entry_price - (risk * 2)
            
    return signal, entry_price, sl_price, tp_price, setup_valid

def get_data(symbol, tf):
    exchange = ccxt.indodax()
    ohlcv = exchange.fetch_ohlcv(symbol, tf, limit=200)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize('UTC').dt.tz_convert('Asia/Jakarta')
    ticker = exchange.fetch_ticker(symbol)
    return df, ticker

# --- 3. DASHBOARD VISUAL ---
st.sidebar.header("Strategy: Rizki Aditama")
symbol = st.sidebar.selectbox("Pair", ['BTC/IDR', 'ETH/IDR', 'SOL/IDR', 'DOGE/IDR', 'XRP/IDR', 'SHIB/IDR'])
timeframe = st.sidebar.selectbox("Timeframe", ['15m', '1h', '4h'])

st.title(f"🏛️ Market Structure & Sweep: {symbol}")

@st.fragment(run_every=60)
def show_dashboard(sym, tf):
    try:
        # 1. Fetch & Process
        df, ticker = get_data(sym, tf)
        df = get_market_structure(df)
        htf_bias, htf_label = get_htf_bias(sym, tf)
        
        # 2. Logic Entry
        sig_text, entry, sl, tp, is_valid = detect_sweep_entry(df, htf_bias)
        
        # 3. Realtime Var
        curr = float(ticker['last'])
        vol = float(ticker['baseVolume'])
        high_24 = float(ticker['high'])
        low_24 = float(ticker['low'])
        
        # Warna
        sig_col = "#777"
        sig_bg = "#1e1e1e"
        if "BUY" in sig_text:
            sig_col = "#00e676"
            sig_bg = "rgba(0, 255, 0, 0.2)"
        elif "SELL" in sig_text:
            sig_col = "#ff1744"
            sig_bg = "rgba(255, 0, 0, 0.2)"
            
        def fmt(x): return f"{x:,.0f}".replace(",", ".") if x > 0 else "-"

        # --- LAYOUT ATAS (PASAR) ---
        st.markdown(f"""
        <style>
            .grid-row {{ display: grid; grid-template-columns: 1.5fr 1fr 1fr 1fr 1fr; gap: 8px; margin-bottom: 10px; }}
            .grid-plan {{ display: grid; grid-template-columns: 1fr 1fr 1fr 1.5fr; gap: 8px; margin-bottom: 20px; }}
            .box {{ background: #1e1e1e; border: 1px solid #333; padding: 10px; border-radius: 6px; text-align: center; }}
            .sig-box {{ background: {sig_bg}; border: 2px solid {sig_col}; padding: 10px; border-radius: 6px; text-align: center; }}
            .lbl {{ font-size: 9px; color: #aaa; font-weight: bold; margin-bottom: 4px; text-transform: uppercase; }}
            .val {{ font-size: 14px; color: white; font-weight: bold; }}
            .val-lg {{ font-size: 16px; color: {sig_col}; font-weight: 900; }}
        </style>
        
        <div class="grid-row">
            <div class="sig-box"><div class="lbl">SINYAL ({tf})</div><div class="val-lg">{sig_text}</div></div>
            <div class="box"><div class="lbl">HARGA</div><div class="val" style="color:#f1c40f">Rp {fmt(curr)}</div></div>
            <div class="box"><div class="lbl">LOW 24H</div><div class="val" style="color:#ff1744">{fmt(low_24)}</div></div>
            <div class="box"><div class="lbl">HIGH 24H</div><div class="val" style="color:#00e676">{fmt(high_24)}</div></div>
            <div class="box"><div class="lbl">VOLUME</div><div class="val">{vol:,.0f}</div></div>
        </div>
        
        <div class="grid-plan">
            <div class="box" style="border-top: 3px solid #2979ff">
                <div class="lbl">ENTRY (SWEEP ZONE)</div>
                <div class="val" style="color:#2979ff">Rp {fmt(entry)}</div>
            </div>
            <div class="box" style="border-top: 3px solid #00e676">
                <div class="lbl">TP (RR 1:2)</div>
                <div class="val" style="color:#00e676">Rp {fmt(tp)}</div>
            </div>
            <div class="box" style="border-top: 3px solid #ff1744">
                <div class="lbl">SL (SWING LOW)</div>
                <div class="val" style="color:#ff1744">Rp {fmt(sl)}</div>
            </div>
            <div class="box">
                <div class="lbl">KONFIRMASI MTF ({htf_label})</div>
                <div class="val" style="color:{'#00e676' if htf_bias=='BULLISH' else '#ff1744'}">{htf_bias}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        # --- CHART ---
        fig = make_subplots(rows=1, cols=1)
        
        # 1. Candlestick
        fig.add_trace(go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Price'))
        
        # 2. Market Structure (Fractals) - Titik Likuiditas
        highs = df[df['is_high']]
        lows = df[df['is_low']]
        
        fig.add_trace(go.Scatter(x=highs['timestamp'], y=highs['high'], mode='markers', marker=dict(symbol='triangle-down', size=8, color='orange'), name='Swing High (Liq)'))
        fig.add_trace(go.Scatter(x=lows['timestamp'], y=lows['low'], mode='markers', marker=dict(symbol='triangle-up', size=8, color='yellow'), name='Swing Low (Liq)'))
        
        # 3. Gambar Plan Jika Valid
        if is_valid:
            # Garis Entry
            fig.add_hline(y=entry, line_dash="solid", line_color="blue", annotation_text="ENTRY", line_width=1)
            # Garis SL
            fig.add_hline(y=sl, line_dash="dash", line_color="red", annotation_text="STOP LOSS", line_width=1)
            # Garis TP
            fig.add_hline(y=tp, line_dash="dash", line_color="green", annotation_text="TAKE PROFIT (1:2)", line_width=1)
            
            # Arrow Sinyal
            fig.add_trace(go.Scatter(
                x=[df['timestamp'].iloc[-1]], 
                y=[entry], 
                mode='markers', 
                marker=dict(symbol='star', size=15, color='cyan'),
                name='SIGNAL TRIGGER'
            ))

        fig.update_layout(height=500, template="plotly_dark", margin=dict(l=0,r=0,t=10,b=0), xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True)
        
        # --- TABEL ZONA SUPPLY DEMAND & SWEEP ---
        st.subheader("📋 Catatan Struktur Pasar (Supply/Demand)")
        
        # Buat list swing terakhir untuk referensi
        struct_data = []
        last_h = highs.tail(3)
        last_l = lows.tail(3)
        
        for i, row in last_h.iterrows():
            struct_data.append(["Swing High (Likuiditas Atas)", fmt(row['high']), row['timestamp'].strftime('%H:%M')])
        for i, row in last_l.iterrows():
            struct_data.append(["Swing Low (Likuiditas Bawah)", fmt(row['low']), row['timestamp'].strftime('%H:%M')])
            
        df_struct = pd.DataFrame(struct_data, columns=["Tipe Struktur", "Harga Level", "Waktu Terbentuk"])
        st.table(df_struct.sort_values(by="Waktu Terbentuk", ascending=False))

    except Exception as e:
        st.error(f"Menunggu pembentukan struktur pasar... ({e})")

show_dashboard(symbol, timeframe)
