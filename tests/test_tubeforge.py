import collections
import json
import os
import subprocess
import pytest

from tubeforge import create_app
from tubeforge.config import CONFIG, PathError, dl_dir, update_config
from tubeforge.ffmpeg_compiler import DIRECTORY_OPS, build_ffmpeg, normalize_media_spec
from tubeforge.ffmpeg_registry import compile_filter
from tubeforge.jobs import JOBS, make_job
from tubeforge.probe import _probe_cache, ffprobe_json
from tubeforge.routes.ffmpeg import effective_job_duration
from tubeforge.ytdlp_compiler import YTDLP_INDEX, build_ytdlp


@pytest.fixture()
def app(tmp_path):
    orig_dir = CONFIG["download_dir"]
    orig_raw = CONFIG.get("allow_raw_ffmpeg", False)
    orig_auth = CONFIG.get("auth_enabled", False)
    orig_hash = CONFIG.get("auth_token_hash", "")
    orig_sec = CONFIG.get("auth_cookie_secure", "auto")
    dl = tmp_path / "dl"
    dl.mkdir()
    update_config(dict(CONFIG, download_dir=str(dl), allow_raw_ffmpeg=False,
                       auth_enabled=False, auth_token_hash="", auth_cookie_secure="auto"))
    yield create_app()
    update_config(dict(CONFIG, download_dir=orig_dir, allow_raw_ffmpeg=orig_raw,
                       auth_enabled=orig_auth, auth_token_hash=orig_hash, auth_cookie_secure=orig_sec))


@pytest.fixture()
def client(app):
    return app.test_client()


def test_part1_ytdlp_ignore_config_and_no_exec_or_config_location():
    assert "config_location" not in YTDLP_INDEX
    assert "ignore_config" not in YTDLP_INDEX
    assert "exec_cmd" not in YTDLP_INDEX
    argv = build_ytdlp({"urls": ["https://example.com/v"], "opts": {}})
    assert argv[1] == "--ignore-config"
    with pytest.raises(ValueError):
        build_ytdlp({"urls": ["https://example.com/v"], "raw": "--exec whoami"})


def test_part1_ffmpeg_sandbox_blocks_raw_and_dangerous_extra(app, tmp_path):
    media = tmp_path / "dl" / "a.mp4"
    # Create valid dummy media using ffmpeg
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=64x64:d=1",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "1", str(media)
    ], check=True, capture_output=True)

    with pytest.raises(ValueError):
        build_ffmpeg({"op": "freeform", "params": {"line": "-i /etc/passwd"}})
    with pytest.raises(ValueError):
        build_ffmpeg({"op": "custom", "inputs": [str(media)], "params": {"post": "-y"}, "output": str(tmp_path / "dl" / "out.mp4")})
    with pytest.raises(ValueError):
        build_ffmpeg({"op": "transcode", "inputs": [str(media)], "extra_pre": "-i /etc/passwd", "output": str(tmp_path / "dl" / "out.mp4")})
    with pytest.raises(ValueError):
        build_ffmpeg({"op": "transcode", "inputs": [str(media)], "enc": {"extra_out": "/tmp/evil.mp4"}, "output": str(tmp_path / "dl" / "out.mp4")})

    # Filter file path validation
    with pytest.raises(PathError):
        compile_filter({"id": "lut3d", "params": {"file": "/etc/passwd"}})
    with pytest.raises(PathError):
        compile_filter({"id": "subtitles", "params": {"filename": "/etc/passwd"}})


def test_part1_compile_filter_positional():
    assert compile_filter({"id": "atempo", "params": {"tempo": "1.25"}}) == "atempo=1.25"
    assert compile_filter({"id": "scale", "params": {"w": "-2", "h": "720", "flags": "lanczos"}}) == "scale=-2:720:flags=lanczos"
    # If first positional arg is omitted, remaining positional args become named
    assert compile_filter({"id": "scale", "params": {"w": "", "h": "720"}}) == "scale=h=720"


def test_part1_csrf_empty_post_requires_json(client):
    r = client.post("/api/jobs/clear")
    assert r.status_code == 415
    r2 = client.post("/api/jobs/clear", json={})
    assert r2.status_code == 200


def test_part1_auth_cookie_auto_http(client):
    import hashlib
    update_config(dict(CONFIG, auth_enabled=True, auth_token_hash=hashlib.sha256(b"secret").hexdigest(), auth_cookie_secure="auto"))
    r = client.post("/api/auth/login", json={"token": "secret"})
    assert r.status_code == 200
    cookie = r.headers.get("Set-Cookie", "")
    assert "tubeforge_session=" in cookie
    assert "Secure" not in cookie


