# -*- coding: utf-8 -*-
# market_env_report.py
import os
import io
import json
import time
import math
import smtplib
import requests
import schedule
import numpy as np
import pandas as pd
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from datetime import datetime, timedelta

# 可選：使用 yfinance 取得 VIX 與 ETF 價格
import yfinance as yf

# ========== 基本設定 ==========
RECIPIENT = os.getenv("EMAIL_RECIPIENT","jeffrey@gis.tw,gary@gis.tw")
SENDER = os.getenv("EMAIL_USER","jeffrey0218@gmail.com")
APP_PASS = os.getenv("EMAIL_PASSWORD","lprw gbrd jqmd tdqp")

if not RECIPIENT or not SENDER or not APP_PASS:
    raise RuntimeError("缺少 Email 設定，請設定 EMAIL_RECIPIENT、EMAIL_USER、EMAIL_PASSWORD 環境變數")

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT=587
SEND_TIME = "17:00"

# 快取檔案
FGI_CACHE_PATH = "fear_greed_cache.json"

# ========== 工具函式 ==========
def _save_fgi_cache(val: int):
    try:
        with open(FGI_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump({"value": int(val), "ts": datetime.now().isoformat()}, f, ensure_ascii=False)
    except Exception:
        pass

def _load_fgi_cache():
    try:
        if os.path.exists(FGI_CACHE_PATH):
            with open(FGI_CACHE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return int(data.get("value"))
    except Exception:
        return None
    return None

def fetch_fear_greed():
    """
    嘗試從 CNN 的資料端點/頁面取得 Fear & Greed。
    解析失敗 → 回傳 None；呼叫端自行決策（快取/環境變數）。
    """
    urls = [
        "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
        "https://production.dataviz.cnn.io/index/fearandgreed/graphdata/one"
    ]
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    for url in urls:
        try:
            r = requests.get(url, timeout=12, headers=headers)
            if r.status_code != 200:
                continue
            data = r.json()
            # 常見結構：
            # {"fear_and_greed": {"score": 63.57, "previous_close": 63.14, ...}, "fear_and_greed_historical": {...}}
            val = None
            fa = data.get("fear_and_greed") or data.get("feargreed")
            if isinstance(fa, dict):
                if "score" in fa and isinstance(fa["score"], (int, float)):
                    val = float(fa["score"])
                elif "previous_close" in fa and isinstance(fa["previous_close"], (int, float)):
                    val = float(fa["previous_close"])
            # 後備：歷史序列最後一筆
            if val is None:
                hist = data.get("fear_and_greed_historical", {}) or {}
                d = hist.get("data")
                if isinstance(d, list) and d:
                    last = d[-1]
                    y = last.get("y")
                    if isinstance(y, (int, float)):
                        val = float(y)
            if val is not None:
                val_int = int(round(val))  # 四捨五入成整數
                _save_fgi_cache(val_int)
                return val_int
        except Exception:
            continue
    return None  # 讓上層處理快取/覆蓋

def fetch_vix_last():
    try:
        vix = yf.Ticker("^VIX").history(period="5d")["Close"].dropna()
        return float(vix.iloc[-1])
    except Exception:
        return None

def fetch_rsi(symbol, window=14, lookback="90d"):
    try:
        px = yf.Ticker(symbol).history(period=lookback)["Close"].dropna()
        if len(px) < window + 5:
            return None
        delta = px.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.rolling(window).mean()
        avg_loss = loss.rolling(window).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return float(rsi.dropna().iloc[-1])
    except Exception:
        return None

def classify_environment(fg, vix, avg_rsi):
    """
    依指標分類市場環境（中英雙語）
    """
    # Extreme Panic
    if fg is not None and vix is not None and avg_rsi is not None:
        if fg <= 20 and vix >= 30 and avg_rsi <= 30:
            return ("極度恐慌", "Extreme Panic"), 1.0
        if fg <= 40 and (vix >= 20 or avg_rsi <= 40):
            return ("溫和恐慌", "Moderate Panic"), 0.8
        if fg >= 70 and vix <= 15 and avg_rsi >= 70:
            return ("極度貪婪", "Extreme Greed"), 1.0
        if fg >= 60 and avg_rsi >= 65:
            return ("溫和貪婪", "Moderate Greed"), 0.8
    # 其他情形歸為中性
    return ("中性市場", "Neutral"), 0.7

def fetch_sp500_earnings_calls():
    """
    抓取 S&P 500 成分股未來兩周的財報會議（earnings call）
    使用 yfinance 的 calendar 屬性
    """
    earnings_list = []
    try:
        # 使用常見的大型 S&P 500 成分股列表
        major_sp500_stocks = [
            'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'BRK.B', 'UNH', 'JNJ',
            'V', 'XOM', 'WMT', 'JPM', 'LLY', 'MA', 'PG', 'AVGO', 'HD', 'CVX',
            'MRK', 'ABBV', 'KO', 'COST', 'PEP', 'ADBE', 'TMO', 'BAC', 'CSCO', 'ACN',
            'MCD', 'NFLX', 'ABT', 'LIN', 'NKE', 'CRM', 'DIS', 'DHR', 'VZ', 'WFC',
            'PM', 'CMCSA', 'AMD', 'TXN', 'NEE', 'INTC', 'ORCL', 'COP', 'RTX', 'UPS',
            'QCOM', 'SPGI', 'HON', 'UNP', 'IBM', 'INTU', 'GE', 'AMAT', 'LOW', 'CAT',
            'BA', 'SBUX', 'ELV', 'DE', 'GS', 'BLK', 'PLD', 'MS', 'MDLZ', 'AXP',
            'AMGN', 'BKNG', 'ISRG', 'ADI', 'TJX', 'GILD', 'SYK', 'ADP', 'PFE', 'MMC',
            'CI', 'VRTX', 'C', 'REGN', 'SO', 'ZTS', 'CB', 'DUK', 'NOW', 'PGR',
            'BSX', 'TMUS', 'BDX', 'SCHW', 'MO', 'ETN', 'EOG', 'USB', 'LRCX', 'PANW'
        ]
        
        # 計算未來兩周日期範圍（今天到未來 14 天）
        today = datetime.now().date()
        two_weeks_later = today + timedelta(days=14)
        
        print(f"正在查詢 {len(major_sp500_stocks)} 支 S&P 500 主要成分股的財報會議...")
        
        for symbol in major_sp500_stocks:
            try:
                ticker = yf.Ticker(symbol)
                calendar = ticker.calendar
                
                # calendar 是字典，Earnings Date 是列表
                if isinstance(calendar, dict) and 'Earnings Date' in calendar:
                    earnings_dates = calendar['Earnings Date']
                    if not isinstance(earnings_dates, list):
                        earnings_dates = [earnings_dates]
                    
                    for earnings_date in earnings_dates:
                        if isinstance(earnings_date, (pd.Timestamp, datetime)):
                            earnings_date = earnings_date.date() if hasattr(earnings_date, 'date') else earnings_date
                        
                        if isinstance(earnings_date, type(today)) and today <= earnings_date <= two_weeks_later:
                            company_name = ticker.info.get('longName', symbol)
                            earnings_list.append({
                                'symbol': symbol,
                                'company': company_name,
                                'date': earnings_date.strftime('%Y-%m-%d')
                            })
                            break  # 只取第一個符合的日期
            except Exception:
                continue
                
        # 依日期排序
        earnings_list.sort(key=lambda x: x['date'])
        
    except Exception as e:
        print(f"Error fetching earnings calls: {e}")
    
    return earnings_list

def build_strategy_table(current_env_tw_en):
    tw, en = current_env_tw_en
    rows = [
        ["極度恐慌", "F&G ≤20、VIX ≥30、RSI ≤30", "大幅加碼（3–5成）", "謹慎小額加碼", "穩健加碼", "停損20%／分批進場", ""],
        ["溫和恐慌", "F&G 21–40、Put/Call ≥1.0、跌破均線", "分批加碼（約2成）", "小額分批", "分散投入", "停損15%", ""],
        ["中性市場", "F&G 41–59、RSI 31–69、均線盤整", "持續定期定額", "正常投入", "正常投入", "正常風控10%", ""],
        ["溫和貪婪", "F&G 60–69、RSI ≥70、站上均線", "減少投入", "減少部位", "維持部位", "設停利／逐步減碼", ""],
        ["極度貪婪", "F&G ≥70、VIX ≤15、K值 ≥80", "分批獲利了結", "大幅減碼", "部分獲利", "嚴格停利", ""],
    ]
    df = pd.DataFrame(rows, columns=["市場環境","指標組合條件（範例門檻）","VOO/SPLG操作","QQQ/VOOG操作","VT操作","風險控管","目前市場環境"])
    df.loc[df["市場環境"] == "中性市場", "目前市場環境"] = f"✅（{tw} / {en}）" if tw == "中性市場" else ""
    df.loc[df["市場環境"] == "溫和恐慌", "目前市場環境"] = f"✅（{tw} / {en}）" if tw == "溫和恐慌" else df.loc[df["市場環境"] == "溫和恐慌","目前市場環境"]
    df.loc[df["市場環境"] == "極度恐慌", "目前市場環境"] = f"✅（{tw} / {en}）" if tw == "極度恐慌" else df.loc[df["市場環境"] == "極度恐慌","目前市場環境"]
    df.loc[df["市場環境"] == "溫和貪婪", "目前市場環境"] = f"✅（{tw} / {en}）" if tw == "溫和貪婪" else df.loc[df["市場環境"] == "溫和貪婪","目前市場環境"]
    df.loc[df["市場環境"] == "極度貪婪", "目前市場環境"] = f"✅（{tw} / {en}）" if tw == "極度貪婪" else df.loc[df["市場環境"] == "極度貪婪","目前市場環境"]
    return df

def render_html(analysis_text, strategy_df, earnings_list):
    # 產生簡單 HTML（嵌入表格與財報會議列表）
    table_html = strategy_df.to_html(index=False, escape=False)
    
    # 建立財報會議列表 HTML
    earnings_html = ""
    if earnings_list:
        earnings_html = "<h2>📅 未來兩周 S&P 500 財報會議（Earnings Calls）</h2>"
        earnings_html += "<table><tr><th>日期</th><th>股票代號</th><th>公司名稱</th></tr>"
        for item in earnings_list:
            earnings_html += f"<tr><td>{item['date']}</td><td>{item['symbol']}</td><td>{item['company']}</td></tr>"
        earnings_html += "</table>"
    else:
        earnings_html = "<h2>📅 未來兩周 S&P 500 財報會議</h2><p>目前無財報會議資訊</p>"
    
    html = f"""
    <html><head><meta charset="utf-8">
    <style>
      body {{ font-family: Arial, sans-serif; color:#333; }}
      h1 {{ background:#222;color:#fff;padding:10px 14px;border-radius:8px; }}
      .note {{ font-size:12px;color:#777; }}
      table {{ border-collapse: collapse; width: 100%; margin-bottom: 20px; }}
      th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; font-size: 13px; }}
      th {{ background: #f5f5f5; }}
    </style>
    </head><body>
      <h1>每日市場環境分析（Daily Market Environment Report）</h1>
      <h2>專業分析</h2>
      <pre style="white-space: pre-wrap; font-family: inherit;">{analysis_text}</pre>
      <h2>投資策略對照表</h2>
      {table_html}
      {earnings_html}
    </body></html>
    """
    return html

def send_email(subject, html_body):
    if not SENDER or not APP_PASS:
        raise RuntimeError("請以環境變數 EMAIL_USER / EMAIL_PASSWORD 設定寄件者與密碼（建議 Gmail App Password）。")

    msg = MIMEMultipart("related")
    msg["Subject"] = subject
    msg["From"] = SENDER
    msg["To"] = RECIPIENT

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText("您的郵件用戶端不支援 HTML，請切換至 HTML 檢視。", "plain", "utf-8"))
    alt.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(alt)

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SENDER, APP_PASS)
        # 將收件者字串分割成列表
        recipients = [email.strip() for email in RECIPIENT.split(",")]
        server.send_message(msg, to_addrs=recipients)

