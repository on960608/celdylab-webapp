import os

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify, send_file

import db
from analysis import (
    parse_comments_text, parse_comments_spreadsheet, draw_giveaway_winners,
    fetch_ig_comments_via_graph_api, build_winners_excel, BRANDS,
)

giveaway_bp = Blueprint("giveaway", __name__, url_prefix="/giveaway")


@giveaway_bp.before_request
def _require_login():
    if not session.get("user_id"):
        return redirect(url_for("login", next=request.path))


def _api_configured():
    return bool(os.environ.get("INSTAGRAM_ACCESS_TOKEN") and os.environ.get("INSTAGRAM_BUSINESS_ID"))


@giveaway_bp.route("/")
def index():
    events = db.list_giveaway_events()
    return render_template("giveaway.html", brands=BRANDS, events=events, api_configured=_api_configured(), result=None)


@giveaway_bp.route("/api/fetch-comments", methods=["POST"])
def api_fetch_comments():
    post_url = (request.get_json(silent=True) or {}).get("post_url", "").strip()
    if not post_url:
        return jsonify({"ok": False, "error": "게시물 링크를 먼저 입력해 주세요."})
    comments, error = fetch_ig_comments_via_graph_api(post_url)
    if error:
        return jsonify({"ok": False, "error": error})
    lines = [f"{c['username']}: {c['text']}" for c in comments]
    return jsonify({"ok": True, "count": len(comments), "raw_text": "\n".join(lines)})


@giveaway_bp.route("/draw", methods=["POST"])
def draw():
    f = request.form
    post_url = f.get("post_url", "").strip()
    event_type = f.get("event_type", "general").strip()
    keyword = f.get("keyword", "").strip()
    winner_count = int(f.get("winner_count") or 0)
    excluded_accounts = f.get("excluded_accounts", "").strip()
    comments_raw = f.get("comments_raw", "")
    related_brand = f.get("related_brand", "").strip()
    related_note = f.get("related_note", "").strip()
    source = f.get("source", "manual")

    comments_file = request.files.get("comments_file")
    if comments_file and comments_file.filename:
        comments, file_error = parse_comments_spreadsheet(comments_file)
        if file_error:
            flash(f"업로드한 파일을 처리하지 못했어요: {file_error}")
            return redirect(url_for("giveaway.index"))
        source = "file"
    else:
        comments = parse_comments_text(comments_raw)

    if not comments:
        flash("댓글 데이터가 없어요. 자동 불러오기·파일 업로드·직접 붙여넣기 중 하나로 댓글을 채워 주세요.")
        return redirect(url_for("giveaway.index"))
    if event_type == "keyword" and not keyword:
        flash("구매인증/키워드 이벤트는 필수 단어를 입력해 주세요.")
        return redirect(url_for("giveaway.index"))
    if winner_count <= 0:
        flash("당첨 인원을 1명 이상 입력해 주세요.")
        return redirect(url_for("giveaway.index"))

    winners, stats = draw_giveaway_winners(comments, event_type, keyword, winner_count, excluded_accounts)

    event_id = db.create_giveaway_event(
        {
            "post_url": post_url,
            "event_type": event_type,
            "keyword": keyword,
            "excluded_accounts": excluded_accounts,
            "winner_count": winner_count,
            "total_comments": stats["total_comments"],
            "matched_accounts": stats["matched_accounts"],
            "final_pool_count": stats["final_pool_count"],
            "source": source,
            "related_brand": related_brand,
            "related_note": related_note,
        },
        winners,
        session.get("user_name"),
    )

    events = db.list_giveaway_events()
    result = db.get_giveaway_event(event_id)
    result["stats"] = stats
    return render_template("giveaway.html", brands=BRANDS, events=events, api_configured=_api_configured(), result=result)


@giveaway_bp.route("/<int:event_id>/export")
def export(event_id):
    event = db.get_giveaway_event(event_id)
    if not event:
        flash("추첨 기록을 찾을 수 없어요.")
        return redirect(url_for("giveaway.index"))
    if not event["winners"]:
        flash("당첨자가 없어서 엑셀로 내려받을 내용이 없어요.")
        return redirect(url_for("giveaway.index"))

    buf = build_winners_excel(event)
    date_part = (event["created_at"] or "")[:10] or "기록"
    filename = f"댓글이벤트_당첨자_{date_part}_{event_id}.xlsx"
    return send_file(
        buf,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@giveaway_bp.route("/<int:event_id>/delete", methods=["POST"])
def delete(event_id):
    db.delete_giveaway_event(event_id)
    flash("삭제했어요.")
    return redirect(url_for("giveaway.index"))
