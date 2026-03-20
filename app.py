import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import requests

# ==========================================
# --- 1. KONFIGURASI & SETUP ---
# ==========================================
st.set_page_config(layout="wide", page_title="Indodax Scalper V8.3 (Supertrend)")

# --- TELEGRAM SETTINGS ---
def send_telegram(message):
    # GANTI DENGAN TOKEN & CHAT ID ANDA
    BOT_TOKEN = "TOKEN_BOT_ANDA_DISINI" 
    CHAT_ID = "CHAT_ID_ANDA_DISINI"
    
    if "TOKEN_BOT" in BOT_TOKEN: return 
        
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    params = {'chat_id': CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    try:
        requests.get(url, params=params, timeout=3)
    except Exception as e:
        print(f"Telegram Error: {e}")

# ==========================================
# --- 2. DATA ENGINE (OHLCV & ORDERBOOK) ---
# ==========================================
def get_data(symbol, tf):
    exchange = ccxt.indodax()
    try:
        ohlcv = exchange.fetch_ohlcv(symbol, tf, limit=500)
        if not ohlcv: return pd.DataFrame(), None
        
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        # Konversi ke WIB
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize('UTC').dt.tz_convert('Asia/Jakarta')
        
        ticker = exchange.fetch_ticker(symbol)
        return df, ticker
    except Exception as e:
        st.error(f"Koneksi Indodax Error: {e}")
        return pd.DataFrame(), None

def get_orderbook_analysis(symbol):
    try:
        exchange = ccxt.indodax()
        # UPDATE: Ambil 50 antrian teratas (Deep Scan)
        ob = exchange.fetch_order_book(symbol, limit=50)
        
        # Analisa Bids (Beli)
        bids = pd.DataFrame(ob['bids'], columns=['price', 'volume'])
        # Cari harga dengan Volume tertinggi sebagai 'Wall'
        max_bid_idx = bids['volume'].idxmax()
        wall_buy_price = bids.iloc[max_bid_idx]['price']
        wall_buy_vol = bids.iloc[max_bid_idx]['volume']
        
        # Analisa Asks (Jual)
        asks = pd.DataFrame(ob['asks'], columns=['price', 'volume'])
        max_ask_idx = asks['volume'].idxmax()
        wall_sell_price = asks.iloc[max_ask_idx]['price']
        wall_sell_vol = asks.iloc[max_ask_idx]['volume']
        
        return {
            'buy_wall_price': wall_buy_price,
            'buy_wall_vol': wall_buy_vol,
            'sell_wall_price': wall_sell_price,
            'sell_wall_vol': wall_sell_vol,
            'bids_df': bids.head(10), # Tampilkan 10 teratas di tabel
            'asks_df': asks.head(10)
        }
    except Exception as e:
        return None

# ==========================================
# --- 3. INDIKATOR (PLUS SUPERTREND) ---
# ==========================================
def process_indicators(df):
    if df.empty: return df
    
    # 1. Basic Indicators
    df['EMA_200'] = df['close'].ewm(span=200, adjust=False).mean()
    
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['Hist'] = df['MACD'] - df['Signal']
    
    # ATR
    df['tr'] = np.maximum(df['high'] - df['low'], 
               np.maximum(abs(df['high'] - df['close'].shift()), abs(df['low'] - df['close'].shift())))
    df['ATR'] = df['tr'].ewm(span=14).mean()
    
    # Volume Analysis
    df['Vol_MA'] = df['volume'].rolling(20).mean()
    df['Vol_Spike'] = df['volume'] > (df['Vol_MA'] * 1.5) # Harus 1.5x rata-rata
    
    # Candle Patterns
    df['Bull_Engulf'] = (df['close'] > df['open']) & (df['close'] > df['open'].shift(1)) & \
                        (df['open'] < df['close'].shift(1))
    df['Bear_Engulf'] = (df['close'] < df['open']) & (df['close'] < df['open'].shift(1)) & \
                        (df['open'] > df['close'].shift(1))
                        
    # RSI
    period = 14
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # --- BARU: SUPERTREND CALCULATION ---
    st_period = 10
    st_mul = 3
    
    hl2 = (df['high'] + df['low']) / 2
    df['st_upper'] = hl2 + (st_mul * df['ATR'])
    df['st_lower'] = hl2 - (st_mul * df['ATR'])
    df['supertrend'] = np.nan
    df['st_dir'] = 1 # 1=Bull, -1=Bear
    
    # Iterasi Manual untuk Supertrend (Wajib urut waktu)
    # Kita mulai dari index 1 karena butuh data sebelumnya
    for i in range(1, len(df)):
        curr_close = df['close'].iloc[i]
        prev_close = df['close'].iloc[i-1]
        
        curr_upper = df['st_upper'].iloc[i]
        prev_upper = df['st_upper'].iloc[i-1]
        
        curr_lower = df['st_lower'].iloc[i]
        prev_lower = df['st_lower'].iloc[i-1]
        
        prev_dir = df['st_dir'].iloc[i-1]
        
        # Logic Upper (Hanya boleh turun)
        if curr_upper < prev_upper or prev_close > prev_upper:
            df.at[df.index[i], 'st_upper'] = curr_upper
        else:
            df.at[df.index[i], 'st_upper'] = prev_upper
            
        # Logic Lower (Hanya boleh naik)
        if curr_lower > prev_lower or prev_close < prev_lower:
            df.at[df.index[i], 'st_lower'] = curr_lower
        else:
            df.at[df.index[i], 'st_lower'] = prev_lower
            
        # Logic Direction Check
        if prev_dir == 1:
            if curr_close < df.at[df.index[i], 'st_lower']:
                df.at[df.index[i], 'st_dir'] = -1
                df.at[df.index[i], 'supertrend'] = df.at[df.index[i], 'st_upper']
            else:
                df.at[df.index[i], 'st_dir'] = 1
                df.at[df.index[i], 'supertrend'] = df.at[df.index[i], 'st_lower']
        elif prev_dir == -1:
            if curr_close > df.at[df.index[i], 'st_upper']:
                df.at[df.index[i], 'st_dir'] = 1
                df.at[df.index[i], 'supertrend'] = df.at[df.index[i], 'st_lower']
            else:
                df.at[df.index[i], 'st_dir'] = -1
                df.at[df.index[i], 'supertrend'] = df.at[df.index[i], 'st_upper']

    return df

# ==========================================
# --- 4. DETEKSI SUPPLY & DEMAND ---
# ==========================================
def detect_zones(df):
    zones = []
    vol_ma = df['volume'].rolling(20).mean()
    body = (df['close'] - df['open']).abs()
    avg_body = body.rolling(20).mean()
    
    start = max(0, len(df) - 200) 
    for i in range(start, len(df)-2):
        curr = df.iloc[i]
        prev = df.iloc[i-1]
        is_impulse = (curr['volume'] > vol_ma.iloc[i]) and (body.iloc[i] > avg_body.iloc[i])
        
        if is_impulse and curr['close'] > curr['open'] and prev['close'] < prev['open']:
            zones.append({'type': 'DEMAND', 'top': prev['high'], 'bot': prev['low'], 'time': prev['timestamp'],
                          'color': 'rgba(41, 182, 246, 0.2)', 'line': 'rgba(41, 182, 246, 0.8)'})
        elif is_impulse and curr['close'] < curr['open'] and prev['close'] > prev['open']:
            zones.append({'type': 'SUPPLY', 'top': prev['high'], 'bot': prev['low'], 'time': prev['timestamp'],
                          'color': 'rgba(255, 167, 38, 0.2)', 'line': 'rgba(255, 167, 38, 0.8)'})
            
    active = []
    for z in zones:
        future = df[df['timestamp'] > z['time']]
        if future.empty:
            active.append(z)
        elif z['type'] == 'DEMAND':
            # Validasi Ekor (Wick)
            if not (future['low'] < z['bot']).any(): 
                active.append(z)
        else:
            if not (future['high'] > z['top']).any(): 
                active.append(z)
    return active

# ==========================================
# --- 5. LOGIKA SINYAL (FEE GUARD) ---
# ==========================================
def generate_signals(df, zones):
    history = []
    df['sig_buy'] = False
    df['sig_sell'] = False
    start = max(1, len(df) - 100)
    
    for i in range(start, len(df)):
        row = df.iloc[i]
        prev_row = df.iloc[i-1]
        
        safe_buy = row['RSI'] < 70  
        safe_sell = row['RSI'] > 30
        
        # FEE GUARD: Min Profit Bersih harus > 0.2% (Total Spread > 0.8%)
        min_spread = 0.008  
        
        # Pola Candle & MACD
        is_hammer = (row['close'] > row['open']) and ((row['open'] - row['low']) > 2 * (row['close'] - row['open']))
        trigger_buy = row['Bull_Engulf'] or row['Vol_Spike'] or is_hammer
        
        macd_cross_buy = (prev_row['MACD'] < prev_row['Signal']) and (row['MACD'] > row['Signal'])
        macd_cross_sell = (prev_row['MACD'] > prev_row['Signal']) and (row['MACD'] < row['Signal'])

        zone_signal_taken = False
        entry = row['close']

        # --- STRATEGI 1: ZONA ---
        if row['MACD'] > row['Signal'] and trigger_buy and safe_buy:
            for z in zones:
                if z['type'] == 'DEMAND' and z['time'] < row['timestamp']:
                    if row['low'] <= z['top']*1.015 and row['high'] >= z['bot']:
                        sl = z['bot'] - row['ATR']
                        tp = z['top'] + ((z['top'] - sl) * 1.5)
                        
                        if (tp - entry) / entry > min_spread:
                            df.loc[df.index[i], 'sig_buy'] = True
                            history.append({'Waktu': row['timestamp'], 'Tipe': 'BUY (Zone)', 'Entry': entry, 'SL': sl, 'TP': tp, 'Status': 'Active'})
                            zone_signal_taken = True
                        break

        # --- STRATEGI 2: MOMENTUM ---
        if not zone_signal_taken and macd_cross_buy and safe_buy:
            sl = row['low'] - (row['ATR'] * 1.5)
            tp = entry + ((entry - sl) * 1.5)
            
            if (tp - entry) / entry > min_spread:
                df.loc[df.index[i], 'sig_buy'] = True
                history.append({'Waktu': row['timestamp'], 'Tipe': 'BUY (Momtm)', 'Entry': entry, 'SL': sl, 'TP': tp, 'Status': 'Active'})

        # Logic SELL (Mirroring Buy logic here for brevity if needed, but focused on Buy for Spot)
        # (Kode Sell sama seperti sebelumnya, disederhanakan untuk fokus Spot Market Indodax)
        if macd_cross_sell and safe_sell:
             sl = row['high'] + (row['ATR'] * 1.5)
             tp = entry - ((sl - entry) * 1.5)
             if (entry - tp) / entry > min_spread:
                 df.loc[df.index[i], 'sig_sell'] = True
                 history.append({'Waktu': row['timestamp'], 'Tipe': 'SELL', 'Entry': entry, 'SL': sl, 'TP': tp, 'Status': 'Active'})

    return df, history

# ==========================================
# --- 6. DASHBOARD UTAMA ---
# ==========================================
st.sidebar.header("🎛️ Scalper V8.3")
symbol = st.sidebar.selectbox("Pair", ['BTC/IDR', 'ETH/IDR', 'SOL/IDR', 'DOGE/IDR', 'XRP/IDR', 'SHIB/IDR', 'USDT/IDR'])
timeframe = st.sidebar.selectbox("Timeframe", ['1m', '15m', '30m', '1h', '4h'])
st.title(f"Scalper Pro: {symbol} ({timeframe})")

@st.fragment(run_every=60)
def dashboard(sym, tf):
    df, ticker = get_data(sym, tf)
    if df.empty: return
    
    df = process_indicators(df)
    zones = detect_zones(df)
    df, history = generate_signals(df, zones)
    
    # --- LOAD ORDERBOOK ANALYSIS ---
    ob_data = get_orderbook_analysis(sym)
    
    # Realtime Vars
    curr = float(ticker['last'])
    vol = float(ticker['baseVolume'])
    rsi_val = df['RSI'].iloc[-1]
    
    # Tentukan Trend berdasarkan Supertrend Terakhir
    st_dir = df['st_dir'].iloc[-1]
    trend_txt = "BULLISH 🟢" if st_dir == 1 else "BEARISH 🔴"
    trend_col = "#00e676" if st_dir == 1 else "#ff1744"

    # --- NOTIFIKASI ---
    if 'last_alert_time' not in st.session_state:
        st.session_state['last_alert_time'] = None
    
    status_txt = "WAITING..."
    sig_col = "#777"
    entry_plan = "-"
    
    if history:
        last_sig = history[-1]
        if last_sig['Waktu'] == df['timestamp'].iloc[-1]:
            if st.session_state['last_alert_time'] != last_sig['Waktu']:
                st.session_state['last_alert_time'] = last_sig['Waktu']
                msg = f"⚠️ SIGNALE BARU: {sym}\nType: {last_sig['Tipe']}\nPrice: {last_sig['Entry']}"
                send_telegram(msg)
                st.toast("Signal Sent!", icon="🚀")
                
            if 'BUY' in last_sig['Tipe']:
                status_txt = last_sig['Tipe']
                sig_col = "#00e676"
            elif 'SELL' in last_sig['Tipe']:
                status_txt = last_sig['Tipe']
                sig_col = "#ff1744"
            entry_plan = f"{last_sig['Entry']:,.0f}"

    def fmt(x): return f"{x:,.0f}".replace(",", ".")

    # --- HTML LAYOUT ---
    st.markdown(f"""
    <style>
        .row-1 {{ display: grid; grid-template-columns: 1.5fr 1fr 1fr 1fr 1fr; gap: 8px; margin-bottom: 10px; }}
        .row-2 {{ display: grid; grid-template-columns: 1fr 1fr 1fr 1fr 1.2fr; gap: 8px; margin-bottom: 20px; }}
        .box {{ background: #1e1e1e; border: 1px solid #333; padding: 8px; border-radius: 6px; text-align: center; }}
        .sig-box {{ background: {sig_col}20; border: 2px solid {sig_col}; padding: 8px; border-radius: 6px; text-align: center; }}
        .lbl {{ font-size: 9px; color: #aaa; font-weight: bold; margin-bottom: 3px; }}
        .val {{ font-size: 14px; font-weight: bold; color: white; }}
        .val-lg {{ font-size: 18px; font-weight: 900; color: {sig_col}; }}
    </style>

    <div class="row-1">
        <div class="sig-box"><div class="lbl">SIGNAL STATUS</div><div class="val-lg">{status_txt}</div></div>
        <div class="box"><div class="lbl">PRICE</div><div class="val" style="color:#f1c40f">Rp {fmt(curr)}</div></div>
        <div class="box"><div class="lbl">24H LOW</div><div class="val" style="color:#ff1744">{fmt(ticker['low'])}</div></div>
        <div class="box"><div class="lbl">24H HIGH</div><div class="val" style="color:#00e676">{fmt(ticker['high'])}</div></div>
        <div class="box"><div class="lbl">VOL (IDR)</div><div class="val">{fmt(vol)}</div></div>
    </div>
    <div class="row-2">
        <div class="box"><div class="lbl">ENTRY PLAN</div><div class="val" style="color:#29b6f6">{entry_plan}</div></div>
        <div class="box"><div class="lbl">RSI (14)</div><div class="val">{rsi_val:.0f}</div></div>
        <div class="box"><div class="lbl">TREND (ST)</div><div class="val" style="color:{trend_col}">{trend_txt}</div></div>
        <!-- WALL INDICATORS -->
        <div class="box"><div class="lbl">BUY WALL</div><div class="val" style="color:#00e676">{fmt(ob_data['buy_wall_price']) if ob_data else '-'}</div></div>
        <div class="box"><div class="lbl">SELL WALL</div><div class="val" style="color:#ff1744">{fmt(ob_data['sell_wall_price']) if ob_data else '-'}</div></div>
    </div>
    """, unsafe_allow_html=True)

    # --- PLOT CHART ---
    range_start = df['timestamp'].iloc[-100] # Zoom 100 candle terakhir
    
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.75, 0.25])
    
    # 1. Candlestick
    fig.add_trace(go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Price'), row=1, col=1)
    
    # 2. SUPERTREND LINES (Fix: Filtering Data)
    # Pisahkan data Bull (Hijau) dan Bear (Merah) agar garis tidak nyambung sembarangan
    st_bull = df.copy()
    st_bull.loc[st_bull['st_dir'] == -1, 'supertrend'] = np.nan
    
    st_bear = df.copy()
    st_bear.loc[st_bear['st_dir'] == 1, 'supertrend'] = np.nan
    
    fig.add_trace(go.Scatter(x=st_bull['timestamp'], y=st_bull['supertrend'], line=dict(color='#00e676', width=2), name='ST Bull'), row=1, col=1)
    fig.add_trace(go.Scatter(x=st_bear['timestamp'], y=st_bear['supertrend'], line=dict(color='#ff1744', width=2), name='ST Bear'), row=1, col=1)
    
    # 3. Zones & Walls
    for z in zones:
        end_t = df['timestamp'].iloc[-1] + timedelta(hours=4)
        fig.add_shape(type="rect", x0=z['time'], y0=z['bot'], x1=end_t, y1=z['top'], 
                      fillcolor=z['color'], line_color=z['line'], line_width=1, row=1, col=1)

    if ob_data:
        fig.add_hline(y=ob_data['buy_wall_price'], line_dash="dash", line_color="#00e676", annotation_text="BUY WALL", row=1, col=1)
        fig.add_hline(y=ob_data['sell_wall_price'], line_dash="dash", line_color="#ff1744", annotation_text="SELL WALL", row=1, col=1)
    
    # 4. Signal Markers
    if df['sig_buy'].any():
        fig.add_trace(go.Scatter(x=df[df['sig_buy']]['timestamp'], y=df[df['sig_buy']]['low'], mode='markers', marker=dict(symbol='triangle-up', size=12, color='#00e676'), name='Buy'), row=1, col=1)
    
    # 5. MACD
    fig.add_trace(go.Bar(x=df['timestamp'], y=df['Hist'], marker_color=np.where(df['Hist']<0, '#ff1744', '#00e676')), row=2, col=1)
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['MACD'], line=dict(color='#2962ff'), name='MACD'), row=2, col=1)
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['Signal'], line=dict(color='#ff9100'), name='Signal'), row=2, col=1)
    
    fig.update_layout(height=650, template="plotly_dark", margin=dict(l=0,r=50,t=0,b=0), xaxis_range=[range_start, df['timestamp'].iloc[-1]+timedelta(minutes=30)], xaxis_rangeslider_visible=False)
    st.plotly_chart(fig, use_container_width=True)
    
    # --- BAGIAN TENGAH: TABEL ZONA & HISTORI ---
    st.markdown("### 📋 Analisa Teknikal")
    c1, c2 = st.columns(2)
    
    with c1:
        st.caption("Zona Supply & Demand (Support/Resist)")
        if zones:
            z_list = []
            for z in reversed(zones[-5:]):
                z_list.append([
                    "🟦 DEMAND" if z['type']=='DEMAND' else "🟧 SUPPLY",
                    f"{fmt(z['bot'])} - {fmt(z['top'])}",
                    z['time'].strftime('%d/%m %H:%M')
                ])
            st.table(pd.DataFrame(z_list, columns=["Tipe", "Area", "Waktu"]))
        else:
            st.info("Tidak ada zona valid dekat harga sekarang.")
            
    with c2:
        st.caption("Riwayat Sinyal (Terakhir)")
        if history:
            h_df = pd.DataFrame(history).iloc[::-1]
            h_df['Entry'] = h_df['Entry'].apply(lambda x: fmt(x))
            h_df['Waktu'] = h_df['Waktu'].dt.strftime('%H:%M')
            st.dataframe(h_df[['Waktu', 'Tipe', 'Entry', 'Status']], use_container_width=True, hide_index=True, height=200)
        else:
            st.info("Menunggu sinyal...")

    # --- BAGIAN BAWAH: ORDERBOOK DEPTH ---
    st.divider()
    st.markdown("### 🧱 Market Depth (50 Top Queues)")
    if ob_data:
        bc1, bc2 = st.columns(2)
        with bc1:
            st.success(f"🛡️ **Bids (Antrian Beli)** | Wall: **{fmt(ob_data['buy_wall_price'])}**")
            st.dataframe(ob_data['bids_df'].style.format({"price": "{:,.0f}", "volume": "{:,.2f}"}), use_container_width=True, hide_index=True)
        with bc2:
            st.error(f"🧱 **Asks (Antrian Jual)** | Wall: **{fmt(ob_data['sell_wall_price'])}**")
            st.dataframe(ob_data['asks_df'].style.format({"price": "{:,.0f}", "volume": "{:,.2f}"}), use_container_width=True, hide_index=True)

# Execute
dashboard(symbol, timeframe)
