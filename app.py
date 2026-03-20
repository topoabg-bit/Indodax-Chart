import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import requests

# --- 1. SETUP ---
st.set_page_config(layout="wide", page_title="Scalper V8.9 Stable")

def send_telegram(message):
    BOT_TOKEN = "TOKEN_BOT_ANDA_DISINI" 
    CHAT_ID = "CHAT_ID_ANDA_DISINI"
    if "TOKEN" in BOT_TOKEN: return 
    try: requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", params={'chat_id': CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}, timeout=2)
    except: pass

# --- 2. DATA ---
def get_data(symbol, tf):
    try:
        ex = ccxt.indodax()
        ohlcv = ex.fetch_ohlcv(symbol, tf, limit=500)
        if not ohlcv: return pd.DataFrame(), None
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize('UTC').dt.tz_convert('Asia/Jakarta')
        return df, ex.fetch_ticker(symbol)
    except Exception as e: return pd.DataFrame(), None

def get_ob(symbol):
    try:
        ob = ccxt.indodax().fetch_order_book(symbol, limit=50)
        bids, asks = pd.DataFrame(ob['bids'], columns=['p','v']), pd.DataFrame(ob['asks'], columns=['p','v'])
        return {'buy_w': bids.iloc[bids['v'].idxmax()], 'sell_w': asks.iloc[asks['v'].idxmax()], 'bids': bids.head(10), 'asks': asks.head(10)}
    except: return None

# --- 3. INDIKATOR (FIXED) ---
def process_indicators(df):
    if df.empty: return df
    
    # EMA & MACD
    df['EMA_200'] = df['close'].ewm(span=200).mean()
    df['MACD'] = df['close'].ewm(span=12).mean() - df['close'].ewm(span=26).mean()
    df['Signal'] = df['MACD'].ewm(span=9).mean()
    df['Hist'] = df['MACD'] - df['Signal']
    
    # ATR & RSI (Fix NaN for Supertrend)
    df['tr'] = np.maximum(df['high']-df['low'], np.maximum(abs(df['high']-df['close'].shift()), abs(df['low']-df['close'].shift())))
    df['ATR'] = df['tr'].ewm(span=14).mean().bfill()
    
    delta = df['close'].diff()
    gain = (delta.where(delta>0, 0)).rolling(14).mean()
    loss = (-delta.where(delta<0, 0)).rolling(14).mean()
    df['RSI'] = 100 - (100/(1 + gain/loss))
    
    # VOL MA (PENTING: Ini yang bikin error sebelumnya, sekarang sudah ada)
    df['Vol_MA'] = df['volume'].rolling(20).mean()
    df['Vol_Spike'] = df['volume'] > (df['Vol_MA'] * 1.5)
    df['Bull_Engulf'] = (df['close'] > df['open']) & (df['close'] > df['open'].shift(1)) & (df['open'] < df['close'].shift(1))

    # Supertrend
    st_mul = 3
    df['st_u'] = ((df['high']+df['low'])/2) + (st_mul*df['ATR'])
    df['st_l'] = ((df['high']+df['low'])/2) - (st_mul*df['ATR'])
    df['st'], df['st_dir'] = df['st_u'], 1
    
    for i in range(1, len(df)):
        # Logic Upper
        if df['st_u'].iloc[i] < df['st_u'].iloc[i-1] or df['close'].iloc[i-1] > df['st_u'].iloc[i-1]:
            df.at[df.index[i], 'st_u'] = df['st_u'].iloc[i]
        else:
            df.at[df.index[i], 'st_u'] = df['st_u'].iloc[i-1]
            
        # Logic Lower
        if df['st_l'].iloc[i] > df['st_l'].iloc[i-1] or df['close'].iloc[i-1] < df['st_l'].iloc[i-1]:
            df.at[df.index[i], 'st_l'] = df['st_l'].iloc[i]
        else:
            df.at[df.index[i], 'st_l'] = df['st_l'].iloc[i-1]
            
        # Switch
        if df['st_dir'].iloc[i-1] == 1:
            if df['close'].iloc[i] < df['st_l'].iloc[i]:
                df.at[df.index[i], 'st_dir'], df.at[df.index[i], 'st'] = -1, df['st_u'].iloc[i]
            else:
                df.at[df.index[i], 'st_dir'], df.at[df.index[i], 'st'] = 1, df['st_l'].iloc[i]
        else:
            if df['close'].iloc[i] > df['st_u'].iloc[i]:
                df.at[df.index[i], 'st_dir'], df.at[df.index[i], 'st'] = 1, df['st_l'].iloc[i]
            else:
                df.at[df.index[i], 'st_dir'], df.at[df.index[i], 'st'] = -1, df['st_u'].iloc[i]
    return df

