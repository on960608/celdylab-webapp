import os
from datetime import date, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify

import db
import naver_rank
from analysis import (
    TREND_PLATFORMS, TREND_CATEGORIES, TREND_PLATFORM_LINKS, OPPORTUNITY_CATEGORIES,
    NAVER_SHOPPING_CATEGORIES, summarize_groupbuy_exposure,
    fetch_naver_shopping_insight, donut_chart, trend_sparkline_points,
)

trend_bp = Blueprint("trend", __name__, url_prefix="/trend")

# 인기검색어 TOP100(비공식) 전용 분야 목록 — 위 NAVER_SHOPPING_CATEGORIES(추이 차트용, 공식 API)와는
# 다른 목록이에요. 셀디랩 제품과 관련 있는 분야만 추려서 naver_rank.py에 이미 정해져 있어요.
NAVER_RANK_CATEGORIES = list(naver_rank.CATEGORIES.items())
NAVER_RANK_DEFAULT_CID = naver_rank.CATEGORIES["생활/건강"]  # 지인이 "생활/건강 전체 하나만" 매일 모으기로 정함
NAVER_RANK_AGE_OPTIONS = naver_rank.AGES


@trend_bp.before_request
def _require_login():
    # /trend/api/* 는 브라우저 로그인 세션이 아니라 자체 API 키로 인증해요 (Cowork 등 서버-투-서버 호출용)
    if request.path.startswith("/trend/api/"):
        return
    if not session.get("user_id"):
        return redirect(url_for("login", next=request.path))


def _most_common(values):
    values = [v for v in values if v]
    if not values:
        return None
    counts = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return max(counts, key=counts.get)


PLATFORM_SELLER_CAP = 20


def _dedupe_keep_order(values):
    seen = []
    for v in values:
        v = (v or "").strip()
        if v and v not in seen:
            seen.append(v)
    return seen


def _common_seller_analysis(seller_rows):
    """플랫폼별로 등록된 인기셀러를 이름 기준으로 묶어서, 여러 플랫폼에 공통으로
    등록된 셀러를 우선 정렬해요. (여러 외부몰에서 동시에 공구를 진행 중인 셀러 찾기)"""
    groups = {}
    for r in seller_rows:
        name = (r["seller"] or "").strip()
        if not name:
            continue
        g = groups.setdefault(name, {"platforms": [], "brand_products": [], "notes": [], "links": []})
        if r["platform"]:
            g["platforms"].append(r["platform"])
        brand_product = " ".join(x for x in [(r["brand"] or "").strip(), (r["product"] or "").strip()] if x)
        if brand_product:
            g["brand_products"].append(brand_product)
        if r["frequency_note"]:
            g["notes"].append(r["frequency_note"])
        if r["link"]:
            g["links"].append(r["link"])

    result = []
    for name, g in groups.items():
        platforms = _dedupe_keep_order(g["platforms"])
        result.append({
            "seller": name,
            "platforms": platforms,
            "platform_count": len(platforms),
            "brand_products": _dedupe_keep_order(g["brand_products"]),
            "frequency_notes": _dedupe_keep_order(g["notes"]),
            "link": g["links"][0] if g["links"] else "",
        })

    result.sort(key=lambda s: (-s["platform_count"], s["seller"]))
    return result[:20]


def _top_brand_products(seller_rows):
    """6개 플랫폼 전체 데이터에서 브랜드/제품이 겹치는 걸 모아 등록 횟수 순으로 TOP10을 뽑아요.
    카테고리 구분 없이, 브랜드·제품명이 모두 비어있는 행은 집계에서 빠져요(집계할 정보가 없어서)."""
    groups = {}
    for r in seller_rows:
        brand = (r["brand"] or "").strip()
        product = (r["product"] or "").strip()
        if not brand and not product:
            continue
        key = (brand, product)
        g = groups.setdefault(key, {"count": 0, "platforms": set()})
        g["count"] += 1
        if r["platform"]:
            g["platforms"].add(r["platform"])

    result = [
        {
            "brand": brand or "-",
            "product": product or "-",
            "count": g["count"],
            "platform_count": len(g["platforms"]),
        }
        for (brand, product), g in groups.items()
    ]
    result.sort(key=lambda x: (-x["count"], -x["platform_count"]))
    return result[:10]


