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

# 4. Main App Logic
st.title(f"Chart {symbol} ({timeframe})")

try:
    # Load Data
    with st.spinner('Mengambil data dari Indodax...'):
        df = get_indodax_data(symbol, timeframe)

    # Buat Chart Candlestick
    fig = go.Figure(data=[go.Candlestick(
        x=df['timestamp'],
        open=df['open'],
        high=df['high'],
        low=df['low'],
        close=df['close'],
        name=symbol
    )])

    # Styling Chart agar Responsif (PENTING untuk HP)
    fig.update_layout(
        height=600,
        margin=dict(l=20, r=20, t=40, b=20),
        xaxis_rangeslider_visible=False, # Matikan slider bawah agar rapi di HP
        template="plotly_dark" # Mode gelap lebih nyaman di mata
    )

    # Tampilkan Chart
    st.plotly_chart(fig, use_container_width=True)

    # Tampilkan Data Tabel (Opsional)
    with st.expander("Lihat Data Mentah"):
        st.dataframe(df.sort_values(by='timestamp', ascending=False))

except Exception as e:
    st.error(f"Gagal mengambil data: {e}")
