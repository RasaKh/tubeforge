from datetime import datetime
import hashlib
import json
import mimetypes
import os
import shutil
import subprocess
import sys

from flask import Blueprint, Response, jsonify, request, send_file

from ..config import CONFIG, PathError, TMP_DIR, allowed_roots, dl_dir, human_size, resolve_path
from ..ffmpeg_registry import compile_filterchain
from . import body, jerr

bp = Blueprint("files", __name__)


MEDIA_EXT = {
    "video": {".mp4", ".mkv", ".webm", ".mov", ".avi", ".flv", ".ts", ".m4v", ".wmv", ".mpg", ".mpeg", ".3gp"},
    "audio": {".mp3", ".m4a", ".aac", ".flac", ".wav", ".opus", ".ogg", ".wma", ".alac", ".aiff"},
    "image": {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".avif"},
    "subtitle": {".srt", ".vtt", ".ass", ".ssa", ".sub", ".lrc"},
    "data": {".json", ".txt", ".info", ".description", ".nfo", ".xml", ".cube"},
}


# Files that are still being written, or leftovers from an interrupted run.
# They have no usable stream yet, so no tool should be pointed at them.
PARTIAL_EXT = {".part", ".ytdl", ".tmp", ".temp", ".download", ".crdownload", ".!qb"}

# Text formats we can show inline but cannot decode as media.
TEXT_KINDS = {"subtitle", "data"}


def classify(name):
    ext = os.path.splitext(name)[1].lower()
    for kind, exts in MEDIA_EXT.items():
        if ext in exts:
            return kind
    return "other"


def capabilities(name):
    """What this file can actually be used for. Drives which buttons appear,
    so the interface never offers an action that is bound to fail."""
    lower = name.lower()
    ext = os.path.splitext(lower)[1]
    # yt-dlp writes things like "video.f137.mp4.part"; the real extension is
    # buried, but the file is incomplete either way.
    partial = ext in PARTIAL_EXT or ".part" in lower or lower.endswith(".ytdl")
    kind = classify(name)
    if partial:
        return {"partial": True, "preview": False, "probe": False,
                "process": False, "text": False}
    decodable = kind in ("video", "audio", "image")
    return {
        "partial": False,
        "preview": decodable or kind in TEXT_KINDS,
        "probe": decodable,
        "process": decodable,
        "text": kind in TEXT_KINDS,
    }


@bp.route("/api/files")
def api_files():
    rel = request.args.get("dir", "")
    recursive = request.args.get("recursive") == "1"
    query = (request.args.get("q") or "").lower()
    kinds = set(filter(None, (request.args.get("kind") or "").split(",")))
    try:
        base = resolve_path(rel or dl_dir())
    except PathError as exc:
        return jerr(exc)
    if not os.path.isdir(base):
        return jerr("Not a folder: %s" % base)

    dirs, files = [], []
    if recursive:
        walker = ((dp, [], fs) for dp, _, fs in os.walk(base))
    else:
        try:
            names = os.listdir(base)
        except OSError as exc:
            return jerr(exc)
        walker = [(base, [n for n in names if os.path.isdir(os.path.join(base, n))],
                   [n for n in names if os.path.isfile(os.path.join(base, n))])]
    count = 0
    for dp, dns, fns in walker:
        for d in sorted(dns):
            p = os.path.join(dp, d)
            try:
                dirs.append({"name": d, "path": p, "mtime": os.path.getmtime(p),
                             "entries": len(os.listdir(p))})
            except OSError:
                pass
        for f in sorted(fns):
            p = os.path.join(dp, f)
            kind = classify(f)
            if kinds and kind not in kinds:
                continue
            if query and query not in f.lower():
                continue
            try:
                st = os.stat(p)
            except OSError:
                continue
            files.append({"name": f, "path": p, "rel": os.path.relpath(p, base),
                          "size": st.st_size, "size_h": human_size(st.st_size),
                          "mtime": st.st_mtime,
                          "mtime_h": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                          "kind": kind, "ext": os.path.splitext(f)[1].lower().lstrip("."),
                          "caps": capabilities(f)})
            count += 1
            if count > 4000:
                break
        if count > 4000:
            break

    parent = os.path.dirname(base)
    return jsonify({"ok": True, "base": base, "parent": parent if base != "/" else None,
                    "dirs": dirs, "files": files,
                    "roots": allowed_roots(), "download_dir": dl_dir()})


@bp.route("/api/files/download")
def api_file_download():
    try:
        p = resolve_path(request.args.get("path"), must_exist=True)
    except PathError as exc:
        return jerr(exc)
    return send_file(p, as_attachment=True, download_name=os.path.basename(p))