@trend_bp.route("/")
def index():
    records = [dict(r) for r in db.list_trend_records()]

    # 상품군별 공구 시장 노출 요약 — 여러 플랫폼 동시 등장 / 신규 등장 / 반복 등장
    # (매출 기회 대시보드의 점수 계산에도 쓰이는 기능이라 그대로 유지해요)
    groups = db.list_trend_groups()
    group_summaries = summarize_groupbuy_exposure(records, groups, TREND_PLATFORMS)

    # ① 플랫폼별 인기셀러 (최대 TOP 20씩)
    platform_sellers = {}
    for p in TREND_PLATFORMS:
        rows = [dict(r) for r in db.list_platform_sellers(p)]
        platform_sellers[p] = {"rows": rows, "count": len(rows), "full": len(rows) >= PLATFORM_SELLER_CAP}

    all_seller_rows = [dict(r) for r in db.list_platform_sellers()]

    # ② 왼쪽 — 공통 인기셀러 분석 (총 20명, 10명씩 2페이지)
    common_sellers = _common_seller_analysis(all_seller_rows)
    common_sellers_page1 = common_sellers[:10]
    common_sellers_page2 = common_sellers[10:20]

    # ② 오른쪽 — 공구 인기 브랜드·제품 TOP10 (5개 플랫폼 통합, 카테고리 구분 없음)
    top_brand_products = _top_brand_products(all_seller_rows)

    return render_template(
        "trend.html",
        platforms=TREND_PLATFORMS, categories=TREND_CATEGORIES, platform_links=TREND_PLATFORM_LINKS,
        api_key_configured=bool(os.environ.get("AUTOMATION_API_KEY")),
        records=records, groups=groups, group_summaries=group_summaries,
        platform_sellers=platform_sellers, platform_seller_cap=PLATFORM_SELLER_CAP,
        common_sellers_page1=common_sellers_page1, common_sellers_page2=common_sellers_page2,
        top_brand_products=top_brand_products,
    )


@trend_bp.route("/platform-sellers/add", methods=["POST"])
def platform_sellers_add():
    f = request.form
    platform = f.get("platform", "").strip()
    seller = f.get("seller", "").strip()
    if not platform or platform not in TREND_PLATFORMS:
        flash("플랫폼을 확인해 주세요.")
        return redirect(url_for("trend.index"))
    if not seller:
        flash("셀러명을 입력해 주세요.")
        return redirect(url_for("trend.index"))
    if db.count_platform_sellers(platform) >= PLATFORM_SELLER_CAP:
        flash(f"{platform}은(는) 이미 TOP {PLATFORM_SELLER_CAP}명이 모두 등록되어 있어요. 먼저 삭제한 뒤 추가해 주세요.")
        return redirect(url_for("trend.index"))
    data = {
        "platform": platform,
        "seller": seller,
        "brand": f.get("brand", "").strip(),
        "product": f.get("product", "").strip(),
        "frequency_note": f.get("frequency_note", "").strip(),
        "link": f.get("link", "").strip(),
        "check_date": f.get("check_date", "").strip(),
    }
    db.create_platform_seller(data, session.get("user_name"))
    flash(f"{platform}에 '{seller}'님을 등록했어요.")
    return redirect(url_for("trend.index"))


@trend_bp.route("/platform-sellers/<int:seller_id>/delete", methods=["POST"])
def platform_sellers_delete(seller_id):
    db.delete_platform_seller(seller_id)
    flash("삭제했어요.")
    return redirect(url_for("trend.index"))


