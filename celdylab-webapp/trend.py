import os
from datetime import datetime, timezone

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify

import db
from analysis import TREND_PLATFORMS, TREND_CATEGORIES, TREND_PLATFORM_LINKS

trend_bp = Blueprint("trend", __name__, url_prefix="/trend")

# 새로고침할 때마다 매번 모니터링 대상 플랫폼(trend_scraper.SCRAPERS 참고)을 다시 읽어오면
# 너무 잦은 요청이 될 수 있어서, 최근 자동 수집이 이 시간(초) 안에 있었으면 새로고침은
# 건너뛰고 기존 데이터를 그대로 보여줘요. "⚡ 자동 생성" 버튼은 이 제한 없이 항상 바로 실행돼요.
AUTO_REFRESH_MIN_INTERVAL_SECONDS = 300


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


def _run_auto_scrape():
    """모니터링 대상 플랫폼(trend_scraper.SCRAPERS 참고)을 지금 이 순간 다시 읽어와서, 이전
    자동 수집 기록은 지우고 새로 읽은 걸로 교체해요(수동으로 '+ 등록'한 기록은 그대로
    둬요) — 그래야 매번 '지금 이 순간'의 인기 순위만 남아요."""
    import trend_scraper

    db.clear_auto_trend_records()
    summaries = []
    total = 0
    for label, fn in trend_scraper.SCRAPERS:
        try:
            records = fn(limit=20)
        except Exception as e:
            summaries.append(f"{label} 실패({e.__class__.__name__})")
            continue
        for r in records:
            db.create_trend_record(r, "auto-refresh")
        total += len(records)
        summaries.append(f"{label} {len(records)}건")
    return total, summaries


def _maybe_auto_scrape_on_load():
    """페이지를 새로고침할 때마다 자동으로 최신 상태로 바꿔요 — 다만 최근에 이미
    자동 수집했다면(AUTO_REFRESH_MIN_INTERVAL_SECONDS 이내) 외부 사이트에 너무 자주
    요청하지 않도록 건너뛰어요."""
    latest = db.latest_auto_trend_refresh_at()
    if latest:
        try:
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(latest)).total_seconds()
        except ValueError:
            elapsed = None
        if elapsed is not None and elapsed < AUTO_REFRESH_MIN_INTERVAL_SECONDS:
            return
    _run_auto_scrape()


# ---------------------------------------------------------------------------
# 이커머스 마켓플레이스 베스트셀러 (G마켓 등) — marketplace_scraper.py 참고
# ---------------------------------------------------------------------------

MARKETPLACE_DISPLAY_LIMIT = 20  # 화면에는 카테고리별 상위 N개만 보여줘요 (DB에는 더 많이 저장돼요)


def _run_marketplace_scrape():
    """G마켓 베스트에서 셀디랩 카테고리(청소/주방/구강제품/침구/생활용품)별 순위를 다시
    읽어와서, 카테고리별로 기존 데이터를 새 순위로 통째로 교체해요."""
    import marketplace_scraper

    total = 0
    summaries = []
    for category in marketplace_scraper.GMARKET_CATEGORY_MAP:
        try:
            items = marketplace_scraper.fetch_gmarket_best(category, limit=50)
        except Exception as e:
            summaries.append(f"{category} 실패({e.__class__.__name__})")
            continue
        db.replace_marketplace_best_items("G마켓", category, items)
        total += len(items)
        summaries.append(f"{category} {len(items)}건")
    return total, summaries


def _maybe_auto_scrape_marketplace_on_load():
    """공구 셀러 트렌드와 같은 방식으로, 최근 AUTO_REFRESH_MIN_INTERVAL_SECONDS 안에 이미
    수집했으면 건너뛰고 그렇지 않으면 지금 다시 수집해요."""
    latest = db.latest_marketplace_collected_at()
    if latest:
        try:
            elapsed = (datetime.now(timezone.utc) - datetime.fromisoformat(latest)).total_seconds()
        except ValueError:
            elapsed = None
        if elapsed is not None and elapsed < AUTO_REFRESH_MIN_INTERVAL_SECONDS:
            return
    _run_marketplace_scrape()


