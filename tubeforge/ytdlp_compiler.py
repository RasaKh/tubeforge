import ipaddress
import json
import os
import re
import subprocess
from urllib.parse import urlsplit

from .config import CONFIG, dl_dir, human_size, resolve_path

# ═══════════════════════════════════════════════════════════════════════════
#  YT-DLP OPTION REGISTRY
#  The UI renders itself from this table; the compiler builds argv from it.
#  type:  bool | text | number | select | list | path | time
#  Adding an entry here instantly adds a control to the web UI.
# ═══════════════════════════════════════════════════════════════════════════

YTDLP_GROUPS = [
    ("format",    "Format & Quality",        "Pick streams, codecs, containers"),
    ("output",    "Output & Naming",         "Where files land and what they're called"),
    ("playlist",  "Playlist & Selection",    "Ranges, filters, archives"),
    ("subs",      "Subtitles",               "Write, embed, translate, convert"),
    ("meta",      "Thumbnails & Metadata",   "Tags, covers, sidecar files"),
    ("sponsor",   "SponsorBlock & Chapters", "Skip segments, split by chapter"),
    ("sections",  "Clipping & Live",         "Download only part of a video"),
    ("post",      "Post-processing",         "Recode, remux, run commands after"),
    ("network",   "Network & Throttling",    "Proxy, retries, concurrency, rate limits"),
    ("auth",      "Authentication",          "Cookies, logins, geo bypass"),
    ("fs",        "Filesystem & Behaviour",  "Overwrite, resume, cache, mtime"),
    ("verbose",   "Simulation & Logging",    "Dry runs, listings, JSON dumps"),
    ("extractor", "Extractor & Raw",         "Site-specific switches and raw args"),
]