# ---------------------------------------------------------------------------
# 작업지시서 03: "붙여넣기로 한꺼번에 등록"
# 사람이 직접 확인해야 하는 플랫폼(위시버니 공구 목록, 자동수집이 막히거나 계속 실패하는 곳 등)을 위한
# 기능이에요. 화면에서 복사한 목록을 한 줄에 하나씩 붙여넣으면, 미리보기를 보여준 뒤 확인을 눌러야
# 저장돼요(바로 저장하지 않아요).
#
# 한 줄 형식: 셀러 | 브랜드 | 제품명 | 공구가 | 링크
# (셀러만 필수, 나머지는 비워도 돼요. 예: "하봄 | 레벤호프 | 내열유리용기 | 12900 | https://...")
# ---------------------------------------------------------------------------

def _parse_paste_lines(raw_text):
    rows = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        seller = parts[0] if len(parts) > 0 else ""
        if not seller:
            continue
        brand = parts[1] if len(parts) > 1 else ""
        product = parts[2] if len(parts) > 2 else ""
        price_raw = parts[3] if len(parts) > 3 else ""
        link = parts[4] if len(parts) > 4 else ""
        try:
            price = int(price_raw.replace(",", "").replace("원", "")) if price_raw else 0
        except ValueError:
            price = 0
        rows.append({"seller": seller, "brand": brand, "product": product, "price": price, "link": link})
    return rows


@trend_bp.route("/platform-sellers/paste-preview", methods=["POST"])
def platform_sellers_paste_preview():
    platform = request.form.get("platform", "").strip()
    raw_text = request.form.get("raw_text", "")
    if not platform or platform not in TREND_PLATFORMS:
        flash("플랫폼을 확인해 주세요.")
        return redirect(url_for("trend.index"))

    rows = _parse_paste_lines(raw_text)
    if not rows:
        flash("붙여넣은 내용에서 읽을 수 있는 줄이 없어요. '셀러 | 브랜드 | 제품명 | 공구가 | 링크' 형식으로 한 줄에 하나씩 넣어 주세요.")
        return redirect(url_for("trend.index"))

    session["paste_preview"] = {"platform": platform, "rows": rows}
    return render_template("trend_paste_preview.html", platform=platform, rows=rows)


@trend_bp.route("/platform-sellers/paste-confirm", methods=["POST"])
def platform_sellers_paste_confirm():
    pending = session.pop("paste_preview", None)
    if not pending:
        flash("미리보기가 만료됐어요. 다시 붙여넣어 주세요.")
        return redirect(url_for("trend.index"))

    platform = pending["platform"]
    today = date.today().isoformat()
    saved = 0
    for r in pending["rows"]:
        data = {
            "check_date": today, "platform": platform, "seller": r["seller"],
            "product": r["product"], "category": "", "price": r["price"], "link": r["link"],
            "product_group_id": None, "insta_handle": "", "followers": 0, "brand": r["brand"],
        }
        db.upsert_trend_record(data, session.get("user_name") or "manual-paste")
        db.merge_platform_seller(platform, data, session.get("user_name") or "manual-paste")
        saved += 1

    flash(f"{platform}에서 {saved}건을 붙여넣기로 등록했어요.")
    return redirect(url_for("trend.index"))


@trend_bp.route("/<int:record_id>/tag", methods=["POST"])
def tag(record_id):
    group_id = request.form.get("product_group_id", type=int)
    db.set_trend_record_group(record_id, group_id)
    flash("상품군을 지정했어요.")
    return redirect(url_for("trend.index"))


# ---------------------------------------------------------------------------
# 상품군(키워드 그룹) 사전 관리 — 예: "텀블러 세척/세정제/냄새 제거" -> "텀블러 세정제" 상품군
# ---------------------------------------------------------------------------

@trend_bp.route("/groups")
def groups_index():
    code_to_name = {code: name for name, code in NAVER_SHOPPING_CATEGORIES}
    groups = db.list_trend_groups()
    for g in groups:
        g["shopping_category_label"] = code_to_name.get(g.get("shopping_category"))
    return render_template(
        "trend_groups.html", groups=groups, categories=OPPORTUNITY_CATEGORIES,
        shopping_categories=NAVER_SHOPPING_CATEGORIES,
    )


