import streamlit as st
import ccxt
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
import pytz
import numpy as np

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(layout="wide", page_title="Indodax Pro + Anti-Fake Signal")

# --- 2. ENGINE DATA & ANALISA ---
def get_market_data(symbol, timeframe):
    exchange = ccxt.indodax()
    ticker = exchange.fetch_ticker(symbol)
    
    # Ambil Data Candle
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=100)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    # Fix Timezone ke WIB
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize('UTC').dt.tz_convert('Asia/Jakarta')
    
    # --- INDIKATOR EMA ---
    df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
    
    # --- INDIKATOR RSI (FILTER SINYAL PALSU) ---
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # --- DETEKSI CROSSOVER (UNTUK PANAH CHART) ---
    df['signal_flag'] = np.where(df['EMA_9'] > df['EMA_21'], 1, -1)
    df['crossover'] = df['signal_flag'].diff()
    
    return df, ticker

# --- 3. SIDEBAR ---
st.sidebar.header("🎛️ Kontrol Panel")
symbol = st.sidebar.selectbox("Pilih Koin", ['BTC/IDR', 'ETH/IDR', 'DOGE/IDR', 'SOL/IDR', 'XRP/IDR', 'SHIB/IDR', 'PEPE/IDR'])
timeframe = st.sidebar.selectbox("Timeframe", ['15m', '1h', '4h', '1d'])
st.sidebar.markdown("---")
st.sidebar.info("""
**🛡️ Filter Anti-Fake Signal:**
Sinyal hanya valid jika arah EMA dikonfirmasi oleh Momentum RSI (>50 Bullish, <50 Bearish).
""")

