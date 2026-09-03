import io
import json
import time
import uuid

from flask import Blueprint, Response, render_template, request, redirect, url_for, session, flash, send_file

from analysis import load_har_entries, extract_comments_from_har_entry, build_ig_comments_excel

igcomments_bp = Blueprint("igcomments", __name__, url_prefix="/ig-comments")

# 추출 결과는 만들어지자마자 바로 다운로드하는 용도라 DB에 영구 저장하지 않고, 메모리에
# 잠깐만 담아둬요(서버가 재시작되면 사라져요). 1차 개발 범위 — "HAR 파일 → 전체 댓글
# 수집 → 엑셀 다운로드" — 에는 이걸로 충분하고, 이후 당첨자 추첨/필터링 등으로 확장할
# 때는 이 결과 엑셀을 그대로 "댓글 이벤트 추첨" 페이지의 파일 업로드에 올리면 돼요
# (컬럼명이 자동 인식되도록 맞춰뒀어요).
_RESULT_CACHE = {}
_CACHE_TTL_SECONDS = 30 * 60


@igcomments_bp.before_request
def _require_login():
    if not session.get("user_id"):
        return redirect(url_for("login", next=request.path))


def _cleanup_cache():
    now = time.time()
    for k in [k for k, v in _RESULT_CACHE.items() if now - v["created_at"] > _CACHE_TTL_SECONDS]:
        _RESULT_CACHE.pop(k, None)


@igcomments_bp.route("/")
def index():
    return render_template("igcomments.html")


def _ndjson(obj):
    return json.dumps(obj, ensure_ascii=False) + "\n"


@igcomments_bp.route("/extract", methods=["POST"])
def extract():
    _cleanup_cache()
    har_file = request.files.get("har_file")

    if not har_file or not har_file.filename:
        return Response(_ndjson({"type": "error", "message": "HAR 파일을 먼저 선택해 주세요."}), mimetype="application/x-ndjson")
    if not har_file.filename.lower().endswith(".har"):
        return Response(_ndjson({
            "type": "error",
            "message": "HAR 파일(.har)만 올릴 수 있어요. 크롬 개발자도구 Network 탭에서 우클릭 → 'Save all as HAR with content'로 저장해 주세요.",
        }), mimetype="application/x-ndjson")

    raw_bytes = har_file.read()

    def generate():
        entries, error = load_har_entries(raw_bytes)
        if error:
            yield _ndjson({"type": "error", "message": error})
            return

        total = len(entries)
        found = {}
        counter = [0]
        responses_scanned = 0
        chunk = max(1, total // 200)  # 대략 0.5%마다 진행 상황을 전송해요(너무 잦지 않게)

        yield _ndjson({"type": "progress", "scanned": 0, "total": total, "found": 0})

        for i, entry in enumerate(entries, start=1):
            try:
                if extract_comments_from_har_entry(entry, found, counter):
                    responses_scanned += 1
            except Exception:
                pass
            if i % chunk == 0 or i == total:
                yield _ndjson({"type": "progress", "scanned": i, "total": total, "found": len(found)})

        if not found:
            yield _ndjson({
                "type": "error",
                "message": "이 HAR 파일에서 댓글 데이터를 찾지 못했어요. 게시물 페이지에서 댓글을 끝까지 스크롤해 모두 불러온 뒤 저장한 HAR 파일인지 확인해 주세요.",
            })
            return

        comments = list(found.values())
        raw_found = counter[0]
        final_count = len(comments)

        buf = build_ig_comments_excel(comments)
        token = uuid.uuid4().hex
        filename = f"instagram_comments_{final_count}.xlsx"
        _RESULT_CACHE[token] = {"data": buf.getvalue(), "filename": filename, "created_at": time.time()}

        yield _ndjson({
            "type": "done",
            "raw_found": raw_found,
            "duplicates_removed": max(0, raw_found - final_count),
            "final_count": final_count,
            "responses_scanned": responses_scanned,
            "token": token,
            "filename": filename,
        })

    return Response(generate(), mimetype="application/x-ndjson")


@igcomments_bp.route("/download/<token>")
def download(token):
    item = _RESULT_CACHE.get(token)
    if not item:
        flash("다운로드 유효 시간이 지났어요. HAR 파일을 다시 올려서 추출해 주세요.")
        return redirect(url_for("igcomments.index"))
    return send_file(
        io.BytesIO(item["data"]),
        as_attachment=True,
        download_name=item["filename"],
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