@trend_bp.route("/groups/add", methods=["POST"])
def groups_add():
    name = request.form.get("name", "").strip()
    category = request.form.get("category", "").strip()
    shopping_category = request.form.get("shopping_category", "").strip()
    if not name:
        flash("상품군 이름을 입력해 주세요.")
        return redirect(url_for("trend.groups_index"))
    group_id = db.create_trend_group(name, category, session.get("user_name"))
    if shopping_category:
        db.set_trend_group_shopping_category(group_id, shopping_category)
    terms_raw = request.form.get("terms", "")
    for term in [t.strip() for t in terms_raw.split(",") if t.strip()]:
        db.add_trend_group_term(group_id, term)
    flash(f"상품군 '{name}'을(를) 만들었어요.")
    return redirect(url_for("trend.groups_index"))


@trend_bp.route("/groups/<int:group_id>/shopping-category", methods=["POST"])
def groups_set_shopping_category(group_id):
    shopping_category = request.form.get("shopping_category", "").strip()
    db.set_trend_group_shopping_category(group_id, shopping_category)
    flash("네이버 쇼핑 카테고리를 저장했어요." if shopping_category else "네이버 쇼핑 카테고리 연결을 해제했어요.")
    return redirect(url_for("trend.groups_index"))


@trend_bp.route("/groups/<int:group_id>/delete", methods=["POST"])
def groups_delete(group_id):
    db.delete_trend_group(group_id)
    flash("상품군을 삭제했어요.")
    return redirect(url_for("trend.groups_index"))


@trend_bp.route("/groups/<int:group_id>/terms/add", methods=["POST"])
def groups_add_term(group_id):
    term = request.form.get("term", "").strip()
    if term:
        db.add_trend_group_term(group_id, term)
    return redirect(url_for("trend.groups_index"))


@trend_bp.route("/groups/terms/<int:term_id>/delete", methods=["POST"])
def groups_delete_term(term_id):
    db.delete_trend_group_term(term_id)
    return redirect(url_for("trend.groups_index"))


# ---------------------------------------------------------------------------
# 쇼핑인사이트 조회 — 네이버 공식 API로 분야 클릭 추이 + 기기·성별·연령 비중 확인
# ---------------------------------------------------------------------------

@trend_bp.route("/shopping-insight")
def shopping_insight():
    category_code = request.args.get("category") or NAVER_SHOPPING_CATEGORIES[8][1]  # 기본값: 생활/건강
    months = request.args.get("months", type=int) or 1
    if months not in (1, 3):
        months = 1
    category_name = next((name for name, code in NAVER_SHOPPING_CATEGORIES if code == category_code), category_code)

    result = fetch_naver_shopping_insight(category_code, category_name, months)

    trend_points, trend_w, trend_h = trend_sparkline_points(result["trend"])
    device_chart = donut_chart(result["device"]) if result["device"] else None
    gender_chart = donut_chart(result["gender"]) if result["gender"] else None
    age_chart = donut_chart(result["age"]) if result["age"] else None

    # ---- 인기검색어 TOP100 (비공식, 작업지시서 02) ----
    rank_cid = request.args.get("rank_cid") or NAVER_RANK_DEFAULT_CID
    if rank_cid not in dict(NAVER_RANK_CATEGORIES).values():
        rank_cid = NAVER_RANK_DEFAULT_CID
    rank_category_name = next((n for n, c in NAVER_RANK_CATEGORIES if c == rank_cid), rank_cid)
    rank_gender = request.args.get("rank_gender") or ""
    if rank_gender not in ("", "f", "m"):
        rank_gender = ""
    rank_ages = [a for a in request.args.getlist("rank_age") if a in NAVER_RANK_AGE_OPTIONS]

    rank_table, rank_error = _build_rank_table(rank_cid, rank_category_name, rank_gender, rank_ages)
    last_log = db.get_last_naver_rank_log()

    return render_template(
        "trend_shopping_insight.html",
        categories=NAVER_SHOPPING_CATEGORIES, category_code=category_code, category_name=category_name,
        months=months, error=result["error"],
        trend=result["trend"], trend_points=trend_points, trend_w=trend_w, trend_h=trend_h,
        device_chart=device_chart, gender_chart=gender_chart, age_chart=age_chart,
        rank_categories=NAVER_RANK_CATEGORIES, rank_cid=rank_cid, rank_category_name=rank_category_name,
        rank_gender=rank_gender, rank_ages=rank_ages, rank_age_options=NAVER_RANK_AGE_OPTIONS,
        rank_table=rank_table, rank_error=rank_error, rank_last_log=dict(last_log) if last_log else None,
        rank_is_default=(rank_cid == NAVER_RANK_DEFAULT_CID and rank_gender == "" and not rank_ages),
        trend_groups=db.list_trend_groups(),
    )


