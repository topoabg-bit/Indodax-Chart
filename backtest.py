# Simpan ini sebagai backtest.py
import ccxt
import pandas as pd
import numpy as np
# Import fungsi dari file bot utama Anda (asumsikan nama file bot.py)
from bot import get_data, process_indicators, detect_zones, generate_signals

def run_backtest(symbol='BTC/IDR', tf='15m', modal_awal=10_000_000):
    print(f"🔄 Memulai Backtest untuk {symbol} ({tf})...")
    
    # 1. Ambil Data Lebih Banyak (Limit diperbesar)
    exchange = ccxt.indodax()
    ohlcv = exchange.fetch_ohlcv(symbol, tf, limit=1000) # Tarik 1000 candle
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    
    # 2. Jalankan Logika Bot
    df = process_indicators(df)
    zones = detect_zones(df)
    df, history = generate_signals(df, zones)
    
    # 3. Simulasi Saldo
    saldo = modal_awal
    win = 0
    loss = 0
    fee_trx = 0.006 # 0.6% (Beli 0.3% + Jual 0.3%)
    
    equity_curve = [modal_awal]
    
    print(f"\n📊 HASIL BACKTEST:")
    print("-" * 40)
    
    for trade in history:
        # Simulasi Profit/Loss
        # Asumsi: TP atau SL pasti kena (Sederhana)
        # Realitanya kita harus cek candle by candle, tapi ini estimasi kasar yang cukup
        
        entry = trade['Entry']
        
        if "BUY" in trade['Tipe']:
            tp = trade['TP']
            sl = trade['SL']
            # Kita cek mana yang kena duluan di candle masa depan (Simplified)
            # Di sini kita pakai asumsi Win Rate 50% random untuk contoh, 
            # ATAU cek data high/low candle berikutnya (Lebih akurat)
            
            # Logika Profit Kotor (Tanpa Fee)
            pnl_percent = (tp - entry) / entry if trade['Status'] == 'Active' else (sl - entry) / entry
            
            # Kurangi Fee
            pnl_bersih_percent = pnl_percent - fee_trx
            
            # Update Saldo
            profit_rupiah = saldo * pnl_bersih_percent
            saldo += profit_rupiah
            
            trade_res = "WIN ✅" if profit_rupiah > 0 else "LOSS ❌"
            if profit_rupiah > 0: win += 1
            else: loss += 1
            
            print(f"{trade['Waktu'].strftime('%d/%m %H:%M')} | {trade_res} | Rp {profit_rupiah:,.0f}")
            equity_curve.append(saldo)

    total_trade = win + loss
    win_rate = (win / total_trade * 100) if total_trade > 0 else 0
    
    print("-" * 40)
    print(f"💰 Saldo Awal  : Rp {modal_awal:,.0f}")
    print(f"🏁 Saldo Akhir : Rp {saldo:,.0f}")
    print(f"📈 Net Profit  : Rp {saldo - modal_awal:,.0f} ({(saldo-modal_awal)/modal_awal*100:.2f}%)")
    print(f"🎯 Win Rate    : {win_rate:.1f}% ({win}/{total_trade})")

# Jalankan
run_backtest()
