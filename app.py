import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import pytz
import requests

# --- 1. KONFIGURASI & SETUP ---
st.set_page_config(layout="wide", page_title="Indodax Scalper V8.1: Fee Guard")

# --- TELEGRAM SETTINGS (ISI DISINI) ---
def send_telegram(message):
    # GANTI DENGAN TOKEN & CHAT ID ANDA
    BOT_TOKEN = "7992906337:AAGPstFckZsaMmabZDA6m_EauP-aTqQxlZQ" 
    CHAT_ID = "8107526630"
    
    # Skip jika token belum diisi
    if "TOKEN_BOT" in BOT_TOKEN:
        return 
        
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    params = {'chat_id': CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    try:
        requests.get(url, params=params, timeout=3)
    except Exception as e:
        print(f"Telegram Error: {e}")

# --- 2. DATA ENGINE (CCXT INDODAX) ---
def get_data(symbol, tf):
    exchange = ccxt.indodax()
    try:
        # Mengambil 500 candle terakhir
        ohlcv = exchange.fetch_ohlcv(symbol, tf, limit=500)
        if not ohlcv: return pd.DataFrame(), None
        
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        # Konversi waktu ke WIB (Asia/Jakarta)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize('UTC').dt.tz_convert('Asia/Jakarta')
        
        ticker = exchange.fetch_ticker(symbol)
        return df, ticker
    except Exception as e:
        st.error(f"Koneksi Indodax Error: {e}")
        return pd.DataFrame(), None

def get_orderbook_analysis(symbol):
    try:
        exchange = ccxt.indodax()
        # Ambil 20 antrian teratas untuk mencari tembok tebal
        ob = exchange.fetch_order_book(symbol, limit=20)
        
        # 1. Cari Tembok Beli (Bid) Terbesar
        # Kita cari entry dengan Volume x Harga (Value) terbesar, atau Volume murni terbesar
        # Di sini kita cari Volume terbesar sebagai "Tembok"
        bids = pd.DataFrame(ob['bids'], columns=['price', 'volume'])
        max_bid_idx = bids['volume'].idxmax()
        wall_buy_price = bids.iloc[max_bid_idx]['price']
        wall_buy_vol = bids.iloc[max_bid_idx]['volume']
        
        # 2. Cari Tembok Jual (Ask) Terbesar
        asks = pd.DataFrame(ob['asks'], columns=['price', 'volume'])
        max_ask_idx = asks['volume'].idxmax()
        wall_sell_price = asks.iloc[max_ask_idx]['price']
        wall_sell_vol = asks.iloc[max_ask_idx]['volume']
        
        return {
            'buy_wall_price': wall_buy_price,
            'buy_wall_vol': wall_buy_vol,
            'sell_wall_price': wall_sell_price,
            'sell_wall_vol': wall_sell_vol,
            'bids_df': bids.head(5), # Untuk tabel mini
            'asks_df': asks.head(5)
        }
    except Exception as e:
        return None

# --- 3. INDIKATOR TEKNIKAL ---
def process_indicators(df):
    if df.empty: return df
    
    # 1. Trend Filter (EMA 200)
    df['EMA_200'] = df['close'].ewm(span=200, adjust=False).mean()
    
    # 2. Momentum (MACD)
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['Hist'] = df['MACD'] - df['Signal']
    
    # 3. Volatilitas (ATR)
    df['tr'] = np.maximum(df['high'] - df['low'], 
               np.maximum(abs(df['high'] - df['close'].shift()), abs(df['low'] - df['close'].shift())))
    df['ATR'] = df['tr'].ewm(span=14).mean()
    
    # 4. Volume & Pola Candle
    df['Vol_MA'] = df['volume'].rolling(20).mean()
    df['Vol_Spike'] = df['volume'] > df['Vol_MA']
    
    df['Bull_Engulf'] = (df['close'] > df['open']) & (df['close'] > df['open'].shift(1)) & \
                        (df['open'] < df['close'].shift(1))
    df['Bear_Engulf'] = (df['close'] < df['open']) & (df['close'] < df['open'].shift(1)) & \
                        (df['open'] > df['close'].shift(1))
                        
    # 5. RSI Calculation
    period = 14
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    return df

# --- 4. DETEKSI SUPPLY & DEMAND (FIXED) ---
def detect_zones(df):
    zones = []
    vol_ma = df['volume'].rolling(20).mean()
    body = (df['close'] - df['open']).abs()
    avg_body = body.rolling(20).mean()
    
    start = max(0, len(df) - 200) # Scan 200 candle terakhir
    for i in range(start, len(df)-2):
        curr = df.iloc[i]
        prev = df.iloc[i-1]
        
        # Syarat Zona: Candle Impulsif (Body besar + Volume besar)
        is_impulse = (curr['volume'] > vol_ma.iloc[i]) and (body.iloc[i] > avg_body.iloc[i])
        
        if is_impulse and curr['close'] > curr['open'] and prev['close'] < prev['open']:
            zones.append({'type': 'DEMAND', 'top': prev['high'], 'bot': prev['low'], 'time': prev['timestamp'],
                          'color': 'rgba(41, 182, 246, 0.3)', 'line': 'rgba(41, 182, 246, 0.8)'})
        elif is_impulse and curr['close'] < curr['open'] and prev['close'] > prev['open']:
            zones.append({'type': 'SUPPLY', 'top': prev['high'], 'bot': prev['low'], 'time': prev['timestamp'],
                          'color': 'rgba(255, 167, 38, 0.3)', 'line': 'rgba(255, 167, 38, 0.8)'})
            
    # --- VALIDASI ZONA (FIXED V8.1) ---
    active = []
    for z in zones:
        future = df[df['timestamp'] > z['time']]
        if future.empty:
            active.append(z)
        elif z['type'] == 'DEMAND':
            # FIX: Gunakan 'low' agar zona hangus jika ekor tembus bawah
            if not (future['low'] < z['bot']).any(): 
                active.append(z)
        else:
            # FIX: Gunakan 'high' agar zona hangus jika ekor tembus atas
            if not (future['high'] > z['top']).any(): 
                active.append(z)
    return active

# --- 5. LOGIKA SINYAL (FEE GUARD) ---
def generate_signals(df, zones):
    history = []
    df['sig_buy'] = False
    df['sig_sell'] = False
    start = max(1, len(df) - 100)
    
    for i in range(start, len(df)):
        row = df.iloc[i]
        prev_row = df.iloc[i-1]
        
        # --- PARAMETER ---
        safe_buy = row['RSI'] < 70  # Jangan beli di pucuk
        safe_sell = row['RSI'] > 30 # Jangan jual di dasar
        min_profit_percent = 0.008  # WAJIB 0.8% untuk cover fee Indodax (0.6%)
        
        # Pola Candle
        is_hammer = (row['close'] > row['open']) and ((row['open'] - row['low']) > 2 * (row['close'] - row['open']))
        is_shooting_star = (row['open'] > row['close']) and ((row['high'] - row['open']) > 2 * (row['open'] - row['close']))
        
        # Trigger Gabungan
        trigger_buy_zone = row['Bull_Engulf'] or row['Vol_Spike'] or is_hammer
        trigger_sell_zone = row['Bear_Engulf'] or row['Vol_Spike'] or is_shooting_star
        
        # MACD Cross
        macd_cross_buy = (prev_row['MACD'] < prev_row['Signal']) and (row['MACD'] > row['Signal'])
        macd_cross_sell = (prev_row['MACD'] > prev_row['Signal']) and (row['MACD'] < row['Signal'])

        zone_signal_taken = False
        entry_price = row['close']
        tp, sl = 0, 0

        # --- STRATEGI 1: ZONE BASED ---
        if row['MACD'] > row['Signal'] and trigger_buy_zone and safe_buy:
            for z in zones:
                if z['type'] == 'DEMAND' and z['time'] < row['timestamp']:
                    # Harga mantul di area Demand
                    if row['low'] <= z['top']*1.015 and row['high'] >= z['bot']:
                        sl = z['bot'] - row['ATR']
                        tp = z['top'] + ((z['top'] - sl) * 1.5) # RR 1:1.5
                        
                        # --- FEE GUARD CHECK ---
                        if (tp - entry_price) / entry_price > min_profit_percent:
                            df.loc[df.index[i], 'sig_buy'] = True
                            history.append({'Waktu': row['timestamp'], 'Tipe': 'BUY (Zone)', 'Entry': entry_price, 'SL': sl, 'TP': tp, 'Status': 'Active'})
                            zone_signal_taken = True
                        break

        if row['MACD'] < row['Signal'] and trigger_sell_zone and safe_sell:
            for z in zones:
                if z['type'] == 'SUPPLY' and z['time'] < row['timestamp']:
                    if row['high'] >= z['bot']*0.985 and row['low'] <= z['top']:
                        sl = z['top'] + row['ATR']
                        tp = z['bot'] - ((sl - z['bot']) * 1.5)
                        
                        # --- FEE GUARD CHECK ---
                        if (entry_price - tp) / entry_price > min_profit_percent:
                            df.loc[df.index[i], 'sig_sell'] = True
                            history.append({'Waktu': row['timestamp'], 'Tipe': 'SELL (Zone)', 'Entry': entry_price, 'SL': sl, 'TP': tp, 'Status': 'Active'})
                            zone_signal_taken = True
                        break

        # --- STRATEGI 2: MOMENTUM ONLY ---
        if not zone_signal_taken:
            if macd_cross_buy and safe_buy:
                sl = row['low'] - (row['ATR'] * 1.5)
                risk = entry_price - sl
                tp = entry_price + (risk * 1.5)
                
                if (tp - entry_price) / entry_price > min_profit_percent:
                    df.loc[df.index[i], 'sig_buy'] = True
                    history.append({'Waktu': row['timestamp'], 'Tipe': 'BUY (Momtm)', 'Entry': entry_price, 'SL': sl, 'TP': tp, 'Status': 'Active'})

            elif macd_cross_sell and safe_sell:
                sl = row['high'] + (row['ATR'] * 1.5)
                risk = sl - entry_price
                tp = entry_price - (risk * 1.5)
                
                if (entry_price - tp) / entry_price > min_profit_percent:
                    df.loc[df.index[i], 'sig_sell'] = True
                    history.append({'Waktu': row['timestamp'], 'Tipe': 'SELL (Momtm)', 'Entry': entry_price, 'SL': sl, 'TP': tp, 'Status': 'Active'})
                        
    return df, history

# --- 6. DASHBOARD & VISUALISASI ---
st.sidebar.header("🎛️ Indodax Scalper V8.1")
symbol = st.sidebar.selectbox("Pair", ['BTC/IDR', 'ETH/IDR', 'SOL/IDR', 'DOGE/IDR', 'XRP/IDR', 'SHIB/IDR', 'USDT/IDR'])
timeframe = st.sidebar.selectbox("Timeframe", ['1m', '5m', '15m', '30m', '1h', '4h', '1d'])
st.title(f"Scalper Pro: {symbol} ({timeframe})")

# --- 7. DASHBOARD VISUAL (V8.2 UPGRADE) ---
@st.fragment(run_every=60)
def dashboard(sym, tf):
    # 1. Load Data
    df, ticker = get_data(sym, tf)
    if df.empty:
        st.warning("Menunggu data...")
        return
        
    df = process_indicators(df)
    zones = detect_zones(df)
    df, history = generate_signals(df, zones)
    
    # 2. Analisa Orderbook (WALL DETECTOR)
    ob_data = get_orderbook_analysis(sym)
    
    # 3. Variabel Realtime
    curr = float(ticker['last'])
    vol = float(ticker['baseVolume'])
    high24 = float(ticker['high'])
    low24 = float(ticker['low'])
    atr = df['ATR'].iloc[-1]
    rsi_val = df['RSI'].iloc[-1]
    ema200 = df['EMA_200'].iloc[-1]
    
    # Tentukan Trend Text
    trend_txt = "BULLISH 🐂" if curr > ema200 else "BEARISH 🐻"
    trend_col = "#00e676" if curr > ema200 else "#ff1744"

    # --- LOGIKA NOTIFIKASI ---
    if 'last_alert_time' not in st.session_state:
        st.session_state['last_alert_time'] = None

    status_txt = "WAITING..."
    sig_col = "#777"
    entry_plan, tp_plan, sl_plan = "-", "-", "-"
    
    if history:
        last_sig = history[-1]
        if last_sig['Waktu'] == df['timestamp'].iloc[-1]:
            is_new = False
            if st.session_state['last_alert_time'] != last_sig['Waktu']:
                is_new = True
                st.session_state['last_alert_time'] = last_sig['Waktu']
            
            if 'BUY' in last_sig['Tipe']:
                status_txt = last_sig['Tipe']
                sig_col = "#00e676"
                msg_head = "🟢 *BUY SIGNAL!*"
            elif 'SELL' in last_sig['Tipe']:
                status_txt = last_sig['Tipe']
                sig_col = "#ff1744"
                msg_head = "🔴 *SELL SIGNAL!*"
                
            entry_plan = f"Rp {last_sig['Entry']:,.0f}"
            tp_plan = f"Rp {last_sig['TP']:,.0f}"
            sl_plan = f"Rp {last_sig['SL']:,.0f}"
            
            if is_new:
                msg = f"{msg_head}\nAsset: {sym}\nPrice: {entry_plan}\nWall Support: {ob_data['buy_wall_price']}"
                send_telegram(msg)
                st.toast("Sinyal Terkirim!", icon="🚀")

    def fmt(x): return f"{x:,.0f}".replace(",", ".")

    # --- LAYOUT ATAS ---
    st.markdown(f"""
    <style>
        .row-1 {{ display: grid; grid-template-columns: 1.5fr 1fr 1fr 1fr 1fr; gap: 8px; margin-bottom: 10px; }}
        .row-2 {{ display: grid; grid-template-columns: 1fr 1fr 1fr 1fr 1fr; gap: 8px; margin-bottom: 20px; }}
        .box {{ background: #1e1e1e; border: 1px solid #333; padding: 8px; border-radius: 6px; text-align: center; }}
        .sig-box {{ background: {sig_col}20; border: 2px solid {sig_col}; padding: 8px; border-radius: 6px; text-align: center; }}
        .lbl {{ font-size: 9px; color: #aaa; font-weight: bold; margin-bottom: 3px; text-transform: uppercase; }}
        .val {{ font-size: 14px; font-weight: bold; color: white; }}
        .val-lg {{ font-size: 18px; font-weight: 900; color: {sig_col}; }}
    </style>

    <div class="row-1">
        <div class="sig-box"><div class="lbl">STATUS</div><div class="val-lg">{status_txt}</div></div>
        <div class="box"><div class="lbl">HARGA</div><div class="val" style="color:#f1c40f">Rp {fmt(curr)}</div></div>
        <div class="box"><div class="lbl">LOW 24J</div><div class="val" style="color:#ff1744">{fmt(low24)}</div></div>
        <div class="box"><div class="lbl">HIGH 24J</div><div class="val" style="color:#00e676">{fmt(high24)}</div></div>
        <div class="box"><div class="lbl">VOLUME</div><div class="val">{fmt(vol)}</div></div>
    </div>

    <div class="row-2">
        <div class="box" style="border-top: 3px solid #29b6f6"><div class="lbl">ENTRY PLAN</div><div class="val" style="color:#29b6f6">{entry_plan}</div></div>
        <div class="box" style="border-top: 3px solid #00e676"><div class="lbl">TAKE PROFIT</div><div class="val" style="color:#00e676">{tp_plan}</div></div>
        <div class="box" style="border-top: 3px solid #ff1744"><div class="lbl">STOP LOSS</div><div class="val" style="color:#ff1744">{sl_plan}</div></div>
        <div class="box"><div class="lbl">RSI (MOMENTUM)</div><div class="val"><span style="color:{'#ff1744' if rsi_val > 70 else '#00e676' if rsi_val < 30 else 'white'}">{rsi_val:.0f}</span></div></div>
        <div class="box"><div class="lbl">TREND</div><div class="val" style="color:{trend_col}">{trend_txt}</div></div>
    </div>
    """, unsafe_allow_html=True)
    
    # --- CHART UTAMA DENGAN DYNAMIC ORDERBOOK LINES ---
    range_end = df['timestamp'].iloc[-1] + timedelta(minutes=15)
    range_start = df['timestamp'].iloc[-80]
    
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.75, 0.25])
    
    # 1. Candlestick
    fig.add_trace(go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Price'), row=1, col=1)
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['EMA_200'], line=dict(color='yellow', width=1), name='EMA 200'), row=1, col=1)
    
    # 2. Supply/Demand Zones (Rectangles)
    for z in zones:
        end_t = df['timestamp'].iloc[-1] + timedelta(hours=4)
        fig.add_shape(type="rect", x0=z['time'], y0=z['bot'], x1=end_t, y1=z['top'], 
                      fillcolor=z['color'], line_color=z['line'], line_width=1, row=1, col=1)

    # 3. DYNAMIC ORDERBOOK LINES (FITUR BARU)
    if ob_data:
        # Garis Support Dinamis (Buy Wall)
        fig.add_hline(y=ob_data['buy_wall_price'], line_dash="dash", line_color="#00e676", annotation_text=f"🛡️ BUY WALL: {fmt(ob_data['buy_wall_price'])}", annotation_position="bottom right", row=1, col=1)
        # Garis Resistance Dinamis (Sell Wall)
        fig.add_hline(y=ob_data['sell_wall_price'], line_dash="dash", line_color="#ff1744", annotation_text=f"🧱 SELL WALL: {fmt(ob_data['sell_wall_price'])}", annotation_position="top right", row=1, col=1)

    # 4. Sinyal Markers
    if df['sig_buy'].any():
        fig.add_trace(go.Scatter(x=df[df['sig_buy']]['timestamp'], y=df[df['sig_buy']]['low'], mode='markers', marker=dict(symbol='triangle-up', size=12, color='#00e676'), name='Buy'), row=1, col=1)
    if df['sig_sell'].any():
        fig.add_trace(go.Scatter(x=df[df['sig_sell']]['timestamp'], y=df[df['sig_sell']]['high'], mode='markers', marker=dict(symbol='triangle-down', size=12, color='#ff1744'), name='Sell'), row=1, col=1)

    # 5. MACD
    fig.add_trace(go.Bar(x=df['timestamp'], y=df['Hist'], marker_color=np.where(df['Hist']<0, '#ff1744', '#00e676'), name='Hist'), row=2, col=1)
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['MACD'], line=dict(color='#2962ff'), name='MACD'), row=2, col=1)
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['Signal'], line=dict(color='#ff9100'), name='Signal'), row=2, col=1)
    
    fig.update_layout(height=600, template="plotly_dark", margin=dict(l=0,r=50,t=0,b=0), xaxis_range=[range_start, range_end], xaxis2_range=[range_start, range_end], xaxis_rangeslider_visible=False)
    st.plotly_chart(fig, use_container_width=True)
    
    # --- BAGIAN BAWAH: TABEL ORDERBOOK & LOG ---
    c1, c2, c3 = st.columns([1, 1, 1.5])
    
    if ob_data:
        with c1:
            st.markdown("### 🛡️ Orderbook (Bids)")
            st.dataframe(ob_data['bids_df'].style.format({"price": "{:,.0f}", "volume": "{:,.2f}"}), use_container_width=True, hide_index=True)
            st.caption(f"Tembok Terkuat: **Rp {fmt(ob_data['buy_wall_price'])}** ({fmt(ob_data['buy_wall_vol'])})")
            
        with c2:
            st.markdown("### 🧱 Orderbook (Asks)")
            st.dataframe(ob_data['asks_df'].style.format({"price": "{:,.0f}", "volume": "{:,.2f}"}), use_container_width=True, hide_index=True)
            st.caption(f"Tembok Terkuat: **Rp {fmt(ob_data['sell_wall_price'])}** ({fmt(ob_data['sell_wall_vol'])})")

    with c3:
        st.markdown("### 📊 Riwayat Sinyal")
        if history:
            h_df = pd.DataFrame(history).iloc[::-1]
            h_df['Waktu'] = h_df['Waktu'].dt.strftime('%H:%M')
            st.dataframe(h_df[['Waktu', 'Tipe', 'Entry', 'Status']], use_container_width=True, hide_index=True)
        else:
            st.info("Belum ada sinyal terbentuk.")

# Jalankan Dashboard
dashboard(symbol, timeframe)
