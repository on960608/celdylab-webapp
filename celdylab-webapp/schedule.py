from flask import Blueprint, render_template, request, redirect, url_for, session, flash

import db

schedule_bp = Blueprint("schedule", __name__, url_prefix="/schedule")

# 자료실(seed.py)에 이미 등록된 실제 브랜드 이름 그대로 사용해요.
BRANDS = ["코드니처", "빠이러스", "명퉤", "라이프스타일"]

# 자유 입력이지만, 처음 쓰는 사람이 참고할 수 있도록 자동완성 후보로 띄워주는 카테고리들
SUGGESTED_CATEGORIES = ["출시", "협찬", "공구", "테스트", "콘텐츠", "기타"]

SPONSOR_LABELS = {"none": "해당 없음", "sponsored": "협찬(제품 제공)", "paid": "유가 협찬"}

# 캘린더/테스트 일정표에서 브랜드별로 구분해서 보여줄 때 쓰는 색상이에요 (이 화면 전용이라
# 전역 style.css가 아니라 schedule.html 안의 <style>에서만 써요).
BRAND_COLORS = {"코드니처": "#2AA8A0", "빠이러스": "#E8973A", "명퉤": "#D8618B", "라이프스타일": "#5C7BA6"}

STATUSES = [
    {"id": "pending", "name": "대기"},
    {"id": "inprogress", "name": "진행중"},
    {"id": "done", "name": "완료"},
    {"id": "hold", "name": "보류"},
]
STATUS_MAP = {s["id"]: s for s in STATUSES}


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
    import json

    import naver_datalab

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

    # ---------- 테스트 일정표 / 캘린더 전용 일정 / 네이버 트렌드 ----------
    tests = [dict(r) for r in db.list_schedule_tests()]
    events = [dict(r) for r in db.list_schedule_events()]

    snapshot_row = db.get_schedule_trend_snapshot()
    trend_snapshot = dict(snapshot_row) if snapshot_row else None
    if trend_snapshot:
        trend_snapshot["keyword_list"] = [k.strip() for k in (trend_snapshot.get("keywords") or "").split(",") if k.strip()]
        try:
            trend_snapshot["series"] = json.loads(trend_snapshot.get("series") or "[]")
        except ValueError:
            trend_snapshot["series"] = []
        max_ratio = max([s.get("ratio", 0) for s in trend_snapshot["series"]] or [1]) or 1
        for s in trend_snapshot["series"]:
            s["pct"] = round((s.get("ratio", 0) / max_ratio) * 100, 1)

    # 캘린더 탭용 이벤트 목록 — 제품 일정(전체, 브랜드 필터 무관) + 테스트 일정 + 캘린더 전용
    # 일정을 한 배열로 합쳐요.
    all_items = [dict(r) for r in db.list_product_schedule()]
    calendar_events = []
    for it in all_items:
        if it.get("date"):
            calendar_events.append({"date": it["date"], "title": it["name"], "brand": it["brand"], "kind": "제품"})
    for t in tests:
        if t.get("date"):
            calendar_events.append({
                "date": t["date"], "title": f'{t["product"]} · {t["item"]}'.strip(" ·"),
                "brand": t["brand"], "kind": "테스트",
            })
    for e in events:
        if e.get("date"):
            calendar_events.append({"date": e["date"], "title": e["title"], "brand": e.get("brand", ""), "kind": "일정"})

    return render_template(
        "schedule.html",
        groups=groups,
        count=len(items),
        brands=BRANDS,
        brand_colors=BRAND_COLORS,
        brand_colors_json=json.dumps(BRAND_COLORS, ensure_ascii=False),
        categories=categories,
        suggested_categories=SUGGESTED_CATEGORIES,
        brand=brand or "",
        category=category or "",
        sponsor_labels=SPONSOR_LABELS,
        tests=tests,
        events=events,
        statuses=STATUSES,
        status_map=STATUS_MAP,
        trend_snapshot=trend_snapshot,
        datalab_configured=naver_datalab.datalab_configured(),
        calendar_events_json=json.dumps(calendar_events, ensure_ascii=False),
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


# ---------------------------------------------------------------------------
# 테스트 일정표
# ---------------------------------------------------------------------------

@schedule_bp.route("/tests/save", methods=["POST"])
def tests_save():
    f = request.form
    product = (f.get("product") or "").strip()
    if not product:
        flash("제품명을 입력해 주세요.")
        return redirect(url_for("schedule.index"))
    db.create_schedule_test({
        "brand": (f.get("brand") or "").strip(), "product": product, "item": (f.get("item") or "").strip(),
        "date": (f.get("date") or "").strip(), "status": (f.get("status") or "pending").strip(),
        "assignee": (f.get("assignee") or "").strip(), "note": (f.get("note") or "").strip(),
    })
    flash("테스트 일정을 추가했어요.")
    return redirect(url_for("schedule.index"))


@schedule_bp.route("/tests/<test_id>/delete", methods=["POST"])
def tests_delete(test_id):
    db.delete_schedule_test(test_id)
    flash("테스트 일정을 삭제했어요.")
    return redirect(url_for("schedule.index"))


# ---------------------------------------------------------------------------
# 캘린더 전용 일정
# ---------------------------------------------------------------------------

@schedule_bp.route("/events/save", methods=["POST"])
def events_save():
    f = request.form
    title = (f.get("title") or "").strip()
    date_str = (f.get("date") or "").strip()
    if not title or not date_str:
        flash("제목과 날짜를 입력해 주세요.")
        return redirect(url_for("schedule.index"))
    db.create_schedule_event({
        "title": title, "date": date_str, "brand": (f.get("brand") or "").strip(),
        "note": (f.get("note") or "").strip(),
    })
    flash("일정을 추가했어요.")
    return redirect(url_for("schedule.index"))


@schedule_bp.route("/events/<event_id>/delete", methods=["POST"])
def events_delete(event_id):
    db.delete_schedule_event(event_id)
    flash("일정을 삭제했어요.")
    return redirect(url_for("schedule.index"))


# ---------------------------------------------------------------------------
# 네이버 트렌드 자동 새로고침
# ---------------------------------------------------------------------------

@schedule_bp.route("/trend/refresh", methods=["POST"])
def trend_refresh():
    import naver_datalab

    if not naver_datalab.datalab_configured():
        flash("네이버 API 키가 아직 설정되지 않았어요 (NAVER_SHOPPING_CLIENT_ID / NAVER_SHOPPING_CLIENT_SECRET).")
        return redirect(url_for("schedule.index"))

    snapshot, error = naver_datalab.fetch_trend_snapshot()
    if error:
        flash("네이버 트렌드 새로고침 실패 — " + error)
        return redirect(url_for("schedule.index"))

    db.save_schedule_trend_snapshot(snapshot)
    flash("네이버 트렌드를 새로고침했어요.")
    return redirect(url_for("schedule.index"))
