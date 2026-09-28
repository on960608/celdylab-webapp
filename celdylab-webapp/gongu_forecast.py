"""공구 옵션 수량 계산기의 핵심 로직.

팔로워 수와 제품을 넣으면 옵션별로 몇 개를 요청(준비)해야 하는지 계산한다.
웹 프레임워크와 무관하고 표준 라이브러리만 쓴다. 앱에서는 DB 기록을
GonguRecord 목록으로 바꿔서 forecast()에 넘기면 된다.

규칙 요약 (작업지시서 01의 3단계와 같다)
- 제품 기록이 MIN_RECORDS건 이상: 그 제품의 "1만 명당 판매량" 백분위를 쓴다.
- 그보다 적으면(처음 하는 제품 포함): 같은 브랜드(부족하면 전체) 기록의
  "1만 명당 매출" 백분위로 예상 매출을 구하고, 평균 판매가로 나눠 수량으로 바꾼다.
- 평균 대신 백분위(보수 25%, 보통 50%, 낙관 75%)를 쓴다. 큰 기록 한 건에 끌려가지 않게.
"""

from dataclasses import dataclass
from math import floor

MIN_RECORDS = 3
BANDS = (("low", 0.25), ("mid", 0.50), ("high", 0.75))
BAND_LABELS = {"low": "보수", "mid": "보통", "high": "낙관"}


@dataclass
class GonguRecord:
    product: str
    brand: str
    followers: int  # 팔로워 수 (명)
    revenue: int  # 매출 (원)
    qty: int  # 주문 수량 합 (옵션 수량을 더한 값)


@dataclass
class Option:
    name: str
    share: float  # 옵션 비중. 모든 옵션의 합이 1
    pack: int  # 구성 수량: 옵션 하나에 실제로 들어가는 개수
    price: int  # 판매가 (원)


def round_half_up(x):
    """0.5는 올린다. 파이썬 round()는 0.5를 짝수 쪽으로 보내서 화면(JS)과 달라진다."""
    return int(floor(x + 0.5))


def normalize(name):
    """띄어쓰기 차이를 없앤다. 예: "세정서버 세트" == "세정서버세트"."""
    return "".join((name or "").split())


def percentile_inc(values, p):
    """엑셀 PERCENTILE.INC와 같은 선형 보간 백분위."""
    xs = sorted(values)
    if not xs:
        raise ValueError("값이 없습니다")
    h = (len(xs) - 1) * p
    lo = int(floor(h))
    if lo + 1 >= len(xs):
        return xs[-1]
    return xs[lo] + (h - lo) * (xs[lo + 1] - xs[lo])


def per_10k(value, followers):
    """팔로워 1만 명당 값."""
    return value / (followers / 10000)


def bands(values):
    return {key: percentile_inc(values, p) for key, p in BANDS}


def split_by_share(total, shares):
    """총 수량을 비중대로 나눈다. 반올림 때문에 합이 안 맞으면 비중이 가장 큰 옵션에서 맞춘다."""
    parts = [round_half_up(total * s) for s in shares]
    biggest = max(range(len(shares)), key=lambda i: shares[i])
    parts[biggest] += total - sum(parts)
    return parts


def forecast(records, product, brand, followers, options, margin=0.2):
    """옵션별 예상 주문 수량과 추천 요청 수량을 계산한다.

    records: 과거 공구 기록(GonguRecord) 목록
    product, brand: 계산할 제품과 브랜드
    followers: 이번 셀러의 팔로워 수
    options: Option 목록 (비중 합 1)
    margin: 여유분. 0.2면 보통 예측에 20%를 더해 추천 요청 수량을 만든다.
    """
    if followers <= 0:
        raise ValueError("팔로워 수는 0보다 커야 합니다")
    if not options:
        raise ValueError("옵션이 하나 이상 있어야 합니다")
    share_sum = sum(o.share for o in options)
    if abs(share_sum - 1) > 0.001:
        raise ValueError(f"옵션 비중의 합이 100%가 아닙니다 ({share_sum * 100:.1f}%)")

    same_product = [r for r in records if normalize(r.product) == normalize(product)]
    if len(same_product) >= MIN_RECORDS:
        method = "qty"
        rates = bands([per_10k(r.qty, r.followers) for r in same_product])
        totals = {k: round_half_up(v * followers / 10000) for k, v in rates.items()}
        basis = f"{product} 기록 {len(same_product)}건의 판매량 기준"
    else:
        same_brand = [r for r in records if normalize(r.brand) == normalize(brand)]
        pool = same_brand if len(same_brand) >= MIN_RECORDS else list(records)
        if not pool:
            raise ValueError("계산에 쓸 과거 기록이 없습니다")
        avg_price = sum(o.share * o.price for o in options)
        if avg_price <= 0:
            raise ValueError("옵션 판매가를 넣어 주세요")
        method = "revenue"
        rates = bands([per_10k(r.revenue, r.followers) for r in pool])
        totals = {k: round_half_up(v * followers / 10000 / avg_price) for k, v in rates.items()}
        scope = f"{brand} 기록" if pool is same_brand else "전체 기록"
        basis = f"처음 하는 제품: {scope} {len(pool)}건의 매출 기준"

    shares = [o.share for o in options]
    per_band = {k: split_by_share(totals[k], shares) for k in totals}
    rows = []
    for i, o in enumerate(options):
        request = round_half_up(per_band["mid"][i] * (1 + margin))
        rows.append({
            "option": o.name,
            "share": o.share,
            "low": per_band["low"][i],
            "mid": per_band["mid"][i],
            "high": per_band["high"][i],
            "request": request,  # 추천 요청 수량
            "units": request * o.pack,  # 실제 개수 = 추천 요청 수량 × 구성 수량
        })
    revenue = {k: sum(q * o.price for q, o in zip(per_band[k], options)) for k in per_band}

    warning = None
    if method == "revenue" and same_product:
        warning = f"{product} 기록이 {len(same_product)}건뿐이라 다른 제품 기록을 함께 썼습니다"
    return {
        "method": method,
        "basis": basis,
        "rates_per_10k": rates,
        "totals": totals,
        "rows": rows,
        "revenue": revenue,
        "request_total": sum(r["request"] for r in rows),
        "units_total": sum(r["units"] for r in rows),
        "warning": warning,
    }
