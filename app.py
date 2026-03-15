import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import pytz

# --- 1. KONFIGURASI ---
st.set_page_config(layout="wide", page_title="Scalping Pro: Trend + SMC")

# --- 2. ENGINE PERHITUNGAN ---
def get_htf_trend(symbol, ltf_timeframe):
    """
    Mengambil data Timeframe yang lebih tinggi (2 tingkat diatas) 
    untuk Filter Trend.
    15m -> 1h, 1h -> 4h, 4h -> 1d
    """
    tf_map = {'15m': '1h', '1h': '4h', '4h': '1d', '1d': '1w'}
    htf = tf_map.get(ltf_timeframe, '1d')
    
    exchange = ccxt.indodax()
    ohlcv = exchange.fetch_ohlcv(symbol, htf, limit=50)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    # Menghitung EMA 50 pada HTF sebagai Trend Baseline
    df['HTF_EMA'] = df['close'].ewm(span=50, adjust=False).mean()
    
    # Return Trend terakhir: Bullish/Bearish & Nilai EMA
    last_row = df.iloc[-1]
    trend = "BULLISH" if last_row['close'] > last_row['HTF_EMA'] else "BEARISH"
    return trend, last_row['HTF_EMA']

def get_daily_pivot(symbol):
    """Mengambil Pivot Point Harian untuk Magnet Harga"""
    exchange = ccxt.indodax()
    # Ambil candle kemarin (Daily)
    ohlcv = exchange.fetch_ohlcv(symbol, '1d', limit=2) 
    prev_day = ohlcv[-2] # Candle kemarin yang sudah close
    
    high = prev_day[2]
    low = prev_day[3]
    close = prev_day[4]
    
    pivot = (high + low + close) / 3
    r1 = (2 * pivot) - low
    s1 = (2 * pivot) - high
    return pivot, r1, s1

def process_scalping_logic(df, htf_ema_val):
    # 1. Indikator Dasar
    # RSI (Filter Pucuk)
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # Volume MA (Filter Volume)
    df['VOL_MA'] = df['volume'].rolling(window=20).mean()

    # 2. Struktur Pasar (Price Action 21 Period)
    # Mencari Atap (Highest High) dan Lantai (Lowest Low) dalam 21 bar terakhir
    df['HH_21'] = df['high'].rolling(window=21).max().shift(1) # Shift 1 agar tidak repainting
    df['LL_21'] = df['low'].rolling(window=21).min().shift(1)
    
    # 3. Pivot Structure (Fractals - Deteksi Dini)
    # Fractal High: High di tengah lebih tinggi dari 2 kiri dan 2 kanan
    df['is_fractal_high'] = (df['high'] > df['high'].shift(1)) & (df['high'] > df['high'].shift(2)) & \
                            (df['high'] > df['high'].shift(-1)) & (df['high'] > df['high'].shift(-2))
    # Propagasi nilai Fractal High terakhir ke baris saat ini (Last Swing High)
    df['LAST_SWING_HIGH'] = df['high'].where(df['is_fractal_high']).ffill()

    # 4. Smart Money FVG (Auto Cleaning)
    # Logika: Gap antara Low candle i dan High candle i-2
    df['fvg_bull_cond'] = (df['low'] > df['high'].shift(2)) & (df['close'] > df['open'])
    df['bull_top'] = df['low']
    df['bull_bot'] = df['high'].shift(2)
    
    # 5. LOGIKA SINYAL ENTRY
    df['signal'] = "NEUTRAL"
    
    # Loop iterasi manual untuk FVG Cleaning & Signal Confirmation (Simulasi Realtime)
    # Kita hanya iterasi 5 candle terakhir untuk efisiensi
    last_indices = df.index[-5:]
    
    for i in last_indices:
        close = df.loc[i, 'close']
        vol = df.loc[i, 'volume']
        vol_ma = df.loc[i, 'VOL_MA']
        swing_high = df.loc[i, 'LAST_SWING_HIGH']
        hh_21 = df.loc[i, 'HH_21']
        
        # A. KONDISI TRENDING (Follow Trend)
        # Harga > HTF EMA (Filter) + Breakout HH 21 + Volume Kuat
        if (close > htf_ema_val) and (close > hh_21) and (vol > vol_ma) and (df.loc[i, 'RSI'] < 70):
            df.loc[i, 'signal'] = "TREND BUY"
            
        # B. KONDISI REVERSAL (Early Entry)
        # Harga Breakout Swing High Terakhir (ChoCh) + Volume Kuat (Walaupun dibawah HTF EMA)
        elif (close > swing_high) and (vol > vol_ma) and (close < htf_ema_val):
            df.loc[i, 'signal'] = "REVERSAL BUY"
            
    return df

