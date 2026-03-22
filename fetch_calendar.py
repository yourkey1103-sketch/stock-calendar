"""
股票行事曆自動抓取腳本
每天由 GitHub Actions 執行，結果存成 data/calendar.json
"""

import json
import requests
import datetime
import os
from bs4 import BeautifulSoup
from io import StringIO

# ── 輸出目錄 ──────────────────────────────────────────
os.makedirs("data", exist_ok=True)

today = datetime.date.today()
tw_year = today.year - 1911  # 民國年

events = []  # 所有事件存在這裡


# ══════════════════════════════════════════════════════
# 1. 四巫日（每季第3個週五：3/6/9/12月）
# ══════════════════════════════════════════════════════
def get_witching_days(year):
    witching = []
    for month in [3, 6, 9, 12]:
        # 找當月第3個週五
        d = datetime.date(year, month, 1)
        fridays = [d + datetime.timedelta(days=i)
                   for i in range(31)
                   if (d + datetime.timedelta(days=i)).month == month
                   and (d + datetime.timedelta(days=i)).weekday() == 4]
        if len(fridays) >= 3:
            witching.append({
                "date": fridays[2].isoformat(),
                "title": "🧙 四巫日",
                "category": "美股",
                "source": "計算"
            })
    return witching


events += get_witching_days(today.year)
print(f"✅ 四巫日：找到 {len([e for e in events if '四巫' in e['title']])} 筆")


# ══════════════════════════════════════════════════════
# 2. TWSE OpenAPI — 除權息預告
# ══════════════════════════════════════════════════════
def fetch_twse_exdividend():
    result = []
    try:
        url = "https://openapi.twse.com.tw/v1/announcement/twt48u"
        headers = {"accept": "application/json"}
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        for row in data:
            # 欄位：Code, Name, Date(除息日), CashDividend, StockDividend...
            date_str = row.get("Date", "") or row.get("除息日", "")
            code = row.get("Code", "") or row.get("股票代號", "")
            name = row.get("Name", "") or row.get("公司簡稱", "")
            cash = row.get("CashDividend", "") or row.get("現金股利", "")

            if not date_str:
                continue
            # TWSE 日期格式通常是 YYYYMMDD 或 民國年格式
            try:
                if len(date_str) == 8 and date_str.isdigit():
                    d = datetime.date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:]))
                    date_iso = d.isoformat()
                else:
                    date_iso = date_str
            except Exception:
                date_iso = date_str

            result.append({
                "date": date_iso,
                "title": f"💰 {code} {name} 除息",
                "detail": f"現金股利：{cash}",
                "category": "台股除息",
                "source": "TWSE"
            })
    except Exception as e:
        print(f"⚠️  TWSE 除權息 API 失敗：{e}")
    return result


exdiv = fetch_twse_exdividend()
events += exdiv
print(f"✅ TWSE 除息：找到 {len(exdiv)} 筆")


# ══════════════════════════════════════════════════════
# 3. TWSE OpenAPI — 重大訊息
# ══════════════════════════════════════════════════════
def fetch_twse_news():
    result = []
    try:
        url = "https://openapi.twse.com.tw/v1/announcement/twtann"
        headers = {"accept": "application/json"}
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        for row in data[:50]:  # 只取最新50筆
            date_str = row.get("Date", "") or row.get("date", "")
            code = row.get("Code", "") or row.get("股票代號", "")
            name = row.get("Name", "") or row.get("公司簡稱", "")
            subject = row.get("Subject", "") or row.get("主旨", "") or row.get("title", "")

            if not date_str:
                continue

            try:
                if len(date_str) == 8 and date_str.isdigit():
                    d = datetime.date(int(date_str[:4]), int(date_str[4:6]), int(date_str[6:]))
                    date_iso = d.isoformat()
                else:
                    date_iso = date_str
            except Exception:
                date_iso = date_str

            result.append({
                "date": date_iso,
                "title": f"📢 {code} {name}",
                "detail": subject[:60] if subject else "",
                "category": "台股重訊",
                "source": "TWSE"
            })
    except Exception as e:
        print(f"⚠️  TWSE 重大訊息 API 失敗：{e}")
    return result


news = fetch_twse_news()
events += news
print(f"✅ TWSE 重訊：找到 {len(news)} 筆")


