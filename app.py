import streamlit as st
import ccxt
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import pytz # Library untuk zona waktu

# 1. Konfigurasi Halaman
st.set_page_config(layout="wide", page_title="Indodax Pro Chart")

# 2. Fungsi Ambil Data (Diupdate untuk mengambil Ticker + OHLCV)
def get_market_data(symbol, timeframe):
    exchange = ccxt.indodax()
    
    # A. Ambil Data Statistik 24 Jam (Ticker)
    ticker = exchange.fetch_ticker(symbol)
    
    # B. Ambil Data Candle (Chart)
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=200)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    
    return df, ticker

# 3. Sidebar Kontrol
st.sidebar.header("Pengaturan")
symbol = st.sidebar.selectbox("Pilih Aset", ['BTC/IDR', 'ETH/IDR', 'DOGE/IDR', 'SOL/IDR', 'XRP/IDR', 'SHIB/IDR'])
timeframe = st.sidebar.selectbox("Timeframe", ['15m', '1h', '4h', '1d'])
st.sidebar.markdown("---")
st.sidebar.caption("Data bersumber dari API Publik Indodax. Refresh otomatis setiap 60 detik.")

# 4. Main App Logic
st.title(f"Pasar {symbol}")

# Auto-refresh setiap 60 detik
@st.fragment(run_every=60)
def show_dashboard(sym, tf):
    try:
        # Ambil data terbaru
        df, ticker = get_market_data(sym, tf)
        
        # --- BAGIAN 1: Statistik Utama (New!) ---
        # Mengambil data real dari Ticker Indodax
        curr_price = ticker['last']
        high_24h = ticker['high']
        low_24h = ticker['low']
        vol_24h = ticker['baseVolume'] # Volume aset (misal: jumlah BTC yg diperdagangkan)
        
        # Hitung perubahan harga (Delta) dari candle sebelumnya untuk warna
        prev_close = df['close'].iloc[-2]
        delta_price = curr_price - prev_close
        
        # Tampilkan 4 Kolom Statistik
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("Harga Terakhir", f"Rp {curr_price:,.0f}", f"{delta_price:,.0f}")
        with col2:
            st.metric("Tertinggi (24 Jam)", f"Rp {high_24h:,.0f}")
        with col3:
            st.metric("Terendah (24 Jam)", f"Rp {low_24h:,.0f}")
        with col4:
            # Format volume agar tidak terlalu panjang (misal 1.2K)
            st.metric("Volume (24 Jam)", f"{vol_24h:,.2f}")

        # --- BAGIAN 2: Chart ---
        # Konfigurasi Waktu WIB
        wib = pytz.timezone('Asia/Jakarta')
        now_wib = datetime.now(wib).strftime('%H:%M:%S WIB')

        fig = go.Figure(data=[go.Candlestick(
            x=df['timestamp'],
            open=df['open'],
            high=df['high'],
            low=df['low'],
            close=df['close'],
            name=sym
        )])

        fig.update_layout(
            height=500,
            margin=dict(l=10, r=10, t=40, b=10),
            xaxis_rangeslider_visible=False,
            template="plotly_dark",
            title=f"Update Terakhir: {now_wib}" # Judul menggunakan waktu WIB
        )

        st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"Gagal memuat data: {e}")
        
    # Tampilkan Data Tabel (Opsional)
    with st.expander("Lihat Data Mentah"):
        st.dataframe(df.sort_values(by='timestamp', ascending=False))

# Jalankan Dashboard
show_dashboard(symbol, timeframe)
