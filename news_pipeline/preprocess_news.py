import json
import glob
import os
import re
import html
import hashlib
from datetime import datetime
from typing import List

# =============================
# 1) 정규식 규칙
# =============================

BOILERPLATE_PATTERNS = [
    r"Copyrights?\s*ⓒ.*",
    r"\[?\s*ⓒ.*",
    r".*무단전재\s*.*재배포\s*금지.*",
    r".*무단전재&재배포\s*금지.*",
    r".*재배포\s*금지.*",
    r".*저작권.*",

    # 제작/편집 크레딧
    r"^\(영상취재\s*:.*\)$",
    r"^\(영상편집\s*:.*\)$",
    r"^\(디자인\s*:.*\)$",
    r"^\(.*영상취재.*영상편집.*\)$",
]

REPORTER_PATTERNS = [
    r".*기자\s+\S+@\S+.*",
    r".*[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}.*",
]

BROADCAST_META_PATTERNS = [
    r"^\[앵커\].*$",
    r"^\[리포트\].*$",
    r"^.*기자입니다\..*$",
    r"^TV\s?조선.*입니다\..*$",
]

BRACKET_CREDIT_PATTERNS = [
    r"^\[[^\]]*(기자|=|특파원|뉴스|연합뉴스|마이데일리|스포츠서울|스포츠월드)[^\]]*\]$",
]

NEWSIS_PATTERNS = [
    r"^◎\s*공감언론\s*뉴시스.*$",
    r"^공감언론\s*뉴시스.*$",
]

UI_NOISE_PATTERNS = [
    r"^기사추천\s*\d+$",
    r"^기사추천$",
    r"^\d+$",
    r"^댓글\s*\d+.*$",
    r"^공유\s*$",

    r"^입력$",
    r"^수정$",
    r"^입력\s*\d{4}-\d{2}-\d{2}.*$",
    r"^수정\s*\d{4}-\d{2}-\d{2}.*$",
    r"^\|$",
    r"^\d{4}-\d{2}-\d{2}\s*\d{2}:\d{2}$",
]

SECTION_LINE = re.compile(r"^[가-힣A-Za-z\s·-]{1,10}$")

# 푸터(footer) 시작 트리거: 이 라인부터 아래는 통째로 컷
FOOTER_CUT_TRIGGERS = [
    r"^이\s*기사를\s*공유합니다.*$",
    r"^기사\s*추천.*$",
    r"^다른기사.*$",
    r"^주요뉴스.*$",
    r"^이슈\s*NOW.*$",

    # 리액션 블록
    r"^-\s*추천해요\s*\d+.*$",
    r"^-\s*좋아요\s*\d+.*$",
    r"^-\s*감동이에요\s*\d+.*$",
    r"^-\s*화나요\s*\d+.*$",
    r"^-\s*슬퍼요\s*\d+.*$",

    # 붙어 나오는 변형까지 커버
    r"^.*주요뉴스.*$",
    r"^.*이슈\s*NOW.*$",
    r"^실시간\s*주요뉴스.*$",
    r"^기사\s*공유.*$",
    r"^댓글\s*쓰기.*$",
    r"^댓글\s*$",

    # 제보/문의/홍보/광고
    r"^제보하기.*$",
    r"^기사문의.*제보.*$",
    r"^연합뉴스TV\s*기사문의.*$",
    r"^ADVERTISEMENT.*$",
    r"^ADVERTIS(E|EMENT).*$",
    r"^※.*제보하기.*$",

    # 추천/응원 UI
    r"^좋아요\s*$",
    r"^응원해요\s*$",
    r"^후속\s*원해요\s*$",

    # 연락처 안내
    r"^▷\s*전화.*$",
    r"^▷\s*카카오톡.*$",
    r"^-\s*라인.*$",
    r"^-\s*jebo\d+.*$",
    r"^카톡/라인\s*\w+.*$",
]

# "OOO 기자" 라인 자체도 푸터 시작으로 간주
REPORTER_CUT_TRIGGERS = [
    r"^[가-힣]{2,6}\s*(기자|선임기자|수석기자|차장|부장|편집위원|특파원|논설위원)\b.*$",
    r"^[가-힣]{2,6}\s*(기자|선임기자|수석기자|특파원|논설위원).*$",
]


# =============================
# 2) 유틸 함수
# =============================
def normalize_whitespace(text: str) -> str:
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_published_at(value: str) -> str:
    if not value:
        return value
    try:
        dt = datetime.strptime(value.strip(), "%a, %d %b %Y %H:%M:%S %z")
        return dt.isoformat()
    except Exception:
        return value


def remove_lines(lines: List[str], patterns: List[str]) -> List[str]:
    regexes = [re.compile(p) for p in patterns]
    out = []
    for ln in lines:
        if any(r.search(ln) for r in regexes):
            continue
        out.append(ln)
    return out


