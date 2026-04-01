import json
import os
import re
import shlex
import signal
import subprocess
import threading
import time
import uuid
from collections import deque
from queue import Empty, Queue

from .config import CONFIG, LOG_DIR, PathError, dl_dir, human_size, human_time, resolve_path
from .db import db_exec, db_query
from .ffmpeg_compiler import DIRECTORY_OPS, _n, build_ffmpeg
from .probe import ALLOWED_BINARIES, media_duration
from .ytdlp_compiler import PROGRESS_SENTINEL

# ═══════════════════════════════════════════════════════════════════════════
#  JOB MANAGER
#  Every command runs as a Job. Jobs have ordered stages, a live log ring
#  buffer, structured progress, cancellation, and SQLite-backed history.
# ═══════════════════════════════════════════════════════════════════════════

LOG_RING = 4000          # lines kept in memory per job
BUS_RING = 300           # recent global events replayed to new listeners

PCT_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")
LOUDNORM_RE = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.S)


class EventBus:
    """Fan-out of job state changes to any number of SSE listeners."""

    def __init__(self):
        self._subs = []
        self._lock = threading.Lock()
        self._recent = deque(maxlen=BUS_RING)

    def publish(self, event):
        with self._lock:
            self._recent.append(event)
            dead = []
            for q in self._subs:
                try:
                    q.put_nowait(event)
                except Exception:
                    dead.append(q)
            for q in dead:
                self._subs.remove(q)

    def subscribe(self):
        q = Queue(maxsize=2000)
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)


BUS = EventBus()


