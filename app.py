import streamlit as st
import ccxt
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
import pytz

# --- 1. KONFIGURASI ---
st.set_page_config(layout="wide", page_title="Sniper + Peak Hunter")

# --- 2. DATA & INDIKATOR ENGINE ---
def get_market_data(symbol, timeframe):
    exchange = ccxt.indodax()
    ticker = exchange.fetch_ticker(symbol)
    
    # Ambil 300 Candle untuk akurasi MA 200
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=300)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize('UTC').dt.tz_convert('Asia/Jakarta')
    
    # --- A. TREND (EMA) ---
    df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
    df['EMA_200'] = df['close'].ewm(span=200, adjust=False).mean()
    
    # --- B. MOMENTUM (MACD) ---
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['MACD_SIGNAL'] = df['MACD'].ewm(span=9, adjust=False).mean()
    
    # --- C. RSI (Untuk Deteksi Puncak) ---
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # --- D. BOLLINGER BANDS ---
    df['BB_MID'] = df['close'].rolling(window=20).mean()
    df['BB_STD'] = df['close'].rolling(window=20).std()
    df['BB_UPPER'] = df['BB_MID'] + (df['BB_STD'] * 2)
    df['BB_LOWER'] = df['BB_MID'] - (df['BB_STD'] * 2)
    
    # --- E. VOLUME MA ---
    df['VOL_MA'] = df['volume'].rolling(window=20).mean()
    
    # --- F. LOGIKA SINYAL ---
    df['signal'] = 0 
    
    # 1. SNIPER BUY (Trend Follow)
    cond_buy = (
        (df['EMA_9'] > df['EMA_21']) & 
        (df['EMA_9'].shift(1) <= df['EMA_21'].shift(1)) &
        (df['close'] > df['EMA_200']) &
        (df['MACD'] > df['MACD_SIGNAL'])
    )
    
    # 2. SNIPER SELL (Trend Follow - Downtrend)
    cond_sell_trend = (
        (df['EMA_9'] < df['EMA_21']) & 
        (df['EMA_9'].shift(1) >= df['EMA_21'].shift(1)) &
        (df['close'] < df['EMA_200'])
    )
    
    # 3. PEAK SELL (Reversal - Tangkap Pucuk)
    cond_sell_peak = (
        (df['RSI'] > 70) & 
        (df['high'] >= df['BB_UPPER']) &
        (df['close'] < df['open']) 
    )
    
    df.loc[cond_buy, 'signal'] = 2
    df.loc[cond_sell_trend, 'signal'] = -2
    df.loc[cond_sell_peak, 'signal'] = -3
    
    return df, ticker

# --- 3. SIDEBAR ---
st.sidebar.header("🎯 Sniper + Peak Hunter")
symbol = st.sidebar.selectbox("Aset", ['BTC/IDR', 'ETH/IDR', 'DOGE/IDR', 'SOL/IDR', 'XRP/IDR', 'SHIB/IDR', 'PEPE/IDR'])
timeframe = st.sidebar.selectbox("Timeframe", ['15m', '1h', '4h', '1d'])
st.sidebar.markdown("---")
st.sidebar.info("🟢 **BUY:** Trend Follow\n\n🔴 **SELL:** Downtrend\n\n🟣 **PEAK:** Reversal Pucuk")

# --- 4. MAIN APP ---
st.title(f"⚡ Trader {symbol}")

