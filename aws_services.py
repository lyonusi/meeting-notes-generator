"""
AWS services integration for Meeting Notes Generator.
Handles interactions with S3, Transcribe, and Bedrock.
"""

import os
import time
import json
import uuid
import logging
import boto3
from datetime import datetime
from botocore.exceptions import ClientError

from config import AWS_REGION, S3_BUCKET, S3_PREFIX, BEDROCK_MODEL_ID

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class AWSHandler:
    """Handles AWS service interactions."""
    
    def __init__(self, bedrock_profile='bedrock'):
        """Initialize AWS clients with appropriate profiles.
        
        Args:
            bedrock_profile: AWS profile for Bedrock API calls (default: 'bedrock')
        """
        # Create default session for S3 and Transcribe
        self.default_session = boto3.Session()  # Uses default profile
        
        # Create a separate session for Bedrock with the specified profile
        self.bedrock_session = boto3.Session(profile_name=bedrock_profile)
        
        # Create clients from appropriate sessions
        self.s3_client = self.default_session.client('s3', region_name=AWS_REGION)
        self.transcribe_client = self.default_session.client('transcribe', region_name=AWS_REGION)
        self.bedrock_runtime = self.bedrock_session.client('bedrock-runtime', region_name=AWS_REGION)
        self.bedrock_client = self.bedrock_session.client('bedrock', region_name=AWS_REGION)
        
        logger.info(f"Using default profile for S3 and Transcribe")
        logger.info(f"Using '{bedrock_profile}' profile for Bedrock API")
        
        # Cache AWS account ID
        self.aws_account_id = self._get_aws_account_id()
        
        # Cache inference profiles at initialization
        self.inference_profiles = {}
        self.refresh_inference_profiles_cache()
        
        # Ensure S3 bucket exists
        self._ensure_bucket_exists()
    
    def _ensure_bucket_exists(self):
        """Check if S3 bucket exists and create it if needed."""
        try:
            self.s3_client.head_bucket(Bucket=S3_BUCKET)
            logger.info(f"S3 bucket {S3_BUCKET} exists.")
            # Set up lifecycle policy for existing bucket
            self._configure_bucket_lifecycle()
            return True
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code')
            
            if error_code == '404':
                logger.info(f"S3 bucket {S3_BUCKET} does not exist. Attempting to create it...")
                try:
                    if AWS_REGION == 'us-east-1':
                        self.s3_client.create_bucket(Bucket=S3_BUCKET)
                    else:
                        self.s3_client.create_bucket(
                            Bucket=S3_BUCKET,
                            CreateBucketConfiguration={'LocationConstraint': AWS_REGION}
                        )
                    logger.info(f"S3 bucket {S3_BUCKET} created successfully.")
                    # Set up lifecycle policy for new bucket
                    self._configure_bucket_lifecycle()
                    return True
                except ClientError as e2:
                    logger.warning(f"Could not create S3 bucket: {e2}")
                    logger.warning("The application will continue running, but AWS features will be limited.")
                    return False
            else:
                # Handle 403 Forbidden and other errors
                logger.warning(f"Cannot access S3 bucket: {e}")
                logger.warning("The application will continue running, but AWS features will be limited.")
                return False
    
    def _configure_bucket_lifecycle(self):
        """Set a lifecycle policy on the bucket for auto-deletion after 30 days."""
        try:
            lifecycle_config = {
                'Rules': [
                    {
                        'ID': 'Delete after 30 days',
                        'Status': 'Enabled',
                        'Prefix': S3_PREFIX,
                        'Expiration': {'Days': 30}
                    }
                ]
            }
            self.s3_client.put_bucket_lifecycle_configuration(
                Bucket=S3_BUCKET,
                LifecycleConfiguration=lifecycle_config
            )
            logger.info(f"Set 30-day retention policy on {S3_BUCKET}")
        except ClientError as e:
            logger.warning(f"Could not set bucket lifecycle policy: {e}")
            logger.warning("Files will remain in S3 until manually deleted.")
    
    def upload_audio_to_s3(self, file_path):
        """Upload audio file to S3.
        
        Args:
            file_path: Local path to the audio file.
            
        Returns:
            S3 URI of the uploaded file.
        """
        file_name = os.path.basename(file_path)
        s3_key = f"{S3_PREFIX}{file_name}"
        
        try:
            logger.info(f"Uploading {file_path} to S3...")
            self.s3_client.upload_file(file_path, S3_BUCKET, s3_key)
            s3_uri = f"s3://{S3_BUCKET}/{s3_key}"
            logger.info(f"File uploaded successfully to {s3_uri}")
            return s3_uri
        except ClientError as e:
            logger.error(f"Error uploading file to S3: {e}")
            raise
    
    def delete_s3_file(self, s3_uri):
        """Delete a file from S3 after it's been used for transcription.
        
        Args:
            s3_uri: S3 URI of the file to delete.
        """
        try:
            # Extract bucket name and key from S3 URI
            # Format: s3://bucket-name/key
            parts = s3_uri.replace("s3://", "").split("/", 1)
            if len(parts) != 2:
                logger.warning(f"Invalid S3 URI format: {s3_uri}")
                return
                
            bucket_name = parts[0]
            s3_key = parts[1]
            
            logger.info(f"Deleting S3 file: {s3_key}")
            self.s3_client.delete_object(Bucket=bucket_name, Key=s3_key)
            logger.info("S3 file deleted successfully")
        except Exception as e:
            logger.warning(f"Could not delete S3 file: {e}")
    
    def transcribe_audio(self, s3_uri):
        """Transcribe audio file using AWS Transcribe.
        
        Args:
            s3_uri: S3 URI of the audio file.
            
        Returns:
            Transcription result.
        """
        job_name = f"meeting-notes-transcription-{uuid.uuid4()}"
        
        try:
            logger.info(f"Starting transcription job {job_name}...")
            response = self.transcribe_client.start_transcription_job(
                TranscriptionJobName=job_name,
                Media={'MediaFileUri': s3_uri},
                MediaFormat=os.path.splitext(s3_uri)[1][1:],  # Get format from file extension
                LanguageCode='en-US',
                Settings={
                    'ShowSpeakerLabels': True,
                    'MaxSpeakerLabels': 10  # Adjust based on expected number of speakers
                }
            )
            
            # Wait for transcription to complete
            while True:
                status = self.transcribe_client.get_transcription_job(
                    TranscriptionJobName=job_name
                )
                job_status = status['TranscriptionJob']['TranscriptionJobStatus']
                
                if job_status in ['COMPLETED', 'FAILED']:
                    break
                
                logger.info(f"Transcription job status: {job_status}")
                time.sleep(5)  # Check every 5 seconds
            
            if job_status == 'COMPLETED':
                transcript_uri = status['TranscriptionJob']['Transcript']['TranscriptFileUri']
                
                # Get the transcript JSON
                import urllib.request
                with urllib.request.urlopen(transcript_uri) as response:
                    transcript_json = json.loads(response.read().decode('utf-8'))
                
                # Log the structure for debugging
                logger.info(f"Transcript structure: {list(transcript_json.keys())}")
                
                # Verify the expected structure exists
                if 'results' not in transcript_json or 'transcripts' not in transcript_json.get('results', {}):
                    logger.error("Unexpected transcript format")
                    # Create a simple transcript structure to avoid errors
                    transcript_json = {
                        'results': {
                            'transcripts': [{'transcript': 'No transcript content available'}]
                        }
                    }
                
                logger.info("Transcription completed successfully.")
                
                # Delete the S3 file now that transcription is complete
                logger.info("Deleting audio file from S3...")
                self.delete_s3_file(s3_uri)
                
                return transcript_json
            else:
                logger.error("Transcription job failed.")
                return None
                
        except ClientError as e:
            logger.error(f"Error in transcription process: {e}")
            raise
    
    def generate_meeting_notes(self, transcript_json, model_id=None):
        """Generate meeting notes using AWS Bedrock.
        
        Args:
            transcript_json: Transcription result from AWS Transcribe.
            model_id: Optional Bedrock model ID to use. If None, uses the default from config.
            
        Returns:
            Generated meeting notes as markdown text.
        """
        # Use the specified model or fall back to default
        used_model_id = model_id if model_id else BEDROCK_MODEL_ID
        logger.info(f"Using Bedrock model: {used_model_id}")
        # Extract the transcript text
        if 'results' not in transcript_json:
            logger.error("Invalid transcript format")
            return self._generate_fallback_notes("No transcript available")
        
        full_transcript = transcript_json['results']['transcripts'][0]['transcript']
        
        # Check for speaker labels
        speakers_text = ""
        if 'speaker_labels' in transcript_json['results']:
            try:
                speakers = transcript_json['results']['speaker_labels']['speakers']
                segments = transcript_json['results']['speaker_labels']['segments']
                
                # Create a mapping of speech by speaker
                speaker_segments = {}
                for segment in segments:
                    speaker_label = segment['speaker_label']
                    if speaker_label not in speaker_segments:
                        speaker_segments[speaker_label] = []
                    
                    start_time = float(segment['start_time'])
                    end_time = float(segment['end_time'])
                    
                    # Find all items that fall within this segment's time range
                    for item in transcript_json['results']['items']:
                        if 'start_time' in item and 'end_time' in item:
                            item_start = float(item['start_time'])
                            item_end = float(item['end_time'])
                            
                            if (item_start >= start_time and item_end <= end_time):
                                speaker_segments[speaker_label].append(item['alternatives'][0]['content'])
                
                # Format the speaker-separated transcript
                for speaker, words in speaker_segments.items():
                    speakers_text += f"\n{speaker}: {' '.join(words)}"
            except Exception as e:
                logger.warning(f"Error processing speaker labels: {e}")
        
        # Construct the prompt for Bedrock
        # Try to extract date from transcript_json or the calling method might have filename info
        meeting_date = None
        
        # Check if transcript_json has timestamp info
        if 'jobName' in transcript_json and transcript_json['jobName'].startswith('meeting-notes-transcription-'):
            pass  # AWS transcript job name doesn't contain date info
        
        # Check if any key in the transcript JSON mentions recording file
        recording_filename = None
        for key, value in transcript_json.items():
            if isinstance(value, str) and value.startswith("meeting_") and "_" in value:
                recording_filename = value
                break
                
        # Try to extract date from recording filename format: meeting_YYYYMMDD_HHMMSS
        if recording_filename:
            try:
                # Extract the date part
                date_part = recording_filename.split('_')[1]
                if len(date_part) == 8:  # YYYYMMDD format
                    year = date_part[:4]
                    month = date_part[4:6]
                    day = date_part[6:8]
                    meeting_date = f"{year}-{month}-{day}"
            except (IndexError, ValueError):
                pass
        
        # Fallback to current date if extraction failed
        if not meeting_date:
            meeting_date = datetime.now().strftime("%Y-%m-%d")
        
        prompt = f"""
        You are an expert meeting notes transcriber. Your task is to convert the following meeting transcript into clear, organized meeting notes.
        
        The notes should be formatted in Markdown and include:
        1. A title that describes the meeting topic
        2. Meeting date: {meeting_date}
        3. A brief overall summary of what was discussed
        4. Organized sections with key points, categorized by topic
        5. Action items clearly marked with checkboxes

        Please focus on making the notes concise, professional, and well-organized. Particularly optimize for SDE (Software Development Engineer) job-related meeting content.
        
        Your response should always start with meeting notes with title in the first line. For any information that is not part of the meeting notes, attach it to the end of your response, with a section separator before it. 
        
        Here is the transcript:
        {full_transcript}
        
        {speakers_text if speakers_text else ''}
        """
        
        try:
            logger.info("Generating meeting notes with AWS Bedrock...")
            
            request_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 4000,
                "temperature": 0.7,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ]
                    }
                ]
            }
            
            # Check if this model requires an inference profile (for newer models like Claude 3.7, Sonnet 4, etc.)
            needs_profile = any(model_type in used_model_id.lower() for model_type in ['claude-3-7', 'claude-sonnet-4'])
            
            # Key discovery from AWS docs: For models that need inference profiles,
            # we don't use a separate parameter. Instead, we REPLACE the modelId with the inference profile ARN!
            effective_model_id = used_model_id
            
            if needs_profile:
                profile_arn = self.get_inference_profile_for_model(used_model_id)
                if profile_arn:
                    # Replace the model ID with the inference profile ARN
                    effective_model_id = profile_arn
                    logger.info(f"Using inference profile ARN as model ID: {effective_model_id}")
                else:
                    logger.warning(f"No inference profile found for {used_model_id}, using base model ID")
            
            try:
                # Standard invoke_model with the effective model ID (which may be the inference profile ARN)
                logger.info(f"Invoking model with effective model ID: {effective_model_id}")
                
                # Use the effective model ID (which may be the inference profile ARN)
                response = self.bedrock_runtime.invoke_model(
                    modelId=effective_model_id,
                    contentType="application/json",
                    accept="application/json",
                    body=json.dumps(request_body)
                )
                
                # Parse response
                response_body = json.loads(response['body'].read().decode())
                generated_text = response_body['content'][0]['text']
                
                logger.info("Meeting notes generated successfully.")
                return generated_text
            except ClientError as bedrock_error:
                error_msg = str(bedrock_error)
                
                if "ValidationException" in error_msg and "on-demand throughput" in error_msg:
                    logger.warning(f"Model {used_model_id} requires an inference profile. Consider creating one.")
                    return self._generate_fallback_notes(full_transcript)
                elif "AccessDeniedException" in error_msg:
                    logger.warning(f"No access to model {used_model_id}. Using fallback notes generation.")
                    return self._generate_fallback_notes(full_transcript)
                else:
                    logger.error(f"Error calling Bedrock: {bedrock_error}")
                    return self._generate_fallback_notes(full_transcript)
            
        except Exception as e:
            logger.error(f"Unexpected error in notes generation: {e}")
            return self._generate_fallback_notes(full_transcript)
    
    def _generate_fallback_notes(self, transcript):
        """Generate simple notes when Bedrock is unavailable.
        
        Args:
            transcript: Transcript text.
            
        Returns:
            Basic formatted notes.
        """
        logger.info("Generating fallback notes")
        
        # Simple formatting of transcript as meeting notes
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        notes = f"""# Meeting Notes ({timestamp})

## Transcript

{transcript}

## Summary

Meeting transcript captured successfully. AI-generated notes are not available.
"""
        return notes
        
    def _get_aws_account_id(self):
        """Get the AWS account ID from the current session.
        
        Returns:
            AWS account ID as string or None if it cannot be determined.
        """
        try:
            sts_client = self.bedrock_session.client('sts')
            account_id = sts_client.get_caller_identity()["Account"]
            logger.info(f"Using AWS account ID: {account_id}")
            return account_id
        except Exception as e:
            logger.warning(f"Could not determine AWS account ID: {e}")
            return None
            
    def refresh_inference_profiles_cache(self):
        """Fetch and cache all available inference profiles."""
        try:
            response = self.bedrock_client.list_inference_profiles()
            profiles = response.get('inferenceProfiles', [])
            
            # Build a model_id -> profile_arn mapping
            self.inference_profiles = {}
            for profile in profiles:
                model_id = profile.get('modelId', '')
                profile_arn = profile.get('inferenceProfileArn', '')
                if model_id and profile_arn:
                    self.inference_profiles[model_id] = profile_arn
                    
            logger.info(f"Cached {len(self.inference_profiles)} inference profiles")
            
            # Log available profiles for debugging
            for model_id, arn in self.inference_profiles.items():
                logger.debug(f"Available inference profile: {model_id} -> {arn}")
                
        except Exception as e:
            logger.warning(f"Could not cache inference profiles: {e}")
    
    def get_inference_profiles(self):
        """Get available inference profiles.
        
        Returns:
            List of inference profiles.
        """
        try:
            response = self.bedrock_client.list_inference_profiles()
            profiles = response.get('inferenceProfiles', [])
            logger.info(f"Found {len(profiles)} inference profiles")
            return profiles
        except Exception as e:
            logger.warning(f"Could not get inference profiles: {e}")
            return []
    
    def get_inference_profile_for_model(self, model_id):
        """Get the inference profile ARN for a specific model.
        
        This method first checks the cached profiles, then attempts to find a direct match
        in the available profiles. If no direct match is found, it tries to construct a
        profile ARN based on the account ID and model pattern.
        
        Args:
            model_id: The model ID to find a profile for.
            
        Returns:
            Inference profile ARN or None if it cannot be determined.
        """
        # Check if we have a cached profile for this exact model
        if model_id in self.inference_profiles:
            profile_arn = self.inference_profiles[model_id]
            logger.info(f"Using cached inference profile for {model_id}: {profile_arn}")
            return profile_arn
        
        # If we don't have an exact match, try to refresh the cache
        # This handles cases where profiles were added since initialization
        logger.info(f"No cached inference profile for {model_id}, refreshing cache")
        self.refresh_inference_profiles_cache()
        
        # Check again after refresh
        if model_id in self.inference_profiles:
            profile_arn = self.inference_profiles[model_id]
            logger.info(f"Found inference profile after refresh: {profile_arn}")
            return profile_arn
        
        # If still no match, try to dynamically construct an ARN if we have the account ID
        if self.aws_account_id:
            # Map model IDs to their inference profile suffixes
            model_profile_mapping = {
                "anthropic.claude-sonnet-4-20250514-v1:0": "us.anthropic.claude-sonnet-4-20250514-v1:0"
            }
            
            # For models that might follow a pattern, dynamically construct the suffix
            if 'claude-sonnet-4' in model_id.lower() and model_id not in model_profile_mapping:
                # Extract the base name and version from the model ID
                parts = model_id.split('-')
                if len(parts) >= 4:
                    # Construct a profile suffix based on the model pattern
                    model_profile_mapping[model_id] = f"us.{model_id}"
                    logger.info(f"Created mapping for unknown model: {model_id} -> {model_profile_mapping[model_id]}")
                    
            # Get the profile suffix for this model
            profile_suffix = model_profile_mapping.get(model_id)
            if profile_suffix:
                # Construct the ARN
                arn = f"arn:aws:bedrock:{AWS_REGION}:{self.aws_account_id}:inference-profile/{profile_suffix}"
                logger.info(f"Dynamically constructed inference profile ARN: {arn}")
                # Add to cache for future use
                self.inference_profiles[model_id] = arn
                return arn
        
        logger.warning(f"No inference profile found for {model_id}")
        return None
        
    def get_model_inference_profile(self, model_id):
        """Find an inference profile for a specific model.
        
        Args:
            model_id: The model ID to find a profile for.
            
        Returns:
            Inference profile ARN or None if no match found.
        """
        # For backward compatibility, redirect to the new method
        logger.info(f"Using legacy get_model_inference_profile for {model_id}, redirecting to get_inference_profile_for_model")
        return self.get_inference_profile_for_model(model_id)
    
    def list_available_models(self):
        """Get available Bedrock models.
        
        Returns:
            List of available Bedrock models.
        """
        try:
            # Try to get the list of accessible foundation models
            response = self.bedrock_client.list_foundation_models()
            
            # Get available inference profiles
            has_profiles = len(self.get_inference_profiles()) > 0
            
            # Include all Claude models, with indicator for those needing inference profiles
            claude_models = []
            # Track seen model IDs to prevent duplicates
            seen_model_ids = set()
            
            for model in response.get('modelSummaries', []):
                model_id = model.get('modelId', '')
                
                # Skip if we've seen this model ID already
                if model_id in seen_model_ids:
                    continue
                    
                # Add to seen set
                seen_model_ids.add(model_id)
                
                # Only include Claude models
                if 'anthropic' in model_id.lower() and 'claude' in model_id.lower():
                    display_name = model.get('modelName', model_id)
                    
                    # Check if model needs inference profile
                    models_needing_profiles = ['claude-3-7', 'claude-sonnet-4']
                    needs_profile = any(model_type in model_id.lower() for model_type in models_needing_profiles)
                    
                    if needs_profile:
                        # Use the enhanced method to check for profile
                        profile_arn = self.get_inference_profile_for_model(model_id)
                        
                        if profile_arn:
                            # Extract account ID from the ARN for display
                            arn_parts = profile_arn.split(':')
                            account_display = ''
                            if len(arn_parts) > 4:
                                account_id = arn_parts[4]
                                # Only show last 4 digits for security
                                account_display = f" (Account: ...{account_id[-4:]})"
                            
                            # This model has an inference profile available
                            claude_models.append({
                                'id': model_id,
                                'name': f"{display_name} [With Inference Profile{account_display}]",
                                'profile_arn': profile_arn
                            })
                        else:
                            # This model might need an inference profile but none found
                            claude_models.append({
                                'id': model_id,
                                'name': f"{display_name} [Requires Inference Profile - NOT FOUND]",
                                'warning': "This model requires an inference profile that is not available."
                            })
                    else:
                        # Regular Claude model that doesn't need inference profile
                        claude_models.append({
                            'id': model_id,
                            'name': f"{display_name} ({model_id})"
                        })
            
            if claude_models:
                logger.info(f"Found {len(claude_models)} Claude models")
                return claude_models
            else:
                logger.warning("No Claude models found")
                # Return default models
                return self._get_default_models()
                
        except ClientError as e:
            logger.warning(f"Could not fetch Bedrock models: {e}")
            return self._get_default_models()
            
    def _get_default_models(self):
        """Return default Bedrock model options when API access fails.
        
        Returns:
            List of default model options.
        """
        return [
            {"id": "anthropic.claude-v2:1", "name": "Claude 2"},
            {"id": "anthropic.claude-3-sonnet-20240229-v1:0", "name": "Claude 3 Sonnet"},
            {"id": "anthropic.claude-3-haiku-20240307-v1:0", "name": "Claude 3 Haiku"}
        ]


# For testing standalone functionality
if __name__ == "__main__":
    # This would require an actual audio file to test
    handler = AWSHandler()
    print("AWSHandler initialized successfully.")
