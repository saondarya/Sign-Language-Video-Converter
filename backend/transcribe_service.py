#!/usr/bin/env python3
"""
Enhanced Transcription Service for Flask Integration
Integrates with the existing transcribe.py functionality
"""

import os
import logging
import whisper
import tempfile
from pathlib import Path
import traceback

logger = logging.getLogger(__name__)

class TranscribeService:
    """Service class for video transcription using Whisper"""
    
    def __init__(self, model_name="base"):
        """
        Initialize the transcription service
        
        Args:
            model_name (str): Whisper model to use ('tiny', 'base', 'small', 'medium', 'large')
        """
        self.model_name = model_name
        self.model = None
        self._load_model()
    
    def _load_model(self):
        """Load the Whisper model"""
        try:
            logger.info(f"Loading Whisper model: {self.model_name}")
            self.model = whisper.load_model(self.model_name)
            logger.info("Model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load Whisper model: {e}")
            raise Exception(f"Model loading failed: {str(e)}")
    
    def transcribe_video(self, video_path, language=None, task="transcribe"):
        """
        Transcribe a video file to text
        
        Args:
            video_path (str): Path to the video file
            language (str, optional): Language code for the audio
            task (str): Either 'transcribe' or 'translate'
        
        Returns:
            dict: Result containing success status, text, and metadata
        """
        try:
            if not os.path.exists(video_path):
                return {
                    'success': False,
                    'error': f'Video file not found: {video_path}',
                    'text': '',
                    'metadata': {}
                }
            
            logger.info(f"Starting transcription of: {video_path}")
            
            # Set up transcription options
            options = {
                'task': task,
                'verbose': False
            }
            
            if language:
                options['language'] = language
            
            # Perform transcription
            result = self.model.transcribe(video_path, **options)
            
            # Extract text and metadata
            transcribed_text = result.get('text', '').strip()
            
            if not transcribed_text:
                return {
                    'success': False,
                    'error': 'No speech detected in the video',
                    'text': '',
                    'metadata': result
                }
            
            # Clean up the text
            cleaned_text = self._clean_text(transcribed_text)
            
            logger.info(f"Transcription completed. Text length: {len(cleaned_text)} characters")
            
            return {
                'success': True,
                'error': None,
                'text': cleaned_text,
                'original_text': transcribed_text,
                'metadata': {
                    'language': result.get('language'),
                    'segments': len(result.get('segments', [])),
                    'model_used': self.model_name,
                    'duration': self._get_video_duration(result)
                }
            }
            
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            logger.error(traceback.format_exc())
            return {
                'success': False,
                'error': str(e),
                'text': '',
                'metadata': {}
            }
    
    def transcribe_from_file_upload(self, file_obj, language=None, task="transcribe"):
        """
        Transcribe from a file upload object
        
        Args:
            file_obj: Flask file upload object
            language (str, optional): Language code for the audio
            task (str): Either 'transcribe' or 'translate'
        
        Returns:
            dict: Result containing success status, text, and metadata
        """
        try:
            # Create temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp4') as temp_file:
                file_obj.save(temp_file.name)
                temp_path = temp_file.name
            
            # Transcribe the temporary file
            result = self.transcribe_video(temp_path, language, task)
            
            # Clean up temporary file
            try:
                os.unlink(temp_path)
            except Exception as cleanup_error:
                logger.warning(f"Failed to cleanup temp file: {cleanup_error}")
            
            return result
            
        except Exception as e:
            logger.error(f"File upload transcription error: {e}")
            return {
                'success': False,
                'error': str(e),
                'text': '',
                'metadata': {}
            }
    
    def _clean_text(self, text):
        """
        Clean and normalize transcribed text
        
        Args:
            text (str): Raw transcribed text
        
        Returns:
            str: Cleaned text
        """
        # Remove excessive whitespace
        text = ' '.join(text.split())
        
        # Remove or replace problematic characters
        text = text.replace('\n', ' ').replace('\r', ' ')
        
        # Ensure sentence ends properly
        if text and not text.endswith(('.', '!', '?')):
            text += '.'
        
        return text
    
    def _get_video_duration(self, whisper_result):
        """
        Extract video duration from Whisper result
        
        Args:
            whisper_result (dict): Whisper transcription result
        
        Returns:
            float: Duration in seconds
        """
        try:
            segments = whisper_result.get('segments', [])
            if segments:
                # Get the end time of the last segment
                return segments[-1].get('end', 0.0)
            return 0.0
        except Exception:
            return 0.0
    
    def get_supported_languages(self):
        """
        Get list of supported languages
        
        Returns:
            dict: Language codes and names
        """
        try:
            from whisper.tokenizer import LANGUAGES
            return LANGUAGES
        except ImportError:
            return {
                'en': 'english',
                'es': 'spanish',
                'fr': 'french',
                'de': 'german',
                'it': 'italian',
                'pt': 'portuguese',
                'ru': 'russian',
                'ja': 'japanese',
                'ko': 'korean',
                'zh': 'chinese'
            }
    
    def transcribe_with_timestamps(self, video_path, language=None):
        """
        Transcribe with detailed timestamp information
        
        Args:
            video_path (str): Path to the video file
            language (str, optional): Language code for the audio
        
        Returns:
            dict: Result with timestamped segments
        """
        try:
            if not os.path.exists(video_path):
                return {
                    'success': False,
                    'error': f'Video file not found: {video_path}',
                    'segments': []
                }
            
            logger.info(f"Starting detailed transcription of: {video_path}")
            
            # Set up transcription options with word-level timestamps
            options = {
                'task': 'transcribe',
                'verbose': False,
                'word_timestamps': True
            }
            
            if language:
                options['language'] = language
            
            # Perform transcription
            result = self.model.transcribe(video_path, **options)
            
            # Process segments with timestamps
            processed_segments = []
            for segment in result.get('segments', []):
                processed_segment = {
                    'id': segment.get('id'),
                    'start': segment.get('start'),
                    'end': segment.get('end'),
                    'text': segment.get('text', '').strip(),
                    'words': segment.get('words', [])
                }
                processed_segments.append(processed_segment)
            
            return {
                'success': True,
                'error': None,
                'segments': processed_segments,
                'full_text': result.get('text', '').strip(),
                'metadata': {
                    'language': result.get('language'),
                    'model_used': self.model_name,
                    'total_segments': len(processed_segments)
                }
            }
            
        except Exception as e:
            logger.error(f"Detailed transcription error: {e}")
            return {
                'success': False,
                'error': str(e),
                'segments': []
            }

# Convenience function for backward compatibility
def transcribe_video_file(video_path, model_name="base", language=None):
    """
    Simple function to transcribe a video file
    
    Args:
        video_path (str): Path to the video file
        model_name (str): Whisper model to use
        language (str, optional): Language code
    
    Returns:
        str: Transcribed text
    """
    service = TranscribeService(model_name)
    result = service.transcribe_video(video_path, language)
    
    if result['success']:
        return result['text']
    else:
        raise Exception(result['error'])

if __name__ == "__main__":
    # Test the service
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python transcribe_service.py <video_path>")
        sys.exit(1)
    
    video_path = sys.argv[1]
    model_name = sys.argv[2] if len(sys.argv) > 2 else "base"
    
    print(f"Testing transcription service with {video_path}")
    
    service = TranscribeService(model_name)
    result = service.transcribe_video(video_path)
    
    if result['success']:
        print(f"Transcription successful!")
        print(f"Text: {result['text']}")
        print(f"Metadata: {result['metadata']}")
    else:
        print(f"Transcription failed: {result['error']}")