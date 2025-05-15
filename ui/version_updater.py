"""
Utility for updating version metadata for Meeting Notes Generator.
This module handles updating version metadata when notes or transcripts are generated.
"""

import os
import json
import logging
from datetime import datetime

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def update_version_metadata(version_manager, meeting_id, notes_path, transcript_path=None, 
                            transcript_json_path=None, model_id=None, 
                            transcription_service=None, is_default=False):
    """Update version metadata after generating notes or transcripts.
    
    Args:
        version_manager: Instance of VersionManager class.
        meeting_id: Meeting ID (timestamp).
        notes_path: Path to the notes file.
        transcript_path: Path to the transcript text file (optional).
        transcript_json_path: Path to the transcript JSON file (optional).
        model_id: AI model ID used for notes generation (optional).
        transcription_service: Transcription service used (optional).
        is_default: Whether this should be the default version (optional).
        
    Returns:
        Updated metadata dictionary.
    """
    # Determine version number
    version_num = 1
    base_name = os.path.basename(notes_path)
    
    # Check if this is a versioned file (e.g., meeting_notes_YYYYMMDD_HHMMSS_v2.md)
    import re
    version_match = re.search(r'_v(\d+)\.md$', base_name)
    if version_match:
        version_num = int(version_match.group(1))
    
    # Create version info
    version_info = {
        'version_num': version_num,
        'notes_path': notes_path,
        'transcript_path': transcript_path,
        'transcript_json_path': transcript_json_path,
        'model_id': model_id,
        'transcription_service': transcription_service,
        'creation_time': datetime.now().isoformat(),
        'name': f"Version {version_num}",
        'is_default': is_default,
        'set_as_default': is_default
    }
    
    # Update metadata
    try:
        metadata = version_manager.create_or_update_metadata(meeting_id, version_info)
        logger.info(f"Updated metadata for meeting {meeting_id}, version {version_num}")
        return metadata
    except Exception as e:
        logger.error(f"Error updating metadata: {e}")
        return None
