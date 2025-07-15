"""
Configuration settings for Meeting Notes Generator.
"""

# AWS Configuration
AWS_REGION = "us-west-2"  # Change this to your preferred AWS region
S3_BUCKET = "meeting-notes-generator-recordings"  # Change this to your S3 bucket
S3_PREFIX = "recordings/"

# Audio Configuration
AUDIO_FORMAT = "wav"
CHANNELS = 1  # Changed from 2 (stereo) to 1 (mono) to fix channel mismatch
RATE = 44100  # Sample rate
CHUNK = 1024  # Buffer size
RECORD_SECONDS = 5  # Default recording time for testing

# UI Configuration
WINDOW_TITLE = "Meeting Notes Generator"
WINDOW_WIDTH = 800
WINDOW_HEIGHT = 600

# File paths
RECORDINGS_DIR = "recordings"

# AWS Bedrock model settings
# Previous models
# BEDROCK_MODEL_ID = "anthropic.claude-3-sonnet-20240229-v1:0"
# BEDROCK_MODEL_ID = "anthropic.claude-3-5-sonnet-20241022-v2:0"
# Using latest Claude Sonnet 4 model (requires inference profile)
BEDROCK_MODEL_ID = "anthropic.claude-sonnet-4-20250514-v1:0"  # Default model

# Transcription settings
TRANSCRIPTION_SERVICE = "whisper"  # Options: "aws", "whisper", "mac"
WHISPER_MODEL_SIZE = "small"   # Options: "tiny", "base", "small", "medium", "large"
