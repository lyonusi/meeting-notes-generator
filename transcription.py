"""
Transcription service for Meeting Notes Generator.
Handles both AWS Transcribe and local Whisper transcription.
"""

import os
import json
import time
import logging
import tempfile
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class WhisperTranscription:
    """Handles transcription using OpenAI's Whisper model locally."""
    
    def __init__(self, model_size="base"):
        """Initialize Whisper transcription.
        
        Args:
            model_size: Size of the Whisper model to use ('tiny', 'base', 'small', 'medium', 'large').
              Smaller models are faster but less accurate.
        """
        self.model_size = model_size
        self.model = None  # Lazy-loaded to avoid importing whisper until needed
        
    def _load_model(self):
        """Load the Whisper model if not already loaded."""
        if self.model is None:
            try:
                import whisper
                # Try different ways to load the model based on different versions of Whisper
                logger.info(f"Loading Whisper {self.model_size} model...")
                
                # Try the OpenAI Whisper way first (newer versions) if API key is set
                try:
                    # Check if OpenAI API key is available
                    if os.environ.get("OPENAI_API_KEY"):
                        from openai import OpenAI
                        self.model = OpenAI()
                        # Just storing the client for API calls later
                        logger.info(f"Using OpenAI Whisper API")
                        self.using_api = True
                        return
                    else:
                        logger.info("No OpenAI API key found, falling back to local model")
                        self.using_api = False
                except (ImportError, AttributeError):
                    logger.info("OpenAI package not available, falling back to local model")
                    self.using_api = False
                
                # Try the local model way - first with standard whisper
                try:
                    # Standard API in openai-whisper package
                    self.model = whisper.load_model(self.model_size)
                    self.model_type = "whisper"
                    logger.info(f"Whisper {self.model_size} model loaded successfully")
                except (AttributeError, TypeError) as e:
                    logger.info(f"Standard whisper.load_model failed: {e}, trying alternatives")
                    
                    # Try faster-whisper if available
                    try:
                        from faster_whisper import WhisperModel
                        self.model = WhisperModel(self.model_size)
                        self.model_type = "faster_whisper"
                        logger.info(f"Faster-Whisper {self.model_size} model loaded successfully")
                    except ImportError:
                        # Last resort: check if whisper module has WhisperModel directly
                        if hasattr(whisper, 'WhisperModel'):
                            self.model = whisper.WhisperModel(self.model_size)
                            self.model_type = "whisper_model"
                            logger.info(f"Whisper.WhisperModel {self.model_size} loaded successfully")
                        else:
                            raise ImportError("No compatible Whisper implementation found")
            except ImportError:
                logger.error("Failed to import whisper. Make sure it's installed with 'pip install openai-whisper'")
                raise
            except Exception as e:
                logger.error(f"Error loading Whisper model: {e}")
                raise
    
    def transcribe(self, audio_file_path, callback=None):
        """Transcribe audio using Whisper.
        
        Args:
            audio_file_path: Path to the audio file.
            callback: Optional callback function to update UI with progress.
            
        Returns:
            JSON-compatible dict with transcription results.
        """
        try:
            if callback:
                callback("Loading Whisper model...", 10)
            
            self._load_model()
            
            if callback:
                callback("Transcribing audio with Whisper...", 30)
            
            # Transcribe the audio
            logger.info(f"Transcribing {audio_file_path} with Whisper...")
            
            # Different transcription method based on what model was loaded
            if hasattr(self, 'using_api') and self.using_api:
                # Using OpenAI API
                with open(audio_file_path, 'rb') as audio_file:
                    response = self.model.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio_file,
                        response_format="verbose_json"
                    )
                # Extract the result
                transcript_text = response.text
                segments = response.segments if hasattr(response, 'segments') else []
            else:
                # Using local model - handle different model outputs
                if hasattr(self, 'model_type') and self.model_type == "faster_whisper":
                    # For faster-whisper, the API is different
                    segments_generator, info = self.model.transcribe(audio_file_path)
                    segments = list(segments_generator)  # Convert generator to list
                    
                    # Combine all segments to create full text
                    transcript_text = " ".join(seg.text for seg in segments)
                    
                    # Format segments for compatibility
                    formatted_segments = []
                    for seg in segments:
                        formatted_segments.append({
                            "start": seg.start,
                            "end": seg.end,
                            "text": seg.text
                        })
                    segments = formatted_segments
                else:
                    # Standard whisper
                    result = self.model.transcribe(audio_file_path)
                    transcript_text = result["text"]
                    segments = result.get("segments", [])
            
            if callback:
                callback("Converting Whisper output to compatible format...", 70)
            
            # Convert to a format compatible with AWS Transcribe output
            
            # Create AWS Transcribe compatible format
            aws_compatible = {
                "jobName": "whisper-transcription",
                "status": "COMPLETED",
                "results": {
                    "transcripts": [
                        {"transcript": transcript_text}
                    ],
                    "items": [],
                    "speaker_labels": {
                        "speakers": [],
                        "segments": []
                    }
                }
            }
            
            # Process segments and speakers if available
            current_speaker = 0
            speaker_segments = []
            items = []
            item_index = 0
            
            for i, segment in enumerate(segments):
                start_time = segment.get("start", 0)
                end_time = segment.get("end", 0)
                text = segment.get("text", "")
                
                # Simple speaker diarization - change speaker every few segments
                # In a real implementation, you'd use proper diarization
                if i % 3 == 0:  # Change speaker every ~3 segments
                    current_speaker = (current_speaker + 1) % 2
                
                speaker_label = f"spk_{current_speaker}"
                
                # Add speaker segment
                speaker_segments.append({
                    "speaker_label": speaker_label,
                    "start_time": str(start_time),
                    "end_time": str(end_time),
                    "items": []
                })
                
                # Add words as items
                words = text.split()
                word_duration = (end_time - start_time) / max(len(words), 1)
                
                for j, word in enumerate(words):
                    word_start = start_time + j * word_duration
                    word_end = word_start + word_duration
                    
                    item = {
                        "start_time": str(word_start),
                        "end_time": str(word_end),
                        "type": "pronunciation",
                        "alternatives": [{"content": word, "confidence": "1.0"}],
                        "speaker_label": speaker_label
                    }
                    
                    items.append(item)
                    speaker_segments[-1]["items"].append(item_index)
                    item_index += 1
            
            # Update the results with speakers and items
            if speaker_segments:
                aws_compatible["results"]["speaker_labels"]["speakers"] = [
                    {"speaker_label": "spk_0"},
                    {"speaker_label": "spk_1"}
                ]
                aws_compatible["results"]["speaker_labels"]["segments"] = speaker_segments
            
            aws_compatible["results"]["items"] = items
            
            if callback:
                callback("Transcription complete!", 100)
            
            return aws_compatible
            
        except Exception as e:
            logger.error(f"Error during Whisper transcription: {e}")
            raise
            