def test_part1_effective_job_duration():
    assert effective_job_duration({"op": "gif", "params": {"duration": "4"}}, 3600.0) == 4.0
    assert effective_job_duration({"op": "trim", "seek": {"ss": "10", "t": "15"}}, 3600.0) == 15.0
    assert effective_job_duration({"op": "trim", "seek": {"ss": "10", "to": "25"}}, 3600.0) == 15.0
    assert effective_job_duration({"op": "speed", "params": {"factor": "2"}}, 100.0) == 50.0
    assert effective_job_duration({"op": "cut_out", "params": {"start": "10", "end": "30"}}, 100.0) == 80.0
    assert effective_job_duration({"op": "loop_clip", "params": {"count": "3"}}, 10.0) == 30.0


def test_part1_ffmpeg_ops_edge_cases(app, tmp_path):
    dl = tmp_path / "dl"
    aud = dl / "only.mp3"
    vid = dl / "v.mp4"
    sub = dl / "s.srt"
    sub.write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n")
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "1", str(aud)], check=True, capture_output=True)
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=64x64:d=1", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "1", str(vid)], check=True, capture_output=True)

    # loudnorm2 on audio-only
    res = build_ffmpeg({"op": "loudnorm2", "inputs": [str(aud)], "output": str(dl / "norm.mp3"), "enc": {"acodec": "libmp3lame"}})
    assert "-c:v" not in res["stages"][1]["argv"]

    # reverse on audio-only
    res_rev = build_ffmpeg({"op": "reverse", "inputs": [str(aud)], "output": str(dl / "rev.mp3")})
    assert "-vf" not in res_rev["stages"][0]["argv"]
    assert "-af" in res_rev["stages"][0]["argv"]

    # concat filter on audio-only raises ValueError, not StopIteration
    with pytest.raises(ValueError, match="Filter concat requires video streams"):
        build_ffmpeg({"op": "concat", "inputs": [str(aud), str(aud)], "params": {"mode": "filter"}, "output": str(dl / "cat.mp4")})

    # add_subs soft maps 1:s:0
    res_sub = build_ffmpeg({"op": "add_subs", "inputs": [str(vid), str(sub)], "params": {"mode": "soft"}, "output": str(dl / "sub.mkv")})
    argv = res_sub["stages"][0]["argv"]
    assert "1:s:0" in argv


def test_part1_job_cancel_queued_removes_from_pending():
    j = make_job("ytdlp", "test", [{"label": "dl", "argv": ["yt-dlp", "--version"]}])
    with JOBS.lock:
        JOBS.jobs[j.id] = j
        JOBS.pending.append(j)
    j.cancel()
    assert j.status == "cancelled"
    assert j not in JOBS.pending


def test_part1_probe_cache_is_lru():
    assert isinstance(_probe_cache, collections.OrderedDict)


def test_part2_settings_returns_streams_and_silent_auto_container(client, tmp_path):
    vid = tmp_path / "dl" / "clip.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=red:s=64x64:d=2", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "2", str(vid)], check=True, capture_output=True)
    r = client.post("/api/ffmpeg/settings", json={"op": "transcode", "inputs": [str(vid)], "output_mode": "auto"})
    assert r.status_code == 200
    data = r.get_json()
    assert data["ok"] is True
    assert len(data["streams"]) >= 2
    assert data["duration"] is not None


def test_part2_thumb_with_vf_and_snippets_and_history_delete(client, tmp_path):
    vid = tmp_path / "dl" / "thumb.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=green:s=128x128:d=2", "-t", "2", str(vid)], check=True, capture_output=True)
    vf = json.dumps([{"id": "hflip", "params": {}, "enabled": True}])
    r = client.get(f"/api/thumb?path={vid}&t=0.5&vf={vf}")
    assert r.status_code == 200
    assert r.mimetype == "image/jpeg"

    # Snippets CRUD
    rs = client.post("/api/snippets", json={"name": "test", "command": "ffmpeg -version"})
    assert rs.status_code == 200
    rl = client.get("/api/snippets").get_json()["snippets"]
    assert any(s["name"] == "test" for s in rl)

    # Disk endpoint
    rd = client.get("/api/disk")
    assert rd.status_code == 200
    assert rd.get_json()["ok"] is True


def test_browse_endpoint_headless_and_invalid_mode(client, monkeypatch):
    r_bad = client.post("/api/browse", json={"mode": "invalid"})
    assert r_bad.status_code == 400

    # Simulate headless Linux (no DISPLAY/WAYLAND_DISPLAY)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    r_hl = client.post("/api/browse", json={"mode": "file"})
    assert r_hl.status_code == 200
    data = r_hl.get_json()
    assert data["ok"] is False
    assert data["headless"] is True
