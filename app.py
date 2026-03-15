import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import pytz

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(layout="wide", page_title="Scalper V3: SnD + MACD")

# --- 2. ENGINE: DATA & INDIKATOR ---
def get_data(symbol, tf):
    exchange = ccxt.indodax()
    try:
        # Ambil 500 candle agar MACD & EMA valid
        ohlcv = exchange.fetch_ohlcv(symbol, tf, limit=500)
        if not ohlcv: return pd.DataFrame(), None
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize('UTC').dt.tz_convert('Asia/Jakarta')
        ticker = exchange.fetch_ticker(symbol)
        return df, ticker
    except Exception as e:
        st.error(f"Gagal ambil data: {e}")
        return pd.DataFrame(), None

def identify_snd_zones(df):
    """
    Mendeteksi Supply & Demand (Order Block)
    Logika: Area sebelum pergerakan impulsif (Body Besar + Volume Spike)
    """
    zones = []
    
    # Rata-rata volume & body size
    vol_ma = df['volume'].rolling(20).mean()
    body_size = (df['close'] - df['open']).abs()
    avg_body = body_size.rolling(20).mean()
    
    # Scan candle
    for i in range(len(df) - 5, 20, -1): # Cek 20 bar terakhir saja untuk SnD terdekat
        curr = df.iloc[i]
        prev = df.iloc[i-1]
        
        is_impulsive = (curr['volume'] > vol_ma.iloc[i] * 1.2) and (body_size.iloc[i] > avg_body.iloc[i])
        
        # DEMAND ZONE (Bullish OB)
        # Candle Merah sebelum Candle Hijau Besar Impulsif
        if is_impulsive and curr['close'] > curr['open'] and prev['close'] < prev['open']:
            zones.append({
                'type': 'DEMAND',
                'top': prev['high'],
                'bot': prev['low'],
                'time': prev['timestamp']
            })
            
        # SUPPLY ZONE (Bearish OB)
        # Candle Hijau sebelum Candle Merah Besar Impulsif
        elif is_impulsive and curr['close'] < curr['open'] and prev['close'] > prev['open']:
            zones.append({
                'type': 'SUPPLY',
                'top': prev['high'],
                'bot': prev['low'],
                'time': prev['timestamp']
            })
            
    return zones

