import streamlit as st
import ccxt
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import pytz
import numpy as np

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(layout="wide", page_title="Indodax Pro + Sinyal Lengkap")

# --- 2. ENGINE DATA & ANALISA ---
def get_market_data(symbol, timeframe):
    exchange = ccxt.indodax()
    ticker = exchange.fetch_ticker(symbol)
    
    # Ambil Data Candle
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=100)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    # --- FIX TIMEZONE KE WIB ---
    # Convert ms timestamp to datetime UTC -> Convert to Asia/Jakarta
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize('UTC').dt.tz_convert('Asia/Jakarta')
    
    # --- RUMUS INDIKATOR EMA ---
    df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
    
    # --- DETEKSI CROSSOVER (UNTUK PANAH) ---
    # 1 = Buy Area, -1 = Sell Area
    df['signal_flag'] = np.where(df['EMA_9'] > df['EMA_21'], 1, -1)
    # Hitung selisih untuk mencari momen perpindahan (2 = Buy Cross, -2 = Sell Cross)
    df['crossover'] = df['signal_flag'].diff()
    
    return df, ticker

# --- 3. SIDEBAR ---
st.sidebar.header("🎛️ Kontrol Panel")
symbol = st.sidebar.selectbox("Pilih Koin", ['BTC/IDR', 'ETH/IDR', 'DOGE/IDR', 'SOL/IDR', 'XRP/IDR', 'SHIB/IDR', 'PEPE/IDR'])
timeframe = st.sidebar.selectbox("Timeframe", ['15m', '1h', '4h', '1d'])
st.sidebar.markdown("---")
st.sidebar.info("💡 **Logika Trading:**\n\n**TP:** Risk x 2\n**SL:** Swing High/Low 5 Candle Terakhir")

# --- 4. MAIN APP ---
st.title(f"📊 Trader {symbol} (WIB)")