YTDLP_OPTIONS = [
    # ── Format & Quality ───────────────────────────────────────────────────
    dict(id="format", group="format", type="text", flag="-f", label="Format selector",
         placeholder="bestvideo*+bestaudio/best",
         help="yt-dlp format expression. Combine with + , use / for fallbacks, [] for filters."),
    dict(id="format_sort", group="format", type="text", flag="-S", label="Format sort (-S)",
         placeholder="res:1080,fps,vcodec:av01,acodec:opus",
         help="Preference ordering. Often easier than a format expression."),
    dict(id="merge_output_format", group="format", type="select", flag="--merge-output-format",
         label="Merge container", choices=["", "mp4", "mkv", "webm", "flv", "ogg", "mov", "avi"],
         help="Container used when video and audio are merged."),
    dict(id="extract_audio", group="format", type="bool", flag="-x", label="Extract audio only",
         hidden=True,
         help="Set by the audio format chips rather than toggled directly, since selecting an "
              "audio-only stream without it leaves the file in its source container."),
    dict(id="audio_format", group="format", type="select", flag="--audio-format",
         label="Audio format", choices=["", "best", "mp3", "m4a", "aac", "flac", "wav", "opus", "vorbis", "alac"],
         help="Target audio codec when extracting audio."),
    dict(id="audio_quality", group="format", type="text", flag="--audio-quality",
         label="Audio quality", placeholder="0 (best VBR) … 10, or 192K",
         help="ffmpeg quality scale 0-10, or an explicit bitrate like 320K."),
    dict(id="remux_video", group="format", type="select", flag="--remux-video",
         label="Remux to", choices=["", "mp4", "mkv", "mov", "webm", "avi", "flv"],
         help="Losslessly change container after download when possible."),
    dict(id="recode_video", group="format", type="select", flag="--recode-video",
         label="Re-encode to", choices=["", "mp4", "mkv", "webm", "avi", "mov", "flv"],
         help="Force a re-encode into this container (slow, lossy)."),
    dict(id="format_id", group="format", type="text", flag="-f", label="Explicit format IDs", hidden=True,
         help="Filled in by the Format Explorer when you tick specific formats."),
    dict(id="check_formats", group="format", type="bool", flag="--check-formats",
         label="Verify formats are downloadable", adv=True),
    dict(id="prefer_free_formats", group="format", type="bool", flag="--prefer-free-formats",
         label="Prefer free (webm/opus) formats", adv=True),
    dict(id="allow_multiple_video", group="format", type="bool", flag="--audio-multistreams",
         label="Allow multiple audio streams", adv=True),
    dict(id="video_multistreams", group="format", type="bool", flag="--video-multistreams",
         label="Allow multiple video streams", adv=True),

    # ── Output & Naming ────────────────────────────────────────────────────
    dict(id="paths", group="output", type="path", flag="-P", label="Output directory",
         placeholder="leave empty for the default download folder"),
    dict(id="output", group="output", type="text", flag="-o", label="Output template",
         placeholder="%(title)s [%(id)s].%(ext)s",
         help="Filename template. Use the token buttons below to build one."),
    dict(id="output_chapter", group="output", type="text", flag="-o", label="Chapter template", prefix="chapter:",
         placeholder="chapter:%(title)s - %(section_number)03d %(section_title)s.%(ext)s", adv=True),
    dict(id="restrict_filenames", group="output", type="bool", flag="--restrict-filenames",
         label="ASCII-safe filenames", help="Strip spaces and non-ASCII characters."),
    dict(id="windows_filenames", group="output", type="bool", flag="--windows-filenames",
         label="Windows-safe filenames", adv=True),
    dict(id="trim_filenames", group="output", type="number", flag="--trim-filenames",
         label="Trim filenames to N chars", placeholder="200", adv=True),
    dict(id="no_overwrites", group="output", type="bool", flag="-w", label="Never overwrite"),
    dict(id="force_overwrites", group="output", type="bool", flag="--force-overwrites",
         label="Always overwrite"),
    dict(id="batch_file", group="output", type="path", flag="-a", label="URL batch file", adv=True,
         help="Read URLs from a text file, one per line."),

    # ── Playlist & Selection ───────────────────────────────────────────────
    dict(id="playlist_mode", group="playlist", type="select", flag="", label="Playlist handling",
         choices=["", "--no-playlist", "--yes-playlist"],
         labels={"": "auto (follow the URL)", "--no-playlist": "single video only",
                 "--yes-playlist": "download the whole playlist"}),
    dict(id="playlist_items", group="playlist", type="text", flag="-I", label="Items",
         placeholder="1:5,8,12::2,-3:",
         help="Index ranges. Supports steps and negative indices."),
    dict(id="max_downloads", group="playlist", type="number", flag="--max-downloads",
         label="Stop after N downloads"),
    dict(id="playlist_random", group="playlist", type="bool", flag="--playlist-random",
         label="Shuffle playlist order", adv=True),
    dict(id="playlist_reverse", group="playlist", type="bool", flag="--playlist-reverse",
         label="Reverse playlist order", adv=True),
    dict(id="lazy_playlist", group="playlist", type="bool", flag="--lazy-playlist",
         label="Process playlist entries lazily", adv=True),
    dict(id="download_archive", group="playlist", type="path", flag="--download-archive",
         label="Archive file", placeholder="archive.txt",
         help="Record downloaded IDs here and skip them next time."),
    dict(id="break_on_existing", group="playlist", type="bool", flag="--break-on-existing",
         label="Stop when hitting an archived item"),
    dict(id="match_filter", group="playlist", type="text", flag="--match-filters",
         label="Match filter", placeholder="duration > 120 & view_count > 1000",
         help="Boolean expression over metadata fields."),
    dict(id="date", group="playlist", type="text", flag="--date", label="Exact upload date",
         placeholder="20240101 or today-2weeks", adv=True),
    dict(id="dateafter", group="playlist", type="text", flag="--dateafter", label="Uploaded after",
         placeholder="20240101", adv=True),
    dict(id="datebefore", group="playlist", type="text", flag="--datebefore", label="Uploaded before",
         placeholder="20241231", adv=True),
    dict(id="min_filesize", group="playlist", type="text", flag="--min-filesize",
         label="Minimum filesize", placeholder="50M", adv=True),
    dict(id="max_filesize", group="playlist", type="text", flag="--max-filesize",
         label="Maximum filesize", placeholder="2G", adv=True),

    # ── Subtitles ──────────────────────────────────────────────────────────
    dict(id="write_subs", group="subs", type="bool", flag="--write-subs", label="Write subtitle files"),
    dict(id="write_auto_subs", group="subs", type="bool", flag="--write-auto-subs",
         label="Include auto-generated subs"),
    dict(id="embed_subs", group="subs", type="bool", flag="--embed-subs", label="Embed subs in the video"),
    dict(id="sub_langs", group="subs", type="text", flag="--sub-langs", label="Languages",
         placeholder="en.*,tr,-live_chat  (or: all)"),
    dict(id="sub_format", group="subs", type="text", flag="--sub-format", label="Preferred sub format",
         placeholder="srt/vtt/best"),
    dict(id="convert_subs", group="subs", type="select", flag="--convert-subs", label="Convert subs to",
         choices=["", "srt", "ass", "vtt", "lrc"]),
    dict(id="list_subs", group="subs", type="bool", flag="--list-subs", label="List available subs (no download)"),

    # ── Thumbnails & Metadata ──────────────────────────────────────────────
    dict(id="embed_thumbnail", group="meta", type="bool", flag="--embed-thumbnail", label="Embed thumbnail"),
    dict(id="write_thumbnail", group="meta", type="bool", flag="--write-thumbnail", label="Save thumbnail file"),
    dict(id="write_all_thumbnails", group="meta", type="bool", flag="--write-all-thumbnails",
         label="Save every thumbnail size", adv=True),
    dict(id="convert_thumbnails", group="meta", type="select", flag="--convert-thumbnails",
         label="Convert thumbnails to", choices=["", "jpg", "png", "webp"], adv=True),
    dict(id="embed_metadata", group="meta", type="bool", flag="--embed-metadata", label="Embed metadata tags"),
    dict(id="embed_chapters", group="meta", type="bool", flag="--embed-chapters", label="Embed chapter markers"),
    dict(id="embed_info_json", group="meta", type="bool", flag="--embed-info-json",
         label="Embed full info JSON", adv=True),
    dict(id="write_info_json", group="meta", type="bool", flag="--write-info-json", label="Save .info.json"),
    dict(id="write_description", group="meta", type="bool", flag="--write-description",
         label="Save description file"),
    dict(id="write_comments", group="meta", type="bool", flag="--write-comments",
         label="Download comments", adv=True),
    dict(id="write_link", group="meta", type="bool", flag="--write-url-link",
         label="Write .url shortcut", adv=True),
    dict(id="parse_metadata", group="meta", type="list", flag="--parse-metadata",
         label="Parse metadata rules", placeholder="title:%(artist)s - %(title)s", adv=True,
         help="One rule per line. Extracts fields out of existing ones."),
    dict(id="replace_in_metadata", group="meta", type="list", flag="--replace-in-metadata",
         label="Replace in metadata", placeholder='title "  " " "', adv=True),

    # ── SponsorBlock & Chapters ────────────────────────────────────────────
    dict(id="sponsorblock_mark", group="sponsor", type="text", flag="--sponsorblock-mark",
         label="Mark categories as chapters", placeholder="all  |  sponsor,intro,outro"),
    dict(id="sponsorblock_remove", group="sponsor", type="text", flag="--sponsorblock-remove",
         label="Cut categories out", placeholder="sponsor,selfpromo,interaction"),
    dict(id="sponsorblock_api", group="sponsor", type="text", flag="--sponsorblock-api",
         label="SponsorBlock API URL", placeholder="https://sponsor.ajay.app", adv=True),
    dict(id="split_chapters", group="sponsor", type="bool", flag="--split-chapters",
         label="Split file by chapters"),
    dict(id="no_chapters", group="sponsor", type="bool", flag="--no-embed-chapters",
         label="Do not embed chapters", adv=True),

    # ── Clipping & Live ────────────────────────────────────────────────────
    dict(id="download_sections", group="sections", type="list", flag="--download-sections",
         label="Download only sections", placeholder="*00:01:30-00:04:00",
         help="One per line. Use *START-END for times, or a chapter title regex."),
    dict(id="force_keyframes", group="sections", type="bool", flag="--force-keyframes-at-cuts",
         label="Re-encode at cut points (accurate clips)"),
    dict(id="live_from_start", group="sections", type="bool", flag="--live-from-start",
         label="Live: download from the start"),
    dict(id="wait_for_video", group="sections", type="text", flag="--wait-for-video",
         label="Wait for scheduled stream", placeholder="60-300", adv=True),
    dict(id="no_live_from_start", group="sections", type="bool", flag="--no-live-from-start",
         label="Live: only from now", adv=True),

    # ── Post-processing ────────────────────────────────────────────────────
    dict(id="keep_video", group="post", type="bool", flag="-k", label="Keep intermediate files"),
    dict(id="postprocessor_args", group="post", type="list", flag="--postprocessor-args",
         label="Post-processor args", placeholder="ffmpeg:-c:v libx264 -crf 20",
         help="One per line, in NAME:ARGS form."),
    dict(id="ffmpeg_location", group="post", type="path", flag="--ffmpeg-location",
         label="Custom ffmpeg location", adv=True),
    dict(id="concat_playlist", group="post", type="select", flag="--concat-playlist",
         label="Concatenate playlist", choices=["", "never", "always", "multi_video"], adv=True),

    # ── Network ────────────────────────────────────────────────────────────
    dict(id="limit_rate", group="network", type="text", flag="-r", label="Rate limit",
         placeholder="4.2M / 500K"),
    dict(id="throttled_rate", group="network", type="text", flag="--throttled-rate",
         label="Re-extract below rate", placeholder="100K", adv=True),
    dict(id="retries", group="network", type="text", flag="-R", label="Retries", placeholder="10 or infinite"),
    dict(id="fragment_retries", group="network", type="text", flag="--fragment-retries",
         label="Fragment retries", placeholder="10 or infinite"),
    dict(id="concurrent_fragments", group="network", type="number", flag="-N",
         label="Concurrent fragments", placeholder="4"),
    dict(id="file_access_retries", group="network", type="number", flag="--file-access-retries",
         label="File access retries", adv=True),
    dict(id="socket_timeout", group="network", type="number", flag="--socket-timeout",
         label="Socket timeout (s)", adv=True),
    dict(id="buffer_size", group="network", type="text", flag="--buffer-size",
         label="Buffer size", placeholder="16K", adv=True),
    dict(id="http_chunk_size", group="network", type="text", flag="--http-chunk-size",
         label="HTTP chunk size", placeholder="10M", adv=True),
    dict(id="proxy", group="network", type="text", flag="--proxy", label="Proxy",
         placeholder="socks5://127.0.0.1:1080"),
    dict(id="source_address", group="network", type="text", flag="--source-address",
         label="Bind source address", adv=True),
    dict(id="force_ipv4", group="network", type="bool", flag="-4", label="Force IPv4", adv=True),
    dict(id="force_ipv6", group="network", type="bool", flag="-6", label="Force IPv6", adv=True),
    dict(id="downloader", group="network", type="select", flag="--downloader", label="External downloader",
         choices=["", "native", "aria2c", "axel", "curl", "wget", "ffmpeg", "httpie"]),
    dict(id="downloader_args", group="network", type="list", flag="--downloader-args",
         label="Downloader args", placeholder="aria2c:-x 16 -k 1M", adv=True),
    dict(id="sleep_interval", group="network", type="number", flag="--sleep-interval",
         label="Sleep between downloads (s)", adv=True),
    dict(id="max_sleep_interval", group="network", type="number", flag="--max-sleep-interval",
         label="Max sleep (s)", adv=True),
    dict(id="sleep_requests", group="network", type="number", flag="--sleep-requests",
         label="Sleep between requests (s)", adv=True),

    # ── Authentication ─────────────────────────────────────────────────────
    dict(id="cookies", group="auth", type="path", flag="--cookies", label="Cookies file",
         placeholder="cookies.txt (Netscape format)"),
    dict(id="cookies_from_browser", group="auth", type="text", flag="--cookies-from-browser",
         label="Cookies from browser", placeholder="firefox  |  chrome:Default  |  brave"),
    dict(id="username", group="auth", type="text", flag="-u", label="Username"),
    dict(id="password", group="auth", type="text", flag="-p", label="Password", secret=True),
    dict(id="twofactor", group="auth", type="text", flag="-2", label="2FA code", secret=True),
    dict(id="video_password", group="auth", type="text", flag="--video-password",
         label="Video password", secret=True),
    dict(id="netrc", group="auth", type="bool", flag="-n", label="Use .netrc", adv=True),
    dict(id="geo_bypass", group="auth", type="bool", flag="--geo-bypass", label="Geo bypass"),
    dict(id="geo_bypass_country", group="auth", type="text", flag="--geo-bypass-country",
         label="Pretend country (ISO 3166-2)", placeholder="TR", adv=True),
    dict(id="user_agent", group="auth", type="text", flag="--user-agent", label="User agent", adv=True),
    dict(id="referer", group="auth", type="text", flag="--referer", label="Referer", adv=True),
    dict(id="headers", group="auth", type="list", flag="--add-headers", label="Extra headers",
         placeholder="X-Token:abc123", adv=True),

    # ── Filesystem & Behaviour ─────────────────────────────────────────────
    dict(id="continue_dl", group="fs", type="bool", flag="-c", label="Resume partial downloads"),
    dict(id="no_part", group="fs", type="bool", flag="--no-part", label="Write directly (no .part files)"),
    dict(id="no_mtime", group="fs", type="bool", flag="--no-mtime", label="Do not set file mtime"),
    dict(id="no_cache_dir", group="fs", type="bool", flag="--no-cache-dir", label="Disable cache", adv=True),
    dict(id="rm_cache_dir", group="fs", type="bool", flag="--rm-cache-dir", label="Wipe cache first", adv=True),
    dict(id="ignore_errors", group="fs", type="bool", flag="-i", label="Continue past errors"),
    dict(id="abort_on_error", group="fs", type="bool", flag="--abort-on-error", label="Abort on first error"),
    dict(id="no_warnings", group="fs", type="bool", flag="--no-warnings", label="Suppress warnings"),
    dict(id="paths_temp", group="fs", type="path", flag="-P", prefix="temp:", label="Temp directory", adv=True),

    # ── Simulation & Logging ───────────────────────────────────────────────
    dict(id="simulate", group="verbose", type="bool", flag="-s", label="Simulate (no download)"),
    dict(id="skip_download", group="verbose", type="bool", flag="--skip-download",
         label="Skip media, keep sidecars"),
    dict(id="list_formats", group="verbose", type="bool", flag="-F", label="List formats"),
    dict(id="list_thumbnails", group="verbose", type="bool", flag="--list-thumbnails", label="List thumbnails"),
    dict(id="dump_json", group="verbose", type="bool", flag="-j", label="Dump metadata JSON"),
    dict(id="print_fields", group="verbose", type="list", flag="--print", label="Print fields",
         placeholder="%(title)s %(duration)s", adv=True),
    dict(id="verbose_flag", group="verbose", type="bool", flag="-v", label="Verbose output"),
    dict(id="quiet", group="verbose", type="bool", flag="-q", label="Quiet"),

    # ── Extractor & Raw ────────────────────────────────────────────────────
    dict(id="extractor_args", group="extractor", type="list", flag="--extractor-args",
         label="Extractor args", placeholder="youtube:player_client=android,web",
         help="Site-specific tuning. One per line."),
    dict(id="extractor_retries", group="extractor", type="text", flag="--extractor-retries",
         label="Extractor retries", adv=True),
    dict(id="allow_unplayable", group="extractor", type="bool", flag="--allow-unplayable-formats",
         label="Allow unplayable (DRM) formats", adv=True),
    dict(id="mark_watched", group="extractor", type="bool", flag="--mark-watched",
         label="Mark as watched", adv=True),
    dict(id="no_check_certificate", group="extractor", type="bool", flag="--no-check-certificates",
         label="Skip TLS verification", adv=True),
    dict(id="legacy_server_connect", group="extractor", type="bool", flag="--legacy-server-connect",
         label="Allow legacy TLS", adv=True),
]

