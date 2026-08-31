-- 직원 계정
CREATE TABLE IF NOT EXISTS employees (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL
);

-- 자료실 폴더 링크
-- product = '' (빈 문자열) 이면 "브랜드 폴더 전체" 링크를 뜻해요.
CREATE TABLE IF NOT EXISTS archive_links (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  brand TEXT NOT NULL,
  product TEXT NOT NULL DEFAULT '',
  url TEXT NOT NULL DEFAULT '',
  updated_by TEXT,
  updated_at TEXT NOT NULL,
  UNIQUE(brand, product)
);
