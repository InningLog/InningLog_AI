import requests
import trafilatura

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NewsPipelineBot/0.1)"
}

def fetch_article_text(url: str):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return None

        text = trafilatura.extract(
            r.text,
            include_comments=False,
            include_tables=False
        )

        if not text or len(text) < 300:
            return None

        return text.strip()

    except requests.RequestException:
        return None