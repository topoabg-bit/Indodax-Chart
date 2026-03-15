import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import pytz

# --- 1. KONFIGURASI ---
st.set_page_config(layout="wide", page_title="Scalper V4: SnD & MACD Zoom")

# --- 2. DATA & INDIKATOR ENGINE ---
def get_data(symbol, tf):
    exchange = ccxt.indodax()
    try:
        # Ambil 500 data (History panjang untuk EMA 200)
        ohlcv = exchange.fetch_ohlcv(symbol, tf, limit=500)
        if not ohlcv: return pd.DataFrame(), None
        
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        # Konversi ke WIB
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize('UTC').dt.tz_convert('Asia/Jakarta')
        ticker = exchange.fetch_ticker(symbol)
        return df, ticker
    except Exception as e:
        st.error(f"Gangguan koneksi: {e}")
        return pd.DataFrame(), None

def process_technical(df):
    if df.empty: return df
    
    # A. Trend Filter (EMA 200)
    df['EMA_200'] = df['close'].ewm(span=200, adjust=False).mean()
    
    # B. MACD (12, 26, 9)
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['Hist'] = df['MACD'] - df['Signal']
    
    # C. Volume & ATR
    df['Vol_MA'] = df['volume'].rolling(20).mean()
    df['Vol_Spike'] = df['volume'] > df['Vol_MA']
    
    df['tr'] = np.maximum(df['high'] - df['low'], 
               np.maximum(abs(df['high'] - df['close'].shift()), abs(df['low'] - df['close'].shift())))
    df['ATR'] = df['tr'].ewm(span=14).mean()
    
    # D. Candle Pattern (Rebound Trigger)
    # Bullish Engulfing
    df['Bull_Engulf'] = (df['close'] > df['open']) & (df['close'] > df['open'].shift(1)) & \
                        (df['open'] < df['close'].shift(1)) & (df['close'].shift(1) < df['open'].shift(1))
    # Bearish Engulfing
    df['Bear_Engulf'] = (df['close'] < df['open']) & (df['close'] < df['open'].shift(1)) & \
                        (df['open'] > df['close'].shift(1)) & (df['close'].shift(1) > df['open'].shift(1))

    return df

def detect_zones(df):
    """
    Deteksi Supply & Demand Area (Order Blocks)
    Hanya mengambil zona yang 'Fresh' atau relevan dalam 100 bar terakhir
    """
    zones = []
    
    # Parameter Impulsif
    vol_ma = df['volume'].rolling(20).mean()
    body_size = (df['close'] - df['open']).abs()
    avg_body = body_size.rolling(20).mean()
    
    # Scan 100 candle terakhir
    start_scan = len(df) - 100
    if start_scan < 0: start_scan = 0
    
    for i in range(start_scan, len(df)-2):
        curr = df.iloc[i]
        prev = df.iloc[i-1]
        
        # Deteksi pergerakan kuat (Impulse)
        is_impulsive = (curr['volume'] > vol_ma.iloc[i]) and (body_size.iloc[i] > avg_body.iloc[i])
        
        # DEMAND (Sebelum Naik Kuat)
        if is_impulsive and curr['close'] > curr['open'] and prev['close'] < prev['open']:
            zones.append({
                'type': 'DEMAND',
                'top': prev['high'],
                'bot': prev['low'],
                'time': prev['timestamp'],
                'color': 'rgba(41, 182, 246, 0.3)', # Biru Muda Transparan
                'border': 'rgba(41, 182, 246, 0.8)'
            })
            
        # SUPPLY (Sebelum Turun Kuat)
        elif is_impulsive and curr['close'] < curr['open'] and prev['close'] > prev['open']:
            zones.append({
                'type': 'SUPPLY',
                'top': prev['high'],
                'bot': prev['low'],
                'time': prev['timestamp'],
                'color': 'rgba(255, 167, 38, 0.3)', # Orange Transparan
                'border': 'rgba(255, 167, 38, 0.8)'
            })
    
    # Filter Zona: Hapus zona yang sudah ditembus total (Broken)
    active_zones = []
    curr_price = df['close'].iloc[-1]
    
    for z in zones:
        # Ambil data setelah zona terbentuk
        future_df = df[df['timestamp'] > z['time']]
        if future_df.empty: 
            active_zones.append(z)
            continue
            
        if z['type'] == 'DEMAND':
            # Jika ada candle close di bawah zona demand, anggap broken
            if not (future_df['close'] < z['bot']).any():
                active_zones.append(z)
        else:
            # Jika ada candle close di atas zona supply, anggap broken
            if not (future_df['close'] > z['top']).any():
                active_zones.append(z)
                
    return active_zones

# --- 3. DASHBOARD UTAMA ---
st.sidebar.header("🎛️ Scalping Control")
symbol = st.sidebar.selectbox("Pair", ['BTC/IDR', 'ETH/IDR', 'SOL/IDR', 'DOGE/IDR', 'XRP/IDR', 'SHIB/IDR'])
timeframe = st.sidebar.selectbox("Timeframe", ['1m', '15m', '30m', '1h', '4h'])

