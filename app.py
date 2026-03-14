import streamlit as st
import ccxt
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import pytz

# 1. Konfigurasi Halaman
st.set_page_config(layout="wide", page_title="Indodax Pro Dashboard")

# 2. Fungsi Ambil Data
def get_market_data(symbol, timeframe):
    exchange = ccxt.indodax()
    ticker = exchange.fetch_ticker(symbol)
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=100)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    
    # Indikator EMA
    df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
    df['ATR'] = df['high'].rolling(window=14).max() - df['low'].rolling(window=14).min() # Sederhana untuk SL
    
    return df, ticker

# 3. Sidebar
st.sidebar.header("Pengaturan")
symbol = st.sidebar.selectbox("Pilih Aset", ['BTC/IDR', 'ETH/IDR', 'DOGE/IDR', 'SOL/IDR', 'XRP/IDR', 'SHIB/IDR'])
timeframe = st.sidebar.selectbox("Timeframe", ['15m', '1h', '4h', '1d'])

st.title(f"Trading Terminal: {symbol}")

@st.fragment(run_every=60)
def show_dashboard(sym, tf):
    try:
        df, ticker = get_market_data(sym, tf)
        
        # 1. Pastikan Data Angka
        curr = float(ticker['last'])
        high_24h = float(ticker['high'])
        low_24h = float(ticker['low'])
        vol = float(ticker['baseVolume'])
        
        # 2. Logika Sinyal & Prediksi
        ema_fast = df['EMA_9'].iloc[-1]
        ema_slow = df['EMA_21'].iloc[-1]
        last_close = df['close'].iloc[-1]
        
        if ema_fast > ema_slow:
            sig_text, sig_col, sig_bg = "STRONG BUY", "#00ff00", "rgba(0, 255, 0, 0.1)"
            tp, sl = last_close * 1.03, last_close * 0.98
        else:
            sig_text, sig_col, sig_bg = "STRONG SELL", "#ff0000", "rgba(255, 0, 0, 0.1)"
            tp, sl = last_close * 0.97, last_close * 1.02

        # 3. Fungsi Format Angka (Titik Pemisah)
        def fmt(x): return f"{x:,.0f}".replace(",", ".")

        # 4. TAMPILKAN CSS TERPISAH (Agar tidak bentrok dengan f-string)
        st.markdown("""
        <style>
            .main-container { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 20px; }
            .box-left { flex: 1; padding: 15px; border-radius: 10px; min-width: 250px; }
            .box-right { 
                flex: 2; background-color: #1e1e1e; border: 1px solid #333; 
                padding: 15px; border-radius: 10px; display: flex; justify-content: space-around; min-width: 350px;
            }
            .inner-stat { text-align: center; }
            .label { font-size: 11px; color: #999; font-weight: bold; margin-bottom: 5px; text-transform: uppercase; }
            .val-price { font-size: 20px; font-weight: bold; color: #f1c40f; }
            .val-hl { font-size: 14px; font-weight: bold; }
            .sig-title { font-size: 24px; font-weight: 900; margin-bottom: 5px; }
            .pred-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; margin-top: 10px; border-top: 1px solid rgba(255,255,255,0.1); padding-top: 10px; }
            .pred-item { text-align: center; }
            .pred-val { font-size: 13px; font-weight: bold; color: white; }
        </style>
        """, unsafe_allow_html=True)

        # 5. TAMPILKAN KONTEN (Tanpa CSS di dalamnya)
        st.markdown(f"""
        <div class="main-container">
            <!-- KOTAK KIRI: SINYAL & PREDIKSI -->
            <div class="box-left" style="background-color: {sig_bg}; border: 2px solid {sig_col};">
                <div class="label" style="color: white; opacity: 0.7;">REKOMENDASI</div>
                <div class="sig-title" style="color: {sig_col};">{sig_text}</div>
                <div class="pred-grid">
                    <div class="pred-item"><div class="label">ENTRY</div><div class="pred-val">{fmt(last_close)}</div></div>
                    <div class="pred-item"><div class="label">TARGET</div><div class="pred-val" style="color:#00ff00;">{fmt(tp)}</div></div>
                    <div class="pred-item"><div class="label">S. LOSS</div><div class="pred-val" style="color:#ff4444;">{fmt(sl)}</div></div>
                </div>
            </div>

            <!-- KOTAK KANAN: STATUS PASAR -->
            <div class="box-right">
                <div class="inner-stat">
                    <div class="label">HARGA TERKINI</div>
                    <div class="val-price">Rp {fmt(curr)}</div>
                </div>
                <div class="inner-stat">
                    <div class="label">24H HIGH / LOW</div>
                    <div class="val-hl" style="color:#2ecc71;">↑ {fmt(high_24h)}</div>
                    <div class="val-hl" style="color:#e74c3c;">↓ {fmt(low_24h)}</div>
                </div>
                <div class="inner-stat">
                    <div class="label">VOLUME (24H)</div>
                    <div class="val-hl" style="color:#ecf0f1;">{f"{vol:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")}</div>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # --- Bagian Chart tetap sama ---
        fig = go.Figure()
        fig.add_trace(go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Price'))
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['EMA_9'], line=dict(color='#2962ff', width=1.5), name='EMA 9'))
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['EMA_21'], line=dict(color='#ff6d00', width=1.5), name='EMA 21'))
        fig.update_layout(height=450, template="plotly_dark", margin=dict(l=0,r=0,t=30,b=0), xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"Gagal memuat data: {e}")

show_dashboard(symbol, timeframe)
