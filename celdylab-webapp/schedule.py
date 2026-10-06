"""
스케줄링 — 시딩·공동구매 팀 업무 캘린더.

팀원들이 시딩/공구 일정을 월간 캘린더 한 화면에서 보고, 각 일정마다 담당자·진행상태·
체크리스트·코멘트까지 확인/관리할 수 있게 하는 기능이에요. 다른 화면(트렌드 분석, 공구
성과분석 등)에는 전혀 영향을 주지 않는 독립 모듈이고, DB도 새 테이블 4개만 추가로 써요
(schema.sql의 schedules / schedule_assignees / schedule_tasks / schedule_comments).

일정 유형(시딩/공구) 필터·담당자 필터·검색은 이 화면에서 새로고침 없이 자바스크립트로만
동작해요 — 한 달치 일정 데이터를 화면에 한 번에 내려주고, 보이기/숨기기만 전환하는 방식이에요.
월을 이동할 때만 서버에 새로 요청해요.
"""
import calendar
import json
from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for, flash

import db

schedule_bp = Blueprint("schedule", __name__, url_prefix="/schedule")

TYPES = ["시딩", "공구", "공통", "정산"]
TYPE_COLORS = {"시딩": {"bg": "#eaf1ff", "border": "#8fb4f5", "text": "#2f5fb8", "dot": "#3f7ce0"},
               "공구": {"bg": "#e8f7ee", "border": "#8fd3ab", "text": "#1f8a4c", "dot": "#2aa860"},
               "공통": {"bg": "#f2eefc", "border": "#b7a3e8", "text": "#6a46c4", "dot": "#8a63e0"},
               "정산": {"bg": "#fff2e3", "border": "#e6b579", "text": "#a8650f", "dot": "#e0932f"}}
STATUSES = ["예정", "진행중", "확인 필요", "완료"]
PRIORITIES = ["일반", "중요", "긴급"]
# 2026-10-01: 일정표에서 중요도가 "긴급"인 일정은 유형 색과 상관없이 빨간색으로 눈에 띄게
# 표시해요(희현님 확인). type_colors와는 별개로 priority 전용 색을 하나만 둬요.
URGENT_COLOR = {"bg": "#fdeaea", "border": "#e2847a", "text": "#b7291a", "dot": "#d9453f"}

# 12번 문단 — 일정 등록 시 유형에 맞춰 자동으로 깔아주는 기본 체크리스트예요.
# (나중에 "템플릿으로 저장" 기능을 붙일 때 이 상수를 별도 테이블로 옮기기 쉽게 구조를 단순하게 유지)
# 2026-10-01: "공통"은 미리 깔리는 체크리스트 없이 필요할 때마다 직접 업무를 추가하는 용도라
# 빈 목록으로 둬요. "정산"은 비용지급 확인 → 엑셀 기입 → 지결 올리기 3단계만 깔려요(희현님 확인).
DEFAULT_CHECKLISTS = {
    "시딩": [
        "인플루언서 리스트 확정", "컨택 완료", "주소 취합", "제품 출고", "송장 전달",
        "콘텐츠 가이드 전달", "업로드 일정 확인", "콘텐츠 업로드 확인", "수정 요청", "최종 완료",
    ],
    "공구": [
        "인플루언서 확정", "공구 조건 협의", "샘플 발송", "공구 가이드 전달", "콘텐츠 일정 확인",
        "공구 페이지 준비", "사전 홍보", "공구 오픈", "진행 모니터링", "공구 종료", "결과 정리",
    ],
    "공통": [],
    "정산": ["비용지급 확인", "엑셀 기입", "지결올리기"],
}

WEEKDAY_LABELS = ["월", "화", "수", "목", "금", "토", "일"]


@schedule_bp.before_request
def _require_login():
    if not session.get("user_id"):
        return redirect(url_for("login", next=request.path))


def _parse_date(s, fallback=None):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return fallback


def _month_grid(year, month):
    """해당 월을 꽉 채우는 주 단위(월~일) 날짜 리스트를 만들어요. 앞/뒤 달의 날짜도 채워서
    항상 완전한 7일짜리 주로만 구성돼요(달력이 이빨 빠진 것처럼 보이지 않게)."""
    cal = calendar.Calendar(firstweekday=0)  # 0 = 월요일
    weeks = []
    for week in cal.monthdatescalendar(year, month):
        weeks.append(list(week))
    return weeks


def _fields_from_form(f):
    start_date = (f.get("start_date") or "").strip()
    end_date = (f.get("end_date") or "").strip() or start_date
    if end_date < start_date:
        end_date = start_date
    group_id_raw = (f.get("group_id") or "").strip()
    return {
        "type": (f.get("type") or "시딩").strip() if (f.get("type") or "").strip() in TYPES else "시딩",
        "title": (f.get("title") or "").strip(),
        "brand": (f.get("brand") or "").strip(),
        "product": (f.get("product") or "").strip(),
        "description": (f.get("description") or "").strip(),
        "start_date": start_date,
        "end_date": end_date,
        "start_time": (f.get("start_time") or "").strip(),
        "end_time": (f.get("end_time") or "").strip(),
        "status": (f.get("status") or "예정").strip() if (f.get("status") or "").strip() in STATUSES else "예정",
        "priority": (f.get("priority") or "일반").strip() if (f.get("priority") or "").strip() in PRIORITIES else "일반",
        "group_id": int(group_id_raw) if group_id_raw.isdigit() else None,
        "memo": (f.get("memo") or "").strip(),
    }


