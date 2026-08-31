import os
import functools
from urllib.parse import quote
from flask import Flask, render_template, request, redirect, url_for, session, flash

from werkzeug.security import check_password_hash

import db

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")

# 앱이 처음 켜질 때 DB 파일/테이블이 없으면 자동으로 만들고, 기본 브랜드·제품 목록과
# 데모 로그인 계정도 함께 채워줘요. 배포 환경(Railway 등)에서 첫 실행 시 한 번만 동작해요.
if not os.path.exists(db.DB_PATH):
    import seed
    seed.main()


# ---------------------------------------------------------------------------
# 로그인 / 인증
# ---------------------------------------------------------------------------

def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@app.context_processor
def inject_user():
    name = session.get("user_name")
    return {"current_user_name": name}


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        emp = db.get_employee_by_username(username)
        if emp and check_password_hash(emp["password_hash"], password):
            session.clear()
            session["user_id"] = emp["id"]
            session["user_name"] = emp["name"]
            next_url = request.args.get("next") or url_for("archive")
            return redirect(next_url)
        flash("아이디 또는 비밀번호가 맞지 않아요.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# 홈 / 자료실
# ---------------------------------------------------------------------------

@app.route("/")
@login_required
def index():
    return redirect(url_for("archive"))


def drive_search_url(q):
    return "https://drive.google.com/drive/search?q=" + quote(q)


@app.route("/archive")
@login_required
def archive():
    data = db.list_archive_links()
    brands = []
    for brand, info in data.items():
        brand_url = info["brand_url"] or drive_search_url(brand)
        brand_has_link = bool(info["brand_url"])
        products = []
        for p in info["products"]:
            url = p["url"] or (info["brand_url"] or drive_search_url(brand + "_" + p["name"]))
            products.append({"name": p["name"], "url": url, "has_link": bool(p["url"])})
        brands.append({"name": brand, "url": brand_url, "has_link": brand_has_link, "products": products})
    return render_template("archive.html", brands=brands)


@app.route("/archive/update", methods=["POST"])
@login_required
def archive_update():
    brand = request.form.get("brand", "").strip()
    product = request.form.get("product", "").strip()
    url = request.form.get("url", "").strip()
    if not brand:
        flash("브랜드 정보가 없어요.")
        return redirect(url_for("archive"))
    db.upsert_archive_link(brand, product, url, session.get("user_name"))
    flash(f"{brand}{(' · ' + product) if product else ''} 링크를 저장했어요.")
    return redirect(url_for("archive"))


# ---------------------------------------------------------------------------
# 앞으로 채워질 페이지들 (지금은 자리만) — 여기에 새 블루프린트를 추가하면 돼요
#   예: from seeding import seeding_bp / app.register_blueprint(seeding_bp)
# ---------------------------------------------------------------------------

@app.route("/seeding")
@login_required
def seeding():
    return render_template("coming_soon.html", title="시딩 업무 가이드")


@app.route("/gonggu")
@login_required
def gonggu():
    return render_template("coming_soon.html", title="공구 업무 가이드")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
