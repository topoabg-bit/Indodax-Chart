import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from plotly.subplots import make_subplots
import numpy as np

# ==========================================
# 1. KONFIGURASI HALAMAN
# ==========================================
st.set_page_config(page_title="Expert Trend Dashboard", layout="wide")
st.title("📈 Trend Follower Pro: EMA Cross + Stop Loss")

# --- SIDEBAR ---
st.sidebar.header("1. Market & Aset")
market_type = st.sidebar.radio("Market:", ["Crypto (-USD)", "Saham Indonesia (.JK)"])

if market_type == "Saham Indonesia (.JK)":
    default_ticker = "BBCA.JK"
    period_opts = ["6mo", "1y", "2y", "5y"]
else:
    default_ticker = "BTC-USD"
    period_opts = ["3mo", "6mo", "1y", "2y"]

ticker = st.sidebar.text_input("Simbol Aset:", value=default_ticker)
timeframe = st.sidebar.selectbox("Timeframe:", ["1d", "1h"], index=0)
period_input = st.sidebar.selectbox("Periode Backtest:", period_opts, index=1)

st.sidebar.markdown("---")
st.sidebar.header("2. Strategi Setup")
fast_ma = st.sidebar.slider("EMA Cepat (Fast Trend)", 5, 50, 20)
slow_ma = st.sidebar.slider("EMA Lambat (Baseline)", 20, 200, 50)
stop_loss_pct = st.sidebar.slider("Stop Loss Protection (%)", 1, 20, 5) / 100

# ==========================================
# 2. LOGIKA INDIKATOR (TREND FOLLOWING)
# ==========================================
def add_trend_indicators(df, fast, slow):
    # Exponential Moving Average (EMA) lebih responsif daripada MA biasa
    df['EMA_Fast'] = df['Close'].ewm(span=fast, adjust=False).mean()
    df['EMA_Slow'] = df['Close'].ewm(span=slow, adjust=False).mean()
    
    # Signal: 1 jika Fast > Slow (Uptrend), -1 jika Fast < Slow (Downtrend)
    df['Trend'] = np.where(df['EMA_Fast'] > df['EMA_Slow'], 1, -1)
    return df

# ==========================================
# 3. ENGINE BACKTEST (DENGAN STOP LOSS)
# ==========================================
def run_trend_backtest(df, sl_pct):
    capital = 100_000_000
    balance = capital
    position = 0
    entry_price = 0
    trades = []
    
    # Loop data
    for i in range(1, len(df)):
        current_price = df['Close'].iloc[i]
        current_date = df.index[i]
        
        # Cek Trend (EMA Cross)
        prev_trend = df['Trend'].iloc[i-1]
        curr_trend = df['Trend'].iloc[i]
        
        # --- LOGIKA JUAL (Exit) ---
        if position > 0:
            # 1. Kena Stop Loss? (Bahaya, potong rugi!)
            if current_price <= entry_price * (1 - sl_pct):
                reason = "🛑 STOP LOSS"
                pnl_pct = (current_price - entry_price) / entry_price
                balance = position * current_price
                position = 0
                trades.append({
                    'Tanggal': current_date, 'Aksi': 'SELL', 'Alasan': reason,
                    'Harga': current_price, 'PnL (%)': pnl_pct * 100, 'Saldo': balance
                })
                continue # Lanjut ke hari berikutnya
            
            # 2. Trend Berubah jadi Turun (Death Cross)?
            if prev_trend == 1 and curr_trend == -1:
                reason = "📉 Trend Reversal"
                pnl_pct = (current_price - entry_price) / entry_price
                balance = position * current_price
                position = 0
                trades.append({
                    'Tanggal': current_date, 'Aksi': 'SELL', 'Alasan': reason,
                    'Harga': current_price, 'PnL (%)': pnl_pct * 100, 'Saldo': balance
                })

        # --- LOGIKA BELI (Entry) ---
        # Beli jika Trend berubah dari Bawah ke Atas (Golden Cross) DAN tidak punya posisi
        elif position == 0:
            if prev_trend == -1 and curr_trend == 1:
                position = balance / current_price
                entry_price = current_price
                balance = 0
                trades.append({
                    'Tanggal': current_date, 'Aksi': 'BUY', 'Alasan': '🚀 Golden Cross',
                    'Harga': current_price, 'PnL (%)': 0, 'Saldo': position * current_price
                })

    # Valuasi Akhir
    final_val = balance if position == 0 else position * df['Close'].iloc[-1]
    total_profit = ((final_val - capital) / capital) * 100
    return final_val, total_profit, trades

# ==========================================
# 4. TAMPILAN DASHBOARD
# ==========================================
try:
    # A. Fetch Data
    data = yf.download(ticker, period=period_input, interval=timeframe)
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    data = data.dropna()

    if not data.empty and len(data) > slow_ma:
        # B. Hitung
        df = add_trend_indicators(data, fast_ma, slow_ma)
        final_val, profit_pct, trade_log = run_trend_backtest(df, stop_loss_pct)
        
        # C. Scorecard Utama
        st.subheader(f"Simulasi Strategy pada {ticker}")
        c1, c2, c3 = st.columns(3)
        c1.metric("Modal Awal", "IDR 100 Juta")
        
        delta_color = "normal" if profit_pct >= 0 else "inverse"
        c2.metric("Total Profit/Loss", f"{profit_pct:.2f}%", delta=f"{profit_pct:.2f}%", delta_color=delta_color)
        c3.metric("Saldo Akhir", f"IDR {final_val:,.0f}")

        # D. Visualisasi Chart (Entry/Exit Marker)
        fig = go.Figure()
        
        # Candlestick
        fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name="Price"))
        
        # EMA Lines
        fig.add_trace(go.Scatter(x=df.index, y=df['EMA_Fast'], line=dict(color='cyan', width=1), name=f"EMA {fast_ma}"))
        fig.add_trace(go.Scatter(x=df.index, y=df['EMA_Slow'], line=dict(color='orange', width=2), name=f"EMA {slow_ma}"))

        # Plot Buy/Sell Markers dari History
        trades_df = pd.DataFrame(trade_log)
        if not trades_df.empty:
            buys = trades_df[trades_df['Aksi'] == 'BUY']
            sells = trades_df[trades_df['Aksi'] == 'SELL']
            
            # Panah Hijau untuk BUY
            fig.add_trace(go.Scatter(
                x=buys['Tanggal'], y=buys['Harga'], mode='markers', 
                marker=dict(symbol='triangle-up', size=15, color='green'), name="BUY Signal"
            ))
            
            # Panah Merah untuk SELL
            fig.add_trace(go.Scatter(
                x=sells['Tanggal'], y=sells['Harga'], mode='markers', 
                marker=dict(symbol='triangle-down', size=15, color='red'), name="SELL Signal"
            ))

        fig.update_layout(height=700, template="plotly_dark", title=f"Chart & Trade Signals: {ticker}")
        st.plotly_chart(fig, use_container_width=True)

        # E. Jurnal Trading
        with st.expander("📜 Lihat Detail Jurnal Transaksi (Kenapa saya rugi/untung?)"):
            if not trades_df.empty:
                st.dataframe(trades_df.style.format({"Harga": "{:.2f}", "PnL (%)": "{:.2f}", "Saldo": "{:,.0f}"}))
            else:
                st.write("Tidak ada sinyal trade pada periode ini.")
                
    else:
        st.error("Data tidak cukup untuk menghitung EMA. Coba perpanjang periode.")

except Exception as e:
    st.error(f"System Error: {e}")