st.title(f"Scalper Pro V4: {symbol} ({timeframe})")

@st.fragment(run_every=60)
def main_dashboard(sym, tf):
    # 1. Proses Data
    df, ticker = get_data(sym, tf)
    if df.empty: return
    
    df = process_technical(df)
    zones = detect_zones(df)
    
    # 2. Data Realtime
    curr = float(ticker['last'])
    last = df.iloc[-1]
    atr = last['ATR']
    
    # 3. Analisa Signal & Plan
    status = "TUNGGU / SIDEWAYS"
    sig_col = "#888"
    entry_plan = "-"
    tp_plan = "-"
    sl_plan = "-"
    
    # Cari Zone Terdekat dengan harga sekarang
    nearest_dem = None
    nearest_sup = None
    
    # Logic mencari zona terdekat
    for z in zones:
        if z['type'] == 'DEMAND' and z['top'] < curr: # Zone dibawah harga
            if nearest_dem is None or z['top'] > nearest_dem['top']: nearest_dem = z
        if z['type'] == 'SUPPLY' and z['bot'] > curr: # Zone diatas harga
            if nearest_sup is None or z['bot'] < nearest_sup['bot']: nearest_sup = z
            
    # LOGIKA SINYAL (MACD + Volume + Candle di Area SnD)
    
    # A. SETUP BUY
    if nearest_dem:
        # Harga menyentuh area Demand (atau sangat dekat)
        in_zone = curr <= nearest_dem['top'] * 1.005 and curr >= nearest_dem['bot']
        
        if in_zone:
            status = "PERSIAPAN BUY (LIMIT)"
            sig_col = "#ffeb3b" # Kuning
            entry_plan = f"{nearest_dem['bot']:,.0f} - {nearest_dem['top']:,.0f}"
            
            # Konfirmasi MACD Golden Cross / Bullish Candle
            if (last['MACD'] > last['Signal']) and (last['Bull_Engulf'] or last['Vol_Spike']):
                status = "BUY SEKARANG (CONFIRMED)"
                sig_col = "#00e676" # Hijau
                
                sl_val = nearest_dem['bot'] - atr
                tp_val = nearest_dem['top'] + (2 * (nearest_dem['top'] - sl_val)) # RR 1:2
                
                sl_plan = f"{sl_val:,.0f}"
                tp_plan = f"{tp_val:,.0f}"
                
                # Mark Sinyal di Dataframe (Untuk Chart)
                df.loc[df.index[-1], 'buy_signal'] = True

    # B. SETUP SELL
    if nearest_sup:
        in_zone = curr >= nearest_sup['bot'] * 0.995 and curr <= nearest_sup['top']
        
        if in_zone:
            status = "PERSIAPAN SELL (LIMIT)"
            sig_col = "#ff9100" # Orange
            entry_plan = f"{nearest_sup['bot']:,.0f} - {nearest_sup['top']:,.0f}"
            
            if (last['MACD'] < last['Signal']) and (last['Bear_Engulf'] or last['Vol_Spike']):
                status = "SELL SEKARANG (CONFIRMED)"
                sig_col = "#ff1744" # Merah
                
                sl_val = nearest_sup['top'] + atr
                tp_val = nearest_sup['bot'] - (2 * (sl_val - nearest_sup['bot']))
                
                sl_plan = f"{sl_val:,.0f}"
                tp_plan = f"{tp_val:,.0f}"
                
                df.loc[df.index[-1], 'sell_signal'] = True

    # Format Helper
    def fmt(x): return f"{x:,.0f}".replace(",", ".")

    # --- LAYOUT HTML ---
    st.markdown(f"""
    <style>
        .grid-info {{ display: grid; grid-template-columns: 2fr 1fr 1fr 1fr; gap: 8px; margin-bottom: 10px; }}
        .grid-plan {{ display: grid; grid-template-columns: 1.5fr 1fr 1fr 1.5fr; gap: 8px; margin-bottom: 20px; }}
        .box {{ background: #1e1e1e; border: 1px solid #333; padding: 10px; border-radius: 6px; text-align: center; }}
        .sig-box {{ background: {sig_col}20; border: 2px solid {sig_col}; padding: 10px; border-radius: 6px; text-align: center; }}
        .lbl {{ font-size: 10px; color: #aaa; font-weight: bold; text-transform: uppercase; margin-bottom: 4px; }}
        .val {{ font-size: 15px; font-weight: bold; color: white; }}
        .val-lg {{ font-size: 20px; font-weight: 900; color: {sig_col}; }}
    </style>
    
    <div class="grid-info">
        <div class="sig-box"><div class="lbl">STATUS PASAR</div><div class="val-lg">{status}</div></div>
        <div class="box"><div class="lbl">HARGA</div><div class="val" style="color:#f1c40f">Rp {fmt(curr)}</div></div>
        <div class="box"><div class="lbl">VOLATILITAS (ATR)</div><div class="val">{fmt(atr)}</div></div>
        <div class="box"><div class="lbl">VOLUME</div><div class="val">{'✅ TINGGI' if last['Vol_Spike'] else 'NORMAL'}</div></div>
    </div>
    
    <div class="grid-plan">
        <div class="box" style="border-top: 3px solid #29b6f6"><div class="lbl">AREA ENTRY (SnD)</div><div class="val" style="color:#29b6f6">{entry_plan}</div></div>
        <div class="box" style="border-top: 3px solid #00e676"><div class="lbl">TAKE PROFIT</div><div class="val" style="color:#00e676">Rp {tp_plan}</div></div>
        <div class="box" style="border-top: 3px solid #ff1744"><div class="lbl">STOP LOSS</div><div class="val" style="color:#ff1744">Rp {sl_plan}</div></div>
        <div class="box"><div class="lbl">MACD MOMENTUM</div><div class="val" style="font-size:12px">
             {'🟢 BULLISH' if last['MACD'] > last['Signal'] else '🔴 BEARISH'} (Hist: {last['Hist']:.2f})
        </div></div>
    </div>
    """, unsafe_allow_html=True)
    
    # --- CHARTING SYSTEM (ZOOMED) ---
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.75, 0.25])
    
    # 1. Candlestick (Data 500 Candle)
    fig.add_trace(go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Harga'), row=1, col=1)
    
    # 2. EMA 200
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['EMA_200'], line=dict(color='yellow', width=2), name='EMA 200'), row=1, col=1)
    
    # 3. Supply & Demand Zones
    for z in zones:
        # Extend zona ke masa depan (3 jam ke depan dari candle terakhir)
        end_time = df['timestamp'].iloc[-1] + timedelta(hours=3)
        
        fig.add_shape(type="rect",
            x0=z['time'], y0=z['bot'], x1=end_time, y1=z['top'],
            fillcolor=z['color'], line_color=z['border'], line_width=1,
            row=1, col=1
        )

    # 4. Buy/Sell Markers (Panah)
    if 'buy_signal' in df.columns:
        buys = df[df['buy_signal'] == True]
        fig.add_trace(go.Scatter(x=buys['timestamp'], y=buys['low'], mode='markers', marker=dict(symbol='triangle-up', size=12, color='#00e676'), name='BUY Signal'), row=1, col=1)
        
    if 'sell_signal' in df.columns:
        sells = df[df['sell_signal'] == True]
        fig.add_trace(go.Scatter(x=sells['timestamp'], y=sells['high'], mode='markers', marker=dict(symbol='triangle-down', size=12, color='#ff1744'), name='SELL Signal'), row=1, col=1)

    # 5. MACD Subplot
    fig.add_trace(go.Bar(x=df['timestamp'], y=df['Hist'], marker_color=np.where(df['Hist']<0, '#ff1744', '#00e676'), name='Histogram'), row=2, col=1)
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['MACD'], line=dict(color='#2979ff'), name='MACD'), row=2, col=1)
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['Signal'], line=dict(color='#ff9100'), name='Signal'), row=2, col=1)

    # --- KONFIGURASI ZOOM & WAKTU ---
    # Hitung range waktu untuk 60 candle terakhir
    range_end = df['timestamp'].iloc[-1] + timedelta(minutes=30) # Buffer kanan kosong
    range_start = df['timestamp'].iloc[-60] 
    
    fig.update_layout(
        height=600, template="plotly_dark", margin=dict(l=0,r=50,t=10,b=0),
        xaxis_rangeslider_visible=False,
        xaxis_range=[range_start, range_end], # Default View 60 Candle
        xaxis2_range=[range_start, range_end] # Sync dengan MACD
    )
    
    st.plotly_chart(fig, use_container_width=True)
    
    # --- TABEL RENTANG HARGA SnD (DIBAWAH CHART) ---
    st.subheader("📋 Daftar Area Supply & Demand (Aktif)")
    
    if zones:
        table_data = []
        for z in reversed(zones[-5:]): # Ambil 5 terbaru saja
            tipe = "🟦 DEMAND (BUY LIMIT)" if z['type'] == 'DEMAND' else "🟧 SUPPLY (SELL LIMIT)"
            range_harga = f"Rp {fmt(z['bot'])} - Rp {fmt(z['top'])}"
            waktu = z['time'].strftime('%H:%M %d/%m')
            table_data.append([tipe, range_harga, waktu])
            
        df_table = pd.DataFrame(table_data, columns=["Tipe Zona", "Rentang Harga (Area)", "Waktu Terbentuk"])
        st.table(df_table)
    else:
        st.info("Belum ada zona Supply/Demand yang valid terbentuk di timeframe ini.")

main_dashboard(symbol, timeframe)
