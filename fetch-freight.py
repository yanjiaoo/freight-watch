#!/usr/bin/env python3
"""
头程运费观察 - 周度自动抓取
从 AJOT/Container News 的 Freightos 周报中提取 FBX 指数数据
"""
import urllib.request
import xml.etree.ElementTree as ET
import json
import re
import html
from datetime import datetime, timezone
from urllib.parse import quote


def fetch_rss(query, max_items=5):
    url = f'https://news.google.com/rss/search?q={quote(query)}&hl=en&gl=US&ceid=US:en'
    items = []
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'FreightBot/1.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
        root = ET.fromstring(data)
        for item in root.findall('.//item')[:max_items]:
            title_raw = item.findtext('title', '')
            parts = title_raw.rsplit(' - ', 1)
            title = html.unescape(parts[0].strip())
            source = parts[1].strip() if len(parts) > 1 else ''
            desc = re.sub(r'<[^>]+>', '', html.unescape(item.findtext('description', ''))).strip()[:500]
            pub_date = item.findtext('pubDate', '')
            link = item.findtext('link', '')
            try:
                dt = datetime.strptime(pub_date, '%a, %d %b %Y %H:%M:%S %Z')
            except Exception:
                dt = datetime.now(timezone.utc)
            items.append({
                'title': title, 'content': desc, 'source': source,
                'url': link, 'date': dt.strftime('%Y-%m-%d'),
            })
    except Exception as e:
        print(f'  [WARN] {e}')
    return items


QUERIES = [
    'Freightos weekly update container rates',
    'Freightos FBX China US ocean freight rate',
    'Drewry WCI container shipping rate weekly',
    'China US ocean freight rate FBA shipping cost',
    '跨境电商 头程运费 海运 空运 变化',
    '亚马逊 FBA 头程 运费 物流费',
]

RELEVANCE_KEYWORDS = [
    'freight', 'shipping', 'container', 'FBX', 'FEU', 'TEU',
    'ocean rate', 'air cargo', 'Freightos', 'Drewry', 'WCI',
    'fuel surcharge', 'GRI', 'blank sailing',
    '运费', '海运', '空运', '头程', '物流费', '集装箱',
    '燃油附加费', 'FBA', '货代',
]

EXCLUDE = ['stock price', 'investment', '股价', 'Prime Video']


def is_relevant(title, content):
    text = (title + ' ' + content).lower()
    if any(e in text for e in EXCLUDE):
        return False
    return any(k.lower() in text for k in RELEVANCE_KEYWORDS)


def main():
    print('=== 头程运费观察 周度抓取 ===')
    all_items = []
    seen = set()

    for q in QUERIES:
        print(f'  [{q[:40]}...]')
        for item in fetch_rss(q, 5):
            if item['title'] not in seen and is_relevant(item['title'], item['content']):
                seen.add(item['title'])
                all_items.append(item)

    all_items.sort(key=lambda x: x['date'], reverse=True)
    top = all_items[:8]
    print(f'  筛选后: {len(top)} 条')

    # 读取现有数据保留手工条目
    existing = []
    try:
        with open('freight-data.json', 'r', encoding='utf-8') as f:
            existing = json.load(f)
    except Exception:
        pass

    # 保留有 route 字段的手工条目
    manual = [item for item in existing if item.get('route')]
    manual_titles = set(item.get('title', '') for item in manual)

    # 合并
    final = list(manual)
    for item in top:
        if item['title'] in manual_titles:
            continue
        # 清洗标题
        title = item['title']
        title = re.sub(r'[?!]+$', '', title).strip()

        final.append({
            'id': f'fw_auto_{len(final)+1:03d}',
            'title': title,
            'date': item['date'],
            'route': '',
            'mode': 'Freightos周报',
            'summary': item['content'][:300],
            'source': item['source'],
            'links': [{'label': item['source'] or '查看原文', 'url': item['url']}],
        })

    final.sort(key=lambda x: x.get('date', ''), reverse=True)

    with open('freight-data.json', 'w', encoding='utf-8') as f:
        json.dump(final, f, ensure_ascii=False, indent=2)

    print(f'=== 完成！{len(final)} 条运费动态 ===')


if __name__ == '__main__':
    main()
