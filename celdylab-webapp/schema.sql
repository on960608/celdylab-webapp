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
-- 외부몰 트렌드 분석 — 이커머스 마켓플레이스 베스트셀러 (G마켓 등, 카테고리별 순위 스냅샷)
-- 새로고침/자동 수집할 때마다 (platform, category) 조합의 기존 데이터를 지우고 그
-- 순간의 순위로 통째로 교체해요 — trend_records의 자동 수집분과 같은 방식이에요.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS marketplace_best_items (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  platform TEXT NOT NULL DEFAULT '',
  category TEXT NOT NULL DEFAULT '',
  rank INTEGER NOT NULL DEFAULT 0,
  product TEXT NOT NULL DEFAULT '',
  original_price INTEGER,
  discount_pct INTEGER,
  sale_price INTEGER,
  link TEXT NOT NULL DEFAULT '',
  keyword TEXT,        -- 네이버 전용: 검색량을 확인한 키워드
  search_count INTEGER, -- 네이버 전용: 월간 검색량(PC+모바일 합)
  collected_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_marketplace_best_items_category ON marketplace_best_items(category, rank);

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

-- ---------------------------------------------------------------------------
-- 브랜드 제품 일정 (브랜드 런치 플래너의 "제품 우선순위 표" — 브랜드별 우선순위로 관리)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_schedule (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  brand TEXT NOT NULL DEFAULT '',
  name TEXT NOT NULL DEFAULT '',
  category TEXT NOT NULL DEFAULT '',          -- (레거시) 예전 버전의 자유입력 카테고리 — 지금 화면에서는 안 쓰지만
                                               -- 이미 저장된 값을 지우지 않으려고 컬럼은 남겨둬요.
  date TEXT NOT NULL DEFAULT '',              -- 일정(오픈 예정일), YYYY-MM-DD
  priority INTEGER,                           -- 브랜드 내 우선순위 (숫자가 작을수록 우선)
  link TEXT NOT NULL DEFAULT '',
  selling TEXT NOT NULL DEFAULT '',           -- 소구점
  timing TEXT NOT NULL DEFAULT '',            -- 판매 시기 (추천 월)
  group_buy_period TEXT NOT NULL DEFAULT '',  -- 공구 진행 시기
  recommend_reason TEXT NOT NULL DEFAULT '',  -- 추천 근거
  sponsor_status TEXT NOT NULL DEFAULT 'none',-- none / sponsored / paid
  sponsor_note TEXT NOT NULL DEFAULT '',
  note TEXT NOT NULL DEFAULT '',
  pending_analysis INTEGER NOT NULL DEFAULT 0,-- "링크로 분석 추가"로 만들어져 아직 분석 전인 항목 (1=분석 대기)
  created_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- 브랜드 런치 플래너 — 테스트 일정표 / 캘린더 전용 일정 / 네이버 트렌드 스냅샷
-- (product_schedule과 같은 "브랜드 런치 플래너" 화면의 나머지 탭들이에요. id는 서버에서
-- 생성한 문자열 키(uuid4 hex)를 써요 — product_schedule의 AUTOINCREMENT 정수 id와는
-- 별개 체계지만, 두 방식 다 이 앱에서 이미 쓰이고 있어서(브랜드 런치 플래너 원본 프로토타입
-- 계열은 문자열 id, 나머지 대부분 표는 정수 id) 문제 없어요.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schedule_tests (
  id TEXT PRIMARY KEY,
  brand TEXT NOT NULL DEFAULT '',
  product TEXT NOT NULL DEFAULT '',
  item TEXT NOT NULL DEFAULT '',
  date TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',   -- pending / inprogress / done / hold
  assignee TEXT NOT NULL DEFAULT '',
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schedule_events (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL DEFAULT '',
  date TEXT NOT NULL DEFAULT '',
  brand TEXT NOT NULL DEFAULT '',   -- 비워두면 "전체" 일정
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

-- 네이버 데이터랩 트렌드 스냅샷 — 행 하나만 유지(항상 id=1). "⚡ 자동 새로고침" 버튼을 누를
-- 때마다 통째로 덮어써요. 처음엔 비어 있고(가짜 데이터를 심어두지 않음), 실제로 새로고침해야
-- 값이 채워져요.
CREATE TABLE IF NOT EXISTS schedule_trend_snapshot (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  category TEXT NOT NULL DEFAULT '',
  range_label TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL DEFAULT '',
  mobile_pct REAL,
  desktop_pct REAL,
  female_pct REAL,
  male_pct REAL,
  age_group TEXT NOT NULL DEFAULT '',
  keywords TEXT NOT NULL DEFAULT '',  -- 쉼표로 구분된 인기 검색어 목록
  series TEXT NOT NULL DEFAULT ''     -- JSON 배열 [{"date":"20260806","ratio":62.1}, ...]
);
