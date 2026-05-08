from flask import Flask, jsonify, request
from flask_cors import CORS
import requests
import math
import time
from datetime import datetime, timezone

app = Flask(__name__)
CORS(app)

# ─────────────────────────────────────────────
#  جلب البيانات الحقيقية من Yahoo Finance (مجاني)
# ─────────────────────────────────────────────

PAIR_SYMBOLS = {
    # Forex
    "EUR/USD": "EURUSD=X", "GBP/USD": "GBPUSD=X", "USD/JPY": "JPY=X",
    "USD/CHF": "CHF=X",    "AUD/USD": "AUDUSD=X", "USD/CAD": "CAD=X",
    "NZD/USD": "NZDUSD=X", "EUR/JPY": "EURJPY=X", "GBP/JPY": "GBPJPY=X",
    "EUR/GBP": "EURGBP=X", "EUR/AUD": "EURAUD=X", "EUR/CAD": "EURCAD=X",
    "EUR/CHF": "EURCHF=X", "GBP/CHF": "GBPCHF=X", "GBP/AUD": "GBPAUD=X",
    "GBP/CAD": "GBPCAD=X", "AUD/JPY": "AUDJPY=X", "AUD/CAD": "AUDCAD=X",
    "AUD/CHF": "AUDCHF=X", "CAD/JPY": "CADJPY=X", "CHF/JPY": "CHFJPY=X",
    "NZD/JPY": "NZDJPY=X", "EUR/NZD": "EURNZD=X", "GBP/NZD": "GBPNZD=X",
    # OTC — نستخدم الزوج الأقرب (OTC مشتق من السوق الفوري)
    "USD/BRL OTC": "BRL=X", "USD/MXN OTC": "MXN=X", "USD/ZAR OTC": "ZAR=X",
    "USD/TRY OTC": "TRY=X", "USD/INR OTC": "INR=X", "USD/THB OTC": "THB=X",
    "USD/SGD OTC": "SGD=X", "EUR/TRY OTC": "EURTRY=X","EUR/ZAR OTC": "EURZAR=X",
    "USD/NGN OTC": "NGN=X", "USD/RUB OTC": "RUB=X", "USD/EGP OTC": "EGP=X",
    "USD/MYR OTC": "MYR=X",
}

def fetch_yahoo_candles(symbol: str, interval: str = "1m", range_: str = "1d"):
    """جلب بيانات الشموع من Yahoo Finance بدون API key"""
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?interval={interval}&range={range_}&includePrePost=false"
    )
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    }
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        result = data["chart"]["result"][0]
        timestamps = result["timestamp"]
        quote = result["indicators"]["quote"][0]
        candles = []
        for i in range(len(timestamps)):
            o = quote["open"][i]
            h = quote["high"][i]
            l = quote["low"][i]
            c = quote["close"][i]
            v = quote.get("volume", [0]*len(timestamps))[i] or 0
            if None not in (o, h, l, c):
                candles.append({"open": o, "high": h, "low": l, "close": c, "volume": v, "ts": timestamps[i]})
        return candles[-100:] if len(candles) >= 14 else None
    except Exception as e:
        print(f"Yahoo fetch error for {symbol}: {e}")
        return None

# ─────────────────────────────────────────────
#  التحليل الفني الحقيقي
# ─────────────────────────────────────────────

def ema(values: list, period: int) -> float:
    if len(values) < period:
        return sum(values) / len(values)
    k = 2 / (period + 1)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = v * k + e * (1 - k)
    return e

def sma(values: list, period: int) -> float:
    return sum(values[-period:]) / period

def calc_rsi(closes: list, period: int = 14) -> dict:
    if len(closes) < period + 1:
        return {"value": 50, "overbought": False, "oversold": False, "neutral": True}
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i-1]
        gains.append(max(d, 0))
        losses.append(max(-d, 0))
    avg_g = sum(gains[-period:]) / period
    avg_l = sum(losses[-period:]) / period
    if avg_l == 0:
        rsi_val = 100.0
    else:
        rs = avg_g / avg_l
        rsi_val = 100 - (100 / (1 + rs))
    return {
        "value": round(rsi_val, 2),
        "overbought": rsi_val > 70,
        "oversold": rsi_val < 30,
        "neutral": 40 <= rsi_val <= 60,
    }

