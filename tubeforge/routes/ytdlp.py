import subprocess
import time

from flask import Blueprint, jsonify

from ..config import CONFIG, dl_dir, human_time
from ..db import db_exec
from ..jobs import JOBS, make_job
from ..ytdlp_compiler import build_ytdlp, preflight_ytdlp, summarize_formats, ytdlp_metadata
from . import body, cmd_string, jerr

bp = Blueprint("ytdlp", __name__)


@bp.route("/api/ytdlp/preview", methods=["POST"])
def api_ytdlp_preview():
    spec = body()
    try:
        argv = build_ytdlp(spec)
    except Exception as exc:
        return jerr(exc)
    return jsonify({"ok": True, "argv": argv, "cmd": cmd_string(argv),
                    "warnings": preflight_ytdlp(spec)})


@bp.route("/api/ytdlp/run", methods=["POST"])
def api_ytdlp_run():
    spec = body()
    try:
        argv = build_ytdlp(spec)
    except Exception as exc:
        return jerr(exc)
    urls = spec.get("urls") or []
    if isinstance(urls, str):
        urls = urls.splitlines()
    urls = [u.strip() for u in urls if u.strip() and not u.strip().startswith("#")]
    if not urls and not (spec.get("opts") or {}).get("batch_file"):
        return jerr("Add at least one URL.")

    warnings = preflight_ytdlp(spec)
    blockers = [w for w in warnings if w["level"] == "block"]
    if blockers and not spec.get("ignore_warnings"):
        return jsonify({"ok": False, "blocked": True, "warnings": warnings,
                        "error": blockers[0]["text"]}), 409

    if spec.get("split_jobs") and len(urls) > 1:
        staged = []
        for u in urls:
            sub = dict(spec, urls=[u])
            try:
                a = build_ytdlp(sub)
            except Exception as exc:
                return jerr(exc)
            j = make_job("ytdlp", u[:110], [{"label": "download", "argv": a}], spec=sub)
            staged.append(j)
        created = []
        for j in staged:
            JOBS.submit(j)
            created.append(j.id)
        return jsonify({"ok": True, "jobs": created})

    title = (urls[0][:110] if urls else "URLs from batch file") + (" (+%d more)" % (len(urls) - 1) if len(urls) > 1 else "")
    job = make_job("ytdlp", title, [{"label": "download", "argv": argv}], spec=spec)
    JOBS.submit(job)
    for u in urls[:20]:
        db_exec("INSERT INTO url_history(url,title,ts) VALUES (?,?,?)", (u, "", time.time()))
    return jsonify({"ok": True, "job": job.id, "cmd": cmd_string(argv),
                    "warnings": warnings})


@bp.route("/api/ytdlp/info", methods=["POST"])
def api_ytdlp_info():
    data = body()
    url = (data.get("url") or "").strip()
    if not url:
        return jerr("No URL given.")
    try:
        info = ytdlp_metadata(url, flat=bool(data.get("flat")))
    except subprocess.TimeoutExpired:
        return jerr("yt-dlp took too long to answer.")
    except Exception as exc:
        return jerr(exc)

    entries = info.get("entries")
    if entries is not None:
        items = []
        for e in entries[:500]:
            if not e:
                continue
            items.append({"id": e.get("id"), "title": e.get("title"),
                          "url": e.get("url") or e.get("webpage_url"),
                          "duration": e.get("duration"),
                          "duration_h": human_time(e.get("duration")) if e.get("duration") else "",
                          "uploader": e.get("uploader") or e.get("channel"),
                          "thumb": e.get("thumbnail")})
        return jsonify({"ok": True, "kind": "playlist", "title": info.get("title"),
                        "count": len(items), "entries": items})

    db_exec("INSERT INTO url_history(url,title,uploader,duration,thumb,ts) VALUES (?,?,?,?,?,?)",
            (url, info.get("title", ""), info.get("uploader", ""),
             info.get("duration"), info.get("thumbnail", ""), time.time()))

    return jsonify({
        "ok": True, "kind": "video",
        "info": {
            "id": info.get("id"), "title": info.get("title"),
            "uploader": info.get("uploader") or info.get("channel"),
            "channel_url": info.get("channel_url"),
            "duration": info.get("duration"),
            "duration_h": human_time(info.get("duration")) if info.get("duration") else "",
            "thumbnail": info.get("thumbnail"),
            "description": (info.get("description") or "")[:4000],
            "view_count": info.get("view_count"), "like_count": info.get("like_count"),
            "upload_date": info.get("upload_date"), "extractor": info.get("extractor_key"),
            "webpage_url": info.get("webpage_url"), "is_live": info.get("is_live"),
            "categories": info.get("categories"), "tags": (info.get("tags") or [])[:30],
            "chapters": info.get("chapters") or [],
            "subtitles": sorted(list((info.get("subtitles") or {}).keys()))[:80],
            "auto_captions": sorted(list((info.get("automatic_captions") or {}).keys()))[:80],
        },
        "formats": summarize_formats(info),
    })


@bp.route("/api/ytdlp/update", methods=["POST"])
def api_ytdlp_update():
    job = make_job("ytdlp", "update yt-dlp",
                   [{"label": "self-update", "argv": [CONFIG["ytdlp_bin"], "-U"]}])
    JOBS.submit(job)
    return jsonify({"ok": True, "job": job.id})


