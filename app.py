import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import pytz

# --- 1. KONFIGURASI ---
st.set_page_config(layout="wide", page_title="Scalper V5: History & Signals")

# --- 2. DATA & TEKNIKAL ---
def get_data(symbol, tf):
    exchange = ccxt.indodax()
    try:
        # Ambil 500 candle
        ohlcv = exchange.fetch_ohlcv(symbol, tf, limit=500)
        if not ohlcv: return pd.DataFrame(), None
        
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        # Waktu WIB
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize('UTC').dt.tz_convert('Asia/Jakarta')
        ticker = exchange.fetch_ticker(symbol)
        return df, ticker
    except Exception as e:
        st.error(f"Koneksi Error: {e}")
        return pd.DataFrame(), None

def process_indicators(df):
    if df.empty: return df
    
    # EMA 200 Trend
    df['EMA_200'] = df['close'].ewm(span=200, adjust=False).mean()
    
    # MACD
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['Hist'] = df['MACD'] - df['Signal']
    
    # Volume & ATR
    df['Vol_MA'] = df['volume'].rolling(20).mean()
    df['Vol_Spike'] = df['volume'] > df['Vol_MA']
    
    df['tr'] = np.maximum(df['high'] - df['low'], 
               np.maximum(abs(df['high'] - df['close'].shift()), abs(df['low'] - df['close'].shift())))
    df['ATR'] = df['tr'].ewm(span=14).mean()
    
    # Pola Candle
    df['Bull_Engulf'] = (df['close'] > df['open']) & (df['close'] > df['open'].shift(1)) & \
                        (df['open'] < df['close'].shift(1)) & (df['close'].shift(1) < df['open'].shift(1))
    
    df['Bear_Engulf'] = (df['close'] < df['open']) & (df['close'] < df['open'].shift(1)) & \
                        (df['open'] > df['close'].shift(1)) & (df['close'].shift(1) > df['open'].shift(1))
    return df

def detect_zones(df):
    """ Deteksi Supply & Demand 100 Candle Terakhir """
    zones = []
    vol_ma = df['volume'].rolling(20).mean()
    body_size = (df['close'] - df['open']).abs()
    avg_body = body_size.rolling(20).mean()
    
    start_scan = max(0, len(df) - 150) # Scan 150 candle terakhir
    
    for i in range(start_scan, len(df)-2):
        curr = df.iloc[i]
        prev = df.iloc[i-1]
        
        is_impulsive = (curr['volume'] > vol_ma.iloc[i]) and (body_size.iloc[i] > avg_body.iloc[i])
        
        # DEMAND (Biru)
        if is_impulsive and curr['close'] > curr['open'] and prev['close'] < prev['open']:
            zones.append({
                'type': 'DEMAND', 'top': prev['high'], 'bot': prev['low'], 
                'time': prev['timestamp'], 'color': 'rgba(41, 182, 246, 0.3)', 'border': 'rgba(41, 182, 246, 0.8)'
            })
        # SUPPLY (Orange)
        elif is_impulsive and curr['close'] < curr['open'] and prev['close'] > prev['open']:
            zones.append({
                'type': 'SUPPLY', 'top': prev['high'], 'bot': prev['low'], 
                'time': prev['timestamp'], 'color': 'rgba(255, 167, 38, 0.3)', 'border': 'rgba(255, 167, 38, 0.8)'
            })
            
    # Filter Zone Aktif
    active_zones = []
    for z in zones:
        future_df = df[df['timestamp'] > z['time']]
        if future_df.empty: 
            active_zones.append(z)
            continue
            
        # Hapus jika ditembus body candle
        if z['type'] == 'DEMAND':
            if not (future_df['close'] < z['bot']).any(): active_zones.append(z)
        else:
            if not (future_df['close'] > z['top']).any(): active_zones.append(z)
            
    return active_zones

