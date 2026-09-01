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

-- ---------------------------------------------------------------------------
-- 시딩 인사이트 분석
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS insight_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  brand TEXT NOT NULL DEFAULT '',
  product TEXT NOT NULL DEFAULT '',
  seller TEXT NOT NULL DEFAULT '',
  followers INTEGER NOT NULL DEFAULT 0,
  link TEXT NOT NULL DEFAULT '',
  views INTEGER NOT NULL DEFAULT 0,
  likes INTEGER NOT NULL DEFAULT 0,
  comments INTEGER NOT NULL DEFAULT 0,
  saves INTEGER NOT NULL DEFAULT 0,
  shares INTEGER NOT NULL DEFAULT 0,
  features TEXT NOT NULL DEFAULT '',
  created_by TEXT,
  created_at TEXT NOT NULL
);

-- 인사이트 캡처 폴더(제품별 카테고리 + 폴더 링크 모음)
CREATE TABLE IF NOT EXISTS insight_categories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT UNIQUE NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS insight_folders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  category_id INTEGER NOT NULL REFERENCES insight_categories(id) ON DELETE CASCADE,
  label TEXT NOT NULL,
  url TEXT NOT NULL,
  created_at TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- 공구 성과 분석
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gongu_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  month TEXT NOT NULL DEFAULT '',
  channel TEXT NOT NULL DEFAULT '',
  brand TEXT NOT NULL DEFAULT '',
  product TEXT NOT NULL DEFAULT '',
  seller TEXT NOT NULL DEFAULT '',
  followers INTEGER NOT NULL DEFAULT 0,
  link TEXT NOT NULL DEFAULT '',
  revenue INTEGER NOT NULL DEFAULT 0,
  sold_qty INTEGER NOT NULL DEFAULT 0,
  return_qty INTEGER NOT NULL DEFAULT 0,
  created_by TEXT,
  created_at TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- 협찬 인원 리스트업 / 컨택관리
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS listup_candidates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT UNIQUE NOT NULL,
  link TEXT NOT NULL DEFAULT '',
  followers INTEGER NOT NULL DEFAULT 0,
  views1 INTEGER NOT NULL DEFAULT 0,
  views2 INTEGER NOT NULL DEFAULT 0,
  views3 INTEGER NOT NULL DEFAULT 0,
  likes INTEGER NOT NULL DEFAULT 0,
  comments INTEGER NOT NULL DEFAULT 0,
  shares INTEGER NOT NULL DEFAULT 0,
  last_upload TEXT NOT NULL DEFAULT '',
  has_real_comments INTEGER NOT NULL DEFAULT 0,
  sponsored_low INTEGER NOT NULL DEFAULT 0,
  reason TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contacted_list (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  brand TEXT NOT NULL DEFAULT '',
  name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(brand, name)
);

-- ---------------------------------------------------------------------------
-- 외부몰 트렌드 분석 (인기 셀러 등록 + 자동 집계)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trend_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  check_date TEXT NOT NULL DEFAULT '',
  platform TEXT NOT NULL DEFAULT '',
  seller TEXT NOT NULL DEFAULT '',
  product TEXT NOT NULL DEFAULT '',
  category TEXT NOT NULL DEFAULT '',
  price INTEGER NOT NULL DEFAULT 0,
  link TEXT NOT NULL DEFAULT '',
  created_by TEXT,
  created_at TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- 댓글 이벤트 추첨
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS giveaway_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  post_url TEXT NOT NULL DEFAULT '',
  event_type TEXT NOT NULL DEFAULT '',        -- 'keyword' | 'general'
  keyword TEXT NOT NULL DEFAULT '',
  excluded_accounts TEXT NOT NULL DEFAULT '', -- 쉼표/줄바꿈 구분 원문 저장
  winner_count INTEGER NOT NULL DEFAULT 0,
  total_comments INTEGER NOT NULL DEFAULT 0,
  matched_accounts INTEGER NOT NULL DEFAULT 0,
  final_pool_count INTEGER NOT NULL DEFAULT 0,
  source TEXT NOT NULL DEFAULT '',            -- 'api' | 'manual'
  -- 앞으로 시딩/공구 진행 건과 연결할 때 쓰는 선택 필드 (지금은 자유 입력)
  related_brand TEXT NOT NULL DEFAULT '',
  related_note TEXT NOT NULL DEFAULT '',
  created_by TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS giveaway_winners (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id INTEGER NOT NULL REFERENCES giveaway_events(id) ON DELETE CASCADE,
  rank INTEGER NOT NULL,
  username TEXT NOT NULL,
  comment_text TEXT NOT NULL DEFAULT '',
  keyword_matched INTEGER  -- 1=포함 / 0=미포함 / NULL=일반 댓글 이벤트(해당없음)
);
