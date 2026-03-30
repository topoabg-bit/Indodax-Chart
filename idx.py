import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from plotly.subplots import make_subplots
import numpy as np

# ==========================================
# 1. KONFIGURASI HALAMAN
# ==========================================
st.set_page_config(page_title="GainzAlgo-Style Pro Dashboard", layout="wide")
st.title("🚀 GainzAlgo-Style Pro Suite (HMA + SuperTrend)")

# --- SIDEBAR ---
st.sidebar.header("1. Asset Configuration")
market_type = st.sidebar.radio("Market Type:", ["Crypto (-USD)", "Saham Indo (.JK)"])

if market_type == "Saham Indo (.JK)":
    default_ticker = "BBCA.JK"
else:
    default_ticker = "BTC-USD"

ticker = st.sidebar.text_input("Ticker Symbol:", value=default_ticker)
timeframe = st.sidebar.selectbox("Timeframe:", ["1d", "1h", "15m", "5m"], index=0)
period_input = st.sidebar.selectbox("Backtest Data:", ["6mo", "1y", "2y"], index=1)

st.sidebar.markdown("---")
st.sidebar.header("2. Algo Sensitivity")
# Parameter HMA (Hull Moving Average)
hma_len = st.sidebar.slider("HMA Length (Fast Signal)", 10, 100, 55)
# Parameter SuperTrend
atr_len = st.sidebar.slider("ATR Length (Volatility)", 7, 20, 10)
factor = st.sidebar.slider("SuperTrend Factor (Multiplier)", 1.0, 5.0, 3.0, step=0.1)

# ==========================================
# 2. MATHEMATICAL ENGINE (The "Secret Sauce")
# ==========================================

# A. Weighted Moving Average (Helper untuk HMA)
def wma(series, length):
    weights = np.arange(1, length + 1)
    return series.rolling(length).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)

# B. Hull Moving Average (HMA) - "Zero Lag" Indicator
def calculate_hma(series, length):
    half_length = int(length / 2)
    sqrt_length = int(np.sqrt(length))
    
    wma_half = wma(series, half_length)
    wma_full = wma(series, length)
    
    raw_hma = (2 * wma_half) - wma_full
    return wma(raw_hma, sqrt_length)

# C. SuperTrend Indicator
def calculate_supertrend(df, atr_period, multiplier):
    # Hitung True Range (TR)
    hl2 = (df['High'] + df['Low']) / 2
    df['TR'] = np.maximum(df['High'] - df['Low'], 
                          np.maximum(abs(df['High'] - df['Close'].shift(1)), 
                                     abs(df['Low'] - df['Close'].shift(1))))
    df['ATR'] = df['TR'].rolling(atr_period).mean()
    
    # Basic Bands
    df['Basic_Upper'] = hl2 + (multiplier * df['ATR'])
    df['Basic_Lower'] = hl2 - (multiplier * df['ATR'])
    
    # Final Bands (Logic SuperTrend)
    df['Final_Upper'] = 0.0
    df['Final_Lower'] = 0.0
    df['SuperTrend'] = 0.0
    df['Trend_Dir'] = 1 # 1 = Up (Green), -1 = Down (Red)
    
    for i in range(atr_period, len(df)):
        # Upper Band Logic
        if df['Basic_Upper'].iloc[i] < df['Final_Upper'].iloc[i-1] or df['Close'].iloc[i-1] > df['Final_Upper'].iloc[i-1]:
            df.loc[df.index[i], 'Final_Upper'] = df['Basic_Upper'].iloc[i]
        else:
            df.loc[df.index[i], 'Final_Upper'] = df['Final_Upper'].iloc[i-1]
            
        # Lower Band Logic
        if df['Basic_Lower'].iloc[i] > df['Final_Lower'].iloc[i-1] or df['Close'].iloc[i-1] < df['Final_Lower'].iloc[i-1]:
            df.loc[df.index[i], 'Final_Lower'] = df['Basic_Lower'].iloc[i]
        else:
            df.loc[df.index[i], 'Final_Lower'] = df['Final_Lower'].iloc[i-1]
            
        # Trend Direction Logic
        prev_trend = df['Trend_Dir'].iloc[i-1]
        
        if prev_trend == 1: # Sedang Uptrend
            if df['Close'].iloc[i] < df['Final_Lower'].iloc[i]:
                df.loc[df.index[i], 'Trend_Dir'] = -1 # Ganti jadi Downtrend
            else:
                df.loc[df.index[i], 'Trend_Dir'] = 1
        else: # Sedang Downtrend
            if df['Close'].iloc[i] > df['Final_Upper'].iloc[i]:
                df.loc[df.index[i], 'Trend_Dir'] = 1 # Ganti jadi Uptrend
            else:
                df.loc[df.index[i], 'Trend_Dir'] = -1
                
        # Nilai SuperTrend Final untuk Plotting
        if df['Trend_Dir'].iloc[i] == 1:
            df.loc[df.index[i], 'SuperTrend'] = df['Final_Lower'].iloc[i]
        else:
            df.loc[df.index[i], 'SuperTrend'] = df['Final_Upper'].iloc[i]
            
    return df

