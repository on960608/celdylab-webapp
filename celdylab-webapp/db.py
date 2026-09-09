"""
아주 얇은 데이터 접근 레이어예요.
지금은 SQLite(파일 하나짜리 진짜 서버 DB)를 쓰지만, 나중에 Postgres로 옮길 때
이 파일만 바꾸면 되도록 함수 시그니처를 단순하게 유지했어요.
"""
import sqlite3
import os
import uuid
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
    _migrate_marketplace_best_items_columns()
    _migrate_product_schedule_columns()
    _seed_product_schedule_if_empty()


def _migrate_marketplace_best_items_columns():
    """schema.sql은 CREATE TABLE IF NOT EXISTS라서 이미 만들어진 테이블에는 새 컬럼이
    안 생겨요 — 네이버 검색량 기능에 필요한 keyword/search_count 컬럼을 이미 배포된 DB에도
    안전하게(여러 번 실행돼도 괜찮게) 추가해줘요."""
    conn = get_conn()
    existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(marketplace_best_items)")}
    if "keyword" not in existing_cols:
        conn.execute("ALTER TABLE marketplace_best_items ADD COLUMN keyword TEXT")
    if "search_count" not in existing_cols:
        conn.execute("ALTER TABLE marketplace_best_items ADD COLUMN search_count INTEGER")
    conn.commit()
    conn.close()


def _migrate_product_schedule_columns():
    """schema.sql은 CREATE TABLE IF NOT EXISTS라서 이미 배포된 DB에는 새 컬럼이 안 생겨요 —
    "링크로 분석 추가" 기능에 필요한 pending_analysis 컬럼을 이미 배포된 DB에도 안전하게
    (여러 번 실행돼도 괜찮게) 추가해줘요."""
    conn = get_conn()
    existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(product_schedule)")}
    if "pending_analysis" not in existing_cols:
        conn.execute("ALTER TABLE product_schedule ADD COLUMN pending_analysis INTEGER NOT NULL DEFAULT 0")
    conn.commit()
    conn.close()


def _seed_product_schedule_if_empty():
    """새로 만들어진 '브랜드 제품 일정' 표에, "브랜드 런치 플래너"에서 실제로 분석을 마친
    항목 하나(하수구 악취 세정 서버 — 자료실의 '하수구 세정서버'와 동일 제품)만 예시로 채워둬요.
    그 문서의 나머지 항목은 전부 "(예시)" 표시가 붙은 참고용 가짜 데이터라 실제 DB에 넣지
    않았어요 — 진짜 일정은 이 표에서 직접 추가해 주세요. 표가 비어 있을 때만 1회 실행돼요."""
    if count_product_schedule() > 0:
        return
    now = now_iso()
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO product_schedule
            (brand, name, category, date, priority, link, selling, timing,
             group_buy_period, recommend_reason, sponsor_status, sponsor_note, note,
             created_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "코드니처", "하수구 악취 세정 서버", "출시", "", 1,
            "https://codenit.co.kr/product/detail.html?product_no=23",
            "싱크대 배수구에 던져 넣기만 하면 되는 간편 사용, 거품 세정+탈취 동시 해결, 리뷰 156건 대부분 5점 · 재구매율 높음, 오늘출발 배송 가능. 1세트/2+1세트/3+2세트(BEST) 구성, 판매가 19,900원(23% 할인)",
            "6월 ~ 8월 (초여름~한여름 순수 판매 추천)",
            "6월 3주차 ~ 7월 1주차 진행 추천",
            "하수구 악취는 고온다습한 환경에서 배수구 내 세균·유기물이 늘며 심해지는 계절성 문제라, 무더위가 시작되는 초여름부터 한여름(6~8월)에 관련 수요와 검색이 늘어나는 경향이 있어요 (일반 검색 결과 기반 추정치 — 정확한 월별 수치는 네이버 데이터랩 쇼핑인사이트에서 직접 확인 권장).",
            "none", "자사몰(codenit.co.kr) 판매 상품 — 협찬 정황 없음",
            "브랜드 런치 플래너에서 링크 분석 완료된 항목을 이어받음. 자료실의 '하수구 세정서버'와 동일 제품.",
            "seed", now, now,
        ),
    )
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


def update_employee_username(emp_id, new_username):
    conn = get_conn()
    conn.execute("UPDATE employees SET username = ? WHERE id = ?", (new_username, emp_id))
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


