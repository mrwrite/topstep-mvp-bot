from fastapi import APIRouter, Depends, HTTPException
import time
import requests
from config import BASE_URL
from app.auth import get_session_token
import pandas as pd
from datetime import datetime, timedelta
from indicators import compute_indicators
from app.strategy import check_trade_signal
from projectx import execute_trade, get_contract_id
from logger import log_trade
import csv
import os

router = APIRouter()

def fetch_price_data(token, contract_id, interval_minutes=1, lookback_minutes=100):
    """Fetch historical bars for the given contract.

    The function previously looked at a very short window one day in the past.
    To better seed the indicator calculations we extend the window to cover the
    last month.  The API still respects the ``limit`` parameter so callers can
    control how many bars are returned.
    """

    end_time = datetime.utcnow()
    start_time = end_time - timedelta(days=30)

    url = f"{BASE_URL}/api/History/retrieveBars"
    payload = {
        "contractId": contract_id,
        "live": False,
        "startTime": start_time.isoformat() + "Z",
        "endTime": end_time.isoformat() + "Z",
        "unit": 2,  # 2 = Minute
        "unitNumber": interval_minutes,
        "limit": lookback_minutes,
        "includePartialBar": False
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "accept": "application/json"
    }

    print("📡 Requesting bars from:", url)
    print("📨 Payload:", payload)

    response = requests.post(url, json=payload, headers=headers)

    print("📥 Status Code:", response.status_code)
    print("📥 Response Text:", response.text)

    if response.status_code != 200:
        raise Exception(f"Error fetching price data: {response.text}")

    data = response.json()
    if not data.get("success") or "bars" not in data:
        raise Exception(f"Invalid response: {data}")

    bars = data["bars"]
    if not bars:
        print("❌  No bars returned -- skipping this interval.")
        return
    df = pd.DataFrame(bars)
    df.rename(columns={
        't': 'timestamp',
        'o': 'open',
        'h': 'high',
        'l': 'low',
        'c': 'close',
        'v': 'volume'
    }, inplace=True)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df.set_index('timestamp', inplace=True)
    return df

@router.get("/run-bot")
def run_bot(symbol="RTYZ4", quantity=1, interval_seconds=60):
    print("📈 Starting bot loop at", datetime.now())

    token = get_session_token()
    contract_id = get_contract_id(symbol, token)
    if not contract_id:
        print("❌ Could not get contract ID.")
        return

    while True:
        try:
            print(f"\n⏰ Fetching data at {datetime.now()}")
            df = fetch_price_data(token=token, contract_id=contract_id)

            if df is None or df.empty:
                print("⚠️ No data returned.")
                time.sleep(interval_seconds)
                continue

            indicators = compute_indicators(df)
            required_cols = ['rsi', 'ma_fast', 'ma_slow']
            if not all(col in indicators.columns for col in required_cols):
                raise Exception(f"Missing indicator columns in DataFrame: {set(required_cols) - set(indicators.columns)}")
            print("🧪 Indicator columns:", indicators.columns)
            print("📊 Indicators computed:", indicators.tail())
            print("📉 RSI:", indicators['rsi'].iloc[-1])
            print("📈 MA Fast:", indicators['ma_fast'].iloc[-1])
            print("📉 MA Slow:", indicators['ma_slow'].iloc[-1])

            signal = check_trade_signal(indicators)

            print(f"📊 Latest Close: {df['close'].iloc[-1]:.2f} | Signal: {signal}")

            if signal == "BUY":
                print("🟢 BUY signal detected!")
                response = execute_trade(symbol=symbol, side="BUY", quantity=quantity, token=token)
                print("✅ Trade response:", response)
                log_trade(symbol, "BUY", quantity, df['close'].iloc[-1], "SUCCESS" if response.get("success") else "FAIL", str(response))
            elif signal == "SELL":
                print("🔴 SELL signal detected!")
                response = execute_trade(symbol=symbol, side="SELL", quantity=quantity, token=token)
                print("✅ Trade response:", response)
                log_trade(symbol, "SELL", quantity, df['close'].iloc[-1], "SUCCESS" if response.get("success") else "FAIL", str(response))
            else:
                print("⏳ No trade signal at this time.")

        except Exception as e:
            print("❌ Error during bot loop:", str(e))

        time.sleep(interval_seconds)
