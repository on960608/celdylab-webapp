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
-- 매출 기회 발굴 대시보드 — 자사 제품 속성 (자동매칭용)
-- 제품 "이름"만 있는 archive_links와 별개로, 매칭에 필요한 속성을 여기에 채워요.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_profiles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  brand TEXT NOT NULL,
  product TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT '',       -- 제품 카테고리 (리빙/청소/살림/욕실/주방/세탁/수납/생활용품 등)
  usage_desc TEXT NOT NULL DEFAULT '',     -- 용도
  problem_solved TEXT NOT NULL DEFAULT '', -- 해결하는 문제
  consumer_need TEXT NOT NULL DEFAULT '',  -- 소비자 니즈
  updated_by TEXT,
  updated_at TEXT NOT NULL,
  UNIQUE(brand, product)
);

CREATE TABLE IF NOT EXISTS product_keywords (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  product_profile_id INTEGER NOT NULL REFERENCES product_profiles(id) ON DELETE CASCADE,
  keyword TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- 트렌드 상품군(키워드 그룹) 사전
-- 예: "텀블러 세정제" 그룹 = {"텀블러 세척", "텀블러 세정제", "텀블러 냄새 제거", ...}
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trend_keyword_groups (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT UNIQUE NOT NULL,
  category TEXT NOT NULL DEFAULT '',
  created_by TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trend_keyword_group_terms (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  group_id INTEGER NOT NULL REFERENCES trend_keyword_groups(id) ON DELETE CASCADE,
  term TEXT NOT NULL
);

-- 검색 트렌드 원본 — 소스별로 절대 섞지 않고 그대로 보존 (source: 'naver_search' | 'naver_shopping' | 'google')
CREATE TABLE IF NOT EXISTS trend_search_raw (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  group_id INTEGER NOT NULL REFERENCES trend_keyword_groups(id) ON DELETE CASCADE,
  collected_date TEXT NOT NULL,
  index_value REAL,
  raw_json TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

-- 월별 Trend Score 스냅샷 — 상품군별 순위 변화 추적용 누적 이력
CREATE TABLE IF NOT EXISTS monthly_trend_scores (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  year_month TEXT NOT NULL,
  group_id INTEGER NOT NULL REFERENCES trend_keyword_groups(id) ON DELETE CASCADE,
  score REAL,
  rank INTEGER,
  sources_used TEXT NOT NULL DEFAULT '',
  metrics_json TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE(year_month, group_id)
);

-- 상품군 ↔ 자사 제품 매칭 점수 (계산 캐시, 원본은 product_profiles/trend_keyword_groups)
CREATE TABLE IF NOT EXISTS product_group_matches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  group_id INTEGER NOT NULL REFERENCES trend_keyword_groups(id) ON DELETE CASCADE,
  product_profile_id INTEGER NOT NULL REFERENCES product_profiles(id) ON DELETE CASCADE,
  score REAL NOT NULL DEFAULT 0,
  matched_terms TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL,
  UNIQUE(group_id, product_profile_id)
);

-- 이번 달 시딩·공구 실행 후보로 등록한 자사 제품 (대시보드 [시딩 후보 등록]/[공구 후보 등록] 버튼)
CREATE TABLE IF NOT EXISTS execution_candidates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,                 -- 'seeding' | 'gongu'
  product_profile_id INTEGER NOT NULL REFERENCES product_profiles(id) ON DELETE CASCADE,
  group_id INTEGER REFERENCES trend_keyword_groups(id) ON DELETE SET NULL,
  reason TEXT NOT NULL DEFAULT '',    -- 등록 당시 추천 이유 스냅샷
  status TEXT NOT NULL DEFAULT '대기', -- 대기 / 진행중 / 완료 / 보류
  created_by TEXT,
  created_at TEXT NOT NULL
);

-- 상품기회점수 가중치 (트렌드/시딩성과/공구매출/자사적합도) — 단일 행, 화면에서 조정 가능
CREATE TABLE IF NOT EXISTS opportunity_weights (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  trend_weight REAL NOT NULL DEFAULT 40,
  seeding_weight REAL NOT NULL DEFAULT 25,
  gongu_weight REAL NOT NULL DEFAULT 25,
  fit_weight REAL NOT NULL DEFAULT 10,
  updated_by TEXT,
  updated_at TEXT NOT NULL
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
