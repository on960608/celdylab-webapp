"""주문 엑셀(xlsx/csv)에서 옵션별 주문 수량을 합산한다.

- 필요한 열(상품명, 옵션, 수량, 금액, 주문상태)만 읽는다. 고객 이름, 연락처, 주소 열은 읽지 않는다.
- 열 이름은 판매 채널마다 달라서 후보 목록으로 찾는다. 못 찾으면 column_map으로 직접 지정한다.
  실제 주문 엑셀을 받으면 COLUMN_CANDIDATES와 상태 문구 규칙을 그 파일에 맞게 조정한다.
- 취소 주문은 빼고, 반품은 수량에 포함한 채 반품 수량으로 따로 센다.
- 비밀번호가 걸린 엑셀은 열 수 없다. 엑셀에서 비밀번호 없이 다시 저장해서 올린다.
"""

import csv
import hashlib
import io
from pathlib import Path

COLUMN_CANDIDATES = {
    "product": ["상품명"],
    "option": ["옵션정보", "옵션명", "상품옵션", "옵션"],
    "qty": ["수량", "주문수량", "구매수(수량)", "구매수량"],
    "amount": ["최종 상품별 총 주문금액", "상품별 총 주문금액", "총 주문금액", "결제금액", "상품구매금액", "판매가"],
}
STATUS_CANDIDATES = ["주문상태", "주문세부상태", "클레임상태"]
REQUIRED = ("option", "qty")
CANCEL_WORD = "취소"
RETURN_WORD = "반품"
HEADER_SCAN_ROWS = 10
NO_OPTION = "(옵션 없음)"


def normalize(text):
    return "".join(str(text or "").split())


def file_fingerprint(data):
    """같은 파일을 두 번 올렸는지 확인할 때 쓴다."""
    return hashlib.sha256(data).hexdigest()


