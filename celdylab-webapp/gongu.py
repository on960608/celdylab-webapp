from flask import Blueprint, render_template, request, redirect, url_for, session, flash

import db
from analysis import gongu_net_sold, gongu_return_pct, gongu_tier, TIER_ORDER, won, pct, manwon, BRANDS
from gongu_forecast import bands, per_10k, round_half_up
from gongu_order_parser import parse_courier_orders
from order_excel import file_fingerprint

gongu_bp = Blueprint("gongu", __name__, url_prefix="/gongu-perf")


@gongu_bp.before_request
def _require_login():
    if not session.get("user_id"):
        return redirect(url_for("login", next=request.path))

MONTHS = [f"{i:02d}" for i in range(1, 13)]

# 신규 공구 예상 계산기 - 팔로워 수 드롭다운 선택지 (10만 단위, 10만 이하 ~ 70만 이상)
FC_FOLLOWER_OPTIONS = [
    {"value": 100000, "label": "10만 이하"},
    {"value": 200000, "label": "20만"},
    {"value": 300000, "label": "30만"},
    {"value": 400000, "label": "40만"},
    {"value": 500000, "label": "50만"},
    {"value": 600000, "label": "60만"},
    {"value": 700000, "label": "70만 이상"},
]

# 신규 공구 예상 계산기 - 보수적/권장/공격적 재고를 예상 판매 수량의 몇 %로 잡을지
FC_LOW_RATIO = 0.8
FC_MID_RATIO = 1.05
FC_HIGH_RATIO = 1.3


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
    total_revenue = sum(r["revenue"] for r in records)
    avg_revenue = total_revenue / n if n else 0
    # 팔로워 기준 매출 벤치마크 (1만 / 5만 / 10만 / 30만명 가정 시 예상 매출)
    # 기록별 "1만 명당 매출"의 중앙값을 쓴다 (매출 큰 기록 한 건에 끌려가지 않도록,
    # 합계 비율 대신 백분위 방식으로 바꿈 — 작업지시서 01의 1단계).
    revenue_rates = [per_10k(r["revenue"], r["followers"]) for r in records if r["followers"]]
    median_rate_per_10k = bands(revenue_rates)["mid"] if revenue_rates else 0
    follower_benchmarks = [
        {"label": "팔로워 1만명 기준", "revenue": median_rate_per_10k * 1},
        {"label": "팔로워 5만명 기준", "revenue": median_rate_per_10k * 5},
        {"label": "팔로워 10만명 기준", "revenue": median_rate_per_10k * 10},
        {"label": "팔로워 30만명 기준", "revenue": median_rate_per_10k * 30},
    ]
    avg_return = sum(gongu_return_pct(r) for r in records) / n if n else 0

    # 셀러별 성과 분석 (모든 회차 합산)
    seller_groups = {}
    for r in records:
        name = (r["seller"] or "").strip()
        if not name:
            continue
        g = seller_groups.setdefault(name, {"followers": 0, "revenue": 0, "sold_qty": 0, "return_qty": 0, "products": [], "count": 0, "records": []})
        g["followers"] = max(g["followers"], r["followers"])
        g["revenue"] += r["revenue"]
        g["sold_qty"] += r["sold_qty"]
        g["return_qty"] += r["return_qty"]
        if r["product"]:
            g["products"].append(r["product"])
        g["count"] += 1
        g["records"].append(r)
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
                # 회차가 1건뿐인 셀러는 그 원본 데이터를 그대로 수정할 수 있어요.
                # (여러 회차가 합산된 값은 어느 회차를 고칠지 애매해서, 그 경우엔 수정 버튼을 숨겨요.)
                "record": g["records"][0] if g["count"] == 1 else None,
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
            tiers.append({"tier": t, "count": 0, "avg_revenue": 0, "avg_sold": 0})
            continue
        tiers.append({
            "tier": t,
            "count": len(arr),
            "avg_revenue": sum(x["revenue"] for x in arr) / len(arr),
            "avg_sold": sum(gongu_net_sold(x) for x in arr) / len(arr),
        })

    # 제품별 평균
    # "1만 명당 판매량"을 보수(25%)/보통(중앙값)/낙관(75%) 백분위로 계산한다 (작업지시서 01의 1단계).
    # 평균 대신 백분위를 쓰는 이유: 기록 하나가 유독 크면(예: 팔로워 73만에 매출 2.36억) 평균이
    # 그 기록 쪽으로 크게 끌려가서 다른 셀러들의 실제 성과를 왜곡하기 때문.
    product_groups = {}
    for r in records:
        p = r["product"] or "미지정"
        product_groups.setdefault(p, []).append(r)
    products = []
    for p, arr in product_groups.items():
        avg_return = sum(gongu_return_pct(x) for x in arr) / len(arr)
        risk = "위험" if avg_return >= 20 else ("주의" if avg_return >= 10 else "양호")
        qty_rates = [per_10k(gongu_net_sold(x), x["followers"]) for x in arr if x["followers"]]
        qty_bands = bands(qty_rates) if qty_rates else {"low": 0, "mid": 0, "high": 0}
        products.append({
            "product": p, "count": len(arr),
            "avg_revenue": sum(x["revenue"] for x in arr) / len(arr),
            "per10k_low": qty_bands["low"], "per10k_mid": qty_bands["mid"], "per10k_high": qty_bands["high"],
            "avg_return": avg_return, "risk": risk,
            "low_sample": len(arr) < 3,
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
                "low": f"{round(qty * FC_LOW_RATIO):,}개",
                "mid": f"{round(qty * FC_MID_RATIO):,}개",
                "high": f"{round(qty * FC_HIGH_RATIO):,}개",
                "low_pct": f"예상 판매 수량의 {FC_LOW_RATIO * 100:.0f}%",
                "mid_pct": f"예상 판매 수량의 {FC_MID_RATIO * 100:.0f}%",
                "high_pct": f"예상 판매 수량의 {FC_HIGH_RATIO * 100:.0f}%",
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
        records=records, count=n, avg_revenue=avg_revenue, follower_benchmarks=follower_benchmarks, avg_return=avg_return,
        sellers=sellers, tiers=tiers, products=products, forecast=forecast,
        fc_followers=fc_followers, fc_price=fc_price, fc_follower_options=FC_FOLLOWER_OPTIONS,
        won=won, pct=pct, net_sold=gongu_net_sold, return_pct=gongu_return_pct, manwon=manwon,
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


@gongu_bp.route("/<int:record_id>/edit", methods=["POST"])
def edit(record_id):
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
    db.update_gongu_record(record_id, data)
    flash("공구 데이터를 수정했어요.")
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


# ---------- 주문 엑셀 올리기 (작업지시서 01의 2단계) ----------
# 고객 이름·연락처·주소는 gongu_order_parser.py가 애초에 읽지 않는다. 이 화면과 아래 라우트는
# 그 파서가 돌려준 "옵션별 수량 합계"만 다룬다.

def _get_record_or_404(record_id):
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM gongu_records WHERE id = ?", (record_id,)).fetchone()
    conn.close()
    if row is None:
        from flask import abort
        abort(404)
    return dict(row)


@gongu_bp.route("/<int:record_id>/orders", methods=["GET"])
def orders_form(record_id):
    record = _get_record_or_404(record_id)
    existing = [dict(r) for r in db.list_gongu_record_options(record_id)]
    return render_template("gongu_orders.html", record=record, existing=existing, preview=None)


@gongu_bp.route("/<int:record_id>/orders/preview", methods=["POST"])
def orders_preview(record_id):
    record = _get_record_or_404(record_id)
    f = request.files.get("order_file")
    if not f or not f.filename:
        flash("파일을 선택해 주세요.")
        return redirect(url_for("gongu.orders_form", record_id=record_id))

    data = f.read()
    try:
        parsed = parse_courier_orders(data, filename=f.filename)
    except ValueError as e:
        flash(str(e))
        return redirect(url_for("gongu.orders_form", record_id=record_id))

    fingerprint = file_fingerprint(data)
    already_uploaded = db.find_order_upload(record_id, fingerprint) is not None

    all_options = [dict(o) for o in db.list_product_options()]
    preview_rows = []
    for r in parsed["rows"]:
        option_name = db.find_option_alias(r["option"])
        matched = None
        if option_name:
            opt = db.find_product_option(option_name)
            matched = dict(opt) if opt else None
        preview_rows.append({
            "raw": r["option"],
            "qty": r["qty"],
            "return_qty": r["return_qty"],
            "option_name": option_name,
            "price": matched["price"] if matched else None,
        })

    preview = {
        "filename": f.filename,
        "fingerprint": fingerprint,
        "already_uploaded": already_uploaded,
        "rows": preview_rows,
        "total_qty": parsed["total_qty"],
        "total_return_qty": parsed["total_return_qty"],
        "unmatched_count": sum(1 for r in preview_rows if not r["option_name"]),
    }
    return render_template("gongu_orders.html", record=record, existing=None,
                            preview=preview, all_options=all_options)


@gongu_bp.route("/<int:record_id>/orders/confirm", methods=["POST"])
def orders_confirm(record_id):
    record = _get_record_or_404(record_id)
    f = request.form
    n = int(f.get("row_count") or 0)

    rows_to_save = []
    for i in range(n):
        raw = f.get(f"row_{i}_raw", "")
        qty = int(f.get(f"row_{i}_qty") or 0)
        return_qty = int(f.get(f"row_{i}_return_qty") or 0)
        option_name = (f.get(f"row_{i}_option_name") or "").strip()
        if not raw or not qty or not option_name:
            continue
        # 처음 연결하는 옵션이면 별칭으로 저장해서 다음부터는 자동으로 인식되게 한다.
        if db.find_option_alias(raw) != option_name:
            opt_row = db.find_product_option(option_name)
            product_label = opt_row["product"] if opt_row else ""
            db.create_option_alias(raw, option_name, product_label, session.get("user_name"))
        opt_row = db.find_product_option(option_name)
        price = opt_row["price"] if opt_row else 0
        rows_to_save.append({
            "option_name": option_name,
            "qty": qty,
            "revenue": qty * price,
            "return_qty": return_qty,
        })

    if not rows_to_save:
        flash("연결된 옵션이 없어서 저장하지 않았어요. 옵션을 선택한 뒤 다시 눌러주세요.")
        return redirect(url_for("gongu.orders_form", record_id=record_id))

    db.save_gongu_record_options(record_id, rows_to_save)

    total_qty = sum(r["qty"] for r in rows_to_save)
    total_revenue = sum(r["revenue"] for r in rows_to_save)
    total_return = sum(r["return_qty"] for r in rows_to_save)
    updated = {
        "month": record["month"], "channel": record["channel"], "brand": record["brand"],
        "product": record["product"], "seller": record["seller"], "followers": record["followers"],
        "link": record["link"], "revenue": total_revenue, "sold_qty": total_qty, "return_qty": total_return,
    }
    db.update_gongu_record(record_id, updated)

    filename = f.get("filename", "")
    fingerprint = f.get("fingerprint", "")
    if filename and fingerprint:
        db.record_order_upload(record_id, filename, fingerprint, session.get("user_name"))

    flash(f"주문 엑셀을 반영했어요. 판매 수량 {total_qty:,}개 · 매출 {total_revenue:,}원 · 반품 {total_return:,}개")
    return redirect(url_for("gongu.index", brand=record["brand"] or None))
