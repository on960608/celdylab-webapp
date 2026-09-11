"""
매출 기회 발굴 대시보드
외부 트렌드 발견 -> 인기 상품/키워드 분석 -> 자사 제품 매칭 -> 시딩 후보 선정 -> 시딩 성과 확인
-> 공구 후보 선정 -> 공구 진행 -> 실제 매출 확인, 이 흐름을 한 화면에서 이어주는 게 목표예요.

중요: 확보하지 못한 데이터를 임의의 숫자로 채우지 않아요. 네이버 API가 아직 연동되지 않았거나
구글 트렌드 수집이 실패하면, 그 지표는 계산에서 빠지고 화면에는 "N개 지표 중 M개로 계산됨"처럼
어떤 데이터로 계산된 결과인지 항상 함께 보여줘요.
"""
import os
import json
from collections import defaultdict
from datetime import date

from flask import Blueprint, render_template, request, redirect, url_for, session, flash

import db
from analysis import (
    TREND_PLATFORMS, OPPORTUNITY_CATEGORIES,
    summarize_groupbuy_exposure, compute_group_trend_metrics, compute_trend_score,
    compute_opportunity_score, product_group_fit_score, fetch_google_trends_for_group,
    fetch_naver_trends_for_group, fetch_naver_shopping_keyword_trend,
)

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


@dashboard_bp.before_request
def _require_login():
    if not session.get("user_id"):
        return redirect(url_for("login", next=request.path))


def _naver_configured():
    return bool(os.environ.get("NAVER_CLIENT_ID") and os.environ.get("NAVER_CLIENT_SECRET"))


def _current_year_month():
    return date.today().strftime("%Y-%m")


def _prev_year_month(year_month):
    y, m = (int(x) for x in year_month.split("-"))
    return f"{y-1}-12" if m == 1 else f"{y}-{m-1:02d}"


def _monthly_points_for_group(group_id):
    """이 상품군의 월별 검색 지수를 하나로 합쳐요. 같은 달에 여러 소스가 있으면 네이버를 우선해요
    (네이버가 절대 검색량에 더 가까운 공식 지표라서). 구글만 있으면 구글을 써요."""
    raw = db.list_trend_search_raw(group_id=group_id)
    by_month_source = {}
    for r in raw:
        if not r["collected_date"]:
            continue
        by_month_source.setdefault(r["collected_date"][:7], {})[r["source"]] = r["index_value"]
    points = []
    for month, sources in by_month_source.items():
        value = sources.get("naver_search")
        if value is None:
            value = sources.get("naver_shopping")
        if value is None:
            value = sources.get("google")
        if value is not None:
            points.append({"year_month": month, "value": value})
    return points


_SOURCE_LABELS = {"naver_search": "네이버 검색어트렌드", "naver_shopping": "네이버 쇼핑인사이트", "google": "구글 트렌드(보조)"}


def _chart_series_for_group(group_id):
    """그래프용 — 소스를 하나로 합치지 않고, 소스별로 따로따로 월별 지수를 돌려줘요.
    반환: [{"label": "네이버 검색어트렌드", "points": [{"year_month":..., "value":...}, ...]}, ...]
    (데이터가 있는 소스만 포함돼요. 하나도 없으면 빈 리스트.)"""
    raw = db.list_trend_search_raw(group_id=group_id)
    by_source = {}
    for r in raw:
        if not r["collected_date"] or r["index_value"] is None:
            continue
        by_source.setdefault(r["source"], []).append(
            {"year_month": r["collected_date"][:7], "value": r["index_value"]}
        )
    series = []
    for source in ("naver_search", "naver_shopping", "google"):
        points = sorted(by_source.get(source, []), key=lambda p: p["year_month"])
        if points:
            series.append({"label": _SOURCE_LABELS[source], "points": points})
    return series


def _compute_all_group_scores():
    groups = db.list_trend_groups()
    records = [dict(r) for r in db.list_trend_records()]
    results = []
    for g in groups:
        g_records = [r for r in records if r.get("product_group_id") == g["id"]]
        points = _monthly_points_for_group(g["id"])
        metrics, exposure = compute_group_trend_metrics(g_records, TREND_PLATFORMS, points)
        score_result = compute_trend_score(metrics)
        results.append({"group": g, "metrics": metrics, "exposure": exposure, "score_result": score_result})
    return results


