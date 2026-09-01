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
    conn.commit()
    conn.close()


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
        """INSERT INTO trend_records (check_date, platform, seller, product, category, price, link, created_by, created_at)
           VALUES (:check_date, :platform, :seller, :product, :category, :price, :link, :created_by, :created_at)""",
        {**data, "created_by": created_by, "created_at": now_iso()},
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
