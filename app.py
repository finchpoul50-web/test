from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
import yt_dlp
import urllib.request as urlreq
import re
import os
import tempfile

app = Flask(__name__)

# Fix CORS for all routes
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

# ── Cookie support ──────────────────────────────────────────────────────────────
# Option 1 (Local dev — easiest):
#   Set YOUTUBE_COOKIES_FILE=/absolute/path/to/your/cookies.txt in your .env
#
# Option 2 (Production / Railway):
#   Set YOUTUBE_COOKIES to the full text content of a Netscape cookies.txt file.
#   yt-dlp will use these to authenticate and bypass bot detection.

_cookie_file_path = None  # cached path so we only write once per worker


def _get_cookie_file():
    """Return path to a valid Netscape cookies.txt file, or None."""
    global _cookie_file_path

    # ── Option 1: direct file path (easiest for local dev) ──────────────────
    cookies_file = os.environ.get("YOUTUBE_COOKIES_FILE", "").strip()
    if cookies_file and os.path.exists(cookies_file):
        return cookies_file

    # ── Option 2: inline content in env var (production / Railway) ──────────
    if _cookie_file_path and os.path.exists(_cookie_file_path):
        return _cookie_file_path

    cookies_content = os.environ.get("YOUTUBE_COOKIES", "").strip()
    if not cookies_content:
        return None

    # Railway sometimes stores multiline vars with literal \n instead of real newlines
    cookies_content = cookies_content.replace("\\n", "\n").replace("\\t", "\t")

    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, prefix="yt_cookies_"
    )
    tmp.write(cookies_content)
    tmp.close()
    _cookie_file_path = tmp.name
    return _cookie_file_path


def get_ydl_opts(extra=None):
    """
    Return base yt-dlp options.
    - With cookies: 'web' client works and returns all formats including 720p.
    - Without cookies: 'android_vr' / 'ios' are better at bypassing bot detection.
    """
    has_cookies = bool(_get_cookie_file())
    opts = {
        "quiet": True,
        "noplaylist": True,
        "extractor_args": {
            "youtube": {
                # With cookies: web is best (bypasses bot check + all formats)
                # Without cookies: android_vr/ios bypass bot detection better
                "player_client": ["web", "android_vr", "ios"] if has_cookies else ["android_vr", "ios", "web"]
            }
        },
    }
    cookie_path = _get_cookie_file()
    if cookie_path:
        opts["cookiefile"] = cookie_path
    if extra:
        opts.update(extra)
    return opts




@app.route("/")
def home():
    return jsonify({
        "status": "running",
        "message": "Downloader API Running"
    })