@st.fragment(run_every=60)
def show_dashboard(sym, tf):
    try:
        df, ticker = get_market_data(sym, tf)
        
        # --- DATA REALTIME ---
        curr_price = ticker['last']
        high_24h = ticker['high']
        low_24h = ticker['low']
        vol_24h = ticker['baseVolume']
        
        # --- ANALISA SINYAL TERAKHIR ---
        last_ema_fast = df['EMA_9'].iloc[-1]
        last_ema_slow = df['EMA_21'].iloc[-1]
        trend_strength = abs(last_ema_fast - last_ema_slow) / last_ema_slow * 100
        
        # Tentukan Status
        if last_ema_fast > last_ema_slow:
            signal_text = "BUY SIGNAL"
            signal_color = "#00ff00"    # Hijau
            signal_bg = "rgba(0, 255, 0, 0.15)"
            trend_icon = "🔼"
            
            # --- RUMUS TP/SL (STRATEGI BUY) ---
            # SL = Terendah dari 5 candle terakhir (Swing Low)
            sl_price = df['low'].tail(5).min()
            risk = curr_price - sl_price
            # Jika harga sudah jauh diatas SL (risk negatif/kecil), set default 1%
            if risk <= 0: risk = curr_price * 0.01 
            
            tp_price = curr_price + (risk * 2) # Rasio 1:2
            
        else:
            signal_text = "SELL SIGNAL"
            signal_color = "#ff0044"    # Merah
            signal_bg = "rgba(255, 0, 68, 0.15)"
            trend_icon = "🔽"
            
            # --- RUMUS TP/SL (STRATEGI SELL) ---
            # SL = Tertinggi dari 5 candle terakhir (Swing High)
            sl_price = df['high'].tail(5).max()
            risk = sl_price - curr_price
            if risk <= 0: risk = curr_price * 0.01
            
            tp_price = curr_price - (risk * 2)

        # Format Angka agar rapi
        str_curr = f"{curr_price:,.0f}"
        str_high = f"{high_24h:,.0f}"
        str_low = f"{low_24h:,.0f}"
        str_entry = f"{curr_price:,.0f}"
        str_tp = f"{tp_price:,.0f}"
        str_sl = f"{sl_price:,.0f}"

        # --- TAMPILAN HTML VISUAL ---
        # CSS kita pisah agar HTML bersih dan tidak dideteksi sebagai kode
        css_style = f"""
        <style>
            .main-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin-bottom: 10px; }}
            .plan-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin-bottom: 15px; background: #1e1e1e; padding: 10px; border-radius: 8px; border: 1px solid #444; }}
            
            .box {{ background: #262730; padding: 10px; border-radius: 6px; text-align: center; }}
            .signal-box {{ grid-column: span 2; background: {signal_bg}; border: 2px solid {signal_color}; padding: 10px; border-radius: 6px; text-align: center; }}
            
            .lbl {{ font-size: 11px; color: #aaa; margin-bottom: 4px; letter-spacing: 1px; text-transform: uppercase; }}
            .val {{ font-size: 14px; font-weight: bold; color: white; }}
            .sig-val {{ font-size: 18px; font-weight: 900; color: {signal_color}; }}
            
            .tp-text {{ color: #00ff00; font-weight: bold; }}
            .sl-text {{ color: #ff0044; font-weight: bold; }}
        </style>
        """

        # HTML Structure (Rata Kiri Total)
        html_code = f"""
<div class="main-grid">
<div class="signal-box">
<div class="lbl">PREDIKSI PASAR</div>
<div class="sig-val">{trend_icon} {signal_text}</div>
<div style="font-size:10px; color:{signal_color}">Strength: {trend_strength:.2f}%</div>
</div>
<div class="box">
<div class="lbl">HARGA (IDR)</div>
<div class="val">{str_curr}</div>
</div>
<div class="box">
<div class="lbl">VOLUME</div>
<div class="val">{vol_24h:,.0f}</div>
</div>
<div class="box">
<div class="lbl">TERTINGGI 24J</div>
<div class="val" style="color: #4caf50">{str_high}</div>
</div>
<div class="box">
<div class="lbl">TERENDAH 24J</div>
<div class="val" style="color: #f44336">{str_low}</div>
</div>
</div>

<div class="lbl" style="margin-left: 5px; margin-bottom:5px;">🎯 TRADING PLAN (RISK 1:2)</div>
<div class="plan-grid">
<div style="text-align:center">
<div class="lbl">ENTRY AREA</div>
<div class="val" style="color: #ffeb3b">Rp {str_entry}</div>
</div>
<div style="text-align:center; border-left: 1px solid #444; border-right: 1px solid #444;">
<div class="lbl">TAKE PROFIT</div>
<div class="val tp-text">Rp {str_tp}</div>
</div>
<div style="text-align:center">
<div class="lbl">STOP LOSS</div>
<div class="val sl-text">Rp {str_sl}</div>
</div>
</div>
"""
        st.markdown(css_style + html_code, unsafe_allow_html=True)

        # --- CHARTING ---
        now_wib = datetime.now(pytz.timezone('Asia/Jakarta')).strftime('%H:%M:%S')
        
        fig = go.Figure()

        # 1. Candlestick
        fig.add_trace(go.Candlestick(
            x=df['timestamp'], open=df['open'], high=df['high'],
            low=df['low'], close=df['close'], name='Market'
        ))

        # 2. Garis EMA
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['EMA_9'], line=dict(color='#2962ff', width=1), name='EMA 9'))
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['EMA_21'], line=dict(color='#ff6d00', width=1), name='EMA 21'))

        # 3. LOGIKA PANAH (Buy/Sell Markers)
        # Cari titik dimana crossover == 2 (Buy) atau -2 (Sell)
        buy_signals = df[df['crossover'] == 2]
        sell_signals = df[df['crossover'] == -2]

        # Marker Buy (Panah Hijau ke Atas di bawah candle low)
        if not buy_signals.empty:
            fig.add_trace(go.Scatter(
                x=buy_signals['timestamp'], y=buy_signals['low'] * 0.995, # Sedikit dibawah candle
                mode='markers', marker=dict(symbol='triangle-up', size=12, color='#00ff00'),
                name='Sinyal Beli'
            ))

        # Marker Sell (Panah Merah ke Bawah di atas candle high)
        if not sell_signals.empty:
            fig.add_trace(go.Scatter(
                x=sell_signals['timestamp'], y=sell_signals['high'] * 1.005, # Sedikit diatas candle
                mode='markers', marker=dict(symbol='triangle-down', size=12, color='#ff0000'),
                name='Sinyal Jual'
            ))

        fig.update_layout(
            height=550,
            margin=dict(t=30, b=20, l=10, r=10),
            template="plotly_dark",
            title=dict(text=f"Live Chart (WIB): {now_wib}", font=dict(size=12)),
            legend=dict(orientation="h", y=1, x=0),
            xaxis_rangeslider_visible=False
        )

        st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"Sedang memuat data pasar... {e}")

show_dashboard(symbol, timeframe)
