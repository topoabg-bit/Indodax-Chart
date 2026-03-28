import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from plotly.subplots import make_subplots
import numpy as np

# ==========================================
# 1. KONFIGURASI HALAMAN & SIDEBAR
# ==========================================
st.set_page_config(page_title="Expert Quant Dashboard", layout="wide")
st.title("📈 Pro Trader Dashboard: Indodax & Stockbit (IDX)")

st.sidebar.header("Konfigurasi Market")
ticker = st.sidebar.text_input("Simbol (Contoh: BBCA.JK atau BTC-USD):", "BBCA.JK")
timeframe = st.sidebar.selectbox("Timeframe:", ["1d", "1h", "15m", "5m"])
period_input = st.sidebar.selectbox("Periode Data:", ["1mo", "3mo", "6mo", "1y"])

# ==========================================
# 2. LOGIKA INDIKATOR (MFI & BBW)
# ==========================================
def add_indicators(df):
    # Hitung Money Flow Index (MFI)
    typical_price = (df['High'] + df['Low'] + df['Close']) / 3
    money_flow = typical_price * df['Volume']
    
    pos_flow = []
    neg_flow = []
    for i in range(1, len(typical_price)):
        if typical_price.iloc[i] > typical_price.iloc[i-1]:
            pos_flow.append(money_flow.iloc[i])
            neg_flow.append(0)
        else:
            pos_flow.append(0)
            neg_flow.append(money_flow.iloc[i])
            
    pos_res = pd.Series(pos_flow).rolling(window=14).sum()
    neg_res = pd.Series(neg_flow).rolling(window=14).sum()
    mfr = pos_res / neg_res
    df['MFI'] = 100 - (100 / (1 + mfr)).values
    
    # Hitung Bollinger Band Width (BBW)
    ma20 = df['Close'].rolling(window=20).mean()
    std20 = df['Close'].rolling(window=20).std()
    df['BBW'] = (((ma20 + (std20 * 2)) - (ma20 - (std20 * 2))) / ma20) * 100
    return df

# ==========================================
# 3. LOGIKA BACKTESTING (STRATEGY ENGINE)
# ==========================================
def run_backtest(df):
    initial_capital = 100_000_000
    balance = initial_capital
    position = 0
    trades = []
    
    for i in range(len(df)):
        price = df['Close'].iloc[i]
        mfi = df['MFI'].iloc[i]
        
        # BUY: MFI < 20 (Oversold)
        if position == 0 and mfi < 20:
            position = balance / price
            balance = 0
            trades.append({'Date': df.index[i], 'Type': 'BUY', 'Price': price})
            
        # SELL: MFI > 80 (Overbought)
        elif position > 0 and mfi > 80:
            balance = position * price
            position = 0
            trades.append({'Date': df.index[i], 'Type': 'SELL', 'Price': price})

    final_val = balance if position == 0 else position * df['Close'].iloc[-1]
    return final_val, ((final_val - initial_capital)/initial_capital)*100, trades

# ==========================================
# 4. EKSEKUSI & VISUALISASI
# ==========================================
try:
    # A. Download Data
    data = yf.download(ticker, period=period_input, interval=timeframe)
    
    if not data.empty:
        # B. Hitung Indikator
        df = add_indicators(data)
        
        # C. Chart Utama (Plotly)
        fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.6, 0.2, 0.2])
        fig.add_trace(go.Candlestick(x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name="Price"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['MFI'], name="MFI", line=dict(color='yellow')), row=2, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df['BBW'], name="BB Width", fill='tozeroy', line=dict(color='cyan')), row=3, col=1)
        fig.update_layout(height=800, template="plotly_dark", xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True)
        
        # D. Tampilkan Hasil Backtest
        st.header("📊 Backtest Result (MFI Strategy)")
        final_val, profit, trade_log = run_backtest(df)
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Final Balance", f"IDR {final_val:,.0f}")
        c2.metric("Profit/Loss (%)", f"{profit:.2f}%")
        c3.metric("Total Trades", len(trade_log))
        
        if trade_log:
            with st.expander("Detail Transaksi"):
                st.table(pd.DataFrame(trade_log))
    else:
        st.warning("Data kosong. Periksa simbol/ticker.")

except Exception as e:
    st.error(f"Terjadi kesalahan: {e}")
