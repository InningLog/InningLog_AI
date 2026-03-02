'''
- Input : clean/clean.jsonl (전처리된 뉴스 데이터)
- Output : digest/YYYY-MM-DD.json (팀별 Top2 클러스터 카드)


기능:
1) 하루치 기사 필터링
2) 팀 추출(룰 기반: 제목+본문 앞부분)
3) 팀별로 유사 기사 그룹핑(클러스터링)
   - 기본: TF-IDF + cosine radius neighbors (설치 추가 필요 없음)
   - 옵션: sentence-transformers 있으면 임베딩 모드로도 가능(코드에 준비)
4) 클러스터 대표기사 선택(centroid에 가장 가까운 기사)
5) Top2 선정(score = volume + recency + source_weight)
'''

import os 
import re
import json
import math 
import argparse
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional

# 팀 별칭
TEAM_ALIASES = {
    "KIA": ["KIA", "기아", "타이거즈", "KIA타이거즈", "기아타이거즈"],
    "두산": ["두산", "베어스", "두산베어스"],
    "LG": ["LG", "엘지", "트윈스", "LG트윈스", "엘지트윈스"],
    "삼성": ["삼성", "라이온즈", "삼성라이온즈"],
    "SSG": ["SSG", "랜더스", "쓱", "SSG랜더스", "쓱렌더스"],
    "롯데": ["롯데", "자이언츠", "롯데자이언츠"],
    "한화": ["한화", "이글스", "한화이글스"],
    "NC": ["NC", "엔씨", "다이노스", "NC다이노스", "엔씨다이노스"],
    "키움": ["키움", "히어로즈", "키움히어로즈"],
    "KT": ["KT", "케이티", "위즈", "KT위즈", "케이티위즈"],
}

TEAM_ORDER = list(TEAM_ALIASES.keys())

# 언론사 가중치(초기 MVP용: 없으면 1.0)
SOURCE_WEIGHT = {
    # 예시. 네가 중요하다고 생각하는 매체를 1.1~1.3 정도로 올리는 식
    # "sportsseoul.com": 1.10,
    # "news.tvchosun.com": 1.05,
}

# 유틸 
def parse_iso(dt_str: str) -> Optional[datetime]:
    if not dt_str:
        return None
    try:
        # 2026-01-12T21:46:00+09:00 형태
        return datetime.fromisoformat(dt_str)
    except Exception:
        return None
    
def safe_date(dt: Optional[datetime]) -> str:
    if not dt:
        return ""
    return dt.date().isoformat()
    
def read_jsonl(path: str) -> List[dict]:
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(json.loads(line))
    return out

def make_article_id(url: str) -> str:
    # 간단: url 기반 id
    return re.sub(r"[^a-zA-Z0-9]+", "_", url)[-80:]


# content 앞부분아니고 전체에서 보는건 불가능(???) 
def extract_team(title: str, content: str) -> Optional[str]:
    # title + content 앞부분에서 매칭
    text = f"{title} {content[:800]}"
    for team in TEAM_ORDER:
        for alias in TEAM_ALIASES[team]:
            if alias and alias in text:
                return team
    return None

def text_for_similarity(title: str, content: str, max_chars: int = 2500) -> str:
    # 본문 길이가 너무 길면 앞부분만
    body = content[:max_chars]
    return f"{title}\n{body}"


#------------------------------
# 클러스터링 관련
#------------------------------

class UnionFind: 
    def __init__(self, n : int):
        self.parent = list(range(n))
        self.rank = [0] * n
        
    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x
    
    def union(self, a: int, b: int):
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.rank[ra] < self.rank[rb]:
            self.parent[ra] = rb
        elif self.rank[ra] > self.rank[rb]:
            self.parent[rb] = ra
        else:
            self.parent[rb] = ra
            self.rank[ra] += 1
            
    def groups(self) -> Dict[int, List[int]]:
        g: Dict[int, List[int]] = {}
        for i in range(len(self.parent)):
            r = self.find(i)
            g.setdefault(r, []).append(i)
        return g
    
    
