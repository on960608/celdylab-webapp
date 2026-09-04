"""
쿠팡 카테고리/베스트 페이지의 네트워크 응답(JSON)에서 상품 목록을 찾아내는 휴리스틱 파서예요.

*** 왜 이 방식인지 ***
쿠팡은 공식 검색량 API가 없고, 브라우저 자동화 도구로 쿠팡 페이지에 접속하는 것도 자동화
도구 자체의 안전 정책 때문에 막혀 있어요(marketplace_scraper.py 맨 위 설명 참고 — 전자상거래
결제/로그인 성격 사이트라서 우회하지 않고 자동화 대상에서 제외했어요). 그래서 인스타그램
댓글 추출 기능(igcomments.py)과 똑같은 방식을 썼어요 — 희현님이 크롬에서 쿠팡 카테고리/
베스트 페이지를 직접 열어 "Save all as HAR with content"로 저장한 HAR 파일을 올리면, 그
안에 이미 담겨 있는 네트워크 응답(브라우저가 실제로 받은 데이터)에서 상품 목록처럼 보이는
JSON을 찾아 파싱해요.

*** 휴리스틱이 필요한 이유 ***
쿠팡 내부 API의 정확한 응답 스키마는 공개돼 있지 않고 페이지·카테고리마다 다를 수 있어요.
그래서 "상품명 같은 필드 + 가격 같은 필드를 함께 가진 딕셔너리가 여러 개 들어있는 배열"을
JSON 안에서 재귀적으로 찾아서, 그중 가장 그럴듯한(상품처럼 보이는 항목이 가장 많은) 배열을
상품 목록으로 채택해요. 실제 HAR 파일로 업로드해보면서 필드명이 안 맞으면 아래 *_KEYS
후보 목록에 실제 필드명을 추가하면 돼요.
"""
import base64
import json
import re

_NAME_KEYS = ["productname", "name", "itemname", "title", "displayname", "goodsname"]
_SALE_PRICE_KEYS = [
    "salesprice", "saleprice", "discountedprice", "finalprice", "price",
    "currentprice", "displaysaleprice",
]
_ORIGINAL_PRICE_KEYS = ["originalprice", "baseprice", "normalprice", "listprice", "regularprice"]
_DISCOUNT_KEYS = ["discountrate", "discountpercentage", "discount", "salesrate"]
_LINK_KEYS = ["productlink", "link", "url", "landingurl", "producturl", "href", "vendoritemurl", "detailurl"]
_ID_KEYS = ["productid", "itemid", "vendoritemid"]
_RANK_KEYS = ["rank", "ranking", "bestranking", "bestrank", "displayrank"]

_MIN_ITEMS = 3  # 이 개수 미만이면 "상품 목록"으로 보지 않아요 (우연히 필드가 겹칠 수 있어서)


def _lower_keys(d):
    return {str(k).lower(): v for k, v in d.items()} if isinstance(d, dict) else {}


def _find_key(d_lower, candidates):
    for c in candidates:
        if c in d_lower:
            return d_lower[c]
    return None


def _looks_like_product(d):
    d_lower = _lower_keys(d)
    return _find_key(d_lower, _NAME_KEYS) is not None and _find_key(d_lower, _SALE_PRICE_KEYS) is not None


def _score_list(lst):
    if not isinstance(lst, list) or len(lst) < _MIN_ITEMS:
        return 0
    matches = sum(1 for it in lst if isinstance(it, dict) and _looks_like_product(it))
    return matches if matches >= _MIN_ITEMS else 0


def _walk(obj, best):
    """obj를 재귀적으로 순회하며 가장 상품 목록다운 리스트를 찾아요.
    best는 [현재까지 최고 점수, 그 리스트] 형태의 2칸짜리 리스트예요(재귀 중 계속 갱신)."""
    if isinstance(obj, list):
        score = _score_list(obj)
        if score > best[0]:
            best[0] = score
            best[1] = obj
        for item in obj:
            _walk(item, best)
    elif isinstance(obj, dict):
        for v in obj.values():
            _walk(v, best)