@bp.route("/api/files/delete", methods=["POST"])
def api_file_delete():
    data = body()
    paths = data.get("paths") or ([data.get("path")] if data.get("path") else [])
    removed, errors = 0, []
    for raw in paths:
        try:
            lexical = os.path.abspath(os.path.expanduser(str(raw)) if os.path.isabs(os.path.expanduser(str(raw))) else os.path.join(dl_dir(), str(raw)))
            resolve_path(os.path.dirname(lexical), must_exist=True)
            if os.path.islink(lexical):
                os.unlink(lexical)
                removed += 1
                continue
            p = resolve_path(raw, must_exist=True)
            if p in allowed_roots():
                raise PathError("Cannot delete an allowed root folder.")
            if os.path.isdir(p):
                shutil.rmtree(p)
            else:
                os.remove(p)
            removed += 1
        except Exception as exc:
            errors.append(str(exc))
    return jsonify({"ok": not errors, "removed": removed, "errors": errors})


@bp.route("/api/files/rename", methods=["POST"])
def api_file_rename():
    data = body()
    try:
        src = resolve_path(data.get("path"), must_exist=True)
        newname = (data.get("name") or "").strip()
        if not newname or "/" in newname:
            return jerr("Give a plain file name.")
        dst = resolve_path(os.path.join(os.path.dirname(src), newname), for_output=True)
        if os.path.exists(dst):
            return jerr("A file with that name already exists.")
        os.rename(src, dst)
    except Exception as exc:
        return jerr(exc)
    return jsonify({"ok": True, "path": dst})


@bp.route("/api/files/move", methods=["POST"])
def api_file_move():
    data = body()
    errors, moved = [], 0
    try:
        dest = resolve_path(data.get("dest"), for_output=True)
        os.makedirs(dest, exist_ok=True)
    except Exception as exc:
        return jerr(exc)
    for raw in data.get("paths") or []:
        try:
            src = resolve_path(raw, must_exist=True)
            target = os.path.join(dest, os.path.basename(src))
            if os.path.lexists(target):
                raise PathError("Destination already exists: %s" % target)
            shutil.move(src, target)
            moved += 1
        except Exception as exc:
            errors.append(str(exc))
    return jsonify({"ok": not errors, "moved": moved, "errors": errors})


@bp.route("/api/files/mkdir", methods=["POST"])
def api_file_mkdir():
    data = body()
    try:
        p = resolve_path(os.path.join(data.get("dir") or dl_dir(), data.get("name") or "new folder"),
                         for_output=True)
        os.makedirs(p, exist_ok=True)
    except Exception as exc:
        return jerr(exc)
    return jsonify({"ok": True, "path": p})


@bp.route("/api/browse", methods=["POST"])
def api_browse():
    data = body()
    mode = data.get("mode") or "file"
    if mode not in ("file", "files", "dir", "save"):
        return jerr("Invalid browse mode.")
    title = str(data.get("title") or "Select")[:120]
    initial = (data.get("initial") or "").strip()
    start_dir = dl_dir()
    if initial:
        expanded = os.path.expanduser(initial)
        if os.path.isdir(expanded):
            start_dir = expanded
        elif os.path.isdir(os.path.dirname(expanded)):
            start_dir = os.path.dirname(expanded)

    def _in_sandbox(p):
        real = os.path.realpath(p)
        return any(real == r or real.startswith(r + os.sep) for r in allowed_roots())

    def _result(paths):
        paths = [os.path.abspath(p) for p in paths if p and p.strip()]
        if not paths:
            return jsonify({"ok": True, "cancelled": True})
        first = paths[0]
        outside = (mode != "dir") and CONFIG.get("sandbox_paths", True) and not _in_sandbox(first)
        return jsonify({
            "ok": True,
            "path": first,
            "paths": paths,
            "outside_sandbox": outside,
            "parent": os.path.dirname(first),
        })

    # Linux desktop: zenity -> kdialog -> tkinter
    if sys.platform.startswith("linux"):
        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            return jsonify({"ok": False, "headless": True})
        zen = shutil.which("zenity")
        if zen:
            cmd = [zen, "--file-selection", "--title", title, "--filename", start_dir.rstrip("/") + "/"]
            if mode == "files":
                cmd += ["--multiple", "--separator=\n"]
            elif mode == "dir":
                cmd += ["--directory"]
            elif mode == "save":
                cmd += ["--save", "--confirm-overwrite"]
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
                if res.returncode == 0:
                    return _result(res.stdout.strip().splitlines())
                return jsonify({"ok": True, "cancelled": True})
            except Exception:
                pass
        kd = shutil.which("kdialog")
        if kd:
            flag = {"file": "--getopenfilename", "files": "--getopenfilename",
                    "dir": "--getexistingdirectory", "save": "--getsavefilename"}[mode]
            cmd = [kd, flag, start_dir, "--title", title]
            if mode == "files":
                cmd += ["--multiple", "--separate-output"]
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
                if res.returncode == 0:
                    return _result(res.stdout.strip().splitlines())
                return jsonify({"ok": True, "cancelled": True})
            except Exception:
                pass

    # macOS native osascript
    if sys.platform == "darwin":
        if mode == "dir":
            script = f'POSIX path of (choose folder with prompt {json.dumps(title)} default location POSIX file {json.dumps(start_dir)})'
        elif mode == "save":
            script = f'POSIX path of (choose file name with prompt {json.dumps(title)} default location POSIX file {json.dumps(start_dir)})'
        elif mode == "files":
            script = f'set fs to (choose file with prompt {json.dumps(title)} default location POSIX file {json.dumps(start_dir)} with multiple selections allowed)\nset out to ""\nrepeat with f in fs\nset out to out & POSIX path of f & linefeed\nend repeat\nout'
        else:
            script = f'POSIX path of (choose file with prompt {json.dumps(title)} default location POSIX file {json.dumps(start_dir)})'
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=180)
            if res.returncode == 0:
                return _result(res.stdout.strip().splitlines())
            return jsonify({"ok": True, "cancelled": True})
        except Exception:
            return jsonify({"ok": False, "headless": True})

    # Fallback: tkinter.filedialog in a subprocess (works on Windows and Linux with python3-tk)
    tk_script = (
        "import json, sys, tkinter as tk; from tkinter import filedialog as fd; "
        "r = tk.Tk(); r.withdraw(); r.attributes('-topmost', True); "
        "mode, start, title = sys.argv[1], sys.argv[2], sys.argv[3]; "
        "res = (fd.askdirectory(initialdir=start, title=title) if mode=='dir' "
        "else fd.asksaveasfilename(initialdir=start, title=title) if mode=='save' "
        "else list(fd.askopenfilenames(initialdir=start, title=title)) if mode=='files' "
        "else fd.askopenfilename(initialdir=start, title=title)); "
        "print(json.dumps(res if isinstance(res, list) else ([res] if res else [])))"
    )
    try:
        res = subprocess.run([sys.executable, "-c", tk_script, mode, start_dir, title],
                             capture_output=True, text=True, timeout=180)
        if res.returncode == 0 and res.stdout.strip():
            return _result(json.loads(res.stdout.strip()))
    except Exception:
        pass
    return jsonify({"ok": False, "headless": True})


