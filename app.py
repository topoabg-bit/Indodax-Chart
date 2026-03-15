import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
import pytz

# --- 1. KONFIGURASI ---
st.set_page_config(layout="wide", page_title="Pro Scalper: Early Signal")

# --- 2. ENGINE DATA & INDIKATOR ---
def get_data(symbol, tf):
    exchange = ccxt.indodax()
    try:
        # AMBIL BANYAK DATA (500) untuk kalkulasi akurat
        ohlcv = exchange.fetch_ohlcv(symbol, tf, limit=500)
        if not ohlcv: return pd.DataFrame(), None
        
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize('UTC').dt.tz_convert('Asia/Jakarta')
        ticker = exchange.fetch_ticker(symbol)
        return df, ticker
    except Exception as e:
        st.error(f"Koneksi Error: {e}")
        return pd.DataFrame(), None

def calculate_strategy(df):
    if df.empty: return df
    
    # A. Trend (EMA 200)
    df['EMA_200'] = df['close'].ewm(span=200, adjust=False).mean()
    
    # B. Momentum (Stoch RSI)
    period = 14
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    
    stoch_rsi = (rsi - rsi.rolling(period).min()) / (rsi.rolling(period).max() - rsi.rolling(period).min())
    df['K'] = stoch_rsi.rolling(3).mean() * 100 
    df['D'] = df['K'].rolling(3).mean()
    
    # C. ATR (Stop Loss)
    df['tr'] = np.maximum(df['high'] - df['low'], 
               np.maximum(abs(df['high'] - df['close'].shift()), abs(df['low'] - df['close'].shift())))
    df['ATR'] = df['tr'].ewm(span=14).mean()

    # --- LOGIKA SINYAL 5 TINGKAT ---
    df['signal'] = "TUNGGU"
    df['color'] = "#777" # Abu-abu
    
    last = df.index[-1]
    
    # Ambil Data Terakhir
    close = df.loc[last, 'close']
    ema200 = df.loc[last, 'EMA_200']
    k = df.loc[last, 'K']
    d = df.loc[last, 'D']
    k_prev = df['K'].iloc[-2]
    d_prev = df['D'].iloc[-2]
    
    # 1. LOGIKA UPTREND (Harga > EMA 200)
    if close > ema200:
        # Kondisi: Stoch RSI Oversold (< 30)
        if k < 30:
            if k > d and k_prev < d_prev: # Crossing UP
                df.loc[last, 'signal'] = "BUY SEKARANG"
                df.loc[last, 'color'] = "#00e676" # Hijau Neon
            else:
                df.loc[last, 'signal'] = "PERSIAPAN BUY"
                df.loc[last, 'color'] = "#ffeb3b" # Kuning (Siap-siap)
                
    # 2. LOGIKA DOWNTREND (Harga < EMA 200)
    elif close < ema200:
        # Kondisi: Stoch RSI Overbought (> 70)
        if k > 70:
            if k < d and k_prev > d_prev: # Crossing DOWN
                df.loc[last, 'signal'] = "SELL SEKARANG"
                df.loc[last, 'color'] = "#ff1744" # Merah Neon
            else:
                df.loc[last, 'signal'] = "PERSIAPAN SELL"
                df.loc[last, 'color'] = "#ff9100" # Oranye (Siap-siap)
                
    return df

# --- 3. TAMPILAN ---
st.sidebar.header("⚡ Scalping Panel")
symbol = st.sidebar.selectbox("Aset", ['BTC/IDR', 'ETH/IDR', 'SOL/IDR', 'DOGE/IDR', 'XRP/IDR', 'SHIB/IDR'])
timeframe = st.sidebar.selectbox("Timeframe", ['1m', '15m', '30m', '1h', '4h', '1d'])

st.title(f"Scalper: {symbol} | TF {timeframe}")

