import requests
import os
from django.conf import settings

def send_telegram_alert(message):
    """
    Sends a message to the configured Telegram chat.
    Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in settings.
    """
    bot_token = getattr(settings, 'TELEGRAM_BOT_TOKEN', os.environ.get('TELEGRAM_BOT_TOKEN'))
    chat_id = getattr(settings, 'TELEGRAM_CHAT_ID', os.environ.get('TELEGRAM_CHAT_ID'))
    
    if not bot_token or not chat_id:
        print("Telegram Bot Token or Chat ID not configured. Skipping alert.")
        return False
        
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }
    
    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            print("Telegram alert sent successfully.")
            return True
        else:
            print(f"Failed to send Telegram alert: {response.text}")
            return False
    except Exception as e:
        print(f"Exception occurred while sending Telegram alert: {e}")
        return False

def format_alert_message(stock_data):
    """
    Formats the fundamental analysis data into a readable Telegram message.
    """
    symbol = stock_data.get('symbol')
    dcf = stock_data.get('dcf', {})
    relative = stock_data.get('relative', {})
    
    current_price = dcf.get('current_price')
    intrinsic_value = dcf.get('intrinsic_value')
    upside = dcf.get('upside_percent')
    pe_ratio = relative.get('pe_ratio')
    market_pe = relative.get('market_average_pe')
    
    message = (
        f"🚨 <b>STOCK ALERT: {symbol}</b> 🚨\n\n"
        f"<b>Fundamental Setup Detected (Undervalued)</b>\n"
        f"• Current Price: {current_price}\n"
        f"• Intrinsic Value (DCF): {intrinsic_value} (+{upside}% Upside)\n"
        f"• P/E Ratio: {pe_ratio} (Market Avg: {market_pe})\n\n"
        f"💡 Both DCF and Relative Valuation indicate this stock hasn't gone up yet!\n"
    )
    
    return message
