#!/usr/bin/env python3
import argparse
import os

from tubeforge import create_app
from tubeforge.config import APP_VERSION, CONFIG, CONF_PATH, LOG_DIR, dl_dir
from tubeforge.jobs import JOBS
from tubeforge.probe import dependency_report, which


def banner(host, port):
    deps = dependency_report()

    def mark(name):
        d = deps.get(name, {})
        return ("\u2713 " + (d.get("version") or "")[:44]) if d.get("found") else "\u2717 not found on PATH"

    lines = [
        "",
        "  TUBEFORGE %s" % APP_VERSION,
        "  yt-dlp and ffmpeg, with the knobs exposed.",
        "",
        "  open        http://%s:%d" % ("localhost" if host in ("0.0.0.0", "127.0.0.1") else host, port),
        "  downloads   %s" % dl_dir(),
        "  settings    %s" % CONF_PATH,
        "  logs        %s" % LOG_DIR,
        "",
        "  yt-dlp      %s" % mark("yt-dlp"),
        "  ffmpeg      %s" % mark("ffmpeg"),
        "  ffprobe     %s" % mark("ffprobe"),
        "  aria2c      %s" % mark("aria2c"),
        "",
        "  Ctrl+C to stop.",
        "",
    ]
    width = max(len(l) for l in lines) + 2
    top = "\u250c" + "\u2500" * width + "\u2510"
    bot = "\u2514" + "\u2500" * width + "\u2518"
    print(top)
    for l in lines:
        print("\u2502" + l.ljust(width) + "\u2502")
    print(bot)


def main():
    ap = argparse.ArgumentParser(description="TubeForge — yt-dlp + ffmpeg web control surface")
    ap.add_argument("--host", default="127.0.0.1",
                    help="interface to bind (default 127.0.0.1; use 0.0.0.0 to expose on your LAN)")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--downloads", help="override the download folder for this run")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    if args.downloads:
        CONFIG["download_dir"] = os.path.abspath(os.path.expanduser(args.downloads))
        os.makedirs(CONFIG["download_dir"], exist_ok=True)

    app = create_app()
    missing = [n for n in ("yt-dlp", "ffmpeg", "ffprobe") if not which(CONFIG.get(
        {"yt-dlp": "ytdlp_bin", "ffmpeg": "ffmpeg_bin", "ffprobe": "ffprobe_bin"}[n]))]
    banner(args.host, args.port)
    if missing:
        print("  Heads up: %s not on PATH. Install them, or set the paths under Settings.\n"
              % ", ".join(missing))

    try:
        app.run(host=args.host, port=args.port, debug=args.debug,
                threaded=True, use_reloader=False)
    except KeyboardInterrupt:
        pass
    finally:
        n = JOBS.cancel_all()
        if n:
            print("\nStopped %d running job(s)." % n)


if __name__ == "__main__":
    main()
