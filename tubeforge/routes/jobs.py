import json
import os
import re
from queue import Empty

from flask import Blueprint, Response, jsonify, request, send_file, stream_with_context

from ..config import LOG_DIR
from ..db import db_query
from ..jobs import BUS, JOBS, Job, make_job
from . import jerr
from .ffmpeg import _compile_pipeline, _ff_build

bp = Blueprint("jobs", __name__)


@bp.route("/api/jobs")
def api_jobs():
    try:
        limit = min(max(int(request.args.get("limit", 200)), 1), 1000)
    except (TypeError, ValueError):
        return jerr("Job limit must be an integer between 1 and 1000.")
    return jsonify({"ok": True, "jobs": JOBS.list(limit)})


@bp.route("/api/jobs/<jid>")
def api_job(jid):
    job = JOBS.get(jid)
    if not job:
        rows = db_query("SELECT * FROM jobs WHERE id=?", (jid,))
        if rows:
            return jsonify({"ok": True, "job": rows[0], "archived": True})
        return jerr("Unknown job.", 404)
    return jsonify({"ok": True, "job": job.brief(), "log": list(job.log)})


@bp.route("/api/jobs/<jid>/cancel", methods=["POST"])
def api_job_cancel(jid):
    job = JOBS.get(jid)
    if not job:
        return jerr("Unknown job.", 404)
    job.cancel()
    return jsonify({"ok": True})


@bp.route("/api/jobs/<jid>/retry", methods=["POST"])
def api_job_retry(jid):
    job = JOBS.get(jid)
    if not job:
        return jerr("Unknown job.", 404)
    if job.status in ("queued", "running"):
        return jerr("Wait until the current job stops before retrying.", 409)
    stages, meta = job.stages, dict(job.meta)
    try:
        if job.kind == "ffmpeg" and job.spec.get("steps"):
            stages, notes, outputs, temps = _compile_pipeline(dict(job.spec, _creating=True))
            meta.update(outputs=outputs, cleanup=temps, notes=notes)
        elif job.kind == "ffmpeg" and job.spec.get("op"):
            built, dur = _ff_build(dict(job.spec, _creating=True))
            stages = built["stages"]
            meta.update(outputs=built["outputs"], cleanup=built.get("cleanup", []), notes=built["notes"], duration=dur)
    except Exception as exc:
        return jerr(exc)
    clone = Job(job.kind, job.title, stages, cwd=job.cwd, spec=job.spec, meta=meta)
    JOBS.submit(clone)
    return jsonify({"ok": True, "job": clone.id})


@bp.route("/api/jobs/<jid>/log")
def api_job_log(jid):
    if not re.fullmatch(r"[0-9a-f]{12}", jid or ""):
        return jerr("Invalid job id.", 400)
    job = JOBS.get(jid)
    if job:
        return Response("".join(e["d"] + "\n" for e in job.log),
                        mimetype="text/plain; charset=utf-8")
    path = os.path.join(LOG_DIR, "%s.log" % jid)
    if os.path.exists(path):
        return send_file(path, mimetype="text/plain")
    return jerr("No log for that job.", 404)


@bp.route("/api/jobs/cancel-all", methods=["POST"])
def api_jobs_cancel_all():
    return jsonify({"ok": True, "cancelled": JOBS.cancel_all()})


@bp.route("/api/jobs/clear", methods=["POST"])
def api_jobs_clear():
    return jsonify({"ok": True, "removed": JOBS.clear_finished()})


@bp.route("/api/jobs/stream")
def api_jobs_stream():
    q = BUS.subscribe()

    @stream_with_context
    def gen():
        try:
            yield "retry: 2000\n\n"
            yield "data: %s\n\n" % json.dumps({"type": "hello", "jobs": JOBS.list(60)})
            while True:
                try:
                    ev = q.get(timeout=15)
                    yield "data: %s\n\n" % json.dumps(ev)
                except Empty:
                    yield ": ping\n\n"
        finally:
            BUS.unsubscribe(q)

    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@bp.route("/api/jobs/<jid>/stream")
def api_job_stream(jid):
    job = JOBS.get(jid)
    if not job:
        return jerr("Unknown job.", 404)
    q, snapshot = job.subscribe()

    @stream_with_context
    def gen():
        try:
            for entry in snapshot[-1500:]:
                yield "data: %s\n\n" % json.dumps(entry)
            while True:
                try:
                    entry = q.get(timeout=15)
                    yield "data: %s\n\n" % json.dumps(entry)
                except Empty:
                    if job.status not in ("queued", "running"):
                        yield "data: %s\n\n" % json.dumps({"t": "eof", "d": ""})
                        break
                    yield ": ping\n\n"
        finally:
            job.unsubscribe(q)

    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

