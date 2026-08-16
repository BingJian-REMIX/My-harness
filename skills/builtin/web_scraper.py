"""
爬取网页文本
"""

import requests
from bs4 import BeautifulSoup

def execute(url, max_size=3000):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.encoding = 'utf-8'
        soup = BeautifulSoup(resp.text, 'html.parser')
        for tag in soup(['script', 'style']):
            tag.decompose()
        text = soup.get_text(separator='\n')
        return text[:max_size] + ('...' if len(text) > max_size else '')
    except Exception as e:
        return f"爬取失败: {e}"