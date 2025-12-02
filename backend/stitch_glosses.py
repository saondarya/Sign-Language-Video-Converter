#!/usr/bin/env python3
"""
stitch_glosses.py
Prototype pipeline:
 - read transcript.txt
 - read gloss_dataset.json
 - map transcript tokens -> gloss instances
 - download videos (direct http or youtube via yt-dlp)
 - crop using bbox, subclip using frame_start/frame_end and fps
 - resize and concatenate clips -> signed_output.mp4
"""

import os
import json
import re
import logging
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional
from difflib import get_close_matches
from urllib.parse import urlparse

import requests
from tqdm import tqdm

from moviepy.editor import VideoFileClip, concatenate_videoclips
import yt_dlp

# Import our ASL video search utility
from asl_video_search import ASLVideoSearcher, QuietYTDLogger

LOG_LEVEL = os.getenv("ASL_LOG_LEVEL", "INFO").upper()
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(levelname)s | %(message)s",
)

# optional lemmatizer (helps match plural -> singular)
try:
    import nltk
    from nltk.stem import WordNetLemmatizer
    try:
        nltk.data.find("corpora/wordnet")
    except Exception:
        nltk.download("wordnet", quiet=True)
    lemmatizer = WordNetLemmatizer()
except Exception:
    lemmatizer = None
    logger.warning("nltk not available or wordnet missing; continuing without lemmatization.")


@dataclass
class ClipRecord:
    token: str
    status: str
    detail: str = ""
    path: Optional[Path] = None


def sanitize_for_filename(token: str, fallback: str) -> str:
    """Return a filesystem-safe token label."""
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", token.strip() or "")
    return safe or fallback


def create_text_placeholder(clips_dir: Path, token: str, index: int,
                            title: str, lines: List[str], suffix: str) -> Path:
    """Create a small text placeholder file summarising why no clip is available."""
    safe_tok = sanitize_for_filename(token, f"token_{index}")
    out_path = Path(clips_dir) / f"{safe_tok}_{index}_{suffix}.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join([title, *lines])
    out_path.write_text(content, encoding="utf-8")
    return out_path


