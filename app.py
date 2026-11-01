"""台股查詢 Web App：twstock 股價 + My-TW-Coverage 研究報告整合。"""
import html as htmllib
import json
import os
import re
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests
import twstock
import yfinance as yf
from flask import Flask, jsonify, render_template, request

try:
    import keyring
except ImportError:
    keyring = None


def get_secret(key_name: str) -> str:
    """安全取得金鑰：優先從環境變數讀取，次之從 Windows 系統安全憑證庫 (keyring) 讀取。"""
    val = os.environ.get(key_name)
    if val:
        return val.strip()
    if keyring:
        try:
            stored = keyring.get_password("tw-stock-app", key_name)
            if stored:
                return stored.strip()
        except Exception:
            pass
    return ""

_INTERNAL_COVERAGE = Path(__file__).resolve().parent / "coverage"
_EXTERNAL_COVERAGE = Path(__file__).resolve().parent.parent / "My-TW-Coverage"
COVERAGE_DIR = _INTERNAL_COVERAGE if _INTERNAL_COVERAGE.exists() else _EXTERNAL_COVERAGE
REPORTS_DIR = COVERAGE_DIR / "Pilot_Reports"
CACHE_DIR = Path(__file__).resolve().parent / "cache"
CACHE_DIR.mkdir(exist_ok=True)
T86_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"
TPEX_URL = "https://www.tpex.org.tw/www/zh-tw/insti/dailyTrade"
HOLIDAY_URL = "https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule"
FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"
FINMIND_TOKEN = get_secret("FINMIND_TOKEN")  # 選填：有 token 可提高查詢上限
FINMIND_CACHE_SECONDS = 6 * 3600
CODE_RE = re.compile(r"^[0-9A-Za-z]{4,6}$")

app = Flask(__name__)


def find_report(code: str):
    """依股票代號找出對應的研究報告檔案。限定合法代號格式，防止路徑遍歷。"""
    if not re.fullmatch(r"^[0-9A-Za-z]{4,6}$", code):
        return None
    matches = list(REPORTS_DIR.glob(f"*/{code}_*.md"))
    if not matches:
        return None
    # 確保解析後的路徑必定在 REPORTS_DIR 內
    try:
        resolved = matches[0].resolve()
        if REPORTS_DIR.resolve() in resolved.parents:
            return resolved
    except Exception:
        pass
    return None


def resolve_ticker(query: str):
    """將輸入解析為標準股票代號。支援代號（如 2330、5483）或名稱（如 台積電、中美晶）。"""
    q = query.strip()
    # 1. 直接符合代號 (如 2330, 5483, 0050)
    if q in twstock.codes:
        return q, twstock.codes[q].name

    # 2. 精確匹配名稱（優先普通股票/ETF）
    exact_stocks = [c for c, item in twstock.codes.items() if item.name == q and item.type in ('股票', 'ETF')]
    if exact_stocks:
        return exact_stocks[0], twstock.codes[exact_stocks[0]].name

    exact_all = [c for c, item in twstock.codes.items() if item.name == q]
    if exact_all:
        return exact_all[0], twstock.codes[exact_all[0]].name

    # 3. 模糊匹配名稱（開頭符合或包含，排除權證）
    stock_matches = [
        (c, item.name) for c, item in twstock.codes.items() 
        if item.type in ('股票', 'ETF') and (q in item.name)
    ]
    if stock_matches:
        # 最短名稱或完全包含者優先
        stock_matches.sort(key=lambda x: (len(x[1]), x[0]))
        return stock_matches[0][0], stock_matches[0][1]

    # 4. 若 twstock 沒找到，嘗試在 Pilot_Reports 目錄匹配檔案名稱
    for p in REPORTS_DIR.glob(f"*/*{q}*.md"):
        m = re.match(r"(\d+[A-Z]?)_(.+)\.md", p.name)
        if m:
            return m.group(1), m.group(2)

    return None, None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/quote/<query>")
