from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
import yt_dlp
import requests
import re

app = Flask(__name__)

# Fix CORS for all routes
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)


@app.route("/")
def home():
    return jsonify({
        "status": "running",
        "message": "Downloader API Running"
    })


@app.route("/download", methods=["GET", "OPTIONS"])
def download():
    url = request.args.get("url")

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    if "kick.com" in url.lower():
        return jsonify({
            "error": "Kick.com is not supported via this API"
        }), 400

    ydl_opts = {
        "format": "best",
        "quiet": True,
        "noplaylist": True
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

            return jsonify({
                "title": info.get("title"),
                "duration": info.get("duration"),
                "thumbnail": info.get("thumbnail"),
                "direct_url": info.get("url")
            })

    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 500


@app.route("/stream-download", methods=["GET"])
def stream_download():
    """
    Proxy endpoint that fetches the video from the CDN and streams it
    back to the browser with Content-Disposition: attachment.
    
    This forces the browser to SAVE the file instead of opening/playing it.
    
    Query params:
        url      - URL-encoded direct video URL
        title    - (optional) desired filename without extension
        ext      - (optional) file extension, defaults to mp4
    """
    direct_url = request.args.get("url")
    title = request.args.get("title", "video")
    ext = request.args.get("ext", "mp4")

    if not direct_url:
        return jsonify({"error": "Missing url parameter"}), 400

    # Basic security: only allow http/https
    if not direct_url.startswith("http://") and not direct_url.startswith("https://"):
        return jsonify({"error": "Invalid URL scheme"}), 400

    # Sanitize the filename
    safe_title = re.sub(r'[^\w\s\-]', '', title).strip().replace(' ', '_')
    if not safe_title:
        safe_title = "video"
    filename = f"{safe_title}.{ext}"

    headers = {
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
        remote = requests.get(
            direct_url,
            headers=headers,
            stream=True,
            timeout=30,
            allow_redirects=True
        )
        remote.raise_for_status()

        content_type = remote.headers.get("Content-Type", "video/mp4")
        content_length = remote.headers.get("Content-Length")

        def generate():
            for chunk in remote.iter_content(chunk_size=1024 * 64):  # 64 KB chunks
                if chunk:
                    yield chunk

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

    except requests.exceptions.RequestException as e:
        return jsonify({"error": f"Failed to fetch video: {str(e)}"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000)