YTDLP_INDEX = {o["id"]: o for o in YTDLP_OPTIONS}

# Ready-made format expressions offered as one-click chips in the UI.
# `sets` carries any companion options a preset needs to actually do what its
# name promises. Selecting an audio-only stream without -x leaves the file in
# its source container (opus inside .webm), which then breaks thumbnail
# embedding and confuses every downstream tool.
FORMAT_PRESETS = [
    ("Best available (merged)", "bestvideo*+bestaudio/best"),
    ("Best MP4/H.264 + AAC", "bestvideo[ext=mp4][vcodec^=avc]+bestaudio[ext=m4a]/best[ext=mp4]"),
    ("≤ 2160p", "bestvideo[height<=2160]+bestaudio/best[height<=2160]"),
    ("≤ 1440p", "bestvideo[height<=1440]+bestaudio/best[height<=1440]"),
    ("≤ 1080p", "bestvideo[height<=1080]+bestaudio/best[height<=1080]"),
    ("≤ 1080p60", "bestvideo[height<=1080][fps>=50]+bestaudio/bestvideo[height<=1080]+bestaudio"),
    ("≤ 720p", "bestvideo[height<=720]+bestaudio/best[height<=720]"),
    ("≤ 480p", "bestvideo[height<=480]+bestaudio/best[height<=480]"),
    ("Smallest possible", "worstvideo+worstaudio/worst"),
    ("Audio only, best", "bestaudio/best", {"extract_audio": True}),
    ("Audio only, m4a", "bestaudio[ext=m4a]/bestaudio", {"extract_audio": True}),
    ("AV1 preferred", "bestvideo[vcodec^=av01]+bestaudio/bestvideo+bestaudio"),
    ("VP9 preferred", "bestvideo[vcodec^=vp9]+bestaudio/bestvideo+bestaudio"),
    ("No AV1 (compat)", "bestvideo[vcodec!^=av01]+bestaudio/best"),
    ("Under 500 MB", "best[filesize<500M]/bestvideo[filesize<400M]+bestaudio"),
]

