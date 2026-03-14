import streamlit as st
import ccxt
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import pytz
import textwrap  # <--- 1. Wajib import ini

# 1. Konfigurasi Halaman
st.set_page_config(layout="wide", page_title="Indodax Pro + Sinyal")

# 2. Fungsi Ambil Data & Analisa Teknis
def get_market_data(symbol, timeframe):
    exchange = ccxt.indodax()
    ticker = exchange.fetch_ticker(symbol)
    
    # Ambil data candle
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=100)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    
    # --- RUMUS INDIKATOR ---
    df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
    
    return df, ticker

# 3. Sidebar
st.sidebar.header("Pengaturan")
symbol = st.sidebar.selectbox("Pilih Aset", ['BTC/IDR', 'ETH/IDR', 'DOGE/IDR', 'SOL/IDR', 'XRP/IDR', 'SHIB/IDR', 'PEPE/IDR'])
timeframe = st.sidebar.selectbox("Timeframe", ['15m', '1h', '4h', '1d'])
st.sidebar.markdown("---")
st.sidebar.warning("⚠️ Sinyal ini berdasarkan indikator EMA Cross. Bukan ajakan finansial. DYOR.")

# 4. Main App Logic
st.title(f"Trader {symbol}")

@st.fragment(run_every=60)
def show_dashboard(sym, tf):
    try:
        df, ticker = get_market_data(sym, tf)
        
        # Data Realtime
        curr = ticker['last']
        vol = ticker['baseVolume']
        
        # --- LOGIKA SINYAL ---
        ema_fast = df['EMA_9'].iloc[-1]
        ema_slow = df['EMA_21'].iloc[-1]
        
        if ema_fast > ema_slow:
            signal_text = "STRONG BUY"
            signal_color = "#00ff00"
            signal_bg = "rgba(0, 255, 0, 0.1)"
        else:
            signal_text = "STRONG SELL"
            signal_color = "#ff0000"
            signal_bg = "rgba(255, 0, 0, 0.1)"
            
        trend_strength = abs(ema_fast - ema_slow) / ema_slow * 100

        # --- PERBAIKAN UTAMA DI SINI (textwrap.dedent) ---
        # Fungsi ini menghapus spasi indentasi agar HTML dibaca dengan benar
        html_stats = textwrap.dedent(f"""
        <style>
            .stat-container {{
                display: flex;
                flex-wrap: wrap;
                gap: 5px;
                margin-bottom: 10px;
            }}
            .stat-box {{
                flex: 1;
                background-color: #262730;
                padding: 8px;
                border-radius: 5px;
                text-align: center;
                min-width: 70px;
            }}
            .signal-box {{
                flex: 1;
                background-color: {signal_bg};
                border: 1px solid {signal_color};
                padding: 8px;
                border-radius: 5px;
                text-align: center;
                min-width: 100px;
            }}
            .label {{ font-size: 10px; color: #bbb; margin-bottom: 2px; }}
            .value {{ font-size: 12px; font-weight: bold; color: white; }}
            .signal-text {{ 
                font-size: 14px; 
                font-weight: 900; 
                color: {signal_color}; 
                letter-spacing: 1px;
            }}
        </style>

        <div class="stat-container">
            <div class="signal-box">
                <div class="label">REKOMENDASI</div>
                <div class="signal-text">{signal_text}</div>
                <div class="label" style="font-size: 8px;">Kekuatan: {trend_strength:.2f}%</div>
            </div>
            
            <div class="stat-box">
                <div class="label">HARGA</div>
                <div class="value">Rp {curr:,.0f}</div>
            </div>
            
            <div class="stat-box">
                <div class="label">VOL (24J)</div>
                <div class="value">{vol:,.0f}</div>
            </div>
        </div>
        """)
        
        st.markdown(html_stats, unsafe_allow_html=True)

        # --- CHART ---
        wib = pytz.timezone('Asia/Jakarta')
        now_wib = datetime.now(wib).strftime('%H:%M:%S WIB')

        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=df['timestamp'],
            open=df['open'], high=df['high'],
            low=df['low'], close=df['close'],
            name='Harga'
        ))
        fig.add_trace(go.Scatter(
            x=df['timestamp'], y=df['EMA_9'],
            line=dict(color='#2962ff', width=1),
            name='EMA 9'
        ))
        fig.add_trace(go.Scatter(
            x=df['timestamp'], y=df['EMA_21'],
            line=dict(color='#ff6d00', width=1),
            name='EMA 21'
        ))

        fig.update_layout(
            height=500,
            margin=dict(l=10, r=10, t=30, b=10),
            xaxis_rangeslider_visible=False,
            template="plotly_dark",
            title=dict(text=f"Analisa Live: {now_wib}", font=dict(size=10)),
            legend=dict(orientation="h", y=1, x=0)
        )

        st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"Tunggu sebentar.. (Mengambil data): {e}")

show_dashboard(symbol, timeframe)