def calc_macd(closes: list, fast=12, slow=26, sig=9) -> dict:
    if len(closes) < slow + sig:
        return {"macd": 0, "signal": 0, "histogram": 0, "bullish": False, "bearish": False}
    fast_e = ema(closes, fast)
    slow_e = ema(closes, slow)
    macd_line = fast_e - slow_e
    # signal as SMA of last `sig` MACD values (simplified but accurate enough)
    macd_series = []
    for i in range(sig):
        window = closes[:-(sig - i) if (sig - i) > 0 else len(closes)]
        if len(window) >= slow:
            macd_series.append(ema(window, fast) - ema(window, slow))
    sig_line = sum(macd_series) / len(macd_series) if macd_series else macd_line
    histogram = macd_line - sig_line
    return {
        "macd": round(macd_line, 6),
        "signal": round(sig_line, 6),
        "histogram": round(histogram, 6),
        "bullish": histogram > 0 and macd_line > 0,
        "bearish": histogram < 0 and macd_line < 0,
    }

def calc_bollinger(closes: list, period=20, k=2) -> dict:
    if len(closes) < period:
        period = len(closes)
    window = closes[-period:]
    mid = sum(window) / period
    variance = sum((x - mid)**2 for x in window) / period
    std = math.sqrt(variance)
    upper = mid + k * std
    lower = mid - k * std
    price = closes[-1]
    band_range = upper - lower
    position = (price - lower) / band_range if band_range != 0 else 0.5
    return {
        "upper": round(upper, 6), "middle": round(mid, 6), "lower": round(lower, 6),
        "position": round(position, 4),
        "squeeze": band_range < (mid * 0.003),
        "above_upper": price > upper, "below_lower": price < lower,
    }

def calc_stochastic(candles: list, period=14) -> dict:
    if len(candles) < period:
        return {"k": 50, "overbought": False, "oversold": False}
    highs = [c["high"] for c in candles[-period:]]
    lows  = [c["low"]  for c in candles[-period:]]
    close = candles[-1]["close"]
    h, l = max(highs), min(lows)
    k = ((close - l) / (h - l) * 100) if (h - l) != 0 else 50
    return {"k": round(k, 2), "overbought": k > 80, "oversold": k < 20}

def calc_atr(candles: list, period=14) -> float:
    if len(candles) < 2:
        return 0
    trs = []
    for i in range(1, len(candles)):
        hl = candles[i]["high"] - candles[i]["low"]
        hc = abs(candles[i]["high"] - candles[i-1]["close"])
        lc = abs(candles[i]["low"]  - candles[i-1]["close"])
        trs.append(max(hl, hc, lc))
    return sum(trs[-period:]) / min(period, len(trs))

def calc_ema_trend(closes: list) -> dict:
    e9  = ema(closes, 9)
    e21 = ema(closes, 21)
    e50 = ema(closes, min(50, len(closes)))
    price = closes[-1]
    return {
        "ema9": round(e9, 6), "ema21": round(e21, 6), "ema50": round(e50, 6),
        "bullish": e9 > e21 and price > e9,
        "bearish": e9 < e21 and price < e9,
        "price_above_all": price > e9 and price > e21 and price > e50,
        "price_below_all": price < e9 and price < e21 and price < e50,
    }

def detect_candle_patterns(candles: list) -> dict:
    if len(candles) < 3:
        return {"pattern": "Unknown", "bullish": False, "bearish": False}
    c0, c1, c2 = candles[-3], candles[-2], candles[-1]
    body2 = abs(c2["close"] - c2["open"])
    range2 = c2["high"] - c2["low"]
    upper_wick = c2["high"] - max(c2["close"], c2["open"])
    lower_wick = min(c2["close"], c2["open"]) - c2["low"]
    body_ratio = body2 / range2 if range2 > 0 else 0

    # Doji
    if body_ratio < 0.1:
        return {"pattern": "Doji — Indecision", "bullish": False, "bearish": False, "neutral": True}

    # Hammer (bullish reversal)
    if lower_wick > body2 * 2 and upper_wick < body2 * 0.5 and c1["close"] < c1["open"]:
        return {"pattern": "Hammer 🔨 Bullish", "bullish": True, "bearish": False}

    # Shooting Star (bearish reversal)
    if upper_wick > body2 * 2 and lower_wick < body2 * 0.5 and c1["close"] > c1["open"]:
        return {"pattern": "Shooting Star ⭐ Bearish", "bullish": False, "bearish": True}

    # Engulfing
    if (c2["close"] > c2["open"] and c1["close"] < c1["open"]
            and c2["close"] > c1["open"] and c2["open"] < c1["close"]):
        return {"pattern": "Bullish Engulfing 📈", "bullish": True, "bearish": False}

    if (c2["close"] < c2["open"] and c1["close"] > c1["open"]
            and c2["close"] < c1["open"] and c2["open"] > c1["close"]):
        return {"pattern": "Bearish Engulfing 📉", "bullish": False, "bearish": True}

    # Strong Candle
    if body_ratio > 0.7:
        bull = c2["close"] > c2["open"]
        return {
            "pattern": f"Strong {'Bullish' if bull else 'Bearish'} Candle",
            "bullish": bull, "bearish": not bull
        }

    return {"pattern": "Normal Candle", "bullish": c2["close"] > c2["open"], "bearish": c2["close"] < c2["open"]}

