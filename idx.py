import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from plotly.subplots import make_subplots
import numpy as np

# ==========================================
# 1. KONFIGURASI HALAMAN & SIDEBAR (UPDATED)
# ==========================================
st.set_page_config(page_title="Expert Quant Dashboard", layout="wide")
st.title("📈 Pro Trader Dashboard: Multi-Asset")

st.sidebar.header("1. Konfigurasi Aset")

# --- FITUR BARU: PILIHAN MARKET ---
market_type = st.sidebar.radio("Pilih Jenis Market:", ["Crypto (Global/Indodax)", "Saham (IDX / Stockbit)"])

if market_type == "Saham (IDX / Stockbit)":
    default_ticker = "BBCA.JK"
    st.sidebar.info("Tips: Gunakan akhiran **.JK** untuk saham Indonesia (contoh: TLKM.JK, GOTO.JK).")
else:
    default_ticker = "BTC-USD"
    st.sidebar.info("Tips: Gunakan pair **-USD** untuk data chart yang lebih stabil (contoh: ETH-USD, SOL-USD).")

ticker = st.sidebar.text_input("Ketik Simbol Aset:", value=default_ticker)

st.sidebar.header("2. Parameter Analisa")
timeframe = st.sidebar.selectbox("Timeframe:", ["1d", "1h", "15m", "5m"], index=0)
period_input = st.sidebar.selectbox("Periode Data (Backtest):", ["3mo", "6mo", "1y", "2y"], index=1)

# ==========================================
# 2. LOGIKA INDIKATOR (MFI & BBW)
# ==========================================
def add_indicators(df):
    # A. Money Flow Index (MFI)
    # Menggabungkan Harga & Volume untuk mendeteksi 'Smart Money'
    typical_price = (df['High'] + df['Low'] + df['Close']) / 3
    money_flow = typical_price * df['Volume']
    
    pos_flow = []
    neg_flow = []
    
    # Loop untuk memisahkan arus uang masuk (Positif) vs keluar (Negatif)
    for i in range(1, len(typical_price)):
        if typical_price.iloc[i] > typical_price.iloc[i-1]:
            pos_flow.append(money_flow.iloc[i])
            neg_flow.append(0)
        else:
            pos_flow.append(0)
            neg_flow.append(money_flow.iloc[i])
    
    # Padding angka 0 di awal karena loop mulai dari index 1
    pos_flow.insert(0, 0)
    neg_flow.insert(0, 0)
            
    pos_res = pd.Series(pos_flow).rolling(window=14).sum()
    neg_res = pd.Series(neg_flow).rolling(window=14).sum()
    
    # Mencegah pembagian dengan nol
    mfr = pos_res / neg_res.replace(0, 1)
    df['MFI'] = 100 - (100 / (1 + mfr)).values
    
    # B. Bollinger Band Width (BBW) - Volatility Squeeze
    ma20 = df['Close'].rolling(window=20).mean()
    std20 = df['Close'].rolling(window=20).std()
    
    upper = ma20 + (std20 * 2)
    lower = ma20 - (std20 * 2)
    
    # BBW mengukur persentase lebar band relatif terhadap harga rata-rata
    df['BBW'] = ((upper - lower) / ma20) * 100
    
    return df

# ==========================================
# 3. LOGIKA BACKTESTING (STRATEGY ENGINE)
# ==========================================
def run_backtest(df):
    initial_capital = 100_000_000 # Modal Simulasi Rp 100jt
    balance = initial_capital
    position = 0 # Jumlah lembar/koin yang dipegang
    trades = []
    
    for i in range(len(df)):
        # Skip jika data indikator belum tersedia (NaN)
        if pd.isna(df['MFI'].iloc[i]):
            continue
            
        price = df['Close'].iloc[i]
        mfi = df['MFI'].iloc[i]
        date = df.index[i]
        
        # LOGIKA BUY: MFI < 20 (Oversold/Murah) -> Sinyal Beli
        if position == 0 and mfi < 20:
            position = balance / price
            balance = 0
            trades.append({
                'Tanggal': date, 
                'Aksi': '🟢 BUY', 
                'Harga': price, 
                'MFI': f"{mfi:.1f}"
            })
            
        # LOGIKA SELL: MFI > 80 (Overbought/Mahal) -> Sinyal Jual
        elif position > 0 and mfi > 80:
            # Hitung profit trade ini
            buy_price = trades[-1]['Harga']
            pnl = (price - buy_price) / buy_price * 100
            
            balance = position * price
            position = 0
            trades.append({
                'Tanggal': date, 
                'Aksi': '🔴 SELL', 
                'Harga': price, 
                'MFI': f"{mfi:.1f} (PnL: {pnl:.1f}%)"
            })

    # Hitung nilai akhir portofolio
    final_val = balance if position == 0 else position * df['Close'].iloc[-1]
    total_profit_pct = ((final_val - initial_capital) / initial_capital) * 100
    
    return final_val, total_profit_pct, trades

