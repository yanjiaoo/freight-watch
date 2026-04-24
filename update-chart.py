#!/usr/bin/env python3
"""
月度更新图表数据：从 Freightos 周报抓取最新 FBX 数据，追加到 freight-chart-data.json
每月1号运行，提取上月的运价数据
"""
import urllib.request
import xml.etree.ElementTree as ET
import json
import re
import html
from datetime import datetime, timezone, timedelta
from urllib.parse import quote


def fetch_freightos_reports():
    """从 AJOT 和 Container News 抓取最近的 Freightos 周报"""
    queries = [
        'Freightos weekly update FBX container rates site:ajot.com',
        'Freightos weekly update container rates site:container-news.com',
    ]
    articles = []
    for q in queries:
        url = f'https://news.google.com/rss/search?q={quote(q)}&hl=en&gl=US&ceid=US:en'
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'FreightChartBot/1.0'})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = resp.read()
            root = ET.fromstring(data)
            for item in root.findall('.//item')[:5]:
                title = html.unescape(item.findtext('title', ''))
                desc = re.sub(r'<[^>]+>', '', html.unescape(item.findtext('description', ''))).strip()
                link = item.findtext('link', '')
                pub_date = item.findtext('pubDate', '')
                try:
                    dt = datetime.strptime(pub_date, '%a, %d %b %Y %H:%M:%S %Z')
                except Exception:
                    dt = datetime.now(timezone.utc)
                articles.append({
                    'title': title, 'content': desc,
                    'url': link, 'date': dt.strftime('%Y-%m-%d'),
                })
        except Exception as e:
            print(f'  [WARN] {e}')
    return articles


def extract_fbx_from_text(text):
    """从文本中提取 FBX 运价数据"""
    data = {}

    # FBX01 美西
    m = re.search(r'(?:West Coast|FBX01)[^$]*\$([0-9,]+)/FEU', text)
    if m:
        data['west_coast'] = int(m.group(1).replace(',', ''))

    # FBX03 美东
    m = re.search(r'(?:East Coast|FBX03)[^$]*\$([0-9,]+)/FEU', text)
    if m:
        data['east_coast'] = int(m.group(1).replace(',', ''))

    # FBX11 北欧
    m = re.search(r'(?:N\.\s*Europe|North Europe|FBX11)[^$]*\$([0-9,]+)/FEU', text)
    if m:
        data['north_europe'] = int(m.group(1).replace(',', ''))

    # 空运 中国-美国
    m = re.search(r'China\s*[-–]\s*N\.\s*America[^$]*\$([0-9.]+)/kg', text)
    if m:
        data['air_cn_us'] = float(m.group(1))

    # 空运 中国-欧洲
    m = re.search(r'China\s*[-–]\s*N\.\s*Europe[^$]*\$([0-9.]+)/kg', text)
    if m:
        data['air_cn_eu'] = float(m.group(1))

    return data


def main():
    print('=== 月度更新图表数据 ===')

    # 1. 抓取最新 Freightos 周报
    articles = fetch_freightos_reports()
    print(f'抓取到 {len(articles)} 篇周报')

    # 2. 提取 FBX 数据
    latest_data = {}
    for article in articles:
        text = article['title'] + ' ' + article['content']
        extracted = extract_fbx_from_text(text)
        if extracted:
            # 用最新的数据覆盖
            for k, v in extracted.items():
                if k not in latest_data:
                    latest_data[k] = v
            print(f'  从 [{article["date"]}] 提取: {extracted}')

    if not latest_data:
        print('未提取到有效数据，跳过更新')
        return

    print(f'最终提取数据: {latest_data}')

    # 3. 读取现有图表数据
    with open('freight-chart-data.json', 'r', encoding='utf-8') as f:
        chart = json.load(f)

    # 4. 计算当前月份标签
    now = datetime.now(timezone.utc)
    current_month = now.strftime('%Y-%m')
    months = chart['months']

    if current_month in months:
        # 更新当月数据
        idx = months.index(current_month)
        print(f'更新当月 {current_month} (index {idx})')
    else:
        # 追加新月份
        months.append(current_month)
        idx = len(months) - 1
        # 各航线追加 null 占位
        for route in chart['routes'].values():
            for key in route:
                if isinstance(route[key], list):
                    route[key].append(None)
        print(f'追加新月份 {current_month} (index {idx})')

    # 5. 填入数据
    routes = chart['routes']
    route_keys = list(routes.keys())

    # 找到对应航线
    for rk in route_keys:
        rk_lower = rk.lower()
        if '美西' in rk or 'fbx01' in rk_lower:
            if 'west_coast' in latest_data:
                feu_key = 'ocean_fcl_feu' if 'ocean_fcl_feu' in routes[rk] else 'ocean_fcl_teu'
                routes[rk][feu_key][idx] = latest_data['west_coast']
            if 'air_cn_us' in latest_data:
                routes[rk]['air_per_kg'][idx] = latest_data['air_cn_us']
        elif '美东' in rk or 'fbx03' in rk_lower:
            if 'east_coast' in latest_data:
                feu_key = 'ocean_fcl_feu' if 'ocean_fcl_feu' in routes[rk] else 'ocean_fcl_teu'
                routes[rk][feu_key][idx] = latest_data['east_coast']
            if 'air_cn_us' in latest_data:
                routes[rk]['air_per_kg'][idx] = latest_data.get('air_cn_us')
        elif '北欧' in rk or '欧洲' in rk or 'fbx11' in rk_lower:
            if 'north_europe' in latest_data:
                feu_key = 'ocean_fcl_feu' if 'ocean_fcl_feu' in routes[rk] else 'ocean_fcl_teu'
                routes[rk][feu_key][idx] = latest_data['north_europe']
            if 'air_cn_eu' in latest_data:
                routes[rk]['air_per_kg'][idx] = latest_data['air_cn_eu']

    chart['lastUpdated'] = now.strftime('%Y-%m-%d')

    # 6. 写入
    with open('freight-chart-data.json', 'w', encoding='utf-8') as f:
        json.dump(chart, f, ensure_ascii=False, indent=2)

    print(f'图表数据已更新，当前 {len(months)} 个月')


if __name__ == '__main__':
    main()
