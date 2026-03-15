import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import pytz

# --- 1. KONFIGURASI ---
st.set_page_config(layout="wide", page_title="SMC Scalping: Clean Chart")

# --- 2. ENGINE SMC (LOGIC MITIGASI) ---
def process_smc(df):
    # A. RSI & ATR
    df['delta'] = df['close'].diff()
    gain = (df['delta'].where(df['delta'] > 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    loss = (-df['delta'].where(df['delta'] < 0, 0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    df['tr'] = np.maximum(df['high'] - df['low'], 
               np.maximum(abs(df['high'] - df['close'].shift()), abs(df['low'] - df['close'].shift())))
    df['ATR'] = df['tr'].ewm(span=14).mean()

    # B. DETEKSI FVG RAW
    # Bullish FVG: Low Candle 3 > High Candle 1
    df['fvg_bull'] = (df['low'] > df['high'].shift(2)) & (df['close'] > df['open'])
    df['bull_top'] = df['low']           
    df['bull_bot'] = df['high'].shift(2) 
    
    # Bearish FVG: High Candle 3 < Low Candle 1
    df['fvg_bear'] = (df['high'] < df['low'].shift(2)) & (df['close'] < df['open'])
    df['bear_top'] = df['low'].shift(2)
    df['bear_bot'] = df['high']

    return df

def check_mitigation(df):
    # Fungsi ini memfilter FVG yang sudah basi (sudah tersentuh harga masa depan)
    bullish_zones = []
    bearish_zones = []
    
    # Scan Bullish FVG
    indices = df.index[df['fvg_bull']]
    for idx in indices:
        top = df.loc[idx, 'bull_top']
        bot = df.loc[idx, 'bull_bot']
        
        # Cek candle SETELAH pembentukan FVG (idx+1 sampai akhir)
        future_candles = df.loc[idx+1:]
        
        if future_candles.empty:
            # FVG terbentuk di candle terakhir (Fresh banget)
            bullish_zones.append({'idx': idx, 'top': top, 'bot': bot, 'time': df.loc[idx, 'timestamp'], 'status': 'FRESH'})
            continue
            
        # Cek apakah ada Low candle masa depan yang menyentuh Top FVG?
        # Jika Low <= Top, berarti sudah "Mitigated" (Disentuh)
        is_mitigated = (future_candles['low'] <= top).any()
        
        if not is_mitigated:
            bullish_zones.append({'idx': idx, 'top': top, 'bot': bot, 'time': df.loc[idx, 'timestamp'], 'status': 'FRESH'})
        
        # Jika candle terakhir sedang menyentuh, ini adalah SINYAL
        elif (future_candles.iloc[-1]['low'] <= top) and (future_candles.iloc[-1]['low'] >= bot):
             bullish_zones.append({'idx': idx, 'top': top, 'bot': bot, 'time': df.loc[idx, 'timestamp'], 'status': 'TESTING NOW'})

    # Scan Bearish FVG
    indices = df.index[df['fvg_bear']]
    for idx in indices:
        top = df.loc[idx, 'bear_top']
        bot = df.loc[idx, 'bear_bot']
        future_candles = df.loc[idx+1:]
        
        if future_candles.empty:
             bearish_zones.append({'idx': idx, 'top': top, 'bot': bot, 'time': df.loc[idx, 'timestamp'], 'status': 'FRESH'})
             continue
             
        # Jika High >= Bot, berarti Mitigated
        is_mitigated = (future_candles['high'] >= bot).any()
        
        if not is_mitigated:
            bearish_zones.append({'idx': idx, 'top': top, 'bot': bot, 'time': df.loc[idx, 'timestamp'], 'status': 'FRESH'})
        elif (future_candles.iloc[-1]['high'] >= bot) and (future_candles.iloc[-1]['high'] <= top):
            bearish_zones.append({'idx': idx, 'top': top, 'bot': bot, 'time': df.loc[idx, 'timestamp'], 'status': 'TESTING NOW'})
            
    return bullish_zones, bearish_zones

def get_data(symbol, timeframe):
    exchange = ccxt.indodax()
    ticker = exchange.fetch_ticker(symbol)
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=200)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize('UTC').dt.tz_convert('Asia/Jakarta')
    return df, ticker

# --- 3. DASHBOARD ---
st.sidebar.header("Scalping Setup")
symbol = st.sidebar.selectbox("Pasar", ['BTC/IDR', 'ETH/IDR', 'SOL/IDR', 'DOGE/IDR', 'XRP/IDR', 'SHIB/IDR'])
timeframe = st.sidebar.selectbox("Timeframe", ['15m', '1h', '4h'])

st.title(f"SMC Scalper: {symbol}")

@st.fragment(run_every=30)
def show_dashboard(sym, tf):
    try:
        df_raw, ticker = get_data(sym, tf)
        df = process_smc(df_raw)
        bull_zones, bear_zones = check_mitigation(df)
        
        curr = float(ticker['last'])
        rsi = df['RSI'].iloc[-1]
        atr = df['ATR'].iloc[-1]
        
        # --- ANALISA SINYAL ---
        signal_text = "WAITING FOR RETEST..."
        signal_bg = "#262730"
        signal_col = "#aaa"
        
        active_plan = None
        
        # Cek apakah ada zona yang statusnya "TESTING NOW"
        # Prioritas Sinyal
        for z in bull_zones:
            if z['status'] == 'TESTING NOW' and rsi < 50:
                signal_text = "BUY SIGNAL (FVG RETEST)"
                signal_bg = "rgba(0, 255, 0, 0.2)"
                signal_col = "#00e676"
                active_plan = z
                active_plan['type'] = 'bull'
                break # Ambil satu saja
                
        if active_plan is None:
            for z in bear_zones:
                if z['status'] == 'TESTING NOW' and rsi > 50:
                    signal_text = "SELL SIGNAL (FVG RETEST)"
                    signal_bg = "rgba(255, 0, 0, 0.2)"
                    signal_col = "#ff1744"
                    active_plan = z
                    active_plan['type'] = 'bear'
                    break

        # --- FORMAT ANGKA ---
        def fmt(x): return f"{x:,.0f}".replace(",", ".")
        
        sl_txt, tp_txt, entry_txt = "-", "-", "-"
        
        if active_plan:
            if active_plan['type'] == 'bull':
                entry_txt = f"{fmt(active_plan['bot'])} - {fmt(active_plan['top'])}"
                sl_val = active_plan['bot'] - (1.5 * atr)
                risk = active_plan['top'] - sl_val
                tp_val = active_plan['top'] + (risk * 2)
            else:
                entry_txt = f"{fmt(active_plan['bot'])} - {fmt(active_plan['top'])}"
                sl_val = active_plan['top'] + (1.5 * atr)
                risk = sl_val - active_plan['bot']
                tp_val = active_plan['bot'] - (risk * 2)
            
            sl_txt = fmt(sl_val)
            tp_txt = fmt(tp_val)

        # --- UI DASHBOARD ---
        st.markdown(f"""
        <style>
            .stat-container {{ display: grid; grid-template-columns: 1.5fr 1fr 1fr 1fr; gap: 8px; margin-bottom: 10px; }}
            .plan-container {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; margin-bottom: 15px; }}
            .box {{ background: #1e1e1e; border: 1px solid #333; padding: 10px; border-radius: 6px; text-align: center; }}
            .sig-box {{ background: {signal_bg}; border: 2px solid {signal_col}; padding: 10px; border-radius: 6px; text-align: center; }}
            .lbl {{ font-size: 9px; color: #aaa; font-weight: bold; margin-bottom: 3px; }}
            .val {{ font-size: 14px; color: white; font-weight: bold; }}
            .val-lg {{ font-size: 16px; color: {signal_col}; font-weight: 900; }}
        </style>
        
        <div class="stat-container">
            <div class="sig-box"><div class="lbl">STATUS PASAR</div><div class="val-lg">{signal_text}</div></div>
            <div class="box"><div class="lbl">HARGA</div><div class="val" style="color:#f1c40f">Rp {fmt(curr)}</div></div>
            <div class="box"><div class="lbl">RSI</div><div class="val">{rsi:.1f}</div></div>
            <div class="box"><div class="lbl">ATR (VOLATILITAS)</div><div class="val">{atr:,.0f}</div></div>
        </div>
        
        <div class="plan-container">
            <div class="box" style="border-top: 2px solid #2962ff">
                <div class="lbl">ZONA ENTRY (LIMIT)</div>
                <div class="val" style="color:#2962ff">{entry_txt}</div>
            </div>
            <div class="box" style="border-top: 2px solid #ff1744">
                <div class="lbl">STOP LOSS (1.5x ATR)</div>
                <div class="val" style="color:#ff1744">{sl_txt}</div>
            </div>
            <div class="box" style="border-top: 2px solid #00e676">
                <div class="lbl">TAKE PROFIT (1:2)</div>
                <div class="val" style="color:#00e676">{tp_txt}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # --- CHARTING ---
        fig = make_subplots(rows=1, cols=1)
        
        # 1. Candle
        fig.add_trace(go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Price'))
        
        # 2. Gambar FVG (Hanya yang FRESH / Belum Mitigasi)
        # Kita hanya gambar 5 zona terdekat dengan harga sekarang agar chart bersih
        
        def draw_zone(zones, color, name):
            count = 0
            for z in reversed(zones): # Mulai dari yang terbaru
                if count >= 3: break # Limit 3 kotak per tipe
                
                # Tentukan warna berdasarkan status
                fill_col = color
                line_w = 0
                if z['status'] == 'TESTING NOW':
                    fill_col = "rgba(255, 215, 0, 0.3)" # Kuning jika sedang dites
                    line_w = 2
                
                # Gambar Kotak
                fig.add_shape(type="rect",
                    x0=z['time'], y0=z['bot'], 
                    x1=df['timestamp'].iloc[-1] + timedelta(minutes=60*4), # Extend ke masa depan
                    y1=z['top'],
                    fillcolor=fill_col, line=dict(width=line_w, color="yellow"),
                )
                count += 1
        
        draw_zone(bull_zones, "rgba(0, 230, 118, 0.2)", "Buy Zone")  # Hijau Transparan
        draw_zone(bear_zones, "rgba(255, 23, 68, 0.2)", "Sell Zone") # Merah Transparan
        
        fig.update_layout(
            height=500, 
            template="plotly_dark", 
            margin=dict(l=0,r=0,t=10,b=0), 
            xaxis_rangeslider_visible=False,
            title_text=""
        )
        st.plotly_chart(fig, use_container_width=True)
        
        # --- TABEL DAFTAR ZONE (DI BAWAH CHART) ---
        st.markdown("### 📋 Daftar Zona Supply & Demand (Unmitigated)")
        
        # Siapkan data untuk tabel
        table_data = []
        for z in reversed(bull_zones[-5:]): # Ambil 5 terbaru
            table_data.append(["🟢 DEMAND (BUY)", fmt(z['top']), fmt(z['bot']), z['status']])
        for z in reversed(bear_zones[-5:]):
            table_data.append(["🔴 SUPPLY (SELL)", fmt(z['top']), fmt(z['bot']), z['status']])
            
        df_table = pd.DataFrame(table_data, columns=["Tipe", "Harga Atas", "Harga Bawah", "Status"])
        st.table(df_table)

    except Exception as e:
        st.error(f"Sedang memindai struktur... {e}")

show_dashboard(symbol, timeframe)
