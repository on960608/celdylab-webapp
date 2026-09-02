"""
외부몰 트렌드 자동 수집 — 82market · 지금하는공구(09now.com) · 공구모아(09more.com)에서
지금 진행중인 인기 셀러·상품을 읽어와서 trend_records에 자동으로 채워 넣어요.

*** 중요: 이 세 사이트만 자동화한 이유 ***
셀디랩이 원래 모니터링하던 6개 채널(캘린·82market·위시버니·지금하는공구·인공·공구모아) 중
82market과 지금하는공구(09now.com)만 로그인 없이 접근 가능한 '공개 페이지' 안에
목록이 그대로 서버에서 완성되어 내려와요 (사람이 브라우저로 보는 것과 완전히 동일한
정보를 그냥 읽어오는 방식이라 안전해요).

캘린·위시버니·인공·(원래) gonggumoa.com은 화면에 보이는 상품 목록이 자바스크립트가
그 사이트의 비공개 내부 API를 호출해야만 채워지는 방식이라, 이 안전한 방식으로는
데이터를 가져올 수 없어요. 그래서 '공구모아' 자리는 같은 이름의 다른 사이트인
09more.com(마찬가지로 공개 페이지에 목록이 그대로 내려옴)으로 대체했어요.

*** 유지보수 참고 ***
세 사이트 모두 공식 API가 아니라 화면 HTML 구조를 그대로 읽는 방식이에요. 사이트가
디자인을 바꾸면 이 파싱 로직도 깨질 수 있어요 — 그럴 땐 fetch_* 함수 하나가 빈 리스트를
돌려주거나 예외를 던질 뿐, 나머지 사이트 수집에는 영향 없어요(trend.py의 refresh()에서
사이트별로 각각 try/except 처리해요).
"""
import re
from datetime import date

import requests
from bs4 import BeautifulSoup

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}
_TIMEOUT = 10


def _get_soup(url):
    resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    # 서버가 응답 헤더에 charset을 안 적어주면 requests가 기본값(ISO-8859-1)으로
    # 잘못 해석해서 한글이 다 깨져요(예: 09more.com). 그럴 때만 실제 인코딩을 다시
    # 감지해서 써요 — charset이 이미 명시돼 있으면 그대로 두는 게 더 안전해요.
    content_type = resp.headers.get("content-type", "")
    if "charset" not in content_type.lower():
        resp.encoding = resp.apparent_encoding
    return BeautifulSoup(resp.text, "html.parser")


_SKIP_TAGS = {"script", "style", "noscript"}


def _leaf_texts(tag):
    """tag 안에서 '더 이상 자식 태그가 없는' 요소들의 글자만 순서대로 뽑아요.
    <script>/<style> 태그는 화면에 보이는 글자가 아니라 코드·CSS 텍스트라서 제외해요
    (SSR 단계에서 각 카드 근처에 style 태그가 섞여 나오는 사이트가 있어서 꼭 필요해요)."""
    out = []
    for el in tag.find_all(True):
        if el.name in _SKIP_TAGS:
            continue
        if not el.find(True):
            t = el.get_text(strip=True)
            if t:
                out.append(t)
    return out


# ---------------------------------------------------------------------------
# 82market — https://www.82market.com/
#   1) '지금 활발한 인플루언서' 코너 = 실제 인기 순위 (rank 1, 2, 3 ...)
#   2) 오늘 진행중인 포스트 카드 = 셀러 + 상품명
#   두 정보를 셀러명으로 이어붙여서, 순위가 높은 셀러의 포스트를 우선으로 올려요.
# ---------------------------------------------------------------------------

def fetch_82market(limit=20):
    soup = _get_soup("https://www.82market.com/")

    rank_of = {}
    heading = soup.find(string=lambda s: s and s.strip() == "지금 활발한 인플루언서")
    if heading:
        section = heading.find_parent("section") or heading.find_parent()
        if section:
            idx = 0
            for a in section.select('a[href^="/influencers/"]'):
                if a.get("href") == "/influencers":
                    continue
                texts = [t for t in _leaf_texts(a) if not t.startswith("공구")]
                name = next((t for t in texts if not t.isdigit()), None)
                if not name:
                    continue
                idx += 1
                rank_of.setdefault(name.strip(), idx)

    items = []
    seen = set()
    for a in soup.select('a[href^="/post/"]'):
        href = a.get("href")
        if not href or href in seen:
            continue
        h3 = a.find("h3")
        if not h3:
            continue
        seller = next(
            (t for t in _leaf_texts(a) if t not in ("오늘 마감",) and t != h3.get_text(strip=True)),
            None,
        )
        if not seller:
            continue
        seen.add(href)
        items.append({
            "check_date": date.today().isoformat(),
            "platform": "82market",
            "seller": seller,
            "product": h3.get_text(strip=True),
            "category": "",
            "price": 0,
            "link": "https://www.82market.com" + href,
            "rank": rank_of.get(seller.strip(), 999),
        })

    items.sort(key=lambda r: r["rank"])
    for r in items:
        del r["rank"]
    return items[:limit]


# ---------------------------------------------------------------------------
# 지금하는공구 — https://www.09now.com/
#   카드마다 가격("N원")·상품명(h2)·셀러명(작은 텍스트)이 함께 내려와요.
# ---------------------------------------------------------------------------

_PRICE_WON_RE = re.compile(r"^[\d,]+원$")
_PERCENT_RE = re.compile(r"^\d+%$")


