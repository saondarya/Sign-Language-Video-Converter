#!/usr/bin/env python3
"""
Simple Flask API that accepts a video upload, transcribes it with Whisper,
and runs stitch_glosses to generate a signed output video.
"""

import os
import uuid
import logging
from io import BytesIO
from pathlib import Path
from functools import wraps

from flask import Flask, request, jsonify, send_file, make_response

from transcribe_service import TranscribeService
from stitch_glosses import build_signed_video
from database import db_manager
from auth import hash_password, verify_password, create_access_token, decode_access_token

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=getattr(
        logging,
        os.getenv("API_LOG_LEVEL", "INFO").upper(),
        logging.INFO,
    ),
    format="%(levelname)s | %(message)s",
)

WORK_DIR = Path(os.getenv("ASL_WORKDIR", "work"))
UPLOAD_DIR = WORK_DIR / "api_uploads"
OUTPUT_DIR = WORK_DIR / "api_outputs"
DATASET_PATH = Path(os.getenv("ASL_GLOSS_DATASET", "gloss_dataset.json"))

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
transcriber = TranscribeService(model_name=os.getenv("WHISPER_MODEL", "base"))


def _corsify(response):
    response.headers["Access-Control-Allow-Origin"] = os.getenv("FRONTEND_ORIGIN", "*")
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
    return response


def get_current_user():
    """Extract current user from JWT token."""
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None
    
    token = auth_header.split(" ")[1]
    payload = decode_access_token(token)
    if not payload:
        return None
    
    user_id = payload.get("sub")
    if not user_id:
        return None
    
    user = db_manager.get_user_by_id(user_id)
    return user