# ══════════════════════════════════════════════════════
# 4. MOPS — 近期法說會
# ══════════════════════════════════════════════════════
def fetch_mops_investor_conf():
    result = []
    try:
        url = "https://mops.twse.com.tw/mops/web/ajax_t100sb01"
        payload = {
            "encodeURIComponent": "1",
            "step": "1",
            "firstin": "1",
            "off": "1",
            "TYPEK": "sii",
            "year": str(tw_year),
            "month": str(today.month).zfill(2),
        }
        headers = {
            "User-Agent": "Mozilla/5.0",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        r = requests.post(url, data=payload, headers=headers, timeout=20)
        r.encoding = "utf-8"
        soup = BeautifulSoup(r.text, "html.parser")
        tables = soup.find_all("table")

        for table in tables:
            rows = table.find_all("tr")
            for row in rows[1:]:
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                if len(cells) >= 5:
                    # 典型欄位：公司代號、公司名稱、辦理日期、地點、主題
                    code = cells[0]
                    name = cells[1]
                    date_str = cells[2]  # 格式通常是 民國年/月/日
                    topic = cells[4] if len(cells) > 4 else ""

                    # 民國日期轉西元
                    try:
                        parts = date_str.replace("年", "/").replace("月", "/").replace("日", "").split("/")
                        if len(parts) == 3:
                            y = int(parts[0]) + 1911
                            m = int(parts[1])
                            d_val = int(parts[2])
                            date_iso = datetime.date(y, m, d_val).isoformat()
                        else:
                            date_iso = date_str
                    except Exception:
                        date_iso = date_str

                    if code and name:
                        result.append({
                            "date": date_iso,
                            "title": f"🎤 {code} {name} 法說會",
                            "detail": topic[:60],
                            "category": "台股法說",
                            "source": "MOPS"
                        })
    except Exception as e:
        print(f"⚠️  MOPS 法說會失敗：{e}")
    return result


conf = fetch_mops_investor_conf()
events += conf
print(f"✅ MOPS 法說會：找到 {len(conf)} 筆")


# ══════════════════════════════════════════════════════
# 5. FMP API — 美股財報日曆（需要 API Key）
# ══════════════════════════════════════════════════════
def fetch_fmp_earnings():
    result = []
    api_key = os.environ.get("FMP_API_KEY", "")
    if not api_key:
        print("⚠️  FMP_API_KEY 未設定，跳過美股財報")
        return result

    try:
        # 抓未來30天的財報
        end_date = (today + datetime.timedelta(days=30)).isoformat()
        url = f"https://financialmodelingprep.com/api/v3/earning_calendar?from={today.isoformat()}&to={end_date}&apikey={api_key}"
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()

        # 只關注重要大型股（可自行修改清單）
        watch_list = {
            "MU": "美光", "NVDA": "輝達", "TSMC": "台積電ADR",
            "AAPL": "蘋果", "MSFT": "微軟", "GOOGL": "Google",
            "META": "Meta", "AMZN": "亞馬遜", "INTC": "英特爾",
            "AMD": "AMD", "QCOM": "高通", "AMAT": "應材",
            "TSM": "台積電ADR", "ASML": "ASML", "SMCI": "超微電腦",
        }

        for item in data:
            symbol = item.get("symbol", "")
            if symbol in watch_list:
                result.append({
                    "date": item.get("date", ""),
                    "title": f"📊 {symbol} {watch_list[symbol]} 財報",
                    "detail": f"預估EPS：{item.get('epsEstimated', 'N/A')}",
                    "category": "美股財報",
                    "source": "FMP"
                })
    except Exception as e:
        print(f"⚠️  FMP 財報失敗：{e}")
    return result


earnings = fetch_fmp_earnings()
events += earnings
print(f"✅ 美股財報：找到 {len(earnings)} 筆")


# ══════════════════════════════════════════════════════
# 6. 重要經濟數據（固定行程，靜態資料）
#    Fed 決議日期每年初公布，這裡放2025年的
# ══════════════════════════════════════════════════════
fed_dates_2025 = [
    "2025-01-29", "2025-03-19", "2025-05-07",
    "2025-06-18", "2025-07-30", "2025-09-17",
    "2025-10-29", "2025-12-10"
]
fed_dates_2026 = [
    "2026-01-28", "2026-03-18", "2026-04-29",
    "2026-06-17", "2026-07-29", "2026-09-16",
    "2026-10-28", "2026-12-09"
]
for d in fed_dates_2025 + fed_dates_2026:
    events.append({
        "date": d,
        "title": "🏦 Fed 利率決議",
        "detail": "FOMC 利率決策公告",
        "category": "總經",
        "source": "Fed"
    })


# ══════════════════════════════════════════════════════
# 整理 & 輸出
# ══════════════════════════════════════════════════════

# 移除空日期、排序
events = [e for e in events if e.get("date")]
events.sort(key=lambda x: x["date"])

# 輸出
output = {
    "updated": today.isoformat(),
    "total": len(events),
    "events": events
}

with open("data/calendar.json", "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f"\n🎉 完成！共 {len(events)} 筆事件 → data/calendar.json")