def build_analysis_block(date_str, env_tw_en, fg, vix, rsi_dict, conf):
    tw, en = env_tw_en
    lines = []
    lines.append(f"📊 市場環境專業分析 - {date_str}")
    lines.append("")
    lines.append("【當前市場狀況】")
    if fg is not None: lines.append(f"- Fear & Greed Index: {fg}")
    if vix is not None: lines.append(f"- VIX: {vix:.2f}")
    lines.append(f"- 綜合分類：{tw} / {en}（信心度約 {int(conf*100)}%）")
    # RSI數值可顯示或僅敘述在中性區間，避免亂碼與冗長
    lines.append("")
    lines.append("【操作建議（依表格）】")
    if tw == "中性市場":
        lines.append("- 大盤、全球：持續定期定額（正常投入）；科技：正常投入。")
        lines.append("- 風控：維持常規 10%，觀察是否突破關鍵區間。")
    elif tw == "溫和恐慌":
        lines.append("- 逢低分批佈局，留意波動；科技小額試單。風控 15%。")
    elif tw == "極度恐慌":
        lines.append("- 進行較大幅度分批加碼（3–5成），嚴設 20% 停損與分批進場紀律。")
    elif tw == "溫和貪婪":
        lines.append("- 逐步減碼、設停利，科技與高Beta部位降風險。")
    elif tw == "極度貪婪":
        lines.append("- 分批獲利了結，提高停利嚴謹度。")
    lines.append("")
    lines.append("【提醒】市場數據與情緒可能快速變化，請每日留意核心指標。")
    return "\n".join(lines)

