"""
자사 제품 속성 관리 — 매출 기회 발굴 대시보드의 "자사 제품 자동 매칭"이 쓰는 원본 데이터.

자료실(archive_links)에는 브랜드/제품 "이름"만 있고 카테고리·용도·해결하는 문제·소비자 니즈·
연관 키워드 같은 속성은 없어서, 이 화면에서 별도로 채워요. 자동으로 채워지지 않고 반드시
담당자가 직접 입력해야 하는 데이터라, 입력 전까지는 그 제품이 트렌드 매칭에 나타나지 않아요.
"""
from flask import Blueprint, render_template, request, redirect, url_for, session, flash

import db
from analysis import OPPORTUNITY_CATEGORIES

products_bp = Blueprint("products", __name__, url_prefix="/products")


@products_bp.before_request
def _require_login():
    if not session.get("user_id"):
        return redirect(url_for("login", next=request.path))


@products_bp.route("/")
def index():
    profiles = db.list_product_profiles()
    filled = sum(1 for p in profiles if p["is_filled"])
    return render_template(
        "products.html",
        profiles=profiles, categories=OPPORTUNITY_CATEGORIES,
        filled_count=filled, total_count=len(profiles),
    )


@products_bp.route("/save", methods=["POST"])
def save():
    f = request.form
    brand = f.get("brand", "").strip()
    product = f.get("product", "").strip()
    if not brand or not product:
        flash("브랜드/제품 정보가 없어요.")
        return redirect(url_for("products.index"))

    fields = {
        "category": f.get("category", "").strip(),
        "usage_desc": f.get("usage_desc", "").strip(),
        "problem_solved": f.get("problem_solved", "").strip(),
        "consumer_need": f.get("consumer_need", "").strip(),
    }
    keywords = [k.strip() for k in f.get("keywords", "").split(",") if k.strip()]
    db.save_product_profile(brand, product, fields, keywords, session.get("user_name"))
    flash(f"'{brand} · {product}' 제품 정보를 저장했어요.")
    return redirect(url_for("products.index"))
