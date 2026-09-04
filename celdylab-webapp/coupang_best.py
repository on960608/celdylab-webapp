"""
쿠팡 베스트 — HAR 파일 업로드로 순위를 읽어와요.

쿠팡은 브라우저 자동화 도구 접속 자체가 막혀 있고("이 사이트는 안전 정책에 따라 허용되지
않습니다") 공식 검색량 API도 없어서, 인스타 댓글 추출 기능(igcomments.py/analysis.py)과
똑같은 방식으로 처리해요: 희현님이 실제 로그인된 브라우저에서 반영하고 싶은 카테고리의
베스트/랭킹 페이지를 HAR 파일로 저장해서 올리면, 그 안에 담긴 네트워크 응답 중 상품 목록처럼
생긴 JSON 배열을 찾아서 순위·상품명·가격·링크를 읽어와요. 검색량 API가 없어서 검색수 없이
쿠팡 자체 순위만 표시돼요.

파싱은 "완전히 정확한 스키마"를 가정하지 않고, 상품 데이터처럼 보이는 필드 조합(이름 계열
키 + 가격 계열 키)을 가진 딕셔너리가 3개 이상 모여 있는 배열을 찾는 휴리스틱이에요. 쿠팡이
API 응답 구조를 바꾸면 이 파싱도 깨질 수 있는데, 그때는 빈 결과 대신 "찾지 못했다"는 안내
메시지를 보여줘요(trend.py에서 카테고리별로 각각 처리하니 다른 카테고리에는 영향 없어요).
"""
import json

from analysis import load_har_entries

_PRODUCT_NAME_KEYS = ("productName", "itemName", "name", "title", "vendorItemName", "goodsName")
_PRICE_KEYS = ("salePrice", "price", "finalPrice", "discountedPrice", "couponPrice", "displayPrice")
_ORIGINAL_PRICE_KEYS = ("originalPrice", "basePrice", "listPrice", "normalPrice")
_RANK_KEYS = ("rank", "ranking", "bestRank", "order", "displayRank")
_ID_KEYS = ("productId", "itemId", "vendorItemId", "goodsId")
_URL_KEYS = ("productUrl", "landingUrl", "url", "link", "detailUrl")

_MIN_LIST_MATCHES = 3  # 이 이상 모여 있어야 "상품 목록"으로 인정해요(우연히 섞인 잡음 방지)


def _looks_like_product(d):
    if not isinstance(d, dict):
        return False
    has_name = any(isinstance(d.get(k), str) and d.get(k, "").strip() for k in _PRODUCT_NAME_KEYS)
    has_price = any(isinstance(d.get(k), (int, float)) and not isinstance(d.get(k), bool) for k in _PRICE_KEYS)
    return has_name and has_price


def _extract_product_fields(d):
    name = next((d[k] for k in _PRODUCT_NAME_KEYS if isinstance(d.get(k), str) and d.get(k, "").strip()), "")
    price = next((d[k] for k in _PRICE_KEYS if isinstance(d.get(k), (int, float)) and not isinstance(d.get(k), bool)), None)
    original = next((d[k] for k in _ORIGINAL_PRICE_KEYS if isinstance(d.get(k), (int, float)) and not isinstance(d.get(k), bool)), None)
    rank = next((d[k] for k in _RANK_KEYS if isinstance(d.get(k), (int, float)) and not isinstance(d.get(k), bool)), None)
    link = next((d[k] for k in _URL_KEYS if isinstance(d.get(k), str) and d.get(k)), "")
    if not link:
        pid = next((d[k] for k in _ID_KEYS if d.get(k)), None)
        if pid:
            link = f"https://www.coupang.com/vp/products/{pid}"
    if link and not link.startswith("http"):
        link = "https://www.coupang.com" + link

    discount_pct = None
    if original and price and original > 0 and original >= price:
        discount_pct = round((1 - price / original) * 100)

    return {
        "product": str(name).strip(),
        "sale_price": int(price) if price is not None else None,
        "original_price": int(original) if original is not None else None,
        "discount_pct": discount_pct,
        "link": link,
        "rank": int(rank) if rank is not None else None,
        "keyword": None,
        "search_count": None,
    }


def _find_product_lists(node, found_lists, depth=0):
    if depth > 30:  # 너무 깊은 재귀는 방지해요
        return
    if isinstance(node, list):
        matches = [x for x in node if _looks_like_product(x)]
        if len(matches) >= _MIN_LIST_MATCHES:
            found_lists.append(matches)
        for x in node:
            _find_product_lists(x, found_lists, depth + 1)
    elif isinstance(node, dict):
        for v in node.values():
            _find_product_lists(v, found_lists, depth + 1)


def _response_json(entry):
    try:
        content = (entry.get("response") or {}).get("content") or {}
        text = content.get("text")
        if not text:
            return None
        if content.get("encoding") == "base64":
            import base64
            try:
                text = base64.b64decode(text).decode("utf-8", errors="ignore")
            except Exception:
                return None
        text = text.strip()
        if not text or text[0] not in "{[":
            return None
        return json.loads(text)
    except Exception:
        return None


def parse_coupang_har(raw_bytes, limit=50):
    """HAR 파일 bytes에서 상품 목록으로 보이는 JSON 배열을 찾아 순위 데이터로 바꿔줘요.
    가장 많은 상품이 매칭된 배열을 채택해요(그게 실제 목록 응답일 가능성이 가장 높아요).
    반환: (items, error) — 실패하면 items=[], error에 사람이 읽을 안내 메시지."""
    entries, error = load_har_entries(raw_bytes)
    if error:
        return [], error

    found_lists = []
    for entry in entries:
        data = _response_json(entry)
        if data is None:
            continue
        _find_product_lists(data, found_lists)

    if not found_lists:
        return [], (
            "이 HAR 파일에서 상품 목록 데이터를 찾지 못했어요. 쿠팡 카테고리 베스트/랭킹 "
            "페이지에서 상품이 다 보이도록 끝까지 스크롤한 뒤, 개발자도구 Network 탭에서 "
            "'Save all as HAR with content'로 저장했는지 확인해 주세요."
        )

    best = max(found_lists, key=len)
    items = []
    seen = set()
    for raw in best:
        f = _extract_product_fields(raw)
        if not f["product"] or f["product"] in seen:
            continue
        seen.add(f["product"])
        f["rank"] = f["rank"] or (len(items) + 1)
        items.append(f)
        if len(items) >= limit:
            break

    items.sort(key=lambda r: r["rank"])
    return items, None
