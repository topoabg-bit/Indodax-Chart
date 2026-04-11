import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import time

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Indodax Monitor Fix", layout="wide")

# --- FUNGSI FETCH DATA (DIPERBAIKI) ---
def get_indodax_data(pair="BTCIDR", resolution="15", lookback_days=2):
    """
    Mengambil data candle dengan Header Browser untuk menghindari blokir.
    """
    url = "https://indodax.com/tradingview/history"
    
    end_time = int(time.time())
    start_time = int((datetime.now() - timedelta(days=lookback_days)).timestamp())
    
    # PARAMETER WAJIB
    params = {
        "symbol": pair,
        "resolution": resolution,
        "from": start_time,
        "to": end_time
    }
    
    # HEADER SAMARAN (PENTING: Agar tidak dianggap bot)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://indodax.com/chart/" + pair,
        "Accept": "application/json"
    }
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=15)
        
        # Cek jika response sukses tapi bukan JSON (misal HTML error)
        if response.status_code != 200:
            st.error(f"Server Error: Status {response.status_code}")
            return pd.DataFrame()

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
            df["time"] = pd.to_datetime(df["time"], unit="s")
            return df
        elif data["s"] == "no_data":
            st.warning(f"Tidak ada data untuk periode ini. Coba timeframe lain.")
            return pd.DataFrame()
        else:
            st.error(f"API Error: {data['s']}")
            return pd.DataFrame()
            
    except Exception as e:
        st.error(f"Koneksi Gagal: {str(e)}")
        # Debugging: Tampilkan respon mentah jika gagal parsing
        try:
            st.text("Raw Response (Debug):")
            st.code(response.text[:500]) 
        except:
            pass
        return pd.DataFrame()

# --- UI LAYOUT ---
st.title("📈 Indodax Chart Monitor (Fixed)")

# Sidebar
with st.sidebar:
    st.header("Menu")
    pair = st.selectbox("Coin", ["BTCIDR", "ETHIDR", "SOLIDR", "DOGEIDR", "SHIBIDR"])
    tf = st.selectbox("Timeframe (Menit)", ["1", "15", "30", "60", "240", "1D"], index=1)
    
    if st.button("Muat Data"):
        st.rerun()

# --- PLOTTING ---
df = get_indodax_data(pair, tf)

if not df.empty:
    # Setup Layout: Chart Harga (Atas) & Volume (Bawah)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                        vertical_spacing=0.03, row_heights=[0.7, 0.3])

    # 1. Candlestick
    fig.add_trace(go.Candlestick(
        x=df['time'], open=df['open'], high=df['high'],
        low=df['low'], close=df['close'], name="Harga"
    ), row=1, col=1)

    # 2. Volume Bar
    colors = ['red' if row['open'] - row['close'] > 0 else 'green' for index, row in df.iterrows()]
    fig.add_trace(go.Bar(
        x=df['time'], y=df['volume'], name="Volume", marker_color=colors
    ), row=2, col=1)

    # 3. Fitur Geser & Zoom
    initial_view = [df['time'].iloc[-60], df['time'].iloc[-1]] # Default 60 candle terakhir
    
    fig.update_layout(
        title=f"{pair} - Timeframe {tf}",
        xaxis_rangeslider_visible=False, # Slider default dimatikan agar tidak berat
        xaxis_range=initial_view,        # Set zoom awal
        height=600,
        template="plotly_dark",
        margin=dict(l=0, r=0, t=40, b=0),
        dragmode="pan" # Mode geser aktif
    )

    st.plotly_chart(fig, use_container_width=True)
    
    # Info Harga
    curr = df.iloc[-1]
    st.metric("Harga Terakhir", f"Rp {curr['close']:,.0f}", 
              f"Vol: {curr['volume']:,.2f}")

else:
    st.info("Silakan pilih pair dan tekan 'Muat Data' atau cek koneksi.")
