from flask import Blueprint, render_template, request, redirect, url_for, session, flash

import db

schedule_bp = Blueprint("schedule", __name__, url_prefix="/schedule")

# 자료실(seed.py)에 이미 등록된 실제 브랜드 이름 그대로 사용해요.
BRANDS = ["코드니처", "빠이러스", "명퉤", "라이프스타일"]

# 자유 입력이지만, 처음 쓰는 사람이 참고할 수 있도록 자동완성 후보로 띄워주는 카테고리들
SUGGESTED_CATEGORIES = ["출시", "협찬", "공구", "테스트", "콘텐츠", "기타"]

SPONSOR_LABELS = {"none": "해당 없음", "sponsored": "협찬(제품 제공)", "paid": "유가 협찬"}


@schedule_bp.before_request
def _require_login():
    if not session.get("user_id"):
        return redirect(url_for("login", next=request.path))


def _fields_from_form(f):
    priority_raw = (f.get("priority") or "").strip()
    return {
        "brand": (f.get("brand") or "").strip(),
        "name": (f.get("name") or "").strip(),
        "category": (f.get("category") or "").strip(),
        "date": (f.get("date") or "").strip(),
        "priority": int(priority_raw) if priority_raw.isdigit() else None,
        "link": (f.get("link") or "").strip(),
        "selling": (f.get("selling") or "").strip(),
        "timing": (f.get("timing") or "").strip(),
        "group_buy_period": (f.get("group_buy_period") or "").strip(),
        "recommend_reason": (f.get("recommend_reason") or "").strip(),
        "sponsor_status": (f.get("sponsor_status") or "none").strip(),
        "sponsor_note": (f.get("sponsor_note") or "").strip(),
        "note": (f.get("note") or "").strip(),
    }


@schedule_bp.route("/")
def index():
    brand = request.args.get("brand") or None
    category = request.args.get("category") or None
    items = [dict(r) for r in db.list_product_schedule(brand, category)]

    categories = sorted(set(db.list_product_schedule_categories()) | set(SUGGESTED_CATEGORIES))

    groups = []
    for b in BRANDS:
        if brand and brand != b:
            continue
        b_items = [it for it in items if it["brand"] == b]
        if not brand and not b_items:
            continue
        groups.append({"name": b, "rows": b_items})
    # 등록된 브랜드 목록에 없는 값으로 저장된 항목도 놓치지 않도록 마지막에 묶어줘요
    known = set(BRANDS)
    leftover = [it for it in items if it["brand"] not in known]
    if leftover and not brand:
        groups.append({"name": "기타", "rows": leftover})

    return render_template(
        "schedule.html",
        groups=groups,
        count=len(items),
        brands=BRANDS,
        categories=categories,
        suggested_categories=SUGGESTED_CATEGORIES,
        brand=brand or "",
        category=category or "",
        sponsor_labels=SPONSOR_LABELS,
    )


@schedule_bp.route("/add", methods=["POST"])
def add():
    fields = _fields_from_form(request.form)
    if not fields["brand"] or not fields["name"]:
        flash("브랜드와 제품명은 꼭 입력해 주세요.")
        return redirect(url_for("schedule.index"))
    db.create_product_schedule(fields, session.get("user_name"))
    flash(f"'{fields['name']}' 일정을 추가했어요.")
    return redirect(url_for("schedule.index"))


@schedule_bp.route("/<int:item_id>/update", methods=["POST"])
def update(item_id):
    item = db.get_product_schedule(item_id)
    if not item:
        flash("항목을 찾을 수 없어요.")
        return redirect(url_for("schedule.index"))
    fields = _fields_from_form(request.form)
    if not fields["brand"] or not fields["name"]:
        flash("브랜드와 제품명은 꼭 입력해 주세요.")
        return redirect(url_for("schedule.index"))
    db.update_product_schedule(item_id, fields)
    flash(f"'{fields['name']}' 일정을 수정했어요.")
    return redirect(url_for("schedule.index"))


@schedule_bp.route("/<int:item_id>/delete", methods=["POST"])
def delete(item_id):
    db.delete_product_schedule(item_id)
    flash("삭제했어요.")
    return redirect(url_for("schedule.index"))
