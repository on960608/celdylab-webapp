"""
이커머스 마켓플레이스 베스트셀러 자동 수집 — G마켓 베스트(gmarket.co.kr/n/best)에서
셀디랩 판매 카테고리(청소·주방·구강제품·침구·생활용품)에 해당하는 카테고리 페이지를
방문해 순위·상품명·가격·할인율을 그대로 읽어와요.

*** 왜 G마켓만 자동화했는지 ***
쿠팡·네이버 스마트스토어·11번가는 브라우저 자동화 도구 자체의 안전 정책 때문에 접속이
막혀 있어요("이 사이트는 안전 정책에 따라 허용되지 않습니다") — 사이트가 우리를 차단한
게 아니라 자동화 도구 쪽에서 애초에 막아 둔 카테고리(전자상거래 결제/로그인 성격 사이트)
라서, 이 세 곳은 우회하지 않고 자동화 대상에서 제외했어요. G마켓 베스트는 로그인 없이
접근 가능한 공개 순위 페이지이고, 화면에 보이는 순위표 전체(상품명·가격·할인율 등)가
서버에서 완성되어 그대로 내려오는 걸 직접 확인했어요(leaf-text 비교로 페이지 텍스트
3614/3615개가 raw HTML 응답 안에 그대로 있었어요 — 유일하게 안 걸린 1개는 "<" 문자가
포함된 상품명이 HTML 이스케이프되며 생긴 단순 문자열 비교 차이였고, 실제로는 SSR이에요).

*** 카테고리 매핑 (2026-09 기준, G마켓 UI에서 직접 확인) ***
G마켓 베스트는 대분류(groupCode) 아래 소분류(subGroupCode) 탭으로 나뉘는데, 셀디랩의
판매 카테고리와 아래처럼 매칭돼요:
  청소     → 생활/주방(100001001) > 욕실/청소(200001006)
  주방     → 생활/주방(100001001) > 주방용품(200001012)
  구강제품 → 생필품/육아(100000007) > 구강/위생용품(200001003)
  침구     → 가구/홈(100001004) > 침구/홈(200006015)
  생활용품 → 생활/주방(100001001) > 생활잡화/보안/수납(200001007)
각 페이지는 최대 200위까지 순위를 보여줘요(광고 배너 li가 하나 섞여 있는데, 상품명이
없어서 자동으로 건너뛰어요).

*** 자사 판매 데이터 안내 ***
쿠팡윙·네이버 커머스센터 등 셀러센터 로그인이 필요한 자사 노출·판매 데이터는 이 방식으로
수집할 수 없어요 — 각 플랫폼의 셀러센터 오픈 API 키 발급과 별도 연동이 필요해요.

*** 유지보수 참고 ***
G마켓이 화면 구조(class명)를 바꾸면 이 파싱 로직도 깨질 수 있어요 — 그럴 땐 카테고리
하나가 빈 리스트를 돌려줄 뿐, 다른 카테고리 수집에는 영향 없어요(trend.py에서 카테고리
별로 각각 try/except 처리해요).
"""
import base64
import hashlib
import hmac
import os
import re
import time

import requests
from bs4 import BeautifulSoup

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}
_TIMEOUT = 12

# 셀디랩 카테고리명 -> (groupCode, subGroupCode)
GMARKET_CATEGORY_MAP = {
    "청소": ("100001001", "200001006"),
    "주방": ("100001001", "200001012"),
    "구강제품": ("100000007", "200001003"),
    "침구": ("100001004", "200006015"),
    "생활용품": ("100001001", "200001007"),
}

# 마켓플레이스 베스트셀러 탭에서 G마켓·네이버·쿠팡이 공통으로 쓰는 셀디랩 판매 카테고리
# 목록이에요(순서 그대로 화면에 표시돼요).
MARKETPLACE_CATEGORIES = list(GMARKET_CATEGORY_MAP.keys())

_PRICE_RE = re.compile(r"[\d,]+")
_DISCOUNT_RE = re.compile(r"(\d+)%")
_RANK_ALT_RE = re.compile(r"^(\d+)위$")


def _get_soup(url):
    resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    content_type = resp.headers.get("content-type", "")
    if "charset" not in content_type.lower():
        resp.encoding = resp.apparent_encoding
    return BeautifulSoup(resp.text, "html.parser")


def _price(li, selector):
    el = li.select_one(selector)
    if not el:
        return None
    m = _PRICE_RE.search(el.get_text())
    return int(m.group().replace(",", "")) if m else None


def _discount_pct(li):
    el = li.select_one(".box__discount")
    if not el:
        return None
    m = _DISCOUNT_RE.search(el.get_text())
    return int(m.group(1)) if m else None