def _collect_and_store(cid, category_name, gender="", ages=()):
    """네이버에서 그 조합의 순위를 가져와 오늘 날짜로 저장한다. 우회하지 않고, 실패하면 그대로 알린다."""
    try:
        result = naver_rank.fetch_top100(cid, gender=gender, ages=ages)
    except naver_rank.NaverRankError as e:
        db.log_naver_rank_collect(False, str(e))
        return False, str(e)
    today = date.today().isoformat()
    db.save_naver_ranks(today, cid, category_name, gender, ",".join(ages), result["range"], result["ranks"])
    db.log_naver_rank_collect(True, f"{category_name} {len(result['ranks'])}개 저장 (기간 {result['range']})")
    return True, result["range"]


def _build_rank_table(cid, category_name, gender, ages):
    """오늘치 순위 + 전날/7일 전 대비를 화면에 뿌릴 형태로 만든다.
    오늘 이 조합을 아직 못 모았으면 지금 바로 한 번 가져와서 그날치로 저장한다 (doc 02의 "나머지는
    화면에서 고를 때 가져와서 그날 하루 저장" 규칙). 실패하면 마지막으로 성공한 데이터를 대신 보여준다."""
    age_key = ",".join(ages)
    today = date.today().isoformat()
    rows = [dict(r) for r in db.get_naver_ranks(cid, gender, age_key, today)]
    error = None

    if not rows:
        ok, info = _collect_and_store(cid, category_name, gender, ages)
        if ok:
            rows = [dict(r) for r in db.get_naver_ranks(cid, gender, age_key, today)]
        else:
            error = info
            fallback_dates = db.list_naver_rank_dates(cid, gender, age_key, limit=1)
            if fallback_dates:
                rows = [dict(r) for r in db.get_naver_ranks(cid, gender, age_key, fallback_dates[0])]

    if not rows:
        return None, error

    latest_date = rows[0]["collected_date"]
    period_range = rows[0]["period_range"]
    known_dates = set(db.list_naver_rank_dates(cid, gender, age_key, limit=60))

    prev_date = (date.fromisoformat(latest_date) - timedelta(days=1)).isoformat()
    seven_date = (date.fromisoformat(latest_date) - timedelta(days=7)).isoformat()
    prev_rows = [dict(r) for r in db.get_naver_ranks(cid, gender, age_key, prev_date)] if prev_date in known_dates else []
    seven_rows = [dict(r) for r in db.get_naver_ranks(cid, gender, age_key, seven_date)] if seven_date in known_dates else []

    today_ranks = [{"rank": r["rank"], "keyword": r["keyword"]} for r in rows]
    prev_ranks = [{"rank": r["rank"], "keyword": r["keyword"]} for r in prev_rows]
    changes = naver_rank.rank_changes(today_ranks, prev_ranks)

    seven_before = {r["keyword"]: r["rank"] for r in seven_rows}
    for c in changes:
        old7 = seven_before.get(c["keyword"])
        c["change_7d"] = None if old7 is None else old7 - c["rank"]

    has_previous = bool(prev_rows)
    new_keywords = [c for c in changes if c["is_new"]] if has_previous else []
    risers = sorted([c for c in changes if c["change"] and c["change"] > 0], key=lambda c: -c["change"])[:10]

    return {
        "collected_date": latest_date,
        "period_range": period_range,
        "rows": changes,
        "has_previous": has_previous,
        "has_seven": bool(seven_rows),
        "new_keywords": new_keywords[:10],
        "risers": risers,
        "is_stale": latest_date != today,
    }, error