OUTPUT_TOKENS = [
    ("title", "Video title"), ("id", "Video ID"), ("ext", "Extension"),
    ("uploader", "Channel/uploader"), ("channel", "Channel name"),
    ("upload_date", "YYYYMMDD"), ("duration_string", "H:MM:SS"),
    ("resolution", "e.g. 1920x1080"), ("fps", "Frames per second"),
    ("playlist", "Playlist name"), ("playlist_index", "Index in playlist"),
    ("playlist_autonumber", "Sequential counter"), ("autonumber", "Global counter"),
    ("view_count", "Views"), ("like_count", "Likes"), ("epoch", "Unix time"),
    ("format_id", "Chosen format id"), ("vcodec", "Video codec"), ("acodec", "Audio codec"),
    ("release_date", "Release date"), ("section_title", "Chapter title"),
    ("section_number", "Chapter number"), ("webpage_url_domain", "Site domain"),
]

OUTPUT_TEMPLATE_PRESETS = [
    ("Title + ID", "%(title)s [%(id)s].%(ext)s"),
    ("Plain title", "%(title)s.%(ext)s"),
    ("Channel / Title", "%(uploader)s/%(title)s.%(ext)s"),
    ("Date - Title", "%(upload_date>%Y-%m-%d)s - %(title)s.%(ext)s"),
    ("Playlist ordered", "%(playlist)s/%(playlist_index)03d - %(title)s.%(ext)s"),
    ("Archive style", "%(uploader)s/%(upload_date>%Y)s/%(upload_date>%Y-%m-%d)s %(title)s [%(id)s].%(ext)s"),
    ("Music", "%(artist,uploader)s - %(track,title)s.%(ext)s"),
    ("Chapters", "chapter:%(title)s/%(section_number)03d %(section_title)s.%(ext)s"),
]

# Progress template: yt-dlp prints one machine-readable line per tick.
PROGRESS_SENTINEL = "@@TF@@"
PROGRESS_TEMPLATE = (
    PROGRESS_SENTINEL +
    "%(progress.status)s|%(progress._percent_str)s|%(progress._speed_str)s|"
    "%(progress._eta_str)s|%(progress._downloaded_bytes_str)s|%(progress._total_bytes_estimate_str)s|"
    "%(info.title)s"
)


FORMAT_PRESETS = [(p[0], p[1], (p[2] if len(p) > 2 else {})) for p in FORMAT_PRESETS]
