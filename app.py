import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots  # <-- Import yang sebelumnya hilang
from datetime import datetime, timedelta
import pytz

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(layout="wide", page_title="Indodax Scalper Pro")

# --- 2. ENGINE ANALISA ---
def get_htf_trend(symbol, ltf_tf):
    """Mengambil Tren dari Timeframe lebih tinggi (Filter)"""
    tf_map = {'15m': '1h', '1h': '4h', '4h': '1d'}
    htf = tf_map.get(ltf_tf, '1h')
    
    exchange = ccxt.indodax()
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, htf, limit=50)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        # EMA 50 sebagai Trend Filter
        ema_htf = df['close'].ewm(span=50).mean().iloc[-1]
        return ema_htf, "BULLISH" if df['close'].iloc[-1] > ema_htf else "BEARISH"
    except:
        return 0, "NEUTRAL"

def process_scalping_data(df, htf_ema):
    # A. Indikator Dasar
    df['RSI'] = 100 - (100 / (1 + df['close'].diff().clip(lower=0).ewm(alpha=1/14).mean() / 
                             abs(df['close'].diff().clip(upper=0)).ewm(alpha=1/14).mean()))
    
    df['ATR'] = np.maximum(df['high'] - df['low'], 
                np.maximum(abs(df['high'] - df['close'].shift()), abs(df['low'] - df['close'].shift()))).ewm(span=14).mean()
    
    df['VOL_MA'] = df['volume'].rolling(20).mean()

    # B. Struktur Pasar (21 Candle) - Atap & Lantai Scalping
    df['HH'] = df['high'].rolling(21).max().shift(1)
    df['LL'] = df['low'].rolling(21).min().shift(1)
    
    # C. FVG Detection (Bullish Only untuk Buy)
    # Gap antara Low candle sekarang dan High candle 2 bar lalu
    df['fvg_bull'] = (df['low'] > df['high'].shift(2)) & (df['close'] > df['open'])
    df['fvg_top'] = df['low']
    df['fvg_bot'] = df['high'].shift(2)

    # D. Logika Sinyal
    df['signal'] = "WAIT"
    
    # Kondisi A: TREND FOLLOW (Aman)
    # Harga > HTF EMA + Breakout HH Struktur + Volume > Rata2
    cond_trend = (df['close'] > htf_ema) & (df['close'] > df['HH']) & (df['volume'] > df['VOL_MA'])
    
    # Kondisi B: REVERSAL (Agresif)
    # Harga < HTF EMA tapi RSI Oversold (<30) dan mulai naik + Breakout minor
    cond_rev = (df['close'] < htf_ema) & (df['RSI'] < 35) & (df['close'] > df['open']) 
    
    df.loc[cond_trend, 'signal'] = "TREND BUY"
    df.loc[cond_rev, 'signal'] = "REVERSAL BUY"
    
    return df

def get_clean_fvgs(df):
    """Auto-Cleaning Logic: Hapus FVG yang sudah tertembus/terisi"""
    clean_zones = []
    candidates = df[df['fvg_bull']]
    
    for idx in reversed(candidates.index):
        if idx < df.index[-60]: break # Expired (terlalu lama)
        
        top = df.loc[idx, 'fvg_top']
        bot = df.loc[idx, 'fvg_bot']
        
        # Cek masa depan
        future = df.loc[idx+1:]
        if future.empty:
            clean_zones.append({'time': df.loc[idx,'timestamp'], 'top': top, 'bot': bot, 'status': 'FRESH'})
            continue
            
        # Jika ada harga low masa depan yang menembus TOP, berarti sudah dijemput (Mitigated)
        if (future['low'] <= top).any():
            continue # Skip, jangan tampilkan
        else:
            clean_zones.append({'time': df.loc[idx,'timestamp'], 'top': top, 'bot': bot, 'status': 'FRESH'})
            if len(clean_zones) >= 3: break # Max 3 zona
            
    return clean_zones

def get_data(symbol, tf):
    exchange = ccxt.indodax()
    ohlcv = exchange.fetch_ohlcv(symbol, tf, limit=200)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize('UTC').dt.tz_convert('Asia/Jakarta')
    ticker = exchange.fetch_ticker(symbol)
    return df, ticker

# --- 3. TAMPILAN UTAMA ---
st.sidebar.header("Scalper Control")
symbol = st.sidebar.selectbox("Pair", ['BTC/IDR', 'ETH/IDR', 'SOL/IDR', 'DOGE/IDR', 'XRP/IDR', 'SHIB/IDR'])
timeframe = st.sidebar.selectbox("Timeframe", ['15m', '1h', '4h'])

st.title(f"⚔️ Scalping Command: {symbol}")

