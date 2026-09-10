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

    # 상품기회점수 가중치는 항상 정확히 한 행(id=1)이 있어야 화면에서 바로 읽고 조정할 수 있어요.
    conn.execute(
        "INSERT OR IGNORE INTO opportunity_weights (id, trend_weight, seeding_weight, gongu_weight, fit_weight, updated_at) "
        "VALUES (1, 40, 25, 25, 10, ?)",
        (now_iso(),),
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


def clear_gongu_records():
    conn = get_conn()
    conn.execute("DELETE FROM gongu_records")
    conn.commit()
    conn.close()


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
        """INSERT INTO trend_records (check_date, platform, seller, product, category, price, link, product_group_id, created_by, created_at)
           VALUES (:check_date, :platform, :seller, :product, :category, :price, :link, :product_group_id, :created_by, :created_at)""",
        {"product_group_id": None, **data, "created_by": created_by, "created_at": now_iso()},
    )
    conn.commit()
    conn.close()


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
        {"id": g["id"], "name": g["name"], "category": g["category"], "terms": terms_by_group.get(g["id"], [])}
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
