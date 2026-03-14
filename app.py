import streamlit as st
import ccxt
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
import pytz

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(layout="wide", page_title="SMC & VSA Sniper")

# --- 2. ENGINE DATA & SINYAL ---
def get_market_data(symbol, timeframe):
    # Koneksi ke Indodax
    exchange = ccxt.indodax()
    ticker = exchange.fetch_ticker(symbol)
    
    # Ambil Data Candle (Limit 300 untuk EMA 200 yang akurat)
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=300)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    
    # Konversi Waktu ke WIB (Asia/Jakarta)
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize('UTC').dt.tz_convert('Asia/Jakarta')
    
    # --- INDIKATOR TEKNIKAL ---
    
    # 1. EMA 200 (Trend Filter)
    df['EMA_200'] = df['close'].ewm(span=200, adjust=False).mean()
    
    # 2. MACD (Momentum)
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['MACD_SIGNAL'] = df['MACD'].ewm(span=9, adjust=False).mean()
    
    # 3. Bollinger Bands (Reversal Detection)
    df['BB_MID'] = df['close'].rolling(window=20).mean()
    df['BB_STD'] = df['close'].rolling(window=20).std()
    df['BB_UPPER'] = df['BB_MID'] + (df['BB_STD'] * 2)
    df['BB_LOWER'] = df['BB_MID'] - (df['BB_STD'] * 2)
    
    # 4. VSA (Volume Spread Analysis) - Volume MA
    df['VOL_MA'] = df['volume'].rolling(window=20).mean()
    
    # 5. Market Structure (Swing High/Low untuk SL SMC)
    # Mencari titik terendah/tertinggi dari 5 candle terakhir
    df['SWING_LOW'] = df['low'].rolling(window=5).min()
    df['SWING_HIGH'] = df['high'].rolling(window=5).max()

    # --- PATTERN RECOGNITION (Price Action) ---
    # Bullish Engulfing: Candle Merah, lalu Hijau besar menutup body sebelumnya
    df['BULL_ENGULF'] = (
        (df['close'].shift(1) < df['open'].shift(1)) & # Kemarin Merah
        (df['close'] > df['open']) &                   # Sekarang Hijau
        (df['close'] > df['open'].shift(1)) &          # Tutup di atas buka kemarin
        (df['open'] < df['close'].shift(1))            # Buka di bawah tutup kemarin
    )

    # Bearish Engulfing
    df['BEAR_ENGULF'] = (
        (df['close'].shift(1) > df['open'].shift(1)) & # Kemarin Hijau
        (df['close'] < df['open']) &                   # Sekarang Merah
        (df['close'] < df['open'].shift(1)) &
        (df['open'] > df['close'].shift(1))
    )
    
    # --- LOGIKA SCORING SINYAL ---
    df['signal_type'] = "NEUTRAL"
    
    # LOGIKA 1: SMC TREND BUY (Follow Trend)
    # Syarat: Harga > EMA 200 + Bullish Engulfing + Volume > Rata-rata
    cond_smc_buy = (
        (df['close'] > df['EMA_200']) &
        (df['BULL_ENGULF'] == True) &
        (df['volume'] > df['VOL_MA']) &
        (df['MACD'] > df['MACD_SIGNAL'])
    )
    
    # LOGIKA 2: SMC TREND SELL (Downtrend)
    # Syarat: Harga < EMA 200 + Bearish Engulfing + Volume Konfirmasi
    cond_smc_sell = (
        (df['close'] < df['EMA_200']) &
        (df['BEAR_ENGULF'] == True) &
        (df['MACD'] < df['MACD_SIGNAL'])
    )
    
    # LOGIKA 3: BB REVERSAL (Extreme Reversal)
    # Syarat: Tembus BB Bawah + Bullish Engulfing (Buy Pucuk Bawah)
    cond_reversal_buy = (
        (df['low'] <= df['BB_LOWER']) &
        (df['BULL_ENGULF'] == True)
    )
    
    # Syarat: Tembus BB Atas + Bearish Engulfing (Sell Pucuk Atas)
    cond_reversal_sell = (
        (df['high'] >= df['BB_UPPER']) &
        (df['BEAR_ENGULF'] == True)
    )
    
    # Prioritas Penulisan Sinyal
    df.loc[cond_smc_buy, 'signal_type'] = "STRONG BUY (SMC)"
    df.loc[cond_smc_sell, 'signal_type'] = "STRONG SELL (SMC)"
    df.loc[cond_reversal_buy, 'signal_type'] = "REVERSAL BUY (BB)"
    df.loc[cond_reversal_sell, 'signal_type'] = "REVERSAL SELL (BB)"

    return df, ticker

# --- 3. SIDEBAR ---
st.sidebar.header("⚙️ Smart Money Settings")
symbol = st.sidebar.selectbox("Aset Kripto", ['BTC/IDR', 'ETH/IDR', 'DOGE/IDR', 'SOL/IDR', 'XRP/IDR', 'SHIB/IDR', 'PEPE/IDR'])
timeframe = st.sidebar.selectbox("Timeframe", ['15m', '1h', '4h', '1d'])
st.sidebar.markdown("---")
st.sidebar.info("""
**Logika SMC & VSA:**
1. **EMA 200**: Penentu Tren Besar.
2. **Price Action**: Engulfing Candle.
3. **SL**: Struktur Market (Swing Low/High).
4. **TP**: Risk Reward 1:2 (Likuiditas).
""")

