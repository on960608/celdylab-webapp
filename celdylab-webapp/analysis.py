"""
시딩 인사이트 / 공구 성과 / 리스트업 판정에서 공통으로 쓰는 계산식.
기존 오프라인 트래커(seeding-gongu-tracker.html)의 자바스크립트 공식을 그대로 옮겼어요.
"""
from datetime import date, datetime

BRANDS = ["코드니처", "빠이러스", "라이프스타일마트"]
TREND_PLATFORMS = ["캘린", "82market", "위시버니", "지금하는공구", "인공", "공구모아"]
TREND_CATEGORIES = ["리빙", "여행", "홈인테리어", "패션잡화", "주방용품", "생활용품", "기타"]

# 인플루언서 공동구매(공구)가 활발히 진행되는 모니터링 대상 플랫폼
TREND_PLATFORM_LINKS = [
    {"name": "캘린 (Calen)", "url": "https://www.calen.co.kr/", "desc": "인플루언서 공동구매"},
    {"name": "82market", "url": "https://www.82market.com/", "desc": "인플루언서 공구 마켓"},
    {"name": "위시버니 (드랍)", "url": "https://www.wishbunny.me/drop", "desc": "공구 일정·알림"},
    {"name": "지금하는공구", "url": "https://www.09now.com/", "desc": "인스타 공구 검색엔진"},
    {"name": "인공 (IN gong)", "url": "https://insta-gong.com/category/kitchen-clean", "desc": "주방/청소 특화 인스타 공구 모음"},
    {"name": "공구모아", "url": "https://gonggumoa.com/", "desc": "공구 일정·인기 공구 통합 모음"},
]


# ---------------------------------------------------------------------------
# 시딩 인사이트
# ---------------------------------------------------------------------------

def insight_metrics(r):
    """r: dict-like (views, likes, comments, saves, shares, followers)"""
    views = r["views"] or 0
    followers = r["followers"] or 0
    engagement = ((r["likes"] or 0) + (r["comments"] or 0) + (r["saves"] or 0) + (r["shares"] or 0)) / views * 100 if views else 0
    save_rate = (r["saves"] or 0) / views * 100 if views else 0
    reach_rate = views / followers * 100 if followers else 0
    return {"engagement": engagement, "save_rate": save_rate, "reach_rate": reach_rate}


def pct(n):
    return f"{(n or 0):.1f}%"


def won(n):
    return f"{round(n or 0):,}원"


# ---------------------------------------------------------------------------
# 협찬 인원 리스트업 — STEP 02 · 5가지 탈락 기준 + 반응점수(1,000점)
# ---------------------------------------------------------------------------

def listup_score(c):
    avg_views = ((c["views1"] or 0) + (c["views2"] or 0) + (c["views3"] or 0)) / 3
    return round(avg_views / 10 + (c["comments"] or 0) * 2 + (c["shares"] or 0) * 4)


def days_since(date_str):
    if not date_str:
        return None
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    return (date.today() - d).days


def listup_exclusion_reasons(c):
    reasons = []
    avg_views = ((c["views1"] or 0) + (c["views2"] or 0) + (c["views3"] or 0)) / 3
    if 0 < avg_views < 10000:
        reasons.append(f"① 최근 릴스 조회수 낮음(평균 {round(avg_views):,})")
    if not c["has_real_comments"]:
        reasons.append("② 실제 관심 댓글 없음")
    likes = c["likes"] or 0
    if likes and ((c["comments"] or 0) + (c["shares"] or 0)) / likes * 100 < 1:
        reasons.append("③ 좋아요 대비 반응 낮음")
    if c["sponsored_low"]:
        reasons.append("④ 협찬 콘텐츠 반응 낮음")
    d = days_since(c["last_upload"])
    if d is not None and d >= 14:
        reasons.append(f"⑤ 최근 활동 없음({d}일 경과)")
    return reasons