def _ids_from_form(f, key):
    return [int(v) for v in f.getlist(key) if v.isdigit()]


def _build_calendar(year, month, schedules):
    """월 그리드 + 각 일정을 주별로 겹치지 않게 lane(줄)에 배치한 bar 데이터를 만들어요.
    기간이 있는 일정(시작일~마감일)은 여러 날짜에 걸친 막대(bar)로 표시하기 위한 계산이에요."""
    today = date.today()
    weeks_dates = _month_grid(year, month)
    weeks = []
    for week_dates in weeks_dates:
        week_start, week_end = week_dates[0], week_dates[-1]
        days = [
            {
                "iso": d.isoformat(),
                "day": d.day,
                "is_today": d == today,
                "is_other_month": d.month != month,
                "show_month_label": d.day == 1,
            }
            for d in week_dates
        ]

        segments = []
        for s in schedules:
            s_start, s_end = s["_start"], s["_end"]
            if s_end < week_start or s_start > week_end:
                continue
            seg_start = max(s_start, week_start)
            seg_end = min(s_end, week_end)
            col_start = (seg_start - week_start).days
            col_end = (seg_end - week_start).days
            segments.append({
                "schedule": s,
                "col_start": col_start,
                "span": col_end - col_start + 1,
                "continues_left": seg_start > s_start,
                "continues_right": seg_end < s_end,
            })

        segments.sort(key=lambda seg: (seg["col_start"], -seg["span"]))
        lane_end = []  # 각 lane에서 마지막으로 채운 col
        for seg in segments:
            placed = False
            for i, end_col in enumerate(lane_end):
                if end_col < seg["col_start"]:
                    lane_end[i] = seg["col_start"] + seg["span"] - 1
                    seg["lane"] = i
                    placed = True
                    break
            if not placed:
                lane_end.append(seg["col_start"] + seg["span"] - 1)
                seg["lane"] = len(lane_end) - 1

        weeks.append({"days": days, "segments": segments, "lane_count": max(len(lane_end), 1)})
    return weeks


@schedule_bp.route("/")
def index():
    today = date.today()
    try:
        year = int(request.args.get("year", today.year))
        month = int(request.args.get("month", today.month))
        if month < 1 or month > 12:
            raise ValueError
    except (TypeError, ValueError):
        year, month = today.year, today.month

    weeks_dates = _month_grid(year, month)
    grid_start, grid_end = weeks_dates[0][0], weeks_dates[-1][-1]

    raw_schedules = db.list_schedules_for_range(grid_start.isoformat(), grid_end.isoformat())
    for s in raw_schedules:
        s["_start"] = _parse_date(s["start_date"], grid_start)
        s["_end"] = _parse_date(s["end_date"], grid_end)

    weeks = _build_calendar(year, month, raw_schedules)

    prev_month = date(year, month, 1) - timedelta(days=1)
    next_month = date(year, month, 28) + timedelta(days=7)
    next_month = date(next_month.year, next_month.month, 1)

    employees = db.list_employees()
    groups = db.list_trend_groups()

    # 자바스크립트에서 필터/검색/상세보기에 그대로 쓸 수 있도록 이번 달 일정 전체를 JSON으로도 내려줘요.
    schedules_json = [
        {
            "id": s["id"], "type": s["type"], "title": s["title"], "brand": s["brand"], "product": s["product"],
            "status": s["status"], "priority": s["priority"],
            "start_date": s["start_date"], "end_date": s["end_date"],
            "start_time": s["start_time"], "end_time": s["end_time"],
            "assignees": s["assignees"], "participants": s["participants"],
            "search_text": " ".join([s["title"], s["brand"], s["product"]] + [a["name"] for a in s["assignees"]]).lower(),
        }
        for s in raw_schedules
    ]

    today_tasks = db.list_today_tasks(today.isoformat())

    return render_template(
        "schedule.html",
        year=year, month=month, weeks=weeks,
        month_label=f"{year}년 {month}월",
        prev_year=prev_month.year, prev_month=prev_month.month,
        next_year=next_month.year, next_month=next_month.month,
        weekday_labels=WEEKDAY_LABELS,
        types=TYPES, statuses=STATUSES, priorities=PRIORITIES,
        type_colors=TYPE_COLORS, type_colors_json=json.dumps(TYPE_COLORS, ensure_ascii=False),
        urgent_color=URGENT_COLOR, urgent_color_json=json.dumps(URGENT_COLOR, ensure_ascii=False),
        employees=employees, groups=groups,
        schedules_json=json.dumps(schedules_json, ensure_ascii=False),
        today_tasks=today_tasks, today_iso=today.isoformat(),
        today_count=len(today_tasks),
    )