def _to_number(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    text = str(value).replace(",", "").replace("원", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _read_rows(path_or_bytes, filename):
    """파일의 모든 행을 값 목록으로 돌려준다. 첫 번째 시트만 읽는다."""
    data = path_or_bytes if isinstance(path_or_bytes, bytes) else Path(path_or_bytes).read_bytes()
    if filename.lower().endswith(".csv"):
        for encoding in ("utf-8-sig", "cp949"):
            try:
                text = data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise ValueError("CSV 글자 인코딩을 알 수 없습니다 (UTF-8, CP949 아님)")
        return list(csv.reader(io.StringIO(text)))

    try:
        from openpyxl import load_workbook
    except ImportError:
        load_workbook = None  # 회사 PC에서 설치가 막혀 있어도 아래 기본 방식으로 읽는다
    try:
        if load_workbook is None:
            return _read_xlsx_stdlib(data)
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        rows = [list(r) for r in wb.worksheets[0].iter_rows(values_only=True)]
        wb.close()
        return rows
    except Exception as e:
        raise ValueError("엑셀을 열 수 없습니다. 비밀번호가 걸려 있다면 비밀번호 없이 다시 저장해 주세요.") from e


def _read_xlsx_stdlib(data):
    """openpyxl 없이 표준 라이브러리만으로 첫 번째 시트의 값을 읽는다."""
    import re
    import zipfile
    import xml.etree.ElementTree as ET

    m = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    r = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    z = zipfile.ZipFile(io.BytesIO(data))
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(m + "si"):
            shared.append("".join(t.text or "" for t in si.iter(m + "t")))
    first_id = ET.fromstring(z.read("xl/workbook.xml")).find(f"{m}sheets/{m}sheet").get(r + "id")
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    target = next(rel.get("Target") for rel in rels if rel.get("Id") == first_id)
    path = target.lstrip("/") if target.startswith("/") else "xl/" + target

    rows = []
    for row in ET.fromstring(z.read(path)).iter(m + "row"):
        cells, col = {}, -1
        for c in row.iter(m + "c"):
            ref = c.get("r")
            if ref:
                col = 0
                for ch in re.match(r"[A-Z]+", ref).group():
                    col = col * 26 + ord(ch) - 64
                col -= 1
            else:
                col += 1
            kind, v = c.get("t"), c.find(m + "v")
            if kind == "s":
                cells[col] = shared[int(v.text)]
            elif kind == "inlineStr":
                cells[col] = "".join(t.text or "" for t in c.iter(m + "t"))
            else:
                cells[col] = v.text if v is not None else None
        rows.append([cells.get(i) for i in range(max(cells) + 1)] if cells else [])
    return rows


def _find_columns(header, column_map):
    names = [normalize(h) for h in header]
    found = {}
    for field, candidates in COLUMN_CANDIDATES.items():
        wanted = [column_map[field]] if column_map and field in column_map else candidates
        for cand in wanted:
            if normalize(cand) in names:
                found[field] = names.index(normalize(cand))
                break
    found["status"] = [names.index(normalize(c)) for c in STATUS_CANDIDATES if normalize(c) in names]
    return found


def read_orders(path_or_bytes, filename=None, column_map=None):
    """주문 파일을 읽어 (상품명, 옵션 글자)별로 수량과 금액을 합친다.

    column_map: 자동으로 못 찾는 열을 직접 지정. 예: {"option": "옵션내용", "qty": "개수"}
    """
    filename = filename or str(path_or_bytes)
    rows = _read_rows(path_or_bytes, filename)

    header_at, cols = None, None
    for i, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        found = _find_columns(row, column_map)
        if all(f in found for f in REQUIRED):
            header_at, cols = i, found
            break
    if header_at is None:
        raise ValueError("옵션 열과 수량 열을 찾지 못했습니다. column_map으로 열 이름을 지정해 주세요.")

    header = rows[header_at]
    merged = {}
    cancelled_qty = 0
    for row in rows[header_at + 1:]:
        cell = lambda idx: row[idx] if idx is not None and idx < len(row) else None
        qty = _to_number(cell(cols["qty"]))
        if not qty:
            continue  # 빈 줄, 합계 줄
        status = " ".join(str(cell(i) or "") for i in cols["status"])
        if CANCEL_WORD in status and RETURN_WORD not in status:
            cancelled_qty += int(qty)
            continue
        product = str(cell(cols.get("product")) or "").strip()
        option = str(cell(cols["option"]) or "").strip() or NO_OPTION
        item = merged.setdefault((product, option), {"product": product, "option": option,
                                                     "qty": 0, "amount": 0, "return_qty": 0})
        item["qty"] += int(qty)
        item["amount"] += int(_to_number(cell(cols.get("amount"))) or 0)
        if RETURN_WORD in status:
            item["return_qty"] += int(qty)

    used = {f: header[i] for f, i in cols.items() if f != "status"}
    used["status"] = [header[i] for i in cols["status"]]
    result_rows = sorted(merged.values(), key=lambda r: -r["qty"])
    return {
        "columns": used,
        "rows": result_rows,
        "total_qty": sum(r["qty"] for r in result_rows),
        "cancelled_qty": cancelled_qty,
    }


def apply_aliases(rows, aliases):
    """옵션 글자를 표준 옵션명으로 바꿔 합친다.

    aliases: {"주문서에 적힌 옵션 글자": "표준 옵션명"}. 띄어쓰기 차이는 무시한다.
    처음 보는 옵션 글자는 unmatched로 돌려준다. 사람이 연결하면 aliases에 저장해서 다음부터 쓴다.
    """
    lookup = {normalize(k): v for k, v in aliases.items()}
    options, unmatched = {}, []
    for r in rows:
        std = lookup.get(normalize(r["option"]))
        if std is None:
            unmatched.append(r["option"])
            continue
        o = options.setdefault(std, {"option": std, "qty": 0, "amount": 0, "return_qty": 0})
        for k in ("qty", "amount", "return_qty"):
            o[k] += r[k]
    return {"options": sorted(options.values(), key=lambda o: -o["qty"]),
            "unmatched": sorted(set(unmatched))}