def _snapshot_current_month(all_scores):
    """점수가 실제로 나온(=지표가 1개 이상 확보된) 상품군만 이번 달 스냅샷으로 남겨서 월별 이력을 쌓아요."""
    ym = _current_year_month()
    scored = [r for r in all_scores if r["score_result"]["score"] is not None]
    scored.sort(key=lambda r: -r["score_result"]["score"])
    for rank, r in enumerate(scored, start=1):
        db.upsert_monthly_trend_score(
            ym, r["group"]["id"], r["score_result"]["score"], rank,
            ",".join(r["score_result"]["used"]),
            json.dumps(r["metrics"], ensure_ascii=False, default=str),
        )
    return ym, scored


def _compute_category_rising(scored, prev_ym):
    groups_by_id = {g["id"]: g for g in db.list_trend_groups()}
    cur_by_cat = defaultdict(list)
    for r in scored:
        cur_by_cat[r["group"]["category"] or "미분류"].append(r["score_result"]["score"])

    prev_by_cat = defaultdict(list)
    for r in db.get_monthly_trend_scores(prev_ym):
        g = groups_by_id.get(r["group_id"])
        if not g or r["score"] is None:
            continue
        prev_by_cat[g["category"] or "미분류"].append(r["score"])

    result = []
    for cat, scores in cur_by_cat.items():
        if cat not in prev_by_cat or not prev_by_cat[cat]:
            continue  # 지난달 값이 없으면 "상승/하락"을 말할 수 없으니 비교 대상에서 제외
        cur_avg = sum(scores) / len(scores)
        prev_avg = sum(prev_by_cat[cat]) / len(prev_by_cat[cat])
        result.append({
            "category": cat, "cur_avg": round(cur_avg, 1), "prev_avg": round(prev_avg, 1),
            "delta": round(cur_avg - prev_avg, 1),
        })
    result.sort(key=lambda r: -r["delta"])
    return result


def _recompute_product_matches():
    """상품군 ↔ 자사 제품 키워드 겹침 점수를 다시 계산해서 캐시 테이블에 저장하고 반환해요."""
    groups = db.list_trend_groups()
    profiles = db.list_product_profiles_full()
    matches = []
    for g in groups:
        terms = [t["term"] for t in g["terms"]] or [g["name"]]
        for p in profiles:
            text_fields = [p["category"], p["usage_desc"], p["problem_solved"], p["consumer_need"], p["brand"], p["product"]]
            score, matched = product_group_fit_score(terms, p["keywords"], text_fields)
            if score > 0:
                db.upsert_product_group_match(g["id"], p["id"], score, ",".join(matched))
                matches.append({"group": g, "profile": p, "score": score, "matched": matched})
    return matches


def _compute_recommendations(all_scores):
    """트렌드 점수(있으면) 70% + 자사 제품 적합도 30%로 조합 — 트렌드 데이터가 아직 없으면 적합도만으로 계산돼요."""
    matches = _recompute_product_matches()
    scores_by_group = {r["group"]["id"]: r["score_result"]["score"] for r in all_scores}
    weights = {"trend_weight": 70, "seeding_weight": 0, "gongu_weight": 0, "fit_weight": 30}

    best_by_product = {}
    for m in matches:
        combo = compute_opportunity_score(scores_by_group.get(m["group"]["id"]), None, None, m["score"], weights)
        if combo["score"] is None:
            continue
        row = {**m, "combo_score": combo["score"], "combo_used": combo["used"],
               "trend_score": scores_by_group.get(m["group"]["id"])}
        pid = m["profile"]["id"]
        if pid not in best_by_product or row["combo_score"] > best_by_product[pid]["combo_score"]:
            best_by_product[pid] = row
    return sorted(best_by_product.values(), key=lambda r: -r["combo_score"])


def _compute_progress():
    candidates = [dict(c) for c in db.list_execution_candidates() if c["status"] != "완료"]
    gongu_records = [dict(r) for r in db.list_gongu_records()]
    insight_records = [dict(r) for r in db.list_insight_records()]
    rows = []
    for c in candidates:
        related_gongu = [r for r in gongu_records if r["brand"] == c["brand"] and r["product"] == c["product"]]
        related_insight = [r for r in insight_records if r["brand"] == c["brand"] and r["product"] == c["product"]]
        rows.append({
            "candidate": c,
            "revenue": sum(r["revenue"] for r in related_gongu),
            "gongu_count": len(related_gongu),
            "insight_count": len(related_insight),
        })
    return rows


