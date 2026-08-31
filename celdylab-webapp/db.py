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
