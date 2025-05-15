"""
Version management functionality for Meeting Notes Generator.
This module handles tracking and managing versions of transcriptions and notes.
"""

import os
import json
import logging
from datetime import datetime
import difflib
import re

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class VersionManager:
    """Manages versions of transcriptions and notes."""
    
    def __init__(self, notes_dir):
        """Initialize VersionManager.
        
        Args:
            notes_dir: Directory where notes and transcripts are stored.
        """
        self.notes_dir = notes_dir
        self.metadata_dir = os.path.join(notes_dir, "metadata")
        
        # Ensure metadata directory exists
        os.makedirs(self.metadata_dir, exist_ok=True)
    
    def get_meeting_metadata_path(self, meeting_id):
        """Get path to the metadata file for a meeting.
        
        Args:
            meeting_id: Meeting ID (timestamp).
            
        Returns:
            Path to the metadata JSON file.
        """
        return os.path.join(self.metadata_dir, f"meeting_{meeting_id}_metadata.json")
    
    def create_or_update_metadata(self, meeting_id, version_info):
        """Create or update meeting metadata.
        
        Args:
            meeting_id: Meeting ID (timestamp).
            version_info: Dictionary with version information:
                - version_num: Version number (e.g., 1, 2, 3).
                - notes_path: Path to the notes file.
                - transcript_path: Path to the transcript file.
                - transcript_json_path: Path to the transcript JSON file.
                - model_id: AI model used for notes generation.
                - transcription_service: Service used for transcription.
                - creation_time: Version creation timestamp.
                - name: Optional custom name for this version.
                - comments: Optional user comments.
        
        Returns:
            Updated metadata dictionary.
        """
        metadata_path = self.get_meeting_metadata_path(meeting_id)
        
        # Load existing metadata or create new
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, 'r') as f:
                    metadata = json.load(f)
            except Exception as e:
                logger.error(f"Error reading metadata file {metadata_path}: {e}")
                metadata = self._create_new_metadata(meeting_id)
        else:
            metadata = self._create_new_metadata(meeting_id)
        
        # Add/update version info
        version_num = str(version_info.get('version_num', 1))
        creation_time = version_info.get('creation_time', datetime.now().isoformat())
        
        # Get friendly model name if available
        model_id = version_info.get('model_id', "unknown_model")
        model_name = self._get_friendly_model_name(model_id)
        
        # Get friendly transcription service name
        service_type = version_info.get('transcription_service', "unknown_service")
        service_name = self._get_friendly_service_name(service_type)
        
        # Ensure versions dictionary exists
        if 'versions' not in metadata:
            metadata['versions'] = {}
        
        # Add version information
        metadata['versions'][version_num] = {
            'notes_path': version_info.get('notes_path', None),
            'transcript_path': version_info.get('transcript_path', None),
            'transcript_json_path': version_info.get('transcript_json_path', None),
            'model': {
                'id': model_id,
                'name': model_name
            },
            'transcription_service': {
                'id': service_type,
                'name': service_name
            },
            'creation_time': creation_time,
            'name': version_info.get('name', f"Version {version_num}"),
            'comments': version_info.get('comments', ""),
            'is_default': version_info.get('is_default', version_num == '1')
        }
        
        # Update default version if specified
        if version_info.get('set_as_default', False):
            for ver in metadata['versions']:
                metadata['versions'][ver]['is_default'] = (ver == version_num)
        
        # Update latest_version
        metadata['latest_version'] = max([int(v) for v in metadata['versions'].keys()])
        
        # Update metadata file
        try:
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)
        except Exception as e:
            logger.error(f"Error writing metadata file {metadata_path}: {e}")
        
        return metadata
    
    def _create_new_metadata(self, meeting_id):
        """Create new metadata structure for a meeting.
        
        Args:
            meeting_id: Meeting ID (timestamp).
            
        Returns:
            New metadata dictionary.
        """
        # Format display date from meeting_id
        if len(meeting_id) >= 15:  # Format: YYYYMMDD_HHMMSS
            year = meeting_id[:4]
            month = meeting_id[4:6]
            day = meeting_id[6:8]
            hour = meeting_id[9:11]
            minute = meeting_id[11:13]
            display_date = f"{year}-{month}-{day} {hour}:{minute}"
        else:
            display_date = "Unknown Date"
            
        return {
            'meeting_id': meeting_id,
            'display_date': display_date,
            'creation_time': datetime.now().isoformat(),
            'latest_version': 1,
            'versions': {}
        }
    
    def get_metadata(self, meeting_id):
        """Get metadata for a meeting.
        
        Args:
            meeting_id: Meeting ID (timestamp).
            
        Returns:
            Metadata dictionary or None if not found.
        """
        metadata_path = self.get_meeting_metadata_path(meeting_id)
        
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error reading metadata file {metadata_path}: {e}")
                return None
        else:
            # Try to auto-discover and generate metadata
            return self._auto_discover_metadata(meeting_id)
    
    def _auto_discover_metadata(self, meeting_id):
        """Auto-discover files and create metadata for a meeting.
        
        Args:
            meeting_id: Meeting ID (timestamp).
            
        Returns:
            Generated metadata dictionary or None if files not found.
        """
        # Find notes files for this meeting
        notes_files = []
        transcript_files = []
        transcript_json_files = []
        
        for file in os.listdir(self.notes_dir):
            if file.startswith(f"meeting_notes_{meeting_id}") and file.endswith(".md"):
                notes_files.append(os.path.join(self.notes_dir, file))
            elif file.startswith(f"transcript_{meeting_id}") and file.endswith(".txt"):
                transcript_files.append(os.path.join(self.notes_dir, file))
            elif file.startswith(f"transcript_{meeting_id}") and file.endswith(".json"):
                transcript_json_files.append(os.path.join(self.notes_dir, file))
        
        if not notes_files and not transcript_files:
            return None
            
        # Create initial metadata
        metadata = self._create_new_metadata(meeting_id)
        
        # Extract version numbers from filenames
        version_pattern = re.compile(r"_v(\d+)\.md$")
        
        # Process notes files
        for notes_path in notes_files:
            filename = os.path.basename(notes_path)
            match = version_pattern.search(filename)
            
            if match:
                version_num = int(match.group(1))
            else:
                version_num = 1
                
            # Find corresponding transcript file
            transcript_path = None
            transcript_json_path = None
            
            for t_path in transcript_files:
                if os.path.basename(t_path).startswith(f"transcript_{meeting_id}"):
                    transcript_path = t_path
                    break
                    
            for tj_path in transcript_json_files:
                if os.path.basename(tj_path).startswith(f"transcript_{meeting_id}"):
                    transcript_json_path = tj_path
                    break
            
            # Create version entry
            version_info = {
                'version_num': version_num,
                'notes_path': notes_path,
                'transcript_path': transcript_path,
                'transcript_json_path': transcript_json_path,
                'creation_time': datetime.fromtimestamp(os.path.getctime(notes_path)).isoformat(),
                'is_default': version_num == 1  # Make the first version the default
            }
            
            # Update metadata with this version
            self.create_or_update_metadata(meeting_id, version_info)
        
        # Return the updated metadata
        return self.get_metadata(meeting_id)
    
    def set_default_version(self, meeting_id, version_num):
        """Set the default version for a meeting.
        
        Args:
            meeting_id: Meeting ID (timestamp).
            version_num: Version number to set as default.
            
        Returns:
            Updated metadata dictionary.
        """
        metadata = self.get_metadata(meeting_id)
        if not metadata:
            return None
            
        version_num = str(version_num)
        
        # Update default status for all versions
        for ver in metadata['versions']:
            metadata['versions'][ver]['is_default'] = (ver == version_num)
        
        # Save updated metadata
        metadata_path = self.get_meeting_metadata_path(meeting_id)
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        
        return metadata
    
    def rename_version(self, meeting_id, version_num, new_name):
        """Rename a version.
        
        Args:
            meeting_id: Meeting ID (timestamp).
            version_num: Version number to rename.
            new_name: New name for the version.
            
        Returns:
            Updated metadata dictionary.
        """
        metadata = self.get_metadata(meeting_id)
        if not metadata:
            return None
            
        version_num = str(version_num)
        
        if version_num in metadata['versions']:
            metadata['versions'][version_num]['name'] = new_name
            
            # Save updated metadata
            metadata_path = self.get_meeting_metadata_path(meeting_id)
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)
        
        return metadata
    
    def add_comments(self, meeting_id, version_num, comments):
        """Add comments to a version.
        
        Args:
            meeting_id: Meeting ID (timestamp).
            version_num: Version number to add comments to.
            comments: Comments text.
            
        Returns:
            Updated metadata dictionary.
        """
        metadata = self.get_metadata(meeting_id)
        if not metadata:
            return None
            
        version_num = str(version_num)
        
        if version_num in metadata['versions']:
            metadata['versions'][version_num]['comments'] = comments
            
            # Save updated metadata
            metadata_path = self.get_meeting_metadata_path(meeting_id)
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)
        
        return metadata
    
    def get_default_version(self, meeting_id):
        """Get the default version for a meeting.
        
        Args:
            meeting_id: Meeting ID (timestamp).
            
        Returns:
            Default version number as string, or None if no metadata.
        """
        metadata = self.get_metadata(meeting_id)
        if not metadata or 'versions' not in metadata:
            return None
            
        for ver, info in metadata['versions'].items():
            if info.get('is_default', False):
                return ver
        
        # If no default set, use the latest version
        if metadata.get('latest_version'):
            return str(metadata['latest_version'])
            
        return None
    
    def compare_versions(self, meeting_id, version1, version2):
        """Compare two versions of notes.
        
        Args:
            meeting_id: Meeting ID (timestamp).
            version1: First version number.
            version2: Second version number.
            
        Returns:
            Dictionary with comparison results.
        """
        metadata = self.get_metadata(meeting_id)
        if not metadata:
            return None
            
        version1 = str(version1)
        version2 = str(version2)
        
        if version1 not in metadata['versions'] or version2 not in metadata['versions']:
            return None
            
        # Get notes content
        notes1_path = metadata['versions'][version1].get('notes_path')
        notes2_path = metadata['versions'][version2].get('notes_path')
        
        if not notes1_path or not notes2_path:
            return None
            
        try:
            with open(notes1_path, 'r') as f:
                notes1_content = f.readlines()
            with open(notes2_path, 'r') as f:
                notes2_content = f.readlines()
                
            # Generate diff
            diff = difflib.unified_diff(
                notes1_content, 
                notes2_content,
                fromfile=f"Version {version1}",
                tofile=f"Version {version2}",
                lineterm=''
            )
            
            return {
                'version1': {
                    'number': version1,
                    'name': metadata['versions'][version1].get('name'),
                    'content': ''.join(notes1_content)
                },
                'version2': {
                    'number': version2,
                    'name': metadata['versions'][version2].get('name'),
                    'content': ''.join(notes2_content)
                },
                'diff': list(diff)
            }
        except Exception as e:
            logger.error(f"Error comparing versions: {e}")
            return None
    
    def get_all_meetings_with_metadata(self):
        """Get all meetings with their metadata.
        
        Returns:
            List of dictionaries containing meeting metadata.
        """
        meetings = []
        
        # First look for metadata files
        metadata_pattern = re.compile(r"meeting_(\d+_\d+)_metadata\.json")
        
        for file in os.listdir(self.metadata_dir):
            match = metadata_pattern.search(file)
            if match:
                meeting_id = match.group(1)
                metadata = self.get_metadata(meeting_id)
                if metadata:
                    meetings.append(metadata)
        
        # Then look for notes files without metadata
        notes_pattern = re.compile(r"meeting_notes_(\d+_\d+).*\.md")
        found_meeting_ids = set(m['meeting_id'] for m in meetings)
        
        for file in os.listdir(self.notes_dir):
            match = notes_pattern.search(file)
            if match:
                meeting_id = match.group(1)
                
                if meeting_id not in found_meeting_ids:
                    # Create metadata for this meeting
                    metadata = self._auto_discover_metadata(meeting_id)
                    if metadata:
                        meetings.append(metadata)
                        found_meeting_ids.add(meeting_id)
        
        # Sort by meeting ID (timestamp), newest first
        meetings.sort(key=lambda x: x['meeting_id'], reverse=True)
        
        return meetings
    
    def _get_friendly_model_name(self, model_id):
        """Get a friendly name for a model ID.
        
        Args:
            model_id: Model ID string.
            
        Returns:
            Friendly name for the model.
        """
        model_names = {
            "anthropic.claude-v2": "Claude 2",
            "anthropic.claude-v2:1": "Claude 2.1",
            "anthropic.claude-3-sonnet-20240229-v1:0": "Claude 3 Sonnet",
            "anthropic.claude-3-opus-20240229-v1:0": "Claude 3 Opus",
            "anthropic.claude-3-haiku-20240307-v1:0": "Claude 3 Haiku",
            "anthropic.claude-3-5-sonnet-20240620-v1:0": "Claude 3.5 Sonnet",
        }
        
        if model_id in model_names:
            return model_names[model_id]
        else:
            # Extract model name from ID if possible
            if "claude" in model_id.lower():
                parts = model_id.split(".")
                if len(parts) > 1:
                    return parts[1].replace("-", " ").title()
            
            # Just return the ID if we can't make it nicer
            return model_id
    
    def _get_friendly_service_name(self, service_type):
        """Get a friendly name for a transcription service.
        
        Args:
            service_type: Service type string.
            
        Returns:
            Friendly name for the service.
        """
        service_names = {
            "aws": "AWS Transcribe",
            "whisper": "OpenAI Whisper",
            "mac": "macOS Built-in"
        }
        
        return service_names.get(service_type, service_type)
    
    def delete_version(self, meeting_id, version_num):
        """Delete a version from metadata (doesn't delete actual files).
        
        Args:
            meeting_id: Meeting ID (timestamp).
            version_num: Version number to delete.
            
        Returns:
            Updated metadata dictionary.
        """
        metadata = self.get_metadata(meeting_id)
        if not metadata:
            return None
            
        version_num = str(version_num)
        
        if version_num in metadata['versions']:
            # Check if this was the default version
            was_default = metadata['versions'][version_num].get('is_default', False)
            
            # Remove the version
            del metadata['versions'][version_num]
            
            # If there are no more versions, delete the metadata file
            if not metadata['versions']:
                os.remove(self.get_meeting_metadata_path(meeting_id))
                return None
                
            # Update latest version number
            version_numbers = [int(v) for v in metadata['versions'].keys()]
            if version_numbers:
                metadata['latest_version'] = max(version_numbers)
            else:
                metadata['latest_version'] = 0
                
            # If this was the default version, set a new default
            if was_default and version_numbers:
                # Use the latest version as default
                new_default = str(metadata['latest_version'])
                metadata['versions'][new_default]['is_default'] = True
            
            # Save updated metadata
            metadata_path = self.get_meeting_metadata_path(meeting_id)
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)
        
        return metadata
