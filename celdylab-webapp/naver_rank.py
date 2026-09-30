"""네이버 데이터랩 쇼핑인사이트 인기검색어 TOP100.

공식 API에는 인기검색어 순위가 없어서, 데이터랩 화면이 내부적으로 부르는 주소를 쓴다.
비공식 방법이므로 네이버가 바꾸면 멈출 수 있다. 하루 1번, 필요한 분야만 가져온다.
막히면 우회하지 말고 멈춘다 (프록시, 접속 정보 위장, 캡차 풀기 금지).

표준 라이브러리(urllib)만 쓴다. 회사 보안 프록시 인증서가 있는 윈도우 PC에서도
윈도우 인증서 저장소를 그대로 쓰기 때문에 requests보다 문제가 적다.
2026-09-27 동작 확인: 분야(cid), 기간, 성별(gender), 연령(age) 조건 모두 반영됨.
"""

import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

RANK_URL = "https://datalab.naver.com/shoppingInsight/getCategoryKeywordRank.naver"
REFERER = "https://datalab.naver.com/shoppingInsight/sCategory.naver"
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")

# 셀디랩 제품과 관련 있는 생활/건강 분야 (2026-09-27 확인)
CATEGORIES = {
    "생활/건강": "50000008",
    "청소용품": "50000077",
    "세탁용품": "50000062",
    "주방용품": "50000061",
    "욕실용품": "50000157",
    "수납/정리용품": "50000076",
    "생활용품": "50000078",
    "구강위생용품": "50000072",
}
GENDERS = {"": "전체", "f": "여성", "m": "남성"}
AGES = ("10", "20", "30", "40", "50", "60")
PAGE_SIZE = 20
TOP_N = 100


class NaverRankError(Exception):
    pass


def _ssl_contexts():
    """운영체제 인증서를 먼저 쓰고, 안 되면 certifi 인증서를 쓴다. 인증서 검사를 끄지는 않는다.

    윈도우에서는 운영체제(윈도우 인증서 저장소)로 대부분 된다. 회사 보안 프록시가 있어도 마찬가지다.
    맥의 python.org 파이썬처럼 운영체제 인증서를 못 읽는 환경은 certifi로 된다.
    """
    yield ssl.create_default_context()
    try:
        import certifi
    except ImportError:
        return
    yield ssl.create_default_context(cafile=certifi.where())


def _post(form, opener, timeout=15):
    body = urllib.parse.urlencode(form).encode("utf-8")
    req = urllib.request.Request(RANK_URL, data=body, method="POST", headers={
        "Referer": REFERER,
        "User-Agent": USER_AGENT,
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    })
    cert_error = None
    for context in _ssl_contexts():
        try:
            with opener(req, timeout=timeout, context=context) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            if not isinstance(e.reason, ssl.SSLCertVerificationError):
                raise
            cert_error = e
    raise cert_error


def fetch_top100(cid, end=None, days=7, gender="", ages=(), pause=0.35,
                 opener=urllib.request.urlopen, sleep=time.sleep):
    """분야 하나의 인기검색어 TOP100을 가져온다.

    end: 기간 마지막 날. 기본은 이틀 전 (최근 날짜는 아직 집계 전일 수 있다)
    gender: "" 전체, "f" 여성, "m" 남성
    ages: 예) ("30", "40"). 비우면 전체 연령
    반환: {"range": "2026.09.19. ~ 2026.09.25.", "ranks": [{"rank": 1, "keyword": "비데"}, ...]}

    2026-09-30: 오늘 처음 보는 분야·성별·연령 조합을 고르면 이 함수가 5페이지를 순서대로
    (한 번에 하나씩) 물어보는데, 예전에는 페이지 사이를 1초씩 쉬어서 화면이 뜨기까지 4~5초쯤
    걸렸다. 요청을 한꺼번에 동시에 보내는 방법도 있지만, 그러면 네이버 입장에서 봤을 때 아주
    짧은 시간에 여러 번 묻는 패턴으로 보여서 차단될 위험이 살짝 더 있다. 그래서 순서대로
    물어보는 방식은 그대로 두고, 사이 간격만 1초 -> 0.35초로 줄였다(사용자 확인 후 적용).
    막히면(차단되면) 이전처럼 그대로 멈추고 알린다 — 우회하지 않는다."""
    if gender not in GENDERS:
        raise ValueError(f"gender는 '', 'f', 'm' 중 하나여야 합니다: {gender!r}")
    bad = [a for a in ages if a not in AGES]
    if bad:
        raise ValueError(f"알 수 없는 연령대: {bad}")

    end = end or date.today() - timedelta(days=2)
    for back in range(3):  # 결과가 비면 하루씩 앞당긴다
        last = end - timedelta(days=back)
        first = last - timedelta(days=days - 1)
        ranks, period = [], ""
        for page in range(1, TOP_N // PAGE_SIZE + 1):
            form = {
                "cid": cid, "timeUnit": "date",
                "startDate": first.isoformat(), "endDate": last.isoformat(),
                "age": ",".join(ages), "gender": gender, "device": "",
                "page": page, "count": PAGE_SIZE,
            }
            data = _call_with_retry(form, opener, sleep, pause)
            period = data.get("range") or period
            items = data.get("ranks") or []
            ranks.extend({"rank": int(r["rank"]), "keyword": r["keyword"]} for r in items)
            if len(items) < PAGE_SIZE:
                break
            sleep(pause)
        if ranks:
            return {"range": period, "ranks": ranks[:TOP_N]}
    raise NaverRankError("최근 3일 기간으로 모두 빈 결과가 왔습니다")


def _call_with_retry(form, opener, sleep, pause):
    """한 번만 다시 시도한다. 그래도 안 되면 멈춘다."""
    last_error = None
    for attempt in range(2):
        try:
            data = _post(form, opener)
            if data.get("returnCode", 0) != 0:
                raise NaverRankError(f"네이버 응답 오류: {data.get('message')}")
            return data
        except Exception as e:  # 네트워크 오류, 차단, 형식 변경
            last_error = e
            if attempt == 0:
                sleep(pause * 3)
    raise NaverRankError(f"순위를 가져오지 못했습니다. 우회하지 말고 확인이 필요합니다: {last_error}")


def rank_changes(today, previous):
    """전날(또는 이전) 순위와 비교한다.

    today, previous: fetch_top100()의 "ranks" 목록
    반환 항목의 change: 양수면 오름(▲), 음수면 내림(▼), None이면 새로 들어옴(NEW)
    """
    before = {r["keyword"]: r["rank"] for r in previous}
    out = []
    for r in today:
        old = before.get(r["keyword"])
        out.append({**r, "change": None if old is None else old - r["rank"], "is_new": old is None})
    return out


if __name__ == "__main__":
    # 동작 확인용: python naver_rank.py  (요청 5번)
    result = fetch_top100(CATEGORIES["생활/건강"])
    print(result["range"], f"{len(result['ranks'])}개")
    for r in result["ranks"][:10]:
        print(r["rank"], r["keyword"])