@st.fragment(run_every=30)
def main(sym, tf):
    # 1. Proses Data Lengkap (500 Bar)
    df, ticker = get_data(sym, tf)
    if df.empty: return
    df = calculate_strategy(df)
    
    # 2. Slice Data untuk Tampilan Chart (Hanya 60 Bar Terakhir biar Jelas)
    df_view = df.tail(60) 
    
    # Data Realtime
    curr = float(ticker['last'])
    sig_text = df['signal'].iloc[-1]
    sig_col = df['color'].iloc[-1]
    atr = df['ATR'].iloc[-1]
    
    # Hitung Plan
    entry_txt, sl_txt, tp_txt = "-", "-", "-"
    
    if "BUY" in sig_text:
        sl_val = curr - (2 * atr)
        tp_val = curr + (3 * atr)
        entry_txt = f"Rp {curr:,.0f}"
        sl_txt = f"Rp {sl_val:,.0f}"
        tp_txt = f"Rp {tp_val:,.0f}"
    elif "SELL" in sig_text:
        sl_val = curr + (2 * atr)
        tp_val = curr - (3 * atr)
        entry_txt = f"Rp {curr:,.0f}"
        sl_txt = f"Rp {sl_val:,.0f}"
        tp_txt = f"Rp {tp_val:,.0f}"
        
    def fmt(x): return f"{x:,.0f}".replace(",", ".")

    # --- HTML DISPLAY ---
    st.markdown(f"""
    <style>
        .grid-stat {{ display: grid; grid-template-columns: 2fr 1fr 1fr 1fr; gap: 8px; margin-bottom: 10px; }}
        .grid-plan {{ display: grid; grid-template-columns: 1fr 1fr 1fr 2fr; gap: 8px; margin-bottom: 20px; }}
        .box {{ background: #1e1e1e; border: 1px solid #333; padding: 12px; border-radius: 8px; text-align: center; }}
        .sig-box {{ background: {sig_col}20; border: 2px solid {sig_col}; padding: 12px; border-radius: 8px; text-align: center; }}
        .lbl {{ font-size: 10px; color: #aaa; font-weight: bold; margin-bottom: 4px; text-transform: uppercase; }}
        .val {{ font-size: 16px; font-weight: bold; color: white; }}
        .val-lg {{ font-size: 24px; font-weight: 900; color: {sig_col}; }}
    </style>
    
    <div class="grid-stat">
        <div class="sig-box">
            <div class="lbl">STATUS SINYAL</div>
            <div class="val-lg">{sig_text}</div>
        </div>
        <div class="box">
            <div class="lbl">HARGA</div>
            <div class="val" style="color:#f1c40f">Rp {fmt(curr)}</div>
        </div>
        <div class="box">
            <div class="lbl">VOLATILITAS (ATR)</div>
            <div class="val">{fmt(atr)}</div>
        </div>
        <div class="box">
            <div class="lbl">VOLUME</div>
            <div class="val">{float(ticker['baseVolume']):,.0f}</div>
        </div>
    </div>
    
    <div class="grid-plan">
        <div class="box" style="border-top: 3px solid #2979ff">
            <div class="lbl">ENTRY PLAN</div>
            <div class="val" style="color:#2979ff">{entry_txt}</div>
        </div>
        <div class="box" style="border-top: 3px solid #00e676">
            <div class="lbl">TAKE PROFIT</div>
            <div class="val" style="color:#00e676">{tp_txt}</div>
        </div>
        <div class="box" style="border-top: 3px solid #ff1744">
            <div class="lbl">STOP LOSS</div>
            <div class="val" style="color:#ff1744">{sl_txt}</div>
        </div>
        <div class="box">
            <div class="lbl">ANALISA TEKNIKAL</div>
            <div class="val" style="font-size:12px; text-align:left; padding-left:10px;">
                • Trend (EMA 200): <span style="color:{'#00e676' if curr > df['EMA_200'].iloc[-1] else '#ff1744'}">{'BULLISH' if curr > df['EMA_200'].iloc[-1] else 'BEARISH'}</span><br>
                • Momentum (Stoch): {df['K'].iloc[-1]:.1f} ({'OVERSOLD' if df['K'].iloc[-1] < 30 else 'OVERBOUGHT' if df['K'].iloc[-1] > 70 else 'NETRAL'})
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # --- CHART (Hanya Menampilkan df_view / Zoomed) ---
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.75, 0.25])
    
    # 1. Candlestick (Zoomed)
    fig.add_trace(go.Candlestick(x=df_view['timestamp'], open=df_view['open'], high=df_view['high'], low=df_view['low'], close=df_view['close'], name='Harga'), row=1, col=1)
    
    # EMA 200 (Tetap ditampilkan hasil hitungan penuh, tapi dipotong visualnya)
    fig.add_trace(go.Scatter(x=df_view['timestamp'], y=df_view['EMA_200'], line=dict(color='yellow', width=2), name='EMA 200 Trend'), row=1, col=1)
    
    # 2. Stoch RSI
    fig.add_trace(go.Scatter(x=df_view['timestamp'], y=df_view['K'], line=dict(color='#2979ff', width=1.5), name='K (Cepat)'), row=2, col=1)
    fig.add_trace(go.Scatter(x=df_view['timestamp'], y=df_view['D'], line=dict(color='#ff1744', width=1.5), name='D (Lambat)'), row=2, col=1)
    
    # Batas Area
    fig.add_hline(y=80, line_dash="dot", line_color="#555", row=2, col=1)
    fig.add_hline(y=20, line_dash="dot", line_color="#555", row=2, col=1)
    fig.add_hrect(y0=20, y1=80, fillcolor="rgba(255,255,255,0.03)", line_width=0, row=2, col=1)

    fig.update_layout(
        height=550, template="plotly_dark", margin=dict(l=0,r=0,t=0,b=0), 
        xaxis_rangeslider_visible=False,
        xaxis=dict(showgrid=False), yaxis=dict(showgrid=True, gridcolor='#333')
    )
    st.plotly_chart(fig, use_container_width=True)

main(symbol, timeframe)
