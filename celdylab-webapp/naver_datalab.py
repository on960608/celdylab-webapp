"""
네이버 데이터랩 쇼핑인사이트 API — 브랜드 런치 플래너의 "네이버 트렌드" 탭 자동 새로고침용.

marketplace_scraper.py의 쇼핑검색 API와 같은 자격증명(NAVER_SHOPPING_CLIENT_ID/SECRET,
developers.naver.com 앱에 "데이터랩(쇼핑인사이트)" API를 추가로 등록해야 함)을 그대로 써요.
검색광고 API(NAVER_SEARCHAD_*)는 여기서는 필요 없어요.

가져오는 것:
1. 카테고리 클릭량 추이(상대지수, 최고값=100) — /v1/datalab/shopping/categories
2. 기기/성별/연령 비율 — /v1/datalab/shopping/category/device|gender|age
3. 인기 검색어 TOP N — /v1/datalab/shopping/category/keywords

기본 카테고리는 "생활/건강"(전체) — 플래너에 기존에 있던 스냅샷과 동일한 범위예요. 셀디랩이
파는 청소/주방/구강제품/침구/생활용품은 모두 이 카테고리 아래에 있어서, 이 앱에서는 세부
카테고리로 쪼개지 않고 "생활/건강" 전체 추이 하나만 봐요.

주의: 이 개발 샌드박스 환경은 네트워크 정책상 openapi.naver.com에 직접 접속이 막혀 있어서
(marketplace_scraper.py의 네이버 검색광고/쇼핑검색 API와 동일한 제약) 이 모듈은 실제로
호출해보지 못한 채로 작성됐어요. Railway 배포 환경에서 실제 API 키를 등록한 뒤 "네이버
트렌드" 탭의 "⚡ 자동 새로고침" 버튼으로 처음 실행할 때 정상 동작을 확인해 주세요. 만약
네이버 쪽 요청/응답 형식이 문서와 다르면(카테고리 ID 등), 오류 메시지가 그대로 화면에
표시되니 그걸 보고 조정하면 돼요 — 실패해도 기존 캡처 스냅샷은 그대로 남아있어서 화면이
깨지지는 않아요.
"""
import os
from datetime import date, timedelta

import requests

_TIMEOUT = 15
_BASE = "https://openapi.naver.com/v1/datalab/shopping"

# "생활/건강" 카테고리 전체 — 네이버 데이터랩 쇼핑인사이트 분야 코드.
# (청소/주방/구강제품/침구/생활용품 등 셀디랩 판매 카테고리가 모두 이 아래에 속해요)
DEFAULT_CATEGORY_ID = "50000008"
DEFAULT_CATEGORY_LABEL = "생활/건강"


def datalab_configured():
    return bool(os.environ.get("NAVER_SHOPPING_CLIENT_ID") and os.environ.get("NAVER_SHOPPING_CLIENT_SECRET"))


def _headers():
    return {
        "X-Naver-Client-Id": os.environ["NAVER_SHOPPING_CLIENT_ID"],
        "X-Naver-Client-Secret": os.environ["NAVER_SHOPPING_CLIENT_SECRET"],
        "Content-Type": "application/json",
    }


def _post(path, body):
    resp = requests.post(_BASE + path, headers=_headers(), json=body, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def fetch_trend_snapshot(category_id=DEFAULT_CATEGORY_ID, category_label=DEFAULT_CATEGORY_LABEL, days=31):
    """클릭량 추이 + 기기/성별/연령 비율 + 인기 검색어 TOP20을 한번에 가져와서, 플래너
    화면이 바로 쓸 수 있는 형태로 정리해요.
    반환: (snapshot_dict, error) — 실패하면 snapshot_dict=None, error에 안내 메시지."""
    end = date.today()
    start = end - timedelta(days=days)
    start_s, end_s = start.isoformat(), end.isoformat()

    try:
        trend = _post("/categories", {
            "startDate": start_s, "endDate": end_s, "timeUnit": "date",
            "category": [{"name": category_label, "param": [category_id]}],
        })
        series = [
            {"date": row.get("period", ""), "ratio": row.get("ratio", 0)}
            for row in (trend.get("results") or [{}])[0].get("data", [])
        ]
    except Exception as e:
        return None, f"클릭량 추이 조회 실패 ({e.__class__.__name__})"

    def _ratio_map(path):
        try:
            res = _post(path, {
                "startDate": start_s, "endDate": end_s, "timeUnit": "date",
                "category": category_id,
            })
            return {row.get("name", ""): row.get("data", []) for row in res.get("results", [])}
        except Exception:
            return {}

    device = _ratio_map("/category/device")
    gender = _ratio_map("/category/gender")
    age = _ratio_map("/category/age")

    def _avg_ratio(rows):
        vals = [r.get("ratio", 0) for r in rows if isinstance(r, dict)]
        return round(sum(vals) / len(vals), 1) if vals else None

    mobile_pct = _avg_ratio(device.get("모바일", []))
    pc_pct = _avg_ratio(device.get("PC", []))
    female_pct = _avg_ratio(gender.get("여성", []))
    male_pct = _avg_ratio(gender.get("남성", []))
    top_ages = sorted(
        [(name, _avg_ratio(rows) or 0) for name, rows in age.items()],
        key=lambda x: -x[1],
    )[:2]
    age_group = " · ".join(name for name, _ in top_ages) if top_ages else ""

    try:
        kw_res = _post("/category/keywords", {
            "startDate": start_s, "endDate": end_s, "timeUnit": "date",
            "category": category_id, "page": 1, "count": 20,
        })
        keywords = [row.get("keyword", "") for row in kw_res.get("ranks", []) if row.get("keyword")]
    except Exception:
        keywords = []

    snapshot = {
        "category": category_label,
        "range_label": f"{start_s.replace('-', '.')} ~ {end_s.replace('-', '.')}",
        "mobile_pct": mobile_pct,
        "desktop_pct": pc_pct,
        "female_pct": female_pct,
        "male_pct": male_pct,
        "age_group": age_group,
        "keywords": keywords,
        "series": series,
    }
    return snapshot, None

