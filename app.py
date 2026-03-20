import streamlit as st, ccxt, pandas as pd, numpy as np, requests
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta

# --- 1. CONFIG & UTILS ---
st.set_page_config(layout="wide", page_title="Scalper V8.8 Compact")

def send_telegram(msg):
    token, chat_id = "TOKEN_BOT_ANDA", "CHAT_ID_ANDA" # ISI DISINI
    if "TOKEN" in token: return
    try: requests.get(f"https://api.telegram.org/bot{token}/sendMessage", params={'chat_id': chat_id, 'text': msg, 'parse_mode': 'Markdown'}, timeout=2)
    except: pass

def fmt(x): return f"{x:,.0f}".replace(",", ".")

# --- 2. DATA ENGINE ---
def get_data(symbol, tf):
    try:
        ex = ccxt.indodax()
        ohlcv = ex.fetch_ohlcv(symbol, tf, limit=500)
        if not ohlcv: return pd.DataFrame(), None
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms').dt.tz_localize('UTC').dt.tz_convert('Asia/Jakarta')
        return df, ex.fetch_ticker(symbol)
    except: return pd.DataFrame(), None

def get_ob(symbol):
    try:
        ob = ccxt.indodax().fetch_order_book(symbol, limit=50)
        bids, asks = pd.DataFrame(ob['bids'], columns=['p','v']), pd.DataFrame(ob['asks'], columns=['p','v'])
        return {'buy_w': bids.iloc[bids['v'].idxmax()], 'sell_w': asks.iloc[asks['v'].idxmax()], 'bids': bids.head(10), 'asks': asks.head(10)}
    except: return None

# --- 3. INDICATORS (EMA, MACD, RSI, SUPERTREND) ---
def process_data(df):
    if df.empty: return df
    # Basic
    df['EMA_200'] = df['close'].ewm(span=200).mean()
    df['MACD'] = df['close'].ewm(span=12).mean() - df['close'].ewm(span=26).mean()
    df['Signal'] = df['MACD'].ewm(span=9).mean()
    df['Hist'] = df['MACD'] - df['Signal']
    
    # ATR & RSI
    df['tr'] = np.maximum(df['high']-df['low'], np.maximum(abs(df['high']-df['close'].shift()), abs(df['low']-df['close'].shift())))
    df['ATR'] = df['tr'].ewm(span=14).mean().bfill()
    delta = df['close'].diff()
    gain = (delta.where(delta>0, 0)).rolling(14).mean()
    loss = (-delta.where(delta<0, 0)).rolling(14).mean()
    df['RSI'] = 100 - (100/(1 + gain/loss))

    # Supertrend Logic (Compact)
    st_mul = 3
    df['st_u'] = ((df['high']+df['low'])/2) + (st_mul*df['ATR'])
    df['st_l'] = ((df['high']+df['low'])/2) - (st_mul*df['ATR'])
    df['st'], df['st_dir'] = df['st_u'], 1
    
    for i in range(1, len(df)):
        prev, curr = df.iloc[i-1], df.iloc[i]
        df.at[df.index[i], 'st_u'] = curr['st_u'] if curr['st_u'] < prev['st_u'] or prev['close'] > prev['st_u'] else prev['st_u']
        df.at[df.index[i], 'st_l'] = curr['st_l'] if curr['st_l'] > prev['st_l'] or prev['close'] < prev['st_l'] else prev['st_l']
        
        if prev['st_dir'] == 1:
            if curr['close'] < df.at[df.index[i], 'st_l']:
                df.at[df.index[i], 'st_dir'], df.at[df.index[i], 'st'] = -1, df.at[df.index[i], 'st_u']
            else:
                df.at[df.index[i], 'st_dir'], df.at[df.index[i], 'st'] = 1, df.at[df.index[i], 'st_l']
        else:
            if curr['close'] > df.at[df.index[i], 'st_u']:
                df.at[df.index[i], 'st_dir'], df.at[df.index[i], 'st'] = 1, df.at[df.index[i], 'st_l']
            else:
                df.at[df.index[i], 'st_dir'], df.at[df.index[i], 'st'] = -1, df.at[df.index[i], 'st_u']
    return df

