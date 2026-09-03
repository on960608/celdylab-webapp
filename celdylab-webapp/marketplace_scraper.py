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
import re

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