@bp.route("/api/files/read")
def api_file_read():
    try:
        p = resolve_path(request.args.get("path"), must_exist=True)
    except PathError as exc:
        return jerr(exc)
    if os.path.getsize(p) > 4 * 1024 * 1024:
        return jerr("That file is too large to show inline.")
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as fh:
            return jsonify({"ok": True, "text": fh.read()})
    except Exception as exc:
        return jerr(exc)


# ── Media streaming (with Range support so seeking works) ──────────────────

@bp.route("/api/media")
def api_media():
    try:
        p = resolve_path(request.args.get("path"), must_exist=True)
    except PathError as exc:
        return jerr(exc)
    if not os.path.isfile(p):
        return jerr("Choose a regular file.")
    return send_file(p, mimetype=mimetypes.guess_type(p)[0] or "application/octet-stream", conditional=True)


@bp.route("/api/thumb")
def api_thumb():
    try:
        p = resolve_path(request.args.get("path"), must_exist=True)
    except PathError as exc:
        return jerr(exc)
    at = request.args.get("t", "5")
    vf_raw = (request.args.get("vf") or "").strip()
    vf_compiled = ""
    if vf_raw:
        try:
            entries = json.loads(vf_raw)
            if not isinstance(entries, list):
                return jerr("Invalid filter chain.")
            vf_compiled = compile_filterchain(entries, "video")
        except (ValueError, PathError) as exc:
            return jerr(exc)
    kind = classify(p)
    if kind == "image" and not vf_compiled:
        return send_file(p)
    st = os.stat(p)
    key = hashlib.sha256(("%s|%s|%s|%s|%s" % (p, st.st_mtime_ns, st.st_size, at, vf_compiled)).encode()).hexdigest()
    cache = os.path.join(TMP_DIR, "thumb_" + key + ".jpg")
    if not os.path.exists(cache):
        vf_arg = ",".join(filter(None, [vf_compiled, "scale=480:-1"]))
        cmd = [CONFIG["ffmpeg_bin"], "-hide_banner", "-loglevel", "error", "-y"]
        if kind != "image":
            cmd += ["-ss", str(at)]
        cmd += ["-i", p, "-frames:v", "1", "-vf", vf_arg, "-q:v", "4", cache]
        try:
            subprocess.run(cmd, capture_output=True, timeout=45)
        except Exception:
            pass
    if os.path.exists(cache) and os.path.getsize(cache) > 0:
        return send_file(cache, mimetype="image/jpeg")
    return jerr("No thumbnail available.", 404)

