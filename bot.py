import requests
import mplfinance as mpf
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
import ccxt
import pandas as pd
import pandas_ta as ta

TOKEN = "***REMOVED***"
last_alerts = {}
active_alert_chats = {}
exchange = ccxt.mexc()

SCAN_PAIRS = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "XRP/USDT",
    "DOGE/USDT",
    "BNB/USDT",
    "ZEC/USDT",
    "LINK/USDT"
]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚀 *Crypto Analysis Bot*\n\n"
        "Commands:\n"
        "/analyze BTC/USDT 4h — Full analysis\n"
        "/chart BTC/USDT 4h — Candlestick chart\n"
        "/scan 4h — Scan top pairs\n"
        "/alerts_on 1d — Auto alerts ON\n"
        "/alerts_off — Auto alerts OFF",
        parse_mode="Markdown"
    )


async def analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /analyze BTC/USDT 4h")
        return

    symbol = context.args[0].upper()
    timeframe = context.args[1]

    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=250)
        df = pd.DataFrame(ohlcv, columns=["time", "open", "high", "low", "close", "volume"])

        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"]
        price = close.iloc[-1]

        # --- Indicators ---
        df["RSI"] = ta.rsi(close, length=14)
        df["MFI"] = ta.mfi(high, low, close, volume, length=14)
        df["CCI"] = ta.cci(high, low, close, length=14)
        df["ATR"] = ta.atr(high, low, close, length=14)
        df["SMA50"] = ta.sma(close, length=50)
        df["EMA20"] = ta.ema(close, length=20)
        df["EMA50"] = ta.ema(close, length=50)
        df["EMA200"] = ta.ema(close, length=200)
        df["MOM"] = ta.mom(close, length=10)

        macd = ta.macd(close)
        df["MACD"] = macd["MACD_12_26_9"]
        df["MACD_SIGNAL"] = macd["MACDs_12_26_9"]

        bbands = ta.bbands(close, length=20, std=2)
        df["BBL"] = bbands.iloc[:, 0]
        df["BBM"] = bbands.iloc[:, 1]
        df["BBU"] = bbands.iloc[:, 2]

        adx = ta.adx(high, low, close, length=14)
        df["ADX"] = adx["ADX_14"]
        df["DMP"] = adx["DMP_14"]
        df["DMN"] = adx["DMN_14"]

        psar = ta.psar(high, low, close)
        df["PSAR"] = psar.iloc[:, 0]

        last = df.iloc[-1]
        support = df["low"].iloc[-50:].min()
        resistance = df["high"].iloc[-50:].max()
        divergence_status = "No Divergence"

        # --- Overall Signal ---
        checks = [
            last["EMA20"] > last["EMA50"],
            price > last["SMA50"],
            last["MOM"] > 0,
            last["MACD"] > last["MACD_SIGNAL"],
            last["DMP"] > last["DMN"],
            price > last["PSAR"]
        ]
        bullish_score = sum(checks)
        bearish_score = len(checks) - bullish_score

        if bullish_score >= 5:
            overall = "Strong Bullish"
        elif bullish_score >= 4:
            overall = "Bullish"
        elif bearish_score >= 5:
            overall = "Strong Bearish"
        elif bearish_score >= 4:
            overall = "Bearish"
        else:
            overall = "Neutral / Mixed"

        # --- Stop Loss / Take Profit ---
        if overall in ["Strong Bullish", "Bullish"]:
            stop_loss = round(support, 4)
            take_profit = round(resistance, 4)
        elif overall in ["Strong Bearish", "Bearish"]:
            stop_loss = round(resistance, 4)
            take_profit = round(support, 4)
        else:
            stop_loss = "N/A"
            take_profit = "N/A"

        # --- TD Sequential ---
        td_buy_count = 0
        td_sell_count = 0
        for i in range(-9, 0):
            if df["close"].iloc[i] < df["close"].iloc[i - 4]:
                td_buy_count += 1
            if df["close"].iloc[i] > df["close"].iloc[i - 4]:
                td_sell_count += 1

        if td_buy_count >= 9:
            td_signal = f"🟢 TD Buy Setup ({td_buy_count})"
        elif td_sell_count >= 9:
            td_signal = f"🔴 TD Sell Setup ({td_sell_count})"
        else:
            td_signal = f"⚪ Neutral ({max(td_buy_count, td_sell_count)})"

        # --- S/R Status ---
        if price <= support * 1.01:
            sr_status = "Near Support"
        elif price >= resistance * 0.99:
            sr_status = "Near Resistance"
        else:
            sr_status = "Between S&R"

        # --- RSI Divergence ---
        recent_price_low = df["close"].iloc[-5:].min()
        previous_price_low = df["close"].iloc[-10:-5].min()
        recent_rsi_low = df["RSI"].iloc[-5:].min()
        previous_rsi_low = df["RSI"].iloc[-10:-5].min()
        recent_price_high = df["close"].iloc[-5:].max()
        previous_price_high = df["close"].iloc[-10:-5].max()
        recent_rsi_high = df["RSI"].iloc[-5:].max()
        previous_rsi_high = df["RSI"].iloc[-10:-5].max()

        if recent_price_low < previous_price_low and recent_rsi_low > previous_rsi_low:
            divergence_status = "🟢 Bullish Divergence"
        elif recent_price_high > previous_price_high and recent_rsi_high < previous_rsi_high:
            divergence_status = "🔴 Bearish Divergence"

        # --- Indicator Statuses ---
        rsi_status = "Overbought" if last["RSI"] > 70 else "Oversold" if last["RSI"] < 30 else "Neutral"
        mfi_status = "Overbought" if last["MFI"] > 80 else "Oversold" if last["MFI"] < 20 else "Neutral"
        sma_status = "Above SMA" if price > last["SMA50"] else "Below SMA"
        ema_status = "Bullish" if last["EMA20"] > last["EMA50"] > last["EMA200"] else "Bearish/Weak"
        mom_status = "Bullish" if last["MOM"] > 0 else "Bearish"
        macd_status = "Bullish" if last["MACD"] > last["MACD_SIGNAL"] else "Bearish"
        adx_status = "Bullish" if last["DMP"] > last["DMN"] else "Bearish"
        psar_status = "Bullish" if price > last["PSAR"] else "Bearish"

        if price >= last["BBU"] * 0.98:
            bb_status = "Near Upper Band"
        elif price <= last["BBL"] * 1.02:
            bb_status = "Near Lower Band"
        else:
            bb_status = "Middle Range"

        # --- Icons ---
        sma_icon = "🟢" if price > last["SMA50"] else "🔴"
        ema_icon = "🟢" if last["EMA20"] > last["EMA50"] > last["EMA200"] else "🔴"
        mom_icon = "🟢" if last["MOM"] > 0 else "🔴"
        macd_icon = "🟢" if last["MACD"] > last["MACD_SIGNAL"] else "🔴"
        adx_icon = "🟢" if last["DMP"] > last["DMN"] else "🔴"
        psar_icon = "🟢" if price > last["PSAR"] else "🔴"

        # --- Funding Rate ---
        funding_rate = "Unavailable"
        funding_bias = "Unavailable"
        try:
            funding_symbol = symbol.replace("/", "_")
            funding_url = f"https://contract.mexc.com/api/v1/contract/funding_rate/{funding_symbol}"
            response = requests.get(funding_url, timeout=10)
            funding_data = response.json()
            if funding_data.get("success"):
                funding_value = float(funding_data["data"]["fundingRate"])
                funding_rate = round(funding_value * 100, 4)
                if funding_value > 0.0003:
                    funding_bias = "🟢 Strong Long Bias"
                elif funding_value > 0:
                    funding_bias = "🟢 Long Bias"
                elif funding_value < -0.0003:
                    funding_bias = "🔴 Strong Short Bias"
                elif funding_value < 0:
                    funding_bias = "🔴 Short Bias"
                else:
                    funding_bias = "⚪ Neutral"
        except Exception as e:
            print("FUNDING ERROR:", e)

        # --- AI Summary ---
        if overall == "Strong Bullish":
            ai_summary = "Buyers are strongly in control. Trend and momentum are bullish."
        elif overall == "Bullish":
            ai_summary = "Market is bullish. Wait for confirmation before entering."
        elif overall == "Strong Bearish":
            ai_summary = "Sellers are dominating. Momentum and trend are bearish."
        elif overall == "Bearish":
            ai_summary = "Market is bearish. Long trades risky until structure improves."
        else:
            ai_summary = "Mixed conditions. Waiting for confirmation may be safer."

        # --- Message ---
        message = (
            f"📊 *{symbol}* on MEXC [{timeframe}]\n\n"
            f"💰 Price: `{price:.4f}` USDT\n"
            f"📉 Support: `{support:.4f}`\n"
            f"📈 Resistance: `{resistance:.4f}`\n"
            f"📍 S/R Status: {sr_status}\n"
            f"📊 Volume: `{last['volume']:.2f}`\n"
            f"🔥 ATR: `{last['ATR']:.4f}`\n"
            f"🎯 Entry: `{price:.4f}` USDT\n"
            f"🛑 Stop Loss: `{stop_loss}`\n"
            f"💰 Take Profit: `{take_profit}`\n\n"
            f"⚪ RSI(14): `{last['RSI']:.2f}` — {rsi_status}\n"
            f"⚪ MFI(14): `{last['MFI']:.2f}` — {mfi_status}\n"
            f"⚪ CCI(14): `{last['CCI']:.2f}`\n"
            f"⚠️ RSI Divergence: {divergence_status}\n"
            f"🔢 TD Sequential: {td_signal}\n"
            f"💸 Funding Rate: {funding_rate}%\n"
            f"💡 Funding Bias: {funding_bias}\n"
            f"⚠️ BBands(20,2): {bb_status}\n\n"
            f"{sma_icon} SMA(50): {sma_status}\n"
            f"{ema_icon} EMA Trend: {ema_status}\n"
            f"{mom_icon} MOM(10): {mom_status}\n"
            f"{macd_icon} MACD: {macd_status}\n"
            f"{adx_icon} ADX Signal: {adx_status}\n"
            f"{psar_icon} Parabolic SAR: {psar_status}\n\n"
            f"🧠 *AI Analysis:*\n{ai_summary}\n\n"
            f"📌 *Overall Signal: {overall}*"
        )

        # --- Inline Buttons ---
        keyboard = [
            [
                InlineKeyboardButton("📊 Chart", callback_data=f"chart|{symbol}|{timeframe}"),
                InlineKeyboardButton("🔍 Scan", callback_data=f"scan|{timeframe}"),
            ],
            [
                InlineKeyboardButton("🚨 Alerts ON", callback_data="alerts_on|1d"),
                InlineKeyboardButton("🛑 Alerts OFF", callback_data="alerts_off"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # --- Send alert if signal changed ---
        alert_message = None
        if overall == "Strong Bullish":
            alert_message = f"🚨 {symbol} [{timeframe}] Strong Bullish Setup"
        elif overall == "Strong Bearish":
            alert_message = f"🚨 {symbol} [{timeframe}] Strong Bearish Setup"
        if "Bullish Divergence" in divergence_status:
            alert_message = f"🚨 {symbol} [{timeframe}] Bullish RSI Divergence"
        elif "Bearish Divergence" in divergence_status:
            alert_message = f"🚨 {symbol} [{timeframe}] Bearish RSI Divergence"
        if "TD Buy Setup" in td_signal:
            alert_message = f"🚨 {symbol} [{timeframe}] TD Buy Setup"
        elif "TD Sell Setup" in td_signal:
            alert_message = f"🚨 {symbol} [{timeframe}] TD Sell Setup"

        if alert_message:
            previous_alert = last_alerts.get(symbol)
            if previous_alert != alert_message:
                last_alerts[symbol] = alert_message
                await update.message.reply_text(alert_message)

        await update.message.reply_text(message, reply_markup=reply_markup, parse_mode="Markdown")

    except Exception as e:
        print("ERROR:", e)
        await update.message.reply_text(f"❌ Error: {str(e)[:300]}")


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split("|")
    action = data[0]

    if action == "chart":
        context.args = [data[1], data[2]]
        await chart(update, context)
    elif action == "scan":
        context.args = [data[1]] if len(data) > 1 else []
        await scan(update, context)
    elif action == "alerts_on":
        context.args = [data[1]] if len(data) > 1 else []
        await alerts_on(update, context)
    elif action == "alerts_off":
        context.args = []
        await alerts_off(update, context)


async def chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /chart BTC/USDT 4h")
        return

    symbol = context.args[0].upper()
    timeframe = context.args[1]

    try:
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=100)
        df = pd.DataFrame(ohlcv, columns=["time", "open", "high", "low", "close", "volume"])
        df["time"] = pd.to_datetime(df["time"], unit="ms")
        df.set_index("time", inplace=True)

        df["EMA20"] = ta.ema(df["close"], length=20)
        df["EMA50"] = ta.ema(df["close"], length=50)

        apds = [
            mpf.make_addplot(df["EMA20"]),
            mpf.make_addplot(df["EMA50"])
        ]

        filename = "chart.png"
        mpf.plot(df, type="candle", style="charles", volume=True, addplot=apds, savefig=filename)

        msg = update.message or update.callback_query.message
        await msg.reply_photo(photo=open(filename, "rb"))

    except Exception as e:
        print("CHART ERROR:", e)
        msg = update.message or update.callback_query.message
        await msg.reply_text(f"❌ {str(e)[:300]}")


async def scan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    timeframe = context.args[0] if len(context.args) > 0 else "4h"
    results = []

    msg = update.message or update.callback_query.message
    await msg.reply_text(f"🔍 Scanning market on {timeframe}...")

    for symbol in SCAN_PAIRS:
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=250)
            df = pd.DataFrame(ohlcv, columns=["time", "open", "high", "low", "close", "volume"])

            close = df["close"]
            high = df["high"]
            low = df["low"]
            price = close.iloc[-1]

            df["SMA50"] = ta.sma(close, length=50)
            df["EMA20"] = ta.ema(close, length=20)
            df["EMA50"] = ta.ema(close, length=50)
            df["EMA200"] = ta.ema(close, length=200)
            df["MOM"] = ta.mom(close, length=10)

            macd = ta.macd(close)
            df["MACD"] = macd["MACD_12_26_9"]
            df["MACD_SIGNAL"] = macd["MACDs_12_26_9"]

            adx = ta.adx(high, low, close, length=14)
            df["DMP"] = adx["DMP_14"]
            df["DMN"] = adx["DMN_14"]

            psar = ta.psar(high, low, close)
            df["PSAR"] = psar.iloc[:, 0]

            last = df.iloc[-1]
            checks = [
                last["EMA20"] > last["EMA50"],
                price > last["SMA50"],
                last["MOM"] > 0,
                last["MACD"] > last["MACD_SIGNAL"],
                last["DMP"] > last["DMN"],
                price > last["PSAR"]
            ]
            bullish_score = sum(checks)
            bearish_score = len(checks) - bullish_score

            if bullish_score >= 5:
                results.append(f"🟢 {symbol} → Strong Bullish")
            elif bearish_score >= 5:
                results.append(f"🔴 {symbol} → Strong Bearish")

        except Exception as e:
            print(f"SCAN ERROR {symbol}:", e)

    if not results:
        await msg.reply_text("No strong setups found right now.")
        return

    await msg.reply_text(f"🔥 TOP SETUPS [{timeframe}]\n\n" + "\n".join(results[:10]))


async def alerts_on(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    allowed_timeframes = ["4h", "1d", "1w"]
    timeframe = context.args[0] if len(context.args) > 0 else "1d"

    msg = update.message or update.callback_query.message

    if timeframe not in allowed_timeframes:
        await msg.reply_text("❌ Allowed timeframes: 4h, 1d, 1w")
        return

    active_alert_chats[chat_id] = timeframe
    await msg.reply_text(f"🚨 Auto alerts turned ON for {timeframe} timeframe.")


async def alerts_off(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in active_alert_chats:
        del active_alert_chats[chat_id]

    msg = update.message or update.callback_query.message
    await msg.reply_text("🛑 Auto alerts turned OFF.")


async def auto_alerts(context):
    for chat_id, timeframe in list(active_alert_chats.items()):
        for symbol in SCAN_PAIRS:
            try:
                ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=250)
                df = pd.DataFrame(ohlcv, columns=["time", "open", "high", "low", "close", "volume"])

                close = df["close"]
                high = df["high"]
                low = df["low"]
                price = close.iloc[-1]

                df["SMA50"] = ta.sma(close, length=50)
                df["EMA20"] = ta.ema(close, length=20)
                df["EMA50"] = ta.ema(close, length=50)
                df["EMA200"] = ta.ema(close, length=200)
                df["MOM"] = ta.mom(close, length=10)

                macd = ta.macd(close)
                df["MACD"] = macd["MACD_12_26_9"]
                df["MACD_SIGNAL"] = macd["MACDs_12_26_9"]

                adx = ta.adx(high, low, close, length=14)
                df["DMP"] = adx["DMP_14"]
                df["DMN"] = adx["DMN_14"]

                psar = ta.psar(high, low, close)
                df["PSAR"] = psar.iloc[:, 0]

                last = df.iloc[-1]
                checks = [
                    last["EMA20"] > last["EMA50"],
                    price > last["SMA50"],
                    last["MOM"] > 0,
                    last["MACD"] > last["MACD_SIGNAL"],
                    last["DMP"] > last["DMN"],
                    price > last["PSAR"]
                ]
                bullish_score = sum(checks)
                bearish_score = len(checks) - bullish_score

                if bullish_score >= 5:
                    overall = "Strong Bullish"
                elif bearish_score >= 5:
                    overall = "Strong Bearish"
                else:
                    continue

                alert_message = f"🚨 {symbol} [{timeframe}] {overall}"
                previous_alert = last_alerts.get(f"{chat_id}_{symbol}")

                if previous_alert != alert_message:
                    last_alerts[f"{chat_id}_{symbol}"] = alert_message
                    await context.bot.send_message(chat_id=chat_id, text=alert_message)

            except Exception as e:
                print(f"AUTO ALERT ERROR {symbol}:", e)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data.split("|")

    action = data[0]

    if action == "chart":
        symbol = data[1]
        timeframe = data[2]

        context.args = [symbol, timeframe]
        await chart(update, context)

    elif action == "scan":
        timeframe = data[1]

        context.args = [timeframe]
        await scan(update, context)

    elif action == "alerts_on":
        timeframe = data[1]

        context.args = [timeframe]
        await alerts_on(update, context)

    elif action == "alerts_off":
        await alerts_off(update, context)


# --- App Setup ---
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("analyze", analyze))
app.add_handler(CommandHandler("chart", chart))
app.add_handler(CommandHandler("scan", scan))
app.add_handler(CommandHandler("alerts_on", alerts_on))
app.add_handler(CommandHandler("alerts_off", alerts_off))
app.add_handler(CallbackQueryHandler(button_handler))
app.job_queue.run_repeating(auto_alerts, interval=300, first=10)

print("Bot running...")
app.run_polling()