def generate_signals_and_history(df, zones):
    """
    Looping untuk mencari histori sinyal Buy/Sell
    berdasarkan logika MACD + SnD
    """
    history_log = []
    
    # Kita hanya scan 100 candle terakhir untuk histori agar tidak terlalu berat
    start_idx = max(0, len(df) - 100)
    
    for i in range(start_idx, len(df)):
        row = df.iloc[i]
        close = row['close']
        
        # Cari zone yang relevan pada saat candle tersebut terjadi
        # Logika: Apakah harga Low/High menyentuh zone?
        
        # 1. CEK SINYAL BUY
        # Syarat: Candle Bullish/Spike + MACD Cross Up/Bullish + Harga di Demand
        macd_bull = row['MACD'] > row['Signal']
        trigger = row['Bull_Engulf'] or row['Vol_Spike']
        
        if macd_bull and trigger:
            # Cek apakah ada di Demand Zone?
            for z in zones:
                if z['type'] == 'DEMAND' and z['time'] < row['timestamp']:
                    # Harga masuk area
                    if row['low'] <= z['top']*1.005 and row['high'] >= z['bot']:
                        # SINYAL VALID
                        sl = z['bot'] - row['ATR']
                        risk = z['top'] - sl
                        tp = z['top'] + (risk * 2)
                        
                        # Simpan ke DF untuk Chart
                        df.loc[df.index[i], 'sig_buy'] = True
                        
                        # Simpan ke History Log
                        history_log.append({
                            'Waktu': row['timestamp'].strftime('%d/%m %H:%M'),
                            'Tipe': '🟢 BUY',
                            'Harga Entry': row['close'],
                            'Stop Loss': sl,
                            'Take Profit': tp,
                            'Status': 'Selesai' if i < len(df)-5 else 'Aktif'
                        })
                        break # Satu sinyal per candle cukup

        # 2. CEK SINYAL SELL
        macd_bear = row['MACD'] < row['Signal']
        trigger_sell = row['Bear_Engulf'] or row['Vol_Spike']
        
        if macd_bear and trigger_sell:
            for z in zones:
                if z['type'] == 'SUPPLY' and z['time'] < row['timestamp']:
                    if row['high'] >= z['bot']*0.995 and row['low'] <= z['top']:
                        sl = z['top'] + row['ATR']
                        risk = sl - z['bot']
                        tp = z['bot'] - (risk * 2)
                        
                        df.loc[df.index[i], 'sig_sell'] = True
                        
                        history_log.append({
                            'Waktu': row['timestamp'].strftime('%d/%m %H:%M'),
                            'Tipe': '🔴 SELL',
                            'Harga Entry': row['close'],
                            'Stop Loss': sl,
                            'Take Profit': tp,
                            'Status': 'Selesai' if i < len(df)-5 else 'Aktif'
                        })
                        break

    return df, history_log

# --- 3. DASHBOARD UTAMA ---
st.sidebar.header("🎛️ Scalper Dashboard V5")
symbol = st.sidebar.selectbox("Pair", ['BTC/IDR', 'ETH/IDR', 'SOL/IDR', 'DOGE/IDR', 'XRP/IDR', 'SHIB/IDR'])
timeframe = st.sidebar.selectbox("Timeframe", ['1m', '15m', '30m', '1h', '4h'])

st.title(f"Scalping Master: {symbol} ({timeframe})")