@trend_bp.route("/shopping-insight/collect-now", methods=["POST"])
def shopping_insight_collect_now():
    ok, info = _collect_and_store(NAVER_RANK_DEFAULT_CID, "생활/건강", "", ())
    if ok:
        flash(f"'생활/건강' 인기검색어 TOP100을 방금 새로 모았어요. (기간: {info})")
    else:
        flash("지금 수집이 실패했어요: " + info)
    return redirect(url_for("trend.shopping_insight"))


@trend_bp.route("/rank-keyword/add-to-group", methods=["POST"])
def rank_keyword_add_to_group():
    keyword = request.form.get("keyword", "").strip()
    group_id = request.form.get("group_id", type=int)
    if not keyword or not group_id:
        flash("상품군을 선택한 뒤 추가해 주세요.")
    else:
        db.add_trend_group_term(group_id, keyword)
        flash(f"'{keyword}'을(를) 상품군에 담았어요.")
    return redirect(url_for(
        "trend.shopping_insight",
        rank_cid=request.form.get("rank_cid") or None,
        rank_gender=request.form.get("rank_gender") or None,
        rank_age=request.form.getlist("rank_age"),
    ))


@trend_bp.route("/add", methods=["POST"])
def add():
    f = request.form
    data = {
        "check_date": f.get("check_date", "").strip(),
        "platform": f.get("platform", "").strip(),
        "seller": f.get("seller", "").strip(),
        "product": f.get("product", "").strip(),
        "category": f.get("category", "").strip(),
        "price": int(f.get("price") or 0),
        "link": f.get("link", "").strip(),
        "product_group_id": f.get("product_group_id", type=int),
    }
    if not data["seller"]:
        flash("셀러명을 입력해 주세요.")
        return redirect(url_for("trend.index"))
    db.create_trend_record(data, session.get("user_name"))
    flash("등록했어요.")
    return redirect(url_for("trend.index"))


@trend_bp.route("/<int:record_id>/delete", methods=["POST"])
def delete(record_id):
    db.delete_trend_record(record_id)
    flash("삭제했어요.")
    return redirect(url_for("trend.index"))


@trend_bp.route("/clear", methods=["POST"])
def clear():
    db.clear_trend_records()
    flash("전체 초기화했어요.")
    return redirect(url_for("trend.index"))


# ---------------------------------------------------------------------------
# 외부 자동화(Cowork 예약작업 등)가 호출하는 API
#
# 사용 예 (Cowork가 WebSearch/WebFetch로 외부몰을 확인한 뒤 그 결과를 이 웹앱에 저장할 때):
#
#   POST https://<railway-domain>/trend/api/records
#   Headers: Authorization: Bearer <AUTOMATION_API_KEY>
#            Content-Type: application/json
#   Body:
#   {
#     "records": [
#       {"check_date": "2026-09-01", "platform": "82market", "seller": "하봄",
#        "insta_handle": "@habom_pick", "followers": 12000, "brand": "레벤호프",
#        "product": "레벤호프 내열유리용기", "category": "주방용품", "price": 12900,
#        "link": "https://www.82market.com/..."},
#       ...
#     ]
#   }
#   (insta_handle, followers, brand는 없어도 돼요 — 빈 칸으로 받아요)
#
# 응답: {"ok": true, "inserted": N, "updated": N, "seller_list_updated": N} 또는 {"ok": false, "error": "..."}
#
# 작업지시서 03: 같은 주(월~일)에 같은 플랫폼·셀러·제품이 다시 들어오면 새로 만들지 않고 그 기록을
# 갱신해요. 그리고 "① 플랫폼별 인기셀러" 명단에도 함께 반영해요(이미 있는 셀러면 제품 정보만 채우고,
# 없는 셀러면 그 플랫폼이 20명 미만일 때만 새로 추가해요).
#
# AUTOMATION_API_KEY 환경변수를 Railway에 등록해야 이 엔드포인트가 켜져요.
# (등록 안 돼 있으면 보안을 위해 항상 403을 돌려줘요 — 아무나 호출 못 하게)
# ---------------------------------------------------------------------------

