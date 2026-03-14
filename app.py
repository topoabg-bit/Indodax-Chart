import streamlit as st
import ccxt
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import pytz
import numpy as np

# --- 1. KONFIGURASI ---
st.set_page_config(layout="wide", page_title="Indodax SMC + EMA 200")

# --- 2. ENGINE DATA ---
def get_market_data(symbol, timeframe):
    exchange = ccxt.indodax()
    ticker = exchange.fetch_ticker(symbol)
    
    # PERUBAHAN 1: Ambil data lebih banyak (300) untuk hitung EMA 200 valid
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=300)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    # Timezone WIB
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize('UTC').dt.tz_convert('Asia/Jakarta')
    
    # --- INDIKATOR UTAMA ---
    df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()   # Fast
    df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean() # Slow
    df['EMA_200'] = df['close'].ewm(span=200, adjust=False).mean() # Trend Filter
    
    # --- LOGIKA ENTRY (CROSSOVER) ---
    df['signal_flag'] = np.where(df['EMA_9'] > df['EMA_21'], 1, -1)
    df['crossover'] = df['signal_flag'].diff()
    
    return df, ticker

# --- 3. SIDEBAR ---
st.sidebar.header("🎛️ SMC Control")
symbol = st.sidebar.selectbox("Aset", ['BTC/IDR', 'ETH/IDR', 'DOGE/IDR', 'SOL/IDR', 'XRP/IDR', 'SHIB/IDR', 'PEPE/IDR'])
timeframe = st.sidebar.selectbox("Timeframe", ['15m', '1h', '4h', '1d'])
st.sidebar.markdown("---")
st.sidebar.info("""
**🧠 Strategi SMC + EMA 200:**
1. **Trend Filter:** Hanya Buy jika harga > EMA 200.
2. **SL (Structure):** Swing Low/High Terdekat.
3. **TP (Liquidity):** Menargetkan Swing High/Low lama (Liquidity Run) atau RR 1:3.
""")

# --- 4. MAIN APP ---
st.title(f"🦅 SMC Trader: {symbol}")

