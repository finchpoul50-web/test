from flask import Flask, request, jsonify
from flask_cors import CORS
import yt_dlp

app = Flask(__name__)

# 🔥 حل مشكل CORS نهائياً
CORS(app, resources={r"/*": {"origins": "*"}}, supports_credentials=True)

@app.route("/")
def home():
    return jsonify({
        "status": "running",
        "message": "Downloader API Running"
    })


@app.route("/download", methods=["GET", "OPTIONS"])
def download():

    # منع Kick من API
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000)