@app.route("/download", methods=["GET", "OPTIONS"])
def download():
    """
    Extract video info and return all available quality formats as separate cards.
    Only returns combined (video+audio) formats — no ffmpeg needed.
    YouTube typically has combined formats up to 720p; 1080p+ usually requires muxing.
    """
    url = request.args.get("url")

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    try:
        # Single yt-dlp call — extract info without downloading
        # Note: extractor_args (player_client) are YouTube-specific and only
        # activate for youtube.com/youtu.be URLs; other platforms use their own extractors.
        with yt_dlp.YoutubeDL(get_ydl_opts()) as ydl:
            info = ydl.extract_info(url, download=False)

        all_formats = info.get("formats", [])

        # ── Filter: combined video+audio, direct HTTP URL (no HLS/DASH manifests) ──
        combined = [
            f for f in all_formats
            if f.get("vcodec") not in (None, "none", "")
            and f.get("acodec") not in (None, "none", "")
            and f.get("height")
            and f.get("url")
            and f.get("protocol", "") not in ("m3u8", "m3u8_native", "dash", "mpd")
            and not f.get("url", "").endswith(".m3u8")
            and not f.get("url", "").endswith(".mpd")
        ]

        # ── Group by height — pick best bitrate at each unique resolution ──────────
        by_height = {}
        for f in combined:
            h = f.get("height")
            if not h:
                continue
            current = by_height.get(h)
            if current is None:
                by_height[h] = f
            else:
                # Prefer higher total bitrate (tbr) or video bitrate (vbr)
                if (f.get("tbr") or f.get("vbr") or 0) > (current.get("tbr") or current.get("vbr") or 0):
                    by_height[h] = f

        # ── Build output list (highest resolution first) ────────────────────────────
        formats_out = []
        for height in sorted(by_height.keys(), reverse=True):
            best = by_height[height]

            if height >= 2160:
                label = "4K (2160p)"
            elif height >= 1440:
                label = "2K (1440p)"
            elif height >= 1080:
                label = "Full HD (1080p)"
            elif height >= 720:
                label = "HD (720p)"
            elif height >= 480:
                label = "SD (480p)"
            elif height >= 360:
                label = "360p"
            elif height >= 240:
                label = "240p"
            else:
                label = f"{height}p"

            filesize = best.get("filesize") or best.get("filesize_approx")
            if filesize:
                mb = filesize / (1024 * 1024)
                size_str = f"{mb:.0f} MB" if mb >= 1 else f"{filesize // 1024} KB"
            else:
                size_str = "~"

            formats_out.append({
                "label":  label,
                "height": height,
                "url":    best.get("url"),
                "ext":    best.get("ext", "mp4"),
                "size":   size_str,
                "type":   "video"
            })

        # ── Fallback: if no combined formats found, use yt-dlp "best" ───────────────
        if not formats_out:
            with yt_dlp.YoutubeDL(get_ydl_opts({"format": "best"})) as ydl2:
                info2 = ydl2.extract_info(url, download=False)
            formats_out = [{
                "label": "Best Quality",
                "url":   info2.get("url"),
                "ext":   info2.get("ext", "mp4"),
                "size":  "~",
                "type":  "video"
            }]

        # ── Audio-only ───────────────────────────────────────────────────────────────
        audio_only = [
            f for f in all_formats
            if f.get("acodec") not in (None, "none", "")
            and f.get("vcodec") in (None, "none", "")
            and f.get("url")
            and f.get("protocol", "") not in ("m3u8", "m3u8_native", "dash", "mpd")
        ]
        if audio_only:
            best_audio = max(audio_only, key=lambda x: x.get("abr") or x.get("tbr") or 0)
            abr = best_audio.get("abr") or best_audio.get("tbr") or 0
            formats_out.append({
                "label": f"Audio Only ({int(abr)}kbps)" if abr else "Audio Only",
                "url":   best_audio.get("url"),
                "ext":   best_audio.get("ext", "m4a"),
                "size":  "~",
                "type":  "audio"
            })

        return jsonify({
            "title":     info.get("title"),
            "duration":  info.get("duration"),
            "thumbnail": info.get("thumbnail"),
            "formats":   formats_out
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/stream-download", methods=["GET"])
def stream_download():
    """
    Proxy endpoint — fetches the video from the CDN server-side and
    streams it back to the browser with Content-Disposition: attachment,
    forcing a Save-File dialog instead of opening the video player.

    Query params:
        url   - URL-encoded direct video CDN URL
        title - (optional) desired filename without extension
        ext   - (optional) file extension, defaults to mp4
    """
    direct_url = request.args.get("url")
    title = request.args.get("title", "video")
    ext = request.args.get("ext", "mp4")

    if not direct_url:
        return jsonify({"error": "Missing url parameter"}), 400

    if not direct_url.startswith("http://") and not direct_url.startswith("https://"):
        return jsonify({"error": "Invalid URL scheme"}), 400

    # Sanitize filename
    safe_title = re.sub(r'[^\w\s\-]', '', title).strip().replace(' ', '_')
    if not safe_title:
        safe_title = "video"
    filename = f"{safe_title}.{ext}"

    req_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": direct_url,
    }

    try:
        req = urlreq.Request(direct_url, headers=req_headers)
        remote = urlreq.urlopen(req, timeout=30)

        content_type = remote.headers.get("Content-Type", "video/mp4")
        content_length = remote.headers.get("Content-Length")

        def generate():
            try:
                while True:
                    chunk = remote.read(1024 * 64)  # 64 KB chunks
                    if not chunk:
                        break
                    yield chunk
            finally:
                remote.close()

        response_headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": content_type,
            "Cache-Control": "no-cache",
        }
        if content_length:
            response_headers["Content-Length"] = content_length

        return Response(
            stream_with_context(generate()),
            status=200,
            headers=response_headers
        )

    except Exception as e:
        return jsonify({"error": f"Failed to fetch video: {str(e)}"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=4000)
