#!/usr/bin/env python3
"""Analyze fundf10 HTML table structure for FOF vs regular funds."""
import urllib.request
import re

def analyze(code):
    # Use HTTP (the server doesn't redirect/works with HTTP)
    url = f"http://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc&code={code}&topline=50&year=2026&month=6"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": "http://fundf10.eastmoney.com/"
    })
    text = urllib.request.urlopen(req, timeout=10).read().decode("utf-8", "ignore")

    m = re.search(r'content\s*:\s*"(.*?)",\s*arryear', text, re.DOTALL)
    if not m:
        print(f"{code}: no content found")
        return

    content = m.group(1)
    tables = re.findall(r'<table[^>]*>(.*?)</table>', content, re.DOTALL)
    print(f"\n=== {code}: {len(tables)} tables ===")

    for ti, table in enumerate(tables):
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', table, re.DOTALL)
        print(f"  Table {ti}: {len(rows)} rows")
        for ri, row in enumerate(rows[:5]):
            tds = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
            clean = [re.sub(r'<[^>]+>', '', td).strip()[:20] for td in tds]
            print(f"    row{ri}: {len(tds)} cols -> {clean}")

# Test with FOF and regular fund
analyze("501215")
analyze("167003")
analyze("161015")
