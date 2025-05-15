#!/usr/bin/env python3
"""
Demo script for Meeting Notes Generator.

This script demonstrates the functionality of the Meeting Notes Generator
by simulating the processing of a pre-recorded audio file.
"""

import os
import sys
import logging
import argparse
from notes_generator import NotesGenerator

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("meeting_notes_generator_demo")


def process_sample_file(file_path):
    """Process a sample audio file."""
    if not os.path.exists(file_path):
        logger.error(f"Sample file not found: {file_path}")
        print(f"Error: Sample file not found: {file_path}")
        return False
    
    print(f"Processing sample file: {file_path}")
    print("This will upload the file to AWS, transcribe it, and generate meeting notes.")
    print("Note: AWS charges may apply.")
    
    # Create notes generator
    generator = NotesGenerator()
    
    # Callback for progress updates
    def print_progress(message, percentage):
        if percentage < 0:
            print(f"Error: {message}")
        else:
            print(f"{message} ({percentage}%)")
    
    # Process the file
    notes, transcript, notes_path = generator.process_recording(file_path, print_progress)
    
    if notes:
        print("\n" + "=" * 80)
        print("GENERATED NOTES:")
        print("=" * 80)
        print(notes)
        print("\n" + "=" * 80)
        print(f"Notes saved to: {notes_path}")
        
        if transcript:
            transcript_path = notes_path.replace("meeting_notes_", "transcript_").replace(".md", ".txt")
            print(f"Full transcript saved to: {transcript_path}")
        
        return True
    else:
        print("Failed to generate notes.")
        return False


def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="Meeting Notes Generator Demo")
    parser.add_argument("--file", "-f", help="Path to sample audio file (WAV format)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()
    
    # Set log level
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)
    
    # Check for audio file
    file_path = args.file
    if not file_path:
        print("Error: Please provide a path to a sample audio file.")
        print("Usage: python demo.py --file path/to/audio_file.wav")
        return 1
    
    # Process the file
    success = process_sample_file(file_path)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