def listup_verdict(c):
    score = listup_score(c)
    reasons = listup_exclusion_reasons(c)
    if score < 1000:
        reasons = [f"반응점수 미달({score:,}점)"] + reasons
    if not reasons:
        return {"pass": True, "exception": False, "reasons": [], "score": score}
    if c["reason"]:
        return {"pass": True, "exception": True, "reasons": reasons, "score": score}
    return {"pass": False, "exception": False, "reasons": reasons, "score": score}


# ---------------------------------------------------------------------------
# 공구 성과 분석
# ---------------------------------------------------------------------------

def gongu_net_sold(r):
    return max(0, (r["sold_qty"] or 0) - (r["return_qty"] or 0))


def gongu_return_pct(r):
    return (r["return_qty"] or 0) / r["sold_qty"] * 100 if r["sold_qty"] else 0


def gongu_per1k(r):
    return (r["revenue"] or 0) / r["followers"] * 1000 if r["followers"] else 0


def gongu_tier(followers):
    n = followers or 0
    if n < 10000:
        return "1만 미만"
    if n < 30000:
        return "1만~3만"
    if n < 50000:
        return "3만~5만"
    if n < 100000:
        return "5만~10만"
    if n < 300000:
        return "10만~30만"
    return "30만 이상"


TIER_ORDER = ["1만 미만", "1만~3만", "3만~5만", "5만~10만", "10만~30만", "30만 이상"]


# ---------------------------------------------------------------------------
# 댓글 이벤트 추첨
# ---------------------------------------------------------------------------
import random
import re


def extract_ig_shortcode(url):
    """인스타그램 게시물/릴스 URL에서 짧은 코드를 추출해요. 못 찾으면 None."""
    m = re.search(r"instagram\.com/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)", url or "")
    return m.group(1) if m else None


