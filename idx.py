import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
import yfinance as yf
from datetime import datetime

# Konfigurasi Halaman
st.set_page_config(page_title="Expert Quant Dashboard", layout="wide")
st.title("📈 Multi-Market Trading Dashboard")
st.markdown("Source: **Indodax** (Crypto) & **Yahoo Finance/IDX** (Stocks)")

# --- SIDEBAR: KONTROL ---
st.sidebar.header("Pengaturan Market")
market_type = st.sidebar.radio("Pilih Market:", ["Crypto (Indodax)", "Saham (IDX)"])

if market_type == "Crypto (Indodax)":
    # List pair populer Indodax
    symbol = st.sidebar.selectbox("Pilih Asset:", ["btc_idr", "eth_idr", "doge_idr", "usdt_idr"])
    interval = st.sidebar.selectbox("Timeframe:", ["1m", "5m", "15m", "1h", "1d"])
else:
    # Input kode saham (Gunakan akhiran .JK untuk Bursa Efek Indonesia)
    ticker_input = st.sidebar.text_input("Kode Saham (Contoh: BBCA.JK):", "BBCA.JK")
    period = st.sidebar.selectbox("Periode Data:", ["1d", "5d", "1mo", "6mo", "1y"])
    interval = st.sidebar.selectbox("Interval:", ["1m", "5m", "15m", "1h", "1d"])

# --- FUNGSI AMBIL DATA ---
@st.cache_data(ttl=60)
def get_indodax_data(pair):
    # Mengambil ticker real-time
    url = f"https://indodax.com/api/{pair}/ticker"
    response = requests.get(url).json()
    return response['ticker']

@st.cache_data(ttl=60)
def get_stock_data(ticker, p, i):
    data = yf.download(tickers=ticker, period=p, interval=i)
    return data

# --- MAIN DISPLAY ---
col1, col2 = st.columns([3, 1])

with col1:
    if market_type == "Crypto (Indodax)":
        try:
            ticker_data = get_indodax_data(symbol)
            st.metric(f"Harga Terakhir {symbol.upper()}", 
                      f"IDR {int(ticker_data['last']):,}", 
                      f"{ticker_data.get('change', '0')}%")
            
            # Note: Indodax Public API standar tidak menyediakan OHLCV history yang mudah ditarik 
            # tanpa library CCXT, jadi kita tampilkan data ringkasan.
            st.info("Visualisasi Candlestick Crypto disarankan menggunakan CCXT untuk history lengkap.")
        except Exception as e:
            st.error(f"Gagal memuat data Indodax: {e}")

    else:
        try:
            df = get_stock_data(ticker_input, period, interval)
            if not df.empty:
                # Plot Candlestick
                fig = go.Figure(data=[go.Candlestick(
                    x=df.index,
                    open=df['Open'],
                    high=df['High'],
                    low=df['Low'],
                    close=df['Close'],
                    name=ticker_input
                )])
                fig.update_layout(height=600, template="plotly_dark", xaxis_rangeslider_visible=False)
                st.plotly_chart(fig, use_container_width=True)
                
                with col2:
                    st.subheader("Statistik Saham")
                    st.write(df.tail(10))
            else:
                st.warning("Data tidak ditemukan. Pastikan kode saham benar (misal: TLKM.JK).")
        except Exception as e:
            st.error(f"Error Saham: {e}")

st.sidebar.markdown("---")
st.sidebar.write("Dashboard ini berjalan di browser dan bisa di-deploy ke Streamlit Cloud agar bisa diakses via HP.")