def calc_volume_analysis(candles: list) -> dict:
    if len(candles) < 10:
        return {"above_avg": False, "ratio": 1.0}
    vols = [c["volume"] for c in candles]
    avg_vol = sum(vols[-20:]) / min(20, len(vols))
    cur_vol = vols[-1]
    ratio = (cur_vol / avg_vol) if avg_vol > 0 else 1.0
    return {"above_avg": ratio > 1.2, "ratio": round(ratio, 2), "avg": round(avg_vol, 0)}

def calc_support_resistance(candles: list) -> dict:
    if len(candles) < 20:
        return {"support": 0, "resistance": 0}
    recent = candles[-20:]
    highs  = [c["high"] for c in recent]
    lows   = [c["low"]  for c in recent]
    return {
        "resistance": round(max(highs), 6),
        "support":    round(min(lows), 6),
        "near_resistance": candles[-1]["close"] > max(highs) * 0.998,
        "near_support":    candles[-1]["close"] < min(lows)  * 1.002,
    }

# ─────────────────────────────────────────────
#  محرك قرار الإشارة
# ─────────────────────────────────────────────

def generate_signal(candles: list) -> dict:
    closes = [c["close"] for c in candles]

    rsi       = calc_rsi(closes)
    macd      = calc_macd(closes)
    bb        = calc_bollinger(closes)
    stoch     = calc_stochastic(candles)
    ema_trend = calc_ema_trend(closes)
    pattern   = detect_candle_patterns(candles)
    volume    = calc_volume_analysis(candles)
    sr        = calc_support_resistance(candles)
    atr       = calc_atr(candles)

    bull_score = 0
    bear_score = 0
    reasons    = []

    # RSI
    if rsi["oversold"]:
        bull_score += 25
        reasons.append("RSI oversold — reversal likely ↑")
    elif rsi["overbought"]:
        bear_score += 25
        reasons.append("RSI overbought — reversal likely ↓")
    elif rsi["value"] > 60:
        bull_score += 10
        reasons.append("RSI bullish momentum")
    elif rsi["value"] < 40:
        bear_score += 10
        reasons.append("RSI bearish momentum")

    # MACD
    if macd["bullish"]:
        bull_score += 20
        reasons.append("MACD bullish crossover ↑")
    elif macd["bearish"]:
        bear_score += 20
        reasons.append("MACD bearish crossover ↓")

    # EMA Trend
    if ema_trend["bullish"]:
        bull_score += 20
        reasons.append("EMA9 > EMA21 — uptrend confirmed")
    elif ema_trend["bearish"]:
        bear_score += 20
        reasons.append("EMA9 < EMA21 — downtrend confirmed")
    if ema_trend["price_above_all"]:
        bull_score += 10
        reasons.append("Price above all EMAs — strong bull")
    elif ema_trend["price_below_all"]:
        bear_score += 10
        reasons.append("Price below all EMAs — strong bear")

    # Bollinger Bands
    if bb["below_lower"]:
        bull_score += 15
        reasons.append("Price below Bollinger lower — bounce signal ↑")
    elif bb["above_upper"]:
        bear_score += 15
        reasons.append("Price above Bollinger upper — rejection signal ↓")

    # Stochastic
    if stoch["oversold"]:
        bull_score += 10
        reasons.append("Stochastic oversold ↑")
    elif stoch["overbought"]:
        bear_score += 10
        reasons.append("Stochastic overbought ↓")

    # Candle Pattern
    if pattern["bullish"]:
        bull_score += 15
        reasons.append(f"Pattern: {pattern['pattern']}")
    elif pattern["bearish"]:
        bear_score += 15
        reasons.append(f"Pattern: {pattern['pattern']}")

    # Volume confirmation
    if volume["above_avg"]:
        dominant = "bull" if bull_score >= bear_score else "bear"
        if dominant == "bull":
            bull_score += 10
        else:
            bear_score += 10
        reasons.append(f"Volume x{volume['ratio']} above average — confirms move")

    # Support/Resistance
    if sr["near_support"]:
        bull_score += 8
        reasons.append("Price near key support — bounce zone")
    elif sr["near_resistance"]:
        bear_score += 8
        reasons.append("Price near key resistance — rejection zone")

    total = bull_score + bear_score
    is_up = bull_score >= bear_score
    dominant_score = max(bull_score, bear_score)
    confidence_raw = (dominant_score / total * 100) if total > 0 else 50

    # Map to realistic range 55–92
    confidence = round(55 + (confidence_raw - 50) * (92 - 55) / 50, 1)
    confidence = max(55.0, min(92.0, confidence))

    # Barriers
    barrier1 = pattern["bullish"] or pattern["bearish"]  # pattern confirmed
    barrier2 = (macd["bullish"] or macd["bearish"]) and not rsi["neutral"]
    barrier3 = confidence >= 68.0

    signal_strength = "STRONG" if confidence >= 80 else ("MODERATE" if confidence >= 68 else "WEAK")

    return {
        "is_up": is_up,
        "direction": "BUY ↑" if is_up else "SELL ↓",
        "confidence": confidence,
        "strength": signal_strength,
        "bull_score": bull_score,
        "bear_score": bear_score,
        "reasons": reasons[:6],
        "barriers": {"barrier1": barrier1, "barrier2": barrier2, "barrier3": barrier3},
        "indicators": {
            "rsi": rsi,
            "macd": {k: v for k, v in macd.items() if k in ("macd","signal","histogram","bullish","bearish")},
            "bollinger": bb,
            "stochastic": stoch,
            "ema": ema_trend,
            "pattern": pattern,
            "volume": volume,
            "support_resistance": sr,
            "atr": round(atr, 6),
        },
        "price": {
            "current": round(closes[-1], 6),
            "change_pct": round((closes[-1] - closes[-2]) / closes[-2] * 100, 4) if len(closes) > 1 else 0,
        },
        "candles_used": len(candles),
        "timestamp": int(time.time()),
    }

