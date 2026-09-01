from collections import Counter
from flask import Blueprint, render_template, request, redirect, url_for, session, flash

import db
from analysis import insight_metrics, pct, BRANDS

insight_bp = Blueprint("insight", __name__, url_prefix="/insight")


@insight_bp.before_request
def _require_login():
    if not session.get("user_id"):
        return redirect(url_for("login", next=request.path))

STOPWORDS = {"이번", "공구", "진행", "제품", "브랜드", "판매", "구매", "가격", "배송", "무료", "상품", "기간", "오늘", "오픈", "영상", "콘텐츠", "있는", "합니다", "했어요", "하는"}


def _extract_words(text):
    if not text:
        return []
    import re
    return [w for w in re.split(r"[,.\s/·\-]+", text) if len(w) >= 2]


@insight_bp.route("/")
def index():
    brand = request.args.get("brand") or None
    product = request.args.get("product") or None
    records = db.list_insight_records(brand, product)
    products = db.list_insight_products(brand)

    rows = []
    for r in records:
        m = insight_metrics(r)
        rows.append({**dict(r), "metrics": m})

    n = len(rows)
    if n:
        avg_eng = sum(x["metrics"]["engagement"] for x in rows) / n
        avg_save = sum(x["metrics"]["save_rate"] for x in rows) / n
        avg_reach = sum(x["metrics"]["reach_rate"] for x in rows) / n
    else:
        avg_eng = avg_save = avg_reach = None

    top_result = "2개 이상 등록하면 순위가 표시됩니다."
    reasons_result = "데이터를 등록하면 분석 결과가 표시됩니다."
    direction_result = "추천 후킹과 흐름이 표시됩니다."
    if n >= 1:
        best = max(rows, key=lambda x: x["metrics"]["engagement"])
        top_result = f"『{best['product'] or '(제품명 없음)'}』({best['seller'] or '셀러 미상'}) — 반응률 {pct(best['metrics']['engagement'])}"
    if n >= 2:
        above = [x for x in rows if x["metrics"]["engagement"] >= avg_eng]
        words = Counter()
        for x in above:
            for w in _extract_words(x["features"]):
                if w not in STOPWORDS:
                    words[w] += 1
        common = [w for w, c in words.most_common(5) if c >= 2]
        reasons_result = ("평균 이상 콘텐츠에서 자주 등장한 특징: " + ", ".join(common)) if common else "평균 이상 콘텐츠들 사이에 뚜렷하게 겹치는 특징 키워드가 아직 안 보여요. 데이터가 더 쌓이면 다시 분석해 드려요."
        reach_note = "도달률이 저장률보다 높은 편이에요 — 신규 노출 중심 콘텐츠가 잘 통하고 있어요." if avg_reach >= avg_save else "저장률이 도달률보다 높은 편이에요 — 저장해두고 싶은 정보성 콘텐츠가 잘 통하고 있어요."
        direction_result = reach_note + (" 다음 콘텐츠도 위 특징을 참고해서 기획해보세요." if common else "")

    categories = db.list_insight_categories()

    return render_template(
        "insight.html",
        brands=BRANDS, brand=brand, product=product, products=products,
        rows=rows, count=n, avg_eng=avg_eng, avg_save=avg_save, avg_reach=avg_reach,
        top_result=top_result, reasons_result=reasons_result, direction_result=direction_result,
        categories=categories, pct=pct,
    )


@insight_bp.route("/add", methods=["POST"])
def add():
    f = request.form
    data = {
        "brand": f.get("brand", "").strip(),
        "product": f.get("product", "").strip(),
        "seller": f.get("seller", "").strip(),
        "followers": int(f.get("followers") or 0),
        "link": f.get("link", "").strip(),
        "views": int(f.get("views") or 0),
        "likes": int(f.get("likes") or 0),
        "comments": int(f.get("comments") or 0),
        "saves": int(f.get("saves") or 0),
        "shares": int(f.get("shares") or 0),
        "features": f.get("features", "").strip(),
    }
    db.create_insight_record(data, session.get("user_name"))
    flash("인사이트 데이터를 등록했어요.")
    return redirect(url_for("insight.index", brand=f.get("brand") or None))


@insight_bp.route("/<int:record_id>/delete", methods=["POST"])
def delete(record_id):
    db.delete_insight_record(record_id)
    flash("삭제했어요.")
    return redirect(url_for("insight.index"))


@insight_bp.route("/clear", methods=["POST"])
def clear():
    db.clear_insight_records()
    flash("전체 초기화했어요.")
    return redirect(url_for("insight.index"))


# ---- 캡처 폴더 관리 ----

@insight_bp.route("/categories/add", methods=["POST"])
def add_category():
    name = request.form.get("name", "").strip()
    if name:
        db.create_insight_category(name)
    return redirect(url_for("insight.index"))


@insight_bp.route("/categories/<int:category_id>/delete", methods=["POST"])
def delete_category(category_id):
    db.delete_insight_category(category_id)
    return redirect(url_for("insight.index"))


@insight_bp.route("/folders/add", methods=["POST"])
def add_folder():
    category_id = int(request.form.get("category_id"))
    label = request.form.get("label", "").strip()
    url_ = request.form.get("url", "").strip()
    if label and url_:
        db.add_insight_folder(category_id, label, url_)
    return redirect(url_for("insight.index"))


@insight_bp.route("/folders/<int:folder_id>/delete", methods=["POST"])
def delete_folder(folder_id):
    db.delete_insight_folder(folder_id)
    return redirect(url_for("insight.index"))