@trend_bp.route("/")
def index():
    _maybe_auto_scrape_on_load()
    _maybe_auto_scrape_marketplace_on_load()
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

    # 이커머스 마켓플레이스 베스트셀러 — 카테고리별로 묶고, 화면에는 상위 N개만 노출
    import marketplace_scraper

    marketplace_items = [dict(r) for r in db.list_marketplace_best_items()]
    marketplace_by_category = {cat: [] for cat in marketplace_scraper.GMARKET_CATEGORY_MAP}
    for it in marketplace_items:
        marketplace_by_category.setdefault(it["category"], []).append(it)
    marketplace_stats = {}
    for cat, items in marketplace_by_category.items():
        shown = items[:MARKETPLACE_DISPLAY_LIMIT]
        prices = [it["sale_price"] for it in items if it["sale_price"]]
        discounts = [it["discount_pct"] for it in items if it["discount_pct"] is not None]
        marketplace_stats[cat] = {
            "shown": shown,
            "total_count": len(items),
            "avg_price": (sum(prices) / len(prices)) if prices else None,
            "max_discount": max(discounts) if discounts else None,
        }
    marketplace_collected_at = db.latest_marketplace_collected_at()

    return render_template(
        "trend.html",
        platforms=TREND_PLATFORMS, categories=TREND_CATEGORIES, platform_links=TREND_PLATFORM_LINKS,
        records=records, popular_sellers=popular_sellers, category_insights=category_insights,
        api_key_configured=bool(os.environ.get("AUTOMATION_API_KEY")),
        marketplace_categories=list(marketplace_scraper.GMARKET_CATEGORY_MAP.keys()),
        marketplace_stats=marketplace_stats,
        marketplace_collected_at=marketplace_collected_at,
    )


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


@trend_bp.route("/refresh", methods=["POST"])
def refresh():
    """'⚡ 자동 생성' 버튼 — 새로고침 자동 갱신과 달리 대기시간 없이 지금 바로 모니터링
    대상 플랫폼을 다시 읽어와서 이전 자동 수집 기록을 새 데이터로 교체해요."""
    total, summaries = _run_auto_scrape()

    if total:
        flash("자동 생성 완료 — " + " · ".join(summaries) + f" (총 {total}건)")
    else:
        flash("자동 생성 실패 — " + " · ".join(summaries) if summaries else "자동 생성에 실패했어요.")
    return redirect(url_for("trend.index"))


@trend_bp.route("/marketplace/refresh", methods=["POST"])
def marketplace_refresh():
    """마켓플레이스 베스트셀러 탭의 '⚡ 지금 다시 수집' 버튼 — 대기시간 없이 지금 바로
    G마켓 카테고리별 순위를 다시 읽어와서 교체해요."""
    total, summaries = _run_marketplace_scrape()

    if total:
        flash("마켓플레이스 수집 완료 — " + " · ".join(summaries) + f" (총 {total}건)")
    else:
        flash("마켓플레이스 수집 실패 — " + " · ".join(summaries) if summaries else "수집에 실패했어요.")
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

    inserted = 0
    errors = []
    for i, r in enumerate(records):
        seller = str(r.get("seller", "")).strip()
        if not seller:
            errors.append(f"{i}번째 항목: seller가 비어있어 건너뜀")
            continue
        data = {
            "check_date": str(r.get("check_date", "")).strip(),
            "platform": str(r.get("platform", "")).strip(),
            "seller": seller,
            "product": str(r.get("product", "")).strip(),
            "category": str(r.get("category", "")).strip(),
            "price": int(r.get("price") or 0),
            "link": str(r.get("link", "")).strip(),
        }
        db.create_trend_record(data, "automation")
        inserted += 1

    return jsonify({"ok": True, "inserted": inserted, "skipped": errors})


@trend_bp.route("/api/records", methods=["GET"])
def api_status():
    """등록 여부만 가볍게 확인할 수 있는 헬스체크 (인증 불필요, 민감정보 없음)."""
    return jsonify({"api_enabled": bool(os.environ.get("AUTOMATION_API_KEY"))})