# ==========================================
# 3. STRATEGY BACKTESTER (CONFLUENCE LOGIC)
# ==========================================
def run_algo_backtest(df):
    capital = 100_000_000
    balance = capital
    position = 0
    trades = []
    
    for i in range(1, len(df)):
        # Skip data awal yg belum ada indikatornya
        if df['SuperTrend'].iloc[i] == 0: continue
        
        close = df['Close'].iloc[i]
        trend_dir = df['Trend_Dir'].iloc[i]      # 1 = Green, -1 = Red
        hma_val = df['HMA'].iloc[i]
        prev_hma = df['HMA'].iloc[i-1]
        
        # HMA Slope (Kemiringan HMA)
        hma_rising = hma_val > prev_hma
        
        # --- SIGNAL LOGIC (CONFLUENCE) ---
        # BUY Signal: SuperTrend HIJAU (1) DAN Harga di atas HMA
        buy_signal = (trend_dir == 1) and (close > hma_val)
        
        # SELL Signal: SuperTrend MERAH (-1) ATAU Harga jebol ke bawah HMA
        sell_signal = (trend_dir == -1) or (close < hma_val)
        
        # Eksekusi
        if position == 0 and buy_signal:
            position = balance / close
            balance = 0
            trades.append({'Date': df.index[i], 'Type': 'BUY', 'Price': close, 'Reason': 'SuperTrend + HMA Confirmed'})
            
        elif position > 0 and sell_signal:
            balance = position * close
            pnl = (close - trades[-1]['Price']) / trades[-1]['Price']
            position = 0
            trades.append({'Date': df.index[i], 'Type': 'SELL', 'Price': close, 'Reason': 'Trend Broken', 'PnL': pnl*100})

    final_val = balance if position == 0 else position * df['Close'].iloc[-1]
    return final_val, ((final_val - capital)/capital)*100, trades

# ==========================================
# 4. VISUALISASI & MAIN APP
# ==========================================
try:
    data = yf.download(ticker, period=period_input, interval=timeframe)
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    data = data.dropna()

    if not data.empty and len(data) > hma_len:
        # --- Hitung Indikator ---
        data['HMA'] = calculate_hma(data['Close'], hma_len)
        data = calculate_supertrend(data, atr_len, factor)
        
        # --- Visualisasi ---
        fig = go.Figure()
        
        # Candlestick
        fig.add_trace(go.Candlestick(x=data.index, open=data['Open'], high=data['High'], low=data['Low'], close=data['Close'], name="Price"))
        
        # Hull Moving Average (Garis Halus Cepat)
        fig.add_trace(go.Scatter(x=data.index, y=data['HMA'], line=dict(color='purple', width=2), name=f"HMA ({hma_len})"))
        
        # SuperTrend (Garis Support/Resistance Dinamis)
        # Kita warnai manual: Hijau saat Uptrend, Merah saat Downtrend
        st_color = ['green' if t == 1 else 'red' for t in data['Trend_Dir']]
        
        # Trik Plotly untuk garis warna-warni (Segmented Line) agak rumit, kita pakai Scatter sederhana dengan marker
        fig.add_trace(go.Scatter(x=data.index, y=data['SuperTrend'], mode='markers', marker=dict(size=2, color=st_color), name="SuperTrend Line"))

        # --- Backtest ---
        final_val, profit, log = run_algo_backtest(data)
        
        # Tampilkan Markers BUY/SELL
        log_df = pd.DataFrame(log)
        if not log_df.empty:
            buys = log_df[log_df['Type'] == 'BUY']
            sells = log_df[log_df['Type'] == 'SELL']
            fig.add_trace(go.Scatter(x=buys['Date'], y=buys['Price'], mode='markers', marker=dict(symbol='triangle-up', size=12, color='lime'), name="ALGO BUY"))
            fig.add_trace(go.Scatter(x=sells['Date'], y=sells['Price'], mode='markers', marker=dict(symbol='triangle-down', size=12, color='red'), name="ALGO SELL"))

        fig.update_layout(height=700, template="plotly_dark", title=f"GainzAlgo-Style Replicant: {ticker}")
        st.plotly_chart(fig, use_container_width=True)
        
        # --- Scorecard ---
        st.divider()
        c1, c2, c3 = st.columns(3)
        c1.metric("Algorithm Result (IDR)", f"{final_val:,.0f}")
        c2.metric("Win/Loss %", f"{profit:.2f}%", delta=f"{profit:.2f}%")
        c3.metric("Trades Executed", len(log))
        
        with st.expander("Show Trade Logs"):
            if not log_df.empty:
                st.dataframe(log_df.style.format({"Price": "{:.2f}", "PnL": "{:.2f}%"}))
    else:
        st.warning("Data sedang dimuat atau tidak cukup untuk menghitung HMA.")

except Exception as e:
    st.error(f"System Error: {e}")
