---
inclusion: auto
---
# 头程运费观察 编辑指南

## 项目背景
头程运费观察模块数据，展示在 Seller Learning Hub (https://yanjiaoo.github.io/competitor-study-hub/)。
编辑 freight-data.json 后 push，网页自动加载最新内容。

## 数据结构
每条记录包含：id, title, date, route, summary, source, links
- title: 中文标题，陈述式
- route: 航线/路线（如 中国-美国、中国-欧洲）
- summary: 运费变动内容，包含具体数字
- links: 参考链接数组