def get_active_fvgs(df):
    """
    Logika AUTO CLEANING:
    Hanya mengembalikan FVG yang:
    1. Fresh (Belum tersentuh/mitigated oleh candle setelahnya)
    2. Tidak terlalu tua (Maksimal 50 candle ke belakang untuk scalping)
    """
    bull_zones = []
    
    # Ambil semua kandidat FVG
    candidates = df[df['fvg_bull_cond']]
    
    # Loop dari yang paling baru ke lama
    for idx in reversed(candidates.index):
        # Batas Waktu (Expiry)
        if idx < df.index[-50]: 
            break
            
        top = df.loc[idx, 'bull_top']
        bot = df.loc[idx, 'bull_bot']
        
        # Cek Mitigasi: Apakah ada candle SETELAH pembentukan FVG ini yang Low-nya menembus Top FVG?
        # Ambil slice data masa depan relatif terhadap FVG ini
        future_data = df.loc[idx+1:]
        
        if future_data.empty:
            is_mitigated = False
        else:
            # Jika ada Low candle masa depan yang <= Top FVG, berarti celah sudah diisi
            is_mitigated = (future_data['low'] <= top).any()
            
        if not is_mitigated:
            bull_zones.append({
                'time': df.loc[idx, 'timestamp'],
                'top': top,
                'bot': bot
            })
            # Limit max 3 zona terdekat agar chart bersih
            if len(bull_zones) >= 3: break
            
    return bull_zones

def fetch_data(symbol, timeframe):
    exchange = ccxt.indodax()
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=100)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize('UTC').dt.tz_convert('Asia/Jakarta')
    return df, exchange.fetch_ticker(symbol)

# --- 3. DASHBOARD VISUAL ---
st.sidebar.header("⚙️ Scalping Parameters")
symbol = st.sidebar.selectbox("Aset", ['BTC/IDR', 'ETH/IDR', 'SOL/IDR', 'DOGE/IDR', 'XRP/IDR', 'SHIB/IDR', 'PEPE/IDR'])
timeframe = st.sidebar.selectbox("Timeframe", ['15m', '1h', '4h'])

st.title(f"⚡ Scalping Terminal: {symbol}")

