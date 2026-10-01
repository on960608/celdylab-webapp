from flask import Blueprint, render_template, request, redirect, url_for, session, flash

import db
from analysis import gongu_net_sold, gongu_return_pct, gongu_tier, TIER_ORDER, won, pct, manwon, BRANDS
from gongu_forecast import bands, per_10k, round_half_up, normalize, GonguRecord, Option, forecast
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
    product = request.args.get("product") or None
    records = [dict(r) for r in db.list_gongu_records(brand, month, product)]
    for r in records:
        r["has_upload"] = db.has_order_upload(r["id"])

    # 목차의 "제품" 드롭다운은 "브랜드" 선택에 따라 바뀐다.
    # 제품명은 등록할 때 직접 입력하는 자유 텍스트라 자사 제품 카탈로그와 철자가
    # 다를 수 있어서(예: "변기세정서버" vs "변기수조 세정서버"), 카탈로그가 아니라
    # 실제로 등록된 공구 기록에 쓰인 제품명 그대로를 목록으로 만든다 (기록을 놓치지 않도록).
    records_for_brand = [dict(r) for r in db.list_gongu_records(brand, None, None)]
    filter_products = sorted({r["product"] for r in records_for_brand if r["product"]})

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
    sellers_total_count = len(sellers)
    sellers = sellers[:5]  # 상위 5명만 보여준다 (매출 높은 순). 특정 제품을 고르면 그 제품 기준 상위 5명.

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
        product=product, filter_products=filter_products,
        records=records, count=n, avg_revenue=avg_revenue, follower_benchmarks=follower_benchmarks, avg_return=avg_return,
        sellers=sellers, sellers_total_count=sellers_total_count, tiers=tiers, products=products, forecast=forecast,
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
    new_id = db.create_gongu_record(data, session.get("user_name"))
    flash("공구 데이터를 등록했어요. 주문 엑셀이 있으면 지금 올려서 매출·판매량·반품수량을 자동으로 채울 수 있어요.")
    return redirect(url_for("gongu.orders_form", record_id=new_id))


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
    return redirect(url_for("gongu.index", brand=f.get("brand") or None, month=request.args.get("month") or None, product=request.args.get("product") or None))


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


# ---------- 옵션 수량 계산기 (작업지시서 01의 3단계) ----------
# gongu_forecast.forecast()는 이미 만들어져 테스트까지 끝난 함수라 그대로 쓴다.
# 이 화면은 그 함수에 넣을 입력(제품의 옵션 목록 + 비중, 팔로워 수, 여유분)을 모으고,
# 나온 결과를 표로 보여주는 역할만 한다.

MANUAL_ROWS = 8  # 옵션을 직접 입력할 때 보여줄 빈 줄 수


def _build_forecast_records():
    rows = db.list_gongu_records()
    return [
        GonguRecord(r["product"], r["brand"], r["followers"], r["revenue"], gongu_net_sold(r))
        for r in rows
    ]


def _options_with_product_list():
    """옵션이 등록된 제품 이름 목록 (비슷한 제품 비율 불러오기용)."""
    return sorted({o["product"] for o in db.list_product_options()})


def _rows_for_product(product):
    """그 제품의 표준 옵션과, 지금까지 판매 비율로 채운 옵션 줄 목록을 돌려준다.
    등록된 옵션이 없으면 빈 줄만 있는 목록을 돌려준다."""
    all_opts = db.list_product_options()
    matched = [o for o in all_opts if normalize(o["product"]) == normalize(product)]
    if not matched:
        return [{"option_name": "", "share_pct": "", "pack_qty": "", "price": ""} for _ in range(MANUAL_ROWS)], False

    qty_hist = db.option_qty_by_product(product)
    total_hist = sum(qty_hist.values())
    rows = []
    for o in matched:
        if total_hist > 0:
            share_pct = round(qty_hist.get(o["option_name"], 0) / total_hist * 100, 1)
        else:
            share_pct = round(100 / len(matched), 1)
        rows.append({
            "option_name": o["option_name"], "share_pct": share_pct,
            "pack_qty": o["pack_qty"], "price": o["price"],
        })
    while len(rows) < MANUAL_ROWS:
        rows.append({"option_name": "", "share_pct": "", "pack_qty": "", "price": ""})
    return rows[:MANUAL_ROWS], (total_hist > 0)


@gongu_bp.route("/calculator", methods=["GET"])
def calculator_form():
    products = db.list_all_products()
    return render_template(
        "gongu_calculator.html", step="form", brands=BRANDS, products=products,
    )