# --- 4. SIGNALS & ZONES ---
def get_signals(df):
    zones, history = [], []
    vol_ma = df['volume'].rolling(20).mean()
    
    # Zones
    for i in range(max(0,len(df)-200), len(df)-2):
        c, p = df.iloc[i], df.iloc[i-1]
        if c['volume'] > vol_ma.iloc[i]:
            if c['close'] > c['open'] and p['close'] < p['open']: 
                zones.append({'type':'DEMAND','top':p['high'],'bot':p['low'],'time':p['timestamp'],'c':'rgba(41,182,246,0.2)'})
            elif c['close'] < c['open'] and p['close'] > p['open']: 
                zones.append({'type':'SUPPLY','top':p['high'],'bot':p['low'],'time':p['timestamp'],'c':'rgba(255,167,38,0.2)'})
    
    # Signals
    df['sig_buy'], df['sig_sell'] = False, False
    for i in range(max(1, len(df)-100), len(df)):
        row, prev = df.iloc[i], df.iloc[i-1]
        entry = row['close']
        
        # Triggers
        safe = row['RSI'] < 70
        macd_cross = prev['MACD'] < prev['Signal'] and row['MACD'] > row['Signal']
        candle_trig = row['close'] > row['open'] and row['volume'] > row['Vol_MA']*1.5
        
        # 1. Zone Buy
        hit_zone = False
        if row['MACD'] > row['Signal'] and candle_trig and safe:
            for z in zones:
                if z['type']=='DEMAND' and z['time'] < row['timestamp'] and row['low'] <= z['top']*1.015 and row['high'] >= z['bot']:
                    tp = z['top'] + (z['top']-z['bot'])*2
                    if (tp-entry)/entry > 0.008: # Fee Guard
                        df.loc[df.index[i],'sig_buy'] = True
                        history.append({'W':row['timestamp'],'T':'BUY (Zone)','E':entry,'TP':tp,'S':'Active'})
                        hit_zone = True; break
        
        # 2. Momentum Buy
        if not hit_zone and macd_cross and safe:
            sl = row['low'] - row['ATR']*1.5
            tp = entry + (entry-sl)*1.5
            if (tp-entry)/entry > 0.008:
                df.loc[df.index[i],'sig_buy'] = True
                history.append({'W':row['timestamp'],'T':'BUY (Momtm)','E':entry,'TP':tp,'S':'Active'})

        # Sell Signal (Simple)
        if prev['MACD'] > prev['Signal'] and row['MACD'] < row['Signal']:
            df.loc[df.index[i],'sig_sell'] = True
            history.append({'W':row['timestamp'],'T':'SELL','E':entry,'TP':0,'S':'Exit'})
            
    return df, zones, history

# --- 5. DASHBOARD & UI ---
st.sidebar.header("🎛️ Scalper V8.8")
sym = st.sidebar.selectbox("Pair", ['BTC/IDR','ETH/IDR','SOL/IDR','DOGE/IDR','XRP/IDR','SHIB/IDR','USDT/IDR'])
tf = st.sidebar.selectbox("TF", ['1m','15m','30m','1h','4h'])

