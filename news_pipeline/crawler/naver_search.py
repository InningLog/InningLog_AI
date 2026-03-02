import json
import urllib.parse
import urllib.request
import os 
from dotenv import load_dotenv
import time
from typing import Any, Dict, List

load_dotenv()

CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")

if not CLIENT_ID or not CLIENT_SECRET:
    raise RuntimeError("NAVER API 키가 .env에 설정되어 있지 않습니다.")

DISPLAY = 100
SORT = "date"
STARTS = [1, 101]

# 팀 풀네임/별칭 중심
TEAM_QUERIES = {
    "LG": ["LG 트윈스", "LG트윈스", "트윈스"],
    "두산": ["두산 베어스", "두산베어스", "베어스"],
    "SSG": ["SSG 랜더스", "SSG랜더스", "랜더스"],
    "KT": ["KT 위즈", "KT위즈", "위즈"],
    "한화": ["한화 이글스", "한화이글스", "이글스"],
    "롯데": ["롯데 자이언츠", "롯데자이언츠", "자이언츠"],
    "삼성": ["삼성 라이온즈", "삼성라이온즈", "라이온즈"],
    "NC": ["NC 다이노스", "NC다이노스", "다이노스"],
    "KIA": ["KIA 타이거즈", "KIA타이거즈", "타이거즈"],
    "키움": ["키움 히어로즈", "키움히어로즈", "히어로즈"],
}

# 2) 야구 문맥(필터에도 사용)
BASEBALL_KEYWORDS = [
    "KBO", "프로야구", "야구", "구단", "감독", "코치",
    "투수", "타자", "선발", "불펜", "마무리", "등판",
    "홈런", "타율", "OPS", "ERA", "안타", "볼넷", "삼진",
    "캠프", "스프링캠프", "훈련", "시범경기", "개막",
    "트레이드", "FA", "외국인", "용병", "연봉", "재계약",
     "2군", "1군"
]

def looks_like_baseball(title: str, desc: str) -> bool:
    """
    네이버 검색 결과에는 본문이 없으니 title/description으로만 1차 필터.
    """
    text = f"{title} {desc}".lower()
    hit = 0
    for kw in BASEBALL_KEYWORDS:
        if kw.lower() in text:
            hit += 1
            if hit >= 2:  # 기준: 2개 이상이면 야구로 인정 (원하면 3으로 올려도 됨)
                return True
    return False


def search_news(query: str, start: int = 1) -> Dict[str, Any]:
    if not CLIENT_ID or not CLIENT_SECRET:
        raise RuntimeError("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수가 설정되어 있어야 합니다.")

    enc = urllib.parse.quote(query)
    url = (
        f"https://openapi.naver.com/v1/search/news.json"
        f"?query={enc}&display={DISPLAY}&start={start}&sort={SORT}"
    )

    req = urllib.request.Request(url)
    req.add_header("X-Naver-Client-Id", CLIENT_ID)
    req.add_header("X-Naver-Client-Secret", CLIENT_SECRET)

    with urllib.request.urlopen(req) as res:
        return json.loads(res.read().decode("utf-8"))

def build_queries() -> List[str]:
    """
    쿼리 폭발 방지용:
    - 팀별 별칭을 모두 돌리되,
    - 각 쿼리에 'KBO' 또는 '프로야구' 같은 문맥을 묶어서 precision을 올림
    """
    queries = []
    for team, names in TEAM_QUERIES.items():
        for name in names:
            # 문맥을 붙여서 잡음 줄이기 (둘 중 하나만 써도 됨)
            queries.append(f"{name} KBO")
            queries.append(f"{name} 프로야구")
    # 베이스 쿼리도 약간만 추가
    queries += ["KBO", "프로야구", "KBO리그 스프링캠프", "KBO FA", "KBO 트레이드"]
    # 중복 제거
    return list(dict.fromkeys(queries))

def collect_news_items() -> List[Dict[str, Any]]:
    queries = build_queries()

    all_items = []
    for q in queries:
        for start in STARTS:
            data = search_news(q, start=start)
            items = data.get("items", [])

            # 1차 필터(제목/설명 기반)
            for it in items:
                title = it.get("title", "")
                desc = it.get("description", "")
                if looks_like_baseball(title, desc):
                    all_items.append(it)

            time.sleep(0.05)  # 호출 간격 (너무 빡빡하면 0.1~0.2)

    # URL 기준 중복 제거
    seen = set()
    deduped = []
    for it in all_items:
        url = it.get("originallink") or it.get("link")
        if url and url not in seen:
            seen.add(url)
            deduped.append(it)

    return deduped