def load_dataset(json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    gloss_map = {}
    for entry in data:
        gloss = (entry.get("gloss") or "").strip().lower()
        if not gloss:
            continue
        instances = entry.get("instances", [])
        if instances:
            gloss_map[gloss] = instances
    return gloss_map


def normalize_token(token):
    token = re.sub(r"[^\w\s]", "", token).strip().lower()
    if lemmatizer:
        try:
            token = lemmatizer.lemmatize(token)
        except Exception:
            pass
    return token


def choose_instance_with_online_search(
    gloss_map,
    word,
    enable_online_search=True,
    searcher: Optional[ASLVideoSearcher] = None,
):
    """
    Return a chosen instance dict for a given normalized word, or None.
    If not found in local dataset and online search is enabled, search online.
    """
    if not word:
        return None
        
    # First, try the original logic
    if word in gloss_map:
        return gloss_map[word][0]  # pick the first instance
    
    # Try close match (e.g., minor spelling differences)
    matches = get_close_matches(word, list(gloss_map.keys()), n=1, cutoff=0.8)
    if matches:
        return gloss_map[matches[0]][0]
    
    # If not found locally and online search is enabled, search online
    if enable_online_search:
        if searcher is None:
            searcher = ASLVideoSearcher(cache_dir="work/online_cache")
        logger.info("Gloss '%s' not found locally, searching online...", word)
        try:
            logger.debug("Calling search_for_gloss for '%s'", word)
            results = searcher.search_for_gloss(word, max_results=1)
            logger.debug("search_for_gloss returned %d results", len(results))
            
            if results:
                video_info = results[0]
                logger.info("Found online video for '%s': %s", word, video_info["title"])
                
                # Create a synthetic instance that matches the expected format
                synthetic_instance = {
                    'url': video_info['url'],
                    'video_id': f"online_{video_info.get('id', word)}",
                    'gloss': word,
                    'source': video_info.get('source', 'online_search'),
                    'title': video_info['title'],
                    'fps': 30,  # Default FPS
                    'frame_start': 1,
                    'frame_end': min(300, video_info.get('duration', 10) * 30),  # Max 10 seconds
                    'bbox': None  # No cropping for online videos initially
                }
                return synthetic_instance
            else:
                logger.info("No suitable online video found for '%s'", word)
        except Exception as e:
            logger.exception("Online search failed for '%s': %s", word, e)
    
    return None


def download_url(url, dest_path):
    """Download url to dest_path. Supports direct http and youtube (yt-dlp)."""
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    if dest_path.exists():
        logger.info("[cached] %s", dest_path)
        return str(dest_path)

    if "youtube.com" in url or "youtu.be" in url or "v=" in url:
        # use yt-dlp to fetch a mp4
        ydl_opts = {
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "outtmpl": str(dest_path),
            "noplaylist": True,
            "quiet": True,
            "merge_output_format": "mp4",
            "logger": QuietYTDLogger(),
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            return str(dest_path)
        except Exception as e:
            logger.error("yt-dlp failed for %s: %s", url, e)
            raise
    else:
        # HTTP streaming download
        resp = requests.get(url, stream=True, timeout=30)
        resp.raise_for_status()
        total = int(resp.headers.get("content-length", 0))
        with open(dest_path, "wb") as f:
            for chunk in tqdm(resp.iter_content(chunk_size=8192), total=(total // 8192 + 1), unit="KB", desc=f"dl {dest_path.name}"):
                if chunk:
                    f.write(chunk)
        return str(dest_path)


def crop_and_subclip(src_path, instance, out_path, target_size=(640, 480)):
    """Open src_path, take subclip from frame_start to frame_end (using fps),
       crop to bbox, resize to target_size and write out_path."""
    clip = VideoFileClip(src_path)
    bbox = instance.get("bbox", None)  # [x1, y1, x2, y2]
    fps = instance.get("fps", None) or round(clip.fps)
    fs = instance.get("frame_start", 1)
    fe = instance.get("frame_end", -1)

    # convert frame indices -> seconds. dataset frames often 1-based, so subtract 1.
    start_sec = max(0, (fs - 1) / fps) if fs is not None else 0
    end_sec = None if fe == -1 or fe is None else min(clip.duration, fe / fps)

    if end_sec:
        sub = clip.subclip(start_sec, end_sec)
    else:
        sub = clip.subclip(start_sec)

    # Crop if bbox is present
    if bbox and len(bbox) == 4:
        x1, y1, x2, y2 = bbox
        # ensure within clip bounds
        x1 = max(0, min(clip.w, x1))
        x2 = max(0, min(clip.w, x2))
        y1 = max(0, min(clip.h, y1))
        y2 = max(0, min(clip.h, y2))
        try:
            sub = sub.crop(x1=x1, y1=y1, x2=x2, y2=y2)
        except Exception as e:
            logger.warning("Crop failed for bbox %s: %s", bbox, e)

    # resize to uniform size
    sub = sub.resize(newsize=target_size)

    # write out (no audio for the signed output)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sub.write_videofile(str(out_path), codec="libx264", audio=False, verbose=False, logger=None)

    # close clips
    clip.close()
    sub.close()
    return str(out_path)


def build_signed_video(transcript_path="transcript.txt", dataset_json="gloss_dataset.json",
                       workdir="work", output="signed_output.mp4", enable_online_search=True):
    # --- read transcript
    with open(transcript_path, "r", encoding="utf-8") as f:
        text = f.read()

    tokens = [normalize_token(tok) for tok in re.split(r"\s+", text) if tok.strip()]
    logger.info("Tokens (sample): %s", tokens[:30])

    # --- load dataset mapping
    logger.info("Loading dataset...")
    gloss_map = load_dataset(dataset_json)
    logger.info("Dataset has %d gloss entries.", len(gloss_map))

    # --- prepare work dirs
    downloads_dir = Path(workdir) / "downloads"
    clips_dir = Path(workdir) / "clips"
    online_cache_dir = Path(workdir) / "online_cache"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    clips_dir.mkdir(parents=True, exist_ok=True)
    online_cache_dir.mkdir(parents=True, exist_ok=True)

    clip_objs: List[VideoFileClip] = []
    exit_stack = ExitStack()
    records: List[ClipRecord] = []
    online_searcher = ASLVideoSearcher(cache_dir=str(online_cache_dir)) if enable_online_search else None
    online_failure_count = 0
    max_online_failures = 5
    online_disabled = False

    for i, tok in enumerate(tokens):
        instance = choose_instance_with_online_search(
            gloss_map,
            tok,
            enable_online_search,
            searcher=online_searcher,
        )
        if not instance:
            logger.warning("No gloss found for token '%s' — skipping", tok)
            records.append(ClipRecord(token=tok, status="missing", detail="no gloss found"))
            continue

        url = instance.get("url")
        if not url:
            logger.warning("No URL for gloss '%s' — skipping", tok)
            records.append(ClipRecord(token=tok, status="missing", detail="missing url"))
            continue

        # Handle both local dataset videos and online videos
        is_online_video = instance.get('source') == 'online_search'
        is_fingerspelling = instance.get('source') == 'fingerspelling'
        is_fallback_source = instance.get('source', '').startswith('fallback_')
        
        if is_fingerspelling:
            # Special handling for finger spelling
            logger.info("Using finger spelling for token '%s'", tok)
            out_clip_file = create_text_placeholder(
                clips_dir,
                tok,
                i,
                "FINGER SPELL PLACEHOLDER",
                [f"Token: {tok.upper()}"],
                suffix="fingerspell",
            )
            logger.info("Created finger spelling placeholder for '%s'", tok)
            records.append(ClipRecord(token=tok, status="placeholder", detail="fingerspelling placeholder", path=out_clip_file))
            continue  # Skip video processing for finger spelling
            
        elif is_fallback_source:
            # Handle fallback sources (Lifeprint, SigningSavvy, etc.)
            logger.info("Using fallback source for token '%s': %s", tok, instance.get('source'))
            try:
                # For fallback sources, create an informational placeholder
                # In a real implementation, you might scrape these sites or use their APIs
                out_clip_file = create_text_placeholder(
                    clips_dir,
                    tok,
                    i,
                    "ASL SIGN REFERENCE",
                    [
                        f"Token: {tok.upper()}",
                        f"Title: {instance.get('title', 'Unknown')}",
                        f"Source: {instance.get('source', 'Unknown')}",
                        f"URL: {instance.get('url', 'Unknown')}",
                        "Note: Review this resource manually.",
                    ],
                    suffix="fallback",
                )
                logger.info("Created fallback reference for '%s' from %s", tok, instance.get('source'))
                records.append(ClipRecord(token=tok, status="placeholder", detail=f"fallback: {instance.get('source')}", path=out_clip_file))
                continue  # Skip video processing, just create reference
            except Exception as e:
                logger.error("Fallback processing failed for '%s': %s", tok, e)
                records.append(ClipRecord(token=tok, status="failed", detail=f"fallback handling failed: {e}"))
                continue
                
        elif is_online_video:
            parsed_url = urlparse(url)
            if parsed_url.scheme not in ("http", "https"):
                logger.info("Token '%s' returned synthetic URL '%s'; creating placeholder instead.", tok, url)
                placeholder = create_text_placeholder(
                    clips_dir,
                    tok,
                    i,
                    "SYNTHETIC PLACEHOLDER",
                    [
                        f"Token: {tok.upper()}",
                        "Source requested a generated clip; no downloadable media available.",
                    ],
                    suffix="synthetic",
                )
                records.append(ClipRecord(token=tok, status="placeholder", detail="synthetic placeholder", path=placeholder))
                continue

            if online_disabled:
                logger.warning("Skipping online download for '%s' due to repeated failures.", tok)
                placeholder = create_text_placeholder(
                    clips_dir,
                    tok,
                    i,
                    "ONLINE DOWNLOAD SKIPPED",
                    [
                        f"Token: {tok.upper()}",
                        "Reason: Online downloads disabled after repeated failures.",
                    ],
                    suffix="online_disabled",
                )
                records.append(ClipRecord(token=tok, status="placeholder", detail="online disabled", path=placeholder))
                continue

            # For online videos, download using our ASL video searcher
            logger.info("Downloading online video for token '%s' -> %s", tok, url)
            try:
                searcher = online_searcher or ASLVideoSearcher(cache_dir=str(online_cache_dir))
                # Create a video_info dict from the instance
                video_info = {
                    'url': url,
                    'id': instance.get('video_id', f'online_{tok}_{i}'),
                    'title': instance.get('title', f'ASL {tok}'),
                    'source': instance.get('source', 'youtube'),
                    'duration': (instance.get('frame_end', 300) - instance.get('frame_start', 1)) / instance.get('fps', 30)
                }
                
                # Download and process the video
                processed_path = searcher.download_and_process_video(
                    video_info, tok, str(downloads_dir), max_duration=10
                )
                
                if processed_path and os.path.exists(processed_path):
                    src_file = Path(processed_path)
                    logger.info("Successfully downloaded online video for '%s' to %s", tok, src_file)
                    online_failure_count = 0
                else:
                    logger.error("Failed to download online video for '%s'", tok)
                    online_failure_count += 1
                    placeholder = create_text_placeholder(
                        clips_dir,
                        tok,
                        i,
                        "ONLINE DOWNLOAD FAILED",
                        [
                            f"Token: {tok.upper()}",
                            "Reason: Download returned empty path.",
                        ],
                        suffix="online_failed",
                    )
                    records.append(ClipRecord(token=tok, status="failed", detail="online download returned empty path", path=placeholder))
                    if online_failure_count >= max_online_failures:
                        online_disabled = True
                    continue
                    
            except Exception as e:
                logger.error("Online download failed for token '%s': %s", tok, e)
                online_failure_count += 1
                placeholder = create_text_placeholder(
                    clips_dir,
                    tok,
                    i,
                    "ONLINE DOWNLOAD FAILED",
                    [
                        f"Token: {tok.upper()}",
                        f"Reason: {e}",
                    ],
                    suffix="online_failed",
                )
                records.append(ClipRecord(token=tok, status="failed", detail=f"online download failed: {e}", path=placeholder))
                if online_failure_count >= max_online_failures:
                    online_disabled = True
                continue
        else:
            # For local dataset videos, use existing download logic
            vid_id = instance.get("video_id") or f"{sanitize_for_filename(tok, f'token_{i}')}_{i}"
            src_file = downloads_dir / f"{vid_id}.mp4"
            try:
                logger.info("Downloading for token '%s' -> %s", tok, url)
                download_url(url, src_file)
            except Exception as e:
                logger.error("Download failed for token '%s': %s", tok, e)
                placeholder = create_text_placeholder(
                    clips_dir,
                    tok,
                    i,
                    "LOCAL DOWNLOAD FAILED",
                    [
                        f"Token: {tok.upper()}",
                        f"Reason: {e}",
                    ],
                    suffix="local_failed",
                )
                records.append(ClipRecord(token=tok, status="failed", detail=f"download failed: {e}", path=placeholder))
                continue

        out_clip_file = clips_dir / f"{sanitize_for_filename(tok, f'token_{i}')}_{i}.mp4"
        try:
            logger.info("Processing clip for '%s'...", tok)
            
            # For online videos, we may skip cropping if no bbox is provided
            if is_online_video and not instance.get('bbox'):
                # For online videos without bbox, just copy/link the file
                import shutil
                shutil.copy2(str(src_file), str(out_clip_file))
                logger.info("Copied online video for '%s' (no cropping needed)", tok)
            else:
                # Use the original cropping logic
                crop_and_subclip(str(src_file), instance, str(out_clip_file))
                
            # load clip object to append for final concat
            clip_objs.append(exit_stack.enter_context(VideoFileClip(str(out_clip_file))))
            records.append(ClipRecord(token=tok, status="success", path=out_clip_file))
        except Exception as e:
            logger.error("Processing failed for token '%s': %s", tok, e)
            records.append(ClipRecord(token=tok, status="failed", detail=f"processing failed: {e}"))
            continue

    if not clip_objs:
        logger.error("No clips were produced. Exiting.")
        return

    logger.info("Concatenating %d clips...", len(clip_objs))
    try:
        final = concatenate_videoclips(clip_objs, method="compose")
        final.write_videofile(output, fps=25, codec="libx264")
        final.close()
    finally:
        exit_stack.close()
    logger.info("Finished. Output: %s", output)

    success_count = sum(1 for r in records if r.status == "success")
    placeholder_count = sum(1 for r in records if r.status == "placeholder")
    failure_count = sum(1 for r in records if r.status not in {"success", "placeholder"})
    logger.info(
        "Summary -> success: %s | placeholder: %s | failed/missing: %s",
        success_count,
        placeholder_count,
        failure_count,
    )


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--transcript", default="transcript.txt")
    parser.add_argument("--dataset", default="gloss_dataset.json")
    parser.add_argument("--workdir", default="work")
    parser.add_argument("--output", default="signed_output.mp4")
    parser.add_argument("--enable-online-search", action="store_true", default=True,
                       help="Enable online search for missing glosses (default: True)")
    parser.add_argument("--disable-online-search", action="store_true", 
                       help="Disable online search, use only local dataset")
    args = parser.parse_args()
    
    # Handle the online search flag
    enable_online_search = args.enable_online_search and not args.disable_online_search
    
    logger.info("Online search: %s", "enabled" if enable_online_search else "disabled")

    build_signed_video(transcript_path=args.transcript,
                       dataset_json=args.dataset,
                       workdir=args.workdir,
                       output=args.output,
                       enable_online_search=enable_online_search)