# ---------- 브랜드 제품 일정 (스케줄링 카테고리 포함) ----------

def list_product_schedule(brand=None, category=None):
    conn = get_conn()
    query = "SELECT * FROM product_schedule WHERE 1=1"
    params = []
    if brand:
        query += " AND brand = ?"
        params.append(brand)
    if category:
        query += " AND category = ?"
        params.append(category)
    query += " ORDER BY brand, (priority IS NULL), priority, (date = ''), date"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return rows


def list_product_schedule_categories():
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT category FROM product_schedule WHERE category != '' ORDER BY category"
    ).fetchall()
    conn.close()
    return [r["category"] for r in rows]


def get_product_schedule(item_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM product_schedule WHERE id = ?", (item_id,)).fetchone()
    conn.close()
    return row


def create_product_schedule(fields, created_by):
    conn = get_conn()
    now = now_iso()
    conn.execute(
        """
        INSERT INTO product_schedule
            (brand, name, category, date, priority, link, selling, timing,
             group_buy_period, recommend_reason, sponsor_status, sponsor_note, note,
             pending_analysis, created_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fields.get("brand", ""), fields.get("name", ""), fields.get("category", ""),
            fields.get("date", ""), fields.get("priority"), fields.get("link", ""),
            fields.get("selling", ""), fields.get("timing", ""), fields.get("group_buy_period", ""),
            fields.get("recommend_reason", ""), fields.get("sponsor_status", "none"),
            fields.get("sponsor_note", ""), fields.get("note", ""),
            fields.get("pending_analysis", 0),
            created_by, now, now,
        ),
    )
    conn.commit()
    conn.close()


def update_product_schedule(item_id, fields):
    conn = get_conn()
    conn.execute(
        """
        UPDATE product_schedule SET
            brand = ?, name = ?, category = ?, date = ?, priority = ?, link = ?,
            selling = ?, timing = ?, group_buy_period = ?, recommend_reason = ?,
            sponsor_status = ?, sponsor_note = ?, note = ?, pending_analysis = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            fields.get("brand", ""), fields.get("name", ""), fields.get("category", ""),
            fields.get("date", ""), fields.get("priority"), fields.get("link", ""),
            fields.get("selling", ""), fields.get("timing", ""), fields.get("group_buy_period", ""),
            fields.get("recommend_reason", ""), fields.get("sponsor_status", "none"),
            fields.get("sponsor_note", ""), fields.get("note", ""),
            fields.get("pending_analysis", 0),
            now_iso(), item_id,
        ),
    )
    conn.commit()
    conn.close()


def create_product_schedule_link_only(brand, link, created_by):
    """"링크로 분석 추가" 워크플로우 — 브랜드와 상세페이지 링크만 받아서 "분석 대기" 상태로
    표에 즉시 추가해요. 나머지 필드(소구점/판매 시기/추천 근거 등)는 비워두고, Claude가 분석을
    마친 뒤 수정 폼으로 채워 넣으면(그 시점에 pending_analysis는 0으로 풀려요) 완성돼요."""
    conn = get_conn()
    now = now_iso()
    cur = conn.execute(
        """
        INSERT INTO product_schedule
            (brand, name, category, date, priority, link, selling, timing,
             group_buy_period, recommend_reason, sponsor_status, sponsor_note, note,
             pending_analysis, created_by, created_at, updated_at)
        VALUES (?, ?, '', '', NULL, ?, '', '', '', '', 'none', '', '', 1, ?, ?, ?)
        """,
        (brand, "분석 대기 제품", link, created_by, now, now),
    )
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    return new_id