def is_mojibake(text: str) -> bool:
    """인코딩 깨짐(모지바케) 의심 텍스트 감지 → True면 드랍."""
    if not text:
        return True

    if len(text) < 50:
        return True

    hangul = len(re.findall(r"[가-힣]", text))
    asciiish = len(re.findall(r"[A-Za-z0-9]", text))
    total_letters = hangul + asciiish

    hangul_ratio = hangul / max(len(text), 1)

    # 모지바케에서 자주 보이는 문자들
    mojichars = len(
        re.findall(
            r"[ÂÃÀÁÄÅÆÇÈÉÊËÌÍÎÏÑÒÓÔÕÖÙÚÛÜÝÞßàáâãäåæçèéêëìíîïñòóôõöùúûüýþÿº¼½¾¡¿°±µ¶·¸¹º»¿ÆÇÐÀÌÒÓÔÕÖ×ØÙÚÛÜÝÞß]",
            text,
        )
    )
    mojiratio = mojichars / max(len(text), 1)

    # 한글 거의 없고 모지바케 특수문자 비율이 높으면 드랍
    if hangul_ratio < 0.05 and mojiratio > 0.02:
        return True

    # 한글 거의 없고, ASCII도 애매한 비율이면(깨진 기사/스팸) 드랍
    if hangul_ratio < 0.02 and total_letters > 0 and (asciiish / total_letters) < 0.8:
        return True

    return False


def clean_title(title: str) -> str:
    title = html.unescape(title or "")
    return normalize_whitespace(title)


def cut_footer_block(lines: List[str]) -> List[str]:
    """
    뒤에서부터 스캔하여 footer 트리거를 만나면 그 지점부터 끝까지 컷.
    트리거가 UI(기사추천/공유 등)일 때 바로 윗줄이 기자 라인이면 기자 줄까지 같이 컷.
    """
    cut_regexes = [re.compile(p) for p in (FOOTER_CUT_TRIGGERS + REPORTER_CUT_TRIGGERS)]
    reporter_cut_regexes = [re.compile(p) for p in REPORTER_CUT_TRIGGERS]

    for i in range(len(lines) - 1, -1, -1):
        if any(r.match(lines[i]) for r in cut_regexes):
            cut_at = i
            # UI 트리거 바로 위에 기자 라인이 붙어 있으면 같이 잘라냄
            if i - 1 >= 0 and any(r.match(lines[i - 1]) for r in reporter_cut_regexes):
                cut_at = i - 1
            return lines[:cut_at]
    return lines


def clean_content(content: str) -> str:
    if not content:
        return ""

    content = html.unescape(content)
    content = normalize_whitespace(content)

    # 모지바케면 바로 드랍
    if is_mojibake(content):
        return ""

    lines = [ln.strip() for ln in content.split("\n") if ln.strip()]

    # 라인 제거
    lines = remove_lines(lines, BROADCAST_META_PATTERNS)
    lines = remove_lines(lines, BRACKET_CREDIT_PATTERNS)
    lines = remove_lines(lines, REPORTER_PATTERNS)
    lines = remove_lines(lines, NEWSIS_PATTERNS)
    lines = remove_lines(lines, BOILERPLATE_PATTERNS)
    lines = remove_lines(lines, UI_NOISE_PATTERNS)

    # 푸터 컷
    lines = cut_footer_block(lines)

    # 첫 줄 섹션 라벨 제거(해외야구 등)
    if lines and SECTION_LINE.match(lines[0]) and len(lines[0]) <= 8:
        lines = lines[1:]

    cleaned = normalize_whitespace("\n".join(lines))

    # 최종 품질 체크
    if is_mojibake(cleaned):
        return ""
    return cleaned


def make_hash(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


# =============================
# 3) 메인 전처리
# =============================
def preprocess_all(raw_dir: str, output_path: str):
    seen_urls = set()
    seen_hashes = set()
    cleaned_records = []

    paths = sorted(glob.glob(os.path.join(raw_dir, "*.json")))
    print(f"Found {len(paths)} raw files")

    for path in paths:
        with open(path, "r", encoding="utf-8") as f:
            records = json.load(f)

        for r in records:
            url = r.get("url", "")
            if url in seen_urls:
                continue

            title = clean_title(r.get("title", ""))
            content = clean_content(r.get("content", ""))

            # 빈/너무 짧은 본문 드랍
            if len(content) < 150:
                continue

            content_hash = make_hash(title + content)
            if content_hash in seen_hashes:
                continue

            seen_urls.add(url)
            seen_hashes.add(content_hash)

            cleaned_records.append(
                {
                    "title": title,
                    "url": url,
                    "published_at": parse_published_at(r.get("published_at", "")),
                    "source": r.get("source", ""),
                    "content": content,
                }
            )

    with open(output_path, "w", encoding="utf-8") as f:
        for r in cleaned_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"Cleaned articles: {len(cleaned_records)}")
    print(f"Saved to: {output_path}")


# =============================
# 4) 실행
# =============================
if __name__ == "__main__":
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    RAW_DIR = os.path.join(BASE_DIR, "output")
    CLEAN_DIR = os.path.join(BASE_DIR, "clean")
    OUTPUT_PATH = os.path.join(CLEAN_DIR, "clean.jsonl")

    os.makedirs(CLEAN_DIR, exist_ok=True)
    preprocess_all(RAW_DIR, OUTPUT_PATH)
