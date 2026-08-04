#!/usr/bin/env python3
"""
从 EIA 官方月度序列抓布伦特/WTI 现货月均价，写入 freight-chart-data.json 的 oilPrice。

数据源（美国能源信息署官方历史数据表，无需 API key）：
  Brent: https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s=RBRTE&f=M
  WTI  : https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s=RWTC&f=M
  两个序列都是"月度算术平均现货价（$/桶）"，与图表口径一致。

EIA 通常滞后约 1 个月发布，尚未发布的月份写 null，不做推算。
"""
import json
import re
import html
import urllib.request
from datetime import datetime, timezone

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0 Safari/537.36"}
SERIES = {
    "brent": ("RBRTE", "Europe Brent Spot Price FOB"),
    "wti": ("RWTC", "Cushing OK WTI Spot Price FOB"),
}


def eia_monthly(series_id):
    """解析 EIA 历史数据表：每行一个年份，后面 12 个月的月均值"""
    url = f"https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s={series_id}&f=M"
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=45) as r:
        txt = r.read().decode("utf-8", "ignore")

    out = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", txt, re.S):
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).replace("\xa0", "").strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]
        if not cells or not re.fullmatch(r"\d{4}", cells[0] or ""):
            continue
        year = int(cells[0])
        for i, v in enumerate(cells[1:13]):
            if re.fullmatch(r"\d+(\.\d+)?", v or ""):
                out[f"{year}-{i + 1:02d}"] = float(v)
    return out


def main():
    print("=== 更新原油月均价（EIA 官方）===")
    data = {}
    for key, (sid, label) in SERIES.items():
        try:
            data[key] = eia_monthly(sid)
            print(f"  {key} ({sid}): {len(data[key])} 个月, 最新 {max(data[key])} = {data[key][max(data[key])]}")
        except Exception as e:
            print(f"  [WARN] {key} 抓取失败: {e}")
            data[key] = {}

    if not any(data.values()):
        print("未取到任何数据，跳过")
        return

    with open("freight-chart-data.json", "r", encoding="utf-8") as f:
        chart = json.load(f)

    months = chart["months"]
    oil = chart.setdefault("oilPrice", {})
    filled = {"brent": 0, "wti": 0}
    for key in ("brent", "wti"):
        if not data[key]:
            continue                      # 抓失败时保留原数组，不清空
        series = [data[key].get(m) for m in months]
        oil[key] = series
        filled[key] = sum(1 for v in series if v is not None)

    oil["unit"] = "$/barrel"
    oil["source"] = ("EIA 美国能源信息署官方月度现货均价 — "
                     "Brent: RBRTE https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s=RBRTE&f=M ；"
                     "WTI: RWTC https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s=RWTC&f=M")
    oil["note"] = "EIA 通常滞后约1个月发布，未发布的月份为 null，不做推算。"
    oil["lastFetched"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    with open("freight-chart-data.json", "w", encoding="utf-8") as f:
        json.dump(chart, f, ensure_ascii=False, indent=2)

    print(f"  已对齐 {len(months)} 个月：brent 有值 {filled['brent']} 个，wti 有值 {filled['wti']} 个")
    print("完成")


if __name__ == "__main__":
    main()
