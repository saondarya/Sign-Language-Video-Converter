#!/usr/bin/env python3
"""
ASL Video Search Utility

This module provides functionality to search for and download ASL (American Sign Language) 
videos from various online sources when they are not available in the local dataset.

Supported sources:
- YouTube (via yt-dlp)
- Future: SigningSavvy, Handspeak, ASL dictionaries, etc.
"""

import os
import json
import re
import time
import hashlib
import subprocess
import logging
from urllib.parse import quote
from typing import List, Dict, Optional

import requests
import yt_dlp

logger = logging.getLogger(__name__)
__all__ = ["ASLVideoSearcher", "QuietYTDLogger"]


class QuietYTDLogger:
    """Suppress noisy yt-dlp output while keeping errors."""

    def debug(self, msg):
        logger.debug("[yt-dlp] %s", msg)

    def info(self, msg):
        logger.debug("[yt-dlp] %s", msg)

    def warning(self, msg):
        # Downgrade yt-dlp warnings to DEBUG to keep CLI output clean
        logger.debug("[yt-dlp warning] %s", msg)

    def error(self, msg):
        logger.error("[yt-dlp error] %s", msg)


def _route_print(*args, **kwargs):
    """Route legacy print statements through logging so they honour log level."""
    message = " ".join(str(arg) for arg in args).strip()
    if not message:
        return

    lowered = message.lower()
    if "debug" in lowered:
        logger.debug(message.replace("DEBUG:", "").strip())
    elif lowered.startswith("error"):
        logger.error(message)
    else:
        logger.info(message)


# Ensure legacy print statements log quietly instead of writing to stdout
print = _route_print