def _check_api_key():
    expected = os.environ.get("AUTOMATION_API_KEY")
    if not expected:
        return False
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else request.headers.get("X-API-Key", "")
    return token == expected


@trend_bp.route("/api/records", methods=["POST"])
def api_create_records():
    if not _check_api_key():
        return jsonify({"ok": False, "error": "인증 실패 (AUTOMATION_API_KEY 미설정 또는 키 불일치)"}), 403

    payload = request.get_json(silent=True) or {}
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        return jsonify({"ok": False, "error": "records 배열이 비어있거나 형식이 올바르지 않아요."}), 400

    # 이름으로 상품군을 지정한 경우("product_group": "텀블러 세정제") id로 변환 — 미리 사전에 없으면 태깅 없이 저장
    group_name_cache = {}

    inserted = 0
    updated = 0
    seller_list_updated = 0
    errors = []
    for i, r in enumerate(records):
        seller = str(r.get("seller", "")).strip()
        if not seller:
            errors.append(f"{i}번째 항목: seller가 비어있어 건너뜀")
            continue
        group_name = str(r.get("product_group", "")).strip()
        group_id = None
        if group_name:
            if group_name not in group_name_cache:
                g = next((g for g in db.list_trend_groups() if g["name"] == group_name), None)
                group_name_cache[group_name] = g["id"] if g else None
            group_id = group_name_cache[group_name]
        platform = str(r.get("platform", "")).strip()
        data = {
            "check_date": str(r.get("check_date", "")).strip(),
            "platform": platform,
            "seller": seller,
            "product": str(r.get("product", "")).strip(),
            "category": str(r.get("category", "")).strip(),
            "price": int(r.get("price") or 0),
            "link": str(r.get("link", "")).strip(),
            "product_group_id": group_id,
            "insta_handle": str(r.get("insta_handle", "")).strip(),
            "followers": int(r.get("followers") or 0),
            "brand": str(r.get("brand", "")).strip(),
        }
        created, _id = db.upsert_trend_record(data, "automation")
        if created:
            inserted += 1
        else:
            updated += 1

        if platform in TREND_PLATFORMS:
            result = db.merge_platform_seller(platform, data, "automation")
            if result in ("created", "updated"):
                seller_list_updated += 1

    return jsonify({
        "ok": True, "inserted": inserted, "updated": updated,
        "seller_list_updated": seller_list_updated, "skipped": errors,
    })


@trend_bp.route("/api/records", methods=["GET"])
def api_status():
    """등록 여부만 가볍게 확인할 수 있는 헬스체크 (인증 불필요, 민감정보 없음)."""
    return jsonify({"api_enabled": bool(os.environ.get("AUTOMATION_API_KEY"))})


# ---------------------------------------------------------------------------
# 플랫폼별 인기셀러 자동 수집 API (Cowork 예약작업 전용, 매주 1회)
#
# 위 /api/records용 AUTOMATION_API_KEY와는 별개의 전용 키(PLATFORM_SELLER_API_KEY)를 써요.
# 한 번 호출할 때마다 그 플랫폼의 기존 20명을 통째로 새 목록으로 교체해요(다른 플랫폼은 그대로).
#
# 사용 예:
#   POST https://<railway-domain>/trend/api/platform-sellers
#   Headers: Authorization: Bearer <PLATFORM_SELLER_API_KEY>
#            Content-Type: application/json
#   Body:
#   {
#     "platform": "82market",
#     "sellers": [
#       {"seller": "드엘리사 | yoonjung Lee", "brand": "", "product": "", "frequency_note": "", "link": "https://..."},
#       ...  (최대 20개, 그 이상은 잘려요)
#     ]
#   }
#   응답: {"ok": true, "platform": "82market", "count": N}
# ---------------------------------------------------------------------------

