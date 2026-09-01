from flask import Blueprint, render_template, request, redirect, url_for, flash, session

import db
from analysis import listup_score, listup_verdict, gongu_per1k, gongu_return_pct, BRANDS

listup_bp = Blueprint("listup", __name__, url_prefix="/listup")


@listup_bp.before_request
def _require_login():
    if not session.get("user_id"):
        return redirect(url_for("login", next=request.path))


@listup_bp.route("/")
def index():
    contact_brand = request.args.get("brand") or BRANDS[0]

    candidates = [dict(c) for c in db.list_candidates()]
    for c in candidates:
        c["score"] = listup_score(c)
        c["verdict"] = listup_verdict(c)
        c["contacted"] = db.is_contacted(contact_brand, c["name"])
    candidates.sort(key=lambda c: -c["score"])

    total = len(candidates)
    passed = sum(1 for c in candidates if c["verdict"]["pass"])
    failed = total - passed
    contacted_count = sum(1 for c in candidates if c["contacted"])

    contacted_list = db.list_contacted(contact_brand)

    # 효율 좋은 추천 후보 (해당 브랜드로 등록된 공구 성과 데이터 기준, 컨택 안 한 사람 우선)
    gongu_records = [dict(r) for r in db.list_gongu_records(brand=contact_brand)]
    seller_groups = {}
    for r in gongu_records:
        name = (r["seller"] or "").strip()
        if not name:
            continue
        g = seller_groups.setdefault(name, {"followers": 0, "link": "", "per1k_sum": 0.0, "return_sum": 0.0, "n": 0})
        g["followers"] = max(g["followers"], r["followers"])
        if not g["link"] and r["link"]:
            g["link"] = r["link"]
        g["per1k_sum"] += gongu_per1k(r)
        g["return_sum"] += gongu_return_pct(r)
        g["n"] += 1
    pool = [
        {"name": name, "followers": g["followers"], "link": g["link"], "avg_per1k": g["per1k_sum"] / g["n"], "avg_return": g["return_sum"] / g["n"]}
        for name, g in seller_groups.items()
    ]
    recommend_pool = sorted([p for p in pool if not db.is_contacted(contact_brand, p["name"])], key=lambda p: -p["avg_per1k"])
    recommendations = recommend_pool[:30]
    remaining = max(0, len(recommend_pool) - 30)

    return render_template(
        "listup.html",
        brands=BRANDS, contact_brand=contact_brand,
        candidates=candidates, total=total, passed=passed, failed=failed, contacted_count=contacted_count,
        contacted_list=contacted_list, recommendations=recommendations, remaining=remaining,
        has_gongu_data=bool(gongu_records),
    )


@listup_bp.route("/add", methods=["POST"])
def add():
    f = request.form
    data = {
        "name": f.get("name", "").strip(),
        "link": f.get("link", "").strip(),
        "followers": int(f.get("followers") or 0),
        "views1": int(f.get("views1") or 0),
        "views2": int(f.get("views2") or 0),
        "views3": int(f.get("views3") or 0),
        "likes": int(f.get("likes") or 0),
        "comments": int(f.get("comments") or 0),
        "shares": int(f.get("shares") or 0),
        "last_upload": f.get("last_upload", "").strip(),
        "has_real_comments": 1 if f.get("has_real_comments") else 0,
        "sponsored_low": 1 if f.get("sponsored_low") else 0,
        "reason": f.get("reason", "").strip(),
    }
    if not data["name"]:
        flash("이름·계정을 입력해 주세요.")
        return redirect(url_for("listup.index"))
    db.upsert_candidate(data)
    flash("후보를 등록(또는 갱신)했어요.")
    return redirect(url_for("listup.index"))


@listup_bp.route("/<int:candidate_id>/delete", methods=["POST"])
def delete(candidate_id):
    db.delete_candidate(candidate_id)
    flash("삭제했어요.")
    return redirect(url_for("listup.index"))


@listup_bp.route("/contact/add", methods=["POST"])
def add_contact():
    brand = request.form.get("brand", "").strip() or BRANDS[0]
    name = request.form.get("name", "").strip()
    if name:
        db.add_contacted(brand, name)
    return redirect(url_for("listup.index", brand=brand))


@listup_bp.route("/contact/<int:contact_id>/delete", methods=["POST"])
def delete_contact(contact_id):
    brand = request.form.get("brand", "")
    db.delete_contacted(contact_id)
    return redirect(url_for("listup.index", brand=brand))
