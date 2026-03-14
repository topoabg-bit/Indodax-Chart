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
    
    # Ambil 300 Candle untuk kalkulasi akurat
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=300)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    # Timezone WIB
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize('UTC').dt.tz_convert('Asia/Jakarta')
    
    # --- A. TREND FILTER (EMA 200) ---
    df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
    df['EMA_200'] = df['close'].ewm(span=200, adjust=False).mean()
    
    # --- B. MOMENTUM FILTER (MACD) ---
    # Rumus: MACD = EMA12 - EMA26
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['MACD_SIGNAL'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_HIST'] = df['MACD'] - df['MACD_SIGNAL']
    
    # --- C. VOLUME FILTER ---
    # Rata-rata volume 20 candle terakhir
    df['VOL_MA'] = df['volume'].rolling(window=20).mean()
    
    # --- D. LOGIKA SINYAL (THE SNIPER LOGIC) ---
    # Buy Condition:
    # 1. EMA 9 Cross UP EMA 21
    # 2. Harga > EMA 200 (Uptrend)
    # 3. MACD > Signal (Momentum Positif)
    # 4. Volume > Volume MA (Validasi Power)
    
    cond_buy = (
        (df['EMA_9'] > df['EMA_21']) &              # Cross UP
        (df['EMA_9'].shift(1) <= df['EMA_21'].shift(1)) & # Baru saja Cross
        (df['close'] > df['EMA_200']) &             # Trend Filter
        (df['MACD'] > df['MACD_SIGNAL']) &          # Momentum Filter
        (df['volume'] > df['VOL_MA'])               # Volume Filter
    )
    
    cond_sell = (
        (df['EMA_9'] < df['EMA_21']) &
        (df['EMA_9'].shift(1) >= df['EMA_21'].shift(1)) &
        (df['close'] < df['EMA_200']) &
        (df['MACD'] < df['MACD_SIGNAL']) &
        (df['volume'] > df['VOL_MA'])
    )
    
    # Tandai Sinyal (2 = Buy, -2 = Sell, 0 = Netral)
    df['signal'] = 0
    df.loc[cond_buy, 'signal'] = 2
    df.loc[cond_sell, 'signal'] = -2
    
    return df, ticker

# --- 3. UI ---
st.sidebar.header("🎯 Sniper Control")
symbol = st.sidebar.selectbox("Aset", ['BTC/IDR', 'ETH/IDR', 'DOGE/IDR', 'SOL/IDR', 'XRP/IDR', 'SHIB/IDR', 'PEPE/IDR'])
timeframe = st.sidebar.selectbox("Timeframe", ['15m', '1h', '4h', '1d'])
st.sidebar.markdown("---")
st.sidebar.success("""
**🛡️ SYARAT VALIDASI:**
1. **Trend:** Harga diatas EMA 200.
2. **Momentum:** MACD Biru diatas Oranye.
3. **Volume:** Bar Volume diatas rata-rata.
""")

st.title(f"🎯 Sniper Trader: {symbol}")

@st.fragment(run_every=60)
def show_dashboard(sym, tf):
    try:
        df, ticker = get_market_data(sym, tf)
        
        # Data Terakhir
        curr = ticker['last']
        vol = ticker['baseVolume']
        
        last_row = df.iloc[-1]
        is_uptrend = last_row['close'] > last_row['EMA_200']
        macd_bullish = last_row['MACD'] > last_row['MACD_SIGNAL']
        vol_strong = last_row['volume'] > last_row['VOL_MA']
        
        # --- STATUS BUILDER ---
        score = 0
        if is_uptrend: score += 1
        if macd_bullish: score += 1
        if vol_strong: score += 1
        
        # Tentukan Display
        if score == 3:
            status = "PERFECT CONDITION"
            stat_color = "#00e676" # Super Hijau
        elif score == 2:
            status = "GOOD (WAIT TRIGGER)"
            stat_color = "#ffeb3b" # Kuning
        else:
            status = "WEAK / CHOPPY"
            stat_color = "#ff3d00" # Merah
            
        # Cek Sinyal ENTRY Terakhir (Mungkin candle sebelumnya)
        # Kita cari sinyal di 5 candle terakhir agar tidak ketinggalan info
        last_signals = df.tail(5)
        signal_detected = False
        
        if 2 in last_signals['signal'].values:
            main_signal = "BUY TRIGGERED"
            sig_bg = "rgba(0, 255, 0, 0.2)"
            sig_col = "#00ff00"
            
            # TP/SL Logic (SMC)
            sl_price = df['low'].tail(10).min()
            risk = curr - sl_price
            tp_price = curr + (risk * 2.5) # Reward 1:2.5
            
        elif -2 in last_signals['signal'].values:
            main_signal = "SELL TRIGGERED"
            sig_bg = "rgba(255, 0, 0, 0.2)"
            sig_col = "#ff0000"
            
            sl_price = df['high'].tail(10).max()
            risk = sl_price - curr
            tp_price = curr - (risk * 2.5)
            
        else:
            main_signal = "NO ENTRY"
            sig_bg = "rgba(255,255,255,0.05)"
            sig_col = "#888"
            sl_price = 0
            tp_price = 0

        # --- HTML VISUAL ---
        css = f"""
        <style>
            .stat-grid {{ display: grid; grid-template-columns: 2fr 1fr 1fr 1fr; gap: 8px; margin-bottom: 10px; }}
            .check-grid {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin-bottom: 15px; }}
            
            .box {{ background: #262730; padding: 10px; border-radius: 6px; text-align: center; }}
            .sig-box {{ background: {sig_bg}; border: 1px solid {sig_col}; padding: 10px; border-radius: 6px; text-align: center; }}
            
            .lbl {{ font-size: 10px; color: #bbb; margin-bottom: 3px; }}
            .val {{ font-size: 14px; font-weight: bold; color: white; }}
            .big-val {{ font-size: 18px; font-weight: 900; color: {sig_col}; }}
            
            .check-item {{ background: #1e1e1e; padding: 8px; border-radius: 4px; display: flex; justify-content: space-between; align-items: center; border: 1px solid #333; }}
            .check-lbl {{ font-size: 12px; color: #eee; }}
            .status-dot {{ height: 10px; width: 10px; border-radius: 50%; display: inline-block; }}
        </style>
        """
        
        # Indikator Visual (Dot warna)
        c_trend = "#00ff00" if is_uptrend else "#ff0000"
        c_macd = "#00ff00" if macd_bullish else "#ff0000"
        c_vol = "#00ff00" if vol_strong else "#555" # Abu jika volume rendah

        html = f"""
        <div class="stat-grid">
            <div class="sig-box">
                <div class="lbl">SNIPER SIGNAL</div>
                <div class="big-val">{main_signal}</div>
            </div>
            <div class="box"><div class="lbl">HARGA</div><div class="val">{curr:,.0f}</div></div>
            <div class="box"><div class="lbl">TP (1:2.5)</div><div class="val" style="color:#00e676">{tp_price:,.0f}</div></div>
            <div class="box"><div class="lbl">SL (Low)</div><div class="val" style="color:#ff1744">{sl_price:,.0f}</div></div>
        </div>
        
        <div class="lbl" style="margin-left:5px;">✅ SYARAT CONFLUENCE (Wajib Hijau Semua untuk Entry)</div>
        <div class="check-grid">
            <div class="check-item">
                <span class="check-lbl">1. Trend (EMA 200)</span>
                <span class="status-dot" style="background:{c_trend}; box-shadow: 0 0 5px {c_trend};"></span>
            </div>
            <div class="check-item">
                <span class="check-lbl">2. Momentum (MACD)</span>
                <span class="status-dot" style="background:{c_macd}; box-shadow: 0 0 5px {c_macd};"></span>
            </div>
            <div class="check-item">
                <span class="check-lbl">3. Volume Spike</span>
                <span class="status-dot" style="background:{c_vol}; box-shadow: 0 0 5px {c_vol};"></span>
            </div>
        </div>
        """
        st.markdown(css + html, unsafe_allow_html=True)

        # --- CHARTING (SUBPLOTS) ---
        # Kita buat 2 baris: Atas = Harga, Bawah = MACD
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                            vertical_spacing=0.05, row_heights=[0.7, 0.3])

        # 1. Candlestick (Row 1)
        fig.add_trace(go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Harga'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['EMA_9'], line=dict(color='cyan', width=1), name='EMA 9'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['EMA_21'], line=dict(color='orange', width=1), name='EMA 21'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['EMA_200'], line=dict(color='white', width=2, dash='dot'), name='EMA 200'), row=1, col=1)
        
        # Markers Entry (Hanya tampil jika SEMUA syarat terpenuhi)
        buy_sigs = df[df['signal'] == 2]
        sell_sigs = df[df['signal'] == -2]
        
        if not buy_sigs.empty:
            fig.add_trace(go.Scatter(x=buy_sigs['timestamp'], y=buy_sigs['low']*0.99, mode='markers', marker=dict(symbol='triangle-up', size=15, color='#00ff00', line=dict(width=2, color='white')), name='SNIPER BUY'), row=1, col=1)
        
        if not sell_sigs.empty:
             fig.add_trace(go.Scatter(x=sell_sigs['timestamp'], y=sell_sigs['high']*1.01, mode='markers', marker=dict(symbol='triangle-down', size=15, color='#ff0000', line=dict(width=2, color='white')), name='SNIPER SELL'), row=1, col=1)

        # 2. MACD (Row 2)
        # Histogram warna warni (Hijau jika naik, Merah jika turun)
        colors = np.where(df['MACD_HIST'] > 0, '#00e676', '#ff1744')
        fig.add_trace(go.Bar(x=df['timestamp'], y=df['MACD_HIST'], marker_color=colors, name='MACD Hist'), row=2, col=1)
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['MACD'], line=dict(color='#2962ff', width=1), name='MACD'), row=2, col=1)
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['MACD_SIGNAL'], line=dict(color='#ff6d00', width=1), name='Signal'), row=2, col=1)

        fig.update_layout(height=600, margin=dict(t=30, b=20, l=10, r=10), template="plotly_dark", title=dict(text="Analisa Multi-Filter (Sniper Mode)", font=dict(size=12)), xaxis_rangeslider_visible=False, showlegend=False)
        
        st.plotly_chart(fig, use_container_width=True)
        
    except Exception as e:
        st.error(f"Loading... {e}")

show_dashboard(symbol, timeframe)