@schedule_bp.route("/<int:schedule_id>/detail")
def detail(schedule_id):
    s = db.get_schedule(schedule_id)
    if not s:
        return jsonify({"ok": False, "error": "일정을 찾을 수 없어요."}), 404
    return jsonify({"ok": True, "schedule": s})


@schedule_bp.route("/add", methods=["POST"])
def add():
    fields = _fields_from_form(request.form)
    if not fields["title"] or not fields["start_date"]:
        flash("업무명과 시작일은 꼭 입력해 주세요.")
        return redirect(url_for("schedule.index"))
    schedule_id = db.create_schedule(fields, session.get("user_name"))
    assignee_ids = _ids_from_form(request.form, "assignee_ids")
    participant_ids = _ids_from_form(request.form, "participant_ids")
    db.set_schedule_assignees(schedule_id, assignee_ids, participant_ids)
    for i, title in enumerate(DEFAULT_CHECKLISTS.get(fields["type"], [])):
        db.add_schedule_task(schedule_id, title, sort_order=i)
    flash(f"'{fields['title']}' 일정을 추가했어요. 기본 체크리스트도 함께 만들어졌어요.")
    return redirect(url_for("schedule.index", year=fields["start_date"][:4], month=int(fields["start_date"][5:7])))


@schedule_bp.route("/<int:schedule_id>/update", methods=["POST"])
def update(schedule_id):
    existing = db.get_schedule(schedule_id)
    if not existing:
        flash("일정을 찾을 수 없어요.")
        return redirect(url_for("schedule.index"))
    fields = _fields_from_form(request.form)
    if not fields["title"] or not fields["start_date"]:
        flash("업무명과 시작일은 꼭 입력해 주세요.")
        return redirect(url_for("schedule.index"))
    db.update_schedule(schedule_id, fields)
    assignee_ids = _ids_from_form(request.form, "assignee_ids")
    participant_ids = _ids_from_form(request.form, "participant_ids")
    db.set_schedule_assignees(schedule_id, assignee_ids, participant_ids)
    flash(f"'{fields['title']}' 일정을 수정했어요.")
    return redirect(url_for("schedule.index", year=fields["start_date"][:4], month=int(fields["start_date"][5:7])))


@schedule_bp.route("/<int:schedule_id>/delete", methods=["POST"])
def delete(schedule_id):
    db.delete_schedule(schedule_id)
    flash("일정을 삭제했어요.")
    return redirect(url_for("schedule.index"))


@schedule_bp.route("/<int:schedule_id>/status", methods=["POST"])
def set_status(schedule_id):
    status = (request.json or {}).get("status") if request.is_json else request.form.get("status")
    if status not in STATUSES:
        return jsonify({"ok": False, "error": "잘못된 상태예요."}), 400
    db.update_schedule_status(schedule_id, status)
    return jsonify({"ok": True, "status": status})


@schedule_bp.route("/tasks/add", methods=["POST"])
def tasks_add():
    data = request.get_json(silent=True) or request.form
    schedule_id = data.get("schedule_id")
    title = (data.get("title") or "").strip()
    if not schedule_id or not title:
        return jsonify({"ok": False, "error": "업무 이름을 입력해 주세요."}), 400
    task_id = db.add_schedule_task(schedule_id, title, due_date=(data.get("due_date") or "").strip())
    return jsonify({"ok": True, "task_id": task_id})


@schedule_bp.route("/tasks/<int:task_id>/toggle", methods=["POST"])
def tasks_toggle(task_id):
    db.toggle_schedule_task(task_id)
    task = db.get_schedule_task(task_id)
    return jsonify({"ok": True, "completed": bool(task["completed"]) if task else None})


@schedule_bp.route("/tasks/<int:task_id>/delete", methods=["POST"])
def tasks_delete(task_id):
    db.delete_schedule_task(task_id)
    return jsonify({"ok": True})


@schedule_bp.route("/<int:schedule_id>/tasks/complete-default-today", methods=["POST"])
def tasks_complete_default_today(schedule_id):
    """'오늘 해야 할 업무'에서 일정 하나로 묶여 보이는 기본 체크리스트(마감일 없음) 항목들을
    한 번에 완료 처리해요 (db.list_today_tasks의 kind='schedule' 줄용)."""
    db.complete_default_today_tasks(schedule_id)
    return jsonify({"ok": True})


@schedule_bp.route("/comments/add", methods=["POST"])
def comments_add():
    data = request.get_json(silent=True) or request.form
    schedule_id = data.get("schedule_id")
    content = (data.get("content") or "").strip()
    if not schedule_id or not content:
        return jsonify({"ok": False, "error": "코멘트 내용을 입력해 주세요."}), 400
    db.add_schedule_comment(schedule_id, session.get("user_id"), content)
    return jsonify({"ok": True})
