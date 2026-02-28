from flask import Flask
import yt_dlp

app = Flask(__name__)

@app.route("/")
def home():
    return "API Running"

@app.route("/download")
def download():
    url = request.args.get("url")
    if not url:
        return {"error": "No URL provided"}, 400

    with yt_dlp.YoutubeDL({"quiet": True}) as ydl:
        info = ydl.extract_info(url, download=False)
        return {
            "title": info.get("title"),
            "url": info.get("url"),
        }

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000))