@st.fragment(run_every=60)
def main_app(sym, tf):
    # 1. Get Data
    df, ticker = get_data(sym, tf)
    if df.empty: return
    
    df = process_indicators(df)
    zones = detect_zones(df)
    
    # 2. Generate History & Signals
    df, history = generate_signals_and_history(df, zones)
    
    # 3. Status Realtime (Ambil sinyal terakhir dari History jika baru saja terjadi)
    curr_price = float(ticker['last'])
    last_signal = history[-1] if history else None
    
    # Cek apakah sinyal terakhir masih relevan (baru terjadi 1-3 candle lalu)
    status_txt = "WAITING..."
    sig_col = "#777"
    
    # Jika sinyal terakhir terjadi di candle terakhir atau sebelumnya
    if last_signal and last_signal['Status'] == 'Aktif':
        if "BUY" in last_signal['Tipe']:
            status_txt = "BUY SIGNAL ACTIVE"
            sig_col = "#00e676"
        else:
            status_txt = "SELL SIGNAL ACTIVE"
            sig_col = "#ff1744"
    
    # Format Angka
    def fmt(x): return f"{x:,.0f}".replace(",", ".")

    # --- HTML LAYOUT ---
    st.markdown(f"""
    <style>
        .grid-main {{ display: grid; grid-template-columns: 1.5fr 1fr 1fr 1fr; gap: 8px; margin-bottom: 15px; }}
        .box {{ background: #1e1e1e; border: 1px solid #333; padding: 10px; border-radius: 6px; text-align: center; }}
        .sig-box {{ background: {sig_col}20; border: 2px solid {sig_col}; padding: 10px; border-radius: 6px; text-align: center; }}
        .lbl {{ font-size: 10px; color: #aaa; font-weight: bold; margin-bottom: 4px; }}
        .val {{ font-size: 16px; font-weight: bold; color: white; }}
        .val-lg {{ font-size: 20px; font-weight: 900; color: {sig_col}; }}
    </style>
    
    <div class="grid-main">
        <div class="sig-box">
            <div class="lbl">STATUS SINYAL</div>
            <div class="val-lg">{status_txt}</div>
        </div>
        <div class="box">
            <div class="lbl">HARGA SAAT INI</div>
            <div class="val" style="color:#f1c40f">Rp {fmt(curr_price)}</div>
        </div>
        <div class="box">
            <div class="lbl">VOLATILITAS (ATR)</div>
            <div class="val">{fmt(df['ATR'].iloc[-1])}</div>
        </div>
        <div class="box">
            <div class="lbl">TREND (EMA 200)</div>
            <div class="val" style="color:{'#00e676' if curr_price > df['EMA_200'].iloc[-1] else '#ff1744'}">
                {'BULLISH' if curr_price > df['EMA_200'].iloc[-1] else 'BEARISH'}
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # --- CHART (ZOOMED 60 Candle) ---
    # Logic Zoom
    range_end = df['timestamp'].iloc[-1] + timedelta(minutes=30)
    range_start = df['timestamp'].iloc[-60] # Tampilkan 60 candle terakhir
    
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.75, 0.25])
    
    # 1. Candle
    fig.add_trace(go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Harga'), row=1, col=1)
    
    # 2. EMA 200
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['EMA_200'], line=dict(color='yellow', width=2), name='EMA 200'), row=1, col=1)
    
    # 3. Supply Demand Zones
    for z in zones:
        end_t = df['timestamp'].iloc[-1] + timedelta(hours=4)
        fig.add_shape(type="rect", x0=z['time'], y0=z['bot'], x1=end_t, y1=z['top'], 
                      fillcolor=z['color'], line_color=z['border'], line_width=1, row=1, col=1)
                      
    # 4. Arrows (Marker) Sinyal
    if 'sig_buy' in df.columns:
        buys = df[df['sig_buy'] == True]
        fig.add_trace(go.Scatter(x=buys['timestamp'], y=buys['low'], mode='markers', marker=dict(symbol='triangle-up', size=12, color='#00e676'), name='Buy Signal'), row=1, col=1)
        
    if 'sig_sell' in df.columns:
        sells = df[df['sig_sell'] == True]
        fig.add_trace(go.Scatter(x=sells['timestamp'], y=sells['high'], mode='markers', marker=dict(symbol='triangle-down', size=12, color='#ff1744'), name='Sell Signal'), row=1, col=1)

    # 5. MACD
    fig.add_trace(go.Bar(x=df['timestamp'], y=df['Hist'], marker_color=np.where(df['Hist']<0, '#ff1744', '#00e676'), name='Hist'), row=2, col=1)
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['MACD'], line=dict(color='#2962ff'), name='MACD'), row=2, col=1)
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['Signal'], line=dict(color='#ff9100'), name='Signal'), row=2, col=1)
    
    fig.update_layout(height=600, template="plotly_dark", margin=dict(l=0,r=50,t=0,b=0), xaxis_rangeslider_visible=False,
                      xaxis_range=[range_start, range_end], xaxis2_range=[range_start, range_end])
    st.plotly_chart(fig, use_container_width=True)
    
    # --- TABEL 1: SUPPLY & DEMAND (PLANNING) ---
    st.subheader("📋 Area Supply & Demand (Untuk Limit Order)")
    if zones:
        snd_data = []
        for z in reversed(zones[-5:]):
            tipe = "🟦 DEMAND (BUY)" if z['type'] == 'DEMAND' else "🟧 SUPPLY (SELL)"
            snd_data.append([tipe, f"Rp {fmt(z['bot'])} - Rp {fmt(z['top'])}", z['time'].strftime('%H:%M %d/%m')])
        st.table(pd.DataFrame(snd_data, columns=["Tipe Area", "Rentang Harga", "Waktu Terbentuk"]))
    else:
        st.info("Tidak ada zona Supply/Demand valid dekat harga saat ini.")
        
    # --- TABEL 2: HISTORI SINYAL (BACKTEST SIMPLE) ---
    st.subheader("📊 Histori Sinyal (MACD + SnD Trigger)")
    if history:
        # Reverse agar yang terbaru di atas
        hist_df = pd.DataFrame(history).iloc[::-1]
        
        # Formatting Tampilan Tabel
        def highlight_signal(val):
            color = '#00e676' if 'BUY' in val else '#ff1744'
            return f'color: {color}; font-weight: bold'
            
        st.dataframe(hist_df.style.map(highlight_signal, subset=['Tipe'])
                     .format({"Harga Entry": "Rp {:,.0f}", "Stop Loss": "Rp {:,.0f}", "Take Profit": "Rp {:,.0f}"}),
                     use_container_width=True)
    else:
        st.caption("Belum ada sinyal valid yang terdeteksi pada rentang data ini.")

main_app(symbol, timeframe)