class Job:
    def __init__(self, kind, title, stages, cwd=None, spec=None, meta=None):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind                      # 'ytdlp' | 'ffmpeg' | 'shell'
        self.title = title or kind
        self.stages = stages                  # [{'label','argv', optional 'cwd'}]
        self.cwd = cwd or dl_dir()
        self.spec = spec or {}
        self.meta = meta or {}
        self.status = "queued"                # queued|running|done|error|cancelled
        self.rc = None
        self.created = time.time()
        self.started = None
        self.finished = None
        self.stage_index = 0
        self.progress = {"pct": 0, "stage": 0, "stages": len(stages),
                         "speed": "", "eta": "", "status": "", "line": ""}
        self.log = deque(maxlen=LOG_RING)
        self.log_path = os.path.join(LOG_DIR, "%s.log" % self.id)
        self.proc = None
        self.cancel_requested = False
        self._subs = []
        self._lock = threading.Lock()
        self._captured = {}
        self.outputs = list((meta or {}).get("outputs") or [])

    # ---- log plumbing -------------------------------------------------
    def emit(self, stream, text):
        entry = {"t": stream, "d": text}
        with self._lock:
            self.log.append(entry)
            dead = []
            for q in list(self._subs):
                try:
                    q.put_nowait(entry)
                except Exception:
                    dead.append(q)
            for q in dead:
                self._subs.remove(q)
        try:
            with open(self.log_path, "a", encoding="utf-8", errors="replace") as fh:
                fh.write(text if text.endswith("\n") else text + "\n")
        except Exception:
            pass

    def subscribe(self):
        q = Queue(maxsize=4000)
        with self._lock:
            snapshot = list(self.log)
            self._subs.append(q)
        return q, snapshot

    def unsubscribe(self, q):
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    # ---- serialisation ------------------------------------------------
    def brief(self):
        return {
            "id": self.id, "kind": self.kind, "title": self.title,
            "status": self.status, "rc": self.rc,
            "created": self.created, "started": self.started, "finished": self.finished,
            "progress": self.progress,
            "stages": [s["label"] for s in self.stages],
            "stage_index": self.stage_index,
            "cmd": " ".join(shlex.quote(a) for a in self.stages[self.stage_index]["argv"])
                   if self.stages and self.stage_index < len(self.stages) else "",
            "all_cmds": [" ".join(shlex.quote(a) for a in s["argv"]) for s in self.stages],
            "outputs": self.outputs,
            "duration": (self.finished or time.time()) - (self.started or self.created),
            "meta": {k: v for k, v in self.meta.items() if k not in ("spec",)},
        }

    def push_state(self):
        BUS.publish({"type": "job", "job": self.brief()})
        self.persist()

    def persist(self):
        try:
            db_exec(
                "INSERT OR REPLACE INTO jobs"
                "(id,kind,title,cmd,cwd,status,rc,created,started,finished,spec,meta)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (self.id, self.kind, self.title,
                 json.dumps([s["argv"] for s in self.stages]), self.cwd,
                 self.status, self.rc, self.created, self.started, self.finished,
                 json.dumps(self.spec)[:200000], json.dumps({"outputs": self.outputs,
                                                             "meta": self.meta})[:100000]))
        except Exception:
            pass

    # ---- progress parsing ---------------------------------------------
    def _parse_ytdlp(self, line):
        if PROGRESS_SENTINEL not in line:
            return False
        payload = line.split(PROGRESS_SENTINEL, 1)[1].strip()
        bits = payload.split("|")
        while len(bits) < 7:
            bits.append("")
        status, pct, speed, eta, got, total, title = bits[:7]
        m = PCT_RE.search(pct)
        self.progress.update({
            "pct": float(m.group(1)) if m else self.progress.get("pct", 0),
            "speed": speed.strip(), "eta": eta.strip(),
            "status": status.strip(), "got": got.strip(), "total": total.strip(),
            "line": ("%s  %s  ETA %s" % (pct.strip(), speed.strip(), eta.strip())).strip(),
        })
        if title.strip() and title.strip() != "NA":
            clean_title = title.strip()[:120]
            self.progress["item"] = clean_title
            urls = (self.spec or {}).get("urls") or []
            if len(urls) == 1 and not self.meta.get("_title_backfilled"):
                self.meta["_title_backfilled"] = True
                try:
                    db_exec("UPDATE url_history SET title=? WHERE url=? AND (title IS NULL OR title='')",
                            (title.strip()[:200], urls[0]))
                except Exception:
                    pass
        return True

    def _parse_ffmpeg(self, line):
        if "=" not in line:
            return False
        k, _, v = line.strip().partition("=")
        k, v = k.strip(), v.strip()
        if k not in ("out_time_us", "out_time_ms", "out_time", "speed", "frame", "fps",
                     "bitrate", "total_size", "progress"):
            return False
        dur = self.meta.get("duration")
        if k in ("out_time_us", "out_time_ms") and dur:
            try:
                secs = float(v) / 1000000.0
                base = (self.stage_index / max(1, len(self.stages))) * 100.0
                span = 100.0 / max(1, len(self.stages))
                self.progress["pct"] = min(100.0, base + min(1.0, secs / dur) * span)
                self.progress["line"] = "%s / %s" % (human_time(secs), human_time(dur))
            except (ValueError, ZeroDivisionError):
                pass
        elif k == "out_time":
            self.progress["line"] = v
        elif k == "speed":
            self.progress["speed"] = v
        elif k == "frame":
            self.progress["frame"] = v
        elif k == "fps":
            self.progress["fps"] = v
        elif k == "total_size":
            self.progress["got"] = human_size(_n(v))
        return True

    # ---- execution ----------------------------------------------------
    def run(self):
        self.status = "running"
        self.started = time.time()
        self.push_state()
        try:
            idx = 0
            while idx < len(self.stages):
                if self.cancel_requested:
                    raise KeyboardInterrupt()
                stage = self.stages[idx]
                if stage.get("deferred_spec"):
                    sub = dict(stage["deferred_spec"], _creating=True, allow_missing_inputs=False)
                    sub["inputs"] = [self._pipeline_current] + list(sub["inputs"])[1:]
                    built = build_ffmpeg(sub)
                    if len(built["outputs"]) != 1 or sub.get("op") in DIRECTORY_OPS:
                        raise ValueError("A pipeline step must produce one media file.")
                    expanded = [dict(s, label=stage["label"] + " / " + s["label"]) for s in built["stages"]]
                    expanded[-1]["pipeline_output"] = built["outputs"][0]
                    expanded[-1]["pipeline_final"] = stage.get("pipeline_final", False)
                    self.meta.setdefault("cleanup", []).extend(built.get("cleanup", []))
                    if not stage.get("pipeline_final"):
                        self.meta["cleanup"].append(built["outputs"][0])
                    self.stages[idx:idx + 1] = expanded
                    self.progress["stages"] = len(self.stages)
                    stage = self.stages[idx]
                self.stage_index = idx
                self.progress["stage"] = idx
                argv = self._prepare_stage(stage)
                self.emit("meta", "\n\u2500\u2500 [%d/%d] %s \u2500\u2500\n$ %s\n" % (
                    idx + 1, len(self.stages), stage.get("label", "stage"),
                    " ".join(shlex.quote(a) for a in argv)))
                rc, captured = self._run_one(argv, stage)
                self.rc = rc
                if stage.get("capture"):
                    self._captured[stage["capture"]] = captured
                if rc != 0:
                    if self.cancel_requested:
                        raise KeyboardInterrupt()
                    self.status = "error"
                    self.emit("stderr", "\n\u2717 stage failed with exit code %s\n" % rc)
                    break
                if stage.get("pipeline_output"):
                    self._pipeline_current = stage["pipeline_output"]
                    if stage.get("pipeline_final"):
                        self.outputs = [self._pipeline_current]
                idx += 1
            else:
                if self.cancel_requested:
                    raise KeyboardInterrupt()
                self.status = "done"
                self.progress["pct"] = 100
                self.emit("meta", "\n\u2713 finished in %s\n" % human_time(time.time() - self.started))
        except KeyboardInterrupt:
            self.status = "cancelled"
            self.emit("meta", "\n\u25a0 cancelled by user\n")
        except Exception as exc:
            self.status = "error"
            self.emit("stderr", "\n\u2717 %s\n" % exc)
        finally:
            self.finished = time.time()
            self._cleanup()
            self.push_state()

    def _cleanup(self):
        """Intermediate files exist only to feed the next stage. Remove them once
        the job stops, whether it finished, failed or was cancelled."""
        paths = self.meta.get("cleanup") or []
        removed = 0
        for p in paths:
            try:
                if os.path.exists(p):
                    os.remove(p)
                    removed += 1
            except OSError:
                pass
        if removed:
            self.emit("meta", "cleaned up %d intermediate file(s)\n" % removed)

    def _prepare_stage(self, stage):
        """Late substitution — lets stage 2 use values measured in stage 1."""
        argv = list(stage["argv"])
        for path, contents in (stage.get("prepare_files") or {}).items():
            with open(resolve_path(path, for_output=True), "w", encoding="utf-8") as fh:
                fh.write(contents)
        if stage.get("needs") == "loudnorm":
            data = self._captured.get("loudnorm") or ""
            m = LOUDNORM_RE.search(data)
            base = stage.get("loudnorm_base", "loudnorm=I=-16:TP=-1.5:LRA=11")
            if m:
                try:
                    d = json.loads(m.group(0))
                    if any(_n(d.get(k)) is None for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")):
                        raise ValueError("Loudness measurement is not finite (the track may be silent).")
                    measured = (base +
                                ":measured_I=%s:measured_TP=%s:measured_LRA=%s"
                                ":measured_thresh=%s:offset=%s:linear=true:print_format=summary" % (
                                    d.get("input_i"), d.get("input_tp"), d.get("input_lra"),
                                    d.get("input_thresh"), d.get("target_offset")))
                    argv = [measured if a == "__LOUDNORM__" else a for a in argv]
                    self.emit("meta", "measured: I=%s LUFS, TP=%s dBTP, LRA=%s\n" % (
                        d.get("input_i"), d.get("input_tp"), d.get("input_lra")))
                    return argv
                except (ValueError, TypeError) as exc:
                    raise ValueError("Cannot apply measured loudness: %s" % exc)
            raise ValueError("No loudness measurement was returned by the analysis pass.")
        return argv

    def _run_one(self, argv, stage):
        captured = []
        try:
            self.proc = subprocess.Popen(
                argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, errors="replace",
                cwd=stage.get("cwd") or self.cwd,
                start_new_session=(os.name == "posix"), stdin=subprocess.DEVNULL,
                env=dict(os.environ, PYTHONUNBUFFERED="1", AV_LOG_FORCE_NOCOLOR="1"))
        except FileNotFoundError:
            self.emit("stderr", "Executable not found: %s\n" % argv[0])
            return 127, ""
        except Exception as exc:
            self.emit("stderr", "Could not start process: %s\n" % exc)
            return 126, ""

        if self.cancel_requested:
            self.cancel()
        last_push = 0.0
        for raw in self.proc.stdout:
            line = raw.rstrip("\n")
            captured.append(line)
            if len(captured) > 6000:
                del captured[:2000]
            handled = False
            if self.kind == "ytdlp":
                handled = self._parse_ytdlp(line)
            if not handled and self.kind == "ffmpeg":
                handled = self._parse_ffmpeg(line)
            if not handled:
                lower = line.lower()
                stream = "stderr" if ("error" in lower or "invalid" in lower or
                                      lower.startswith("warning")) else "stdout"
                self.emit(stream, line)
            now = time.time()
            if now - last_push > 0.4:
                last_push = now
                BUS.publish({"type": "progress", "id": self.id,
                             "progress": self.progress, "status": self.status})
        self.proc.wait()
        rc = self.proc.returncode
        self.proc = None
        return rc, "\n".join(captured)

    def cancel(self):
        self.cancel_requested = True
        p = self.proc
        if p and p.poll() is None:
            try:
                if hasattr(os, "killpg"):
                    os.killpg(os.getpgid(p.pid), signal.SIGTERM)
                else:
                    p.terminate()
                for _ in range(30):
                    if p.poll() is not None:
                        break
                    time.sleep(0.1)
                if p.poll() is None:
                    if hasattr(os, "killpg"):
                        os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                    else:
                        p.kill()
            except Exception:
                pass
        elif self.status == "queued":
            with JOBS.lock:
                try:
                    JOBS.pending.remove(self)
                except ValueError:
                    pass
                self.status = "cancelled"
                self.finished = time.time()
            self.push_state()


class JobManager:
    def __init__(self):
        self.jobs = {}
        self.order = deque()
        self.pending = deque()
        self.lock = threading.RLock()
        self.slots = threading.Condition(self.lock)
        self.running_count = 0
        self.workers = []
        self.wake = threading.Semaphore(0)
        self._ensure_workers()

    def _ensure_workers(self):
        want = max(1, int(CONFIG.get("max_concurrent_jobs", 2)))
        while len(self.workers) < want:
            t = threading.Thread(target=self._worker, daemon=True,
                                 name="tf-worker-%d" % len(self.workers))
            t.start()
            self.workers.append(t)
        with self.slots:
            self.slots.notify_all()

    def _worker(self):
        while True:
            self.wake.acquire()
            with self.slots:
                while self.running_count >= max(1, int(CONFIG.get("max_concurrent_jobs", 2))):
                    self.slots.wait()
                job = self.pending.popleft() if self.pending else None
                if job:
                    self.running_count += 1
            if job is None:
                continue
            try:
                if job.cancel_requested:
                    job.status = "cancelled"
                    job.finished = time.time()
                    job.push_state()
                    continue
                job.run()
            finally:
                with self.slots:
                    self.running_count -= 1
                    self.slots.notify_all()

    def submit(self, job):
        with self.lock:
            wanted = [os.path.realpath(p) for p in job.outputs]
            for active in self.jobs.values():
                if active.status in ("queued", "running") and set(wanted).intersection(os.path.realpath(p) for p in active.outputs):
                    raise PathError("Another queued/running job is writing the same output.")
            self.jobs[job.id] = job
            self.order.appendleft(job.id)
            self.pending.append(job)
            self._ensure_workers()
            limit = max(1, int(CONFIG.get("keep_job_history", 500)))
            for old in list(reversed(self.order)):
                if len(self.order) <= limit:
                    break
                if self.jobs[old].status not in ("queued", "running"):
                    self.order.remove(old)
                    self.jobs.pop(old, None)
        job.push_state()
        self.wake.release()
        return job

    def get(self, jid):
        return self.jobs.get(jid)

    def list(self, limit=200):
        with self.lock:
            ids = list(self.order)[:limit]
        return [self.jobs[i].brief() for i in ids if i in self.jobs]

    def active(self):
        return [j for j in self.jobs.values() if j.status in ("queued", "running")]

    def cancel_all(self):
        n = 0
        for j in list(self.jobs.values()):
            if j.status in ("queued", "running"):
                j.cancel()
                n += 1
        return n

    def clear_finished(self):
        with self.lock:
            keep = deque()
            removed = 0
            for jid in self.order:
                j = self.jobs.get(jid)
                if j and j.status in ("queued", "running"):
                    keep.append(jid)
                else:
                    self.jobs.pop(jid, None)
                    removed += 1
            self.order = keep
        return removed


JOBS = JobManager()


def make_job(kind, title, stages, cwd=None, spec=None, meta=None):
    if isinstance(stages, list) and stages and isinstance(stages[0], list):
        stages = [{"label": "run", "argv": stages[0]}]
    for s in stages:
        if s["argv"] and os.path.basename(s["argv"][0]) not in ALLOWED_BINARIES:
            raise PathError("Refusing to run '%s' — not in the allow-list." % s["argv"][0])
    return Job(kind, title, stages, cwd=cwd, spec=spec, meta=meta)