def _check_platform_seller_api_key():
    expected = os.environ.get("PLATFORM_SELLER_API_KEY")
    if not expected:
        return False
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else request.headers.get("X-API-Key", "")
    return token == expected


@trend_bp.route("/api/platform-sellers", methods=["POST"])
def api_replace_platform_sellers():
    if not _check_platform_seller_api_key():
        return jsonify({"ok": False, "error": "인증 실패 (PLATFORM_SELLER_API_KEY 미설정 또는 키 불일치)"}), 403

    payload = request.get_json(silent=True) or {}
    platform = str(payload.get("platform", "")).strip()
    if platform not in TREND_PLATFORMS:
        return jsonify({"ok": False, "error": f"platform은 다음 중 하나여야 해요: {TREND_PLATFORMS}"}), 400

    sellers = payload.get("sellers")
    if not isinstance(sellers, list):
        return jsonify({"ok": False, "error": "sellers 배열이 필요해요."}), 400

    rows = []
    for s in sellers:
        if not isinstance(s, dict):
            continue
        seller = str(s.get("seller", "")).strip()
        if not seller:
            continue
        rows.append({
            "seller": seller,
            "brand": str(s.get("brand", "")).strip(),
            "product": str(s.get("product", "")).strip(),
            "frequency_note": str(s.get("frequency_note", "")).strip(),
            "link": str(s.get("link", "")).strip(),
            "check_date": str(s.get("check_date", "")).strip(),
        })

    db.replace_platform_sellers(platform, rows, "automation")
    return jsonify({"ok": True, "platform": platform, "count": len(rows[:20])})


@trend_bp.route("/api/platform-sellers", methods=["GET"])
def api_platform_seller_status():
    """등록 여부만 가볍게 확인할 수 있는 헬스체크 (인증 불필요, 민감정보 없음)."""
    return jsonify({"api_enabled": bool(os.environ.get("PLATFORM_SELLER_API_KEY"))})


# ---------------------------------------------------------------------------
# 네이버 인기검색어 TOP100 하루 1번 자동 수집 API (Cowork 예약작업 전용)
#
# 위 두 API와는 별개의 전용 키(NAVER_RANK_API_KEY)를 써요. "생활/건강 전체" 조합만 모아요
# (지인이 정한 범위). 다른 분야·성별·연령은 화면에서 볼 때 그때그때 따로 가져와요.
#
# 사용 예:
#   POST https://<railway-domain>/trend/api/collect-ranks
#   Headers: Authorization: Bearer <NAVER_RANK_API_KEY>
#   응답: {"ok": true, "info": "2026.09.19. ~ 2026.09.25."} 또는 {"ok": false, "info": "실패 이유"}
# ---------------------------------------------------------------------------

def _check_naver_rank_api_key():
    expected = os.environ.get("NAVER_RANK_API_KEY")
    if not expected:
        return False
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.startswith("Bearer ") else request.headers.get("X-API-Key", "")
    return token == expected


@trend_bp.route("/api/collect-ranks", methods=["POST"])
def api_collect_ranks():
    if not _check_naver_rank_api_key():
        return jsonify({"ok": False, "error": "인증 실패 (NAVER_RANK_API_KEY 미설정 또는 키 불일치)"}), 403
    ok, info = _collect_and_store(NAVER_RANK_DEFAULT_CID, "생활/건강", "", ())
    return jsonify({"ok": ok, "info": info})


@trend_bp.route("/api/collect-ranks", methods=["GET"])
def api_collect_ranks_status():
    """등록 여부만 가볍게 확인할 수 있는 헬스체크 (인증 불필요, 민감정보 없음)."""
    return jsonify({"api_enabled": bool(os.environ.get("NAVER_RANK_API_KEY"))})
