"""
Notes generation functionality for Meeting Notes Generator.
This module handles processing transcriptions and generating meeting notes.
"""

import os
import json
import logging
import shutil
from datetime import datetime

from aws_services import AWSHandler
from transcription import TranscriptionService
from config import TRANSCRIPTION_SERVICE, WHISPER_MODEL_SIZE, BEDROCK_MODEL_ID

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class NotesGenerator:
    """Processes audio recordings to generate meeting notes."""
    
    def __init__(self, bedrock_profile='bedrock', model_id=None, transcription_service=None, whisper_model_size=None):
        """Initialize NotesGenerator.
        
        Args:
            bedrock_profile: AWS profile for Bedrock API calls (default: 'bedrock')
            model_id: Bedrock model ID to use (default: None, which uses the config value)
            transcription_service: Transcription service to use (default: None, which uses the config value)
        """
        # Initialize AWS handler for Bedrock
        self.aws_handler = AWSHandler(bedrock_profile=bedrock_profile)
        
        # Set up transcription service
        self.transcription_service_type = transcription_service or TRANSCRIPTION_SERVICE
        self.transcription_service = None  # Will be initialized on demand
        
        # Set Whisper model size if provided
        self.whisper_model_size = whisper_model_size or WHISPER_MODEL_SIZE
        
        # Setup directories and model
        self.notes_dir = "notes"
        self.model_id = model_id or BEDROCK_MODEL_ID
        
        # Track the last used recording and transcription
        self.last_recording_path = None
        self.last_transcription_json = None
        self.last_transcript_text = None
        self.last_transcript_path = None
        
        # Ensure notes directory exists
        os.makedirs(self.notes_dir, exist_ok=True)
    
    def _get_transcription_service(self):
        """Get or initialize the transcription service."""
        if self.transcription_service is None:
            if self.transcription_service_type == 'aws':
                self.transcription_service = self.aws_handler
            else:
                kwargs = {}
                if self.transcription_service_type == 'whisper':
                    kwargs['model_size'] = self.whisper_model_size
                
                self.transcription_service = TranscriptionService.get_service(
                    self.transcription_service_type, **kwargs
                )
        
        return self.transcription_service
    
    def get_available_services(self):
        """Get list of available transcription services."""
        return TranscriptionService.get_available_services()
    
    def set_transcription_service(self, service_type, **kwargs):
        """Change the transcription service.
        
        Args:
            service_type: Type of service ('aws', 'whisper', 'mac')
            **kwargs: Additional arguments for the service
        """
        self.transcription_service_type = service_type
        
        # Update whisper_model_size if specified
        if service_type == 'whisper' and 'model_size' in kwargs:
            self.whisper_model_size = kwargs['model_size']
            logger.info(f"Whisper model size set to {self.whisper_model_size}")
            
        # Force re-initialization of the service
        self.transcription_service = None
        logger.info(f"Transcription service changed to {service_type}")
    
    def generate_notes_from_transcript(self, transcript_json, model_id=None, callback=None):
        """Generate meeting notes from a transcript.
        
        Args:
            transcript_json: Transcription result.
            model_id: Bedrock model ID to use (optional, defaults to self.model_id).
            callback: Optional callback function for UI updates.
            
        Returns:
            Generated meeting notes as text.
        """
        try:
            use_model_id = model_id if model_id else self.model_id
            logger.info(f"Generating notes using model: {use_model_id}")
            
            if callback:
                callback(f"Generating notes with model: {use_model_id}", 75)
                
            # Generate notes using AWS Bedrock
            notes_content = self.aws_handler.generate_meeting_notes(
                transcript_json, model_id=use_model_id
            )
            
            if notes_content:
                logger.info("Meeting notes generated successfully")
                return notes_content
            else:
                logger.error("Failed to generate notes")
                return None
                
        except Exception as e:
            logger.error(f"Error generating notes: {e}")
            return None
            
    def retry_transcription(self, audio_file_path=None, service_type=None, callback=None):
        """Retry transcription with a different service or the same service.
        
        Args:
            audio_file_path: Path to audio file (optional, defaults to last recording).
            service_type: Transcription service to use (optional).
            callback: Optional callback function for UI updates.
            
        Returns:
            Tuple containing (transcript_json, transcript_text, transcript_path)
        """
        # Use last recording if no path provided
        file_path = audio_file_path or self.last_recording_path
        if not file_path or not os.path.exists(file_path):
            logger.error("No valid audio file to retry transcription")
            return None, None, None
            
        # Change service if specified
        if service_type and service_type != self.transcription_service_type:
            self.set_transcription_service(service_type)
            
        # Process just the transcription part
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        try:
            if callback:
                if self.transcription_service_type == "aws":
                    callback("Uploading audio to AWS...", 10)
                else:
                    callback(f"Preparing for {self.transcription_service_type} transcription...", 10)
            
            # Get transcription service
            transcription_service = self._get_transcription_service()
                
            # For AWS we need S3
            s3_uri = None
            if self.transcription_service_type == "aws":
                s3_uri = self.aws_handler.upload_audio_to_s3(file_path)
                
            # Update progress
            if callback:
                callback(f"Transcribing audio with {self.transcription_service_type}...", 30)
                
            # Transcribe the audio
            if self.transcription_service_type == "aws":
                transcript_json = transcription_service.transcribe_audio(s3_uri)
            else:
                transcript_json = transcription_service.transcribe(file_path, callback)
                
            # Save transcript if successful
            if transcript_json and 'results' in transcript_json:
                # Save JSON
                transcript_file_path = os.path.join(self.notes_dir, f"transcript_{timestamp}.json")
                with open(transcript_file_path, 'w') as f:
                    json.dump(transcript_json, f, indent=2)
                    
                # Save plain text
                transcript_text = transcript_json['results']['transcripts'][0]['transcript']
                transcript_txt_path = os.path.join(self.notes_dir, f"transcript_{timestamp}.txt")
                with open(transcript_txt_path, 'w') as f:
                    f.write(transcript_text)
                    
                # Update stored values
                self.last_transcription_json = transcript_json
                self.last_transcript_text = transcript_text
                self.last_transcript_path = transcript_file_path
                
                if callback:
                    callback("Transcription successful!", 100)
                    
                return transcript_json, transcript_text, transcript_file_path
            else:
                logger.error("Transcription failed")
                if callback:
                    callback("Transcription failed", -1)
                return None, None, None
        except Exception as e:
            logger.error(f"Error during transcription: {e}")
            if callback:
                callback(f"Error: {str(e)}", -1)
            return None, None, None
            
    def retry_notes_generation(self, transcript_json=None, model_id=None, timestamp=None, callback=None):
        """Regenerate notes from a transcript with a different model.
        
        Args:
            transcript_json: Transcription result (optional, defaults to last transcript).
            model_id: Bedrock model ID to use (optional).
            timestamp: Explicit timestamp to use for the notes file (optional).
            callback: Optional callback function for UI updates.
            
        Returns:
            Tuple containing (notes_content, notes_file_path)
        """
        # Use last transcript if none provided
        transcript = transcript_json or self.last_transcription_json
        if transcript is None:
            logger.error("No transcript available for notes generation")
            return None, None
            
        # Change model if specified
        use_model = model_id or self.model_id
            
        # Use provided timestamp, or try to extract from transcript
        original_timestamp = timestamp
        new_version = False
        
        if original_timestamp is None:
            # Try to get original timestamp from the transcript file path
            if isinstance(transcript_json, dict) and 'jobName' in transcript_json:
                job_name = transcript_json['jobName']
                if job_name.startswith('whisper-') and len(job_name) > 8:
                    logger.warning("Cannot extract timestamp from Whisper job name")
                else:
                    # Extract timestamp from an existing transcript file in the notes directory
                    for filename in os.listdir(self.notes_dir):
                        if filename.startswith("transcript_") and filename.endswith(".json"):
                            try:
                                with open(os.path.join(self.notes_dir, filename), 'r') as f:
                                    existing_json = json.load(f)
                                    if existing_json == transcript_json:
                                        # Found matching transcript, extract timestamp
                                        original_timestamp = filename.replace("transcript_", "").replace(".json", "")
                                        logger.info(f"Found original timestamp: {original_timestamp}")
                                        break
                            except Exception as e:
                                logger.warning(f"Error reading transcript file {filename}: {e}")
                                continue
            
            # Fallback to current time if we couldn't extract timestamp
            if not original_timestamp:
                original_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                logger.warning(f"Could not determine original timestamp, using current time: {original_timestamp}")
                
        # Check if we need to create a versioned file name
        notes_file_path = os.path.join(self.notes_dir, f"meeting_notes_{original_timestamp}.md")
        if os.path.exists(notes_file_path):
            # We need to append version information to the filename
            existing_notes_files = []
            for filename in os.listdir(self.notes_dir):
                if filename.startswith(f"meeting_notes_{original_timestamp}") and filename.endswith(".md"):
                    existing_notes_files.append(filename)
            
            # Create a version number based on the number of existing files
            # Format will be: meeting_notes_YYYYMMDD_HHMMSS_v2.md, _v3.md, etc.
            version = len(existing_notes_files) + 1
            notes_file_path = os.path.join(self.notes_dir, f"meeting_notes_{original_timestamp}_v{version}.md")
            new_version = True
            logger.info(f"Creating new version {version} of notes for meeting {original_timestamp}")
        
        try:
            if callback:
                callback(f"Generating notes with model: {use_model}", 50)
                
            notes_content = self.generate_notes_from_transcript(transcript, use_model, callback)
            
            if notes_content:
                # Save notes (notes_file_path is already correctly set with versioning above)
                with open(notes_file_path, 'w') as f:
                    f.write(notes_content)
                
                # Log whether this is a new version or not    
                if new_version:
                    logger.info(f"Created new version of notes for meeting {original_timestamp}")
                else:
                    logger.info(f"Created notes for meeting {original_timestamp}")
                    
                if callback:
                    callback("Notes generated successfully!", 100)
                    
                logger.info(f"Meeting notes saved to {notes_file_path}")
                return notes_content, notes_file_path
            else:
                logger.error("Failed to generate notes")
                if callback:
                    callback("Failed to generate notes", -1)
                return None, None
        except Exception as e:
            logger.error(f"Error regenerating notes: {e}")
            if callback:
                callback(f"Error: {str(e)}", -1)
            return None, None
    
    def process_recording(self, audio_file_path, callback=None):
        """
        Process an audio recording to generate meeting notes.
        
        Args:
            audio_file_path: Path to the audio recording file.
            callback: Optional callback function to update UI with progress.
            
        Returns:
            Tuple containing (notes_content, transcript_content, notes_file_path)
        """
        if not os.path.exists(audio_file_path):
            logger.error(f"Audio file not found: {audio_file_path}")
            return None, None, None
        
        # Save this as the last recording
        self.last_recording_path = audio_file_path
        
        # Extract the meeting timestamp from the filename or use current time
        # Format is typically meeting_YYYYMMDD_HHMMSS.wav or already a local_recording_*.wav
        if os.path.basename(audio_file_path).startswith("meeting_"):
            # Extract timestamp from a meeting recording file
            try:
                filename = os.path.basename(audio_file_path)
                timestamp = filename.split('_')[1] + '_' + filename.split('_')[2].split('.')[0]
            except (IndexError, ValueError):
                # Fallback to current time if format doesn't match
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        elif os.path.basename(audio_file_path).startswith("local_recording_"):
            # This is already a local copy, extract timestamp
            try:
                filename = os.path.basename(audio_file_path)
                timestamp = filename.replace("local_recording_", "").split('.')[0]
            except (IndexError, ValueError):
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        else:
            # Use current timestamp for other file formats
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        try:
            # Check if we already have a local copy
            local_copy_path = os.path.join(self.notes_dir, f"local_recording_{timestamp}.wav")
            
            if not os.path.exists(local_copy_path) or not os.path.samefile(audio_file_path, local_copy_path):
                # Only make a copy if we don't already have one or if it's a different file
                shutil.copy2(audio_file_path, local_copy_path)
                logger.info(f"Local copy saved to {local_copy_path}")
            
            # Get the appropriate transcription service
            transcription_service = self._get_transcription_service()
            
            # Progress update
            if callback:
                if self.transcription_service_type == "aws":
                    callback("Uploading audio to AWS...", 10)
                else:
                    callback(f"Preparing for {self.transcription_service_type} transcription...", 10)
            
            # If using AWS, we need to upload to S3 first
            s3_uri = None
            if self.transcription_service_type == "aws":
                s3_uri = self.aws_handler.upload_audio_to_s3(audio_file_path)
                logger.info(f"Audio uploaded to {s3_uri}")
            
            # Update progress
            if callback:
                callback(f"Transcribing audio with {self.transcription_service_type}...", 30)
            
            # Transcribe the audio
            if self.transcription_service_type == "aws":
                transcript_json = transcription_service.transcribe_audio(s3_uri)
            else:
                transcript_json = transcription_service.transcribe(audio_file_path, callback)
            
            # Save transcript if successful
            if transcript_json and 'results' in transcript_json and 'transcripts' in transcript_json['results']:
                # Save transcript JSON
                transcript_file_path = os.path.join(self.notes_dir, f"transcript_{timestamp}.json")
                with open(transcript_file_path, 'w') as f:
                    json.dump(transcript_json, f, indent=2)
                self.last_transcript_path = transcript_file_path
                self.last_transcription_json = transcript_json
                
                # Extract and save plain text transcript
                transcript_text = transcript_json['results']['transcripts'][0]['transcript']
                transcript_txt_path = os.path.join(self.notes_dir, f"transcript_{timestamp}.txt")
                with open(transcript_txt_path, 'w') as f:
                    f.write(transcript_text)
                self.last_transcript_text = transcript_text
                
                # Update progress
                if callback:
                    callback("Generating meeting notes...", 70)
                
                # Try to generate meeting notes
                try:
                    # Add filename info to transcript_json for date extraction
                    transcript_json['recording_filename'] = os.path.basename(audio_file_path)
                    notes_content = self.generate_notes_from_transcript(transcript_json, self.model_id, callback)
                    if notes_content:
                        # Save notes
                        notes_file_path = os.path.join(self.notes_dir, f"meeting_notes_{timestamp}.md")
                        with open(notes_file_path, 'w') as f:
                            f.write(notes_content)
                        
                        # Update progress
                        if callback:
                            callback("Notes generated successfully!", 100)
                        
                        logger.info(f"Meeting notes saved to {notes_file_path}")
                        return notes_content, transcript_text, notes_file_path
                    else:
                        # Notes generation failed but we have transcript
                        logger.error("Notes generation failed, but transcript is available")
                        if callback:
                            callback("Notes generation failed. Try regenerating with a different model.", -1)
                        return None, transcript_text, transcript_txt_path
                except Exception as gen_error:
                    # Notes generation failed but we have transcript
                    logger.error(f"Error generating notes: {gen_error}")
                    if callback:
                        callback(f"Error generating notes: {gen_error}", -1)
                    return None, transcript_text, transcript_txt_path
            else:
                # Transcription failed
                logger.warning("Transcription failed or produced invalid format")
                if callback:
                    callback("Transcription failed. Try with a different service.", -1)
                return None, None, None
            
        except Exception as e:
            logger.error(f"Error processing recording: {e}")
            if callback:
                callback(f"Error: {str(e)}", -1)
            return None, None, None
    
    def get_notes_list(self):
        """
        Get a list of all generated notes.
        
        Returns:
            List of dictionaries with notes metadata.
        """
        notes_list = []
        
        if not os.path.exists(self.notes_dir):
            return notes_list
        
        for filename in os.listdir(self.notes_dir):
            if filename.startswith("meeting_notes_") and filename.endswith(".md"):
                file_path = os.path.join(self.notes_dir, filename)
                
                # Extract timestamp from filename
                try:
                    timestamp_str = filename.replace("meeting_notes_", "").replace(".md", "")
                    timestamp = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                    formatted_date = timestamp.strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:
                    formatted_date = "Unknown date"
                
                # Get first line of file as title
                try:
                    with open(file_path, 'r') as f:
                        first_line = f.readline().strip()
                        title = first_line.replace("#", "").strip()
                        if not title:
                            title = "Untitled Meeting"
                except Exception:
                    title = "Untitled Meeting"
                
                notes_list.append({
                    "title": title,
                    "date": formatted_date,
                    "file_path": file_path,
                    "timestamp": timestamp_str
                })
        
        # Sort by timestamp, newest first
        notes_list.sort(key=lambda x: x["timestamp"], reverse=True)
        return notes_list


# For testing standalone functionality
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python notes_generator.py <audio_file_path>")
        sys.exit(1)
    
    audio_file = sys.argv[1]
    generator = NotesGenerator()
    
    def print_progress(message, percentage):
        print(f"{message} ({percentage}%)")
    
    notes, transcript, notes_path = generator.process_recording(audio_file, print_progress)
    
    if notes:
        print(f"\nGenerated notes saved to: {notes_path}")
        print("\nNotes preview:\n")
        print(notes[:500] + "..." if len(notes) > 500 else notes)