class ASLVideoSearcher:
    """Main class for searching and downloading ASL videos from online sources."""
    
    def __init__(self, cache_dir: str = "/tmp/asl_cache"):
        """
        Initialize the ASL video searcher.
        
        Args:
            cache_dir: Directory to cache downloaded videos and metadata
        """
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        
    def search_for_gloss(self, gloss: str, max_results: int = 3) -> List[Dict]:
        """
        Search for ASL videos for a given gloss across multiple sources.
        
        Args:
            gloss: The ASL gloss to search for
            max_results: Maximum number of results to return
            
        Returns:
            List of video metadata dictionaries
        """
        results = []
        
        # Clean up the gloss for searching
        clean_gloss = self._clean_gloss_for_search(gloss)
        
        try:
            # First try YouTube search
            youtube_results = self._search_youtube(clean_gloss, max_results)
            results.extend(youtube_results)
            
            # If YouTube fails, try fallback sources
            if not results:
                print(f"    DEBUG: YouTube search failed, trying fallback sources...")
                fallback_results = self._search_fallback_sources(gloss, max_results)
                results.extend(fallback_results)
            
            # Search additional ASL sources if YouTube doesn't find enough
            if len(results) < max_results:
                additional_results = self._search_additional_sources(clean_gloss, max_results - len(results))
                results.extend(additional_results)
            
        except Exception as e:
            print(f"Error searching for gloss '{gloss}': {e}")
            
        return results[:max_results]
    
    def download_and_process_video(self, video_info: Dict, gloss: str, 
                                 output_dir: str, max_duration: int = 10) -> Optional[str]:
        """
        Download and process a video for use as ASL content.
        
        Args:
            video_info: Video metadata dictionary from search results
            gloss: The gloss this video represents
            output_dir: Directory to save the processed video
            max_duration: Maximum duration to extract from video (seconds)
            
        Returns:
            Path to processed video file, or None if failed
        """
        try:
            video_url = video_info['url']
            video_id = video_info.get('id', str(int(time.time())))
            
            # Create output directory
            os.makedirs(output_dir, exist_ok=True)
            
            # Download the video
            temp_path = os.path.join(self.cache_dir, f"temp_{video_id}")
            
            ydl_opts = {
                'format': 'best[height<=720][ext=mp4]/best[ext=mp4]/best',
                'outtmpl': f'{temp_path}.%(ext)s',
                'quiet': True,
                'no_warnings': True,
                'logger': QuietYTDLogger(),
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])
            
            # Find the downloaded file
            downloaded_files = [f for f in os.listdir(self.cache_dir) 
                              if f.startswith(f"temp_{video_id}")]
            
            if not downloaded_files:
                print(f"No file downloaded for video {video_id}")
                return None
                
            downloaded_path = os.path.join(self.cache_dir, downloaded_files[0])
            
            # Process the video
            processed_path = os.path.join(output_dir, f"{gloss}_{video_id}.mp4")
            success = self._process_video(downloaded_path, processed_path, max_duration)
            
            # Clean up temp file
            if os.path.exists(downloaded_path):
                os.remove(downloaded_path)
                
            if success:
                # Store metadata
                self._store_video_metadata(gloss, video_info, processed_path)
                return processed_path
            else:
                return None
                
        except Exception as e:
            print(f"Error downloading/processing video for gloss '{gloss}': {e}")
            return None
    
    def _clean_gloss_for_search(self, gloss: str) -> str:
        """Clean up gloss string for better search results."""
        # Replace common ASL notation with more searchable terms
        clean_gloss = gloss.replace('-', ' ').replace('_', ' ')
        clean_gloss = re.sub(r'[^\w\s]', '', clean_gloss)
        
        # Handle common ASL patterns
        if clean_gloss.startswith('IX'):
            if '1P' in clean_gloss:
                clean_gloss = 'I me myself'
            elif '2P' in clean_gloss:
                clean_gloss = 'you your'
            elif '3P' in clean_gloss:
                clean_gloss = 'he she they'
        
        return clean_gloss.strip().lower()
    
    def _search_youtube(self, query: str, max_results: int = 3) -> List[Dict]:
        """Search YouTube for ASL videos with improved search strategies."""
        try:
            # Try multiple search strategies for better results
            search_strategies = [
                f"ASL sign language {query}",
                f"American Sign Language {query}",
                f"{query} ASL sign",
                f"how to sign {query} ASL",
                f"{query} deaf sign language"
            ]
            
            all_videos = []
            
            print(f"    DEBUG: Starting YouTube search for '{query}'")
            
            # Try each search strategy (limit to avoid too many requests)
            for search_query in search_strategies[:2]:
                try:
                    print(f"    DEBUG: Trying search strategy: '{search_query}'")
                    ydl_opts = {
                        'quiet': True,
                        'no_warnings': True,
                        'extract_flat': True,
                        'default_search': f'ytsearch{max_results + 2}:',  # Get extra to filter
                        'logger': QuietYTDLogger(),
                    }
                    
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        search_results = ydl.extract_info(search_query, download=False)
                    
                    print(f"    DEBUG: Raw search results: {len(search_results.get('entries', [])) if search_results else 0}")
                    
                    if search_results and 'entries' in search_results:
                        for entry in search_results['entries']:
                            if not entry:
                                continue
                                
                            title = entry.get('title', '').lower()
                            print(f"    DEBUG: Checking video: {title[:50]}...")
                            
                            # Enhanced filtering for ASL content
                            asl_keywords = [
                                'asl', 'sign language', 'signing', 'deaf', 'interpreter',
                                'american sign language', 'signs', 'gesture', 'manual',
                                'lifeprint', 'dr. vicars', 'bill vicars'
                            ]
                            
                            # Check if title contains ASL-related keywords
                            has_asl_keyword = any(keyword in title for keyword in asl_keywords)
                            print(f"    DEBUG: Has ASL keyword: {has_asl_keyword}")
                            
                            # Additional filtering - avoid obviously irrelevant content
                            avoid_keywords = [
                                'music video', 'movie trailer', 'song', 'dance', 'concert',
                                'gaming', 'gameplay', 'reaction', 'review', 'comedy', 'funny',
                                'makeup', 'fashion', 'cooking', 'sports'
                            ]
                            has_avoid_keyword = any(keyword in title for keyword in avoid_keywords)
                            print(f"    DEBUG: Has avoid keyword: {has_avoid_keyword}")
                            
                            if has_asl_keyword and not has_avoid_keyword:
                                duration = entry.get('duration', 0) or 0
                                print(f"    DEBUG: Video duration: {duration}s")
                                # Accept a wider range of durations, but prefer shorter ones
                                if duration <= 600:  # Up to 10 minutes
                                    video_info = {
                                        'title': entry.get('title', ''),
                                        'url': f"https://www.youtube.com/watch?v={entry.get('id', '')}",
                                        'id': entry.get('id', ''),
                                        'duration': duration,
                                        'uploader': entry.get('uploader', ''),
                                        'source': 'youtube',
                                        'relevance_score': self._calculate_relevance(title, query, search_query)
                                    }
                                    all_videos.append(video_info)
                                    print(f"    DEBUG: Added video: {video_info['title']}")
                                else:
                                    print(f"    DEBUG: Video too long ({duration}s), skipping")
                                    
                except Exception as e:
                    print(f"    DEBUG: Search strategy '{search_query}' failed: {e}")
                    continue
            
            print(f"    DEBUG: Total videos found before dedup: {len(all_videos)}")
            
            # Remove duplicates and sort by relevance
            seen_ids = set()
            unique_videos = []
            for video in all_videos:
                if video['id'] not in seen_ids:
                    seen_ids.add(video['id'])
                    unique_videos.append(video)
            
            unique_videos.sort(key=lambda x: x['relevance_score'], reverse=True)
            print(f"    DEBUG: Final unique videos: {len(unique_videos)}")
            return unique_videos[:max_results]
            
        except Exception as e:
            print(f"    DEBUG: YouTube search failed for '{query}': {e}")
            import traceback
            print(f"    DEBUG: Traceback: {traceback.format_exc()}")
            return []
    
    def _search_fallback_sources(self, gloss: str, max_results: int = 1) -> List[Dict]:
        """Fallback method when YouTube search fails - use known ASL video sources."""
        fallback_videos = []
        
        print(f"    DEBUG: Trying fallback sources for '{gloss}'")
        
        # Known working ASL video URLs (verified working sources)
        known_asl_videos = {
            'video': {
                'title': 'ASL Sign for Video - Handspeak',
                'url': 'https://www.handspeak.com/word/search/index.php?id=2286',
                'duration': 3,
                'source': 'handspeak'
            },
            'computer': {
                'title': 'ASL Sign for Computer - SigningSavvy', 
                'url': 'https://www.signingsavvy.com/sign/COMPUTER/722/1',
                'duration': 3,
                'source': 'signingsavvy'
            },
            'hello': {
                'title': 'ASL Sign for Hello - Lifeprint',
                'url': 'https://www.lifeprint.com/asl101/pages-signs/h/hello.htm',
                'duration': 2,
                'source': 'lifeprint'
            },
            'technology': {
                'title': 'ASL Sign for Technology',
                'url': 'https://www.signingsavvy.com/sign/TECHNOLOGY',
                'duration': 4,
                'source': 'signingsavvy'
            },
            'software': {
                'title': 'ASL Sign for Software',
                'url': 'https://www.signingsavvy.com/sign/SOFTWARE', 
                'duration': 3,
                'source': 'signingsavvy'
            },
            'editing': {
                'title': 'ASL Sign for Edit/Editing',
                'url': 'https://www.signingsavvy.com/sign/EDIT',
                'duration': 3,
                'source': 'signingsavvy'
            }
        }
        
        # Check if we have a known mapping
        gloss_lower = gloss.lower()
        if gloss_lower in known_asl_videos:
            video_data = known_asl_videos[gloss_lower]
            fallback_video = {
                'title': video_data['title'],
                'url': video_data['url'],
                'id': f"fallback_{gloss}",
                'duration': video_data['duration'],
                'uploader': video_data['source'].title(),
                'source': f"fallback_{video_data['source']}",
                'relevance_score': 8.0  # High score for known good sources
            }
            fallback_videos.append(fallback_video)
            print(f"    DEBUG: Found fallback video for '{gloss}': {video_data['title']}")
        
        # If no known video, create finger spelling fallback
        if not fallback_videos:
            print(f"    DEBUG: Creating finger spelling fallback for '{gloss}'")
            synthetic_video = {
                'title': f'Finger Spelling: {gloss.upper()}',
                'url': 'synthetic://fingerspelling',
                'id': f"fingerspell_{gloss}",
                'duration': len(gloss) * 2,
                'uploader': 'ASL System',
                'source': 'fingerspelling',
                'relevance_score': 1.0
            }
            fallback_videos.append(synthetic_video)
        
        return fallback_videos[:max_results]
    
    def _search_additional_sources(self, query: str, max_results: int = 2) -> List[Dict]:
        """Search additional ASL video sources like Lifeprint, SigningSavvy, etc."""
        additional_videos = []
        
        try:
            # Search for Lifeprint.com videos
            lifeprint_results = self._search_lifeprint_youtube(query, max_results)
            additional_videos.extend(lifeprint_results)
            
            # Search for other dedicated ASL channels
            asl_channel_results = self._search_asl_channels(query, max_results)
            additional_videos.extend(asl_channel_results)
            
        except Exception as e:
            print(f"Additional source search failed for '{query}': {e}")
            
        return additional_videos[:max_results]
    
    def _search_lifeprint_youtube(self, query: str, max_results: int = 2) -> List[Dict]:
        """Specifically search for Lifeprint/Dr. Vicars content on YouTube."""
        try:
            # Search specifically for Lifeprint content
            search_queries = [
                f"{query} site:youtube.com lifeprint",
                f"{query} Dr. Vicars ASL",
                f"{query} Bill Vicars sign language"
            ]
            
            videos = []
            for search_query in search_queries[:1]:  # Limit requests
                try:
                    ydl_opts = {
                        'quiet': True,
                        'no_warnings': True,
                        'extract_flat': True,
                        'default_search': f'ytsearch{max_results}:',
                        'logger': QuietYTDLogger(),
                    }
                    
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        search_results = ydl.extract_info(search_query, download=False)
                    
                    if search_results and 'entries' in search_results:
                        for entry in search_results['entries']:
                            if not entry:
                                continue
                                
                            title = entry.get('title', '').lower()
                            uploader = entry.get('uploader', '').lower()
                            
                            # Look for Lifeprint/Dr. Vicars content
                            is_lifeprint = any(term in title or term in uploader for term in 
                                             ['lifeprint', 'dr. vicars', 'bill vicars'])
                            
                            if is_lifeprint:
                                duration = entry.get('duration', 0) or 0
                                video_info = {
                                    'title': entry.get('title', ''),
                                    'url': f"https://www.youtube.com/watch?v={entry.get('id', '')}",
                                    'id': entry.get('id', ''),
                                    'duration': duration,
                                    'uploader': entry.get('uploader', ''),
                                    'source': 'youtube_lifeprint',
                                    'relevance_score': self._calculate_relevance(title, query, search_query) + 3.0  # Bonus for Lifeprint
                                }
                                videos.append(video_info)
                                
                except Exception as e:
                    print(f"Lifeprint search failed for '{search_query}': {e}")
                    continue
                    
            return videos[:max_results]
            
        except Exception as e:
            print(f"Lifeprint YouTube search failed for '{query}': {e}")
            return []
    
    def _search_asl_channels(self, query: str, max_results: int = 2) -> List[Dict]:
        """Search known ASL education channels."""
        try:
            # List of known good ASL education channels/terms
            asl_channels = [
                'ASL Rochelle',
                'Learn ASL',
                'Sign Language 101',
                'ASL that',
                'Signing Savvy',
                'ASL Connect'
            ]
            
            videos = []
            for channel in asl_channels[:2]:  # Limit to avoid too many requests
                search_query = f"{query} {channel}"
                
                try:
                    ydl_opts = {
                        'quiet': True,
                        'no_warnings': True,
                        'extract_flat': True,
                        'default_search': 'ytsearch2:',  # Just 2 results per channel
                        'logger': QuietYTDLogger(),
                    }
                    
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        search_results = ydl.extract_info(search_query, download=False)
                    
                    if search_results and 'entries' in search_results:
                        for entry in search_results['entries']:
                            if not entry:
                                continue
                                
                            title = entry.get('title', '').lower()
                            
                            # Check for ASL content
                            if any(term in title for term in ['asl', 'sign language', 'signing']):
                                duration = entry.get('duration', 0) or 0
                                video_info = {
                                    'title': entry.get('title', ''),
                                    'url': f"https://www.youtube.com/watch?v={entry.get('id', '')}",
                                    'id': entry.get('id', ''),
                                    'duration': duration,
                                    'uploader': entry.get('uploader', ''),
                                    'source': 'youtube_asl_channel',
                                    'relevance_score': self._calculate_relevance(title, query, search_query)
                                }
                                videos.append(video_info)
                                
                except Exception as e:
                    print(f"ASL channel search failed for '{channel}': {e}")
                    continue
                    
            return videos[:max_results]
            
        except Exception as e:
            print(f"ASL channel search failed for '{query}': {e}")
            return []
    
    def _calculate_relevance(self, title: str, query: str, search_query: str = None) -> float:
        """Calculate relevance score for search results."""
        title_lower = title.lower()
        query_lower = query.lower()
        
        score = 0.0
        
        # Exact query match gets highest score
        if query_lower in title_lower:
            score += 15.0
        
        # Individual word matches
        query_words = query_lower.split()
        for word in query_words:
            if word in title_lower:
                score += 3.0
        
        # ASL-specific bonus points
        asl_terms = ['asl', 'sign language', 'deaf', 'signs', 'american sign language']
        for term in asl_terms:
            if term in title_lower:
                score += 1.0
        
        # Bonus for educational/tutorial keywords
        educational_terms = ['how to', 'learn', 'tutorial', 'lesson', 'dictionary']
        for term in educational_terms:
            if term in title_lower:
                score += 2.0
                
        # Bonus for known good ASL sources
        good_sources = ['lifeprint', 'dr. vicars', 'bill vicars', 'asl dictionary', 'signing savvy']
        for source in good_sources:
            if source in title_lower:
                score += 5.0
        
        # Penalty for very long titles (likely complex tutorials)
        if len(title) > 100:
            score -= 1.0
            
        # Small penalty for very long videos (might be full lessons)
        if hasattr(self, '_current_duration') and self._current_duration > 300:
            score -= 0.5
            
        return score
    
    def _process_video(self, input_path: str, output_path: str, max_duration: int) -> bool:
        """Process video to standard format for ASL use."""
        try:
            # Use ffmpeg to process:
            # - Extract first N seconds
            # - Resize to standard dimensions
            # - Remove audio
            # - Optimize for web delivery
            cmd = [
                'ffmpeg',
                '-i', input_path,
                '-t', str(max_duration),
                '-vf', 'scale=640:480:force_original_aspect_ratio=decrease,pad=640:480:(ow-iw)/2:(oh-ih)/2',
                '-c:v', 'libx264',
                '-preset', 'fast',
                '-crf', '23',
                '-an',  # Remove audio
                '-movflags', '+faststart',  # Optimize for web
                '-y',  # Overwrite output
                output_path
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0 and os.path.exists(output_path):
                return True
            else:
                print(f"FFmpeg processing failed: {result.stderr}")
                return False
                
        except Exception as e:
            print(f"Error processing video: {e}")
            return False
    
    def _store_video_metadata(self, gloss: str, video_info: Dict, local_path: str):
        """Store metadata about downloaded videos."""
        try:
            metadata = {
                'gloss': gloss,
                'source': video_info.get('source', 'unknown'),
                'original_url': video_info.get('url', ''),
                'title': video_info.get('title', ''),
                'uploader': video_info.get('uploader', ''),
                'local_path': local_path,
                'downloaded_at': time.time(),
                'video_id': video_info.get('id', ''),
                'relevance_score': video_info.get('relevance_score', 0.0)
            }
            
            metadata_file = local_path.replace('.mp4', '_metadata.json')
            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)
                
        except Exception as e:
            print(f"Error storing metadata: {e}")
    
    def get_cached_video(self, gloss: str) -> Optional[str]:
        """Check if we already have a cached video for this gloss."""
        try:
            # Look for existing videos for this gloss
            for filename in os.listdir(self.cache_dir):
                if filename.startswith(f"{gloss}_") and filename.endswith('.mp4'):
                    full_path = os.path.join(self.cache_dir, filename)
                    if os.path.exists(full_path):
                        return full_path
            return None
        except Exception:
            return None
    
    def generate_sign_id(self, gloss: str, video_path: str) -> int:
        """Generate a unique sign ID for downloaded videos."""
        file_size = os.path.getsize(video_path) if os.path.exists(video_path) else 0
        unique_string = f"{gloss}_{file_size}_{int(time.time())}"
        sign_id = int(hashlib.md5(unique_string.encode()).hexdigest()[:8], 16)
        return abs(sign_id) % 1000000000