def run_once_and_send():
    # 1) 取得資料
    today = datetime.now().strftime("%Y-%m-%d")
    fg = fetch_fear_greed()
    if fg is None:
        # 優先用快取；再看是否有覆蓋；最後仍為 None
        fg = _load_fgi_cache()
        if fg is None:
            fallback_str = os.getenv("FGI_FALLBACK", "").strip()
            try:
                if fallback_str:
                    fg = int(float(fallback_str))
            except Exception:
                fg = None

    vix = fetch_vix_last()
    if vix is None:
        vix = 15.15  # fallback

    # 主要ETF RSI
    rsi = {
        "VOO": fetch_rsi("VOO"),
        "SPLG": fetch_rsi("SPLG"),
        "QQQ": fetch_rsi("QQQ"),
        "VT":  fetch_rsi("VT"),
    }
    # 以可得 RSI 平均
    rsi_vals = [v for v in rsi.values() if isinstance(v, (int, float))]
    avg_rsi = float(np.nanmean(rsi_vals)) if len(rsi_vals) else None

    # 2) 環境分類
    env_tw_en, conf = classify_environment(fg, vix, avg_rsi)

    # 3) 抓取財報會議資訊
    print("正在抓取 S&P 500 財報會議資訊...")
    earnings_list = fetch_sp500_earnings_calls()
    print(f"找到 {len(earnings_list)} 筆財報會議")

    # 4) 產表
    df = build_strategy_table(env_tw_en)

    # 5) 產出 HTML 內容與寄出
    analysis = build_analysis_block(today, env_tw_en, fg, vix, rsi, conf)
    html = render_html(analysis, df, earnings_list)
    subject = f"每日市場環境分析 - {today}｜{env_tw_en[0]}/{env_tw_en[1]}"
    send_email(subject, html)

def main():
    # 立即跑一次
    run_once_and_send()
    # 每日固定時間再跑（若改用系統層級排程，可註解掉以下）
    schedule.every().day.at(SEND_TIME).do(run_once_and_send)
    print(f"排程已啟動，每日 {SEND_TIME} 自動寄送至 {RECIPIENT}。")
    while True:
        schedule.run_pending()
        time.sleep(30)

if __name__ == "__main__":
    main()