# --- 4. MAIN DASHBOARD ---
st.title(f"SMC Trader: {symbol}")

@st.fragment(run_every=60)
def show_dashboard(sym, tf):
    try:
        df, ticker = get_market_data(sym, tf)
        
        # Data Terkini
        curr = float(ticker['last'])
        vol = float(ticker['baseVolume'])
        high_24 = float(ticker['high'])
        low_24 = float(ticker['low'])
        
        # Ambil Data Candle Terakhir & Sebelumnya (Untuk cek sinyal baru muncul)
        last = df.iloc[-1]
        prev = df.iloc[-2]
        
        # --- DETEKSI SINYAL DARI 3 CANDLE TERAKHIR ---
        # Kita cek 3 candle terakhir agar user tidak ketinggalan info jika candle baru saja close
        scan_window = df.tail(3)
        active_signal = "WAIT & SEE"
        
        # Loop priority (Last found signal wins)
        detected_sl = 0
        detected_tp = 0
        detected_entry = 0
        
        # Warna Default
        sig_bg = "#262730" 
        sig_col = "#aaa"
        
        for index, row in scan_window.iterrows():
            sig = row['signal_type']
            if sig != "NEUTRAL":
                active_signal = sig
                detected_entry = row['close'] # Entry di harga close candle sinyal
                
                if "BUY" in sig:
                    sig_bg = "rgba(0, 255, 0, 0.1)"
                    sig_col = "#00e676" # Hijau
                    # SL di Swing Low Terakhir (Struktur)
                    detected_sl = row['SWING_LOW'] 
                    # Hitung Risk
                    risk = detected_entry - detected_sl
                    # TP = Entry + (Risk * 2) -> RR 1:2
                    detected_tp = detected_entry + (risk * 2)
                    
                elif "SELL" in sig:
                    sig_bg = "rgba(255, 0, 0, 0.1)"
                    sig_col = "#ff1744" # Merah
                    # SL di Swing High Terakhir (Struktur)
                    detected_sl = row['SWING_HIGH']
                    risk = detected_sl - detected_entry
                    detected_tp = detected_entry - (risk * 2)

        # Jika tidak ada sinyal valid di window, set ke harga sekarang untuk simulasi
        if detected_entry == 0:
             # Default visual jika waiting
             f_tp = "-"
             f_sl = "-"
             f_entry = "-"
        else:
             f_tp = f"Rp {detected_tp:,.0f}".replace(",", ".")
             f_sl = f"Rp {detected_sl:,.0f}".replace(",", ".")
             f_entry = f"Rp {detected_entry:,.0f}".replace(",", ".")

        # --- VALIDATION CHECKBOX (CONFLUENCE) ---
        is_uptrend = last['close'] > last['EMA_200']
        is_mom_up = last['MACD'] > last['MACD_SIGNAL']
        is_vol_up = last['volume'] > last['VOL_MA']
        
        trend_stat = "UPTREND" if is_uptrend else "DOWNTREND"
        trend_color = "#00e676" if is_uptrend else "#ff1744"
        
        mom_stat = "BULLISH" if is_mom_up else "BEARISH"
        mom_color = "#00e676" if is_mom_up else "#ff1744"
        
        vol_stat = "HIGH" if is_vol_up else "LOW"
        vol_color = "#00e676" if is_vol_up else "#777"

        # --- FORMAT ANGKA INDONESIA ---
        def fmt(x): return f"{x:,.0f}".replace(",", ".")
        f_curr = fmt(curr)
        f_high = fmt(high_24)
        f_low = fmt(low_24)
        f_vol = f"{vol:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

        # --- CSS STYLE (DIPISAH TOTAL) ---
        st.markdown("""
        <style>
            .grid-market { display: grid; grid-template-columns: 1.5fr 1fr 1fr 1fr 1fr; gap: 8px; margin-bottom: 10px; }
            .grid-plan { display: grid; grid-template-columns: 1fr 1fr 1fr 1.5fr; gap: 8px; margin-bottom: 20px; }
            
            .card { background: #1e1e1e; padding: 12px; border-radius: 8px; text-align: center; border: 1px solid #333; display: flex; flex-direction: column; justify-content: center; }
            .card-sig { padding: 12px; border-radius: 8px; text-align: center; display: flex; flex-direction: column; justify-content: center; }
            
            .lbl { font-size: 10px; color: #bbb; margin-bottom: 4px; font-weight: bold; text-transform: uppercase; letter-spacing: 0.5px; }
            .val { font-size: 15px; font-weight: bold; color: white; }
            .val-lg { font-size: 18px; font-weight: 900; }
            
            .check-row { display: flex; justify-content: space-between; align-items: center; font-size: 10px; margin-bottom: 2px; border-bottom: 1px solid #333; padding-bottom: 2px; }
            .dot { height: 8px; width: 8px; border-radius: 50%; display: inline-block; }
        </style>
        """, unsafe_allow_html=True)

        # --- HTML LAYOUT ---
        html_content = f"""
        <!-- BARIS 1: MARKET INFO -->
        <div class="grid-market">
            <div class="card-sig" style="background: {sig_bg}; border: 2px solid {sig_col};">
                <div class="lbl">SINYAL AKTIF</div>
                <div class="val-lg" style="color: {sig_col};">{active_signal}</div>
            </div>
            <div class="card">
                <div class="lbl">HARGA SAAT INI</div>
                <div class="val" style="color: #f1c40f;">Rp {f_curr}</div>
            </div>
            <div class="card">
                <div class="lbl">VOL (24J)</div>
                <div class="val">{f_vol}</div>
            </div>
             <div class="card">
                <div class="lbl">LOW 24J</div>
                <div class="val" style="color: #ff5252;">{f_low}</div>
            </div>
             <div class="card">
                <div class="lbl">HIGH 24J</div>
                <div class="val" style="color: #00e676;">{f_high}</div>
            </div>
        </div>

        <!-- BARIS 2: PLAN & VALIDATION -->
        <div class="grid-plan">
             <div class="card" style="border-top: 3px solid #f1c40f;">
                <div class="lbl">ENTRY PLAN</div>
                <div class="val" style="color: #f1c40f;">{f_entry}</div>
            </div>
             <div class="card" style="border-top: 3px solid #00e676;">
                <div class="lbl">TAKE PROFIT (RR 1:2)</div>
                <div class="val" style="color: #00e676;">{f_tp}</div>
            </div>
             <div class="card" style="border-top: 3px solid #ff5252;">
                <div class="lbl">STOP LOSS (SMC)</div>
                <div class="val" style="color: #ff5252;">{f_sl}</div>
            </div>
             <div class="card" style="align-items: stretch; padding: 8px 15px;">
                <div class="lbl" style="text-align:center; margin-bottom:5px;">VALIDATION (CONFLUENCE)</div>
                <div class="check-row">
                    <span style="color:#ccc">EMA 200 TREND</span>
                    <span style="color:{trend_color}; font-weight:bold;">{trend_stat}</span>
                </div>
                <div class="check-row">
                    <span style="color:#ccc">MOMENTUM (MACD)</span>
                    <span style="color:{mom_color}; font-weight:bold;">{mom_stat}</span>
                </div>
                <div class="check-row" style="border:none;">
                    <span style="color:#ccc">VOLUME (VSA)</span>
                    <span style="color:{vol_color}; font-weight:bold;">{vol_stat}</span>
                </div>
            </div>
        </div>
        """
        st.markdown(html_content, unsafe_allow_html=True)

        # --- CHARTING ---
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.75, 0.25])

        # 1. Candlestick
        fig.add_trace(go.Candlestick(
            x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close'],
            name='Harga'
        ), row=1, col=1)

        # 2. EMA 200 (Garis Putih Putus-putus)
        fig.add_trace(go.Scatter(
            x=df['timestamp'], y=df['EMA_200'], 
            line=dict(color='white', width=1, dash='dash'), name='EMA 200 (Trend)'
        ), row=1, col=1)

        # 3. Bollinger Bands (Area Abu Tipis)
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['BB_UPPER'], line=dict(color='rgba(255,255,255,0.2)', width=1), showlegend=False), row=1, col=1)
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['BB_LOWER'], line=dict(color='rgba(255,255,255,0.2)', width=1), showlegend=False), row=1, col=1)

        # 4. Highlight Sinyal Buy/Sell di Chart
        buys = df[df['signal_type'].str.contains("BUY")]
        sells = df[df['signal_type'].str.contains("SELL")]
        
        fig.add_trace(go.Scatter(
            x=buys['timestamp'], y=buys['low'], mode='markers', 
            marker=dict(symbol='triangle-up', size=10, color='#00e676'), name='Signal Buy'
        ), row=1, col=1)
        
        fig.add_trace(go.Scatter(
            x=sells['timestamp'], y=sells['high'], mode='markers', 
            marker=dict(symbol='triangle-down', size=10, color='#ff1744'), name='Signal Sell'
        ), row=1, col=1)

        # 5. MACD di Bawah
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['MACD'], line=dict(color='#00e676', width=1), name='MACD'), row=2, col=1)
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df['MACD_SIGNAL'], line=dict(color='#ff5252', width=1), name='Signal'), row=2, col=1)
        fig.add_trace(go.Bar(x=df['timestamp'], y=df['MACD']-df['MACD_SIGNAL'], marker_color='rgba(255,255,255,0.1)', name='Hist'), row=2, col=1)

        # Layout Chart
        fig.update_layout(
            height=600, 
            template="plotly_dark", 
            margin=dict(l=0,r=0,t=30,b=0), 
            xaxis_rangeslider_visible=False,
            title=dict(text=f"Analisa Waktu Lokal (WIB)", font=dict(size=12, color="#666"))
        )
        
        st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.error(f"Sedang mengambil data pasar... ({e})")

show_dashboard(symbol, timeframe)