def fetch_09now(limit=20):
    soup = _get_soup("https://www.09now.com/")
    records = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href in seen:
            continue
        h2 = a.find("h2")
        if not h2:
            continue
        product = h2.get_text(strip=True)
        if not product:
            continue

        texts = _leaf_texts(a)

        # 할인 중인 카드는 "정가 → 할인율(%) → 할인가" 순으로 가격이 두 번 나와요.
        # "N원" 형태 중 마지막 값이 항상 지금 실제로 살 수 있는 가격이에요.
        price = 0
        for t in texts:
            if _PRICE_WON_RE.match(t):
                try:
                    price = int(t[:-1].replace(",", ""))
                except ValueError:
                    pass

        # 셀러명은 카드에서 항상 맨 마지막 텍스트예요. 마감뱃지·가격·할인율(%)이 그
        # 앞에 섞여 있을 수 있어서, 뒤에서부터 그런 값이 아닌 첫 텍스트를 찾아요.
        seller = None
        for t in reversed(texts):
            if t == product or _PRICE_WON_RE.match(t) or _PERCENT_RE.match(t) or "마감" in t:
                continue
            seller = t
            break
        if not seller:
            continue

        seen.add(href)
        link = href if href.startswith("http") else "https://www.09now.com" + href
        records.append({
            "check_date": date.today().isoformat(),
            "platform": "지금하는공구",
            "seller": seller,
            "product": product,
            "category": "",
            "price": price,
            "link": link,
        })
        if len(records) >= limit:
            break

    return records


# ---------------------------------------------------------------------------
# 공구모아 자리 — https://www.09more.com/
#   (원래 gonggumoa.com은 자바스크립트로만 목록을 불러와서 자동화가 불가능해요.
#    이름이 같은 다른 사이트인 09more.com으로 대신 연동했어요 — 09more.com도
#    스스로를 '공구모아'라고 부르고, 같은 성격의 SNS 공동구매 통합 목록이에요.)
#   카드마다 상품명·셀러명·가격(숫자만)·마감일(YYYY/MM/DD)·카테고리가 함께 내려와요.
# ---------------------------------------------------------------------------

_DATE_RE = re.compile(r"^\d{4}/\d{2}/\d{2}$")
_DIGITS_RE = re.compile(r"^[\d,]+$")

_09MORE_CATEGORY_MAP = {
    "가전": "생활용품", "전기용품": "생활용품", "생활/건강": "생활용품",
    "주방": "주방용품",
    "패션": "패션잡화", "의류": "패션잡화",
    "침구류": "홈인테리어",
    "여행": "여행",
}


def _map_09more_category(raw):
    return _09MORE_CATEGORY_MAP.get(raw, "기타")


# 카드 안에 상품명·셀러명·카테고리 말고도 섞여 나올 수 있는 상태 배지 텍스트 — 카테고리로
# 잘못 인식되지 않도록 걸러내요.
_09MORE_NOISE_WORDS = {"진행 중", "진행중", "종료", "마감", "오픈예정", "예정", "품절"}


def fetch_09more(limit=20):
    soup = _get_soup("https://www.09more.com/")
    records = []
    seen = set()

    for date_str in soup.find_all(string=_DATE_RE):
        node = date_str.parent
        card = None
        # 상품명은 셀러/가격/마감일/카테고리보다 한 단계 더 바깥쪽 태그에 있어요.
        # 그래서 조건을 만족하는 첫 조상에서 멈추지 않고, "형제 카드까지 합쳐지기
        # 직전"까지 계속 올라가면서 매번 갱신해요 — 그래야 상품명이 포함된, 그 카드의
        # 진짜 바깥 경계를 찾을 수 있어요.
        for _ in range(8):
            if node is None:
                break
            texts = [t for t in _leaf_texts(node) if t]
            date_count = sum(1 for t in texts if _DATE_RE.match(t))
            has_price = any(_DIGITS_RE.match(t) and len(t.replace(",", "")) >= 3 for t in texts)
            if date_count > 1:
                # 마감일이 두 개 이상 보이면 옆 카드까지 합쳐진 거예요 — 그 전 단계가 정답.
                break
            if has_price and date_count == 1 and 3 <= len(texts) <= 8:
                card = node
            node = node.parent
        if card is None:
            continue

        texts = [t for t in _leaf_texts(card) if t]
        price = 0
        rest = []
        for t in texts:
            if _DATE_RE.match(t):
                continue
            if not price and _DIGITS_RE.match(t) and len(t.replace(",", "")) >= 3:
                price = int(t.replace(",", ""))
                continue
            if t in _09MORE_NOISE_WORDS:
                continue
            rest.append(t)

        if len(rest) < 2:
            continue
        # 앞의 둘은 항상 [상품명, 셀러명] 순서였어요. 카테고리는 맨 마지막 값을 쓰는 게
        # (중간에 예상 못 한 배지 텍스트가 하나 더 끼어들어도) 더 안전해요.
        product, seller = rest[0], rest[1]
        category = _map_09more_category(rest[-1]) if len(rest) > 2 else "기타"

        key = (product, seller)
        if key in seen:
            continue
        seen.add(key)

        records.append({
            "check_date": date.today().isoformat(),
            "platform": "공구모아",
            "seller": seller,
            "product": product,
            "category": category,
            "price": price,
            "link": "",
        })
        if len(records) >= limit:
            break

    return records


# 이름(라벨) → 수집 함수. trend.py의 /refresh 에서 이 순서대로 실행해요.
SCRAPERS = [
    ("82market", fetch_82market),
    ("지금하는공구", fetch_09now),
    ("공구모아", fetch_09more),
]