def swap_product_schedule_priority(item_id, direction):
    """같은 브랜드 안에서 우선순위를 바로 위/아래 항목과 맞바꿔요. direction: 'up' | 'down'.
    화면에 표시되는 정렬 기준(list_product_schedule과 동일)으로 순서를 계산하고, 우선순위 값이
    비어있는(NULL) 항목이 섞여 있으면 먼저 1부터 다시 번호를 매겨 순서를 확정한 뒤 맞바꿔요."""
    conn = get_conn()
    item = conn.execute("SELECT * FROM product_schedule WHERE id = ?", (item_id,)).fetchone()
    if not item:
        conn.close()
        return
    order_sql = (
        "SELECT * FROM product_schedule WHERE brand = ? "
        "ORDER BY (priority IS NULL), priority, (date = ''), date, id"
    )
    siblings = conn.execute(order_sql, (item["brand"],)).fetchall()
    ids = [r["id"] for r in siblings]
    idx = ids.index(item_id)
    swap_idx = idx - 1 if direction == "up" else idx + 1
    if swap_idx < 0 or swap_idx >= len(siblings):
        conn.close()
        return

    if any(r["priority"] is None for r in siblings):
        for pos, row in enumerate(siblings, start=1):
            conn.execute("UPDATE product_schedule SET priority = ? WHERE id = ?", (pos, row["id"]))
        conn.commit()
        siblings = conn.execute(order_sql, (item["brand"],)).fetchall()

    a_priority = siblings[idx]["priority"]
    b_priority = siblings[swap_idx]["priority"]
    other_id = siblings[swap_idx]["id"]
    now = now_iso()
    conn.execute("UPDATE product_schedule SET priority = ?, updated_at = ? WHERE id = ?", (b_priority, now, item_id))
    conn.execute("UPDATE product_schedule SET priority = ?, updated_at = ? WHERE id = ?", (a_priority, now, other_id))
    conn.commit()
    conn.close()


def delete_product_schedule(item_id):
    conn = get_conn()
    conn.execute("DELETE FROM product_schedule WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()


def count_product_schedule():
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) AS n FROM product_schedule").fetchone()["n"]
    conn.close()
    return n


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


def clear_auto_trend_records():
    """자동 수집(82market·지금하는공구·공구모아)으로 들어온 기록만 지워요.
    수동으로 '+ 등록'한 기록은 건드리지 않아요."""
    conn = get_conn()
    conn.execute("DELETE FROM trend_records WHERE created_by = 'auto-refresh'")
    conn.commit()
    conn.close()


def latest_auto_trend_refresh_at():
    """가장 최근 자동 수집이 언제 있었는지(created_at, UTC ISO 문자열) 돌려줘요.
    한 번도 없었으면 None이에요."""
    conn = get_conn()
    row = conn.execute(
        "SELECT MAX(created_at) AS latest FROM trend_records WHERE created_by = 'auto-refresh'"
    ).fetchone()
    conn.close()
    return row["latest"] if row else None


# ---------- 외부몰 트렌드 분석 — 이커머스 마켓플레이스 베스트셀러 ----------

def replace_marketplace_best_items(platform, category, items):
    """(platform, category) 조합의 기존 순위 데이터를 지우고, 지금 막 읽어온 순위로
    통째로 교체해요. items는 {rank, product, original_price, discount_pct, sale_price, link,
    keyword, search_count} 목록이에요(keyword/search_count는 네이버 전용이라 없으면 None)."""
    conn = get_conn()
    now = now_iso()
    conn.execute(
        "DELETE FROM marketplace_best_items WHERE platform = ? AND category = ?",
        (platform, category),
    )
    if items:
        conn.executemany(
            """INSERT INTO marketplace_best_items
               (platform, category, rank, product, original_price, discount_pct, sale_price, link,
                keyword, search_count, collected_at)
               VALUES (:platform, :category, :rank, :product, :original_price, :discount_pct, :sale_price, :link,
                       :keyword, :search_count, :collected_at)""",
            [
                {
                    "platform": platform,
                    "category": category,
                    "collected_at": now,
                    "rank": it.get("rank"),
                    "product": it.get("product", ""),
                    "original_price": it.get("original_price"),
                    "discount_pct": it.get("discount_pct"),
                    "sale_price": it.get("sale_price"),
                    "link": it.get("link", ""),
                    "keyword": it.get("keyword"),
                    "search_count": it.get("search_count"),
                }
                for it in items
            ],
        )
    conn.commit()
    conn.close()