def fetch_gmarket_best(category, limit=50):
    """
    category: GMARKET_CATEGORY_MAP의 키(청소/주방/구강제품/침구/생활용품).
    반환: [{rank, product, original_price, discount_pct, sale_price, link}, ...]
    순위 오름차순, 최대 limit개. 인식하지 못하는 category나 요청 실패 시 빈 리스트.
    """
    if category not in GMARKET_CATEGORY_MAP:
        return []
    group_code, sub_group_code = GMARKET_CATEGORY_MAP[category]
    url = f"https://www.gmarket.co.kr/n/best?groupCode={group_code}&subGroupCode={sub_group_code}"
    soup = _get_soup(url)

    list_el = soup.select_one("ul.list__best")
    if not list_el:
        return []

    items = []
    for li in list_el.select(":scope > li"):
        title_el = li.select_one(".box__item-title")
        if not title_el:
            continue  # 광고 배너(li.list-item--banner) 등 상품이 아닌 항목은 건너뛰어요.
        product = title_el.get_text(strip=True)
        if not product:
            continue

        rank = None
        img = li.find("img", alt=_RANK_ALT_RE)
        if img:
            m = _RANK_ALT_RE.match(img["alt"])
            if m:
                rank = int(m.group(1))
        if rank is None:
            rank = len(items) + 1  # 순위 뱃지를 못 찾을 때를 대비한 안전장치

        a = li.find("a", href=True)
        link = a["href"] if a else ""
        if link and not link.startswith("http"):
            link = "https://www.gmarket.co.kr" + link

        items.append({
            "rank": rank,
            "product": product,
            "original_price": _price(li, ".box__price-original"),
            "discount_pct": _discount_pct(li),
            "sale_price": _price(li, ".box__price-seller"),
            "link": link,
        })
        if len(items) >= limit:
            break

    items.sort(key=lambda r: r["rank"])
    return items


# (라벨, 함수) — trend.py에서 GMARKET_CATEGORY_MAP의 각 카테고리에 대해 이 함수를 호출해요.
MARKETPLACE_SCRAPERS = [
    ("G마켓", fetch_gmarket_best),
]


# ---------------------------------------------------------------------------
# 네이버 — 공식 API로 완전 자동화
#
# 네이버는 "카테고리 베스트 랭킹" 자체를 주는 공개 API가 없어요. 대신:
#   1. 검색광고(searchad.naver.com) 키워드도구 API로, 카테고리별 후보 키워드들의
#      월간 검색량(PC+모바일)을 조회해서 검색량이 높은 순으로 상위 5개 키워드를 뽑고
#   2. 그 5개 키워드 각각을 쇼핑검색(openapi.naver.com) API로 다시 조회해서, 그 키워드의
#      대표 상품(검색 결과 1위)을 "그 키워드의 대표 제품"으로 보여줘요.
# 즉 "카테고리별 검색량 상위 5개 제품 순위"는 정확히는 "검색량이 가장 높은 키워드 5개 +
# 그 키워드로 검색했을 때 가장 위에 뜨는 대표 상품"이에요 — 네이버에 실제 "베스트 상품
# 랭킹" API가 없어서 나온 근사치예요.
#
# *** 카테고리별 후보 키워드 (2026-09 기준) ***
# 아래 목록은 시작점으로 고른 후보 키워드예요. 실제 검색량 데이터를 보면서 셀디랩 판매
# 제품과 더 잘 맞는 키워드로 자유롭게 수정/추가하면 돼요 — 카테고리당 5개 넘게 넣어도
# 되고(검색량 상위 5개만 자동으로 골라져요), 적게 넣으면 그만큼만 순위에 나와요.
NAVER_CATEGORY_SEED_MAP = {
    "청소": ["청소솔", "욕실청소", "변기청소", "욕실세제", "청소용품", "찌든때제거", "곰팡이제거제"],
    "주방": ["주방용품", "주방수세미", "설거지수세미", "밀폐용기", "주방정리", "냄비세척솔"],
    "구강제품": ["칫솔살균기", "치간칫솔", "구강청결제", "칫솔꽂이", "구강위생용품", "혀클리너"],
    "침구": ["침구청소기", "이불건조기", "매트리스커버", "베개커버", "침구살균", "라텍스베개"],
    "생활용품": ["욕실용품", "정리수납용품", "생활잡화", "청소도구", "다목적세제", "수납박스"],
}

_NAVER_SEARCHAD_BASE = "https://api.searchad.naver.com"
_NAVER_SHOPPING_URL = "https://openapi.naver.com/v1/search/shop.json"
_TAG_RE = re.compile(r"<[^>]+>")


def naver_api_configured():
    """네이버 검색광고 + 쇼핑검색 API 키가 모두 Railway 환경변수에 등록됐는지 확인해요."""
    return all(
        os.environ.get(k)
        for k in (
            "NAVER_SEARCHAD_API_KEY",
            "NAVER_SEARCHAD_SECRET_KEY",
            "NAVER_SEARCHAD_CUSTOMER_ID",
            "NAVER_SHOPPING_CLIENT_ID",
            "NAVER_SHOPPING_CLIENT_SECRET",
        )
    )


