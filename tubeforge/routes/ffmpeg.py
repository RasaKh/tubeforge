import json
import os
import uuid

from flask import Blueprint, jsonify

from ..config import CONFIG, TMP_DIR, dl_dir, parse_time_to_seconds, resolve_path
from ..ffmpeg_compiler import (
    DIRECTORY_OPS,
    SEEK_OPS,
    _n,
    _stage,
    build_ffmpeg,
    encoder_capabilities,
    normalize_media_spec,
    preflight_ffmpeg,
)
from ..ffmpeg_registry import FF_OPS_INDEX
from ..jobs import JOBS, make_job
from ..probe import ffprobe_json, media_duration, summarize_probe
from . import body, cmd_string, jerr

bp = Blueprint("ffmpeg", __name__)


def effective_job_duration(spec, source_dur):
    """Compute actual output duration so FFmpeg progress percentage is accurate."""
    op = spec.get("op") or "transcode"
    params = spec.get("params") or {}
    if op in ("gif", "webp"):
        d = _n(params.get("duration"), 5)
        return d if d and d > 0 else source_dur
    if op in SEEK_OPS:
        seek = spec.get("seek") or {}
        ss = parse_time_to_seconds(seek.get("ss")) or 0.0
        t = parse_time_to_seconds(seek.get("t"))
        to = parse_time_to_seconds(seek.get("to"))
        if t is not None and t > 0:
            return min(t, max(0.1, (source_dur - ss))) if source_dur else t
        if to is not None and to > ss:
            return to - ss
        if ss > 0 and source_dur and source_dur > ss:
            return source_dur - ss
    if op == "speed" and source_dur:
        factor = _n(params.get("factor"), 1.0)
        if factor and factor > 0:
            return source_dur / factor
    if op == "cut_out" and source_dur:
        a = parse_time_to_seconds(params.get("start")) or 0.0
        b = parse_time_to_seconds(params.get("end")) or 0.0
        if b > a:
            return max(0.1, source_dur - (b - a))
    if op == "loop_clip" and source_dur:
        count = int(_n(params.get("count"), 3) or 3)
        return source_dur * max(1, count)
    return source_dur


def _ff_build(spec):
    result = build_ffmpeg(spec)
    dur = None
    ins = spec.get("inputs") or []
    if ins:
        try:
            dur = effective_job_duration(spec, media_duration(ins[0]))
        except Exception:
            dur = None
    return result, dur


@bp.route("/api/ffmpeg/preview", methods=["POST"])
def api_ffmpeg_preview():
    try:
        result, dur = _ff_build(body())
    except Exception as exc:
        return jerr(exc)
    return jsonify({"ok": True,
                    "stages": [{"label": s["label"], "cmd": cmd_string(s["argv"])}
                               for s in result["stages"]],
                    "notes": result["notes"], "outputs": result["outputs"],
                    "warnings": preflight_ffmpeg(body()),
                    "duration": dur, "effective": result.get("effective", {})})


@bp.route("/api/ffmpeg/settings", methods=["POST"])
def api_ffmpeg_settings():
    try:
        spec, notes = normalize_media_spec(body())
        enc = spec["enc"]
        probe_info = {}
        ins = spec.get("inputs") or []
        if ins and ins[0]:
            try:
                summary = summarize_probe(ffprobe_json(ins[0]))
                probe_info = {
                    "streams": summary.get("streams", []),
                    "duration": summary.get("duration"),
                    "chapters": summary.get("chapters", []),
                }
            except Exception:
                probe_info = {}
        return jsonify({"ok": True, "enc": enc, "params": spec["params"],
                        "output": spec["output"], "audio_only": spec["_audio_only"], "notes": notes,
                        "containers": spec["_containers"],
                        "audio_caps": encoder_capabilities(enc.get("acodec")),
                        "video_caps": encoder_capabilities(enc.get("vcodec")),
                        **probe_info})
    except Exception as exc:
        return jerr(exc)


@bp.route("/api/ffmpeg/run", methods=["POST"])
def api_ffmpeg_run():
    spec = body()
    warnings = preflight_ffmpeg(spec)
    blockers = [w for w in warnings if w["level"] == "block"]
    if blockers and not spec.get("ignore_warnings"):
        return jsonify({"ok": False, "blocked": True, "warnings": warnings,
                        "error": blockers[0]["text"]}), 409
    spec["_creating"] = True
    try:
        result, dur = _ff_build(spec)
    except Exception as exc:
        return jerr(exc)
    op = spec.get("op")
    label = FF_OPS_INDEX.get(op, {}).get("label", op)
    src = (spec.get("inputs") or [""])[0]
    title = "%s — %s" % (label, os.path.basename(src) if src else "")
    job = make_job("ffmpeg", title.strip(" —"), result["stages"], spec=spec,
                   meta={"duration": dur, "outputs": result["outputs"], "notes": result["notes"],
                         "cleanup": result.get("cleanup", [])})
    job.outputs = result["outputs"]
    JOBS.submit(job)
    return jsonify({"ok": True, "job": job.id,
                    "stages": [{"label": s["label"], "cmd": cmd_string(s["argv"])}
                               for s in result["stages"]],
                    "notes": result["notes"], "warnings": warnings})


@bp.route("/api/probe", methods=["POST"])
def api_probe():
    data = body()
    try:
        raw = ffprobe_json(data.get("path"), use_cache=not data.get("fresh"))
    except Exception as exc:
        return jerr(exc)
    return jsonify({"ok": True, "summary": summarize_probe(raw),
                    "raw": raw if data.get("raw") else None})


# ── Pipelines (chained ffmpeg operations, one job, many stages) ─────────────