def list_marketplace_best_items(category=None):
    conn = get_conn()
    if category:
        rows = conn.execute(
            "SELECT * FROM marketplace_best_items WHERE category = ? ORDER BY rank ASC", (category,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM marketplace_best_items ORDER BY category, rank ASC").fetchall()
    conn.close()
    return rows


def latest_marketplace_collected_at(platform=None):
    """가장 최근 마켓플레이스 베스트셀러 수집이 언제 있었는지(UTC ISO 문자열) 돌려줘요.
    platform을 주면 그 플랫폼만, 아니면 전체 중 가장 최근 값이에요. 한 번도 없었으면 None."""
    conn = get_conn()
    if platform:
        row = conn.execute(
            "SELECT MAX(collected_at) AS latest FROM marketplace_best_items WHERE platform = ?", (platform,)
        ).fetchone()
    else:
        row = conn.execute("SELECT MAX(collected_at) AS latest FROM marketplace_best_items").fetchone()
    conn.close()
    return row["latest"] if row else None


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
# 브랜드 런치 플래너 — 테스트 일정표 / 캘린더 전용 일정 / 네이버 트렌드 스냅샷
# (제품 우선순위 표는 product_schedule 테이블 함수들을 그대로 써요. 여긴 그 화면의
# 나머지 탭들만 담당해요)
# ---------------------------------------------------------------------------

def _new_id(prefix):
    return prefix + uuid.uuid4().hex[:12]


_SCHEDULE_TEST_FIELDS = ("brand", "product", "item", "date", "status", "assignee", "note")


def list_schedule_tests():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM schedule_tests ORDER BY date, id").fetchall()
    conn.close()
    return rows


def create_schedule_test(data):
    conn = get_conn()
    now = now_iso()
    new_id = _new_id("t")
    row = {k: data.get(k, "") for k in _SCHEDULE_TEST_FIELDS}
    conn.execute(
        """INSERT INTO schedule_tests (id, brand, product, item, date, status, assignee, note, created_at, updated_at)
           VALUES (:id, :brand, :product, :item, :date, :status, :assignee, :note, :created_at, :updated_at)""",
        {**row, "id": new_id, "created_at": now, "updated_at": now},
    )
    conn.commit()
    conn.close()
    return new_id


def delete_schedule_test(test_id):
    conn = get_conn()
    conn.execute("DELETE FROM schedule_tests WHERE id = ?", (test_id,))
    conn.commit()
    conn.close()


def list_schedule_events():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM schedule_events ORDER BY date, id").fetchall()
    conn.close()
    return rows


def create_schedule_event(data):
    conn = get_conn()
    new_id = _new_id("e")
    conn.execute(
        """INSERT INTO schedule_events (id, title, date, brand, note, created_at)
           VALUES (:id, :title, :date, :brand, :note, :created_at)""",
        {
            "id": new_id, "title": data.get("title", ""), "date": data.get("date", ""),
            "brand": data.get("brand", ""), "note": data.get("note", ""), "created_at": now_iso(),
        },
    )
    conn.commit()
    conn.close()
    return new_id


def delete_schedule_event(event_id):
    conn = get_conn()
    conn.execute("DELETE FROM schedule_events WHERE id = ?", (event_id,))
    conn.commit()
    conn.close()


def get_schedule_trend_snapshot():
    conn = get_conn()
    row = conn.execute("SELECT * FROM schedule_trend_snapshot WHERE id = 1").fetchone()
    conn.close()
    return row


def save_schedule_trend_snapshot(snapshot):
    """snapshot: {category, range_label, mobile_pct, desktop_pct, female_pct, male_pct,
    age_group, keywords(list[str]), series(list[{date,ratio}])} — naver_datalab.fetch_trend_snapshot()
    가 돌려주는 그대로 넣으면 돼요."""
    import json

    conn = get_conn()
    conn.execute(
        """INSERT INTO schedule_trend_snapshot
             (id, category, range_label, updated_at, mobile_pct, desktop_pct, female_pct, male_pct, age_group, keywords, series)
           VALUES (1, :category, :range_label, :updated_at, :mobile_pct, :desktop_pct, :female_pct, :male_pct, :age_group, :keywords, :series)
           ON CONFLICT(id) DO UPDATE SET
             category=excluded.category, range_label=excluded.range_label, updated_at=excluded.updated_at,
             mobile_pct=excluded.mobile_pct, desktop_pct=excluded.desktop_pct, female_pct=excluded.female_pct,
             male_pct=excluded.male_pct, age_group=excluded.age_group, keywords=excluded.keywords, series=excluded.series""",
        {
            "category": snapshot.get("category", ""),
            "range_label": snapshot.get("range_label", ""),
            "updated_at": now_iso()[:10].replace("-", "."),
            "mobile_pct": snapshot.get("mobile_pct"),
            "desktop_pct": snapshot.get("desktop_pct"),
            "female_pct": snapshot.get("female_pct"),
            "male_pct": snapshot.get("male_pct"),
            "age_group": snapshot.get("age_group", ""),
            "keywords": ", ".join(snapshot.get("keywords") or []),
            "series": json.dumps(snapshot.get("series") or [], ensure_ascii=False),
        },
    )
    conn.commit()
    conn.close()