def parse_comments_text(raw_text):
    """
    한 줄에 '아이디: 댓글내용' 형식의 텍스트를 댓글 목록으로 변환해요.
    콜론이 없으면 그 줄 전체를 아이디로, 댓글내용은 빈 문자열로 처리해요.
    """
    comments = []
    for line in (raw_text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if ":" in line:
            username, text = line.split(":", 1)
        elif "：" in line:  # 전각 콜론도 지원
            username, text = line.split("：", 1)
        else:
            username, text = line, ""
        username = username.strip().lstrip("@")
        text = text.strip()
        if username:
            comments.append({"username": username, "text": text})
    return comments


_USERNAME_HEADER_KEYS = ["username", "아이디", "계정", "인스타그램아이디", "인스타아이디", "id", "instagram"]
_COMMENT_HEADER_KEYS = ["comment", "댓글", "댓글내용", "text", "content", "내용"]


def _norm_header(h):
    return str(h or "").strip().replace(" ", "").lower()


def _find_col(headers, keys):
    for i, h in enumerate(headers):
        nh = _norm_header(h)
        if not nh:
            continue
        for k in keys:
            nk = _norm_header(k)
            if nh == nk or nk in nh or nh in nk:
                return i
    return None


def parse_comments_spreadsheet(file_storage):
    """
    업로드된 .csv 또는 .xlsx 파일에서 '아이디'/'댓글' 열을 찾아 댓글 목록으로 변환해요.
    (username, comment) 두 열 이름은 유사한 표현(아이디/계정/username, 댓글/comment/내용 등)을 자동으로 인식해요.
    반환: (comments, error)
    """
    filename = (file_storage.filename or "").lower()
    rows = []
    try:
        if filename.endswith(".xlsx"):
            import openpyxl
            wb = openpyxl.load_workbook(file_storage, read_only=True, data_only=True)
            ws = wb.active
            for row in ws.iter_rows(values_only=True):
                rows.append(list(row))
        else:
            import csv
            import io
            raw = file_storage.read()
            for enc in ("utf-8-sig", "cp949", "utf-8"):
                try:
                    text = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                return None, "파일 인코딩을 인식하지 못했어요. UTF-8 또는 CSV(쉼표 구분) 형식으로 저장해 주세요."
            reader = csv.reader(io.StringIO(text))
            rows = [row for row in reader]
    except Exception as e:
        return None, f"파일을 읽는 중 오류가 발생했어요: {e}"

    rows = [r for r in rows if any(c not in (None, "") for c in r)]
    if not rows:
        return None, "빈 파일이에요."

    headers = [str(c) if c is not None else "" for c in rows[0]]
    uname_idx = _find_col(headers, _USERNAME_HEADER_KEYS)
    comment_idx = _find_col(headers, _COMMENT_HEADER_KEYS)

    if uname_idx is None:
        # 헤더를 못 찾으면 1열=아이디, 2열=댓글로 간주(헤더 없이 바로 데이터가 시작하는 경우)
        uname_idx, comment_idx = 0, (1 if len(headers) > 1 else None)
        data_rows = rows
    else:
        data_rows = rows[1:]

    comments = []
    for r in data_rows:
        if uname_idx >= len(r):
            continue
        username = str(r[uname_idx] or "").strip().lstrip("@")
        if not username:
            continue
        text = str(r[comment_idx]).strip() if (comment_idx is not None and comment_idx < len(r) and r[comment_idx] is not None) else ""
        comments.append({"username": username, "text": text})

    if not comments:
        return None, "파일에서 아이디 열을 찾지 못했어요. 열 이름을 '아이디'/'username'과 '댓글'/'comment'로 맞춰 주세요."
    return comments, None


def draw_giveaway_winners(comments, event_type, keyword, winner_count, excluded_raw):
    """
    반환: (winners, stats)
    winners: [{rank, username, comment, keyword_matched}]
    stats: {total_comments, matched_accounts, final_pool_count, shortage: bool}
    """
    excluded = {
        e.strip().lower().lstrip("@")
        for e in re.split(r"[,\n]+", excluded_raw or "")
        if e.strip()
    }

    total_comments = len(comments)

    # 계정별로 묶기 (동일 계정 여러 댓글 -> 1명)
    by_user = {}
    for c in comments:
        key = c["username"].lower()
        by_user.setdefault(key, {"username": c["username"], "texts": []})
        by_user[key]["texts"].append(c["text"])

    # 1) 조건(키워드) 충족 계정 추리기 — 제외 계정 필터 전
    matched = []
    for key, info in by_user.items():
        if event_type == "keyword":
            hit_text = next((t for t in info["texts"] if keyword and keyword in t), None)
            if hit_text is None:
                continue
            matched.append({"key": key, "username": info["username"], "comment": hit_text, "keyword_matched": 1})
        else:
            matched.append({"key": key, "username": info["username"], "comment": info["texts"][0], "keyword_matched": None})

    matched_accounts = len(matched)

    # 2) 제외 계정(본인/브랜드 등) 필터링 -> 최종 추첨 대상
    final_pool = [m for m in matched if m["key"] not in excluded]
    final_pool_count = len(final_pool)

    shortage = final_pool_count < winner_count
    n = min(winner_count, final_pool_count) if winner_count > 0 else 0
    picked = random.sample(final_pool, n) if n > 0 else []
    winners = [
        {"rank": i + 1, "username": w["username"], "comment": w["comment"], "keyword_matched": w["keyword_matched"]}
        for i, w in enumerate(picked)
    ]

    stats = {
        "total_comments": total_comments,
        "matched_accounts": matched_accounts,
        "final_pool_count": final_pool_count,
        "shortage": shortage,
    }
    return winners, stats


def fetch_ig_comments_via_graph_api(post_url):
    """
    셀디랩이 직접 운영하는 인스타그램 비즈니스 계정에 연동된 게시물의 댓글을 Graph API로 가져와요.
    INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_BUSINESS_ID 환경변수가 없으면 (None, 안내 메시지)를 돌려줘요.
    타사 계정 게시물은 이 방식으로 절대 가져올 수 없어요 (Graph API 자체 제약).
    """
    import os
    import requests

    token = os.environ.get("INSTAGRAM_ACCESS_TOKEN")
    ig_user_id = os.environ.get("INSTAGRAM_BUSINESS_ID")
    if not token or not ig_user_id:
        return None, "INSTAGRAM_ACCESS_TOKEN / INSTAGRAM_BUSINESS_ID 환경변수가 설정되어 있지 않아요. 아래 '댓글 직접 붙여넣기'를 이용해 주세요."

    shortcode = extract_ig_shortcode(post_url)
    if not shortcode:
        return None, "인스타그램 게시물/릴스 링크 형식을 인식하지 못했어요."

    api_version = "v21.0"
    base = f"https://graph.facebook.com/{api_version}"

    # 1) 연동 계정의 미디어 목록에서 permalink가 일치하는 게시물의 media id 찾기
    media_id = None
    url = f"{base}/{ig_user_id}/media"
    params = {"fields": "id,permalink", "access_token": token, "limit": 50}
    for _ in range(20):  # 최대 20페이지(=1000개)까지만 탐색
        try:
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()
        except Exception as e:
            return None, f"인스타그램 API 요청 중 오류: {e}"
        if "error" in data:
            return None, data["error"].get("message", "Graph API 오류가 발생했어요.")
        for item in data.get("data", []):
            if shortcode in (item.get("permalink") or ""):
                media_id = item["id"]
                break
        if media_id:
            break
        next_url = data.get("paging", {}).get("next")
        if not next_url:
            break
        url, params = next_url, None

    if not media_id:
        return None, "연동된 인스타그램 계정에서 이 링크의 게시물을 찾지 못했어요 (다른 계정의 게시물이거나, 최근 미디어 목록 범위 밖일 수 있어요)."

    # 2) 해당 게시물의 댓글 전체(페이지네이션) 가져오기
    comments = []
    url = f"{base}/{media_id}/comments"
    params = {"fields": "username,text,timestamp", "access_token": token, "limit": 100}
    for _ in range(50):  # 최대 5,000개 댓글까지
        try:
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()
        except Exception as e:
            return None, f"댓글 조회 중 오류: {e}"
        if "error" in data:
            return None, data["error"].get("message", "Graph API 오류가 발생했어요.")
        for c in data.get("data", []):
            comments.append({"username": c.get("username", ""), "text": c.get("text", "")})
        next_url = data.get("paging", {}).get("next")
        if not next_url:
            break
        url, params = next_url, None

    return comments, None


# ---------------------------------------------------------------------------
# 매출 기회 발굴 대시보드 — 상품군 매칭 / Trend Score / 상품기회점수
#
# 원칙: 확보하지 못한 데이터를 0이나 평균값으로 대신 채우지 않아요. 지표가 없으면
# 계산에서 그냥 빼고, "몇 개 지표 중 몇 개로 계산됐는지"를 항상 함께 보여줘요.
# ---------------------------------------------------------------------------

OPPORTUNITY_CATEGORIES = ["리빙", "청소", "살림", "욕실", "주방", "세탁", "수납", "생활용품"]

TREND_SCORE_WEIGHTS = {
    "search_interest": 35,     # 검색 관심도 (네이버/구글 상대지수)
    "mom_growth": 25,          # 전월 대비 상승률
    "recent_velocity": 15,     # 최근 상승 속도
    "platform_overlap": 15,    # 여러 공구 플랫폼 동시 등장 정도
    "groupbuy_exposure": 10,   # 공구 시장 노출 빈도
}


def _tokenize(text):
    """아주 단순한 키워드 비교용 토크나이저 — 공백/쉼표/슬래시로 나누고 소문자화해요.
    임베딩·형태소 분석 없이도 '겹치는 단어가 있는지'를 투명하게 설명할 수 있게 하는 게 목적이에요."""
    text = (text or "").lower()
    parts = re.split(r"[,\s/·]+", text)
    return {p for p in parts if p}


def product_group_fit_score(group_terms, product_keywords, product_text_fields):
    """
    상품군 키워드 집합과 자사 제품의 (키워드 + 카테고리/용도/문제/니즈 텍스트)를 비교해
    0~100 적합도와 겹치는 단어 목록을 반환해요.
    단순 제품명 일치가 아니라 카테고리/용도/문제/니즈 텍스트까지 포함해서 비교하지만,
    AI 임베딩 기반이 아니라 '단어 겹침' 기준이라 왜 이 점수가 나왔는지 항상 설명 가능해요.
    """
    group_tokens = set()
    for t in group_terms:
        group_tokens |= _tokenize(t)

    product_tokens = set()
    for k in product_keywords:
        product_tokens |= _tokenize(k)
    for f in product_text_fields:
        product_tokens |= _tokenize(f)

    if not group_tokens or not product_tokens:
        return 0.0, []

    matched = group_tokens & product_tokens
    if not matched:
        return 0.0, []
    score = len(matched) / len(group_tokens | product_tokens) * 100
    return round(score, 1), sorted(matched)


def compute_trend_score(metrics):
    """
    metrics: {"search_interest", "mom_growth", "recent_velocity", "platform_overlap", "groupbuy_exposure"}
    각 값은 0~100으로 이미 정규화되어 있다고 가정하고, 없는 지표(None)는 계산에서 제외해요.
    반환: {"score": float|None, "used": [...], "missing": [...]}
    """
    used, missing, weighted_sum, weight_sum = [], [], 0.0, 0.0
    for key, w in TREND_SCORE_WEIGHTS.items():
        v = metrics.get(key)
        if v is None:
            missing.append(key)
            continue
        used.append(key)
        weighted_sum += max(0.0, min(100.0, v)) * w
        weight_sum += w
    if weight_sum == 0:
        return {"score": None, "used": used, "missing": missing}
    return {"score": round(weighted_sum / weight_sum, 1), "used": used, "missing": missing}


def groupbuy_exposure_metrics(records_for_group, all_platforms, days=30):
    """
    records_for_group: 이 상품군으로 태깅된 trend_records(dict, check_date/platform 포함) 목록.
    반환: platform_overlap(0~100, 몇 개 플랫폼에서 동시 등장했는지 비율),
          groupbuy_exposure(0~100, 최근 노출 빈도 기준), recent_count, platforms(set),
          is_new(최근 처음 등장), is_recurring(서로 다른 달에 반복 등장)
    """
    from datetime import date, timedelta

    if not records_for_group:
        return {
            "platform_overlap": None, "groupbuy_exposure": None,
            "recent_count": 0, "platforms": set(), "is_new": False, "is_recurring": False,
        }

    platforms = {r["platform"] for r in records_for_group if r["platform"]}
    platform_overlap = (len(platforms) / len(all_platforms) * 100) if all_platforms else None

    cutoff = (date.today() - timedelta(days=days)).isoformat()
    recent = [r for r in records_for_group if (r["check_date"] or "") >= cutoff]
    # 노출 빈도를 0~100으로 캡(10회 이상 등록 시 만점) — 데이터가 더 쌓이면 기준을 조정할 수 있어요.
    groupbuy_exposure = min(len(recent) / 10 * 100, 100)

    dates_sorted = sorted(r["check_date"] for r in records_for_group if r["check_date"])
    is_new = bool(dates_sorted) and dates_sorted[0] >= cutoff
    is_recurring = len({d[:7] for d in dates_sorted if len(d) >= 7}) >= 2

    return {
        "platform_overlap": platform_overlap,
        "groupbuy_exposure": groupbuy_exposure,
        "recent_count": len(recent),
        "platforms": platforms,
        "is_new": is_new,
        "is_recurring": is_recurring,
    }


def summarize_groupbuy_exposure(records, groups, all_platforms):
    """
    records: trend_records(dict) 전체, groups: trend_keyword_groups 목록.
    상품군이 태깅된 기록만 모아 노출 지표를 계산하고, 플랫폼 동시 등장 수 -> 최근 등록 수 순으로 정렬해요.
    """
    summaries = []
    for g in groups:
        g_records = [r for r in records if r.get("product_group_id") == g["id"]]
        if not g_records:
            continue
        metrics = groupbuy_exposure_metrics(g_records, all_platforms)
        summaries.append({"group": g, "records": g_records, **metrics})
    summaries.sort(key=lambda s: (-len(s["platforms"]), -s["recent_count"]))
    return summaries


def compute_group_trend_metrics(records_for_group, all_platforms, monthly_search_points):
    """
    한 상품군의 Trend Score 계산에 필요한 지표를 모아요.
    monthly_search_points: [{"year_month": "YYYY-MM", "value": float}, ...] — 소스 구분 없이
    이미 대표값으로 합쳐서 넘겨받아요(예: 네이버 있으면 네이버, 없으면 구글).
    반환: (metrics_dict, exposure_detail)
    """
    exposure = groupbuy_exposure_metrics(records_for_group, all_platforms)
    growth = mom_growth_and_velocity(monthly_search_points)
    latest_search = None
    if monthly_search_points:
        latest_search = sorted(monthly_search_points, key=lambda p: p["year_month"])[-1]["value"]
    metrics = {
        "search_interest": latest_search,
        "mom_growth": growth["mom_growth"],
        "recent_velocity": growth["recent_velocity"],
        "platform_overlap": exposure["platform_overlap"],
        "groupbuy_exposure": exposure["groupbuy_exposure"],
    }
    return metrics, exposure


def mom_growth_and_velocity(monthly_points):
    """
    monthly_points: [{"year_month": "YYYY-MM", "value": float}, ...] (순서 무관, 같은 소스 내 지수만 사용)
    전월 대비 상승률(%)과 최근 상승 속도(0~100 정규화)를 계산해요.
    2개 달 미만이면 계산할 수 없으니 None을 돌려줘요(임의로 0%로 채우지 않음).
    """
    pts = sorted([p for p in monthly_points if p.get("value") is not None], key=lambda p: p["year_month"])
    if len(pts) < 2:
        return {"mom_growth": None, "recent_velocity": None}

    prev, last = pts[-2]["value"], pts[-1]["value"]
    mom_growth = ((last - prev) / prev * 100) if prev else None

    # 최근 상승 속도 = 최근 구간 상승률을 0~100으로 캡한 값(음수는 0으로) — 급상승 판정에만 씀
    recent_velocity = None
    if mom_growth is not None:
        recent_velocity = max(0.0, min(mom_growth, 100.0))

    return {"mom_growth": mom_growth, "recent_velocity": recent_velocity}


def fetch_google_trends_for_group(group_name, terms, timeframe="today 3-m", geo="KR"):
    """
    Google은 공식 검색 트렌드 API가 없어서 비공식 라이브러리(pytrends)로 시도해요.
    실패(라이브러리 미설치/네트워크 차단/일시적 차단 등)하면 예외를 삼키고 (None, 에러메시지)를 돌려줘요 —
    이 함수가 실패해도 대시보드 전체가 죽지 않고 그냥 "구글 지표 없음"으로 처리돼요.
    반환: (index_value 0~100 | None, error_message | None)
    """
    try:
        from pytrends.request import TrendReq
    except ImportError:
        return None, "pytrends 라이브러리가 설치되어 있지 않아요."

    try:
        pytrends = TrendReq(hl="ko-KR", tz=540)
        keywords = (terms or [group_name])[:5]  # pytrends는 한 번에 최대 5개 키워드까지만 허용
        pytrends.build_payload(keywords, timeframe=timeframe, geo=geo)
        df = pytrends.interest_over_time()
        if df is None or df.empty:
            return None, "구글 트렌드에서 데이터를 찾지 못했어요."
        # 여러 키워드의 최근 값 중 최댓값을 이 상품군의 대표 지수로 사용
        latest = df.iloc[-1]
        value = max(float(latest[k]) for k in keywords if k in latest.index)
        return round(value, 1), None
    except Exception as e:  # 네트워크 오류, 일시 차단(429) 등 — 보조 지표라 조용히 생략
        return None, f"구글 트렌드 조회 실패(생략됨): {e}"


def fetch_naver_trends_for_group(group_name, terms, months=6):
    """
    네이버 데이터랩 검색어트렌드 API(공식)로 상품군의 월별 상대 검색지수(0~100)를 가져와요.
    한 번 호출로 최근 {months}개월치 월별 지수를 한꺼번에 받아와요(전월 대비 상승률 계산에 필요).
    NAVER_CLIENT_ID/SECRET이 없거나 요청이 실패하면 예외를 삼키고 (빈 목록, 에러메시지)를 돌려줘요 —
    이 함수가 실패해도 대시보드 전체가 죽지 않고 그냥 "네이버 지표 없음"으로 처리돼요.
    반환: (points, error) — points: [{"year_month": "YYYY-MM", "value": float}, ...]
    """
    import os
    import json as _json
    from datetime import date as _date

    client_id = os.environ.get("NAVER_CLIENT_ID")
    client_secret = os.environ.get("NAVER_CLIENT_SECRET")
    if not (client_id and client_secret):
        return [], "NAVER_CLIENT_ID / NAVER_CLIENT_SECRET이 설정되어 있지 않아요."

    keywords = (terms or [group_name])[:20]  # 네이버 데이터랩은 그룹당 최대 20개 키워드까지 허용

    end = _date.today()
    y, m = end.year, end.month - months
    while m <= 0:
        m += 12
        y -= 1
    start = _date(y, m, 1)

    payload = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "timeUnit": "month",
        "keywordGroups": [{"groupName": group_name, "keywords": keywords}],
    }
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
        "Content-Type": "application/json",
    }

    try:
        import requests
        resp = requests.post(
            "https://openapi.naver.com/v1/datalab/search",
            headers=headers, data=_json.dumps(payload), timeout=10,
        )
    except Exception as e:
        return [], f"네이버 API 요청 중 오류: {e}"

    if resp.status_code != 200:
        return [], f"네이버 API 오류(status {resp.status_code}): {resp.text[:200]}"

    try:
        data = resp.json()
        result = data["results"][0]
        points = [
            {"year_month": d["period"][:7], "value": float(d["ratio"])}
            for d in result.get("data", [])
        ]
    except Exception as e:
        return [], f"네이버 응답을 해석하지 못했어요: {e}"

    return points, None


def compute_opportunity_score(trend_score, seeding_score, gongu_score, fit_score, weights):
    """
    weights: {"trend_weight","seeding_weight","gongu_weight","fit_weight"} (합계가 꼭 100일 필요는 없음 — 비율로 계산)
    각 점수 중 None인 항목은 제외하고, 남은 항목의 가중치 비율로 재계산해요.
    """
    components = {
        "trend": (trend_score, weights.get("trend_weight", 0)),
        "seeding": (seeding_score, weights.get("seeding_weight", 0)),
        "gongu": (gongu_score, weights.get("gongu_weight", 0)),
        "fit": (fit_score, weights.get("fit_weight", 0)),
    }
    used, missing, weighted_sum, weight_sum = [], [], 0.0, 0.0
    for key, (value, w) in components.items():
        if value is None:
            missing.append(key)
            continue
        used.append(key)
        weighted_sum += value * w
        weight_sum += w
    if weight_sum == 0:
        return {"score": None, "used": used, "missing": missing}
    return {"score": round(weighted_sum / weight_sum, 1), "used": used, "missing": missing}
