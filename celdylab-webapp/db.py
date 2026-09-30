"""
아주 얇은 데이터 접근 레이어예요.
지금은 SQLite(파일 하나짜리 진짜 서버 DB)를 쓰지만, 나중에 Postgres로 옮길 때
이 파일만 바꾸면 되도록 함수 시그니처를 단순하게 유지했어요.
"""
import sqlite3
import os
from datetime import datetime, timezone

DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(os.path.dirname(__file__), "celdylab.db"))


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    with open(os.path.join(os.path.dirname(__file__), "schema.sql"), "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    _migrate(conn)
    conn.commit()
    conn.close()


def _migrate(conn):
    """
    CREATE TABLE IF NOT EXISTS는 이미 있는 테이블에 새 컬럼을 추가해주지 않아서,
    기존 배포에 새 컬럼이 필요할 때는 여기서 직접 ALTER TABLE로 보정해요.
    (이미 컬럼이 있으면 조용히 건너뜀 — 기존 데이터는 전혀 건드리지 않아요.)
    """
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(trend_records)").fetchall()}
    if "product_group_id" not in cols:
        # SQLite의 ALTER TABLE ADD COLUMN은 REFERENCES 절 제약이 까다로워서 일반 컬럼으로 추가하고,
        # 무결성은 애플리케이션 코드(db.py)에서 관리해요.
        conn.execute("ALTER TABLE trend_records ADD COLUMN product_group_id INTEGER")

    group_cols = {row["name"] for row in conn.execute("PRAGMA table_info(trend_keyword_groups)").fetchall()}
    if "shopping_category" not in group_cols:
        # 네이버 쇼핑인사이트 API 호출에 필요한 카테고리 코드(예: "50000006"). 선택 항목이라 비워둘 수 있어요.
        conn.execute("ALTER TABLE trend_keyword_groups ADD COLUMN shopping_category TEXT DEFAULT ''")

    # 작업지시서 03: 외부몰 자동수집이 인스타 계정·팔로워·브랜드까지 받을 수 있도록 칸 추가
    # (기존에 쌓여있던 기록은 그대로 두고 새 칸만 빈 값으로 추가돼요)
    if "insta_handle" not in cols:
        conn.execute("ALTER TABLE trend_records ADD COLUMN insta_handle TEXT DEFAULT ''")
    if "followers" not in cols:
        conn.execute("ALTER TABLE trend_records ADD COLUMN followers INTEGER DEFAULT 0")
    if "brand" not in cols:
        conn.execute("ALTER TABLE trend_records ADD COLUMN brand TEXT DEFAULT ''")

    # 상품기회점수 가중치는 항상 정확히 한 행(id=1)이 있어야 화면에서 바로 읽고 조정할 수 있어요.
    conn.execute(
        "INSERT OR IGNORE INTO opportunity_weights (id, trend_weight, seeding_weight, gongu_weight, fit_weight, updated_at) "
        "VALUES (1, 40, 25, 25, 10, ?)",
        (now_iso(),),
    )

    # 코드니처 세정서버 제품 옵션 — 구글드라이브 정산서 9건에서 확인한 값 (2026-09-28, 지인 확인 완료).
    # "변기/하수구" 콤보 옵션은 세정서버세트, "하수구" 단독 옵션은 하수구세정서버로 분류했어요.
    # "변기" 단독 옵션은 DB에 아직 없던 제품이라 "변기세정서버"라는 이름으로 새로 만들었어요 —
    # 화면에서 확인하고 이름이 다르면 언제든 고칠 수 있어요. INSERT OR IGNORE라서 이미 있으면 안 건드려요.
    seed_options = [
        ("변기세정서버", "변기 1+1", 2, 14900),
        ("변기세정서버", "변기 2+1", 3, 21900),
        ("변기세정서버", "변기 3+2", 5, 33900),
        ("하수구세정서버", "하수구 1개", 1, 17900),
        ("하수구세정서버", "하수구 2개", 2, 27900),
        ("하수구세정서버", "하수구 2+1", 3, 34800),
        ("하수구세정서버", "하수구 3+2", 5, 51700),
        ("세정서버세트", "변기/하수구 1+1", 2, 27900),
        ("세정서버세트", "변기/하수구 2+2", 4, 37900),
        ("세정서버세트", "변기/하수구 3+2", 5, 40900),
    ]
    for product, option_name, pack_qty, price in seed_options:
        conn.execute(
            "INSERT OR IGNORE INTO product_options (product, option_name, pack_qty, price, created_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (product, option_name, pack_qty, price, "system", now_iso()),
        )


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------- employees ----------

def get_employee_by_username(username):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM employees WHERE username = ?", (username,)
    ).fetchone()
    conn.close()
    return row


def get_employee_by_id(emp_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM employees WHERE id = ?", (emp_id,)).fetchone()
    conn.close()
    return row


def create_employee(username, password_hash, name):
    conn = get_conn()
    conn.execute(
        "INSERT INTO employees (username, password_hash, name, created_at) VALUES (?, ?, ?, ?)",
        (username, password_hash, name, now_iso()),
    )
    conn.commit()
    conn.close()


def list_employees():
    conn = get_conn()
    rows = conn.execute("SELECT id, username, name, created_at FROM employees ORDER BY id").fetchall()
    conn.close()
    return rows


def delete_employee(emp_id):
    conn = get_conn()
    conn.execute("DELETE FROM employees WHERE id = ?", (emp_id,))
    conn.commit()
    conn.close()


# ---------- archive links ----------

def list_archive_links():
    """brand -> {"brand_url": str, "products": [{"name","url","updated_by","updated_at"}]}"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM archive_links ORDER BY brand, (product = '') DESC, product"
    ).fetchall()
    conn.close()
    result = {}
    for r in rows:
        b = result.setdefault(r["brand"], {"brand_url": "", "brand_updated_by": None, "products": []})
        if r["product"] == "":
            b["brand_url"] = r["url"]
            b["brand_updated_by"] = r["updated_by"]
        else:
            b["products"].append(
                {"name": r["product"], "url": r["url"], "updated_by": r["updated_by"], "updated_at": r["updated_at"]}
            )
    return result


def upsert_archive_link(brand, product, url, updated_by):
    """product='' 이면 브랜드 폴더 전체 링크를 뜻해요."""
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO archive_links (brand, product, url, updated_by, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(brand, product) DO UPDATE SET
            url = excluded.url,
            updated_by = excluded.updated_by,
            updated_at = excluded.updated_at
        """,
        (brand, product, url, updated_by, now_iso()),
    )
    conn.commit()
    conn.close()


