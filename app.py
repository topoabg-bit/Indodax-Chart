import streamlit as st
import ccxt
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
import pytz
import numpy as np

# --- 1. KONFIGURASI ---
st.set_page_config(layout="wide", page_title="Indodax Sniper Pro")

# --- 2. ENGINE DATA & INDIKATOR ---
def get_market_data(symbol, timeframe):
    exchange = ccxt.indodax()
    ticker = exchange.fetch_ticker(symbol)
    
    # Ambil 300 Candle untuk kalkulasi EMA 200 yang valid
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=300)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    # Timezone WIB
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize('UTC').dt.tz_convert('Asia/Jakarta')
    
    # --- A. TREND (EMA 200) ---
    df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
    df['EMA_200'] = df['close'].ewm(span=200, adjust=False).mean()
    
    # --- B. MOMENTUM (MACD) ---
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['MACD_SIGNAL'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_HIST'] = df['MACD'] - df['MACD_SIGNAL']
    
    # --- C. VOLUME (MA 20) ---
    df['VOL_MA'] = df['volume'].rolling(window=20).mean()
    
    # --- D. LOGIKA SNIPER ---
    # Syarat Buy: Cross UP + Harga > EMA200 + MACD > Signal + Volume > Rata2
    cond_buy = (
        (df['EMA_9'] > df['EMA_21']) & 
        (df['EMA_9'].shift(1) <= df['EMA_21'].shift(1)) &
        (df['close'] > df['EMA_200']) &
        (df['MACD'] > df['MACD_SIGNAL']) &
        (df['volume'] > df['VOL_MA'])
    )
    
    cond_sell = (
        (df['EMA_9'] < df['EMA_21']) & 
        (df['EMA_9'].shift(1) >= df['EMA_21'].shift(1)) &
        (df['close'] < df['EMA_200']) &
        (df['MACD'] < df['MACD_SIGNAL']) &
        (df['volume'] > df['VOL_MA'])
    )
    
    df['signal'] = 0
    df.loc[cond_buy, 'signal'] = 2
    df.loc[cond_sell, 'signal'] = -2
    
    return df, ticker

# --- 3. UI SIDEBAR ---
st.sidebar.header("🎯 Sniper Control")
symbol = st.sidebar.selectbox("Aset", ['BTC/IDR', 'ETH/IDR', 'DOGE/IDR', 'SOL/IDR', 'XRP/IDR', 'SHIB/IDR', 'PEPE/IDR'])
timeframe = st.sidebar.selectbox("Timeframe", ['15m', '1h', '4h', '1d'])
st.sidebar.markdown("---")
st.sidebar.info("Chart & Sinyal otomatis refresh setiap 60 detik.")

# --- 4. MAIN APP ---
st.title(f"🎯 Sniper Trader: {symbol}")

@st.fragment(run_every=60)
def show_dashboard(sym, tf):
    try:
        df, ticker = get_market_data(sym, tf)
        
        # Data Realtime
        curr = ticker['last']
        vol = ticker['baseVolume']
        high_24 = ticker['high']
        low_24 = ticker['low']
        
        # Status Terakhir
        last_row = df.iloc[-1]
        is_uptrend = last_row['close'] > last_row['EMA_200']
        macd_bullish = last_row['MACD'] > last_row['MACD_SIGNAL']
        vol_strong = last_row['volume'] > last_row['VOL_MA']
        
        # Cek Entry Signal (Lihat 5 candle ke belakang barangkali baru saja terlewat)
        last_signals = df.tail(5)
        
        if 2 in last_signals['signal'].values:
            main_signal = "BUY ENTRY"
            sig_bg = "rgba(0, 255, 0, 0.15)"
            sig_col = "#00ff00"
            # TP/SL Logic
            sl_price = df['low'].tail(10).min()
            risk = curr - sl_price
            tp_price = curr + (risk * 2.5)
        elif -2 in last_signals['signal'].values:
            main_signal = "SELL ENTRY"
            sig_bg = "rgba(255, 0, 0, 0.15)"
            sig_col = "#ff0000"
            sl_price = df['high'].tail(10).max()
            risk = sl_price - curr
            tp_price = curr - (risk * 2.5)
        else:
            main_signal = "WAIT / NO ENTRY"
            sig_bg = "rgba(255, 255, 255, 0.05)"
            sig_col = "#888"
            tp_price = 0
            sl_price = 0

        # Format Angka
        f_curr = f"{curr:,.0f}"
        f_vol = f"{vol:,.0f}"
        f_high = f"{high_24:,.0f}"
        f_low = f"{low_24:,.0f}"
        f_tp = f"{tp_price:,.0f}" if tp_price > 0 else "-"
        f_sl = f"{sl_price:,.0f}" if sl_price > 0 else "-"

        # --- TAMPILAN VISUAL BARU ---
        
        # Warna Status Confluence (Hijau = OK, Merah = Tidak OK)
        c_trend = "#00e676" if is_uptrend else "#ff1744"
        c_macd = "#00e676" if macd_bullish else "#ff1744"
        c_vol = "#00e676" if vol_strong else "#555" # Abu jika vol lemah

        css = f"""
        <style>
            /* Grid Baris 1: 5 Kolom (Signal Besar, Harga, Vol, Low, High) */
            .grid-top {{ 
                display: grid; 
                grid-template-columns: 1.5fr 1fr 1fr 1fr 1fr; 
                gap: 6px; 
                margin-bottom: 8px; 
            }}
            
            /* Grid Baris 2: 4 Kolom (Entry, TP, SL, Confluence Check) */
            .grid-bot {{ 
                display: grid; 
                grid-template-columns: 1fr 1fr 1fr 1.5fr; 
                gap: 6px; 
                margin-bottom: 15px;
            }}
            
            .box {{ background: #262730; padding: 8px; border-radius: 4px; text-align: center; display: flex; flex-direction: column; justify-content: center; }}
            .sig-box {{ background: {sig_bg}; border: 1px solid {sig_col}; padding: 8px; border-radius: 4px; text-align: center; display: flex; flex-direction: column; justify-content: center; }}
            
            .lbl {{ font-size: 9px; color: #bbb; margin-bottom: 2px; text-transform: uppercase; letter-spacing: 0.5px; }}
            .val {{ font-size: 13px; font-weight: bold; color: white; }}
            .val-lg {{ font-size: 16px; font-weight: 900; color: {sig_col}; }}
            
            /* Confluence Status Dots */
            .conf-row {{ display: flex; justify-content: space-around; align-items: center; margin-top: 2px; }}
            .conf-item {{ font-size: 10px; display: flex; align-items: center; color: #ddd; }}
            .dot {{ width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; display: inline-block; }}
        </style>
        """
        
        html = f"""
        <div class="grid-top">
            <div class="sig-box">
                <div class="lbl">REKOMENDASI</div>
                <div class="val-lg">{main_signal}</div>
            </div>
            <div class="box">
                <div class="lbl">HARGA SAAT INI</div>
                <div class="val">Rp {f_curr}</div>
            </div>
            <div class="box">
                <div class="lbl">VOLUME 24J</div>
                <div class="val">{f_vol}</div>
            </div>
            <div class="box">
                <div class="lbl">TERENDAH</div>
                <div class="val" style="color:#ff5252">{f_low}</div>
            </div>
            <div class="box">
                <div class="lbl">TERTINGGI</div>
                <div class="val" style="color:#69f0ae">{f_high}</div>
            </div>
        </div>
        
        <div class="grid-bot">
            <div class="box" style="border: 1px solid #444;">
                <div class="lbl">ENTRY PRICE</div>
                <div class="val" style="color:#ffd740">Rp {f_curr}</div>
            </div>
            <div class="box" style="border: 1px solid #004d40;">
                <div class="lbl">TAKE PROFIT</div>
                <div class="val" style="color:#00e676">Rp {f_tp}</div>
            </div>
            <div class="box" style="border: 1px solid #3e2723;">
                <div class="lbl">STOP LOSS</div>
                <div class="val" style="color:#ff1744">Rp {f_sl}</div>
            </div>
            <div class="box" style="background:#1e1e1e;">
                <div class="lbl">SYARAT CONFLUENCE (WAJIB HIJAU)</div>
                <div class="conf-row">
                    <div class="conf-item"><span class="dot" style="background:{c_trend}; box-shadow:0 0 5px {c_trend}"></span> Trend</div>
                    <div class="conf-item"><span class="dot" style="background:{c_macd}; box-shadow:0 0 5px {c_macd}"></span> Mom</div>
                    <div class="conf-item"><span class="dot" style="background:{c_vol}; box-shadow:0 0 5px {c_vol}"></span> Vol</div>
                </div>
            </div>
        </div>
        """
        st.markdown(css + html, unsafe_allow_html=True)

        # --- CHARTING ---
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
        
        # Row 1: Candle & EMA
        fig.add_trace(go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Harga'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['EMA_9'], line=dict(color='#2979ff', width=1), name='EMA 9'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['EMA_21'], line=dict(color='#ff9100', width=1), name='EMA 21'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['EMA_200'], line=dict(color='white', width=2, dash='dot'), name='EMA 200'), row=1, col=1)
        
        # Marker Sinyal
        buy_sigs = df[df['signal'] == 2]
        sell_sigs = df[df['signal'] == -2]
        if not buy_sigs.empty:
            fig.add_trace(go.Scatter(x=buy_sigs['timestamp'], y=buy_sigs['low']*0.99, mode='markers', marker=dict(symbol='triangle-up', size=14, color='#00e676'), name='Sniper Buy'), row=1, col=1)
        if not sell_sigs.empty:
            fig.add_trace(go.Scatter(x=sell_sigs['timestamp'], y=sell_sigs['high']*1.01, mode='markers', marker=dict(symbol='triangle-down', size=14, color='#ff1744'), name='Sniper Sell'), row=1, col=1)

        # Row 2: MACD
        colors = np.where(df['MACD_HIST'] > 0, '#00e676', '#ff1744')
        fig.add_trace(go.Bar(x=df['timestamp'], y=df['MACD_HIST'], marker_color=colors, name='Histogram'), row=2, col=1)
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['MACD'], line=dict(color='#2979ff', width=1), name='MACD'), row=2, col=1)
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['MACD_SIGNAL'], line=dict(color='#ff9100', width=1), name='Signal'), row=2, col=1)

        fig.update_layout(height=600, margin=dict(t=10, b=10, l=10, r=10), template="plotly_dark", xaxis_rangeslider_visible=False, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"Data loading... {e}")

show_dashboard(symbol, timeframe)