@st.fragment(run_every=60)
def show_dashboard(sym, tf):
    try:
        df, ticker = get_market_data(sym, tf)
        
        # Data Realtime
        curr = ticker['last']
        high_24h = ticker['high']
        low_24h = ticker['low']
        vol = ticker['baseVolume']
        
        # Data Terakhir
        last_close = df['close'].iloc[-1]
        ema_fast = df['EMA_9'].iloc[-1]
        ema_slow = df['EMA_21'].iloc[-1]
        ema_trend = df['EMA_200'].iloc[-1]
        
        # --- ALGORITMA SMC + TREND FILTER ---
        
        status = "WAITING FOR SETUP"
        sig_color = "#777"
        bg_color = "rgba(255,255,255,0.05)"
        icon = "⏳"
        
        # Default Plan (Kosongkan jika wait)
        tp_price = 0
        sl_price = 0
        risk_reward = "0"
        
        # Cek Tren Besar (EMA 200)
        is_uptrend = last_close > ema_trend
        
        if is_uptrend:
            # --- SKENARIO BULLISH (Hanya cari BUY) ---
            if ema_fast > ema_slow: # Cross UP terjadi
                status = "LONG (BUY) SETUP"
                sig_color = "#00ff00" # Hijau
                bg_color = "rgba(0, 255, 0, 0.1)"
                icon = "🟢"
                
                # SMC Logic:
                # SL = Structure Low (Titik terendah dari 10 candle terakhir - Area Demand)
                sl_price = df['low'].tail(10).min()
                
                # TP = Buy Side Liquidity (Titik tertinggi 50 candle terakhir)
                liquidity_pool = df['high'].tail(50).max()
                
                # Hitung Risk
                entry = curr
                risk = entry - sl_price
                if risk <= 0: risk = entry * 0.005 # Safety jika SL tertabrak
                
                # Cek jika Liquidity Pool cukup jauh (Minimal RR 1:2)
                reward = liquidity_pool - entry
                if reward < (risk * 2):
                    # Jika Liquidity dekat, kita targetkan expansion (Fibonacci style) 1:3
                    tp_price = entry + (risk * 3)
                else:
                    tp_price = liquidity_pool
                    
            else:
                status = "UPTREND (PULLBACK)" 
                sig_color = "#aaff00" # Kuning kehijauan
                icon = "⚠️"

        else:
            # --- SKENARIO BEARISH (Hanya cari SELL) ---
            if ema_fast < ema_slow: # Cross DOWN terjadi
                status = "SHORT (SELL) SETUP"
                sig_color = "#ff0044" # Merah
                bg_color = "rgba(255, 0, 68, 0.1)"
                icon = "🔴"
                
                # SMC Logic:
                # SL = Structure High (Titik tertinggi 10 candle terakhir - Area Supply)
                sl_price = df['high'].tail(10).max()
                
                # TP = Sell Side Liquidity (Titik terendah 50 candle terakhir)
                liquidity_pool = df['low'].tail(50).min()
                
                # Hitung Risk
                entry = curr
                risk = sl_price - entry
                if risk <= 0: risk = entry * 0.005
                
                # Cek RR
                reward = entry - liquidity_pool
                if reward < (risk * 2):
                    tp_price = entry - (risk * 3)
                else:
                    tp_price = liquidity_pool
            
            else:
                status = "DOWNTREND (RALLY)"
                sig_color = "#ffaa00"
                icon = "⚠️"

        # Format Angka
        str_sl = f"{sl_price:,.0f}" if sl_price > 0 else "-"
        str_tp = f"{tp_price:,.0f}" if tp_price > 0 else "-"
        
        # TAMPILAN VISUAL
        css = f"""
        <style>
            .grid-header {{ display: grid; grid-template-columns: 2fr 1fr 1fr 1fr 1fr; gap: 5px; margin-bottom: 10px; }}
            .grid-plan {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 0px; background: #121212; border: 1px solid #333; border-radius: 8px; margin-bottom: 15px; }}
            
            .box {{ background: #262730; padding: 8px; border-radius: 4px; text-align: center; display: flex; flex-direction: column; justify-content: center; }}
            .sig-box {{ background: {bg_color}; border: 1px solid {sig_color}; padding: 8px; border-radius: 4px; text-align: center; }}
            
            .lbl {{ font-size: 9px; color: #bbb; text-transform: uppercase; letter-spacing: 1px; }}
            .val {{ font-size: 12px; font-weight: bold; color: white; }}
            .val-lg {{ font-size: 15px; font-weight: 900; color: {sig_color}; }}
            
            .p-item {{ padding: 10px; text-align: center; }}
            .mid {{ border-left: 1px solid #333; border-right: 1px solid #333; }}
            .tp-col {{ color: #00e676; font-size: 16px; font-weight: bold; }}
            .sl-col {{ color: #ff1744; font-size: 16px; font-weight: bold; }}
        </style>
        """
        
        html = f"""
        <div class="grid-header">
            <div class="sig-box">
                <div class="lbl">SMC SIGNAL</div>
                <div class="val-lg">{icon} {status}</div>
                <div class="lbl" style="font-size:8px; margin-top:2px;">Trend Filter: {'BULLISH' if is_uptrend else 'BEARISH'} (EMA200)</div>
            </div>
            <div class="box"><div class="lbl">PRICE</div><div class="val">{curr:,.0f}</div></div>
            <div class="box"><div class="lbl">LOW 24H</div><div class="val" style="color:#ff5252">{low_24h:,.0f}</div></div>
            <div class="box"><div class="lbl">HIGH 24H</div><div class="val" style="color:#69f0ae">{high_24h:,.0f}</div></div>
            <div class="box"><div class="lbl">VOL</div><div class="val">{vol:,.0f}</div></div>
        </div>
        
        <div class="lbl" style="margin-left:5px; margin-bottom:5px;">🎯 SMC EXECUTION PLAN (Liquidity Targeting)</div>
        <div class="grid-plan">
            <div class="p-item">
                <div class="lbl">ENTRY (MARKET)</div>
                <div class="val" style="color:#ffd740; font-size:16px;">Rp {curr:,.0f}</div>
            </div>
            <div class="p-item mid">
                <div class="lbl">TAKE PROFIT (LIQUIDITY)</div>
                <div class="tp-col">Rp {str_tp}</div>
            </div>
            <div class="p-item">
                <div class="lbl">STOP LOSS (STRUCTURE)</div>
                <div class="sl-col">Rp {str_sl}</div>
            </div>
        </div>
        """
        st.markdown(css + html, unsafe_allow_html=True)
        
        # --- CHARTING ---
        fig = go.Figure()
        
        # 1. Candle
        fig.add_trace(go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Price'))
        
        # 2. EMA Lines
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['EMA_9'], line=dict(color='cyan', width=1), name='EMA 9'))
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['EMA_21'], line=dict(color='orange', width=1), name='EMA 21'))
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['EMA_200'], line=dict(color='white', width=2, dash='dot'), name='EMA 200 (Trend)'))
        
        # 3. Visualisasi TP/SL Lines (Hanya jika ada setup)
        if tp_price > 0 and sl_price > 0:
            fig.add_hline(y=tp_price, line_dash="dash", line_color="green", annotation_text="TP (Liquidity)", annotation_position="top right")
            fig.add_hline(y=sl_price, line_dash="dash", line_color="red", annotation_text="SL (Structure)", annotation_position="bottom right")

        # 4. Marker Sinyal (Filtered by EMA 200)
        # Buy Markers: Cross UP AND Close > EMA 200
        buy_cond = (df['crossover'] == 2) & (df['close'] > df['EMA_200'])
        buy_sigs = df[buy_cond]
        
        # Sell Markers: Cross DOWN AND Close < EMA 200
        sell_cond = (df['crossover'] == -2) & (df['close'] < df['EMA_200'])
        sell_sigs = df[sell_cond]
        
        if not buy_sigs.empty:
            fig.add_trace(go.Scatter(x=buy_sigs['timestamp'], y=buy_sigs['low']*0.99, mode='markers', marker=dict(symbol='triangle-up', size=14, color='#00ff00'), name='Valid Buy'))
            
        if not sell_sigs.empty:
            fig.add_trace(go.Scatter(x=sell_sigs['timestamp'], y=sell_sigs['high']*1.01, mode='markers', marker=dict(symbol='triangle-down', size=14, color='#ff0044'), name='Valid Sell'))

        fig.update_layout(
            height=600, 
            margin=dict(t=30, b=20, l=10, r=10), 
            template="plotly_dark",
            title=dict(text=f"Live SMC Market Structure ({now_wib})", font=dict(size=12)),
            xaxis_rangeslider_visible=False
        )
        st.plotly_chart(fig, use_container_width=True)
        
    except Exception as e:
        st.error(f"Loading... {e}")

now_wib = datetime.now(pytz.timezone('Asia/Jakarta')).strftime('%H:%M')
show_dashboard(symbol, timeframe)
