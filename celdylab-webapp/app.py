import os
import functools
from urllib.parse import quote
from flask import Flask, render_template, request, redirect, url_for, session, flash

from werkzeug.security import check_password_hash, generate_password_hash

import db

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")

# 앱이 켜질 때마다 DB 스키마를 최신 상태로 맞춰줘요 (CREATE TABLE IF NOT EXISTS라서 이미 있는
# 테이블/데이터는 건드리지 않고, 새로 추가된 테이블만 만들어져요 — 기존 배포에 새 기능을 추가할 때 필요해요).
_db_was_new = not os.path.exists(db.DB_PATH)
db.init_db()
# DB 파일 자체가 처음 생기는 경우(최초 배포)에만 기본 브랜드/제품과 데모 계정을 함께 채워줘요.
if _db_was_new:
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
# 직원 계정 관리 — 팀원이 직접 로그인 계정을 만들 수 있게 (CLI 없이 화면에서)
# ---------------------------------------------------------------------------

@app.route("/employees")
@login_required
def employees():
    return render_template("employees.html", employees=db.list_employees())


@app.route("/employees/add", methods=["POST"])
@login_required
def employees_add():
    username = request.form.get("username", "").strip()
    name = request.form.get("name", "").strip()
    pw1 = request.form.get("password", "")
    pw2 = request.form.get("password_confirm", "")

    if not username or not name:
        flash("아이디와 이름을 모두 입력해 주세요.")
    elif db.get_employee_by_username(username):
        flash(f"이미 '{username}' 아이디가 있어요.")
    elif pw1 != pw2:
        flash("비밀번호가 서로 달라요.")
    elif len(pw1) < 4:
        flash("비밀번호는 4자 이상으로 입력해 주세요.")
    else:
        db.create_employee(username, generate_password_hash(pw1), name)
        flash(f"'{name}'({username}) 계정을 만들었어요.")
    return redirect(url_for("employees"))


@app.route("/employees/<int:emp_id>/delete", methods=["POST"])
@login_required
def employees_delete(emp_id):
    if emp_id == session.get("user_id"):
        flash("지금 로그인 중인 본인 계정은 삭제할 수 없어요. 다른 계정으로 로그인해서 삭제해 주세요.")
        return redirect(url_for("employees"))
    if len(db.list_employees()) <= 1:
        flash("마지막 남은 계정은 삭제할 수 없어요 (로그인할 방법이 없어져요).")
        return redirect(url_for("employees"))
    db.delete_employee(emp_id)
    flash("계정을 삭제했어요.")
    return redirect(url_for("employees"))


# ---------------------------------------------------------------------------
# 시딩 인사이트 분석 / 공구 성과 분석 / 협찬 인원 리스트업 — 블루프린트로 등록
# ---------------------------------------------------------------------------
from insight import insight_bp
from gongu import gongu_bp
from listup import listup_bp
from trend import trend_bp
from giveaway import giveaway_bp
from igcomments import igcomments_bp

app.register_blueprint(insight_bp)
app.register_blueprint(gongu_bp)
app.register_blueprint(listup_bp)
app.register_blueprint(trend_bp)
app.register_blueprint(giveaway_bp)
app.register_blueprint(igcomments_bp)


# ---------------------------------------------------------------------------
# 시딩 / 공구 업무 가이드 — STEP 텍스트·스크린샷 (예전 오프라인 트래커에서 이식)
# ---------------------------------------------------------------------------

@app.route("/seeding")
@login_required
def seeding():
    return render_template("seeding.html")


@app.route("/gonggu")
@login_required
def gonggu():
    return render_template("gonggu_guide.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
