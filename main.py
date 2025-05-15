#!/usr/bin/env python3
"""
Meeting Notes Generator
A tool to capture system audio during meetings and generate notes using AWS services.

This application records audio from meetings, transcribes it using AWS Transcribe,
and generates structured meeting notes using AWS Bedrock.
"""

import os
import sys
import logging
import argparse
from ui.main_window import run_app

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("meeting_notes_generator.log")
    ]
)
logger = logging.getLogger("meeting_notes_generator")


def setup_environment():
    """Setup the application environment."""
    # Create necessary directories
    os.makedirs("recordings", exist_ok=True)
    os.makedirs("notes", exist_ok=True)
    
    # Check for required dependencies
    try:
        import tkinter
        import pyaudio
        import boto3
    except ImportError as e:
        logger.error(f"Missing required dependency: {e}")
        print(f"Error: Missing required dependency: {e}")
        print("Please install all required dependencies with: pip install -r requirements.txt")
        sys.exit(1)
    
    # Check for AWS credentials
    try:
        boto3.session.Session().get_credentials()
    except Exception as e:
        logger.warning(f"AWS credentials not found or invalid: {e}")
        print("Warning: AWS credentials not found or may not be properly configured.")
        print("Make sure you have valid AWS credentials in ~/.aws/credentials or as environment variables.")
        print("The application may not function correctly without valid AWS credentials.")


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Meeting Notes Generator")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    return parser.parse_args()


def main():
    """Main application entry point."""
    # Parse arguments
    args = parse_arguments()
    
    # Set log level
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")
    
    # Setup environment
    setup_environment()
    
    # Start the UI
    try:
        logger.info("Starting Meeting Notes Generator")
        run_app()
    except Exception as e:
        logger.exception(f"Unhandled exception: {e}")
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