def _to_int_price(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str):
        digits = re.sub(r"[^\d]", "", v)
        return int(digits) if digits else None
    return None


def _clean_link(v):
    if not v:
        return ""
    v = str(v)
    if v.startswith("http"):
        return v
    if v.startswith("/"):
        return "https://www.coupang.com" + v
    return v


def _extract_item(d, index):
    d_lower = _lower_keys(d)
    name = _find_key(d_lower, _NAME_KEYS)
    sale_price = _to_int_price(_find_key(d_lower, _SALE_PRICE_KEYS))
    original_price = _to_int_price(_find_key(d_lower, _ORIGINAL_PRICE_KEYS))
    discount_raw = _find_key(d_lower, _DISCOUNT_KEYS)
    try:
        discount_pct = int(discount_raw) if discount_raw not in (None, "") else None
    except (TypeError, ValueError):
        discount_pct = None

    link = _clean_link(_find_key(d_lower, _LINK_KEYS))
    if not link:
        pid = _find_key(d_lower, _ID_KEYS)
        if pid:
            link = f"https://www.coupang.com/vp/products/{pid}"

    rank_raw = _find_key(d_lower, _RANK_KEYS)
    try:
        rank = int(rank_raw) if rank_raw is not None else index + 1
    except (TypeError, ValueError):
        rank = index + 1

    return {
        "rank": rank,
        "product": str(name).strip() if name else "",
        "original_price": original_price,
        "discount_pct": discount_pct,
        "sale_price": sale_price,
        "link": link,
    }


def parse_coupang_har(raw_bytes, limit=50):
    """
    업로드된 쿠팡 페이지 HAR 파일(bytes)에서 상품 목록을 찾아 파싱해요.
    반환: (items, error)
      - 성공: (상품 목록, None). 상품 목록은 [{rank, product, original_price, discount_pct,
        sale_price, link}, ...] 형태이고 순위 오름차순, 최대 limit개예요.
      - 실패: ([], "안내 메시지")
    """
    try:
        har = json.loads(raw_bytes)
    except Exception:
        return [], "HAR 파일 형식을 인식하지 못했어요. 크롬 개발자도구 Network 탭에서 저장한 .har 파일이 맞는지 확인해 주세요."

    entries = (((har or {}).get("log") or {}).get("entries")) or []
    if not entries:
        return [], "HAR 파일 안에 네트워크 요청 기록이 없어요."

    best = [0, None]
    for entry in entries:
        try:
            content = ((entry.get("response") or {}).get("content") or {})
            text = content.get("text")
            if not text:
                continue
            mime = (content.get("mimeType") or "").lower()
            stripped = text.strip()
            if "json" not in mime and not stripped.startswith(("{", "[")):
                continue
            if content.get("encoding") == "base64":
                text = base64.b64decode(text).decode("utf-8", errors="ignore")
            data = json.loads(text)
        except Exception:
            continue
        _walk(data, best)

    if not best[1]:
        return [], (
            "이 HAR 파일에서 상품 목록 데이터를 찾지 못했어요. 쿠팡 카테고리/베스트 페이지를 "
            "끝까지 스크롤해서 상품을 모두 불러온 뒤 저장한 HAR 파일인지 확인해 주세요."
        )

    items = []
    for i, it in enumerate(best[1]):
        if not isinstance(it, dict) or not _looks_like_product(it):
            continue
        parsed = _extract_item(it, i)
        if not parsed["product"]:
            continue
        items.append(parsed)
        if len(items) >= limit:
            break

    if not items:
        return [], "상품 목록으로 보이는 데이터는 찾았지만 상품명을 읽어오지 못했어요."

    items.sort(key=lambda r: r["rank"])
    for i, it in enumerate(items, start=1):
        it["rank"] = i  # 원본 순위 필드가 없거나 뒤죽박죽이면 발견된 순서로 다시 매겨요
    return items, None