# ==========================================
# 4. EKSEKUSI UTAMA (MAIN APP)
# ==========================================
try:
    # --- FETCH DATA ---
    data = yf.download(ticker, period=period_input, interval=timeframe)
    
    # --- FIX: MENANGANI MULTI-INDEX YFINANCE TERBARU ---
    # Masalah: yfinance baru mengembalikan kolom ('Close', 'BBCA.JK') bukan 'Close'
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    
    # Hapus baris kosong
    data = data.dropna()

    if not data.empty and len(data) > 20:
        # --- HITUNG INDIKATOR ---
        df = add_indicators(data)
        
        # --- VISUALISASI (PLOTLY) ---
        # Kita bagi layar jadi 3 baris: Harga, MFI, dan Volatilitas
        fig = make_subplots(
            rows=3, cols=1, 
            shared_xaxes=True, 
            vertical_spacing=0.05, 
            row_heights=[0.6, 0.2, 0.2],
            subplot_titles=(f"Price Chart: {ticker}", "Money Flow (Smart Money)", "Volatility Squeeze")
        )

        # 1. Candlestick Chart
        fig.add_trace(go.Candlestick(
            x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'], name="Price"
        ), row=1, col=1)

        # 2. MFI Chart
        fig.add_trace(go.Scatter(x=df.index, y=df['MFI'], name="MFI", line=dict(color='#FFD700')), row=2, col=1)
        fig.add_hline(y=80, line_dash="dot", line_color="red", row=2, col=1)
        fig.add_hline(y=20, line_dash="dot", line_color="#00FF00", row=2, col=1)

        # 3. BBW Chart
        fig.add_trace(go.Scatter(x=df.index, y=df['BBW'], name="BB Width", fill='tozeroy', line=dict(color='#00FFFF')), row=3, col=1)

        fig.update_layout(height=900, template="plotly_dark", xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, use_container_width=True)
        
        # --- BAGIAN BACKTEST & KESIMPULAN ---
        st.divider()
        c1, c2 = st.columns([2, 1])
        
        with c1:
            st.header("🤖 Strategy Backtest Result")
            final_val, profit, trade_log = run_backtest(df)
            
            # Tampilan Scorecard
            m1, m2, m3 = st.columns(3)
            m1.metric("Modal Awal", "IDR 100 Juta")
            m2.metric("Hasil Akhir", f"IDR {final_val/1_000_000:.1f} Juta")
            
            color_profit = "normal" if profit >= 0 else "inverse"
            m3.metric("Total Profit/Loss", f"{profit:.2f}%", delta=f"{profit:.2f}%")

            if trade_log:
                with st.expander("📜 Lihat Jurnal Transaksi (Trading Log)"):
                    trades_df = pd.DataFrame(trade_log)
                    st.dataframe(trades_df, use_container_width=True)
            else:
                st.warning("⚠️ Tidak ada sinyal trade yang valid pada periode ini. Coba perpanjang 'Periode Data'.")

        with c2:
            st.header("💡 AI Signal")
            last_mfi = df['MFI'].iloc[-1]
            last_bbw = df['BBW'].iloc[-1]
            
            st.write(f"**MFI Level:** {last_mfi:.1f}")
            if last_mfi < 20:
                st.success("✅ STRONG BUY (Oversold)")
            elif last_mfi > 80:
                st.error("❌ SELL / TAKE PROFIT (Overbought)")
            else:
                st.info("⚖️ HOLD / NEUTRAL")
                
            st.write("---")
            st.write(f"**Volatility:** {last_bbw:.1f}")
            if last_bbw < 5: # Angka 5 relatif, tergantung aset
                st.warning("⚠️ SQUEEZE DETECTED: Siap-siap ledakan harga!")
            
    else:
        st.error(f"Data tidak ditemukan untuk simbol '{ticker}'. Pastikan koneksi internet lancar atau ganti simbol.")

except Exception as e:
    st.error(f"Terjadi kesalahan sistem: {e}")
    st.write("Saran: Coba refresh halaman atau ganti timeframe.")
