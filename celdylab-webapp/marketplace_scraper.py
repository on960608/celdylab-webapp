"""
이커머스 마켓플레이스 베스트셀러 자동 수집.

*** 플랫폼별 방식이 다른 이유 ***
쿠팡·네이버 스마트스토어·11번가는 브라우저 자동화 도구 자체의 안전 정책 때문에 사이트
접속이 막혀 있어요("이 사이트는 안전 정책에 따라 허용되지 않습니다") — 사이트가 우리를
차단한 게 아니라 자동화 도구 쪽에서 애초에 막아 둔 카테고리(전자상거래 결제/로그인 성격
사이트)라서, 이 사이트들은 우회하지 않고 일반 스크레이핑 대상에서 제외했어요. 그래서
플랫폼마다 다른 방식을 써요:
  · G마켓 — 로그인 없이 접근 가능한 공개 순위 페이지(gmarket.co.kr/n/best)를 그대로
    스크레이핑해요(아래 fetch_gmarket_best).
  · 네이버 — 사이트 접속 대신 네이버가 공식 제공하는 API를 인증된 HTTPS 요청으로 직접
    호출해요: 검색광고 API(키워드도구)로 검색량을, 쇼핑검색 API로 대표 상품 링크를
    가져와요(아래 fetch_naver_category_top5). API 키만 등록하면 완전 자동이에요.
  · 쿠팡 — 공식 검색량 API가 없고 사이트 자동화도 막혀 있어서, 인스타 댓글 추출 기능과
    같은 방식으로 처리해요: 사람이 실제 로그인된 브라우저에서 카테고리 페이지를 HAR
    파일로 저장해서 올리면 coupang_best.py가 그 안의 상품 데이터를 읽어요(검색수 없이
    쿠팡 자체 순위만 표시돼요).

G마켓은 화면에 보이는 순위표 전체(상품명·가격·할인율 등)가 서버에서 완성되어 그대로
내려오는 걸 직접 확인했어요(leaf-text 비교로 페이지 텍스트 3614/3615개가 raw HTML 응답
안에 그대로 있었어요 — 유일하게 안 걸린 1개는 "<" 문자가 포함된 상품명이 HTML
이스케이프되며 생긴 단순 문자열 비교 차이였고, 실제로는 SSR이에요).

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
import time as _time

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
# 네이버 — 검색광고 API(키워드도구)로 검색량을, 쇼핑검색 API로 대표 상품 링크를 가져와요.
#
# 필요한 Railway 환경변수 (둘 다 등록해야 자동 수집이 켜져요):
#   · 검색광고 API — 네이버 검색광고(https://searchad.naver.com) 가입 후 [도구 > API 사용
#     관리]에서 발급: NAVER_SEARCHAD_API_KEY(Access License), NAVER_SEARCHAD_SECRET_KEY,
#     NAVER_SEARCHAD_CUSTOMER_ID
#   · 쇼핑검색 오픈API — 네이버 개발자센터(https://developers.naver.com/apps)에서 앱을
#     등록하고 "검색" API를 추가해 발급: NAVER_SHOPPING_CLIENT_ID, NAVER_SHOPPING_CLIENT_SECRET
#
# 참고: 이 API 호출은 지금 이 개발 환경(샌드박스)에서는 네트워크 정책상 테스트할 수 없었어요
# (openapi.naver.com 등이 이 환경에서만 막혀 있어요) — Railway에 배포된 뒤 실제 API 키로
# 처음 "⚡ 지금 다시 수집"을 눌러볼 때 정상 동작을 확인해 주세요.
# ---------------------------------------------------------------------------

# 셀디랩 카테고리명 -> 검색량을 확인할 대표(seed) 키워드
NAVER_CATEGORY_SEED_MAP = {
    "청소": "청소용품",
    "주방": "주방용품",
    "구강제품": "구강청결제",
    "침구": "침구세트",
    "생활용품": "생활용품",
}

_NAVER_SEARCHAD_BASE = "https://api.searchad.naver.com"
_NAVER_SHOPPING_URL = "https://openapi.naver.com/v1/search/shop.json"
_NAVER_TITLE_TAG_RE = re.compile(r"</?b>")


def naver_api_configured():
    """검색광고 API + 쇼핑검색 API 키가 모두 등록돼 있어야 자동 수집이 켜져요."""
    return bool(
        os.environ.get("NAVER_SEARCHAD_API_KEY")
        and os.environ.get("NAVER_SEARCHAD_SECRET_KEY")
        and os.environ.get("NAVER_SEARCHAD_CUSTOMER_ID")
        and os.environ.get("NAVER_SHOPPING_CLIENT_ID")
        and os.environ.get("NAVER_SHOPPING_CLIENT_SECRET")
    )


def _naver_searchad_signature(timestamp, method, uri, secret_key):
    message = f"{timestamp}.{method}.{uri}"
    sig = hmac.new(secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(sig).decode("utf-8")


def _naver_searchad_headers(method, uri):
    api_key = os.environ["NAVER_SEARCHAD_API_KEY"]
    secret_key = os.environ["NAVER_SEARCHAD_SECRET_KEY"]
    customer_id = os.environ["NAVER_SEARCHAD_CUSTOMER_ID"]
    timestamp = str(int(_time.time() * 1000))
    return {
        "X-Timestamp": timestamp,
        "X-API-KEY": api_key,
        "X-Customer": customer_id,
        "X-Signature": _naver_searchad_signature(timestamp, method, uri, secret_key),
    }


def _parse_qc_count(v):
    """검색량이 적으면 '< 10' 같은 문자열로 와서, 안전하게 정수로 바꿔줘요(모자란 값은 0)."""
    if v is None:
        return 0
    s = str(v).strip().replace(",", "")
    if s.startswith("<") or not s:
        return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


def fetch_naver_keyword_volume(seed_keyword, limit=5):
    """검색광고 키워드도구로 seed_keyword의 연관 키워드들과 월간 검색량(PC+모바일)을
    가져와서, 검색량 합이 높은 순으로 상위 limit개를 돌려줘요.
    반환: [{keyword, monthly_pc, monthly_mobile, total}, ...]"""
    uri = "/keywordstool"
    resp = requests.get(
        _NAVER_SEARCHAD_BASE + uri,
        headers=_naver_searchad_headers("GET", uri),
        params={"hintKeywords": seed_keyword, "showDetail": "1"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    rows = []
    for kw in resp.json().get("keywordList", []):
        pc = _parse_qc_count(kw.get("monthlyPcQcCnt"))
        mobile = _parse_qc_count(kw.get("monthlyMobileQcCnt"))
        rows.append({
            "keyword": kw.get("relKeyword", ""),
            "monthly_pc": pc,
            "monthly_mobile": mobile,
            "total": pc + mobile,
        })
    rows.sort(key=lambda r: -r["total"])
    return rows[:limit]


def fetch_naver_shopping_top_product(keyword):
    """쇼핑검색 API로 keyword의 가장 관련도 높은 대표 상품 1개를 가져와요.
    반환: {title, link, price} 또는 못 찾으면 None."""
    resp = requests.get(
        _NAVER_SHOPPING_URL,
        headers={
            "X-Naver-Client-Id": os.environ["NAVER_SHOPPING_CLIENT_ID"],
            "X-Naver-Client-Secret": os.environ["NAVER_SHOPPING_CLIENT_SECRET"],
        },
        params={"query": keyword, "display": 1, "sort": "sim"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    if not items:
        return None
    it = items[0]
    title = _NAVER_TITLE_TAG_RE.sub("", it.get("title", ""))
    try:
        price = int(it.get("lprice") or 0) or None
    except (TypeError, ValueError):
        price = None
    return {"title": title, "link": it.get("link", ""), "price": price}


def fetch_naver_category_top5(category, limit=5):
    """카테고리(청소/주방/구강제품/침구/생활용품)의 대표 키워드로 검색량 상위 limit개를
    뽑고, 각 키워드마다 대표 상품 링크를 붙여서 돌려줘요.
    반환: [{rank, product, keyword, search_count, original_price, discount_pct,
            sale_price, link}, ...]"""
    seed = NAVER_CATEGORY_SEED_MAP.get(category)
    if not seed:
        return []
    keywords = fetch_naver_keyword_volume(seed, limit=limit)
    items = []
    for i, kw_row in enumerate(keywords, start=1):
        try:
            product = fetch_naver_shopping_top_product(kw_row["keyword"])
        except Exception:
            product = None
        items.append({
            "rank": i,
            "product": product["title"] if product else kw_row["keyword"],
            "keyword": kw_row["keyword"],
            "search_count": kw_row["total"],
            "original_price": None,
            "discount_pct": None,
            "sale_price": product["price"] if product else None,
            "link": product["link"] if product else "",
        })
    return items
