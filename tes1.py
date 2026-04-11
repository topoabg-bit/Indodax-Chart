import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta
import time

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Indodax Chart Monitor", layout="wide")

# --- FUNGSI FETCH DATA INDODAX ---
def get_indodax_data(pair="BTCIDR", resolution="15", lookback_days=5):
    """
    Mengambil data candle dari API Indodax (Endpoint TradingView).
    Resolution: '1', '15', '30', '60', '240', '1D', dll.
    """
    # Endpoint TradingView Indodax (Public)
    url = "https://indodax.com/tradingview/history"
    
    # Hitung timestamp (UNIX)
    end_time = int(time.time())
    start_time = int((datetime.now() - timedelta(days=lookback_days)).timestamp())
    
    params = {
        "symbol": pair,
        "resolution": resolution,
        "from": start_time,
        "to": end_time
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        data = response.json()
        
        if data["s"] == "ok":
            df = pd.DataFrame({
                "time": data["t"],
                "open": data["o"],
                "high": data["h"],
                "low": data["l"],
                "close": data["c"],
                "volume": data["v"]
            })
            # Konversi timestamp ke datetime
            df["time"] = pd.to_datetime(df["time"], unit="s")
            # Pastikan data numerik (float)
            cols = ["open", "high", "low", "close", "volume"]
            df[cols] = df[cols].astype(float)
            return df
        else:
            st.error("Gagal mengambil data: Response status not 'ok'")
            return pd.DataFrame()
            
    except Exception as e:
        st.error(f"Error Connection: {e}")
        return pd.DataFrame()

# --- UI LAYOUT ---
st.title("📈 Indodax Market Monitor")

# Sidebar Kontrol
with st.sidebar:
    st.header("Pengaturan")
    pair_select = st.selectbox("Pilih Pair", ["BTCIDR", "ETHIDR", "DOGEIDR", "XRPIDR"], index=0)
    timeframe = st.selectbox("Timeframe", ["15", "30", "60", "240", "1D"], index=0)
    
    if st.button("Refresh Data"):
        st.rerun()

# --- LOGIKA UTAMA ---
# 1. Ambil Data
with st.spinner(f'Mengambil data {pair_select}...'):
    df = get_indodax_data(pair=pair_select, resolution=timeframe)

if not df.empty:
    # 2. Siapkan Plotly Chart
    
    # Tentukan range awal (zoom ke 60 candle terakhir)
    # Kita ambil index terakhir dan kurangi 60
    start_index = max(0, len(df) - 60)
    end_index = len(df) - 1
    
    initial_range = [df['time'].iloc[start_index], df['time'].iloc[end_index]]

    # Buat Candlestick Trace
    fig = go.Figure(data=[go.Candlestick(
        x=df['time'],
        open=df['open'],
        high=df['high'],
        low=df['low'],
        close=df['close'],
        name=pair_select
    )])

    # 3. Styling Chart (Agar mirip TradingView)
    fig.update_layout(
        title=f"{pair_select} - Timeframe {timeframe}m",
        yaxis_title="Harga (IDR)",
        xaxis_rangeslider_visible=True, # Ini yang membuat chart bisa digeser/scroll
        xaxis_range=initial_range,      # Zoom default ke 60 candle terakhir
        height=700,
        template="plotly_dark",         # Tema gelap
        margin=dict(l=0, r=0, t=40, b=0),
        hovermode='x unified'
    )

    # Hilangkan 'rangebreaks' (gap akhir pekan/libur) karena Crypto 24/7
    # (Plotly default kadang menganggap ada gap, tapi crypto tidak ada gap waktu)
    fig.update_xaxes(
        rangebreaks=[],
        showgrid=True, gridwidth=1, gridcolor='#333'
    )
    
    fig.update_yaxes(
        showgrid=True, gridwidth=1, gridcolor='#333'
    )

    # 4. Tampilkan Chart
    st.plotly_chart(fig, use_container_width=True)

    # 5. Statistik Sederhana (Opsional)
    last_price = df['close'].iloc[-1]
    prev_price = df['close'].iloc[-2]
    change = last_price - prev_price
    pct_change = (change / prev_price) * 100
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Harga Terakhir", f"Rp {last_price:,.0f}", f"{pct_change:.2f}%")
    col2.metric("Volume Terakhir", f"{df['volume'].iloc[-1]:,.2f}")
    col3.metric("Candle Data", f"{len(df)} bars loaded")

else:
    st.warning("Data tidak ditemukan. Coba refresh atau periksa koneksi internet.")