# --- 4. MAIN APP ---
st.title(f"📊 Trader {symbol} (Smart Filter)")

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
        ema_fast = df['EMA_9'].iloc[-1]
        ema_slow = df['EMA_21'].iloc[-1]
        rsi_val = df['RSI'].iloc[-1]
        
        # --- LOGIKA FILTER SINYAL PALSU ---
        # Sinyal asli hanya muncul jika RSI mendukung
        
        trend_status = "SIDEWAYS / WAIT"
        signal_color = "#888888" # Abu-abu default
        signal_bg = "rgba(255, 255, 255, 0.05)"
        trend_icon = "⏸️"
        
        # Logika Buy: EMA Biru di atas Oranye DAN RSI diatas 50 (Momentum Kuat)
        if ema_fast > ema_slow:
            if rsi_val > 50:
                trend_status = "STRONG BUY"
                signal_color = "#00ff00"
                signal_bg = "rgba(0, 255, 0, 0.15)"
                trend_icon = "🚀"
                
                # Trading Plan Buy
                sl_price = df['low'].tail(5).min()
                risk = curr_price - sl_price
                if risk <= 0: risk = curr_price * 0.01
                tp_price = curr_price + (risk * 2)
                
            else:
                # EMA Cross tapi RSI lemah (Potensi Fake)
                trend_status = "WEAK BUY (RISKY)"
                signal_color = "#aaff00" 
                tp_price = curr_price * 1.01
                sl_price = curr_price * 0.99

        # Logika Sell
        elif ema_fast < ema_slow:
            if rsi_val < 50:
                trend_status = "STRONG SELL"
                signal_color = "#ff0044"
                signal_bg = "rgba(255, 0, 68, 0.15)"
                trend_icon = "🔻"
                
                # Trading Plan Sell
                sl_price = df['high'].tail(5).max()
                risk = sl_price - curr_price
                if risk <= 0: risk = curr_price * 0.01
                tp_price = curr_price - (risk * 2)
            else:
                trend_status = "WEAK SELL (RISKY)"
                signal_color = "#ffaa00"
                tp_price = curr_price * 0.99
                sl_price = curr_price * 1.01

        # Format String
        str_curr = f"{curr_price:,.0f}"
        str_high = f"{high_24h:,.0f}"
        str_low = f"{low_24h:,.0f}"
        str_entry = f"{curr_price:,.0f}"
        str_tp = f"{tp_price:,.0f}"
        str_sl = f"{sl_price:,.0f}"

        # --- LAYOUT VISUAL BARU ---
        # Grid 5 Kolom: Signal(2) | Price | Low | High | Vol
        
        css_style = f"""
        <style>
            .header-grid {{ 
                display: grid; 
                grid-template-columns: 1.8fr 1fr 1fr 1fr 1fr; 
                gap: 6px; 
                margin-bottom: 10px; 
            }}
            .plan-grid {{ 
                display: grid; 
                grid-template-columns: 1fr 1fr 1fr; 
                gap: 0px; 
                margin-bottom: 15px; 
                background: #1e1e1e; 
                padding: 10px; 
                border-radius: 8px; 
                border: 1px solid #333;
            }}
            
            .box {{ background: #262730; padding: 8px; border-radius: 4px; text-align: center; display: flex; flex-direction: column; justify-content: center; }}
            .signal-box {{ background: {signal_bg}; border: 1px solid {signal_color}; padding: 8px; border-radius: 4px; text-align: center; display: flex; flex-direction: column; justify-content: center; }}
            
            .lbl {{ font-size: 10px; color: #aaa; margin-bottom: 2px; letter-spacing: 0.5px; text-transform: uppercase; }}
            .val {{ font-size: 13px; font-weight: bold; color: white; }}
            .val-lg {{ font-size: 16px; font-weight: 900; color: {signal_color}; }}
            
            .plan-item {{ text-align: center; padding: 5px; }}
            .plan-mid {{ border-left: 1px solid #444; border-right: 1px solid #444; }}
        </style>
        """

        html_code = f"""
<div class="header-grid">
<div class="signal-box">
<div class="lbl">REKOMENDASI</div>
<div class="val-lg">{trend_icon} {trend_status}</div>
</div>
<div class="box">
<div class="lbl">HARGA SAAT INI</div>
<div class="val" style="color:#fff; font-size:14px;">Rp {str_curr}</div>
</div>
<div class="box">
<div class="lbl">TERENDAH 24J</div>
<div class="val" style="color:#f44336;">{str_low}</div>
</div>
<div class="box">
<div class="lbl">TERTINGGI 24J</div>
<div class="val" style="color:#4caf50;">{str_high}</div>
</div>
<div class="box">
<div class="lbl">VOLUME</div>
<div class="val">{vol_24h:,.0f}</div>
</div>
</div>

<div class="lbl" style="margin-left: 5px; margin-bottom:5px;">🎯 TRADING PLAN (Valid jika Strong Signal)</div>
<div class="plan-grid">
<div class="plan-item">
<div class="lbl">ENTRY NOW</div>
<div class="val" style="color: #ffeb3b; font-size: 16px;">Rp {str_entry}</div>
</div>
<div class="plan-item plan-mid">
<div class="lbl">TAKE PROFIT</div>
<div class="val" style="color: #00ff00; font-size: 16px;">Rp {str_tp}</div>
</div>
<div class="plan-item">
<div class="lbl">STOP LOSS</div>
<div class="val" style="color: #ff0044; font-size: 16px;">Rp {str_sl}</div>
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
            low=df['low'], close=df['close'], name='Harga'
        ))

        # 2. Garis EMA
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['EMA_9'], line=dict(color='#2962ff', width=1), name='EMA 9'))
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['EMA_21'], line=dict(color='#ff6d00', width=1), name='EMA 21'))

        # 3. LOGIKA PANAH (Buy/Sell Marker Visual)
        buy_signals = df[df['crossover'] == 2]
        sell_signals = df[df['crossover'] == -2]

        if not buy_signals.empty:
            fig.add_trace(go.Scatter(
                x=buy_signals['timestamp'], y=buy_signals['low'] * 0.99,
                mode='markers', marker=dict(symbol='triangle-up', size=15, color='#00ff00'),
                name='Cross UP'
            ))

        if not sell_signals.empty:
            fig.add_trace(go.Scatter(
                x=sell_signals['timestamp'], y=sell_signals['high'] * 1.01,
                mode='markers', marker=dict(symbol='triangle-down', size=15, color='#ff0000'),
                name='Cross DOWN'
            ))

        fig.update_layout(
            height=550,
            margin=dict(t=30, b=20, l=10, r=10),
            template="plotly_dark",
            title=dict(text=f"Live Chart (WIB) - RSI Filter: {rsi_val:.1f}", font=dict(size=12)),
            legend=dict(orientation="h", y=1, x=0),
            xaxis_rangeslider_visible=False
        )

        st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"Loading data... {e}")

show_dashboard(symbol, timeframe)
