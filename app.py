import streamlit as st
import ccxt
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
import pytz

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(layout="wide", page_title="Hybrid SMC + EMA Pro")

# --- 2. ENGINE DATA & SINYAL ---
def get_market_data(symbol, timeframe):
    exchange = ccxt.indodax()
    ticker = exchange.fetch_ticker(symbol)
    
    # Ambil Data Candle
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=300)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    # Konversi Waktu ke WIB
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize('UTC').dt.tz_convert('Asia/Jakarta')
    
    # --- INDIKATOR ---
    # 1. EMA Cepat & Lambat (Untuk Sinyal Harian)
    df['EMA_9'] = df['close'].ewm(span=9, adjust=False).mean()
    df['EMA_21'] = df['close'].ewm(span=21, adjust=False).mean()
    
    # 2. EMA Tren Besar (Filter)
    df['EMA_200'] = df['close'].ewm(span=200, adjust=False).mean()
    
    # 3. MACD (Momentum)
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['MACD_SIGNAL'] = df['MACD'].ewm(span=9, adjust=False).mean()
    
    # 4. Bollinger Bands
    df['BB_UPPER'] = df['close'].rolling(20).mean() + (df['close'].rolling(20).std() * 2)
    df['BB_LOWER'] = df['close'].rolling(20).mean() - (df['close'].rolling(20).std() * 2)
    
    # 5. Struktur Market (Untuk SL Otomatis)
    df['SWING_LOW'] = df['low'].rolling(window=5).min()
    df['SWING_HIGH'] = df['high'].rolling(window=5).max()

    # --- POLA CANDLE (SMC) ---
    df['BULL_ENGULF'] = (df['close'] > df['open']) & (df['close'] > df['open'].shift(1)) & (df['open'] < df['close'].shift(1))
    df['BEAR_ENGULF'] = (df['close'] < df['open']) & (df['close'] < df['open'].shift(1)) & (df['open'] > df['close'].shift(1))

    # --- LOGIKA SCORING SINYAL (HIERARKI) ---
    df['signal_type'] = "NEUTRAL"
    df['signal_source'] = ""
    
    # A. SINYAL EMA CROSS (Tier 2 - Sering Muncul)
    # Cross Up (Golden Cross Kecil)
    cond_ema_buy = (df['EMA_9'] > df['EMA_21']) & (df['EMA_9'].shift(1) <= df['EMA_21'].shift(1))
    # Cross Down (Death Cross Kecil)
    cond_ema_sell = (df['EMA_9'] < df['EMA_21']) & (df['EMA_9'].shift(1) >= df['EMA_21'].shift(1))
    
    df.loc[cond_ema_buy, 'signal_type'] = "TREND BUY"
    df.loc[cond_ema_buy, 'signal_source'] = "EMA CROSS"
    
    df.loc[cond_ema_sell, 'signal_type'] = "TREND SELL"
    df.loc[cond_ema_sell, 'signal_source'] = "EMA CROSS"
    
    # B. SINYAL SMC (Tier 1 - Prioritas Tinggi / Menimpa EMA)
    # Validasi: Harus searah dengan EMA 200
    cond_smc_buy = (df['BULL_ENGULF']) & (df['close'] > df['EMA_200']) & (df['MACD'] > df['MACD_SIGNAL'])
    cond_smc_sell = (df['BEAR_ENGULF']) & (df['close'] < df['EMA_200']) & (df['MACD'] < df['MACD_SIGNAL'])
    
    df.loc[cond_smc_buy, 'signal_type'] = "STRONG BUY"
    df.loc[cond_smc_buy, 'signal_source'] = "SMC ACTION"
    
    df.loc[cond_smc_sell, 'signal_type'] = "STRONG SELL"
    df.loc[cond_smc_sell, 'signal_source'] = "SMC ACTION"

    return df, ticker

# --- 3. DASHBOARD LOGIC ---
st.sidebar.header("⚙️ Hybrid Trading")
symbol = st.sidebar.selectbox("Aset", ['BTC/IDR', 'ETH/IDR', 'DOGE/IDR', 'SOL/IDR', 'XRP/IDR', 'SHIB/IDR', 'PEPE/IDR'])
timeframe = st.sidebar.selectbox("Timeframe", ['15m', '1h', '4h', '1d'])

