#!/usr/bin/env python3
"""
更新 freight-chart-data.json 的月度运价。

数据源（都是机器可读的结构化数据，不做散文解析）：
  1. 海运 FBX 指数 —— https://fbx.freightos.com/ 页面内嵌的官方 ticker JSON
     window.frProductIntroTickerData[...] = [{"label":"FBX01","value":"$6,129",...}, ...]
  2. 空运 / 结构化周报 —— https://www.freightos.com/wp-json/wp/v2/posts
     "Freight rate update" 类周报里的固定句式：
       "Asia-US West Coast prices (FBX01 Weekly) decreased 12% to $6,212/FEU."
       "China - N. America weekly prices decreased 2% to $5.76/kg."

为什么换掉原来的实现：
  原来读 Google News RSS 的 <description>，那里只有标题重复、没有任何运价数字，
  正则永远匹配不到，每次都打印"未提取到有效数据，跳过更新"。
  6、7 月数据缺失就是这个原因（脚本从上线起就没成功写入过一次）。

为什么不解析普通周报的正文：
  普通周报是散文，"$1,000/FEU" 可能是涨幅、也可能是水平值，语序还不固定
  （"to the West Coast to more than $5,700/FEU" vs "$6,200/FEU to the West Coast"），
  正则会静默写错数字。这类月份人工录入并在 monthlySources 里标 locked。

口径：
  每次运行把当天读数追加到 pendingReadings；
  当某个自然月结束后，用该月所有读数的算术平均写入图表，并记录用了哪些读数。
  monthlySources 里 locked=true 的月份不会被覆盖。

无公开月度数据源、脚本不会填的字段：
  中国→日本航线、中欧班列 rail_per_kg  → 保持 null，需人工维护
"""
import json
import re
import html
import urllib.request
from datetime import datetime, timezone

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0 Safari/537.36",
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
}
FBX_URL = "https://fbx.freightos.com/"
POSTS_URL = ("https://www.freightos.com/wp-json/wp/v2/posts"
             "?per_page=25&search=Update&_fields=id,date,link,title,content")

DASH = r"[-\u2013\u2014]"
# 只接受明确的水平值：数字前必须是 to / at（"peak of $5.25/kg" 这类不会被吃进来）
AIR_PATTERNS = {
    "air_cn_us": rf"China\s*{DASH}\s*(?:N\.?\s*America|US)\b.{{0,120}}?(?:to|at)\s*(?:about\s*)?\$([\d.]+)\s*/\s*kg",
    "air_cn_eu": rf"China\s*{DASH}\s*(?:N\.?\s*)?Europe\b.{{0,120}}?(?:to|at)\s*(?:about\s*)?\$([\d.]+)\s*/\s*kg",
}
# 只认结构化周报里带 (FBXxx Weekly) 标记的句子
OCEAN_PATTERNS = {
    "west_coast": r"\(FBX01 Weekly\).{0,80}?\$([\d,]+)\s*/\s*FEU",
    "east_coast": r"\(FBX03 Weekly\).{0,80}?\$([\d,]+)\s*/\s*FEU",
    "north_europe": r"\(FBX11 Weekly\).{0,80}?\$([\d,]+)\s*/\s*FEU",
}
TICKER_MAP = {"FBX01": "west_coast", "FBX03": "east_coast", "FBX11": "north_europe"}


def _get(url, limit=800000):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
        return r.read(limit).decode("utf-8", "ignore")


def fetch_fbx_ticker():
    """从 fbx.freightos.com 抓当前 FBX 各航线即期运价"""
    try:
        txt = _get(FBX_URL)
    except Exception as e:
        print(f"  [WARN] FBX 页面抓取失败: {e}")
        return {}
    blocks = re.findall(r"frProductIntroTickerData\['[^']+'\]\s*=\s*(\[.*?\]);", txt, re.S)
    for b in blocks:
        try:
            arr = json.loads(b)
        except json.JSONDecodeError:
            continue
        vals = {}
        for d in arr:
            key = TICKER_MAP.get(d.get("label", ""))
            if key:
                m = re.search(r"([\d,]+)", d.get("value", ""))
                if m:
                    vals[key] = int(m.group(1).replace(",", ""))
        if vals:
            return vals
    print("  [WARN] FBX ticker 未找到可解析数据")
    return {}


def fetch_post_readings():
    """从 Freightos 周报抓空运水平值 + 结构化 FBX 值"""
    try:
        posts = json.loads(_get(POSTS_URL))
    except Exception as e:
        print(f"  [WARN] 周报列表抓取失败: {e}")
        return []

    out = []
    for p in posts:
        body = re.sub(r"<[^>]+>", " ", html.unescape(p.get("content", {}).get("rendered", "")))
        body = re.sub(r"\s+", " ", body)
        vals = {}
        for key, pat in {**AIR_PATTERNS, **OCEAN_PATTERNS}.items():
            m = re.search(pat, body, re.IGNORECASE)
            if m:
                raw = m.group(1).replace(",", "")
                vals[key] = float(raw) if "." in raw else int(raw)
        if not vals:
            continue
        title = html.unescape(re.sub(r"<[^>]+>", "", p.get("title", {}).get("rendered", "")))
        out.append({
            "date": p["date"][:10],
            "source": "Freightos Weekly Update",
            "title": title,
            "url": p.get("link", ""),
            "values": vals,
        })
        print(f"  [{p['date'][:10]}] {vals}")
    return out