def process_strategy(df):
    if df.empty: return df
    
    # 1. MACD (12, 26, 9)
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['Signal_Line'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['Hist'] = df['MACD'] - df['Signal_Line']
    
    # 2. Volume Spike
    df['Vol_MA'] = df['volume'].rolling(20).mean()
    df['Vol_Spike'] = df['volume'] > df['Vol_MA']
    
    # 3. ATR (Untuk SL/TP)
    df['tr'] = np.maximum(df['high'] - df['low'], 
               np.maximum(abs(df['high'] - df['close'].shift()), abs(df['low'] - df['close'].shift())))
    df['ATR'] = df['tr'].ewm(span=14).mean()

    # 4. Candlestick Patterns (Reversal)
    # Bullish Engulfing
    df['Bull_Engulf'] = (df['close'] > df['open']) & \
                        (df['close'] > df['open'].shift(1)) & \
                        (df['open'] < df['close'].shift(1)) & \
                        (df['close'].shift(1) < df['open'].shift(1))
    
    # Bearish Engulfing
    df['Bear_Engulf'] = (df['close'] < df['open']) & \
                        (df['close'] < df['open'].shift(1)) & \
                        (df['open'] > df['close'].shift(1)) & \
                        (df['close'].shift(1) > df['open'].shift(1))

    # Hammer (Pinbar Bawah)
    body = (df['close'] - df['open']).abs()
    lower_wick = df[['open', 'close']].min(axis=1) - df['low']
    df['Hammer'] = (lower_wick > (body * 2)) & (df['close'] > df['open'].shift(1)) # Hammer Hijau Valid

    return df

# --- 3. LOGIKA KEPUTUSAN ---
def analyze_market(df, zones, curr_price):
    last = df.iloc[-1]
    
    # Default State
    status = "TUNGGU"
    status_col = "#777"
    entry_area = "-"
    sl_area = "-"
    tp_area = "-"
    pattern_detect = "Tidak Ada Pola"
    
    # Cari Zone Terdekat
    nearest_demand = None
    nearest_supply = None
    
    for z in zones:
        if z['type'] == 'DEMAND' and z['top'] < curr_price: # Zone di bawah harga
            if nearest_demand is None or z['top'] > nearest_demand['top']:
                nearest_demand = z
        elif z['type'] == 'SUPPLY' and z['bot'] > curr_price: # Zone di atas harga
            if nearest_supply is None or z['bot'] < nearest_supply['bot']:
                nearest_supply = z

    # --- LOGIKA BUY ---
    # 1. Harga dekat/masuk Demand Area
    # 2. MACD > Signal (Golden Cross) atau Histogram mulai menipis naik
    # 3. Ada Candle Rebound (Hammer/Engulfing)
    if nearest_demand:
        dist_to_zone = (curr_price - nearest_demand['top']) / curr_price
        
        # Step 1: Persiapan (Harga mendekati Demand)
        if dist_to_zone < 0.005: # 0.5% jarak ke zone
            status = "PERSIAPAN BUY (LIMIT)"
            status_col = "#ffeb3b" # Kuning
            entry_area = f"{nearest_demand['bot']:,.0f} - {nearest_demand['top']:,.0f}"
            
            # Step 2: Konfirmasi Eksekusi
            # MACD Bullish + Candle Pattern + Volume
            macd_bullish = last['MACD'] > last['Signal_Line']
            candle_confirm = last['Bull_Engulf'] or last['Hammer']
            
            if macd_bullish and candle_confirm and last['Vol_Spike']:
                status = "BUY SEKARANG (REBOUND)"
                status_col = "#00e676"
                pattern_detect = "Bullish Engulfing/Hammer"
                
                # Hitung Plan
                sl_val = nearest_demand['bot'] - (last['ATR'] * 1.5)
                risk = nearest_demand['top'] - sl_val
                tp_val = nearest_demand['top'] + (risk * 2)
                
                sl_area = f"{sl_val:,.0f}"
                tp_area = f"{tp_val:,.0f}"

    # --- LOGIKA SELL ---
    if nearest_supply:
        dist_to_zone = (nearest_supply['bot'] - curr_price) / curr_price
        
        if dist_to_zone < 0.005:
            status = "PERSIAPAN SELL (LIMIT)"
            status_col = "#ff9100" # Orange
            entry_area = f"{nearest_supply['bot']:,.0f} - {nearest_supply['top']:,.0f}"
            
            macd_bearish = last['MACD'] < last['Signal_Line']
            candle_confirm = last['Bear_Engulf']
            
            if macd_bearish and candle_confirm and last['Vol_Spike']:
                status = "SELL SEKARANG (REJECT)"
                status_col = "#ff1744"
                pattern_detect = "Bearish Engulfing"
                
                sl_val = nearest_supply['top'] + (last['ATR'] * 1.5)
                risk = sl_val - nearest_supply['bot']
                tp_val = nearest_supply['bot'] - (risk * 2)
                
                sl_area = f"{sl_val:,.0f}"
                tp_area = f"{tp_val:,.0f}"
                
    return status, status_col, entry_area, sl_area, tp_area, nearest_demand, nearest_supply, pattern_detect

# --- 4. DASHBOARD UI ---
st.sidebar.header("🛠️ Pro Scalper Settings")
symbol = st.sidebar.selectbox("Pair", ['BTC/IDR', 'ETH/IDR', 'SOL/IDR', 'DOGE/IDR', 'XRP/IDR', 'SHIB/IDR'])
timeframe = st.sidebar.selectbox("Timeframe", ['15m', '30m', '1h', '4h', '1d'])

st.title(f"Scalper V3: Supply Demand & MACD - {symbol}")

@st.fragment(run_every=60)
def main(sym, tf):
    # Fetch Data
    df_full, ticker = get_data(sym, tf)
    if df_full.empty: return
    
    # Process Indicators
    df_full = process_strategy(df_full)
    zones = identify_snd_zones(df_full)
    
    curr_price = float(ticker['last'])
    
    # Analyze
    status, color, entry, sl, tp, dem_zone, sup_zone, pattern = analyze_market(df_full, zones, curr_price)
    
    # Data View (Zoomed) - Ambil 60 candle terakhir
    df_view = df_full.tail(60)
    
    # Format Helper
    def fmt(x): return f"{x:,.0f}".replace(",", ".")

    # --- LAYOUT GRID ---
    st.markdown(f"""
    <style>
        .row-1 {{ display: grid; grid-template-columns: 2fr 1fr 1fr 1fr; gap: 10px; margin-bottom: 10px; }}
        .row-2 {{ display: grid; grid-template-columns: 1.5fr 1fr 1fr 1.5fr; gap: 10px; margin-bottom: 20px; }}
        .box {{ background: #1e1e1e; border: 1px solid #333; padding: 12px; border-radius: 8px; text-align: center; }}
        .sig {{ background: {color}20; border: 2px solid {color}; padding: 12px; border-radius: 8px; text-align: center; }}
        .lbl {{ font-size: 10px; color: #aaa; font-weight: bold; margin-bottom: 5px; text-transform: uppercase; }}
        .val {{ font-size: 16px; font-weight: bold; color: white; }}
        .val-lg {{ font-size: 22px; font-weight: 900; color: {color}; }}
    </style>
    
    <!-- BARIS 1: INFO PASAR -->
    <div class="row-1">
        <div class="sig"><div class="lbl">STATUS SINYAL</div><div class="val-lg">{status}</div></div>
        <div class="box"><div class="lbl">HARGA</div><div class="val" style="color:#f1c40f">Rp {fmt(curr_price)}</div></div>
        <div class="box"><div class="lbl">VOLATILITAS (ATR)</div><div class="val">{fmt(df_full['ATR'].iloc[-1])}</div></div>
        <div class="box"><div class="lbl">VOLUME CHECK</div><div class="val">{'✅ SPIKE' if df_full['Vol_Spike'].iloc[-1] else 'NORMAL'}</div></div>
    </div>
    
    <!-- BARIS 2: TRADING PLAN (LIMIT) -->
    <div class="row-2">
        <div class="box" style="border-top: 3px solid #2979ff">
            <div class="lbl">ENTRY AREA (LIMIT ORDER)</div>
            <div class="val" style="color:#2979ff">{entry}</div>
        </div>
        <div class="box" style="border-top: 3px solid #00e676">
            <div class="lbl">TAKE PROFIT (1:2)</div>
            <div class="val" style="color:#00e676">Rp {tp}</div>
        </div>
        <div class="box" style="border-top: 3px solid #ff1744">
            <div class="lbl">STOP LOSS</div>
            <div class="val" style="color:#ff1744">Rp {sl}</div>
        </div>
        <div class="box">
            <div class="lbl">KONFIRMASI TEKNIKAL</div>
            <div class="val" style="font-size:12px; text-align:left; padding-left:10px;">
                1. MACD: <span style="color:{'#00e676' if df_full['MACD'].iloc[-1] > df_full['Signal_Line'].iloc[-1] else '#ff1744'}">
                   {'BULLISH' if df_full['MACD'].iloc[-1] > df_full['Signal_Line'].iloc[-1] else 'BEARISH'}</span><br>
                2. CANDLE: {pattern}
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # --- CHART VISUALIZATION ---
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
    
    # 1. Candlestick
    fig.add_trace(go.Candlestick(x=df_view['timestamp'], open=df_view['open'], high=df_view['high'], low=df_view['low'], close=df_view['close'], name='Harga'), row=1, col=1)
    
    # 2. Draw Supply Demand Zones (Hanya yang terdekat)
    if dem_zone:
        fig.add_shape(type="rect",
            x0=dem_zone['time'], y0=dem_zone['bot'], x1=df_view['timestamp'].iloc[-1] + timedelta(hours=4), y1=dem_zone['top'],
            fillcolor="rgba(0, 230, 118, 0.2)", line_color="rgba(0, 230, 118, 0.6)", line_width=1, row=1, col=1
        )
        fig.add_annotation(x=dem_zone['time'], y=dem_zone['bot'], text="DEMAND (BUY AREA)", showarrow=False, yshift=-10, font=dict(size=9, color="#00e676"), row=1, col=1)

    if sup_zone:
        fig.add_shape(type="rect",
            x0=sup_zone['time'], y0=sup_zone['bot'], x1=df_view['timestamp'].iloc[-1] + timedelta(hours=4), y1=sup_zone['top'],
            fillcolor="rgba(255, 23, 68, 0.2)", line_color="rgba(255, 23, 68, 0.6)", line_width=1, row=1, col=1
        )
        fig.add_annotation(x=sup_zone['time'], y=sup_zone['top'], text="SUPPLY (SELL AREA)", showarrow=False, yshift=10, font=dict(size=9, color="#ff1744"), row=1, col=1)

    # 3. MACD
    fig.add_trace(go.Bar(x=df_view['timestamp'], y=df_view['Hist'], name='Histogram', marker_color=np.where(df_view['Hist']<0, '#ff1744', '#00e676')), row=2, col=1)
    fig.add_trace(go.Scatter(x=df_view['timestamp'], y=df_view['MACD'], line=dict(color='#2962ff', width=1.5), name='MACD'), row=2, col=1)
    fig.add_trace(go.Scatter(x=df_view['timestamp'], y=df_view['Signal_Line'], line=dict(color='#ff6d00', width=1.5), name='Signal'), row=2, col=1)
    
    fig.update_layout(height=600, template="plotly_dark", margin=dict(l=0,r=0,t=0,b=0), xaxis_rangeslider_visible=False)
    st.plotly_chart(fig, use_container_width=True)
    
    # Logika Tabel
    st.caption("Catatan: 'Entry Area' adalah zona Supply/Demand terdekat yang dideteksi algoritma Volume Imbalance. Pasang Limit Order di dalam kotak transparan.")

main(symbol, timeframe)