# Convenience function for standalone use
def search_and_download_asl_video(gloss: str, output_dir: str = "/tmp") -> Optional[str]:
    """
    Convenience function to search and download an ASL video for a gloss.
    
    Args:
        gloss: ASL gloss to search for
        output_dir: Directory to save the video
        
    Returns:
        Path to downloaded video or None if failed
    """
    searcher = ASLVideoSearcher()
    
    # Check cache first
    cached_video = searcher.get_cached_video(gloss)
    if cached_video:
        print(f"Using cached video for '{gloss}': {cached_video}")
        return cached_video
    
    # Search online
    results = searcher.search_for_gloss(gloss, max_results=1)
    if results:
        return searcher.download_and_process_video(results[0], gloss, output_dir)
    
    return None


if __name__ == "__main__":
    # Test the searcher
    import argparse
    
    parser = argparse.ArgumentParser(description='Search and download ASL videos')
    parser.add_argument('gloss', help='ASL gloss to search for')
    parser.add_argument('--output-dir', default='/tmp', help='Output directory')
    parser.add_argument('--max-results', type=int, default=3, help='Max search results')
    
    args = parser.parse_args()
    
    searcher = ASLVideoSearcher()
    
    print(f"Searching for ASL videos for gloss: '{args.gloss}'")
    results = searcher.search_for_gloss(args.gloss, args.max_results)
    
    if results:
        print(f"Found {len(results)} potential videos:")
        for i, result in enumerate(results, 1):
            print(f"{i}. {result['title']} (Score: {result.get('relevance_score', 0):.1f})")
            print(f"   Source: {result['source']}, Duration: {result.get('duration', 'unknown')}s")
            print(f"   URL: {result['url']}")
            print()
        
        # Download the best result
        print("Downloading best match...")
        video_path = searcher.download_and_process_video(results[0], args.gloss, args.output_dir)
        if video_path:
            print(f"Successfully downloaded and processed: {video_path}")
        else:
            print("Failed to download and process video")
    else:
        print("No suitable videos found")