def _searchad_headers(method, uri):
    """네이버 검색광고 API는 매 요청마다 HMAC-SHA256으로 서명한 값을 헤더에 실어야 해요
    (공식 문서의 서명 방식 그대로예요)."""
    api_key = os.environ["NAVER_SEARCHAD_API_KEY"]
    secret_key = os.environ["NAVER_SEARCHAD_SECRET_KEY"]
    customer_id = os.environ["NAVER_SEARCHAD_CUSTOMER_ID"]
    timestamp = str(int(time.time() * 1000))
    message = f"{timestamp}.{method}.{uri}"
    signature = base64.b64encode(
        hmac.new(secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
    ).decode("utf-8")
    return {
        "X-Timestamp": timestamp,
        "X-API-KEY": api_key,
        "X-Customer": str(customer_id),
        "X-Signature": signature,
    }


def _qc_to_int(v):
    """검색량 필드는 보통 정수지만, 검색량이 아주 적으면 "< 10" 같은 문자열로 와요.
    그런 경우엔 대략값(5)으로 처리해요."""
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip()
    if s.isdigit():
        return int(s)
    if "10" in s:  # "< 10" 등
        return 5
    return 0


def _fetch_keyword_volumes(keywords):
    """키워드 목록의 월간 검색량(PC+모바일 합)을 조회해요. 반환: {키워드: 검색량 또는 None}.
    검색광고 API는 한 번에 최대 5개 키워드만 받아서, 5개씩 잘라 여러 번 호출해요."""
    result = {kw: None for kw in keywords}
    uri = "/keywordstool"
    for i in range(0, len(keywords), 5):
        batch = keywords[i:i + 5]
        params = {"hintKeywords": ",".join(batch), "showDetail": "1"}
        resp = requests.get(
            _NAVER_SEARCHAD_BASE + uri,
            params=params,
            headers=_searchad_headers("GET", uri),
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        rows = data.get("keywordList") or []
        # relKeyword는 공백이 제거된 형태로 오기도 해서, 비교할 때 공백을 없애고 맞춰요.
        by_norm = {}
        for row in rows:
            norm = str(row.get("relKeyword", "")).replace(" ", "")
            vol = _qc_to_int(row.get("monthlyPcQcCnt")) + _qc_to_int(row.get("monthlyMobileQcCnt"))
            # 같은 키워드가 여러 번 나오면(관련 키워드 확장) 가장 큰 값을 남겨요.
            if norm not in by_norm or vol > by_norm[norm]:
                by_norm[norm] = vol
        for kw in batch:
            norm = kw.replace(" ", "")
            if norm in by_norm:
                result[kw] = by_norm[norm]
    return result


def fetch_naver_keyword_volume(keyword):
    """키워드 하나의 월간 검색량(PC+모바일 합)을 돌려줘요. 조회 실패/데이터 없음이면 None."""
    return _fetch_keyword_volumes([keyword]).get(keyword)


def fetch_naver_shopping_top_product(keyword):
    """쇼핑검색 API로 키워드의 대표 상품(검색결과 1위)을 가져와요.
    반환: {"product": str, "link": str, "sale_price": int|None} 또는 실패 시 None."""
    client_id = os.environ["NAVER_SHOPPING_CLIENT_ID"]
    client_secret = os.environ["NAVER_SHOPPING_CLIENT_SECRET"]
    resp = requests.get(
        _NAVER_SHOPPING_URL,
        params={"query": keyword, "display": 1, "sort": "sim"},
        headers={"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    items = resp.json().get("items") or []
    if not items:
        return None
    item = items[0]
    title = _TAG_RE.sub("", item.get("title", "")).strip()
    lprice = item.get("lprice")
    return {
        "product": title,
        "link": item.get("link", ""),
        "sale_price": int(lprice) if lprice not in (None, "") else None,
    }


def fetch_naver_category_top5(category, limit=5):
    """
    category: NAVER_CATEGORY_SEED_MAP의 키(청소/주방/구강제품/침구/생활용품).
    카테고리 후보 키워드 중 검색량이 가장 높은 순으로 최대 limit개를 뽑고, 각 키워드의
    쇼핑검색 대표 상품을 붙여서 돌려줘요.
    반환: [{rank, product, original_price, discount_pct, sale_price, link, keyword, search_count}, ...]
    API 키 미설정이거나 인식 못 하는 category면 빈 리스트.
    """
    if category not in NAVER_CATEGORY_SEED_MAP or not naver_api_configured():
        return []

    seeds = NAVER_CATEGORY_SEED_MAP[category]
    volumes = _fetch_keyword_volumes(seeds)
    ranked = sorted(
        ((kw, v) for kw, v in volumes.items() if v is not None),
        key=lambda kv: -kv[1],
    )[:limit]

    items = []
    for rank, (keyword, search_count) in enumerate(ranked, start=1):
        try:
            product_info = fetch_naver_shopping_top_product(keyword) or {}
        except Exception:
            product_info = {}
        items.append({
            "rank": rank,
            "product": product_info.get("product") or keyword,
            "original_price": None,
            "discount_pct": None,
            "sale_price": product_info.get("sale_price"),
            "link": product_info.get("link", ""),
            "keyword": keyword,
            "search_count": search_count,
        })
    return items
