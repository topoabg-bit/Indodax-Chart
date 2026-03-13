import streamlit as st
import ccxt
import pandas as pd
import plotly.graph_objects as go

# 1. Konfigurasi Halaman
st.set_page_config(layout="wide", page_title="Indodax Chart")

# 2. Fungsi Ambil Data Indodax
def get_indodax_data(symbol, timeframe):
    exchange = ccxt.indodax()
    # Mengambil 500 candle terakhir
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=500)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

# 3. Sidebar Kontrol
st.sidebar.header("Pengaturan")
symbol = st.sidebar.selectbox("Pilih Aset", ['BTC/IDR', 'ETH/IDR', 'DOGE/IDR', 'SOL/IDR'])
timeframe = st.sidebar.selectbox("Timeframe", ['15m', '1h', '4h', '1d'])

# 4. Main App Logic (Dengan Auto-Refresh)
st.title(f"Chart {symbol} ({timeframe})")

# Decorator ini memerintahkan fungsi di bawahnya untuk
# berjalan ulang otomatis setiap 60 detik
@st.fragment(run_every=60)
def show_live_chart(sym, tf):
    try:
        # Load Data Tanpa Spinner (agar tidak kedip-kedip mengganggu)
        df = get_indodax_data(sym, tf)

        # Buat Chart
        fig = go.Figure(data=[go.Candlestick(
            x=df['timestamp'],
            open=df['open'],
            high=df['high'],
            low=df['low'],
            close=df['close'],
            name=sym
        )])

        # Styling
        fig.update_layout(
            height=600,
            margin=dict(l=20, r=20, t=40, b=20),
            xaxis_rangeslider_visible=False,
            template="plotly_dark",
            title=f"Update Terakhir: {pd.Timestamp.now().strftime('%H:%M:%S')}"
        )

        st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"Gagal koneksi: {e}")

# Panggil fungsi tersebut
show_live_chart(symbol, timeframe)