@st.fragment(run_every=60)
def show_dashboard(sym, tf):
    try:
        df, ticker = get_market_data(sym, tf)
        
        # Data Realtime
        curr = float(ticker['last'])
        vol = float(ticker['baseVolume'])
        high_24 = float(ticker['high'])
        low_24 = float(ticker['low'])
        
        # Indikator Terakhir
        last = df.iloc[-1]
        last_candles = df.tail(5)
        
        # Default Variables
        main_signal = "WAIT / HOLD"
        sig_bg = "rgba(255, 255, 255, 0.05)"
        sig_col = "#888"
        tp_price = 0
        sl_price = 0
        
        # Prioritas Deteksi Sinyal
        if -3 in last_candles['signal'].values:
            main_signal = "PEAK SELL (PUCUK)"
            sig_bg, sig_col = "rgba(180, 0, 255, 0.15)", "#d500f9"
            sl_price = df['high'].tail(5).max() * 1.01
            tp_price = curr * 0.95
            
        elif 2 in last_candles['signal'].values:
            main_signal = "SNIPER BUY"
            sig_bg, sig_col = "rgba(0, 255, 0, 0.15)", "#00e676"
            sl_price = df['low'].tail(10).min()
            risk = curr - sl_price
            tp_price = curr + (risk * 2)
            
        elif -2 in last_candles['signal'].values:
            main_signal = "TREND SELL"
            sig_bg, sig_col = "rgba(255, 0, 0, 0.15)", "#ff1744"
            sl_price = df['high'].tail(10).max()
            risk = sl_price - curr
            tp_price = curr - (risk * 2)

        # Format Angka Indonesia (Titik)
        def fmt(x): return f"{x:,.0f}".replace(",", ".")
        
        f_curr = fmt(curr)
        f_vol = f"{vol:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        f_high = fmt(high_24)
        f_low = fmt(low_24)
        f_tp = fmt(tp_price) if tp_price > 0 else "-"
        f_sl = fmt(sl_price) if sl_price > 0 else "-"
        
        # Indikator Lampu
        rsi_val = last['RSI']
        trend_col = "#00e676" if last['close'] > last['EMA_200'] else "#ff1744"
        mom_col = "#00e676" if last['MACD'] > last['MACD_SIGNAL'] else "#ff1744"

        # --- TAMPILAN VISUAL ---
        # 1. CSS Statis (Dipisah agar aman)
        st.markdown("""
        <style>
            .grid-stats { display: grid; grid-template-columns: 1.5fr 1fr 1fr 1fr 1fr; gap: 8px; margin-bottom: 10px; }
            .grid-pred { display: grid; grid-template-columns: 1fr 1fr 1fr 1.5fr; gap: 8px; margin-bottom: 20px; }
            .box { background: #1e1e1e; padding: 10px; border-radius: 6px; text-align: center; border: 1px solid #333; }
            .lbl { font-size: 10px; color: #aaa; margin-bottom: 4px; font-weight: bold; letter-spacing: 0.5px; }
            .val { font-size: 14px; font-weight: bold; color: white; }
            .val-lg { font-size: 16px; font-weight: 900; }
            .conf-box { display: flex; justify-content: space-around; align-items: center; height: 100%; }
            .dot { height: 8px; width: 8px; border-radius: 50%; display: inline-block; margin-right: 4px; }
        </style>
        """, unsafe_allow_html=True)

        # 2. HTML Dinamis (Menggunakan f-string)
        st.markdown(f"""
        <div class="grid-stats">
            <div class="box" style="background:{sig_bg}; border:1px solid {sig_col};">
                <div class="lbl">SINYAL</div>
                <div class="val-lg" style="color:{sig_col}">{main_signal}</div>
            </div>
            <div class="box">
                <div class="lbl">HARGA</div>
                <div class="val" style="color:#f1c40f">Rp {f_curr}</div>
            </div>
            <div class="box">
                <div class="lbl">VOL (24J)</div>
                <div class="val">{f_vol}</div>
            </div>
            <div class="box">
                <div class="lbl">TERENDAH</div>
                <div class="val" style="color:#e74c3c">{f_low}</div>
            </div>
            <div class="box">
                <div class="lbl">TERTINGGI</div>
                <div class="val" style="color:#2ecc71">{f_high}</div>
            </div>
        </div>

        <div class="grid-pred">
            <div class="box" style="border-bottom: 2px solid #ffd740">
                <div class="lbl">ENTRY</div>
                <div class="val" style="color:#ffd740">Rp {f_curr}</div>
            </div>
            <div class="box" style="border-bottom: 2px solid #00e676">
                <div class="lbl">TAKE PROFIT</div>
                <div class="val" style="color:#00e676">Rp {f_tp}</div>
            </div>
            <div class="box" style="border-bottom: 2px solid #ff5252">
                <div class="lbl">STOP LOSS</div>
                <div class="val" style="color:#ff5252">Rp {f_sl}</div>
            </div>
            <div class="box">
                <div class="lbl">CONFIDENCE</div>
                <div class="conf-box">
                   <span style="font-size:10px"><span class="dot" style="background:{trend_col}"></span>TREND</span>
                   <span style="font-size:10px"><span class="dot" style="background:{mom_col}"></span>MOMENTUM</span>
                   <span style="font-size:10px">RSI: {rsi_val:.0f}</span>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # --- CHART ---
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
        
        # Candle & EMA
        fig.add_trace(go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Price'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['EMA_9'], line=dict(color='#2962ff', width=1), name='EMA 9'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['EMA_21'], line=dict(color='#ff6d00', width=1), name='EMA 21'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['EMA_200'], line=dict(color='#ffffff', width=1, dash='dot'), name='EMA 200'), row=1, col=1)
        
        # Bollinger Bands (Tipis)
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['BB_UPPER'], line=dict(color='rgba(255, 255, 255, 0.3)', width=1), showlegend=False), row=1, col=1)
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['BB_LOWER'], line=dict(color='rgba(255, 255, 255, 0.3)', width=1), showlegend=False), row=1, col=1)

        # MACD
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['MACD'], line=dict(color='#00e676', width=1), name='MACD'), row=2, col=1)
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['MACD_SIGNAL'], line=dict(color='#ff5252', width=1), name='Signal'), row=2, col=1)
        
        fig.update_layout(height=600, template="plotly_dark", margin=dict(l=0,r=0,t=30,b=0), xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"Menunggu Data... ({e})")

show_dashboard(symbol, timeframe)
