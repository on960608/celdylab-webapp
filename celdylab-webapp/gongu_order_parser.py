"""'세부내역서' 형태(택배사 발송용 주문 목록)의 주문 파일을 읽는다.

order_excel.py는 상품명/옵션/금액/주문상태가 각각 다른 열에 있는 스마트스토어·카페24식
주문 엑셀을 읽는 용도다. 코드니처 세정서버 정산서 안의 "세부내역서" 시트는 모양이 달라서
이 파일을 따로 둔다 (작업지시서 01의 "실제 열 이름이 후보에 없으면 맞춰 조정한다" 규칙에 따름).

실제로 확인된 차이
- 상품명과 옵션이 한 칸에 같이 적혀 있다. 예: "옵션=변기수조 세정서버1 (6ea) + 하수구 악취
  세정서버1 (10ea)", "<상품명>...<주문옵션>1. 변기 수조 세정 서버 1+1(총 12개입)",
  "수량=2세트 (20개입) ...". 옵션 글자만 뽑아서 옵션 별칭(option_aliases)으로 표준 옵션과 연결한다.
- 건별 "금액" 칸이 없다. 연결된 표준 옵션의 판매가 × 수량으로 매출을 계산한다 (앱 쪽에서 처리).
- 반품/교환/훼손이 별도 칸이 아니라 "비고" 칸의 문구나, 시트 중간에 끼어있는 구분줄
  ("교환 진행" 같은, 그 칸에만 글자가 있고 나머지는 빈 행)로 표시된다.

개인정보 규칙: 수령인 이름, 휴대전화, 주소, 우편번호 열은 이름조차 찾지 않는다. 읽는 열은
"주문상품명(옵션포함)"과 "수량", "비고" 뿐이다.
"""

from order_excel import _read_rows, _to_number, normalize, file_fingerprint  # noqa: F401  (file_fingerprint는 앱에서 재사용)

COMBINED_CANDIDATES = ["주문상품명(옵션포함)", "주문상품명", "상품명(옵션포함)", "주문상품"]
QTY_CANDIDATES = ["수량", "주문수량"]
NOTE_CANDIDATES = ["비고"]
OPTION_MARKERS = ["옵션=", "<주문옵션>", "수량="]

# 시트 중간 구분줄 글자 → 그 뒤 행에 적용할 상태. None이면 상태 없음(정상으로 취급, 도서산간처럼
# 배송비만 다른 정상 주문).
SECTION_STATUS = {
    "교환 진행": "교환",
    "교환": "교환",
    "단순 반품": "반품",
    "반품": "반품",
    "훼손": "훼손",
    "제주.도서산간지역": None,
    "제주": None,
    "도서산간": None,
}
RETURN_LIKE_STATUSES = {"반품", "교환", "훼손"}
HEADER_SCAN_ROWS = 15


def _extract_option_text(cell):
    """상품명+옵션이 합쳐진 칸에서 옵션 글자만 뽑는다. 구분자를 못 찾으면 칸 전체를 쓴다."""
    text = str(cell or "")
    for marker in OPTION_MARKERS:
        idx = text.find(marker)
        if idx != -1:
            return text[idx + len(marker):].strip()
    return text.strip()


def _find_columns(header):
    names = [normalize(h) for h in header]
    found = {}
    for cand in COMBINED_CANDIDATES:
        if normalize(cand) in names:
            found["combined"] = names.index(normalize(cand))
            break
    for cand in QTY_CANDIDATES:
        if normalize(cand) in names:
            found["qty"] = names.index(normalize(cand))
            break
    for cand in NOTE_CANDIDATES:
        if normalize(cand) in names:
            found["note"] = names.index(normalize(cand))
            break
    return found


def _row_is_section_marker(row, combined_idx):
    """옵션 칸에만 글자가 있고 나머지 칸은 전부 비어있으면 구분줄로 본다."""
    for i, v in enumerate(row):
        if i == combined_idx:
            continue
        if v not in (None, ""):
            return False
    return True


def parse_courier_orders(path_or_bytes, filename=None):
    """세부내역서를 옵션 글자별로 합산한다.

    반환: {
      "columns": 실제로 읽은 열 이름,
      "rows": [{"option": 원문 옵션 글자, "qty": 정상+반품 합, "return_qty": 반품/교환/훼손 합}],
      "total_qty": 전체 합,
    }
    옵션 글자를 표준 옵션으로 연결하는 건 이 함수가 하지 않는다 (호출한 쪽에서
    db.find_option_alias()로 연결한다).
    """
    filename = filename or str(path_or_bytes)
    rows = _read_rows(path_or_bytes, filename)

    header_at, cols = None, None
    for i, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        found = _find_columns(row)
        if "combined" in found and "qty" in found:
            header_at, cols = i, found
            break
    if header_at is None:
        raise ValueError(
            "옵션 글자가 들어있는 열(예: 주문상품명(옵션포함))을 찾지 못했습니다. "
            "열 이름이 다르면 COMBINED_CANDIDATES에 추가해 주세요."
        )

    header = rows[header_at]
    merged = {}
    current_status = None
    for row in rows[header_at + 1:]:
        cell = lambda idx: row[idx] if idx is not None and idx < len(row) else None
        combined_raw = cell(cols["combined"])

        # 구분줄(예: "교환 진행")인지 먼저 확인 — 그 칸에만 글자가 있고 나머지는 빈 행.
        marker_text = str(combined_raw or "").strip()
        if marker_text and _row_is_section_marker(row, cols["combined"]):
            if marker_text in SECTION_STATUS:
                current_status = SECTION_STATUS[marker_text]
                continue
            # 모르는 구분줄은 무시하고 넘어간다 (상태를 함부로 바꾸지 않음).
            continue

        qty = _to_number(cell(cols["qty"]))
        if not qty:
            continue  # 빈 줄, 합계 줄
        option_text = _extract_option_text(combined_raw)
        if not option_text:
            continue

        note = str(cell(cols.get("note")) or "") if cols.get("note") is not None else ""
        status = current_status
        if "반품" in note:
            status = "반품"
        elif "훼손" in note:
            status = "훼손"
        elif "교환" in note:
            status = "교환"

        item = merged.setdefault(option_text, {"option": option_text, "qty": 0, "return_qty": 0})
        item["qty"] += int(qty)
        if status in RETURN_LIKE_STATUSES:
            item["return_qty"] += int(qty)

    result_rows = sorted(merged.values(), key=lambda r: -r["qty"])
    return {
        "columns": {k: header[i] for k, i in cols.items()},
        "rows": result_rows,
        "total_qty": sum(r["qty"] for r in result_rows),
        "total_return_qty": sum(r["return_qty"] for r in result_rows),
    }
