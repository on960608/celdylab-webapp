from flask import Blueprint, render_template, request, redirect, url_for, session, flash

import db
from analysis import TREND_PLATFORMS, TREND_CATEGORIES

trend_bp = Blueprint("trend", __name__, url_prefix="/trend")


@trend_bp.before_request
def _require_login():
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

    return render_template(
        "trend.html",
        platforms=TREND_PLATFORMS, categories=TREND_CATEGORIES,
        records=records, popular_sellers=popular_sellers, category_insights=category_insights,
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