# ---------- 시딩 인사이트 ----------

def list_insight_records(brand=None, product=None):
    conn = get_conn()
    q = "SELECT * FROM insight_records"
    conds, params = [], []
    if brand:
        conds.append("brand = ?"); params.append(brand)
    if product:
        conds.append("product = ?"); params.append(product)
    if conds:
        q += " WHERE " + " AND ".join(conds)
    q += " ORDER BY id DESC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return rows


def list_insight_products(brand=None):
    conn = get_conn()
    if brand:
        rows = conn.execute(
            "SELECT DISTINCT product FROM insight_records WHERE brand = ? AND product != '' ORDER BY product", (brand,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT DISTINCT product FROM insight_records WHERE product != '' ORDER BY product").fetchall()
    conn.close()
    return [r["product"] for r in rows]


def create_insight_record(data, created_by):
    conn = get_conn()
    conn.execute(
        """INSERT INTO insight_records
           (brand, product, seller, followers, link, views, likes, comments, saves, shares, features, created_by, created_at)
           VALUES (:brand, :product, :seller, :followers, :link, :views, :likes, :comments, :saves, :shares, :features, :created_by, :created_at)""",
        {**data, "created_by": created_by, "created_at": now_iso()},
    )
    conn.commit()
    conn.close()


def delete_insight_record(record_id):
    conn = get_conn()
    conn.execute("DELETE FROM insight_records WHERE id = ?", (record_id,))
    conn.commit()
    conn.close()


def clear_insight_records():
    conn = get_conn()
    conn.execute("DELETE FROM insight_records")
    conn.commit()
    conn.close()


def list_insight_categories():
    conn = get_conn()
    cats = conn.execute("SELECT * FROM insight_categories ORDER BY name").fetchall()
    result = []
    for c in cats:
        folders = conn.execute(
            "SELECT * FROM insight_folders WHERE category_id = ? ORDER BY id", (c["id"],)
        ).fetchall()
        result.append({"id": c["id"], "name": c["name"], "folders": folders})
    conn.close()
    return result


def create_insight_category(name):
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO insight_categories (name, created_at) VALUES (?, ?)", (name, now_iso()))
    conn.commit()
    conn.close()


def delete_insight_category(category_id):
    conn = get_conn()
    conn.execute("DELETE FROM insight_categories WHERE id = ?", (category_id,))
    conn.commit()
    conn.close()


def add_insight_folder(category_id, label, url):
    conn = get_conn()
    conn.execute(
        "INSERT INTO insight_folders (category_id, label, url, created_at) VALUES (?, ?, ?, ?)",
        (category_id, label, url, now_iso()),
    )
    conn.commit()
    conn.close()


def delete_insight_folder(folder_id):
    conn = get_conn()
    conn.execute("DELETE FROM insight_folders WHERE id = ?", (folder_id,))
    conn.commit()
    conn.close()


# ---------- 공구 성과 ----------

def list_gongu_records(brand=None, month=None):
    conn = get_conn()
    q = "SELECT * FROM gongu_records"
    conds, params = [], []
    if brand:
        conds.append("brand = ?"); params.append(brand)
    if month:
        conds.append("substr(month, 6, 2) = ?"); params.append(month)
    if conds:
        q += " WHERE " + " AND ".join(conds)
    q += " ORDER BY month DESC, id DESC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return rows


def create_gongu_record(data, created_by):
    conn = get_conn()
    conn.execute(
        """INSERT INTO gongu_records
           (month, channel, brand, product, seller, followers, link, revenue, sold_qty, return_qty, created_by, created_at)
           VALUES (:month, :channel, :brand, :product, :seller, :followers, :link, :revenue, :sold_qty, :return_qty, :created_by, :created_at)""",
        {**data, "created_by": created_by, "created_at": now_iso()},
    )
    conn.commit()
    conn.close()


def delete_gongu_record(record_id):
    conn = get_conn()
    conn.execute("DELETE FROM gongu_records WHERE id = ?", (record_id,))
    conn.commit()
    conn.close()


def update_gongu_record(record_id, data):
    conn = get_conn()
    conn.execute(
        """UPDATE gongu_records SET
            month=:month, channel=:channel, brand=:brand, product=:product, seller=:seller,
            followers=:followers, link=:link, revenue=:revenue, sold_qty=:sold_qty, return_qty=:return_qty
        WHERE id=:id""",
        {**data, "id": record_id},
    )
    conn.commit()
    conn.close()


def clear_gongu_records():
    conn = get_conn()
    conn.execute("DELETE FROM gongu_records")
    conn.commit()
    conn.close()


# ---------- 공구 옵션 (작업지시서 01의 2단계: 제품 옵션 / 옵션 별칭 / 공구별 옵션 판매) ----------

def _normalize(text):
    """띄어쓰기 차이를 없앤다. gongu_forecast.normalize와 같은 규칙."""
    return "".join(str(text or "").split())


def list_product_options(product=None):
    conn = get_conn()
    if product:
        rows = conn.execute(
            "SELECT * FROM product_options WHERE product = ? ORDER BY id", (product,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM product_options ORDER BY product, id").fetchall()
    conn.close()
    return rows


def upsert_product_option(product, option_name, pack_qty, price, created_by):
    """같은 제품+옵션명이면 구성 수량/판매가를 덮어쓰고, 없으면 새로 만든다."""
    conn = get_conn()
    conn.execute(
        """INSERT INTO product_options (product, option_name, pack_qty, price, created_by, created_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(product, option_name) DO UPDATE SET
             pack_qty=excluded.pack_qty, price=excluded.price""",
        (product, option_name, pack_qty, price, created_by, now_iso()),
    )
    conn.commit()
    conn.close()


def delete_product_option(option_id):
    conn = get_conn()
    conn.execute("DELETE FROM product_options WHERE id = ?", (option_id,))
    conn.commit()
    conn.close()


def find_product_option(option_name):
    """표준 옵션명으로 제품 옵션(구성 수량/판매가) 하나를 찾는다 (제품 구분 없이 전체에서). 없으면 None."""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM product_options WHERE option_name = ?", (option_name,)
    ).fetchone()
    conn.close()
    return row


def find_option_alias(raw_text):
    """이미 연결해둔 표준 옵션명을 찾는다 (제품 구분 없이 전체에서). 없으면 None.

    한 공구 회차 정산서에 변기/하수구/세트 옵션이 섞여 나오는 경우가 있어서
    raw_text 하나로만 찾는다 (product로 좁히지 않음).
    """
    conn = get_conn()
    target = _normalize(raw_text)
    rows = conn.execute("SELECT raw_text, option_name FROM option_aliases").fetchall()
    conn.close()
    for row in rows:
        if _normalize(row["raw_text"]) == target:
            return row["option_name"]
    return None


def create_option_alias(raw_text, option_name, product, created_by):
    conn = get_conn()
    conn.execute(
        """INSERT INTO option_aliases (product, raw_text, option_name, created_by, created_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(raw_text) DO UPDATE SET option_name=excluded.option_name, product=excluded.product""",
        (product, raw_text, option_name, created_by, now_iso()),
    )
    conn.commit()
    conn.close()


def list_option_aliases(product=None):
    conn = get_conn()
    if product:
        rows = conn.execute(
            "SELECT * FROM option_aliases WHERE product = ? ORDER BY id", (product,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM option_aliases ORDER BY product, id").fetchall()
    conn.close()
    return rows


def save_gongu_record_options(record_id, rows):
    """그 공구 기록의 옵션별 내역을 통째로 바꿔치기한다 (다시 올리면 이전 값은 지워짐).

    rows: [{"option_name": .., "qty": .., "revenue": .., "return_qty": ..}, ...]
    """
    conn = get_conn()
    conn.execute("DELETE FROM gongu_record_options WHERE record_id = ?", (record_id,))
    for r in rows:
        conn.execute(
            """INSERT INTO gongu_record_options (record_id, option_name, qty, revenue, return_qty, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (record_id, r["option_name"], r["qty"], r["revenue"], r.get("return_qty", 0), now_iso()),
        )
    conn.commit()
    conn.close()


def list_gongu_record_options(record_id):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM gongu_record_options WHERE record_id = ? ORDER BY qty DESC", (record_id,)
    ).fetchall()
    conn.close()
    return rows


def find_order_upload(record_id, fingerprint):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM gongu_order_uploads WHERE record_id = ? AND fingerprint = ?",
        (record_id, fingerprint),
    ).fetchone()
    conn.close()
    return row


def record_order_upload(record_id, filename, fingerprint, uploaded_by):
    conn = get_conn()
    conn.execute(
        """INSERT INTO gongu_order_uploads (record_id, filename, fingerprint, uploaded_by, uploaded_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(record_id, fingerprint) DO UPDATE SET uploaded_at=excluded.uploaded_at""",
        (record_id, filename, fingerprint, uploaded_by, now_iso()),
    )
    conn.commit()
    conn.close()


# ---------- 옵션 수량 계산기 (작업지시서 01의 3단계) ----------

def list_all_products():
    """자료실(archive_links)에 등록된 자사 제품 전체를 [{"brand","product"}]로 돌려준다.
    계산기의 "제품 선택" 목록에 쓴다."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT brand, product FROM archive_links WHERE product != '' ORDER BY brand, product"
    ).fetchall()
    conn.close()
    return [{"brand": r["brand"], "product": r["product"]} for r in rows]


def option_qty_by_product(product):
    """그 제품의 지금까지 쌓인 옵션별 판매 수량(반품 뺀 순수 판매)을 더한다.
    {"표준 옵션명": 순수량, ...}. 계산기에서 옵션 비중을 자동으로 채울 때 쓴다.
    기록이 없으면 빈 딕셔너리를 돌려준다. product 이름은 normalize()로 비교해서
    띄어쓰기가 달라도(예: "세정서버 세트" / "세정서버세트") 같은 제품으로 묶는다."""
    conn = get_conn()
    target = _normalize(product)
    rows = conn.execute(
        """SELECT gr.product AS product, gro.option_name AS option_name,
                  gro.qty AS qty, gro.return_qty AS return_qty
           FROM gongu_record_options gro
           JOIN gongu_records gr ON gr.id = gro.record_id"""
    ).fetchall()
    conn.close()
    result = {}
    for r in rows:
        if _normalize(r["product"]) != target:
            continue
        net = max(0, (r["qty"] or 0) - (r["return_qty"] or 0))
        result[r["option_name"]] = result.get(r["option_name"], 0) + net
    return result


# ---------- 협찬 인원 리스트업 / 컨택관리 ----------

def list_candidates():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM listup_candidates ORDER BY id DESC").fetchall()
    conn.close()
    return rows


def upsert_candidate(data):
    conn = get_conn()
    conn.execute(
        """INSERT INTO listup_candidates
           (name, link, followers, views1, views2, views3, likes, comments, shares, last_upload, has_real_comments, sponsored_low, reason, created_at)
           VALUES (:name, :link, :followers, :views1, :views2, :views3, :likes, :comments, :shares, :last_upload, :has_real_comments, :sponsored_low, :reason, :created_at)
           ON CONFLICT(name) DO UPDATE SET
             link=excluded.link, followers=excluded.followers, views1=excluded.views1, views2=excluded.views2, views3=excluded.views3,
             likes=excluded.likes, comments=excluded.comments, shares=excluded.shares, last_upload=excluded.last_upload,
             has_real_comments=excluded.has_real_comments, sponsored_low=excluded.sponsored_low, reason=excluded.reason""",
        {**data, "created_at": now_iso()},
    )
    conn.commit()
    conn.close()


def delete_candidate(candidate_id):
    conn = get_conn()
    conn.execute("DELETE FROM listup_candidates WHERE id = ?", (candidate_id,))
    conn.commit()
    conn.close()


def list_contacted(brand=None):
    conn = get_conn()
    if brand:
        rows = conn.execute("SELECT * FROM contacted_list WHERE brand = ? ORDER BY name", (brand,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM contacted_list ORDER BY name").fetchall()
    conn.close()
    return rows


def is_contacted(brand, name):
    conn = get_conn()
    row = conn.execute(
        "SELECT 1 FROM contacted_list WHERE brand = ? AND lower(name) = lower(?)", (brand, name)
    ).fetchone()
    conn.close()
    return row is not None


def add_contacted(brand, name):
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO contacted_list (brand, name, created_at) VALUES (?, ?, ?)", (brand, name, now_iso())
    )
    conn.commit()
    conn.close()


def delete_contacted(contact_id):
    conn = get_conn()
    conn.execute("DELETE FROM contacted_list WHERE id = ?", (contact_id,))
    conn.commit()
    conn.close()


# ---------- 외부몰 트렌드 분석 ----------

def list_trend_records():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM trend_records ORDER BY check_date DESC, id DESC").fetchall()
    conn.close()
    return rows


def create_trend_record(data, created_by):
    conn = get_conn()
    conn.execute(
        """INSERT INTO trend_records
           (check_date, platform, seller, product, category, price, link, product_group_id,
            insta_handle, followers, brand, created_by, created_at)
           VALUES (:check_date, :platform, :seller, :product, :category, :price, :link, :product_group_id,
                   :insta_handle, :followers, :brand, :created_by, :created_at)""",
        {"product_group_id": None, "insta_handle": "", "followers": 0, "brand": "",
         **data, "created_by": created_by, "created_at": now_iso()},
    )
    conn.commit()
    conn.close()


def _iso_week_range(check_date_str):
    """check_date("YYYY-MM-DD")가 속한 주(월~일)의 시작/끝 날짜를 ("YYYY-MM-DD", "YYYY-MM-DD")로 돌려줘요.
    날짜 형식이 이상하면 (None, None)을 돌려줘서 호출 쪽이 "이번 주 판정 불가"로 처리하게 해요."""
    try:
        d = datetime.strptime(check_date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None, None
    from datetime import timedelta
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)
    return monday.isoformat(), sunday.isoformat()


def upsert_trend_record(data, created_by):
    """자동 수집(Cowork 예약작업 등)이 보낸 기록을 저장해요.
    같은 주(월~일)에 같은 플랫폼·셀러·제품이 이미 있으면 새로 만들지 않고 그 행을 갱신하고,
    없으면 새로 만들어요. 기존 기록(수동 입력분 포함)은 이 함수가 지우지 않아요.
    반환값: (created_bool, record_id)"""
    week_start, week_end = _iso_week_range(str(data.get("check_date", "")).strip())
    conn = get_conn()
    existing = None
    if week_start:
        existing = conn.execute(
            """SELECT id FROM trend_records
               WHERE platform = :platform AND seller = :seller AND product = :product
                 AND check_date >= :week_start AND check_date <= :week_end
               ORDER BY id DESC LIMIT 1""",
            {"platform": data.get("platform", ""), "seller": data.get("seller", ""),
             "product": data.get("product", ""), "week_start": week_start, "week_end": week_end},
        ).fetchone()

    payload = {
        "product_group_id": None, "insta_handle": "", "followers": 0, "brand": "",
        **data, "created_by": created_by, "created_at": now_iso(),
    }

    if existing:
        payload["id"] = existing["id"]
        conn.execute(
            """UPDATE trend_records SET
                 check_date=:check_date, category=:category, price=:price, link=:link,
                 insta_handle=:insta_handle, followers=:followers, brand=:brand,
                 created_by=:created_by, created_at=:created_at
               WHERE id=:id""",
            payload,
        )
        conn.commit()
        conn.close()
        return False, existing["id"]

    cur = conn.execute(
        """INSERT INTO trend_records
           (check_date, platform, seller, product, category, price, link, product_group_id,
            insta_handle, followers, brand, created_by, created_at)
           VALUES (:check_date, :platform, :seller, :product, :category, :price, :link, :product_group_id,
                   :insta_handle, :followers, :brand, :created_by, :created_at)""",
        payload,
    )
    conn.commit()
    new_id = cur.lastrowid
    conn.close()
    return True, new_id


def delete_trend_record(record_id):
    conn = get_conn()
    conn.execute("DELETE FROM trend_records WHERE id = ?", (record_id,))
    conn.commit()
    conn.close()


def clear_trend_records():
    conn = get_conn()
    conn.execute("DELETE FROM trend_records")
    conn.commit()
    conn.close()


# ---------- 플랫폼별 인기셀러 TOP20 (외부몰 트렌드 분석 ①) ----------

def list_platform_sellers(platform=None):
    conn = get_conn()
    if platform:
        rows = conn.execute(
            "SELECT * FROM trend_platform_sellers WHERE platform = ? ORDER BY id ASC", (platform,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM trend_platform_sellers ORDER BY id ASC").fetchall()
    conn.close()
    return rows


def count_platform_sellers(platform):
    conn = get_conn()
    n = conn.execute(
        "SELECT COUNT(*) AS n FROM trend_platform_sellers WHERE platform = ?", (platform,)
    ).fetchone()["n"]
    conn.close()
    return n


def create_platform_seller(data, created_by):
    conn = get_conn()
    conn.execute(
        """INSERT INTO trend_platform_sellers
           (platform, seller, brand, product, frequency_note, link, check_date, created_by, created_at)
           VALUES (:platform, :seller, :brand, :product, :frequency_note, :link, :check_date, :created_by, :created_at)""",
        {**data, "created_by": created_by, "created_at": now_iso()},
    )
    conn.commit()
    conn.close()


def delete_platform_seller(seller_id):
    conn = get_conn()
    conn.execute("DELETE FROM trend_platform_sellers WHERE id = ?", (seller_id,))
    conn.commit()
    conn.close()


def replace_platform_sellers(platform, rows, created_by):
    """자동 수집(Cowork 예약작업)이 한 플랫폼의 인기셀러 20명을 통째로 교체할 때 써요.
    기존 그 플랫폼 행을 전부 지우고 새 목록으로 다시 채워요(다른 플랫폼은 건드리지 않음).
    최대 20명까지만 저장하고, 나머지는 조용히 잘라내요."""
    conn = get_conn()
    conn.execute("DELETE FROM trend_platform_sellers WHERE platform = ?", (platform,))
    created_at = now_iso()
    for r in rows[:20]:
        conn.execute(
            """INSERT INTO trend_platform_sellers
               (platform, seller, brand, product, frequency_note, link, check_date, created_by, created_at)
               VALUES (:platform, :seller, :brand, :product, :frequency_note, :link, :check_date, :created_by, :created_at)""",
            {
                "platform": platform,
                "seller": (r.get("seller") or "").strip(),
                "brand": (r.get("brand") or "").strip(),
                "product": (r.get("product") or "").strip(),
                "frequency_note": (r.get("frequency_note") or "").strip(),
                "link": (r.get("link") or "").strip(),
                "check_date": (r.get("check_date") or "").strip(),
                "created_by": created_by,
                "created_at": created_at,
            },
        )
    conn.commit()
    conn.close()


def merge_platform_seller(platform, data, created_by):
    """작업지시서 03: /api/records로 들어온 자동수집 데이터를 "① 플랫폼별 인기셀러" 명단에도 반영해요.
    replace_platform_sellers처럼 통째로 지우고 새로 채우지 않고, 셀러 단위로 병합해요:
    - 이미 그 플랫폼에 같은 셀러가 있으면: 새로 들어온 값 중 비어있지 않은 것만 채워 넣어요
      (기존에 있던 값은 새 값이 빈칸이면 그대로 두고, 빈칸("제품 정보 없음")이었던 곳만 채워요).
    - 없으면: 그 플랫폼이 아직 20명 미만일 때만 새로 추가해요(20명이면 자동으로는 추가하지 않음).
    반환값: "updated" | "created" | "skipped_full" """
    seller = (data.get("seller") or "").strip()
    if not seller:
        return "skipped_full"

    conn = get_conn()
    existing = conn.execute(
        "SELECT * FROM trend_platform_sellers WHERE platform = ? AND seller = ?",
        (platform, seller),
    ).fetchone()

    new_vals = {
        "brand": (data.get("brand") or "").strip(),
        "product": (data.get("product") or "").strip(),
        "frequency_note": (data.get("insta_handle") or "").strip(),
        "link": (data.get("link") or "").strip(),
        "check_date": (data.get("check_date") or "").strip(),
    }

    if existing:
        merged = {k: (new_vals[k] if new_vals[k] else existing[k]) for k in new_vals}
        conn.execute(
            """UPDATE trend_platform_sellers SET
                 brand=:brand, product=:product, frequency_note=:frequency_note,
                 link=:link, check_date=:check_date
               WHERE id=:id""",
            {**merged, "id": existing["id"]},
        )
        conn.commit()
        conn.close()
        return "updated"

    count = conn.execute(
        "SELECT COUNT(*) AS n FROM trend_platform_sellers WHERE platform = ?", (platform,)
    ).fetchone()["n"]
    if count >= 20:
        conn.close()
        return "skipped_full"

    conn.execute(
        """INSERT INTO trend_platform_sellers
           (platform, seller, brand, product, frequency_note, link, check_date, created_by, created_at)
           VALUES (:platform, :seller, :brand, :product, :frequency_note, :link, :check_date, :created_by, :created_at)""",
        {"platform": platform, "seller": seller, **new_vals, "created_by": created_by, "created_at": now_iso()},
    )
    conn.commit()
    conn.close()
    return "created"


# ---------- 댓글 이벤트 추첨 ----------

def create_giveaway_event(data, winners, created_by):
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO giveaway_events
           (post_url, event_type, keyword, excluded_accounts, winner_count, total_comments,
            matched_accounts, final_pool_count, source, related_brand, related_note, created_by, created_at)
           VALUES (:post_url, :event_type, :keyword, :excluded_accounts, :winner_count, :total_comments,
                   :matched_accounts, :final_pool_count, :source, :related_brand, :related_note, :created_by, :created_at)""",
        {**data, "created_by": created_by, "created_at": now_iso()},
    )
    event_id = cur.lastrowid
    for w in winners:
        conn.execute(
            "INSERT INTO giveaway_winners (event_id, rank, username, comment_text, keyword_matched) VALUES (?, ?, ?, ?, ?)",
            (event_id, w["rank"], w["username"], w["comment"], w["keyword_matched"]),
        )
    conn.commit()
    conn.close()
    return event_id


def list_giveaway_events():
    conn = get_conn()
    events = conn.execute("SELECT * FROM giveaway_events ORDER BY id DESC").fetchall()
    result = []
    for e in events:
        winners = conn.execute(
            "SELECT * FROM giveaway_winners WHERE event_id = ? ORDER BY rank", (e["id"],)
        ).fetchall()
        result.append({**dict(e), "winners": winners})
    conn.close()
    return result


def get_giveaway_event(event_id):
    conn = get_conn()
    e = conn.execute("SELECT * FROM giveaway_events WHERE id = ?", (event_id,)).fetchone()
    if not e:
        conn.close()
        return None
    winners = conn.execute(
        "SELECT * FROM giveaway_winners WHERE event_id = ? ORDER BY rank", (event_id,)
    ).fetchall()
    conn.close()
    return {**dict(e), "winners": winners}


def delete_giveaway_event(event_id):
    conn = get_conn()
    conn.execute("DELETE FROM giveaway_events WHERE id = ?", (event_id,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# 매출 기회 발굴 대시보드
# ---------------------------------------------------------------------------

# ---------- 자사 제품 속성(product_profiles / product_keywords) ----------

def get_or_create_product_profile(brand, product):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM product_profiles WHERE brand = ? AND product = ?", (brand, product)
    ).fetchone()
    if row:
        conn.close()
        return row
    conn.execute(
        "INSERT INTO product_profiles (brand, product, updated_at) VALUES (?, ?, ?)",
        (brand, product, now_iso()),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM product_profiles WHERE brand = ? AND product = ?", (brand, product)
    ).fetchone()
    conn.close()
    return row


def list_product_profiles():
    """자료실(archive_links)에 등록된 브랜드/제품 전체를, 있으면 product_profiles 속성과 합쳐서 반환.
    반환: [{"brand","product","profile_id","category","usage_desc","problem_solved","consumer_need","keywords":[...]}]"""
    conn = get_conn()
    archive_rows = conn.execute(
        "SELECT brand, product FROM archive_links WHERE product != '' ORDER BY brand, product"
    ).fetchall()
    profiles = {(r["brand"], r["product"]): dict(r) for r in conn.execute("SELECT * FROM product_profiles").fetchall()}
    keywords_by_profile = {}
    for r in conn.execute("SELECT * FROM product_keywords").fetchall():
        keywords_by_profile.setdefault(r["product_profile_id"], []).append(r["keyword"])
    conn.close()

    result = []
    for a in archive_rows:
        key = (a["brand"], a["product"])
        p = profiles.get(key)
        result.append({
            "brand": a["brand"],
            "product": a["product"],
            "profile_id": p["id"] if p else None,
            "category": p["category"] if p else "",
            "usage_desc": p["usage_desc"] if p else "",
            "problem_solved": p["problem_solved"] if p else "",
            "consumer_need": p["consumer_need"] if p else "",
            "keywords": keywords_by_profile.get(p["id"], []) if p else [],
            "is_filled": bool(p and (p["category"] or p["usage_desc"] or p["problem_solved"] or p["consumer_need"])),
        })
    return result


def list_product_profiles_full():
    """product_group_matches 계산 등에 쓰는, 속성이 채워진 product_profiles 원본 목록(키워드 포함)."""
    conn = get_conn()
    rows = [dict(r) for r in conn.execute("SELECT * FROM product_profiles").fetchall()]
    keywords_by_profile = {}
    for r in conn.execute("SELECT * FROM product_keywords").fetchall():
        keywords_by_profile.setdefault(r["product_profile_id"], []).append(r["keyword"])
    conn.close()
    for p in rows:
        p["keywords"] = keywords_by_profile.get(p["id"], [])
    return rows


def get_product_profile(profile_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM product_profiles WHERE id = ?", (profile_id,)).fetchone()
    conn.close()
    return row


def save_product_profile(brand, product, fields, keywords, updated_by):
    """fields: {"category","usage_desc","problem_solved","consumer_need"}. keywords: 문자열 리스트(중복/공백 제거는 호출측)."""
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO product_profiles (brand, product, category, usage_desc, problem_solved, consumer_need, updated_by, updated_at)
        VALUES (:brand, :product, :category, :usage_desc, :problem_solved, :consumer_need, :updated_by, :updated_at)
        ON CONFLICT(brand, product) DO UPDATE SET
            category=excluded.category, usage_desc=excluded.usage_desc,
            problem_solved=excluded.problem_solved, consumer_need=excluded.consumer_need,
            updated_by=excluded.updated_by, updated_at=excluded.updated_at
        """,
        {**fields, "brand": brand, "product": product, "updated_by": updated_by, "updated_at": now_iso()},
    )
    profile_id = conn.execute(
        "SELECT id FROM product_profiles WHERE brand = ? AND product = ?", (brand, product)
    ).fetchone()["id"]
    conn.execute("DELETE FROM product_keywords WHERE product_profile_id = ?", (profile_id,))
    for kw in keywords:
        conn.execute(
            "INSERT INTO product_keywords (product_profile_id, keyword) VALUES (?, ?)", (profile_id, kw)
        )
    conn.commit()
    conn.close()
    return profile_id


# ---------- 트렌드 상품군(키워드 그룹) ----------

def list_trend_groups():
    """[{"id","name","category","terms":[...]}]"""
    conn = get_conn()
    groups = conn.execute("SELECT * FROM trend_keyword_groups ORDER BY name").fetchall()
    terms_by_group = {}
    for r in conn.execute("SELECT * FROM trend_keyword_group_terms").fetchall():
        terms_by_group.setdefault(r["group_id"], []).append({"id": r["id"], "term": r["term"]})
    conn.close()
    return [
        {
            "id": g["id"], "name": g["name"], "category": g["category"],
            "shopping_category": g["shopping_category"] or "",
            "terms": terms_by_group.get(g["id"], []),
        }
        for g in groups
    ]


def get_trend_group(group_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM trend_keyword_groups WHERE id = ?", (group_id,)).fetchone()
    conn.close()
    return row


def create_trend_group(name, category, created_by):
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO trend_keyword_groups (name, category, created_by, created_at) VALUES (?, ?, ?, ?)",
        (name, category, created_by, now_iso()),
    )
    conn.commit()
    row = conn.execute("SELECT id FROM trend_keyword_groups WHERE name = ?", (name,)).fetchone()
    conn.close()
    return row["id"] if row else None


def delete_trend_group(group_id):
    conn = get_conn()
    conn.execute("DELETE FROM trend_keyword_groups WHERE id = ?", (group_id,))
    conn.commit()
    conn.close()


def set_trend_group_shopping_category(group_id, shopping_category):
    """이 상품군을 네이버 쇼핑인사이트 카테고리(코드)에 연결해요. 빈 문자열이면 연결 해제예요."""
    conn = get_conn()
    conn.execute(
        "UPDATE trend_keyword_groups SET shopping_category = ? WHERE id = ?",
        (shopping_category or "", group_id),
    )
    conn.commit()
    conn.close()


def add_trend_group_term(group_id, term):
    conn = get_conn()
    conn.execute("INSERT INTO trend_keyword_group_terms (group_id, term) VALUES (?, ?)", (group_id, term))
    conn.commit()
    conn.close()


def delete_trend_group_term(term_id):
    conn = get_conn()
    conn.execute("DELETE FROM trend_keyword_group_terms WHERE id = ?", (term_id,))
    conn.commit()
    conn.close()


def set_trend_record_group(record_id, group_id):
    conn = get_conn()
    conn.execute("UPDATE trend_records SET product_group_id = ? WHERE id = ?", (group_id, record_id))
    conn.commit()
    conn.close()


# ---------- 검색 트렌드 원본(trend_search_raw) ----------

def get_last_naver_collection_at():
    """네이버 검색어트렌드/쇼핑인사이트를 마지막으로 수집한 시각(ISO 문자열)을 돌려줘요. 한 번도 없으면 None.
    "오늘 이미 한 번 자동으로 가져왔는지" 판단할 때 써요 — 화면 열 때마다 네이버에 요청을 보내지 않기 위해서예요."""
    conn = get_conn()
    row = conn.execute(
        "SELECT MAX(created_at) AS last_at FROM trend_search_raw WHERE source IN ('naver_search', 'naver_shopping')"
    ).fetchone()
    conn.close()
    return row["last_at"] if row else None


def add_trend_search_raw(source, group_id, collected_date, index_value, raw_json=""):
    conn = get_conn()
    conn.execute(
        "INSERT INTO trend_search_raw (source, group_id, collected_date, index_value, raw_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (source, group_id, collected_date, index_value, raw_json, now_iso()),
    )
    conn.commit()
    conn.close()


def list_trend_search_raw(group_id=None, source=None):
    conn = get_conn()
    q = "SELECT * FROM trend_search_raw"
    conds, params = [], []
    if group_id:
        conds.append("group_id = ?"); params.append(group_id)
    if source:
        conds.append("source = ?"); params.append(source)
    if conds:
        q += " WHERE " + " AND ".join(conds)
    q += " ORDER BY collected_date"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return rows


# ---------- 네이버 인기검색어 TOP100 (작업지시서 02) ----------

def save_naver_ranks(collected_date, category_cid, category_name, gender, age, period_range, ranks):
    """그 날짜·분야·성별·연령 조합의 순위를 통째로 바꿔치기한다 (같은 날 다시 수집해도 중복되지 않도록).
    ranks: [{"rank": .., "keyword": ..}, ...]"""
    conn = get_conn()
    conn.execute(
        "DELETE FROM naver_rank_entries WHERE collected_date=? AND category_cid=? AND gender=? AND age=?",
        (collected_date, category_cid, gender, age),
    )
    created_at = now_iso()
    for r in ranks:
        conn.execute(
            """INSERT INTO naver_rank_entries
               (collected_date, category_cid, category_name, gender, age, period_range, rank, keyword, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (collected_date, category_cid, category_name, gender, age, period_range, r["rank"], r["keyword"], created_at),
        )
    conn.commit()
    conn.close()


def get_naver_ranks(category_cid, gender, age, collected_date):
    """그 날짜·분야·성별·연령 조합의 순위를 순위순으로 돌려준다. 없으면 빈 리스트."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT * FROM naver_rank_entries
           WHERE category_cid=? AND gender=? AND age=? AND collected_date=?
           ORDER BY rank""",
        (category_cid, gender, age, collected_date),
    ).fetchall()
    conn.close()
    return rows


def list_naver_rank_dates(category_cid, gender, age, limit=60):
    """그 분야·성별·연령 조합으로 수집에 성공한 날짜 목록을 최신순으로 돌려준다."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT DISTINCT collected_date FROM naver_rank_entries
           WHERE category_cid=? AND gender=? AND age=?
           ORDER BY collected_date DESC LIMIT ?""",
        (category_cid, gender, age, limit),
    ).fetchall()
    conn.close()
    return [r["collected_date"] for r in rows]


def log_naver_rank_collect(ok, message):
    conn = get_conn()
    conn.execute(
        "INSERT INTO naver_rank_collect_log (attempted_at, ok, message, created_at) VALUES (?, ?, ?, ?)",
        (now_iso(), 1 if ok else 0, message, now_iso()),
    )
    conn.commit()
    conn.close()


def get_last_naver_rank_log():
    conn = get_conn()
    row = conn.execute("SELECT * FROM naver_rank_collect_log ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return row


# ---------- 월별 Trend Score 스냅샷 ----------

def upsert_monthly_trend_score(year_month, group_id, score, rank, sources_used, metrics_json):
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO monthly_trend_scores (year_month, group_id, score, rank, sources_used, metrics_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(year_month, group_id) DO UPDATE SET
            score=excluded.score, rank=excluded.rank, sources_used=excluded.sources_used,
            metrics_json=excluded.metrics_json, created_at=excluded.created_at
        """,
        (year_month, group_id, score, rank, sources_used, metrics_json, now_iso()),
    )
    conn.commit()
    conn.close()


def get_monthly_trend_scores(year_month):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM monthly_trend_scores WHERE year_month = ? ORDER BY rank", (year_month,)
    ).fetchall()
    conn.close()
    return rows


def get_group_score_history(group_id, limit=12):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM monthly_trend_scores WHERE group_id = ? ORDER BY year_month DESC LIMIT ?",
        (group_id, limit),
    ).fetchall()
    conn.close()
    return rows


# ---------- 상품군 ↔ 자사 제품 매칭 캐시 ----------

def upsert_product_group_match(group_id, product_profile_id, score, matched_terms):
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO product_group_matches (group_id, product_profile_id, score, matched_terms, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(group_id, product_profile_id) DO UPDATE SET
            score=excluded.score, matched_terms=excluded.matched_terms, updated_at=excluded.updated_at
        """,
        (group_id, product_profile_id, score, matched_terms, now_iso()),
    )
    conn.commit()
    conn.close()


def list_product_group_matches(min_score=0):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM product_group_matches WHERE score >= ? ORDER BY score DESC", (min_score,)
    ).fetchall()
    conn.close()
    return rows


# ---------- 시딩·공구 실행 후보 ----------

def create_execution_candidate(kind, product_profile_id, group_id, reason, created_by):
    conn = get_conn()
    conn.execute(
        """INSERT INTO execution_candidates (kind, product_profile_id, group_id, reason, created_by, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (kind, product_profile_id, group_id, reason, created_by, now_iso()),
    )
    conn.commit()
    conn.close()


def list_execution_candidates(status=None):
    conn = get_conn()
    q = """SELECT ec.*, pp.brand AS brand, pp.product AS product
           FROM execution_candidates ec JOIN product_profiles pp ON pp.id = ec.product_profile_id"""
    params = []
    if status:
        q += " WHERE ec.status = ?"; params.append(status)
    q += " ORDER BY ec.id DESC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return rows


def update_execution_candidate_status(candidate_id, status):
    conn = get_conn()
    conn.execute("UPDATE execution_candidates SET status = ? WHERE id = ?", (status, candidate_id))
    conn.commit()
    conn.close()


# ---------- 상품기회점수 가중치 ----------

def get_opportunity_weights():
    conn = get_conn()
    row = conn.execute("SELECT * FROM opportunity_weights WHERE id = 1").fetchone()
    conn.close()
    return row


def save_opportunity_weights(trend_w, seeding_w, gongu_w, fit_w, updated_by):
    conn = get_conn()
    conn.execute(
        """UPDATE opportunity_weights SET
             trend_weight=?, seeding_weight=?, gongu_weight=?, fit_weight=?, updated_by=?, updated_at=?
           WHERE id = 1""",
        (trend_w, seeding_w, gongu_w, fit_w, updated_by, now_iso()),
    )
    conn.commit()
    conn.close()


# ---------- 스케줄링 (시딩·공동구매 팀 업무 캘린더) ----------

def _schedule_row_to_dict(row):
    d = dict(row)
    return d


def list_schedules_for_range(start_date, end_date):
    """start_date~end_date 기간과 겹치는 일정을 전부 가져와요(월간 캘린더가 화면에 그리는 만큼).
    담당자/참여자 이름까지 한 번에 붙여서 반환하니, 화면에서는 추가 조회 없이 필터링만 하면 돼요."""
    conn = get_conn()
    rows = conn.execute(
        """SELECT * FROM schedules
           WHERE start_date <= ? AND end_date >= ?
           ORDER BY start_date, start_time""",
        (end_date, start_date),
    ).fetchall()
    schedules = [_schedule_row_to_dict(r) for r in rows]
    ids = [s["id"] for s in schedules]
    assignees_by_schedule = {}
    if ids:
        placeholders = ",".join("?" * len(ids))
        for r in conn.execute(
            f"""SELECT sa.schedule_id, sa.role, e.id AS employee_id, e.name
                FROM schedule_assignees sa JOIN employees e ON e.id = sa.employee_id
                WHERE sa.schedule_id IN ({placeholders}) ORDER BY e.name""",
            ids,
        ).fetchall():
            assignees_by_schedule.setdefault(r["schedule_id"], []).append(
                {"employee_id": r["employee_id"], "name": r["name"], "role": r["role"]}
            )
    conn.close()
    for s in schedules:
        all_people = assignees_by_schedule.get(s["id"], [])
        s["assignees"] = [p for p in all_people if p["role"] == "assignee"]
        s["participants"] = [p for p in all_people if p["role"] == "participant"]
    return schedules


def get_schedule(schedule_id):
    """일정 1건 + 담당자/참여자/체크리스트/코멘트까지 한 번에 묶어서 반환해요."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,)).fetchone()
    if not row:
        conn.close()
        return None
    data = _schedule_row_to_dict(row)

    people = conn.execute(
        """SELECT sa.role, e.id AS employee_id, e.name
           FROM schedule_assignees sa JOIN employees e ON e.id = sa.employee_id
           WHERE sa.schedule_id = ? ORDER BY e.name""",
        (schedule_id,),
    ).fetchall()
    data["assignees"] = [{"employee_id": p["employee_id"], "name": p["name"]} for p in people if p["role"] == "assignee"]
    data["participants"] = [{"employee_id": p["employee_id"], "name": p["name"]} for p in people if p["role"] == "participant"]

    tasks = conn.execute(
        """SELECT t.*, e.name AS assignee_name
           FROM schedule_tasks t LEFT JOIN employees e ON e.id = t.assignee_id
           WHERE t.schedule_id = ? ORDER BY t.sort_order, t.id""",
        (schedule_id,),
    ).fetchall()
    data["tasks"] = [dict(t) for t in tasks]

    comments = conn.execute(
        """SELECT c.*, e.name AS employee_name
           FROM schedule_comments c JOIN employees e ON e.id = c.employee_id
           WHERE c.schedule_id = ? ORDER BY c.id""",
        (schedule_id,),
    ).fetchall()
    data["comments"] = [dict(c) for c in comments]

    if data.get("group_id"):
        g = conn.execute("SELECT id, name FROM trend_keyword_groups WHERE id = ?", (data["group_id"],)).fetchone()
        data["group"] = dict(g) if g else None
    else:
        data["group"] = None

    conn.close()
    return data


def create_schedule(fields, created_by):
    conn = get_conn()
    now = now_iso()
    cur = conn.execute(
        """INSERT INTO schedules
           (type, title, brand, product, description, start_date, end_date, start_time, end_time,
            status, priority, group_id, memo, created_by, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            fields["type"], fields["title"], fields["brand"], fields["product"], fields["description"],
            fields["start_date"], fields["end_date"], fields["start_time"], fields["end_time"],
            fields["status"], fields["priority"], fields["group_id"], fields["memo"],
            created_by, now, now,
        ),
    )
    schedule_id = cur.lastrowid
    conn.commit()
    conn.close()
    return schedule_id


def update_schedule(schedule_id, fields):
    conn = get_conn()
    conn.execute(
        """UPDATE schedules SET
             type=?, title=?, brand=?, product=?, description=?, start_date=?, end_date=?,
             start_time=?, end_time=?, status=?, priority=?, group_id=?, memo=?, updated_at=?
           WHERE id = ?""",
        (
            fields["type"], fields["title"], fields["brand"], fields["product"], fields["description"],
            fields["start_date"], fields["end_date"], fields["start_time"], fields["end_time"],
            fields["status"], fields["priority"], fields["group_id"], fields["memo"], now_iso(),
            schedule_id,
        ),
    )
    conn.commit()
    conn.close()


def update_schedule_status(schedule_id, status):
    conn = get_conn()
    conn.execute("UPDATE schedules SET status = ?, updated_at = ? WHERE id = ?", (status, now_iso(), schedule_id))
    conn.commit()
    conn.close()


def delete_schedule(schedule_id):
    conn = get_conn()
    conn.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
    conn.commit()
    conn.close()


def set_schedule_assignees(schedule_id, assignee_ids, participant_ids):
    """담당자/참여자 목록을 통째로 교체해요(기존 걸 지우고 새로 넣는 방식이라 순서 걱정 없어요)."""
    conn = get_conn()
    conn.execute("DELETE FROM schedule_assignees WHERE schedule_id = ?", (schedule_id,))
    for emp_id in dict.fromkeys(assignee_ids or []):
        conn.execute(
            "INSERT OR IGNORE INTO schedule_assignees (schedule_id, employee_id, role) VALUES (?, ?, 'assignee')",
            (schedule_id, emp_id),
        )
    for emp_id in dict.fromkeys(participant_ids or []):
        if emp_id in (assignee_ids or []):
            continue
        conn.execute(
            "INSERT OR IGNORE INTO schedule_assignees (schedule_id, employee_id, role) VALUES (?, ?, 'participant')",
            (schedule_id, emp_id),
        )
    conn.commit()
    conn.close()


def add_schedule_task(schedule_id, title, assignee_id=None, due_date="", sort_order=0):
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO schedule_tasks (schedule_id, title, assignee_id, due_date, completed, sort_order, created_at)
           VALUES (?, ?, ?, ?, 0, ?, ?)""",
        (schedule_id, title, assignee_id, due_date, sort_order, now_iso()),
    )
    task_id = cur.lastrowid
    conn.commit()
    conn.close()
    return task_id


def toggle_schedule_task(task_id):
    conn = get_conn()
    row = conn.execute("SELECT completed FROM schedule_tasks WHERE id = ?", (task_id,)).fetchone()
    if row:
        conn.execute("UPDATE schedule_tasks SET completed = ? WHERE id = ?", (0 if row["completed"] else 1, task_id))
        conn.commit()
    conn.close()


def delete_schedule_task(task_id):
    conn = get_conn()
    conn.execute("DELETE FROM schedule_tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()


def get_schedule_task(task_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM schedule_tasks WHERE id = ?", (task_id,)).fetchone()
    conn.close()
    return row


def add_schedule_comment(schedule_id, employee_id, content):
    conn = get_conn()
    conn.execute(
        "INSERT INTO schedule_comments (schedule_id, employee_id, content, created_at) VALUES (?, ?, ?, ?)",
        (schedule_id, employee_id, content, now_iso()),
    )
    conn.commit()
    conn.close()


def list_today_tasks(today_str, employee_id=None):
    """'오늘 해야 할 업무' 위젯용 — 오늘이 마감일인 미완료 체크리스트 항목(담당자 필터 가능)."""
    conn = get_conn()
    q = """SELECT t.*, s.title AS schedule_title, s.type AS schedule_type, s.id AS schedule_id
           FROM schedule_tasks t JOIN schedules s ON s.id = t.schedule_id
           WHERE t.completed = 0 AND t.due_date = ?"""
    params = [today_str]
    if employee_id:
        q += " AND t.assignee_id = ?"
        params.append(employee_id)
    q += " ORDER BY s.priority = '긴급' DESC, s.priority = '중요' DESC, t.id"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]