def quote(query):
    """即時報價（證交所 MIS / yfinance 備援）。支援股票代號或股票名稱。"""
    code, resolved_name = resolve_ticker(query)
    if not code:
        return jsonify(error=f"查無符合「{query}」的股票代號或名稱"), 404

    # 1. 優先嘗試由 twstock (證交所/櫃買中心即時 MIS) 取得盤中行情
    try:
        data = twstock.realtime.get(code)
        if data and data.get("success"):
            rt = data["realtime"]
            info = data["info"]
            return jsonify(
                code=code,
                name=info.get("name") or resolved_name,
                fullname=info.get("fullname"),
                time=info.get("time"),
                price=rt.get("latest_trade_price"),
                open=rt.get("open"),
                high=rt.get("high"),
                low=rt.get("low"),
                volume=rt.get("accumulate_trade_volume"),
                bid=rt.get("best_bid_price", [])[:1],
                ask=rt.get("best_ask_price", [])[:1],
            )
    except Exception:
        pass

    # 2. 備援機制：若是興櫃或非上市櫃盤中連線個股，透過 yfinance 取得最新收盤價
    try:
        for suffix in (".TWO", ".TW"):
            ticker = yf.Ticker(f"{code}{suffix}")
            hist = ticker.history(period="5d")
            if not hist.empty:
                last_row = hist.iloc[-1]
                return jsonify(
                    code=code,
                    name=resolved_name or code,
                    fullname=f"{resolved_name or code} (興櫃/非盤中即時)",
                    time=f"{hist.index[-1].strftime('%Y-%m-%d')} 收盤",
                    price=str(round(float(last_row["Close"]), 2)),
                    open=str(round(float(last_row["Open"]), 2)),
                    high=str(round(float(last_row["High"]), 2)),
                    low=str(round(float(last_row["Low"]), 2)),
                    volume=str(int(last_row["Volume"] // 1000)),
                    bid=["-"],
                    ask=["-"],
                    notice="此個股非上市櫃盤中連線標的（如興櫃），報價以最近交易日收盤價為準。"
                )
    except Exception:
        pass

    # 3. 若無最新報價但有報告或公司名稱，仍回傳基本資訊，讓前端能顯示報告與財務基本面
    if resolved_name or find_report(code):
        return jsonify(
            code=code,
            name=resolved_name or code,
            fullname=f"{resolved_name or code} (無盤中連線報價)",
            time="—",
            price="-",
            open="-",
            high="-",
            low="-",
            volume="-",
            bid=["-"],
            ask=["-"],
            notice="此個股非證交所盤中連線標的，下方已為您載入研究報告與基本面數據。"
        )

    return jsonify(error=f"查無股票即時資料 ({code})"), 404


@app.route("/api/history/<code>")
def history(code):
    """近 31 個交易日歷史股價（twstock / yfinance 雙重備援）。"""
    code = code.strip()
    if not re.fullmatch(r"^[0-9A-Za-z]{4,6}$", code):
        return jsonify(error="股票代號格式不正確"), 400

    # 1. 優先使用 twstock
    try:
        stock = twstock.Stock(code)
        if stock.date:
            return jsonify(
                dates=[d.strftime("%Y-%m-%d") for d in stock.date],
                close=stock.close,
                volume=stock.capacity,
            )
    except Exception:
        pass

    # 2. 備援機制：yfinance (.TWO 或 .TW)
    try:
        for suffix in (".TWO", ".TW"):
            ticker = yf.Ticker(f"{code}{suffix}")
            hist = ticker.history(period="2mo")
            if not hist.empty:
                hist = hist.tail(31)
                return jsonify(
                    dates=[d.strftime("%Y-%m-%d") for d in hist.index],
                    close=[round(float(c), 2) for c in hist["Close"]],
                    volume=[int(v // 1000) for v in hist["Volume"]],
                )
    except Exception:
        pass

    return jsonify(error="查無歷史股價"), 404


@app.route("/api/report/<code>")
def report(code):
    """My-TW-Coverage 研究報告（Markdown 原文）。"""
    path = find_report(code)
    if not path:
        return jsonify(error="My-TW-Coverage 尚無此股票報告"), 404
    return jsonify(sector=path.parent.name, file=path.name,
                   markdown=path.read_text(encoding="utf-8"))


@app.route("/api/search")
def search():
    """關鍵字（wikilink / 題材）反查相關公司。"""
    kw = request.args.get("q", "").strip()
    if not kw:
        return jsonify(results=[])
    results = []
    for path in REPORTS_DIR.glob("*/*.md"):
        text = path.read_text(encoding="utf-8")
        idx = text.find(kw)
        if idx < 0:
            continue
        m = re.match(r"(\d+[A-Z]?)_(.+)\.md", path.name)
        if not m:
            continue
        snippet = text[max(0, idx - 40): idx + 60].replace("\n", " ")
        results.append(dict(code=m.group(1), name=m.group(2),
                            sector=path.parent.name, tagged=f"[[{kw}]]" in text,
                            count=text.count(kw), snippet=snippet))
    results.sort(key=lambda r: (not r["tagged"], -r["count"]))
    return jsonify(keyword=kw, results=results)


def fetch_t86(day: date):
    """取得證交所某日三大法人買賣超（全市場）。結果快取於磁碟；非交易日存為空字典。"""
    key = day.strftime("%Y%m%d")
    cache_file = CACHE_DIR / f"T86_{key}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))
    time.sleep(1.5)  # 避免觸發證交所頻率限制
    resp = requests.get(T86_URL, params={"date": key, "selectType": "ALLBUT0999",
                                         "response": "json"}, timeout=15)
    data = resp.json()
    result = {}
    if data.get("stat") == "OK":
        f = {name: i for i, name in enumerate(data["fields"])}
        to_lot = lambda s: round(int(s.replace(",", "")) / 1000)  # 股 -> 張
        for row in data["data"]:
            result[row[0].strip()] = {
                "foreign": to_lot(row[f["外陸資買賣超股數(不含外資自營商)"]]) + to_lot(row[f["外資自營商買賣超股數"]]),
                "trust": to_lot(row[f["投信買賣超股數"]]),
                "dealer": to_lot(row[f["自營商買賣超股數"]]),
                "total": to_lot(row[f["三大法人買賣超股數"]]),
            }
    elif "沒有符合條件" not in data.get("stat", ""):
        raise RuntimeError(data.get("stat", "證交所回應異常"))
    # 今天的資料可能尚未公布（約 16:30 後），空結果不快取
    if result or day < date.today():
        cache_file.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


def fetch_tpex(day: date):
    """取得櫃買中心某日三大法人買賣超（上櫃全市場）。快取規則同 fetch_t86。"""
    key = day.strftime("%Y%m%d")
    cache_file = CACHE_DIR / f"TPEX_{key}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))
    time.sleep(1.0)
    resp = requests.get(TPEX_URL, params={"type": "Daily", "sect": "EW", "response": "json",
                                          "date": day.strftime("%Y/%m/%d")}, timeout=15)
    data = resp.json()
    result = {}
    tables = data.get("tables") or []
    if tables and tables[0].get("data"):
        to_lot = lambda s: round(int(str(s).replace(",", "")) / 1000)
        # 欄位：2-4 外資(不含自營) 5-7 外資自營 8-10 外資合計 11-13 投信
        #       14-16 自營(自行) 17-19 自營(避險) 20-22 自營合計 23 三大法人合計
        for row in tables[0]["data"]:
            result[row[0].strip()] = {"foreign": to_lot(row[10]), "trust": to_lot(row[13]),
                                      "dealer": to_lot(row[22]), "total": to_lot(row[23])}
    if result or day < date.today():
        cache_file.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


@app.route("/api/institutional/<code>")
def institutional(code):
    """個股近 N 個交易日三大法人買賣超（單位：張）。上市用證交所、上櫃用櫃買中心。"""
    code = code.strip()
    if not re.fullmatch(r"^[0-9A-Za-z]{4,6}$", code):
        return jsonify(error="股票代號格式不正確"), 400
    try:
        raw_days = int(request.args.get("days", 20))
        days = max(1, min(raw_days, 60))
    except (ValueError, TypeError):
        days = 20
    rows, day, tries, fetcher, market_name = [], date.today(), 0, None, None
    try:
        while len(rows) < days and tries < days * 2 + 10:
            tries += 1
            if day.weekday() < 5:
                if fetcher is None:  # 第一個有資料的交易日決定上市或上櫃
                    twse = fetch_t86(day)
                    if not twse:
                        day -= timedelta(days=1)
                        continue
                    if code in twse:
                        fetcher, market_name = fetch_t86, "上市（證交所）"
                    elif code in fetch_tpex(day):
                        fetcher, market_name = fetch_tpex, "上櫃（櫃買中心）"
                    else:
                        return jsonify(error="查無此股票的三大法人資料"), 404
                market = fetcher(day)
                if market:
                    rec = market.get(code, {"foreign": 0, "trust": 0, "dealer": 0, "total": 0})
                    rows.append({"date": day.isoformat(), **rec})
            day -= timedelta(days=1)
    except Exception as e:  # noqa: BLE001
        if not rows:
            return jsonify(error=f"資料取得失敗：{e}"), 502
    rows.reverse()
    return jsonify(code=code, market=market_name, rows=rows)


# ---------- 期貨／選擇權結算日 ----------

_holiday_cache = {}


def closed_days(year: int):
    """證交所休市日（含「僅辦理結算交割」的無交易日）。"""
    if year in _holiday_cache:
        return _holiday_cache[year]
    days = set()
    try:
        data = requests.get(HOLIDAY_URL, params={"response": "json", "queryYear": year - 1911},
                            timeout=15).json()
        for d, name, *_ in data.get("data", []):
            if d.startswith(str(year)) and "開始交易" not in name and "最後交易" not in name:
                days.add(date.fromisoformat(d))
    except Exception:  # noqa: BLE001
        pass
    _holiday_cache[year] = days
    return days


def is_trading(d: date):
    return d.weekday() < 5 and d not in closed_days(d.year)


def next_trading(d: date):
    while not is_trading(d):
        d += timedelta(days=1)
    return d


def third_wednesday(y, m):
    first = date(y, m, 1)
    return first + timedelta(days=(2 - first.weekday()) % 7 + 14)


def second_last_trading(y, m):
    d = (date(y + (m == 12), m % 12 + 1, 1)) - timedelta(days=1)
    found = 0
    while True:
        if is_trading(d):
            found += 1
            if found == 2:
                return d
        d -= timedelta(days=1)


@app.route("/api/settlement")
def settlement():
    """結算日查詢：週三/週五週選、月結算（臺指期/選）、富時台灣（摩台）結算（支援過去 45 天與未來 N 天）。"""
    try:
        raw_days = int(request.args.get("days", 60))
        days = max(7, min(raw_days, 180))
    except (ValueError, TypeError):
        days = 60
    try:
        raw_past = int(request.args.get("past_days", 45))
        past_days = max(0, min(raw_past, 90))
    except (ValueError, TypeError):
        past_days = 45

    today = date.today()
    start_date = today - timedelta(days=past_days)
    end = today + timedelta(days=days)
    events = {}

    def add(raw: date, kind: str):
        d = next_trading(raw)  # 遇休市順延至次一交易日
        if start_date <= d <= end:
            note = f"（原 {raw.strftime('%m/%d')} 休市順延）" if d != raw else ""
            events.setdefault(d, []).append(kind + note)

    months = set()
    y, m = start_date.year, start_date.month
    while (y, m) <= (end.year, end.month):
        months.add((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)

    monthly = {third_wednesday(y, m) for y, m in months}
    for y, m in months:
        add(third_wednesday(y, m), "月結算（臺指期／臺指選）")
        sgx = second_last_trading(y, m)
        if start_date <= sgx <= end:
            events.setdefault(sgx, []).append("富時台灣結算（SGX 摩台，原 MSCI 摩台）")

    d = start_date
    while d <= end:
        if d.weekday() == 2 and d not in monthly:
            add(d, "週三週選結算")
        if d.weekday() == 4:
            add(d, "週五週選結算")
        d += timedelta(days=1)
    weekday = "一二三四五六日"
    result = [{"date": d.isoformat(), "weekday": weekday[d.weekday()], "days_left": (d - today).days,
               "events": evs} for d, evs in sorted(events.items())]
    return jsonify(today=today.isoformat(), events=result,
                   holiday_known=bool(closed_days(end.year)))


_last_update_time = 0


# ---------- FinMind 基本面 ----------

def finmind(dataset: str, code: str, start: date):
    """呼叫 FinMind API，結果快取在磁碟 6 小時。"""
    cache_file = CACHE_DIR / f"FM_{dataset}_{code}_{start.isoformat()}.json"
    if cache_file.exists() and time.time() - cache_file.stat().st_mtime < FINMIND_CACHE_SECONDS:
        return json.loads(cache_file.read_text(encoding="utf-8"))
    params = {"dataset": dataset, "data_id": code, "start_date": start.isoformat()}
    headers = {"Authorization": f"Bearer {FINMIND_TOKEN}"} if FINMIND_TOKEN else {}
    resp = requests.get(FINMIND_URL, params=params, headers=headers, timeout=20).json()
    if resp.get("status") != 200:
        raise RuntimeError(resp.get("msg", "FinMind 回應異常"))
    data = resp.get("data", [])
    cache_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


@app.route("/api/fundamentals/<code>")
def fundamentals(code):
    """FinMind 基本面：月營收、季 EPS、股利、本益比/淨值比、新聞。"""
    code = code.strip()
    if not CODE_RE.fullmatch(code):
        return jsonify(error="股票代號格式不正確"), 400
    today = date.today()
    out, errors = {"code": code}, []

    # 月營收（抓 25 個月以計算年增率，回傳最近 13 個月）
    try:
        rev = finmind("TaiwanStockMonthRevenue", code, date(today.year - 2, today.month, 1))
        by_ym = {(r["revenue_year"], r["revenue_month"]): r["revenue"] for r in rev}
        rows = []
        for r in rev:
            y, m, v = r["revenue_year"], r["revenue_month"], r["revenue"]
            prev_y = by_ym.get((y - 1, m))
            prev_m = by_ym.get((y, m - 1) if m > 1 else (y - 1, 12))
            rows.append({"ym": f"{y}-{m:02d}", "revenue": round(v / 1e8, 2),  # 億元
                         "yoy": round((v / prev_y - 1) * 100, 1) if prev_y else None,
                         "mom": round((v / prev_m - 1) * 100, 1) if prev_m else None})
        out["revenue"] = rows[-13:]
    except Exception as e:  # noqa: BLE001
        errors.append(f"月營收：{e}")

    # 季 EPS（近 8 季）
    try:
        fs = finmind("TaiwanStockFinancialStatements", code, date(today.year - 2, 1, 1))
        eps = [{"quarter": f"{x['date'][:4]}Q{(int(x['date'][5:7]) - 1) // 3 + 1}", "eps": x["value"]}
               for x in fs if x["type"] == "EPS"]
        out["eps"] = eps[-8:]
    except Exception as e:  # noqa: BLE001
        errors.append(f"EPS：{e}")

    # 股利（近 3 年）
    try:
        div = finmind("TaiwanStockDividend", code, date(today.year - 3, 1, 1))
        out["dividends"] = [{
            "period": x["year"],
            "cash": round(x["CashEarningsDistribution"] + x["CashStatutorySurplus"], 4),
            "stock": round(x["StockEarningsDistribution"] + x["StockStatutorySurplus"], 4),
            "ex_date": x["CashExDividendTradingDate"] or x["StockExDividendTradingDate"],
            "pay_date": x["CashDividendPaymentDate"],
        } for x in div][::-1]
    except Exception as e:  # noqa: BLE001
        errors.append(f"股利：{e}")

    # 本益比 / 淨值比 / 殖利率（近 1 年）
    try:
        per = finmind("TaiwanStockPER", code, today - timedelta(days=365))
        out["per"] = [{"date": x["date"], "per": x["PER"], "pbr": x["PBR"],
                       "yield": x["dividend_yield"]} for x in per]
    except Exception as e:  # noqa: BLE001
        errors.append(f"本益比：{e}")

    out["errors"] = errors
    return jsonify(out)


# ---------- 財報日 / 法說會（公開資訊觀測站 MOPS） ----------

MOPS_BASE = "https://mopsov.twse.com.tw/mops/web/"
_last_mops_call = 0.0


def mops_rows(page: str, data: dict):
    """查詢 MOPS 舊版頁面並把 HTML 表格解析成 list[list[str]]。"""
    global _last_mops_call
    wait = 1.2 - (time.time() - _last_mops_call)  # MOPS 對頻繁查詢會封鎖，保持間隔
    if wait > 0:
        time.sleep(wait)
    _last_mops_call = time.time()
    resp = requests.post(MOPS_BASE + page, headers={"User-Agent": "Mozilla/5.0"}, timeout=20,
                         data={"encodeURIComponent": "1", "step": "1", "firstin": "1", "off": "1", **data})
    resp.encoding = "utf-8"
    if "FOR SECURITY REASONS" in resp.text.upper() or "查詢過於頻繁" in resp.text:
        raise RuntimeError("公開資訊觀測站暫時限制查詢，請稍後再試")
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", resp.text, re.S):
        cells = [re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", c))).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S)]
        if cells:
            rows.append(cells)
    return rows


def cached_mops(name: str, ttl, fetch):
    """ttl=None 表示永久快取（已過去的月份/年度）。空結果不快取。"""
    f = CACHE_DIR / f"MOPS_{name}.json"
    if f.exists() and (ttl is None or time.time() - f.stat().st_mtime < ttl):
        return json.loads(f.read_text(encoding="utf-8"))
    rows = fetch()
    if rows:
        f.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return rows


def roc_to_date(s: str):
    """'115/11/26' 或 '115/11/17 至 115/11/18' -> date(2026, 11, 26)"""
    m = re.search(r"(\d{2,3})/(\d{1,2})/(\d{1,2})", s or "")
    if not m:
        return None
    try:
        return date(int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def parse_date_in_text(s: str):
    """從公告主旨抓日期，例如 '115/11/10'、'115年11月10日'、'11月10日'。"""
    m = re.search(r"(\d{2,4})\s*[/年]\s*(\d{1,2})\s*[/月]\s*(\d{1,2})", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y = y + 1911 if y < 1911 else y
    else:
        m = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日", s)
        if not m:
            return None
        y, mo, d = date.today().year, int(m.group(1)), int(m.group(2))
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def report_label(subject: str):
    """從主旨判斷是哪一期財報。"""
    m = re.search(r"(\d{2,3})\s*年度?\s*第?\s*([一二三四1-4])\s*季", subject)
    if m:
        q = "一二三四".find(m.group(2)) + 1 if m.group(2) in "一二三四" else int(m.group(2))
        return f"{int(m.group(1)) + 1911} Q{q}"
    m = re.search(r"(\d{2,3})\s*年(度)?(上半年|半年)", subject)
    if m:
        return f"{int(m.group(1)) + 1911} 半年報"
    m = re.search(r"(\d{2,3})\s*年度", subject)
    if m:
        return f"{int(m.group(1)) + 1911} 年報"
    return "財務報告"


# 法定截止日：(截止月, 截止日, 對應的財報期末月, 期末日, 年度偏移)
LEGAL_DEADLINES = [(3, 31, 12, 31, -1, "年報"), (5, 15, 3, 31, 0, "Q1"),
                   (8, 14, 6, 30, 0, "Q2"), (11, 14, 9, 30, 0, "Q3")]


def next_legal_deadline(today: date, past_reports: list):
    """下一個「尚未公布」那期財報的法定截止日。"""
    released_dates = [date.fromisoformat(p["date"]) for p in past_reports]
    for yr in (today.year, today.year + 1):
        for dm, dd, pm, pd, yoff, label in LEGAL_DEADLINES:
            deadline, period_end = date(yr, dm, dd), date(yr + yoff, pm, pd)
            if deadline >= today and not any(d > period_end for d in released_dates):
                return deadline, f"{period_end.year} {label}"
    return None, None


@app.route("/api/events/<code>")
def events(code):
    """個股財報日與法說會：未來事件、過去財報日、過去法說日。"""
    code = code.strip()
    if not CODE_RE.fullmatch(code):
        return jsonify(error="股票代號格式不正確"), 400
    info = twstock.codes.get(code)
    typek = "otc" if info and info.market == "上櫃" else "sii"
    today = date.today()
    errors, upcoming, past_reports, past_confs = [], [], [], []

    # 1) 重大訊息：董事會通過財報（過去） / 預計召開董事會審議財報（未來）
    for roc_year in (today.year - 1911 - 1, today.year - 1911):
        ttl = None if roc_year < today.year - 1911 else 6 * 3600
        try:
            rows = cached_mops(f"t05st01_{code}_{roc_year}", ttl,
                               lambda y=roc_year: mops_rows("ajax_t05st01", {"TYPEK": "all", "year": str(y), "co_id": code}))
        except Exception as e:  # noqa: BLE001
            errors.append(f"重大訊息：{e}")
            continue
        for r in rows:
            if len(r) < 5 or r[0] != code:
                continue
            ann_date, subject = roc_to_date(r[2]), r[4]
            if not ann_date or "財務報" not in subject or "董事會" not in subject:
                continue
            if any(k in subject for k in ("預計", "召開日期", "將於", "擬於")):
                meet = parse_date_in_text(subject)
                if meet and meet >= today:
                    upcoming.append({"date": meet.isoformat(), "type": "財報（董事會）",
                                     "title": subject, "note": f"{ann_date.isoformat()} 公告"})
            elif any(k in subject for k in ("通過", "決議", "承認")):
                past_reports.append({"date": ann_date.isoformat(), "time": r[3][:5],
                                     "period": report_label(subject), "title": subject})
    past_reports.sort(key=lambda x: x["date"], reverse=True)

    # 2) 法說會：過去 12 個月 + 未來 2 個月（每月一次全市場查詢，全站共用快取）
    months, y, m = [], today.year, today.month
    for _ in range(12):
        m, y = (12, y - 1) if m == 1 else (m - 1, y)
    for _ in range(15):
        months.append((y, m))
        m, y = (1, y + 1) if m == 12 else (m + 1, y)
    for y, m in months:
        past_month = (y, m) < (today.year, today.month)
        try:
            rows = cached_mops(f"t100sb02_{typek}_{y}{m:02d}", None if past_month else 6 * 3600,
                               lambda y=y, m=m: mops_rows("ajax_t100sb02_1",
                                                          {"TYPEK": typek, "year": str(y - 1911), "month": f"{m:02d}"}))
        except Exception as e:  # noqa: BLE001
            errors.append(f"法說會 {y}/{m:02d}：{e}")
            continue
        for r in rows:
            if len(r) < 6 or r[0] != code:
                continue
            d = roc_to_date(r[2])
            if not d:
                continue
            item = {"date": d.isoformat(), "time": r[3], "place": r[4], "title": r[5],
                    "range": r[2] if "至" in r[2] else ""}
            if d >= today:
                upcoming.append({**item, "type": "法說會"})
            else:
                past_confs.append(item)
    past_confs = sorted({(c["date"], c["title"]): c for c in past_confs}.values(),
                        key=lambda x: x["date"], reverse=True)

    # 3) 若沒有已公告的財報董事會日期，補上下一個法定截止日（估計）
    if not any(u["type"].startswith("財報") for u in upcoming):
        deadline, label = next_legal_deadline(today, past_reports)
        if deadline:
            upcoming.append({"date": deadline.isoformat(), "type": "財報截止（法定）",
                             "title": f"{label} 財報法定公告截止日",
                             "note": "尚未公告董事會日期，實際公布通常在截止日前"})

    upcoming.sort(key=lambda x: x["date"])
    for u in upcoming:
        u["days_left"] = (date.fromisoformat(u["date"]) - today).days
    return jsonify(code=code, market=typek, upcoming=upcoming,
                   past_reports=past_reports, past_conferences=past_confs, errors=errors)

FMP_API_KEY = get_secret("FMP_API_KEY")
FMP_MAG7_CACHE = CACHE_DIR / "fmp_mag7_cache.json"
FMP_CACHE_TTL = 3 * 86400  # 快取 3 天 (72 小時)，節省 FMP API 額度
MAG7_MAP = {
    "AAPL": "蘋果 (Apple)",
    "MSFT": "微軟 (Microsoft)",
    "GOOGL": "Alphabet (Google)",
    "AMZN": "亞馬遜 (Amazon)",
    "NVDA": "輝達 (NVIDIA)",
    "META": "Meta (臉書)",
    "TSLA": "特斯拉 (Tesla)",
    "AMD": "超微 (AMD)",
    "QCOM": "高通 (Qualcomm)",
    "LITE": "朗美通 (Lumentum)",
}
MAG7_SEARCH_QUERIES = {
    "AAPL": "stock:apple",
    "MSFT": "stock:microsoft",
    "GOOGL": "stock:alphabet",
    "AMZN": "stock:amazon",
    "NVDA": "stock:nvidia",
    "META": "stock:meta",
    "TSLA": "stock:tesla",
    "AMD": "stock:amd",
    "QCOM": "stock:qualcomm",
    "LITE": "stock:lumentum",
}
MAG7_PRICE_CACHE = CACHE_DIR / "mag7_price_cache.json"
MAG7_PRICE_TTL = 15 * 60  # 股價快取 15 分鐘


def _fetch_mag7_prices():
    """批次抓取 Mag 7 股票最新收盤價及漲跌（15 分鐘快取）。"""
    now_ts = time.time()
    if MAG7_PRICE_CACHE.exists():
        try:
            cached = json.loads(MAG7_PRICE_CACHE.read_text(encoding="utf-8"))
            if now_ts - cached.get("updated_at", 0) < MAG7_PRICE_TTL:
                return cached.get("prices", {})
        except Exception:
            pass

    prices = {}
    try:
        symbols = list(MAG7_MAP.keys())
        df = yf.download(symbols, period="2d", interval="1d", progress=False)
        close_df = df.get("Close")
        if close_df is not None:
            for sym in symbols:
                if sym in close_df.columns:
                    s = close_df[sym].dropna()
                    if len(s) >= 1:
                        last = round(float(s.iloc[-1]), 2)
                        prev = round(float(s.iloc[-2]), 2) if len(s) >= 2 else last
                        chg = round(last - prev, 2)
                        pct = round((chg / prev) * 100, 2) if prev else 0.0
                        prices[sym] = {"price": last, "change": chg, "pct": pct}
        if prices:
            MAG7_PRICE_CACHE.write_text(json.dumps({
                "updated_at": now_ts,
                "prices": prices
            }, ensure_ascii=False), encoding="utf-8")
            return prices
    except Exception as e:
        print(f"Mag 7 股價抓取失敗: {e}")

    if MAG7_PRICE_CACHE.exists():
        try:
            return json.loads(MAG7_PRICE_CACHE.read_text(encoding="utf-8")).get("prices", {})
        except Exception:
            pass
    return prices

WEEKDAY_ZH = ["一", "二", "三", "四", "五", "六", "日"]


def _get_mag7_tw_time(us_date_str: str):
    """將美股 Mag 7 財報日 (美東盤後 AMC) 轉換為台灣時間。"""
    try:
        d = date.fromisoformat(us_date_str)
        d_tw = d + timedelta(days=1)
        wk = WEEKDAY_ZH[d_tw.weekday()]
        # 2026 年美東夏令時間至 2026-11-01 截止
        is_dst = d < date(2026, 11, 1)
        tw_hour = "04:00~05:00 清晨" if is_dst else "05:00~06:00 清晨"
        return f"{d_tw.month:02d}/{d_tw.day:02d} ({wk}) {tw_hour}", f"{d.month:02d}/{d.day:02d} 盤後"
    except Exception:
        return "", ""


US_MACRO_SCHEDULE = [
    {
        "date": "2026-10-02",
        "event": "美國 9 月非農就業報告 (NFP) / 失業率",
        "impact": "high",
        "tw_time": "10/02 (五) 20:30 晚上",
        "us_time": "10/02 08:30 美東",
    },
    {
        "date": "2026-10-10",
        "event": "美國 9 月 CPI 消費者物價指數",
        "impact": "high",
        "tw_time": "10/10 (六) 20:30 晚上",
        "us_time": "10/10 08:30 美東",
    },
    {
        "date": "2026-10-28",
        "event": "FOMC 利率決議及政策聲明 / 鮑爾記者會",
        "impact": "high",
        "tw_time": "10/29 (四) 02:00 凌晨",
        "us_time": "10/28 14:00 美東",
    },
    {
        "date": "2026-10-30",
        "event": "美國 9 月核心 PCE 物價指數 (年率/月率)",
        "impact": "high",
        "tw_time": "10/30 (五) 20:30 晚上",
        "us_time": "10/30 08:30 美東",
    },
    {
        "date": "2026-11-03",
        "event": "🇺🇸 2026 美國期中選舉投票日 (參眾議院全面改選)",
        "impact": "high",
        "tw_time": "11/04 (三) 早上陸續開票",
        "us_time": "11/03 全日投票",
    },
    {
        "date": "2026-11-06",
        "event": "美國 10 月非農就業報告 (NFP) / 失業率",
        "impact": "high",
        "tw_time": "11/06 (五) 21:30 晚上",
        "us_time": "11/06 08:30 美東",
    },
    {
        "date": "2026-11-13",
        "event": "美國 10 月 CPI 消費者物價指數",
        "impact": "high",
        "tw_time": "11/13 (五) 21:30 晚上",
        "us_time": "11/13 08:30 美東",
    },
    {
        "date": "2026-11-18",
        "event": "FOMC 10 月會議紀要發布",
        "impact": "medium",
        "tw_time": "11/19 (四) 03:00 凌晨",
        "us_time": "11/18 14:00 美東",
    },
    {
        "date": "2026-11-26",
        "event": "美國感恩節 (美股休市一天)",
        "impact": "medium",
        "tw_time": "11/26 (四) 全日休市",
        "us_time": "11/26 全日休市",
    },
    {
        "date": "2026-12-09",
        "event": "FOMC 利率決議與經濟預測摘要 (SEP)",
        "impact": "high",
        "tw_time": "12/10 (四) 03:00 凌晨",
        "us_time": "12/09 14:00 美東",
    },
]


@app.route("/api/us-market")
def us_market():
    """美股重大宏觀財經事件 + 七巨頭 (Mag 7) 最新財報日程（磁碟快取與異常降級保護）。"""
    today = date.today()
    now_ts = time.time()

    # 1. 讀取現有磁碟快取
    raw_mag7 = []
    cache_ts = 0
    if FMP_MAG7_CACHE.exists():
        try:
            cached_data = json.loads(FMP_MAG7_CACHE.read_text(encoding="utf-8"))
            raw_mag7 = cached_data.get("events", [])
            cache_ts = cached_data.get("updated_at", 0)
        except Exception:
            raw_mag7 = []

    # 2. 若快取過期 (超過 3 天) 或尚未有快取，且有 API KEY，嘗試向 FMP 查詢更新
    is_expired = (now_ts - cache_ts > FMP_CACHE_TTL)
    if (is_expired or not raw_mag7) and FMP_API_KEY:
        try:
            start_str = (today - timedelta(days=7)).isoformat()
            end_str = (today + timedelta(days=45)).isoformat()
            url = f"https://financialmodelingprep.com/stable/earnings-calendar?from={start_str}&to={end_str}&apikey={FMP_API_KEY}"
            resp = requests.get(url, timeout=12).json()
            if isinstance(resp, list):
                new_events = []
                for item in resp:
                    sym = item.get("symbol")
                    if sym in MAG7_MAP:
                        new_events.append({
                            "symbol": sym,
                            "name": MAG7_MAP[sym],
                            "date": item.get("date"),
                            "eps_est": item.get("epsEstimated"),
                            "rev_est_b": round(item.get("revenueEstimated") / 1e9, 1) if item.get("revenueEstimated") else None,
                        })
                if new_events:
                    raw_mag7 = new_events
                    FMP_MAG7_CACHE.write_text(json.dumps({
                        "updated_at": now_ts,
                        "events": raw_mag7
                    }, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass  # API 達到上限、網路問題或 429 時，直接降級使用既有快取，絕不噴錯或重複請求

    # 補充：若部分焦點權值股 (如 QCOM, LITE) 尚未在 FMP 財報日曆中出現，透過 yfinance 官方日程補充
    existing_syms = {item.get("symbol") for item in raw_mag7}
    for sym in ["AMD", "QCOM", "LITE"]:
        if sym in MAG7_MAP and sym not in existing_syms:
            try:
                t = yf.Ticker(sym)
                cal = t.calendar
                ed = cal.get("Earnings Date") if isinstance(cal, dict) else None
                if ed:
                    d = ed[0] if isinstance(ed, list) else ed
                    if hasattr(d, "date"):
                        d = d.date()
                    rev_avg = cal.get("Revenue Average")
                    eps_avg = cal.get("Earnings Average")
                    raw_mag7.append({
                        "symbol": sym,
                        "name": MAG7_MAP[sym],
                        "date": d.isoformat(),
                        "eps_est": round(float(eps_avg), 2) if eps_avg else None,
                        "rev_est_b": round(float(rev_avg) / 1e9, 1) if rev_avg else None,
                    })
                    existing_syms.add(sym)
            except Exception:
                pass

    # 3. 取得美股焦點科技股即時/收盤股價與動態計算剩餘天數
    prices_map = _fetch_mag7_prices()
    mag7_events = []
    for item in raw_mag7:
        d_str = item.get("date")
        if not d_str:
            continue
        diff = (date.fromisoformat(d_str) - today).days
        if diff >= -35:
            tw_time, us_time = _get_mag7_tw_time(d_str)
            sym = item.get("symbol", "")
            px_data = prices_map.get(sym)
            search_query = MAG7_SEARCH_QUERIES.get(sym, f"stock:{sym.lower()}")
            mag7_events.append({
                **item,
                "days_left": diff,
                "tw_time": tw_time,
                "us_time": us_time,
                "price": px_data.get("price") if px_data else None,
                "change": px_data.get("change") if px_data else None,
                "pct": px_data.get("pct") if px_data else None,
                "google_url": f"https://www.google.com/search?q={search_query}",
            })
    mag7_events.sort(key=lambda x: x["date"])

    # 4. 宏觀重大財經事件 (含近 35 天已發生及未來 35 天)
    macro_events = []
    for item in US_MACRO_SCHEDULE:
        d = date.fromisoformat(item["date"])
        diff = (d - today).days
        if -35 <= diff <= 35:
            macro_events.append({
                "date": item["date"],
                "event": item["event"],
                "impact": item["impact"],
                "tw_time": item.get("tw_time", ""),
                "us_time": item.get("us_time", ""),
                "days_left": diff,
            })
    macro_events.sort(key=lambda x: x["date"])

    return jsonify(
        today=today.isoformat(),
        mag7=mag7_events,
        macro=macro_events,
        cached=(now_ts - cache_ts <= FMP_CACHE_TTL) and bool(raw_mag7)
    )


FRED_API_KEY = get_secret("FRED_API_KEY")
FRED_CACHE_FILE = CACHE_DIR / "fred_liquidity_cache.json"
FRED_CACHE_TTL = 12 * 3600  # 12 小時快取


@app.route("/api/global-m2")
def global_m2():
    """世界主要央行 M2 與資產負債表流動性數據（FRED API）。"""
    now_ts = time.time()
    if FRED_CACHE_FILE.exists():
        try:
            cached_data = json.loads(FRED_CACHE_FILE.read_text(encoding="utf-8"))
            if now_ts - cached_data.get("updated_at", 0) < FRED_CACHE_TTL:
                return jsonify(cached_data.get("data"))
        except Exception:
            pass

    if not FRED_API_KEY:
        return jsonify(error="未設定 FRED API Key"), 400

    base_url = "https://api.stlouisfed.org/fred/series/observations"

    def fetch_obs(sid, units=None, limit=24):
        p = {
            "series_id": sid,
            "api_key": FRED_API_KEY,
            "file_type": "json",
            "sort_order": "desc",
            "limit": limit
        }
        if units:
            p["units"] = units
        r = requests.get(base_url, params=p, timeout=12).json()
        out = []
        for row in r.get("observations", []):
            try:
                v = float(row["value"])
                out.append({"date": row["date"], "value": round(v, 2)})
            except (ValueError, KeyError):
                continue
        out.reverse()
        return out

    try:
        # 1. 美國 M2 原始額 (十億美元) 與 年增率 (%)
        m2_levels = fetch_obs("M2SL", limit=24)
        m2_yoy = fetch_obs("M2SL", units="pc1", limit=24)

        # 2. 主要央行印鈔水庫資產負債表年增率 (YoY %)
        fed_yoy = fetch_obs("WALCL", units="pc1", limit=24)
        ecb_yoy = fetch_obs("ECBASSETSW", units="pc1", limit=24)
        boj_yoy = fetch_obs("JPNASSETS", units="pc1", limit=24)

        latest_summary = {
            "us_m2_val": m2_levels[-1]["value"] if m2_levels else None,
            "us_m2_yoy": m2_yoy[-1]["value"] if m2_yoy else None,
            "us_m2_date": m2_yoy[-1]["date"] if m2_yoy else None,
            "fed_assets_yoy": fed_yoy[-1]["value"] if fed_yoy else None,
            "fed_assets_date": fed_yoy[-1]["date"] if fed_yoy else None,
            "ecb_assets_yoy": ecb_yoy[-1]["value"] if ecb_yoy else None,
            "ecb_assets_date": ecb_yoy[-1]["date"] if ecb_yoy else None,
            "boj_assets_yoy": boj_yoy[-1]["value"] if boj_yoy else None,
            "boj_assets_date": boj_yoy[-1]["date"] if boj_yoy else None,
        }

        result = {
            "latest": latest_summary,
            "m2_levels": m2_levels,
            "m2_yoy": m2_yoy,
            "fed_yoy": fed_yoy,
            "ecb_yoy": ecb_yoy,
            "boj_yoy": boj_yoy,
        }

        FRED_CACHE_FILE.write_text(json.dumps({
            "updated_at": now_ts,
            "data": result
        }, ensure_ascii=False), encoding="utf-8")

        return jsonify(result)
    except Exception as e:
        if FRED_CACHE_FILE.exists():
            try:
                cached_data = json.loads(FRED_CACHE_FILE.read_text(encoding="utf-8"))
                return jsonify(cached_data.get("data"))
            except Exception:
                pass
        return jsonify(error=f"FRED API 查詢失敗: {e}"), 502


VIX_CACHE_FILE = CACHE_DIR / "vix_cache.json"
VIX_CACHE_TTL = 30 * 60  # 30 分鐘快取


def _get_vix_status(val: float):
    """依 VIX 指數數值回傳情緒評估、文字顏色、背景色與外框色。"""
    if val >= 25:
        return "高度避險 / 恐慌", "#dc2626", "#fee2e2", "#fca5a5"
    elif val >= 20:
        return "中度警戒", "#ea580c", "#ffedd5", "#fdba74"
    elif val >= 15:
        return "輕度謹慎", "#d97706", "#fef3c7", "#fcd34d"
    else:
        return "常態平穩", "#16a34a", "#dcfce7", "#86efac"


@app.route("/api/vix")
def market_vix():
    """市場波動率指數（美股 ^VIX 與 臺指選擇權 VIXTWN）。"""
    now_ts = time.time()
    if VIX_CACHE_FILE.exists():
        try:
            cached_data = json.loads(VIX_CACHE_FILE.read_text(encoding="utf-8"))
            if now_ts - cached_data.get("updated_at", 0) < VIX_CACHE_TTL:
                return jsonify(cached_data.get("data"))
        except Exception:
            pass

    res = {}

    # 1. 美股 VIX (^VIX)
    try:
        v = yf.Ticker("^VIX")
        h = v.history(period="5d")
        if not h.empty:
            curr_val = round(float(h.iloc[-1]["Close"]), 2)
            prev_val = round(float(h.iloc[-2]["Close"]), 2) if len(h) >= 2 else curr_val
            chg = round(curr_val - prev_val, 2)
            pct = round((chg / prev_val) * 100, 2) if prev_val else 0.0
            dt_str = str(h.index[-1])[:10]
            st, col, bg, border = _get_vix_status(curr_val)
            res["us"] = {
                "symbol": "^VIX",
                "name": "美股波動率指數 (^VIX)",
                "close": curr_val,
                "change": chg,
                "pct": pct,
                "date": dt_str,
                "status": st,
                "color": col,
                "bg_color": bg,
                "border_color": border,
                "source": "Cboe / yfinance",
            }
    except Exception as e:
        print(f"美股 VIX 抓取失敗: {e}")

    # 2. 臺指選擇權波動率 (VIXTWN) - 台灣期交所 (TAIFEX) 官方每日公布數據
    try:
        s = requests.Session()
        s.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        })

        def _fetch_month_vix(ym_str):
            u = f"https://www.taifex.com.tw/file/taifex/Dailydownload/vix/log2data/{ym_str}new.txt"
            resp = s.get(u, timeout=8)
            if resp.status_code != 200 or "<title>404</title>" in resp.text.lower():
                return []
            content_lines = resp.content.decode("big5", errors="ignore").splitlines()
            records = []
            for l in content_lines:
                parts = [p.strip() for p in l.split("\t") if p.strip()]
                if parts and len(parts) >= 3 and parts[0].isdigit() and len(parts[0]) == 8:
                    try:
                        vix_num = float(parts[2])
                        records.append((parts[0], vix_num))
                    except ValueError:
                        pass
            return records

        today = date.today()
        cur_ym = today.strftime("%Y%m")
        prev_dt = today.replace(day=1) - timedelta(days=1)
        prev_ym = prev_dt.strftime("%Y%m")

        tw_rows = _fetch_month_vix(prev_ym) + _fetch_month_vix(cur_ym)
        if len(tw_rows) >= 2:
            curr_dt, curr_val = tw_rows[-1]
            prev_dt_val, prev_val = tw_rows[-2]
            chg = round(curr_val - prev_val, 2)
            pct = round((chg / prev_val) * 100, 2) if prev_val else 0.0
            dt_str = f"{curr_dt[:4]}-{curr_dt[4:6]}-{curr_dt[6:]}"
            st, col, bg, border = _get_vix_status(curr_val)
            res["tw"] = {
                "symbol": "VIXTWN",
                "name": "臺指選擇權波動率 (VIXTWN)",
                "close": curr_val,
                "change": chg,
                "pct": pct,
                "date": dt_str,
                "status": st,
                "color": col,
                "bg_color": bg,
                "border_color": border,
                "source": "台灣期交所 (TAIFEX)",
            }
        elif len(tw_rows) == 1:
            curr_dt, curr_val = tw_rows[-1]
            dt_str = f"{curr_dt[:4]}-{curr_dt[4:6]}-{curr_dt[6:]}"
            st, col, bg, border = _get_vix_status(curr_val)
            res["tw"] = {
                "symbol": "VIXTWN",
                "name": "臺指選擇權波動率 (VIXTWN)",
                "close": curr_val,
                "change": 0.0,
                "pct": 0.0,
                "date": dt_str,
                "status": st,
                "color": col,
                "bg_color": bg,
                "border_color": border,
                "source": "台灣期交所 (TAIFEX)",
            }
    except Exception as e:
        print(f"臺指 VIX 抓取失敗: {e}")

    if res:
        try:
            VIX_CACHE_FILE.write_text(json.dumps({
                "updated_at": now_ts,
                "data": res
            }, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        return jsonify(res)

    if VIX_CACHE_FILE.exists():
        try:
            cached_data = json.loads(VIX_CACHE_FILE.read_text(encoding="utf-8"))
            return jsonify(cached_data.get("data"))
        except Exception:
            pass

    return jsonify(error="無法取得市場波動率資料"), 502


@app.route("/api/update/<code>", methods=["POST"])
def update_valuation(code):
    """執行 My-TW-Coverage 的 update_valuation.py 更新估值。設有防重複點擊冷卻限制。"""
    global _last_update_time
    code = code.strip()
    if not re.fullmatch(r"^[0-9A-Za-z]{4,6}$", code):
        return jsonify(error="代號格式錯誤"), 400

    now = time.time()
    if now - _last_update_time < 15:
        return jsonify(error="操作過於頻繁，伺服器忙碌中，請間隔 15 秒後再試"), 429
    _last_update_time = now

    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    try:
        proc = subprocess.run([sys.executable, "scripts/update_valuation.py", code],
                              cwd=COVERAGE_DIR, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", env=env, timeout=60)
        return jsonify(ok=proc.returncode == 0, log=(proc.stdout + proc.stderr)[-2000:])
    except subprocess.TimeoutExpired:
        return jsonify(ok=False, log="更新逾時 (超過 60 秒)"), 504


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host="0.0.0.0", port=port)