# --- 4. ZONES & SIGNALS ---
def get_analysis(df):
    zones, history = [], []
    vol_ma = df['volume'].rolling(20).mean()
    
    # Zones
    for i in range(max(0, len(df)-200), len(df)-2):
        c, p = df.iloc[i], df.iloc[i-1]
        if c['volume'] > vol_ma.iloc[i]: # Impulse
            if c['close'] > c['open'] and p['close'] < p['open']:
                zones.append({'type':'DEMAND','top':p['high'],'bot':p['low'],'time':p['timestamp'],'c':'rgba(41,182,246,0.2)'})
            elif c['close'] < c['open'] and p['close'] > p['open']:
                zones.append({'type':'SUPPLY','top':p['high'],'bot':p['low'],'time':p['timestamp'],'c':'rgba(255,167,38,0.2)'})
    
    # Signals
    df['sig_buy'], df['sig_sell'] = False, False
    for i in range(max(1, len(df)-100), len(df)):
        row, prev = df.iloc[i], df.iloc[i-1]
        entry = row['close']
        
        safe = row['RSI'] < 70
        macd_cross = prev['MACD'] < prev['Signal'] and row['MACD'] > row['Signal']
        trigger = row['Bull_Engulf'] or row['Vol_Spike']
        
        hit_zone = False
        if row['MACD'] > row['Signal'] and trigger and safe:
            for z in zones:
                if z['type']=='DEMAND' and z['time'] < row['timestamp'] and row['low'] <= z['top']*1.015 and row['high'] >= z['bot']:
                    tp = z['top'] + (z['top']-z['bot'])*2
                    if (tp-entry)/entry > 0.008:
                        df.loc[df.index[i],'sig_buy'] = True
                        history.append({'W':row['timestamp'],'T':'BUY (Zone)','E':entry,'TP':tp})
                        hit_zone = True; break
        
        if not hit_zone and macd_cross and safe:
            sl = row['low'] - row['ATR']*1.5
            tp = entry + (entry-sl)*1.5
            if (tp-entry)/entry > 0.008:
                df.loc[df.index[i],'sig_buy'] = True
                history.append({'W':row['timestamp'],'T':'BUY (Momtm)','E':entry,'TP':tp})

        if prev['MACD'] > prev['Signal'] and row['MACD'] < row['Signal']:
             df.loc[df.index[i],'sig_sell'] = True
             history.append({'W':row['timestamp'],'T':'SELL','E':entry,'TP':0})
             
    return df, zones, history

# --- 5. DASHBOARD (LAYOUT V8.2) ---
st.sidebar.header("🎛️ Scalper V8.9")
sym = st.sidebar.selectbox("Pair", ['BTC/IDR','ETH/IDR','SOL/IDR','DOGE/IDR','XRP/IDR','SHIB/IDR','USDT/IDR'])
tf = st.sidebar.selectbox("TF", ['1m','15m','30m','1h','4h'])

