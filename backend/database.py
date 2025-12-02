#!/usr/bin/env python3
"""MongoDB database connection and models."""

import os
from datetime import datetime
from typing import Optional, Tuple

from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from bson import ObjectId
from gridfs import GridFS, NoFile


class DatabaseManager:
    """Manages MongoDB connection and collections."""

    def __init__(self):
        mongo_uri = os.getenv(
            "MONGODB_URI", "mongodb://localhost:27017/"
        )
        db_name = os.getenv("MONGODB_DB_NAME", "asl_avatar_generator")
        
        self.client = MongoClient(mongo_uri)
        self.db: Database = self.client[db_name]
        self.users: Collection = self.db.users
        self.videos: Collection = self.db.videos
        self.fs = GridFS(self.db, collection="video_files")
        
        # Create indexes
        self.users.create_index("email", unique=True)
        self.users.create_index("username", unique=True)
        self.videos.create_index("userId")
        self.videos.create_index("createdAt")

    def get_user_by_email(self, email: str) -> Optional[dict]:
        """Get user by email."""
        return self.users.find_one({"email": email})

    def get_user_by_username(self, username: str) -> Optional[dict]:
        """Get user by username."""
        return self.users.find_one({"username": username})

    def get_user_by_id(self, user_id: str) -> Optional[dict]:
        """Get user by ID."""
        try:
            return self.users.find_one({"_id": ObjectId(user_id)})
        except Exception:
            return None

    def create_user(self, username: str, email: str, password_hash: str) -> dict:
        """Create a new user."""
        user = {
            "username": username,
            "email": email,
            "passwordHash": password_hash,
            "createdAt": datetime.utcnow(),
            "updatedAt": datetime.utcnow(),
        }
        result = self.users.insert_one(user)
        user["_id"] = result.inserted_id
        user.pop("passwordHash", None)  # Don't return password hash
        return user

    def save_video(
        self,
        user_id: str,
        job_id: str,
        transcript: str,
        video_path: str,
        filename: str,
    ) -> dict:
        """Save video translation binary to GridFS and metadata to videos collection."""
        user_object_id = ObjectId(user_id)
        created_at = datetime.utcnow()
        with open(video_path, "rb") as file_handle:
            file_id = self.fs.put(
                file_handle,
                filename=filename,
                metadata={
                    "jobId": job_id,
                    "userId": user_object_id,
                    "createdAt": created_at,
                },
            )

        video_doc = {
            "userId": user_object_id,
            "jobId": job_id,
            "transcript": transcript,
            "fileId": file_id,
            "filename": filename,
            "createdAt": created_at,
        }
        result = self.videos.insert_one(video_doc)
        video_doc["_id"] = result.inserted_id
        return video_doc

    def get_user_videos(self, user_id: str, limit: int = 50) -> list:
        """Get all videos for a user."""
        try:
            cursor = self.videos.find(
                {"userId": ObjectId(user_id)}
            ).sort("createdAt", -1).limit(limit)
            return list(cursor)
        except Exception:
            return []

    def get_video_by_job_id(self, job_id: str) -> Optional[dict]:
        """Get video metadata by job ID."""
        return self.videos.find_one({"jobId": job_id})

    def get_video_file(self, file_id) -> Optional[bytes]:
        """Retrieve raw video bytes from GridFS."""
        try:
            grid_out = self.fs.get(file_id)
            return grid_out.read()
        except (NoFile, TypeError):
            return None

    def get_video_binary_by_job(self, job_id: str) -> Tuple[Optional[dict], Optional[bytes]]:
        """Get (video_doc, binary_data) for a given job."""
        video_doc = self.get_video_by_job_id(job_id)
        if not video_doc:
            return None, None
        binary_data = None
        file_id = video_doc.get("fileId")
        if file_id:
            binary_data = self.get_video_file(file_id)
        elif video_doc.get("videoPath"):
            try:
                with open(video_doc["videoPath"], "rb") as file_handle:
                    binary_data = file_handle.read()
            except (OSError, FileNotFoundError):
                binary_data = None
        return video_doc, binary_data


# Global database instance
db_manager = DatabaseManager()