#------------------------------
# TF-IDF 기반 유사도 그룹핑
#------------------------------
def cluster_by_tfidf(texts: List[str], sim_threshold: float = 0.3) -> List[List[int]]:
    """
    TF-IDF + NearestNeighbors radius 기반으로 유사도 그래프 만들고 연결요소로 그룹 생성.
    sim_threshold: cosine similarity 기준 (TF-IDF는 0.2~0.35 부근이 자주 적당)
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.neighbors import NearestNeighbors

    if len(texts) == 1:
        return [[0]]

    vec = TfidfVectorizer(
        max_features=60000,
        ngram_range=(1, 2),
        min_df=2,
        token_pattern=r"(?u)\b\w+\b",
    )
    X = vec.fit_transform(texts)  # sparse

    # cosine distance = 1 - cosine_similarity
    radius = 1.0 - sim_threshold
    nn = NearestNeighbors(metric="cosine", algorithm="brute")
    nn.fit(X)

    # radius_neighbors_graph: sparse adjacency
    graph = nn.radius_neighbors_graph(X, radius=radius, mode="connectivity")

    uf = UnionFind(len(texts))
    coo = graph.tocoo()
    for i, j in zip(coo.row, coo.col):
        uf.union(int(i), int(j))

    groups = list(uf.groups().values())
    # 큰 그룹 우선 정렬
    groups.sort(key=len, reverse=True)
    return groups

#------------------------------
# SBERT 임베딩 기반
#------------------------------
def cluster_by_sbert(texts: List[str], sim_threshold: float = 0.82, model_name: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2") -> Tuple[List[List[int]], List[List[float]]]:
    """
    sentence-transformers가 설치되어 있으면 사용 가능.
    cosine similarity 기준 threshold (0.78~0.85 권장)
    """
    from sentence_transformers import SentenceTransformer
    from sklearn.neighbors import NearestNeighbors
    import numpy as np

    if len(texts) == 1:
        return [[0]], [[0.0]]

    model = SentenceTransformer(model_name)
    emb = model.encode(texts, normalize_embeddings=True, batch_size=64, show_progress_bar=False)
    emb = np.asarray(emb)

    radius = 1.0 - sim_threshold
    nn = NearestNeighbors(metric="cosine", algorithm="brute")
    nn.fit(emb)
    graph = nn.radius_neighbors_graph(emb, radius=radius, mode="connectivity")

    uf = UnionFind(len(texts))
    coo = graph.tocoo()
    for i, j in zip(coo.row, coo.col):
        uf.union(int(i), int(j))

    groups = list(uf.groups().values())
    groups.sort(key=len, reverse=True)
    return groups, emb.tolist()

# -----------------------------
# 5) 대표 기사 선택 (centroid 가까운 기사)
# -----------------------------
def choose_representative(indices: List[int], vectors: Optional[List[List[float]]] = None) -> int:
    """
    vectors가 있으면 centroid 기반 대표 선택.
    vectors가 없으면(= tfidf 모드) 간단히 첫 번째를 대표로.
    """
    if len(indices) == 1:
        return indices[0]

    if not vectors:
        return indices[0]

    import numpy as np
    V = np.asarray([vectors[i] for i in indices], dtype=float)
    centroid = V.mean(axis=0)
    # cosine similarity since vectors are normalized in sbert mode
    sims = V @ centroid / (np.linalg.norm(centroid) + 1e-9)
    rep_local = int(np.argmax(sims))
    return indices[rep_local]

# -----------------------------
# 6) 스코어링 & Top2
# -----------------------------
def score_cluster(
    cluster_size: int,
    rep_published_at: Optional[datetime],
    rep_source: str,
    day_start: datetime,
    day_end: datetime,
) -> float:
    # volume: 로그(큰 이슈 우대)
    volume = math.log(1 + cluster_size)

    # recency: 해당 날짜 내에서 얼마나 늦게 나온 기사인지 (0~1)
    recency = 0.5
    if rep_published_at and day_start and day_end and day_end > day_start:
        t = rep_published_at.timestamp()
        recency = (t - day_start.timestamp()) / (day_end.timestamp() - day_start.timestamp())
        recency = max(0.0, min(1.0, recency))

    # source weight
    sw = SOURCE_WEIGHT.get(rep_source, 1.0)

    # 가중치(초기값): volume 가장 중요 + 최신성 + 소스
    return 0.60 * volume + 0.30 * recency + 0.10 * (sw - 1.0 + 1.0)  # sw를 1.0 중심으로

# -----------------------------
# 7) 메인 실행
# -----------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True, help="YYYY-MM-DD (예: 2026-01-12)")
    ap.add_argument("--clean_jsonl", default="clean/clean.jsonl", help="전처리된 clean.jsonl 경로")
    ap.add_argument("--out_dir", default="digests", help="출력 폴더")
    ap.add_argument("--mode", choices=["tfidf", "sbert"], default="tfidf", help="클러스터링 모드")
    ap.add_argument("--sim_threshold", type=float, default=None, help="유사도 임계치 (tfidf: 0.2~0.35 / sbert: 0.78~0.85)")
    ap.add_argument("--min_cluster_size", type=int, default=1, help="너무 작은 그룹 제외 기준(1이면 제외 안함)")
    args = ap.parse_args()

    target_date = args.date.strip()

    # 날짜 범위(해당 날짜 00:00~23:59:59)
    day_start = datetime.fromisoformat(target_date + "T00:00:00")
    day_end = datetime.fromisoformat(target_date + "T23:59:59")

    # clean.jsonl 로드
    if not os.path.exists(args.clean_jsonl):
        raise FileNotFoundError(f"clean_jsonl not found: {args.clean_jsonl}")

    articles = read_jsonl(args.clean_jsonl)

    # 하루치 필터 + 팀 추출
    day_articles = []
    for a in articles:
        dt = parse_iso(a.get("published_at", ""))
        if not dt or safe_date(dt) != target_date:
            continue

        title = a.get("title", "") or ""
        content = a.get("content", "") or ""
        team = extract_team(title, content)
        if not team:
            continue  # 야구팀 없는 건 제외(원하면 OTHER로 묶어도 됨)

        day_articles.append({
            "article_id": make_article_id(a.get("url","")),
            "team": team,
            "title": title,
            "url": a.get("url", ""),
            "source": a.get("source", ""),
            "published_at": a.get("published_at", ""),
            "dt": dt,
            "content": content,
        })

    print(f"[{target_date}] articles after team-filter: {len(day_articles)}")

    # 팀별 버킷
    by_team: Dict[str, List[dict]] = {}
    for a in day_articles:
        by_team.setdefault(a["team"], []).append(a)

    os.makedirs(args.out_dir, exist_ok=True)
    out_path = os.path.join(args.out_dir, f"{target_date}.json")

    digests_out = []

    for team, items in by_team.items():
        # 텍스트 준비
        texts = [text_for_similarity(x["title"], x["content"]) for x in items]

        # 클러스터링
        mode = args.mode
        if mode == "tfidf":
            thr = args.sim_threshold if args.sim_threshold is not None else 0.28
            groups = cluster_by_tfidf(texts, sim_threshold=thr)
            vectors = None
        else:
            thr = args.sim_threshold if args.sim_threshold is not None else 0.82
            groups, vectors = cluster_by_sbert(texts, sim_threshold=thr)

        # 각 클러스터 -> 대표 + score
        clusters = []
        for g in groups:
            if len(g) < args.min_cluster_size:
                continue
            rep_idx = choose_representative(g, vectors=vectors)
            rep = items[rep_idx]

            sc = score_cluster(
                cluster_size=len(g),
                rep_published_at=rep["dt"],
                rep_source=rep["source"],
                day_start=day_start,
                day_end=day_end,
            )

            # 연관기사(클러스터 내부) - 대표 제외 상위 5개만
            related = []
            for j in g:
                if j == rep_idx:
                    continue
                related.append({
                    "title": items[j]["title"],
                    "url": items[j]["url"],
                    "source": items[j]["source"],
                    "published_at": items[j]["published_at"],
                })
                if len(related) >= 5:
                    break

            clusters.append({
                "team": team,
                "date": target_date,
                "cluster_size": len(g),
                "score": sc,
                "representative": {
                    "title": rep["title"],
                    "url": rep["url"],
                    "source": rep["source"],
                    "published_at": rep["published_at"],
                },
                "related_articles": related,
                # 요약은 다음 단계에서 붙일 예정
                "headline": None,
                "summary_lines": [],
                "keywords": [],
            })

        # 팀별 Top2
        clusters.sort(key=lambda x: x["score"], reverse=True)
        top2 = clusters[:2]

        # digest_id 부여
        for idx, d in enumerate(top2, start=1):
            d["digest_id"] = f"{team}|{target_date}|{idx}"
            digests_out.append(d)

        print(f"[{target_date}][{team}] clusters={len(clusters)}, top2={len(top2)}")

    # 저장
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(digests_out, f, ensure_ascii=False, indent=2)

    print(f"Saved digests → {out_path}")


if __name__ == "__main__":
    main()