class MacSpeechRecognition:
    """Handles transcription using macOS built-in speech recognition."""
    
    def __init__(self):
        """Initialize macOS speech recognition."""
        self.supported = self._check_support()
    
    def _check_support(self):
        """Check if macOS speech recognition is supported."""
        try:
            # Check for pyobjc and AVFoundation
            import objc
            import AVFoundation
            return True
        except ImportError:
            logger.warning("macOS speech recognition requires pyobjc and AVFoundation")
            return False
    
    def transcribe(self, audio_file_path, callback=None):
        """Transcribe audio using macOS speech recognition.
        
        Args:
            audio_file_path: Path to the audio file.
            callback: Optional callback function to update UI with progress.
            
        Returns:
            JSON-compatible dict with transcription results.
        """
        if not self.supported:
            raise RuntimeError("macOS speech recognition is not supported on this system")
        
        # Implementation for macOS speech recognition would go here
        # This is just a placeholder as it requires pyobjc and proper setup
        raise NotImplementedError("macOS speech recognition is not yet implemented")


class TranscriptionService:
    """Factory class for transcription services."""
    
    @staticmethod
    def get_service(service_type, **kwargs):
        """Get an instance of the specified transcription service.
        
        Args:
            service_type: Type of service ('aws', 'whisper', 'mac').
            **kwargs: Additional arguments to pass to the service.
            
        Returns:
            Transcription service instance.
        """
        if service_type == 'aws':
            from aws_services import AWSHandler
            return AWSHandler(**kwargs)
        elif service_type == 'whisper':
            return WhisperTranscription(**kwargs)
        elif service_type == 'mac':
            return MacSpeechRecognition()
        else:
            raise ValueError(f"Unknown transcription service: {service_type}")
    
    @staticmethod
    def get_available_services():
        """Get a list of available transcription services.
        
        Returns:
            List of available service types.
        """
        services = ['aws', 'whisper']
        
        # Check for macOS speech recognition
        try:
            import objc
            import AVFoundation
            services.append('mac')
        except ImportError:
            pass
        
        return services


# For testing standalone functionality
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python transcription.py <service_type> <audio_file_path>")
        sys.exit(1)
    
    service_type = sys.argv[1]
    audio_file = sys.argv[2]
    
    def print_progress(message, percentage):
        print(f"{message} ({percentage}%)")
    
    try:
        service = TranscriptionService.get_service(service_type)
        result = service.transcribe(audio_file, print_progress)
        print(f"\nTranscription successful!")
        print(f"Transcript: {result['results']['transcripts'][0]['transcript'][:200]}...")
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)
