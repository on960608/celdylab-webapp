# 매출 기회 발굴 대시보드 — 구현 문서

셀디랩 콘텐츠팀 웹앱(`celdylab-webapp`)에 추가된 "매출 기회 발굴 대시보드" 기능 설명입니다.
외부 인플루언서 매니저 앱과는 무관하며, 이 저장소(`celdylab-webapp-v8/celdylab-webapp`) 안에서만
동작합니다.

## 목표 업무 흐름

```
외부 트렌드 발견 → 인기 상품/키워드 분석 → 자사 제품 매칭 → 시딩 후보 선정
→ 시딩 성과 확인 → 공구 후보 선정 → 공구 진행 → 실제 매출 확인
```

## 핵심 원칙

- **확보하지 못한 데이터를 임의의 숫자로 채우지 않는다.** 지표가 없으면 계산에서 빼고,
  화면에는 "몇 개 지표 중 몇 개로 계산됐는지"를 항상 함께 보여준다.
- 소스별(네이버/구글/공구 플랫폼) 원본 데이터를 절대 섞지 않고 그대로 보존한다.
- 자동매칭은 AI 임베딩이 아니라 **키워드 겹침 기반**이라, 왜 이 점수가 나왔는지 항상 설명 가능하다.

## 기존 기능과의 관계

기존 "외부몰 트렌드 분석"(`/trend`)은 담당자가 공구 플랫폼(캘린·82market 등)에서 확인한 셀러·상품을
수동/반자동(API 키 기반 Cowork 연동)으로 기록하는 화면이었다. 검색어 트렌드, 상품군 그룹핑,
자사 제품 매칭, Trend Score, 월별 이력 같은 기능은 전혀 없었다. 이번 작업은 그 위에:

- 상품군(비슷한 검색어 묶음) 개념을 추가하고,
- 자사 제품 속성(카테고리/용도/문제/니즈/키워드) 데이터를 신설하고,
- 위 둘을 연결해 Trend Score·자동매칭·추천·월별 이력·실행 후보 추적까지 이어지는
  대시보드를 새로 만든 것이다.

## 데이터 구조 (신규 테이블)

| 테이블 | 역할 |
|---|---|
| `product_profiles` / `product_keywords` | 자사 제품 카테고리·용도·해결 문제·니즈·연관 키워드 (자동 생성 안 됨, 수동 입력) |
| `trend_keyword_groups` / `trend_keyword_group_terms` | 상품군 사전. 예: "텀블러 세정제" = {텀블러 세척, 텀블러 세정제, 텀블러 냄새 제거, ...} |
| `trend_search_raw` | 검색 트렌드 원본. `source` 컬럼으로 `naver_search`/`naver_shopping`/`google`을 구분해 절대 섞지 않음 |
| `monthly_trend_scores` | 상품군별 월간 Trend Score·순위 스냅샷 (순위 변동 추적용 누적 이력) |
| `product_group_matches` | 상품군 ↔ 자사 제품 매칭 점수 캐시 |
| `execution_candidates` | 대시보드 [시딩 후보 등록]/[공구 후보 등록] 버튼으로 만들어지는 실행 후보 |
| `opportunity_weights` | 상품기회점수 가중치(트렌드/시딩성과/공구매출/적합도), 화면에서 조정 가능 |

기존 테이블(`gongu_records`, `insight_records`, `archive_links` 등)은 전혀 건드리지 않았고,
`trend_records`에는 `product_group_id` 컬럼만 `ALTER TABLE`로 추가했다(기존 데이터 보존).

## Trend Score 계산

```
Trend Score = Σ (확보된 지표 × 가중치) / Σ (확보된 지표의 가중치)
```

| 지표 | 가중치 | 비고 |
|---|---|---|
| 검색 관심도 (search_interest) | 35 | 네이버 우선, 없으면 구글 |
| 전월 대비 상승률 (mom_growth) | 25 | 최소 2개월치 데이터 필요 |
| 최근 상승 속도 (recent_velocity) | 15 | mom_growth 기반 |
| 플랫폼 동시 등장 (platform_overlap) | 15 | 공구 6개 플랫폼 중 몇 곳에서 확인됐는지 |
| 공구 노출 빈도 (groupbuy_exposure) | 10 | 최근 30일 등록 건수 |

없는 지표는 계산에서 제외하고 남은 지표의 가중치 비율로 재계산한다. 모든 지표가 없으면
점수 자체가 `None`이며, 화면에는 숫자 대신 "데이터 없음" 안내가 뜬다.

## 화면 구성

**메인 대시보드** (`/dashboard`, 로그인 후 첫 화면)

| 위젯 | 지금 바로 실데이터로 뜨는지 |
|---|---|
| ① 이번 달 트렌드 상품 TOP5 | ❌ 네이버/구글 연동 후 |
| ② 🔥 급상승 상품 | ❌ 최소 2개월치 검색 데이터 필요 |
| ③ 🎯 시딩·공구 추천 TOP5 | ✅ 자사 제품+상품군만 등록하면 적합도 기준으로 바로 작동 |
| ④ 공구 시장 노출 상품 | ✅ 상품군 태깅한 기록이 있으면 바로 |
| ⑤ 전월 대비 상승 카테고리 | ❌ 최소 2개월치 월별 스냅샷 필요 |
| ⑥ 진행 중인 시딩/공구 + 매출 | ✅ 즉시 (기존 실데이터 활용) |

각 위젯을 클릭하면 상세 페이지(`/dashboard/trend`, `/rising`, `/recommend`, `/groupbuy`,
`/categories`, `/progress`)로 이동한다. `/dashboard/settings`에서 네이버 연동 상태 확인,
구글 트렌드 수동 수집, 상품기회점수 가중치 조정을 할 수 있다.

**새로 추가된 관리 화면**

- `/products` — 자사 제품 정보(카테고리/용도/문제/니즈/키워드) 입력
- `/trend/groups` — 상품군(키워드 묶음) 관리
- `/trend` — 기존 화면에 상품군 태깅 열, 상품군별 공구 노출 요약 추가

## 변경/추가 파일

- `schema.sql`, `db.py` — 신규 테이블 + 마이그레이션(`trend_records.product_group_id`) + CRUD 함수
- `analysis.py` — 적합도/Trend Score/공구노출/구글트렌드/상품기회점수 계산 함수
- `products.py` (신규) — 자사 제품 정보 블루프린트
- `trend.py` — 상품군 관리 라우트, 태깅 라우트 추가
- `dashboard.py` (신규) — 대시보드 전체 라우트
- `templates/products.html`, `trend_groups.html`, `dashboard*.html` (신규 8개), `trend.html`·`base.html` (수정)
- `app.py` — 블루프린트 등록, 로그인 후 첫 화면을 `/dashboard`로 변경
- `requirements.txt` — `pytrends`(구글 트렌드 보조, 실패 시 자동 생략) 추가

## 남은 단계 (사용자 확인 필요)

1. **네이버 검색어트렌드/쇼핑인사이트 API** — 네이버 개발자센터에서 앱 등록 후
   `NAVER_CLIENT_ID`/`NAVER_CLIENT_SECRET`을 Railway Variables에 등록 (①②⑤ 활성화)
2. **공구 플랫폼(캘린·82market 등) Cowork 반자동 수집** — 사이트별 이용약관/robots.txt
   확인 후 별도 설계 예정
3. 로컬 또는 Railway 스테이징에서 실제 구동 확인 (이 환경에는 Python이 없어 직접 실행 테스트는
   하지 못하고 코드 리뷰로 검증함)
