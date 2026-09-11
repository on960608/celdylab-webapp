import os

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify

import db
from analysis import (
    TREND_PLATFORMS, TREND_CATEGORIES, TREND_PLATFORM_LINKS, OPPORTUNITY_CATEGORIES,
    NAVER_SHOPPING_CATEGORIES, summarize_groupbuy_exposure,
)

trend_bp = Blueprint("trend", __name__, url_prefix="/trend")


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


@trend_bp.route("/")
def index():
    records = [dict(r) for r in db.list_trend_records()]

    # 인기 셀러 분석 — 셀러별로 묶어서 등록 횟수 순 나열
    seller_groups = {}
    for r in records:
        seller = (r["seller"] or "").strip()
        if not seller:
            continue
        g = seller_groups.setdefault(seller, {"count": 0, "price_sum": 0, "price_count": 0, "platforms": set(), "categories": [], "link": "", "date": ""})
        g["count"] += 1
        if r["price"]:
            g["price_sum"] += r["price"]
            g["price_count"] += 1
        if r["platform"]:
            g["platforms"].add(r["platform"])
        if r["category"]:
            g["categories"].append(r["category"])
        if r["link"] and (not g["link"] or (r["check_date"] or "") >= g["date"]):
            g["link"] = r["link"]
        if (r["check_date"] or "") >= g["date"]:
            g["date"] = r["check_date"] or g["date"]

    popular_sellers = sorted(
        [
            {
                "seller": name,
                "count": g["count"],
                "platform_count": len(g["platforms"]),
                "category": _most_common(g["categories"]) or "-",
                "avg_price": (g["price_sum"] / g["price_count"]) if g["price_count"] else None,
                "link": g["link"],
            }
            for name, g in seller_groups.items()
        ],
        key=lambda s: (-s["count"], -s["platform_count"]),
    )

    # 카테고리별 소구 인사이트 — 등록 건수·평균 공구가·확인된 플랫폼 수
    category_groups = {}
    for r in records:
        cat = r["category"] or "기타"
        g = category_groups.setdefault(cat, {"count": 0, "price_sum": 0, "price_count": 0, "platforms": set()})
        g["count"] += 1
        if r["price"]:
            g["price_sum"] += r["price"]
            g["price_count"] += 1
        if r["platform"]:
            g["platforms"].add(r["platform"])
    category_insights = sorted(
        [
            {
                "category": cat,
                "count": g["count"],
                "avg_price": (g["price_sum"] / g["price_count"]) if g["price_count"] else None,
                "platform_count": len(g["platforms"]),
            }
            for cat, g in category_groups.items()
        ],
        key=lambda c: -c["count"],
    )

    # 상품군별 공구 시장 노출 요약 — 여러 플랫폼 동시 등장 / 신규 등장 / 반복 등장
    groups = db.list_trend_groups()
    group_summaries = summarize_groupbuy_exposure(records, groups, TREND_PLATFORMS)

    return render_template(
        "trend.html",
        platforms=TREND_PLATFORMS, categories=TREND_CATEGORIES, platform_links=TREND_PLATFORM_LINKS,
        records=records, popular_sellers=popular_sellers, category_insights=category_insights,
        api_key_configured=bool(os.environ.get("AUTOMATION_API_KEY")),
        groups=groups, group_summaries=group_summaries,
    )


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
#        "product": "레벤호프 내열유리용기", "category": "주방용품", "price": 12900,
#        "link": "https://www.82market.com/..."},
#       ...
#     ]
#   }
#
# 응답: {"ok": true, "inserted": N} 또는 {"ok": false, "error": "..."}
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
        data = {
            "check_date": str(r.get("check_date", "")).strip(),
            "platform": str(r.get("platform", "")).strip(),
            "seller": seller,
            "product": str(r.get("product", "")).strip(),
            "category": str(r.get("category", "")).strip(),
            "price": int(r.get("price") or 0),
            "link": str(r.get("link", "")).strip(),
            "product_group_id": group_id,
        }
        db.create_trend_record(data, "automation")
        inserted += 1

    return jsonify({"ok": True, "inserted": inserted, "skipped": errors})


@trend_bp.route("/api/records", methods=["GET"])
def api_status():
    """등록 여부만 가볍게 확인할 수 있는 헬스체크 (인증 불필요, 민감정보 없음)."""
    return jsonify({"api_enabled": bool(os.environ.get("AUTOMATION_API_KEY"))})