# ─────────────────────────────────────────────
#  API Routes
# ─────────────────────────────────────────────

@app.route("/")
def index():
    return jsonify({"status": "JAGUAR SYR Backend v5.1", "uptime": "online"})

@app.route("/health")
def health():
    return jsonify({"status": "ok", "time": datetime.now(timezone.utc).isoformat()})

@app.route("/signal", methods=["GET"])
def get_signal():
    pair      = request.args.get("pair", "EUR/USD")
    timeframe = request.args.get("tf", "1m")

    symbol = PAIR_SYMBOLS.get(pair)
    if not symbol:
        return jsonify({"error": f"Pair '{pair}' not supported"}), 400

    # Map timeframe → Yahoo interval & range
    tf_map = {
        "5s": ("1m","1d"), "10s": ("1m","1d"), "15s": ("1m","1d"),
        "30s": ("1m","1d"), "1m":  ("1m","1d"), "2m":  ("2m","5d"),
        "3m":  ("5m","5d"), "5m":  ("5m","5d"), "15m": ("15m","1mo"),
    }
    interval, range_ = tf_map.get(timeframe, ("1m","1d"))

    candles = fetch_yahoo_candles(symbol, interval, range_)
    if not candles:
        return jsonify({"error": "Failed to fetch market data. Try again."}), 503

    result = generate_signal(candles)
    result["pair"] = pair
    result["timeframe"] = timeframe
    return jsonify(result)

@app.route("/prices", methods=["GET"])
def get_prices():
    pairs  = ["EUR/USD","GBP/USD","USD/JPY","AUD/USD","GBP/JPY","EUR/JPY","USD/CAD","USD/CHF"]
    result = {}
    for pair in pairs:
        symbol = PAIR_SYMBOLS.get(pair)
        if not symbol:
            continue
        candles = fetch_yahoo_candles(symbol, "1m", "1d")
        if candles and len(candles) >= 2:
            c = candles[-1]["close"]
            p = candles[-2]["close"]
            result[pair] = {
                "price": round(c, 5),
                "change_pct": round((c - p) / p * 100, 4),
            }
    return jsonify(result)

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