@dashboard_bp.route("/")
def index():
    all_scores = _compute_all_group_scores()
    ym, scored = _snapshot_current_month(all_scores)
    prev_ym = _prev_year_month(ym)
    prev_scores = {r["group_id"]: r for r in db.get_monthly_trend_scores(prev_ym)}

    trend_top5 = []
    for rank, r in enumerate(scored[:5], start=1):
        prev = prev_scores.get(r["group"]["id"])
        trend_top5.append({
            "rank": rank, "group": r["group"], "score": r["score_result"]["score"],
            "used": r["score_result"]["used"], "missing": r["score_result"]["missing"],
            "prev_rank": prev["rank"] if prev else None,
        })

    rising = sorted(
        (r for r in all_scores if (r["metrics"]["mom_growth"] or 0) > 0),
        key=lambda r: -r["metrics"]["mom_growth"],
    )[:5]

    groups = db.list_trend_groups()
    records = [dict(r) for r in db.list_trend_records()]
    groupbuy_top = summarize_groupbuy_exposure(records, groups, TREND_PLATFORMS)[:5]

    category_rising = _compute_category_rising(scored, prev_ym)[:5]
    recommend_top5 = _compute_recommendations(all_scores)[:5]
    progress = _compute_progress()

    return render_template(
        "dashboard.html",
        trend_top5=trend_top5, rising=rising, groupbuy_top=groupbuy_top,
        category_rising=category_rising, recommend_top5=recommend_top5, progress=progress[:6],
        current_year_month=ym, has_any_group=bool(groups),
        naver_configured=_naver_configured(),
    )


@dashboard_bp.route("/trend")
def trend_detail():
    all_scores = _compute_all_group_scores()
    ym, scored = _snapshot_current_month(all_scores)
    prev_ym = _prev_year_month(ym)
    prev_scores = {r["group_id"]: r for r in db.get_monthly_trend_scores(prev_ym)}
    rows = []
    chart_data = {}
    for rank, r in enumerate(scored, start=1):
        prev = prev_scores.get(r["group"]["id"])
        rows.append({
            "rank": rank, "group": r["group"], "score": r["score_result"]["score"],
            "used": r["score_result"]["used"], "missing": r["score_result"]["missing"],
            "metrics": r["metrics"], "prev_rank": prev["rank"] if prev else None,
        })
        series = _chart_series_for_group(r["group"]["id"])
        if series:
            chart_data[r["group"]["id"]] = series
    return render_template(
        "dashboard_trend.html", rows=rows, current_year_month=ym,
        naver_configured=_naver_configured(), chart_data=chart_data,
    )


@dashboard_bp.route("/rising")
def rising_detail():
    all_scores = _compute_all_group_scores()
    rising = sorted(
        (r for r in all_scores if (r["metrics"]["mom_growth"] or 0) > 0),
        key=lambda r: -r["metrics"]["mom_growth"],
    )
    no_history = [r for r in all_scores if r["metrics"]["mom_growth"] is None]
    return render_template("dashboard_rising.html", rising=rising, no_history_count=len(no_history))


@dashboard_bp.route("/recommend")
def recommend_detail():
    all_scores = _compute_all_group_scores()
    rows = _compute_recommendations(all_scores)
    return render_template("dashboard_recommend.html", rows=rows)


@dashboard_bp.route("/groupbuy")
def groupbuy_detail():
    groups = db.list_trend_groups()
    records = [dict(r) for r in db.list_trend_records()]
    summaries = summarize_groupbuy_exposure(records, groups, TREND_PLATFORMS)
    return render_template("dashboard_groupbuy.html", summaries=summaries, platforms=TREND_PLATFORMS)


@dashboard_bp.route("/categories")
def categories_detail():
    all_scores = _compute_all_group_scores()
    ym, scored = _snapshot_current_month(all_scores)
    prev_ym = _prev_year_month(ym)
    rows = _compute_category_rising(scored, prev_ym)
    return render_template("dashboard_categories.html", rows=rows, current_year_month=ym, prev_year_month=prev_ym)


@dashboard_bp.route("/progress")
def progress_detail():
    return render_template("dashboard_progress.html", rows=_compute_progress())


@dashboard_bp.route("/candidate", methods=["POST"])
def add_candidate():
    kind = request.form.get("kind")
    profile_id = request.form.get("product_profile_id", type=int)
    group_id = request.form.get("group_id", type=int)
    reason = request.form.get("reason", "")
    if kind not in ("seeding", "gongu") or not profile_id:
        flash("잘못된 요청이에요.")
        return redirect(request.referrer or url_for("dashboard.index"))
    db.create_execution_candidate(kind, profile_id, group_id, reason, session.get("user_name"))
    flash("실행 후보로 등록했어요. 진행 현황(⑥)에서 확인할 수 있어요.")
    return redirect(request.referrer or url_for("dashboard.index"))