@st.fragment(run_every=60)
def main():
    df, ticker = get_data(sym, tf)
    if df.empty: return
    
    df = process_indicators(df)
    df, zones, hist = get_analysis(df)
    ob = get_ob(sym)
    
    curr = float(ticker['last'])
    st_dir = df['st_dir'].iloc[-1]
    rsi_val = df['RSI'].iloc[-1]
    trend_c = "#00e676" if st_dir == 1 else "#ff1744"
    
    # Signal Logic
    if 'last_sig' not in st.session_state: st.session_state['last_sig'] = None
    last = hist[-1] if hist else None
    status, sig_c, plan, tp = "WAITING...", "#777", "-", "-"
    
    if last and last['W'] == df['timestamp'].iloc[-1]:
        if st.session_state['last_sig'] != last['W']:
            st.session_state['last_sig'] = last['W']
            send_telegram(f"SIGNAL {sym}: {last['T']}")
            st.toast("Signal Alert!", icon="🚨")
        status = last['T']
        sig_c = "#00e676" if 'BUY' in status else "#ff1744"
        plan, tp = f"{last['E']:,.0f}", f"{last['TP']:,.0f}"

    def fmt(x): return f"{x:,.0f}".replace(",", ".")

    # LAYOUT V8.2 (Kotak-kotak)
    st.markdown(f"""
    <style>
        .row-1 {{ display: grid; grid-template-columns: 1.5fr 1fr 1fr 1fr 1fr; gap: 8px; margin-bottom: 10px; }}
        .row-2 {{ display: grid; grid-template-columns: 1fr 1fr 1fr 1fr 1.2fr; gap: 8px; margin-bottom: 20px; }}
        .box {{ background: #1e1e1e; border: 1px solid #333; padding: 8px; border-radius: 6px; text-align: center; }}
        .sig-box {{ background: {sig_c}20; border: 2px solid {sig_c}; padding: 8px; border-radius: 6px; text-align: center; }}
        .lbl {{ font-size: 9px; color: #aaa; font-weight: bold; margin-bottom: 3px; }}
        .val {{ font-size: 14px; font-weight: bold; color: white; }}
        .val-lg {{ font-size: 18px; font-weight: 900; color: {sig_c}; }}
    </style>
    <div class="row-1">
        <div class="sig-box"><div class="lbl">STATUS</div><div class="val-lg">{status}</div></div>
        <div class="box"><div class="lbl">HARGA</div><div class="val" style="color:#f1c40f">{fmt(curr)}</div></div>
        <div class="box"><div class="lbl">LOW 24H</div><div class="val" style="color:#ff1744">{fmt(ticker['low'])}</div></div>
        <div class="box"><div class="lbl">HIGH 24H</div><div class="val" style="color:#00e676">{fmt(ticker['high'])}</div></div>
        <div class="box"><div class="lbl">VOL</div><div class="val">{fmt(ticker['baseVolume'])}</div></div>
    </div>
    <div class="row-2">
        <div class="box" style="border-top: 3px solid #29b6f6"><div class="lbl">ENTRY PLAN</div><div class="val" style="color:#29b6f6">{plan}</div></div>
        <div class="box" style="border-top: 3px solid #00e676"><div class="lbl">TAKE PROFIT</div><div class="val" style="color:#00e676">{tp}</div></div>
        <div class="box"><div class="lbl">RSI</div><div class="val">{rsi_val:.0f}</div></div>
        <div class="box"><div class="lbl">TREND</div><div class="val" style="color:{trend_c}">{'BULL 🟢' if st_dir==1 else 'BEAR 🔴'}</div></div>
        <div class="box"><div class="lbl">WALL</div><div class="val" style="color:#00e676">{fmt(ob['buy_w']['p']) if ob else '-'}</div></div>
    </div>
    """, unsafe_allow_html=True)

    # CHART (Row 1: Price+ST, Row 2: MACD)
    r_end = df['timestamp'].iloc[-1] + timedelta(minutes=15)
    r_start = df['timestamp'].iloc[-60]
    
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.03)
    
    # Candle & Zones
    fig.add_trace(go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Price'), row=1, col=1)
    for z in zones:
        fig.add_shape(type="rect", x0=z['time'], y0=z['bot'], x1=r_end+timedelta(hours=4), y1=z['top'], fillcolor=z['c'], line_width=0, row=1, col=1)
    
    # Supertrend
    st_g, st_r = df.copy(), df.copy()
    st_g.loc[st_g['st_dir']==-1, 'st'] = np.nan
    st_r.loc[st_r['st_dir']==1, 'st'] = np.nan
    fig.add_trace(go.Scatter(x=st_g['timestamp'], y=st_g['st'], line=dict(color='#00e676', width=2), name='ST Bull'), row=1, col=1)
    fig.add_trace(go.Scatter(x=st_r['timestamp'], y=st_r['st'], line=dict(color='#ff1744', width=2), name='ST Bear'), row=1, col=1)
    
    # Signals & Walls
    if df['sig_buy'].any():
        fig.add_trace(go.Scatter(x=df[df['sig_buy']]['timestamp'], y=df[df['sig_buy']]['low'], mode='markers', marker=dict(symbol='triangle-up', size=14, color='cyan'), name='BUY'), row=1, col=1)
    if ob:
        fig.add_hline(y=ob['buy_w']['p'], line_dash="dash", line_color="#00e676", row=1, col=1)
        fig.add_hline(y=ob['sell_w']['p'], line_dash="dash", line_color="#ff1744", row=1, col=1)

    # MACD (Row 2)
    fig.add_trace(go.Bar(x=df['timestamp'], y=df['Hist'], marker_color=np.where(df['Hist']<0, '#ff1744', '#00e676')), row=2, col=1)
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['MACD'], line=dict(color='#2962ff'), name='MACD'), row=2, col=1)
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['Signal'], line=dict(color='#ff9100'), name='Signal'), row=2, col=1)
    
    fig.update_layout(height=650, template="plotly_dark", margin=dict(l=0,r=50,t=0,b=0), showlegend=False,
                      xaxis=dict(range=[r_start, r_end], rangeslider=dict(visible=True), type="date"))
    st.plotly_chart(fig, use_container_width=True)

    # TABLES
    c1, c2 = st.columns(2)
    with c1:
        st.caption("🟦 Demand & 🟧 Supply")
        if zones: st.table(pd.DataFrame([[ "DEMAND" if z['type']=='DEMAND' else "SUPPLY", f"{fmt(z['bot'])}-{fmt(z['top'])}", z['time'].strftime('%H:%M')] for z in reversed(zones[-5:])], columns=["Tipe","Area","Waktu"]))
    with c2:
        st.caption("📊 Riwayat Sinyal")
        if hist: st.dataframe(pd.DataFrame([[h['W'].strftime('%H:%M'), h['T'], f"{h['E']:,.0f}"] for h in hist[::-1]], columns=['Jam','Tipe','Entry']), height=150, hide_index=True)

    st.divider(); st.caption("🧱 Deep Orderbook (50 Ticks)")
    if ob:
        c3, c4 = st.columns(2)
        with c3: st.success(f"Bids (Wall: {fmt(ob['buy_w']['p'])})"); st.dataframe(ob['bids'].style.format("{:,.0f}"), hide_index=True)
        with c4: st.error(f"Asks (Wall: {fmt(ob['sell_w']['p'])})"); st.dataframe(ob['asks'].style.format("{:,.0f}"), hide_index=True)

main()
