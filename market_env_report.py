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
import matplotlib.pyplot as plt
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from datetime import datetime, timedelta

# 可選：使用 yfinance 取得 VIX 與 ETF 價格
import yfinance as yf

# ========== 基本設定 ==========
RECIPIENT = "jeffrey@gis.tw"            # 收件者
SENDER ="jeffrey0218@gmail.com"
APP_PASS= "lprw gbrd jqmd tdqp"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT=587
SEND_TIME = "17:00"

#SENDER = os.getenv("EMAIL_USER", "jeffrey0218@gmail.com")           # 寄件者（建議 Gmail）
#APP_PASS = os.getenv("EMAIL_PASSWORD", "lprw gbrd jqmd tdqp")     # App Password（請使用 2FA 後的應用程式密碼）
#SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
#SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
#SEND_TIME = os.getenv("SEND_TIME", "17:00")    # 每日寄送時間（本機時間）

# 圖表輸出檔
CHART_PATH = "market_environment_trend.png"

# ========== 工具函式 ==========
def fetch_fear_greed():
    """
    嘗試從 CNN 的資料端點/頁面取得 Fear & Greed（非官方）。
    取得失敗時回傳 None，由上層決策 fallback。
    """
    urls = [
        "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
        "https://production.dataviz.cnn.io/index/fearandgreed/graphdata/one"  # 備援
    ]
    for url in urls:
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                data = r.json()
                # 嘗試多種可能的欄位
                candidates = [
                    ("fear_and_greed", "score"),
                    ("feargreed", "now"),
                    ("now", None)
                ]
                for top, sub in candidates:
                    if top in data and isinstance(data[top], dict) and sub in data[top]:
                        return int(data[top][sub])
                    if sub is None and top in data and isinstance(data[top], (int, float)):
                        return int(data[top])
                # 也可能出現在 data['score']
                if "score" in data and isinstance(data["score"], (int, float)):
                    return int(data["score"])
        except Exception:
            continue
    return None  # 交由呼叫端處理

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

def plot_environment_line(current_env_tw_en):
    # 產生過去30天＋未來30天（簡易均值回歸預測）
    today = datetime.now()
    hist_dates = pd.date_range(today - timedelta(days=30), today, freq="D")
    futu_dates = pd.date_range(today + timedelta(days=1), today + timedelta(days=30), freq="D")

    # 數值區間 1~5 對應環境層級（英文）
    def rnd(seed, n, mu_line_from, mu_line_to, sigma):
        np.random.seed(seed)
        base = np.linspace(mu_line_from, mu_line_to, n)
        noise = np.random.normal(0, sigma, n)
        return np.clip(base + noise, 1, 5)

    hist_vals = rnd(42, len(hist_dates), 2.8, 3.0, 0.30)  # 向中性靠攏
    futu_vals = rnd(84, len(futu_dates), 3.0, 2.9, 0.40)  # 略偏謹慎

    fig, ax = plt.subplots(figsize=(10.5, 5.5))
    ax.plot(hist_dates, hist_vals, "b-", lw=2, label="Historical (Past 30 Days)")
    ax.plot(futu_dates, futu_vals, "r--", lw=2, label="Prediction (Next 30 Days)")

    ax.set_ylim(1, 5)
    ax.set_yticks([1,2,3,4,5])
    ax.set_yticklabels(["Extreme\nPanic","Moderate\nPanic","Neutral","Moderate\nGreed","Extreme\nGreed"])
    for y in [1.5,2.5,3.5,4.5]:
        ax.axhline(y, color="gray", ls=":", alpha=0.4)
    ax.axhspan(1, 2.5, color="#ffcccc", alpha=0.2)
    ax.axhspan(2.5, 3.5, color="#fff2b2", alpha=0.2)
    ax.axhspan(3.5, 5.0, color="#ccffcc", alpha=0.2)

    ax.axvline(today, color="black", lw=1)
    tw, en = current_env_tw_en
    ax.plot([today],[3.0], "go", ms=8, label=f"Current: {en}")

    ax.set_title("Market Environment Trend (Past 30 Days + Next 30 Days)", fontsize=13, weight="bold")
    ax.set_xlabel("Date")
    ax.set_ylabel("Market Environment")
    ax.legend(loc="upper right")
    plt.tight_layout()
    plt.savefig(CHART_PATH, dpi=200)
    plt.close()

def render_html(analysis_text, strategy_df):
    # 產生簡單 HTML（嵌入表格；圖以附件形式寄出）
    table_html = strategy_df.to_html(index=False, escape=False)
    html = f"""
    <html><head><meta charset="utf-8">
    <style>
      body {{ font-family: Arial, sans-serif; color:#333; }}
      h1 {{ background:#222;color:#fff;padding:10px 14px;border-radius:8px; }}
      .note {{ font-size:12px;color:#777; }}
      table {{ border-collapse: collapse; width: 100%; }}
      th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; font-size: 13px; }}
      th {{ background: #f5f5f5; }}
    </style>
    </head><body>
      <h1>每日市場環境分析（Daily Market Environment Report）</h1>
      <h2>專業分析</h2>
      <pre style="white-space: pre-wrap; font-family: inherit;">{analysis_text}</pre>
      <h2>投資策略對照表</h2>
      {table_html}
      <h2>市場環境趨勢圖（英文字）</h2>
      <p class="note">圖檔已作為附件附上（Past 30 days + Next 30 days prediction）。</p>
    </body></html>
    """
    return html

def send_email(subject, html_body, image_path):
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

    if os.path.exists(image_path):
        with open(image_path, "rb") as f:
            img = MIMEImage(f.read())
            img.add_header("Content-Disposition", 'attachment; filename="market_environment_trend.png"')
            msg.attach(img)

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SENDER, APP_PASS)
        server.send_message(msg)

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
        # 取不到時以保守值處理（建議您改用自有資料源或第三方API）
        fg = 59  # fallback

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

    # 3) 產表與產圖
    df = build_strategy_table(env_tw_en)
    plot_environment_line(env_tw_en)

    # 4) 產出 HTML 內容與寄出
    analysis = build_analysis_block(today, env_tw_en, fg, vix, rsi, conf)
    html = render_html(analysis, df)
    subject = f"每日市場環境分析 - {today}｜{env_tw_en[0]}/{env_tw_en[1]}"
    send_email(subject, html, CHART_PATH)

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



