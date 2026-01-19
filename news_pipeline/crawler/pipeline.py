from crawler.naver_search import collect_news_items
from crawler.article_fetcher import fetch_article_text
from datetime import datetime
from urllib.parse import urlparse
import json, os

def run_pipeline():
    items = collect_news_items()
    results = []
    failed_urls = []

    for it in items:
        url = it.get("originallink")
        if not url:
            continue

        text = fetch_article_text(url)
        if not text:
            failed_urls.append(url)
            continue

        results.append({
            "title": it.get("title"),
            "url": url,
            "published_at": it.get("pubDate"),
            "source": urlparse(url).netloc,
            "content": text
        })

    os.makedirs("output", exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")

    with open(f"output/{today}.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    with open("output/failed_urls.txt", "w") as f:
        for u in failed_urls:
            f.write(u + "\n")

    print(f"saved {len(results)} articles / ❌ failed {len(failed_urls)}")