def merge_readings(existing, new):
    """按 (date, source) 去重合并"""
    seen = {(r.get("date"), r.get("source")) for r in existing}
    merged = list(existing)
    for r in new:
        k = (r.get("date"), r.get("source"))
        if k not in seen:
            seen.add(k)
            merged.append(r)
    merged.sort(key=lambda r: r.get("date", ""))
    return merged


def ensure_month(chart, month):
    months = chart["months"]
    if month in months:
        return months.index(month)
    months.append(month)
    months.sort()
    idx = months.index(month)
    for route in chart["routes"].values():
        for arr in route.values():
            if isinstance(arr, list):
                arr.insert(idx, None)
    print(f"  新增月份 {month} at idx={idx}")
    return idx


def is_month_empty(chart, month):
    """该月是否还没有任何运价数据（只填空缺，绝不回头改写已核对的历史）"""
    if month not in chart["months"]:
        return True
    idx = chart["months"].index(month)
    for route in chart["routes"].values():
        for key, arr in route.items():
            if key == "rail_per_kg":
                continue
            if isinstance(arr, list) and idx < len(arr) and arr[idx] is not None:
                return False
    return True


def write_month(chart, month, readings):
    vals = {}
    for r in readings:
        for k, v in r["values"].items():
            vals.setdefault(k, []).append(v)
    avg = {k: (round(sum(v) / len(v), 2) if k.startswith("air") else int(round(sum(v) / len(v))))
           for k, v in vals.items()}

    idx = ensure_month(chart, month)
    for rk, route in chart["routes"].items():
        ocean = "ocean_fcl_feu" if "ocean_fcl_feu" in route else "ocean_fcl_teu"
        if "美西" in rk:
            if "west_coast" in avg:
                route[ocean][idx] = avg["west_coast"]
            if "air_cn_us" in avg:
                route["air_per_kg"][idx] = avg["air_cn_us"]
        elif "美东" in rk:
            if "east_coast" in avg:
                route[ocean][idx] = avg["east_coast"]
            if "air_cn_us" in avg:
                route["air_per_kg"][idx] = avg["air_cn_us"]
        elif "北欧" in rk:
            if "north_europe" in avg:
                route[ocean][idx] = avg["north_europe"]
            if "air_cn_eu" in avg:
                route["air_per_kg"][idx] = avg["air_cn_eu"]

    chart["monthlySources"][month] = {
        "method": f"{len(readings)} 期读数算术平均",
        "reports": [{"date": r["date"], "url": r.get("url", ""), "source": r["source"]} for r in readings],
    }
    print(f"  写入 {month}: {avg}（{len(readings)} 期）")
    return avg


def main():
    print("=== 更新图表月度运价 ===")
    with open("freight-chart-data.json", "r", encoding="utf-8") as f:
        chart = json.load(f)
    chart.setdefault("monthlySources", {})
    chart.setdefault("pendingReadings", [])

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    this_month = today[:7]

    print("\n[1] 抓取 FBX 官方 ticker")
    ticker = fetch_fbx_ticker()
    new_readings = []
    if ticker:
        print(f"  当前 FBX: {ticker}")
        new_readings.append({"date": today, "source": "FBX ticker",
                             "url": FBX_URL, "title": "Freightos Baltic Index", "values": ticker})

    print("\n[2] 抓取 Freightos 周报")
    new_readings += fetch_post_readings()

    if not new_readings:
        print("\n未取到任何读数，退出")
        return

    readings = merge_readings(chart["pendingReadings"], new_readings)
    print(f"\n[3] 累积读数 {len(readings)} 条")

    by_month = {}
    for r in readings:
        by_month.setdefault(r["date"][:7], []).append(r)

    print("\n[4] 结算已完结的月份")
    still_pending = []
    for month in sorted(by_month):
        if month >= this_month:
            print(f"  {month} 尚未结束，留在 pendingReadings（{len(by_month[month])} 期）")
            still_pending += by_month[month]
            continue
        if chart["monthlySources"].get(month, {}).get("locked"):
            print(f"  {month} 已锁定（人工核对过），跳过")
            continue
        if not is_month_empty(chart, month):
            print(f"  {month} 已有数据，不回头覆盖历史，跳过")
            continue
        write_month(chart, month, by_month[month])

    chart["pendingReadings"] = sorted(still_pending, key=lambda r: r["date"])
    chart["lastUpdated"] = today
    chart["dataSource"] = ("海运 Freightos Baltic Index (FBX)：https://fbx.freightos.com/ ；"
                           "空运 Freightos Air Index：Freightos 官方周报 https://www.freightos.com/freight-resources/")
    chart["note"] = ("海运为 FBX 即期运价($/FEU 40尺柜)，空运为 Freightos Air Index($/kg)。"
                     "月度值为该月各期读数的算术平均，用了哪几期见 monthlySources。"
                     "中国→日本航线与中欧班列 rail_per_kg 无公开月度数据源，需人工维护，"
                     "缺失月份保持 null（图上表现为断线，不做插值）。")

    with open("freight-chart-data.json", "w", encoding="utf-8") as f:
        json.dump(chart, f, ensure_ascii=False, indent=2)

    print(f"\n完成：{len(chart['months'])} 个月，pendingReadings {len(chart['pendingReadings'])} 条")


if __name__ == "__main__":
    main()
