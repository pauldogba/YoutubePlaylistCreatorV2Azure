# =======================
# app/main.py
# =======================
from flask import Flask, request, jsonify, send_from_directory
from google.cloud import secretmanager
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from datetime import datetime, timedelta, timezone
import json
import isodate
import os
import logging

logging.basicConfig(level=logging.INFO)


# Detect local vs production environment
IS_LOCAL = os.environ.get("ENV") == "local"

if IS_LOCAL:
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = r"C:\Users\kenna\Documents\credentials\dev-key.json"
    PROJECT_ID = os.environ.get("GCP_PROJECT")
    REDIRECT_URI = "http://localhost:8080/"
else:
    PROJECT_ID = os.environ.get("GCP_PROJECT")
    REDIRECT_URI = "https://youtubeplaylistcreatorv2-117353943789.asia-southeast1.run.app/"

app = Flask(__name__, static_folder='static')

@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def catch_all(path):
    print(f"⚠️ Caught request to: /{path}")
    logging.info("ℹ️ logging /check route")
    logging.info("📥 Called /")
    logging.info(f"🔍 ENV = {os.environ.get('ENV')}")
    logging.info(f"🔍 IS_LOCAL = {IS_LOCAL}")
    logging.info(f"📁 static_folder = {app.static_folder}")
    logging.info(f"📁 Resolved index.html = {os.path.join(app.static_folder, 'index.html')}")
    return send_from_directory(app.static_folder, 'index.html')

@app.route("/check", methods=["GET"])
def check():
    logging.info("ℹ️ logging /check route")
    return "OK", 200

@app.route("/about", methods=["GET"])
def serve_pdf():
    return send_from_directory(app.static_folder, "about.pdf", mimetype="application/pdf")

@app.route("/create_playlist", methods=["POST"])
def create_playlist():
    try:
        data = request.get_json()
        code = data.get("code")
        competition_id = data.get("competition_id")
        earliest_date = data.get("earliest_date")
        api_key = request.headers.get("x-api-key")
        test_mode = request.headers.get("X-Test-Mode", "true").lower() != "false"
        input_date = datetime.fromisoformat(earliest_date)
        sg_midnight = datetime.combine(input_date.date(), datetime.min.time())  # 00:00 on selected date (SGT)
        sg_midnight_utc = sg_midnight - timedelta(hours=8)  # Convert to UTC
        cutoff_iso = sg_midnight_utc.isoformat("T") + "Z"

        if not code or not competition_id or not earliest_date or not api_key:
            return jsonify({"error": "Missing required parameters"}), 400

        # Load client secrets from Secret Manager
        client = secretmanager.SecretManagerServiceClient()

        def get_secret(name):
            resource = f"projects/{PROJECT_ID}/secrets/{name}/versions/latest"
            return client.access_secret_version(request={"name": resource}).payload.data.decode("UTF-8")

        #client_id=get_secret("V2_CLIENT_ID")
        #client_secret=get_secret("V2_CLIENT_SECRET_KEY")
        api_key=get_secret("V2_API_KEY")
        client_config=json.loads(get_secret("V2_CLIENT_JSON"))

        if api_key.strip() != api_key.strip():
            return jsonify({"error": "Unauthorized"}), 403   
        

        flow = Flow.from_client_config(
            client_config,
            scopes=["https://www.googleapis.com/auth/youtube"],
            redirect_uri=REDIRECT_URI
        )
        flow.fetch_token(code=code)
        creds = flow.credentials

        youtube = build("youtube", "v3", credentials=creds)

        if test_mode:
            try:
                test_call = youtube.channels().list(part="snippet", mine=True).execute()
                channel_title = test_call["items"][0]["snippet"]["title"] if test_call.get("items") else "Unknown Channel"

                return jsonify({
                    "message": "✅ Test mode active — YouTube API is reachable",
                    "channel": channel_title,
                    "playlist_url": "https://www.youtube.com/playlist?list=TESTMODE123"
                }), 200
            except Exception as e:
                return jsonify({
                    "error": "❌ YouTube API test failed",
                    "details": str(e)
                }), 500

        with open("channels.json") as f:
            CHANNEL_MAP = json.load(f)

        config = CHANNEL_MAP.get(competition_id)
        if not config:
            return jsonify({"error": "Unknown competition_id"}), 404

        channel_ids = config["channel_ids"]
        search_filter = config.get("search_filter", "highlights").lower()
        min_duration_seconds = config.get("min_duration_minutes", 2) * 60

        video_ids = ["Gb1iGDchKYs","Gb1iGDchKYs"]
        for channel_id in channel_ids:
            search = youtube.search().list(
                part="id,snippet",
                channelId=channel_id,
                maxResults=50,
                order="date",
                type="video"
            ).execute()

            filtered_video_ids = []
            for item in search.get("items", []):
                snippet = item["snippet"]
                title = snippet["title"]
                published_at = snippet.get("publishedAt")
                if search_filter in title.lower() and published_at >= cutoff_iso:
                    filtered_video_ids.append(item["id"]["videoId"])	

            if filtered_video_ids:
                details = youtube.videos().list(
                    part="contentDetails",
                    id=','.join(filtered_video_ids)
                ).execute()

                for item in details.get("items", []):
                    duration = item["contentDetails"]["duration"]
                    duration_seconds = isodate.parse_duration(duration).total_seconds()
                    if duration_seconds > min_duration_seconds:
                        video_ids.append(item["id"])

        if not video_ids:
            return jsonify({"message": "No matching highlight videos found."})

        playlist = youtube.playlists().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title": f"{competition_id} Highlights - {earliest_date}",
                    "description": "Auto-generated playlist"
                },
                "status": {"privacyStatus": "unlisted"}
            }
        ).execute()

        playlist_id = playlist["id"]

        for vid in video_ids:
            youtube.playlistItems().insert(
                part="snippet",
                body={
                    "snippet": {
                        "playlistId": playlist_id,
                        "resourceId": {"kind": "youtube#video", "videoId": vid}
                    }
                }
            ).execute()

        return jsonify({
            "playlist_url": f"https://www.youtube.com/playlist?list={playlist_id}",
            "video_count": len(video_ids)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500