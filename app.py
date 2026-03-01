from flask import Response
import requests
import urllib.parse

@app.route("/download", methods=["GET"])
def download():
    url = request.args.get("url")

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    if "kick.com" in url.lower():
        return jsonify({"error": "Kick.com is not supported"}), 400

    ydl_opts = {
        "format": "best",
        "quiet": True,
        "noplaylist": True
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        formats = info.get("formats")
        if not formats:
            return jsonify({"error": "No formats found"}), 500

        # Pick best progressive mp4 (has audio+video)
        best = None
        for f in reversed(formats):
            if f.get("ext") == "mp4" and f.get("acodec") != "none":
                best = f
                break

        if not best:
            return jsonify({"error": "No suitable MP4 format found"}), 500

        direct_url = best.get("url")
        headers = best.get("http_headers", {})

        # Stream from YouTube
        r = requests.get(direct_url, headers=headers, stream=True)

        filename = f"{info.get('title','video')}.mp4"
        filename = urllib.parse.quote(filename)

        return Response(
            r.iter_content(chunk_size=8192),
            content_type=r.headers.get("Content-Type", "video/mp4"),
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"'
            }
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500