def require_auth(f):
    """Decorator to require authentication."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = get_current_user()
        if not user:
            return jsonify({"error": "Authentication required"}), 401
        request.current_user = user
        return f(*args, **kwargs)
    return decorated_function


@app.after_request
def add_cors_headers(response):
    return _corsify(response)


@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Resource not found"}), 404


@app.errorhandler(500)
def internal_error(error):
    logger.exception("Internal server error: %s", error)
    return jsonify({"error": "Internal server error"}), 500


@app.errorhandler(Exception)
def handle_exception(e):
    logger.exception("Unhandled exception: %s", e)
    return jsonify({"error": "An unexpected error occurred"}), 500


@app.route("/api/auth/signup", methods=["POST", "OPTIONS"])
def signup():
    if request.method == "OPTIONS":
        return _corsify(make_response("", 200))
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Missing request body"}), 400
        
        username = data.get("username", "").strip()
        email = data.get("email", "").strip().lower()
        password = data.get("password", "")
        
        if not username or not email or not password:
            return jsonify({"error": "Username, email, and password are required"}), 400
        
        if len(password) < 6:
            return jsonify({"error": "Password must be at least 6 characters"}), 400
        
        # Check if user already exists
        try:
            if db_manager.get_user_by_email(email):
                return jsonify({"error": "Email already registered"}), 400
            
            if db_manager.get_user_by_username(username):
                return jsonify({"error": "Username already taken"}), 400
        except Exception as db_check_error:
            logger.exception("Database error during user check: %s", db_check_error)
            return jsonify({"error": "Database connection error. Please check if MongoDB is running."}), 500
        
        # Create user
        try:
            password_hash = hash_password(password)
            user = db_manager.create_user(username, email, password_hash)
        except Exception as create_error:
            logger.exception("Error creating user: %s", create_error)
            # Check if it's a duplicate key error
            error_str = str(create_error).lower()
            if "duplicate" in error_str or "e11000" in error_str:
                if "email" in error_str:
                    return jsonify({"error": "Email already registered"}), 400
                elif "username" in error_str:
                    return jsonify({"error": "Username already taken"}), 400
            return jsonify({"error": "Failed to create user. Please try again."}), 500
        
        # Create access token
        try:
            token = create_access_token(data={"sub": str(user["_id"])})
        except Exception as token_error:
            logger.exception("Error creating token: %s", token_error)
            return jsonify({"error": "Failed to create authentication token"}), 500
        
        return jsonify({
            "message": "User created successfully",
            "user": {
                "id": str(user["_id"]),
                "username": user["username"],
                "email": user["email"],
            },
            "token": token,
        }), 201
    except Exception as e:
        logger.exception("Unexpected error in signup: %s", e)
        return jsonify({"error": "An unexpected error occurred during signup"}), 500


@app.route("/api/auth/login", methods=["POST", "OPTIONS"])
def login():
    if request.method == "OPTIONS":
        return _corsify(make_response("", 200))
    
    data = request.get_json()
    if not data:
        return jsonify({"error": "Missing request body"}), 400
    
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    
    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400
    
    # Get user
    user = db_manager.get_user_by_email(email)
    if not user:
        return jsonify({"error": "Invalid email or password"}), 401
    
    # Verify password
    if not verify_password(password, user["passwordHash"]):
        return jsonify({"error": "Invalid email or password"}), 401
    
    # Create access token
    token = create_access_token(data={"sub": str(user["_id"])})
    
    return jsonify({
        "message": "Login successful",
        "user": {
            "id": str(user["_id"]),
            "username": user["username"],
            "email": user["email"],
        },
        "token": token,
    })


@app.route("/api/auth/me", methods=["GET", "OPTIONS"])
@require_auth
def get_current_user_info():
    if request.method == "OPTIONS":
        return _corsify(make_response("", 200))
    
    user = request.current_user
    return jsonify({
        "id": str(user["_id"]),
        "username": user["username"],
        "email": user["email"],
    })


@app.route("/api/process", methods=["POST", "OPTIONS"])
@require_auth
def process_video():
    if request.method == "OPTIONS":
        return _corsify(make_response("", 200))

    user = request.current_user
    file = request.files.get("video")
    if not file:
        return jsonify({"error": "Missing video file in 'video' field."}), 400

    job_id = uuid.uuid4().hex
    upload_path = UPLOAD_DIR / f"{job_id}.mp4"
    file.save(upload_path)
    logger.info("Received upload %s -> %s from user %s", job_id, upload_path, user["_id"])

    transcribe_result = transcriber.transcribe_video(str(upload_path))
    if not transcribe_result.get("success"):
        logger.error("Transcription failed for %s: %s", job_id, transcribe_result.get("error"))
        return jsonify({"error": transcribe_result.get("error", "Transcription failed")}), 500

    transcript_text = transcribe_result["text"]
    transcript_path = OUTPUT_DIR / f"{job_id}_transcript.txt"
    transcript_path.write_text(transcript_text, encoding="utf-8")

    video_filename = f"{job_id}_signed.mp4"
    output_video_path = OUTPUT_DIR / video_filename
    try:
        build_signed_video(
            transcript_path=str(transcript_path),
            dataset_json=str(DATASET_PATH),
            workdir=str(WORK_DIR),
            output=str(output_video_path),
            enable_online_search=True,
        )
    except Exception as exc:
        logger.exception("Stitching failed for %s: %s", job_id, exc)
        return jsonify({"error": "Failed to generate ASL video"}), 500

    # Save video to MongoDB
    try:
        db_manager.save_video(
            user_id=str(user["_id"]),
            job_id=job_id,
            transcript=transcript_text,
            video_path=str(output_video_path),
            filename=video_filename,
        )
        logger.info("Saved video %s to database for user %s", job_id, user["_id"])
        try:
            output_video_path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Unable to delete temp video %s", output_video_path)
    except Exception as exc:
        logger.exception("Failed to save video to database: %s", exc)
        # Don't fail the request if DB save fails

    return jsonify(
        {
            "jobId": job_id,
            "transcript": transcript_text,
            "videoUrl": f"/output/{job_id}",
        }
    )


@app.route("/api/output/<job_id>", methods=["GET", "OPTIONS"])
def download_output(job_id):
    if request.method == "OPTIONS":
        return _corsify(make_response("", 200))
    
    video_doc, binary_data = db_manager.get_video_binary_by_job(job_id)
    if not video_doc or not binary_data:
        logger.warning("Video not found in MongoDB for job_id=%s", job_id)
        return jsonify({"error": "Output video not found"}), 404
    
    file_stream = BytesIO(binary_data)
    file_stream.seek(0)
    response = send_file(
        file_stream,
        mimetype="video/mp4",
        as_attachment=False,
        download_name=video_doc.get("filename", f"{job_id}_signed.mp4"),
    )
    return _corsify(response)


@app.route("/api/transcript/<job_id>", methods=["GET", "OPTIONS"])
def fetch_transcript(job_id):
    if request.method == "OPTIONS":
        return _corsify(make_response("", 200))
    
    video_doc = db_manager.get_video_by_job_id(job_id)
    transcript_text = video_doc.get("transcript") if video_doc else None
    if not transcript_text:
        transcript_path = OUTPUT_DIR / f"{job_id}_transcript.txt"
        if not transcript_path.exists():
            return jsonify({"error": "Transcript not found"}), 404
        transcript_text = transcript_path.read_text(encoding="utf-8")
    
    response = make_response(transcript_text)
    response.headers["Content-Type"] = "text/plain; charset=utf-8"
    response.headers["Content-Disposition"] = f'inline; filename="{job_id}_transcript.txt"'
    return _corsify(response)


@app.route("/api/videos", methods=["GET", "OPTIONS"])
@require_auth
def get_user_videos():
    if request.method == "OPTIONS":
        return _corsify(make_response("", 200))
    
    user = request.current_user
    limit = request.args.get("limit", 50, type=int)
    
    videos = db_manager.get_user_videos(str(user["_id"]), limit=limit)
    
    # Convert ObjectId to string and format response
    video_list = []
    for video in videos:
        video_list.append({
            "id": str(video["_id"]),
            "jobId": video["jobId"],
            "transcript": video["transcript"],
            "videoUrl": f"/output/{video['jobId']}",
            "createdAt": video["createdAt"].isoformat() if "createdAt" in video else None,
        })
    
    return jsonify({"videos": video_list})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5031)), debug=False)