@st.fragment(run_every=60)
def main():
    df, ticker = get_data(sym, tf)
    if df.empty: return
    
    df = process_data(df)
    df, zones, hist = get_signals(df)
    ob = get_ob(sym)
    
    # Current State
    curr, rsi = ticker['last'], df['RSI'].iloc[-1]
    st_bull = df['st_dir'].iloc[-1] == 1
    trend_c = "#00e676" if st_bull else "#ff1744"
    
    # Signal Alert
    last_sig = hist[-1] if hist else None
    stat_txt, stat_col = (last_sig['T'], "#00e676" if 'BUY' in last_sig['T'] else "#ff1744") if last_sig and last_sig['W']==df['timestamp'].iloc[-1] else ("WAITING...", "#777")
    if last_sig and last_sig['W']==df['timestamp'].iloc[-1] and 'sent' not in st.session_state:
        send_telegram(f"🚨 {sym} {last_sig['T']} @ {last_sig['E']}")
        st.session_state['sent'] = last_sig['W']

    # CSS Layout
    st.markdown(f"""
    <style>
        .main-grid {{ display: grid; grid-template-columns: 1.5fr 1fr 1fr 1fr 1fr; gap: 8px; margin-bottom: 10px; }}
        .sub-grid {{ display: grid; grid-template-columns: 1fr 1fr 1fr 1fr 1.2fr; gap: 8px; margin-bottom: 20px; }}
        .box {{ background: #1e1e1e; border: 1px solid #333; padding: 8px; border-radius: 5px; text-align: center; }}
        .sig {{ background: {stat_col}20; border: 2px solid {stat_col}; padding: 8px; border-radius: 5px; text-align: center; }}
        .l {{ font-size: 9px; color: #aaa; font-weight: bold; }} .v {{ font-size: 14px; font-weight: bold; color: white; }}
        .vl {{ font-size: 18px; font-weight: 900; color: {stat_col}; }}
    </style>
    <div class="main-grid">
        <div class="sig"><div class="l">STATUS</div><div class="vl">{stat_txt}</div></div>
        <div class="box"><div class="l">PRICE</div><div class="v" style="color:#f1c40f">{fmt(curr)}</div></div>
        <div class="box"><div class="l">LOW 24H</div><div class="v" style="color:#ff1744">{fmt(ticker['low'])}</div></div>
        <div class="box"><div class="l">HIGH 24H</div><div class="v" style="color:#00e676">{fmt(ticker['high'])}</div></div>
        <div class="box"><div class="l">VOL</div><div class="v">{fmt(ticker['baseVolume'])}</div></div>
    </div>
    <div class="sub-grid">
        <div class="box" style="border-top:3px solid #29b6f6"><div class="l">PLAN ENTRY</div><div class="v" style="color:#29b6f6">{fmt(last_sig['E']) if last_sig else '-'}</div></div>
        <div class="box" style="border-top:3px solid #00e676"><div class="l">TAKE PROFIT</div><div class="v" style="color:#00e676">{fmt(last_sig['TP']) if last_sig and 'TP' in last_sig else '-'}</div></div>
        <div class="box"><div class="l">RSI</div><div class="v">{rsi:.0f}</div></div>
        <div class="box"><div class="l">TREND</div><div class="v" style="color:{trend_c}">{'BULL 🟢' if st_bull else 'BEAR 🔴'}</div></div>
        <div class="box"><div class="l">WALL SUPPORT</div><div class="v" style="color:#00e676">{fmt(ob['buy_w']['p']) if ob else '-'}</div></div>
    </div>
    """, unsafe_allow_html=True)

    # Plotting (Row 1: Candle+ST, Row 2: MACD)
    r_end, r_start = df['timestamp'].iloc[-1]+timedelta(minutes=15), df['timestamp'].iloc[-60]
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.03)
    
    # R1: Candle & Zones
    fig.add_trace(go.Candlestick(x=df['timestamp'], open=df['open'], high=df['high'], low=df['low'], close=df['close'], name='Price'), row=1, col=1)
    for z in zones:
        fig.add_shape(type="rect", x0=z['time'], y0=z['bot'], x1=r_end+timedelta(hours=4), y1=z['top'], fillcolor=z['c'], line_width=0, row=1, col=1)
    
    # R1: Supertrend (Split Colors)
    st_g, st_r = df.copy(), df.copy()
    st_g.loc[st_g['st_dir']==-1, 'st'] = np.nan
    st_r.loc[st_r['st_dir']==1, 'st'] = np.nan
    fig.add_trace(go.Scatter(x=st_g['timestamp'], y=st_g['st'], line=dict(color='#00e676', width=2), name='ST Bull'), row=1, col=1)
    fig.add_trace(go.Scatter(x=st_r['timestamp'], y=st_r['st'], line=dict(color='#ff1744', width=2), name='ST Bear'), row=1, col=1)
    
    # R1: Wall Lines
    if ob:
        fig.add_hline(y=ob['buy_w']['p'], line_dash="dash", line_color="#00e676", row=1, col=1)
        fig.add_hline(y=ob['sell_w']['p'], line_dash="dash", line_color="#ff1744", row=1, col=1)
        
    # R1: Buy Markers
    if df['sig_buy'].any():
        fig.add_trace(go.Scatter(x=df[df['sig_buy']]['timestamp'], y=df[df['sig_buy']]['low'], mode='markers', marker=dict(symbol='triangle-up', size=12, color='cyan'), name='Buy'), row=1, col=1)

    # R2: MACD (RESTORED)
    fig.add_trace(go.Bar(x=df['timestamp'], y=df['Hist'], marker_color=np.where(df['Hist']<0, '#ff1744', '#00e676'), name='Hist'), row=2, col=1)
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['MACD'], line=dict(color='#2962ff'), name='MACD'), row=2, col=1)
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['Signal'], line=dict(color='#ff9100'), name='Signal'), row=2, col=1)

    fig.update_layout(height=650, template="plotly_dark", margin=dict(l=0,r=50,t=0,b=0), showlegend=False,
                      xaxis=dict(range=[r_start, r_end], rangeslider=dict(visible=True), type="date"))
    st.plotly_chart(fig, use_container_width=True)

    # Tables
    c1, c2 = st.columns(2)
    with c1:
        st.caption("🟦 Demand & 🟧 Supply")
        if zones: st.table(pd.DataFrame([[ "DEMAND" if z['type']=='DEMAND' else "SUPPLY", f"{z['bot']:,.0f}-{z['top']:,.0f}", z['time'].strftime('%H:%M')] for z in reversed(zones[-5:])], columns=["Tipe","Area","Waktu"]))
    with c2:
        st.caption("📊 History Signals")
        if hist: st.dataframe(pd.DataFrame([[h['W'].strftime('%H:%M'), h['T'], f"{h['E']:,.0f}"] for h in hist[::-1]], columns=['Jam','Tipe','Entry']), height=150, hide_index=True)

    st.divider(); st.caption("🧱 Deep Orderbook (50 Ticks)")
    if ob:
        c3, c4 = st.columns(2)
        with c3: st.success(f"Bids (Wall: {fmt(ob['buy_w']['p'])})"); st.dataframe(ob['bids'].style.format("{:,.0f}"), hide_index=True)
        with c4: st.error(f"Asks (Wall: {fmt(ob['sell_w']['p'])})"); st.dataframe(ob['asks'].style.format("{:,.0f}"), hide_index=True)

main()