st.title(f"Hybrid Trader: {symbol}")

@st.fragment(run_every=60)
def show_dashboard(sym, tf):
    try:
        df, ticker = get_market_data(sym, tf)
        
        curr = float(ticker['last'])
        high_24 = float(ticker['high'])
        low_24 = float(ticker['low'])
        vol = float(ticker['baseVolume'])
        
        # --- DETEKSI SINYAL ---
        # Cek 5 candle terakhir agar sinyal tidak hilang terlalu cepat
        scan_window = df.tail(5)
        
        # Default State
        active_signal = "WAIT / HOLD"
        source_label = "NO SIGNAL"
        sig_bg = "#262730"
        sig_col = "#777"
        
        # Variabel Plan
        plan_entry = 0
        plan_tp = 0
        plan_sl = 0
        
        # Loop cari sinyal (Prioritaskan yang paling baru)
        for i, row in scan_window.iterrows():
            if row['signal_type'] != "NEUTRAL":
                active_signal = row['signal_type']
                source_label = row['signal_source']
                plan_entry = row['close']
                
                # Logika SL & TP Dinamis
                if "BUY" in active_signal:
                    sig_col = "#00e676" # Hijau
                    sig_bg = "rgba(0, 255, 0, 0.1)"
                    
                    # SL = Swing Low Terakhir (SMC) atau 2% dibawah harga (EMA)
                    sl_candidate = row['SWING_LOW']
                    if sl_candidate >= plan_entry: # Safety check jika swing low aneh
                         sl_candidate = plan_entry * 0.98
                    
                    plan_sl = sl_candidate
                    risk = plan_entry - plan_sl
                    plan_tp = plan_entry + (risk * 2) # RR 1:2
                    
                elif "SELL" in active_signal:
                    sig_col = "#ff1744" # Merah
                    sig_bg = "rgba(255, 0, 0, 0.1)"
                    
                    sl_candidate = row['SWING_HIGH']
                    if sl_candidate <= plan_entry:
                        sl_candidate = plan_entry * 1.02
                        
                    plan_sl = sl_candidate
                    risk = plan_sl - plan_entry
                    plan_tp = plan_entry - (risk * 2)

        # Format String
        def fmt(x): return f"{x:,.0f}".replace(",", ".")
        
        f_curr = fmt(curr)
        f_tp = fmt(plan_tp) if plan_tp > 0 else "-"
        f_sl = fmt(plan_sl) if plan_sl > 0 else "-"
        f_entry = fmt(plan_entry) if plan_entry > 0 else "-"
        
        # Confluence Check (Lampu Indikator)
        last = df.iloc[-1]
        is_ema_uptrend = last['EMA_9'] > last['EMA_21']
        is_big_trend = last['close'] > last['EMA_200']
        
        c_ema = "#00e676" if is_ema_uptrend else "#ff1744"
        c_big = "#00e676" if is_big_trend else "#ff1744"
        c_mom = "#00e676" if last['MACD'] > last['MACD_SIGNAL'] else "#ff1744"

        # --- CSS ISOLATED ---
        st.markdown("""
        <style>
            .grid-market { display: grid; grid-template-columns: 1.5fr 1fr 1fr 1fr 1fr; gap: 8px; margin-bottom: 10px; }
            .grid-plan { display: grid; grid-template-columns: 1fr 1fr 1fr 1.5fr; gap: 8px; margin-bottom: 20px; }
            .box { background: #1e1e1e; border: 1px solid #333; padding: 10px; border-radius: 6px; text-align: center; }
            .sig-box { padding: 10px; border-radius: 6px; text-align: center; display: flex; flex-direction: column; justify-content: center; }
            
            .lbl { font-size: 9px; color: #bbb; font-weight: bold; margin-bottom: 4px; }
            .val { font-size: 14px; font-weight: bold; color: white; }
            .val-lg { font-size: 16px; font-weight: 900; }
            
            .conf-row { display: flex; justify-content: space-between; font-size: 10px; margin-top: 4px; padding-bottom: 4px; border-bottom: 1px solid #333; }
        </style>
        """, unsafe_allow_html=True)

        # --- HTML UI ---
        st.markdown(f"""
        <div class="grid-market">
            <div class="sig-box" style="background: {sig_bg}; border: 2px solid {sig_col};">
                <div class="lbl">{source_label}</div>
                <div class="val-lg" style="color: {sig_col};">{active_signal}</div>
            </div>
            <div class="box">
                <div class="lbl">HARGA</div>
                <div class="val" style="color: #f1c40f;">Rp {f_curr}</div>
            </div>
            <div class="box"><div class="lbl">VOL 24J</div><div class="val">{vol:,.0f}</div></div>
            <div class="box"><div class="lbl">LOW</div><div class="val" style="color: #ff1744;">{fmt(low_24)}</div></div>
            <div class="box"><div class="lbl">HIGH</div><div class="val" style="color: #00e676;">{fmt(high_24)}</div></div>
        </div>
        
        <div class="grid-plan">
            <div class="box" style="border-top: 3px solid #f1c40f;">
                <div class="lbl">ENTRY PLAN</div>
                <div class="val" style="color: #f1c40f;">{f_entry}</div>
            </div>
            <div class="box" style="border-top: 3px solid #00e676;">
                <div class="lbl">TAKE PROFIT</div>
                <div class="val" style="color: #00e676;">{f_tp}</div>
            </div>
            <div class="box" style="border-top: 3px solid #ff1744;">
                <div class="lbl">STOP LOSS</div>
                <div class="val" style="color: #ff1744;">{f_sl}</div>
            </div>
            <div class="box" style="text-align: left; padding: 8px 15px;">
                <div class="lbl" style="text-align: center;">MARKET CONFLUENCE</div>
                <div class="conf-row">
                    <span style="color:#ccc">EMA CROSS (9/21)</span>
                    <span style="color:{c_ema}; font-weight:bold;">{'BULLISH' if is_ema_uptrend else 'BEARISH'}</span>
                </div>
                <div class="conf-row">
                    <span style="color:#ccc">BIG TREND (200)</span>
                    <span style="color:{c_big}; font-weight:bold;">{'UPTREND' if is_big_trend else 'DOWNTREND'}</span>
                </div>
                 <div class="conf-row" style="border:none;">
                    <span style="color:#ccc">MOMENTUM</span>
                    <span style="color:{c_mom}; font-weight:bold;">{'STRONG' if last['MACD'] > last['MACD_SIGNAL'] else 'WEAK'}</span>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # --- CHART ---
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
        
        # 1. Harga & EMA
        fig.add_trace(go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Harga'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['EMA_9'], line=dict(color='#2979ff', width=1.5), name='EMA 9 (Fast)'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['EMA_21'], line=dict(color='#ff9100', width=1.5), name='EMA 21 (Slow)'), row=1, col=1)
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['EMA_200'], line=dict(color='white', width=1, dash='dot'), name='EMA 200'), row=1, col=1)
        
        # 2. Marker Sinyal
        # Marker EMA Cross
        ema_crosses = df[df['signal_source'] == "EMA CROSS"]
        if not ema_crosses.empty:
             fig.add_trace(go.Scatter(x=ema_crosses['timestamp'], y=ema_crosses['close'], mode='markers', marker=dict(symbol='circle-open', size=8, color='yellow'), name='EMA Cross'), row=1, col=1)
        
        # Marker SMC
        smc_sigs = df[df['signal_source'] == "SMC ACTION"]
        if not smc_sigs.empty:
             fig.add_trace(go.Scatter(x=smc_sigs['timestamp'], y=smc_sigs['high'], mode='markers', marker=dict(symbol='diamond', size=12, color='#d500f9'), name='SMC Signal'), row=1, col=1)

        # 3. MACD
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['MACD'], line=dict(color='#00e676'), name='MACD'), row=2, col=1)
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['MACD_SIGNAL'], line=dict(color='#ff1744'), name='Signal'), row=2, col=1)
        
        fig.update_layout(height=600, template="plotly_dark", margin=dict(l=0,r=0,t=30,b=0), xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"Menunggu data... {e}")

show_dashboard(symbol, timeframe)
