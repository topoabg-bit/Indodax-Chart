import streamlit as st
import ccxt
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import pytz

# 1. Konfigurasi Halaman
st.set_page_config(layout="wide", page_title="Indodax Pro Chart")

# 2. Fungsi Ambil Data
def get_market_data(symbol, timeframe):
    exchange = ccxt.indodax()
    ticker = exchange.fetch_ticker(symbol)
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=200)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df, ticker

# 3. Sidebar
st.sidebar.header("Pengaturan")
symbol = st.sidebar.selectbox("Pilih Aset", ['BTC/IDR', 'ETH/IDR', 'DOGE/IDR', 'SOL/IDR', 'XRP/IDR', 'SHIB/IDR'])
timeframe = st.sidebar.selectbox("Timeframe", ['15m', '1h', '4h', '1d'])
st.sidebar.markdown("---")
st.sidebar.caption("Refresh otomatis setiap 60 detik.")

# 4. Main App Logic
st.title(f"Pasar {symbol}")

@st.fragment(run_every=60)
def show_dashboard(sym, tf):
    try:
        df, ticker = get_market_data(sym, tf)
        
        # Data Variabel
        curr = ticker['last']
        high = ticker['high']
        low = ticker['low']
        vol = ticker['baseVolume']
        
        # Hitung Warna (Hijau/Merah)
        prev_close = df['close'].iloc[-2]
        color = "#00cc00" if curr >= prev_close else "#ff4444" # Warna hijau/merah terang

        # --- PERUBAHAN DISINI (Custom HTML Layout) ---
        # Kita membuat tabel mini dengan CSS (HTML) agar font bisa dikecilkan
        # font-size: 0.8rem artinya 80% dari ukuran normal
        
        html_stats = f"""
        <style>
            .stat-box {{
                display: flex;
                flex-direction: row;
                justify-content: space-between;
                background-color: #262730;
                padding: 10px;
                border-radius: 5px;
                margin-bottom: 10px;
            }}
            .stat-item {{
                text-align: center;
                width: 24%; /* Bagi 4 kolom rata */
            }}
            .stat-label {{
                font-size: 10px; /* Ukuran Label Kecil */
                color: #fafafa;
                opacity: 0.7;
            }}
            .stat-value {{
                font-size: 12px; /* Ukuran Angka Kecil agar muat */
                font-weight: bold;
                color: white;
                word-wrap: break-word; /* Paksa turun baris jika kepanjangan */
            }}
            .live-price {{
                color: {color};
                font-size: 14px; /* Harga utama sedikit lebih besar */
            }}
        </style>

        <div class="stat-box">
            <div class="stat-item">
                <div class="stat-label">Harga</div>
                <div class="stat-value live-price">Rp {curr:,.0f}</div>
            </div>
            <div class="stat-item">
                <div class="stat-label">Tertinggi</div>
                <div class="stat-value">Rp {high:,.0f}</div>
            </div>
            <div class="stat-item">
                <div class="stat-label">Terendah</div>
                <div class="stat-value">Rp {low:,.0f}</div>
            </div>
            <div class="stat-item">
                <div class="stat-label">Volume</div>
                <div class="stat-value">{vol:,.0f}</div>
            </div>
        </div>
        """
        
        # Tampilkan HTML di atas chart
        st.markdown(html_stats, unsafe_allow_html=True)

        # --- Chart ---
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
            margin=dict(l=10, r=10, t=20, b=10),
            xaxis_rangeslider_visible=False,
            template="plotly_dark",
            title=dict(text=f"Update: {now_wib}", font=dict(size=10)) # Judul chart juga diperkecil
        )

        st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"Gagal memuat data: {e}")
    # Tampilkan Data Tabel (Opsional)
    with st.expander("Lihat Data Mentah"):
        st.dataframe(df.sort_values(by='timestamp', ascending=False))

show_dashboard(symbol, timeframe)