@gongu_bp.route("/calculator/options", methods=["POST"])
def calculator_options():
    f = request.form
    borrow_from = (f.get("borrow_from") or "").strip()

    if borrow_from:
        # 이미 옵션 단계에 있는 상태에서 "비슷한 제품 비율 불러오기"를 누른 경우.
        # 브랜드/제품/팔로워/여유분은 원래 새로 계산하려던 값 그대로 유지한다.
        brand = f.get("brand", "").strip()
        product = f.get("product", "").strip()
        followers = f.get("followers", "").strip()
        margin_pct = f.get("margin_pct", "20").strip()
        rows, has_history = _rows_for_product(borrow_from)
        note = f"'{borrow_from}' 옵션과 판매 비율을 불러왔어요. 판매가·구성 수량을 이 제품에 맞게 고쳐 주세요."
    else:
        brand = f.get("brand", "").strip()
        product = (f.get("product_custom") or "").strip() or f.get("product_pick", "").strip()
        followers = f.get("followers", "").strip()
        margin_pct = f.get("margin", "20").strip()
        if not brand or not product or not followers:
            flash("브랜드, 제품, 팔로워 수를 모두 입력해 주세요.")
            return redirect(url_for("gongu.calculator_form"))
        rows, has_history = _rows_for_product(product)
        if not rows or not rows[0]["option_name"]:
            note = f"'{product}'은(는) 등록된 표준 옵션이 없는 제품이에요. 아래에 옵션을 직접 입력해 주세요. 비슷한 제품의 비율을 불러와서 시작할 수도 있어요."
        elif has_history:
            note = f"'{product}' 표준 옵션과 지금까지의 판매 비율로 채웠어요. 필요하면 고쳐서 계산하세요."
        else:
            note = f"'{product}' 표준 옵션이에요. 아직 판매 기록이 없어서 옵션 수만큼 똑같이 나눴어요 — 직접 고쳐 주세요."

    return render_template(
        "gongu_calculator.html", step="options", brand=brand, product=product,
        followers=followers, margin_pct=margin_pct, rows=rows, note=note,
        similar_products=_options_with_product_list(),
    )


@gongu_bp.route("/calculator/result", methods=["POST"])
def calculator_result():
    f = request.form
    brand = f.get("brand", "").strip()
    product = f.get("product", "").strip()
    followers = int(f.get("followers") or 0)
    margin_pct = f.get("margin_pct", "20").strip()
    try:
        margin = float(margin_pct) / 100
    except ValueError:
        margin = 0.2

    rows_in = []
    for i in range(MANUAL_ROWS):
        name = (f.get(f"row_{i}_option_name") or "").strip()
        share_pct = (f.get(f"row_{i}_share_pct") or "").strip()
        pack_qty = (f.get(f"row_{i}_pack_qty") or "").strip()
        price = (f.get(f"row_{i}_price") or "").strip()
        if not name or not share_pct:
            continue
        rows_in.append({"option_name": name, "share_pct": share_pct, "pack_qty": pack_qty, "price": price})

    def _bounce_back(message):
        flash(message)
        return render_template(
            "gongu_calculator.html", step="options", brand=brand, product=product,
            followers=followers, margin_pct=margin_pct,
            rows=(rows_in + [{"option_name": "", "share_pct": "", "pack_qty": "", "price": ""}
                              for _ in range(MANUAL_ROWS - len(rows_in))])[:MANUAL_ROWS],
            note="아래 내용을 확인해서 다시 시도해 주세요.",
            similar_products=_options_with_product_list(),
        )

    if not brand or not product or followers <= 0:
        return _bounce_back("브랜드, 제품, 팔로워 수를 다시 확인해 주세요.")
    if not rows_in:
        return _bounce_back("옵션을 하나 이상 입력해 주세요.")

    share_sum = 0.0
    try:
        options = []
        for r in rows_in:
            share = float(r["share_pct"]) / 100
            pack_qty = int(r["pack_qty"] or 1)
            price = int(r["price"] or 0)
            share_sum += share
            options.append(Option(r["option_name"], share, pack_qty, price))
    except ValueError:
        return _bounce_back("비중·구성 수량·판매가는 숫자로 입력해 주세요.")

    if abs(share_sum - 1) > 0.01:
        return _bounce_back(f"옵션 비중의 합이 100%가 아니에요 (지금 {share_sum * 100:.1f}%). 합이 100%가 되도록 고쳐 주세요.")

    records = _build_forecast_records()
    try:
        result = forecast(records, product, brand, followers, options, margin=margin)
    except ValueError as e:
        return _bounce_back(str(e))

    return render_template(
        "gongu_calculator.html", step="result", brand=brand, product=product,
        followers=followers, margin_pct=margin_pct, result=result, won=won,
    )
