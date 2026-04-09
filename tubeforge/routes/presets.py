import json
import time

from flask import Blueprint, jsonify, request

from ..db import db_exec, db_query
from . import body, jerr

bp = Blueprint("presets", __name__)


@bp.route("/api/presets", methods=["GET", "POST", "DELETE"])
def api_presets():
    if request.method == "GET":
        kind = request.args.get("kind")
        rows = db_query("SELECT * FROM presets WHERE (? IS NULL OR kind=?) ORDER BY kind,name",
                        (kind, kind))
        for r in rows:
            try:
                r["data"] = json.loads(r["data"])
            except Exception:
                r["data"] = {}
        return jsonify({"ok": True, "presets": rows})
    if request.method == "DELETE":
        db_exec("DELETE FROM presets WHERE id=?", (request.args.get("id"),))
        return jsonify({"ok": True})
    data = body()
    name = (data.get("name") or "").strip()
    if not name:
        return jerr("Give the preset a name.")
    db_exec("INSERT OR REPLACE INTO presets(kind,name,data,created) VALUES (?,?,?,?)",
            (data.get("kind") or "ytdlp", name, json.dumps(data.get("data") or {}), time.time()))
    return jsonify({"ok": True})


@bp.route("/api/pipelines", methods=["GET", "POST", "DELETE"])
def api_pipelines():
    if request.method == "GET":
        rows = db_query("SELECT * FROM pipelines ORDER BY name")
        for r in rows:
            try:
                r["data"] = json.loads(r["data"])
            except Exception:
                r["data"] = {}
        return jsonify({"ok": True, "pipelines": rows})
    if request.method == "DELETE":
        db_exec("DELETE FROM pipelines WHERE id=?", (request.args.get("id"),))
        return jsonify({"ok": True})
    data = body()
    if not (data.get("name") or "").strip():
        return jerr("Give the pipeline a name.")
    db_exec("INSERT OR REPLACE INTO pipelines(name,data,created) VALUES (?,?,?)",
            (data["name"].strip(), json.dumps(data.get("data") or {}), time.time()))
    return jsonify({"ok": True})


@bp.route("/api/history", methods=["GET", "DELETE"])
def api_history():
    if request.method == "DELETE":
        if request.args.get("id"):
            db_exec("DELETE FROM url_history WHERE id=?", (request.args.get("id"),))
        else:
            db_exec("DELETE FROM url_history")
        return jsonify({"ok": True})
    rows = db_query("SELECT * FROM url_history ORDER BY ts DESC LIMIT 300")
    seen, out = set(), []
    for r in rows:
        if r["url"] in seen:
            continue
        seen.add(r["url"])
        out.append(r)
    return jsonify({"ok": True, "history": out})


@bp.route("/api/jobhistory")
def api_jobhistory():
    rows = db_query("SELECT id,kind,title,status,rc,created,started,finished FROM jobs "
                    "ORDER BY created DESC LIMIT 400")
    return jsonify({"ok": True, "jobs": rows})


@bp.route("/api/snippets", methods=["GET", "POST", "DELETE"])
def api_snippets():
    if request.method == "GET":
        return jsonify({"ok": True, "snippets": db_query(
            "SELECT * FROM snippets ORDER BY created DESC")})
    if request.method == "DELETE":
        db_exec("DELETE FROM snippets WHERE id=?", (request.args.get("id"),))
        return jsonify({"ok": True})
    data = body()
    db_exec("INSERT INTO snippets(name,body,tags,created) VALUES (?,?,?,?)",
            (data.get("name") or "snippet", data.get("body") or "",
             data.get("tags") or "", time.time()))
    return jsonify({"ok": True})