@st.fragment(run_every=30)
def show_dashboard(sym, tf):
    try:
        # 1. Fetch Data Utama & Pendukung
        df, ticker = fetch_data(sym, tf)
        htf_trend_dir, htf_ema_val = get_htf_trend(sym, tf)
        pivot, r1, s1 = get_daily_pivot(sym)
        
        # 2. Kalkulasi
        df = process_scalping_logic(df, htf_ema_val)
        active_fvgs = get_active_fvgs(df)
        
        # 3. Data Terkini
        curr_price = float(ticker['last'])
        last_signal = df['signal'].iloc[-1]
        if last_signal == "NEUTRAL" and df['signal'].iloc[-2] != "NEUTRAL":
            last_signal = df['signal'].iloc[-2] # Cek 1 candle belakang
            
        # Warna & Status
        trend_color = "#00e676" if htf_trend_dir == "BULLISH" else "#ff1744"
        sig_bg = "#1e1e1e"
        sig_col = "#aaa"
        
        if "BUY" in last_signal:
            sig_bg = "rgba(0, 255, 0, 0.2)"
            sig_col = "#00e676"
            
        # --- HEADER METRICS ---
        st.markdown(f"""
        <style>
            .metric-container {{ display: flex; gap: 10px; margin-bottom: 20px; }}
            .card {{ flex: 1; background: #1e1e1e; border: 1px solid #333; padding: 15px; border-radius: 8px; text-align: center; }}
            .lbl {{ font-size: 10px; color: #888; margin-bottom: 5px; font-weight: bold; text-transform: uppercase; }}
            .val {{ font-size: 18px; font-weight: bold; color: white; }}
            .sig-val {{ font-size: 20px; font-weight: 900; color: {sig_col}; }}
        </style>
        
        <div class="metric-container">
            <div class="card" style="background: {sig_bg}; border: 1px solid {sig_col};">
                <div class="lbl">SINYAL SCALPING</div>
                <div class="sig-val">{last_signal}</div>
            </div>
            <div class="card">
                <div class="lbl">HARGA ({htf_trend_dir})</div>
                <div class="val" style="color:{trend_color}">Rp {curr_price:,.0f}</div>
            </div>
            <div class="card">
                <div class="lbl">MAGNET PIVOT (DAILY)</div>
                <div class="val" style="color: #29b6f6;">Rp {pivot:,.0f}</div>
            </div>
             <div class="card">
                <div class="lbl">STRUKTUR BREAKOUT</div>
                <div class="val" style="color: #ffb74d;">Rp {df['HH_21'].iloc[-1]:,.0f}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # --- CHARTING ---
        fig = make_subplots(rows=1, cols=1)
        
        # 1. Candlestick
        fig.add_trace(go.Candlestick(
            x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close'],
            name='Price'
        ))
        
        # 2. HTF Trend Filter (Garis Putus-Putus sebagai Batas)
        fig.add_hline(y=htf_ema_val, line_dash="dash", line_color=trend_color, annotation_text=f"HTF TREND FILTER ({htf_trend_dir})", annotation_position="bottom right")

        # 3. Pivot Magnet (Garis Biru Tipis)
        fig.add_hline(y=pivot, line_width=1, line_color="#29b6f6", annotation_text="DAILY PIVOT (MAGNET)", annotation_position="top right")

        # 4. FVG Boxes (Fresh Only)
        for fvg in active_fvgs:
            # Gambar Kotak Transparan
            fig.add_shape(type="rect",
                x0=fvg['time'], y0=fvg['bot'], 
                x1=df['timestamp'].iloc[-1] + timedelta(minutes=30*4), # Extends ke kanan
                y1=fvg['top'],
                fillcolor="rgba(0, 230, 118, 0.2)", line=dict(width=0), # Hijau Transparan
            )
            # Label Harga FVG
            fig.add_annotation(x=fvg['time'], y=fvg['top'], text="FVG", showarrow=False, yshift=5, font=dict(size=8, color="#00e676"))

        # 5. Sinyal Entry Arrows
        buys = df[df['signal'].str.contains("BUY")]
        if not buys.empty:
            fig.add_trace(go.Scatter(
                x=buys['timestamp'], y=buys['low'], mode='markers', 
                marker=dict(symbol='triangle-up', size=12, color='#00e676'), name='Buy Signal'
            ))

        fig.update_layout(
            height=550, template="plotly_dark", margin=dict(l=0,r=0,t=10,b=0), 
            xaxis_rangeslider_visible=False,
            title_text=""
        )
        st.plotly_chart(fig, use_container_width=True)
        
        # Penjelasan Logic
        st.caption(f"""
        **Logika Scalping:**
        1. **Trend Filter:** Menggunakan EMA 50 pada Timeframe diatasnya (Saat ini: Harga {'DIATAS' if curr_price > htf_ema_val else 'DIBAWAH'} Filter).
        2. **Structure:** Breakout High 21-Bar terakhir di Rp {df['HH_21'].iloc[-1]:,.0f}.
        3. **Smart Money:** Kotak Hijau adalah area 'Celah Harga' yang belum diisi (Fresh FVG). Bagus untuk entry retest.
        """)

    except Exception as e:
        st.error(f"Memproses data pasar... {e}")

show_dashboard(symbol, timeframe)