@bp.route("/api/pipeline/preview", methods=["POST"])
def api_pipeline_preview():
    try:
        stages, notes, outs, _temps = _compile_pipeline(body())
    except Exception as exc:
        return jerr(exc)
    return jsonify({"ok": True,
                    "stages": [{"label": s["label"], "cmd": cmd_string(s["argv"])} for s in stages],
                    "notes": notes, "outputs": outs})


def _compile_pipeline(spec):
    source = spec.get("input")
    steps = spec.get("steps") or []
    if not source:
        raise ValueError("Choose a source file for the pipeline.")
    if not steps:
        raise ValueError("Add at least one step.")
    final_out = (spec.get("output") or "").strip() or "pipeline_output.mp4"
    all_stages, notes, outs = [], [], []
    current = source
    temps = []
    for i, step in enumerate(steps):
        operation = step.get("op", "transcode")
        if operation in DIRECTORY_OPS or FF_OPS_INDEX.get(operation, {}).get("out") is False:
            raise ValueError("Pipeline steps must produce one media file; %s does not." % operation)
        last = (i == len(steps) - 1)
        ext = os.path.splitext(final_out)[1] or ".mkv"
        if last:
            target = final_out
        else:
            target = os.path.join(TMP_DIR, "pipe_%s_%02d%s" % (uuid.uuid4().hex[:6], i, ext))
            temps.append(target)
        sub = dict(step)
        ins = [current] + [x for x in (step.get("extra_inputs") or []) if str(x).strip()]
        sub["inputs"] = ins
        sub["output"] = target
        if i > 0:
            sub["allow_missing_inputs"] = True
        sub["_creating"] = bool(spec.get("_creating"))
        sub["output_mode"] = "manual"
        if i > 0:
            # The intermediate must exist before its streams can be inspected.
            # Compile this step in the worker after the previous one finishes.
            all_stages.append(_stage("step %d · %s (planned after input is ready)" % (i + 1, step.get("op", "transcode")),
                                     [CONFIG["ffmpeg_bin"], "-i", current, target],
                                     deferred_spec=sub, pipeline_final=last))
            current = target
            continue
        built = build_ffmpeg(sub)
        if len(built["outputs"]) != 1 or step.get("op") in DIRECTORY_OPS:
            raise ValueError("Each pipeline step must produce exactly one media file.")
        target = built["outputs"][0]
        temps.extend(built.get("cleanup", []))
        if not last:
            temps.append(target)
        for st in built["stages"]:
            st = dict(st)
            st["label"] = "step %d · %s" % (i + 1, st["label"])
            all_stages.append(st)
        all_stages[-1]["pipeline_output"] = target
        all_stages[-1]["pipeline_final"] = last
        notes += built["notes"]
        current = target
    outs.append(current)
    if temps:
        notes.append("%d intermediate file(s) are written to %s and removed when the "
                     "pipeline finishes." % (len(temps), TMP_DIR))
    if len(steps) > 1:
        notes.append("Later steps are compiled and their output extensions rechecked after the preceding file exists.")
    return all_stages, notes, outs, temps


@bp.route("/api/pipeline/run", methods=["POST"])
def api_pipeline_run():
    spec = body()
    spec["_creating"] = True
    try:
        stages, notes, outs, temps = _compile_pipeline(spec)
        dur = media_duration(spec.get("input"))
    except Exception as exc:
        return jerr(exc)
    job = make_job("ffmpeg", "pipeline · %s" % os.path.basename(str(spec.get("input"))),
                   stages, spec=spec, meta={"duration": dur, "outputs": outs, "notes": notes,
                                            "cleanup": temps})
    job.outputs = outs
    JOBS.submit(job)
    return jsonify({"ok": True, "job": job.id})


# ── Batch (same operation applied to many files) ───────────────────────────

@bp.route("/api/batch/run", methods=["POST"])
def api_batch_run():
    spec = body()
    files = [f for f in (spec.get("files") or []) if str(f).strip()]
    if not files:
        return jerr("Select at least one file.")
    template = spec.get("op_spec") or {}
    pattern = (spec.get("out_pattern") or "{stem}_out{ext}").strip()
    outdir = (spec.get("out_dir") or "").strip()
    created, errors = [], []
    for f in files:
        try:
            real = resolve_path(f, must_exist=True)
            stem, ext = os.path.splitext(os.path.basename(real))
            name = (pattern.replace("{stem}", stem)
                           .replace("{ext}", ext)
                           .replace("{name}", os.path.basename(real))
                           .replace("{parent}", os.path.basename(os.path.dirname(real))))
            if (sub.get("op") or template.get("op")) in DIRECTORY_OPS:
                target = os.path.join(outdir or os.path.dirname(real), stem + "_parts")
            else:
                target = os.path.join(outdir, name) if outdir else os.path.join(
                    os.path.dirname(real), name)
            sub = json.loads(json.dumps(template))
            extra = [x for x in (sub.get("inputs") or [])[1:]]
            sub["inputs"] = [real] + extra
            sub["output"] = target
            sub["output_mode"] = "manual"
            sub["_creating"] = True
            result = build_ffmpeg(sub)
            job = make_job("ffmpeg", "batch · %s" % os.path.basename(real), result["stages"],
                           spec=sub, meta={"duration": media_duration(real),
                                           "outputs": result["outputs"], "cleanup": result.get("cleanup", [])})
            job.outputs = result["outputs"]
            JOBS.submit(job)
            created.append(job.id)
        except Exception as exc:
            errors.append("%s: %s" % (os.path.basename(str(f)), exc))
    return jsonify({"ok": True, "jobs": created, "errors": errors})