@dashboard_bp.route("/candidate/<int:candidate_id>/status", methods=["POST"])
def update_candidate_status(candidate_id):
    status = request.form.get("status", "").strip()
    if status:
        db.update_execution_candidate_status(candidate_id, status)
    return redirect(url_for("dashboard.progress_detail"))


@dashboard_bp.route("/settings")
def settings():
    return render_template(
        "dashboard_settings.html",
        weights=db.get_opportunity_weights(), groups=db.list_trend_groups(),
        naver_configured=_naver_configured(),
    )


@dashboard_bp.route("/settings/weights", methods=["POST"])
def save_weights():
    f = request.form
    db.save_opportunity_weights(
        float(f.get("trend_weight") or 0), float(f.get("seeding_weight") or 0),
        float(f.get("gongu_weight") or 0), float(f.get("fit_weight") or 0),
        session.get("user_name"),
    )
    flash("상품기회점수 가중치를 저장했어요.")
    return redirect(url_for("dashboard.settings"))


@dashboard_bp.route("/settings/collect-google", methods=["POST"])
def collect_google():
    groups = db.list_trend_groups()
    if not groups:
        flash("먼저 상품군을 1개 이상 만들어 주세요.")
        return redirect(url_for("dashboard.settings"))
    today = date.today().isoformat()
    ok, failed, messages = 0, 0, []
    for g in groups:
        terms = [t["term"] for t in g["terms"]] or [g["name"]]
        value, err = fetch_google_trends_for_group(g["name"], terms)
        if value is not None:
            db.add_trend_search_raw("google", g["id"], today, value)
            ok += 1
        else:
            failed += 1
            messages.append(f"{g['name']}: {err}")
    flash(f"구글 트렌드 수집 완료 — 성공 {ok}건 / 실패(생략) {failed}건" + (f" · {messages[0]}" if messages else ""))
    return redirect(url_for("dashboard.settings"))


@dashboard_bp.route("/settings/collect-naver", methods=["POST"])
def collect_naver():
    groups = db.list_trend_groups()
    if not groups:
        flash("먼저 상품군을 1개 이상 만들어 주세요.")
        return redirect(url_for("dashboard.settings"))
    if not _naver_configured():
        flash("네이버 API 키(NAVER_CLIENT_ID/NAVER_CLIENT_SECRET)가 아직 설정되어 있지 않아요.")
        return redirect(url_for("dashboard.settings"))

    ok, failed, total_points, messages = 0, 0, 0, []
    for g in groups:
        terms = [t["term"] for t in g["terms"]] or [g["name"]]
        points, err = fetch_naver_trends_for_group(g["name"], terms)
        if points:
            for p in points:
                db.add_trend_search_raw("naver_search", g["id"], f"{p['year_month']}-01", p["value"])
            total_points += len(points)
            ok += 1
        else:
            failed += 1
            messages.append(f"{g['name']}: {err}")

    # 쇼핑인사이트는 "쇼핑 카테고리"를 지정해둔 상품군만 수집돼요 (설정 안 했으면 조용히 건너뜀).
    shop_ok, shop_failed, shop_points = 0, 0, 0
    for g in groups:
        if not g.get("shopping_category"):
            continue
        terms = [t["term"] for t in g["terms"]] or [g["name"]]
        points, err = fetch_naver_shopping_keyword_trend(g["shopping_category"], g["name"], terms)
        if points:
            for p in points:
                db.add_trend_search_raw("naver_shopping", g["id"], f"{p['year_month']}-01", p["value"])
            shop_points += len(points)
            shop_ok += 1
        else:
            shop_failed += 1
            messages.append(f"[쇼핑인사이트] {g['name']}: {err}")

    shop_msg = f" · 쇼핑인사이트 성공 {shop_ok}개/실패 {shop_failed}건({shop_points}개월치)" if (shop_ok or shop_failed) else ""
    flash(
        f"네이버 검색어트렌드 수집 완료 — 성공 {ok}개 상품군 / 실패 {failed}건 (총 {total_points}개월치 저장)"
        + shop_msg
        + (f" · {messages[0]}" if messages else "")
    )
    return redirect(url_for("dashboard.settings"))