@st.fragment(run_every=30)
def dashboard(sym, tf):
    try:
        # 1. Proses Data
        df, ticker = get_data(sym, tf)
        htf_ema, htf_trend = get_htf_trend(sym, tf)
        df = process_scalping_data(df, htf_ema)
        fvgs = get_clean_fvgs(df)
        
        # 2. Variabel Realtime
        curr = float(ticker['last'])
        vol = float(ticker['baseVolume'])
        high_24 = float(ticker['high'])
        low_24 = float(ticker['low'])
        last_sig = df['signal'].iloc[-1]
        atr = df['ATR'].iloc[-1]
        
        # Warna Sinyal
        sig_col = "#777"
        sig_bg = "#1e1e1e"
        if "BUY" in last_sig:
            sig_col = "#00e676"
            sig_bg = "rgba(0, 255, 0, 0.2)"
            
        # Hitung Plan (JIKA ADA SINYAL / TREND BAGUS)
        if htf_trend == "BULLISH":
            prediksi = "LANJUT NAIK (UPTREND)"
            entry_plan = curr
            sl_plan = curr - (1.5 * atr)
            tp_plan = curr + (3 * atr) # RR 1:2
        else:
            prediksi = "HATI-HATI (DOWNTREND)"
            entry_plan = 0
            sl_plan = 0
            tp_plan = 0

        # Format Rupiah
        def fmt(x): return f"{x:,.0f}".replace(",", ".") if x > 0 else "-"
        
        # --- LAYOUT HTML ---
        st.markdown(f"""
        <style>
            .row-1 {{ display: grid; grid-template-columns: 1.5fr 1fr 1fr 1fr 1fr; gap: 8px; margin-bottom: 10px; }}
            .row-2 {{ display: grid; grid-template-columns: 1fr 1fr 1fr 1.5fr; gap: 8px; margin-bottom: 20px; }}
            .box {{ background: #1e1e1e; border: 1px solid #333; padding: 12px; border-radius: 6px; text-align: center; }}
            .sig-box {{ background: {sig_bg}; border: 2px solid {sig_col}; padding: 12px; border-radius: 6px; text-align: center; }}
            .lbl {{ font-size: 10px; color: #bbb; font-weight: bold; margin-bottom: 4px; text-transform: uppercase; }}
            .val {{ font-size: 15px; color: white; font-weight: bold; }}
            .val-lg {{ font-size: 18px; color: {sig_col}; font-weight: 900; }}
        </style>
        
        <!-- BARIS 1: STATUS PASAR -->
        <div class="row-1">
            <div class="sig-box">
                <div class="lbl">SINYAL LIVE</div>
                <div class="val-lg">{last_sig}</div>
            </div>
            <div class="box">
                <div class="lbl">HARGA</div>
                <div class="val" style="color:#f1c40f">Rp {fmt(curr)}</div>
            </div>
            <div class="box"><div class="lbl">LOW 24J</div><div class="val" style="color:#ff1744">{fmt(low_24)}</div></div>
            <div class="box"><div class="lbl">HIGH 24J</div><div class="val" style="color:#00e676">{fmt(high_24)}</div></div>
            <div class="box"><div class="lbl">VOLUME</div><div class="val">{vol:,.0f}</div></div>
        </div>

        <!-- BARIS 2: PLAN SCALPING -->
        <div class="row-2">
            <div class="box" style="border-top: 3px solid #2979ff">
                <div class="lbl">PLAN ENTRY</div>
                <div class="val" style="color:#2979ff">Rp {fmt(entry_plan)}</div>
            </div>
            <div class="box" style="border-top: 3px solid #00e676">
                <div class="lbl">TARGET (TP)</div>
                <div class="val" style="color:#00e676">Rp {fmt(tp_plan)}</div>
            </div>
            <div class="box" style="border-top: 3px solid #ff1744">
                <div class="lbl">STOP LOSS (ATR)</div>
                <div class="val" style="color:#ff1744">Rp {fmt(sl_plan)}</div>
            </div>
            <div class="box">
                <div class="lbl">PREDIKSI TREN</div>
                <div class="val" style="color:{'#00e676' if htf_trend=='BULLISH' else '#ff1744'}">{prediksi}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # --- CHART ---
        fig = make_subplots(rows=1, cols=1)
        
        # 1. Candle
        fig.add_trace(go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Harga'))
        
        # 2. Filter Trend (Garis Putus2)
        fig.add_hline(y=htf_ema, line_dash="dash", line_color="orange", annotation_text=f"Trend Filter ({htf_trend})", annotation_position="top left")
        
        # 3. FVG Zones (Fresh Only)
        for fvg in fvgs:
            # Gambar Kotak Transparan Hijau (Demand)
            fig.add_shape(type="rect",
                x0=fvg['time'], y0=fvg['bot'], x1=df['timestamp'].iloc[-1] + timedelta(hours=2), # Extend ke kanan
                y1=fvg['top'],
                fillcolor="rgba(0, 255, 128, 0.2)", line_width=0
            )
        
        # 4. Sinyal Panah
        buys = df[df['signal'].str.contains("BUY")]
        if not buys.empty:
             fig.add_trace(go.Scatter(x=buys['timestamp'], y=buys['low'], mode='markers', marker=dict(symbol='triangle-up', size=12, color='#00e676'), name='Buy Signal'))

        fig.update_layout(height=500, template="plotly_dark", margin=dict(l=0,r=0,t=10,b=0), xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True)
        
        # --- TABEL FVG DI BAWAH ---
        st.subheader("📋 Zona Smart Money (Fresh FVG)")
        if fvgs:
            fvg_data = [[f"Rp {fmt(z['bot'])} - Rp {fmt(z['top'])}", z['status'], z['time'].strftime('%H:%M')] for z in fvgs]
            st.table(pd.DataFrame(fvg_data, columns=["Area Harga (Demand)", "Status", "Waktu Terbentuk"]))
        else:
            st.info("Tidak ada FVG segar. Pasar efisien (tidak ada celah).")

    except Exception as e:
        st.error(f"Error: {e}")

dashboard(symbol, timeframe)
