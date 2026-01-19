import json
import urllib.parse
import urllib.request

CLIENT_ID = "xNPv1i9IOBPESq3aW08Q"
CLIENT_SECRET = "CO6stAZN55"

QUERIES = ["야구", "kbo", "프로야구", "투수", "타자","홈런", "선발", "불펜", "경기", "시즌","키움", "히어로즈", "lg", "두산", "ssg", "kt","한화","롯데","삼성","nc","kt wiz"]
DISPLAY = 100
SORT = "date"

def search_news(query):
    enc = urllib.parse.quote(query)
    url = (
        f"https://openapi.naver.com/v1/search/news.json"
        f"?query={enc}&display={DISPLAY}&start=1&sort={SORT}"
    )

    req = urllib.request.Request(url)
    req.add_header("X-Naver-Client-Id", CLIENT_ID)
    req.add_header("X-Naver-Client-Secret", CLIENT_SECRET)

    with urllib.request.urlopen(req) as res:
        return json.loads(res.read().decode("utf-8"))

def collect_news_items():
    all_items = []
    for q in QUERIES:
        data = search_news(q)
        all_items.extend(data.get("items", []))

    # URL 기준 중복 제거
    seen = set()
    deduped = []
    for it in all_items:
        url = it.get("originallink") or it.get("link")
        if url and url not in seen:
            seen.add(url)
            deduped.append(it)

    return deduped