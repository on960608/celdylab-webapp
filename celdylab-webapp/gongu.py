from flask import Blueprint, render_template, request, redirect, url_for, session, flash

import db
from analysis import gongu_net_sold, gongu_return_pct, gongu_per1k, gongu_tier, TIER_ORDER, won, pct, BRANDS

gongu_bp = Blueprint("gongu", __name__, url_prefix="/gongu-perf")


@gongu_bp.before_request
def _require_login():
    if not session.get("user_id"):
        return redirect(url_for("login", next=request.path))

MONTHS = [f"{i:02d}" for i in range(1, 13)]


def _most_frequent(values):
    values = [v for v in values if v]
    if not values:
        return None
    counts = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return max(counts, key=counts.get)


@gongu_bp.route("/")
def index():
    brand = request.args.get("brand") or None
    month = request.args.get("month") or None
    records = [dict(r) for r in db.list_gongu_records(brand, month)]

    n = len(records)
    total_followers = sum(r["followers"] for r in records)
    total_revenue = sum(r["revenue"] for r in records)
    avg_revenue = total_revenue / n if n else 0
    per1k = (total_revenue / total_followers * 1000) if total_followers else 0
    avg_return = sum(gongu_return_pct(r) for r in records) / n if n else 0

    # 셀러별 성과 분석 (모든 회차 합산)
    seller_groups = {}
    for r in records:
        name = (r["seller"] or "").strip()
        if not name:
            continue
        g = seller_groups.setdefault(name, {"followers": 0, "revenue": 0, "sold_qty": 0, "return_qty": 0, "products": [], "count": 0})
        g["followers"] = max(g["followers"], r["followers"])
        g["revenue"] += r["revenue"]
        g["sold_qty"] += r["sold_qty"]
        g["return_qty"] += r["return_qty"]
        if r["product"]:
            g["products"].append(r["product"])
        g["count"] += 1
    sellers = sorted(
        [
            {
                "name": name,
                "followers": g["followers"],
                "top_product": _most_frequent(g["products"]) or "-",
                "total_revenue": g["revenue"],
                "total_sold": max(0, g["sold_qty"] - g["return_qty"]),
                "avg_return": (g["return_qty"] / g["sold_qty"] * 100) if g["sold_qty"] else 0,
                "count": g["count"],
            }
            for name, g in seller_groups.items()
        ],
        key=lambda s: -s["total_revenue"],
    )

    # 팔로워 구간별 평균
    tier_groups = {}
    for r in records:
        t = gongu_tier(r["followers"])
        tier_groups.setdefault(t, []).append(r)
    tiers = []
    for t in TIER_ORDER:
        arr = tier_groups.get(t)
        if not arr:
            continue
        tiers.append({
            "tier": t,
            "avg_revenue": sum(x["revenue"] for x in arr) / len(arr),
            "avg_sold": sum(gongu_net_sold(x) for x in arr) / len(arr),
        })

    # 제품별 평균
    product_groups = {}
    for r in records:
        p = r["product"] or "미지정"
        product_groups.setdefault(p, []).append(r)
    products = []
    for p, arr in product_groups.items():
        avg_return = sum(gongu_return_pct(x) for x in arr) / len(arr)
        risk = "위험" if avg_return >= 20 else ("주의" if avg_return >= 10 else "양호")
        products.append({
            "product": p, "count": len(arr),
            "avg_revenue": sum(x["revenue"] for x in arr) / len(arr),
            "avg_sold": sum(gongu_net_sold(x) for x in arr) / len(arr),
            "avg_return": avg_return, "risk": risk,
        })

    # 신규 공구 예상 계산기 (같은 팔로워 구간 우선 비교)
    forecast = None
    fc_followers = request.args.get("fc_followers", type=int)
    fc_price = request.args.get("fc_price", type=int)
    if fc_followers:
        target_tier = gongu_tier(fc_followers)
        tier_records = [r for r in records if gongu_tier(r["followers"]) == target_tier]
        basis = tier_records if len(tier_records) >= 2 else records
        if basis:
            per_f = sum((r["revenue"] / r["followers"]) if r["followers"] else 0 for r in basis) / len(basis)
            expected_revenue = fc_followers * per_f
            if fc_price:
                qty = expected_revenue / fc_price
            else:
                per_f_qty = sum((gongu_net_sold(r) / r["followers"]) if r["followers"] else 0 for r in basis) / len(basis)
                qty = per_f_qty * fc_followers
            forecast = {
                "revenue": won(expected_revenue),
                "qty": f"{round(qty):,}개",
                "low": f"{round(qty * 0.8):,}개",
                "mid": f"{round(qty * 1.05):,}개",
                "high": f"{round(qty * 1.3):,}개",
                "basis_count": len(tier_records),
                "basis_tier": target_tier,
                "used_tier": len(tier_records) >= 2,
                "total_count": len(records),
            }
        else:
            forecast = {"empty": True}

    return render_template(
        "gongu.html",
        brands=BRANDS, months=MONTHS, brand=brand, month=month,
        records=records, count=n, avg_revenue=avg_revenue, per1k=per1k, avg_return=avg_return,
        sellers=sellers, tiers=tiers, products=products, forecast=forecast,
        fc_followers=fc_followers, fc_price=fc_price,
        won=won, pct=pct, net_sold=gongu_net_sold, return_pct=gongu_return_pct, per1k_of=gongu_per1k,
    )


@gongu_bp.route("/add", methods=["POST"])
def add():
    f = request.form
    data = {
        "month": f.get("month", "").strip(),
        "channel": f.get("channel", "").strip(),
        "brand": f.get("brand", "").strip(),
        "product": f.get("product", "").strip(),
        "seller": f.get("seller", "").strip(),
        "followers": int(f.get("followers") or 0),
        "link": f.get("link", "").strip(),
        "revenue": int(f.get("revenue") or 0),
        "sold_qty": int(f.get("sold_qty") or 0),
        "return_qty": int(f.get("return_qty") or 0),
    }
    db.create_gongu_record(data, session.get("user_name"))
    flash("공구 데이터를 등록했어요.")
    return redirect(url_for("gongu.index", brand=f.get("brand") or None))


@gongu_bp.route("/<int:record_id>/delete", methods=["POST"])
def delete(record_id):
    db.delete_gongu_record(record_id)
    flash("삭제했어요.")
    return redirect(url_for("gongu.index"))


@gongu_bp.route("/clear", methods=["POST"])
def clear():
    db.clear_gongu_records()
    flash("전체 데이터를 초기화했어요.")
    return redirect(url_for("gongu.index"))
