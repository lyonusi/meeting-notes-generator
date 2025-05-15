#!/usr/bin/env python3
"""
Demo script for Meeting Notes Generator.

This script demonstrates the functionality of the Meeting Notes Generator
by simulating the processing of a pre-recorded audio file and showcasing
version management capabilities.
"""

import os
import sys
import logging
import argparse
import time
import json
import tkinter as tk
from tkinter import ttk
from notes_generator import NotesGenerator
from version_manager import VersionManager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("meeting_notes_generator_demo")


def process_sample_file(file_path, show_versions=False):
    """Process a sample audio file and demonstrate version management features."""
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
    notes_v1, transcript_v1, notes_path_v1 = generator.process_recording(file_path, print_progress)
    
    if not notes_v1:
        print("Failed to generate notes.")
        return False
        
    print("\n" + "=" * 80)
    print("VERSION 1 NOTES:")
    print("=" * 80)
    print(notes_v1[:500] + "..." if len(notes_v1) > 500 else notes_v1)
    print("\n" + "=" * 80)
    print(f"Notes saved to: {notes_path_v1}")
    
    transcript_path_v1 = notes_path_v1.replace("meeting_notes_", "transcript_").replace(".md", ".txt")
    transcript_json_path_v1 = transcript_path_v1.replace(".txt", ".json")
    
    if transcript_v1:
        print(f"Full transcript saved to: {transcript_path_v1}")
    
    # If we're not showing versions, we're done
    if not show_versions:
        return True
        
    # Demonstrate version management features
    print("\nDemonstrating version management features...")
    
    # Extract meeting ID from path
    import re
    match = re.search(r'meeting_notes_(\d+_\d+)\.md', os.path.basename(notes_path_v1))
    if not match:
        print("Could not extract meeting ID from notes path.")
        return True
        
    meeting_id = match.group(1)
    print(f"Meeting ID: {meeting_id}")
    
    # Initialize version manager
    notes_dir = os.path.dirname(notes_path_v1)
    version_manager = VersionManager(notes_dir)
    
    # Create metadata for first version
    print("Creating metadata for Version 1...")
    version_info_v1 = {
        'version_num': 1,
        'notes_path': notes_path_v1,
        'transcript_path': transcript_path_v1,
        'transcript_json_path': transcript_json_path_v1,
        'model_id': generator.model_id,
        'transcription_service': generator.transcription_service_type,
        'creation_time': None,  # Use current time
        'is_default': True
    }
    
    version_manager.create_or_update_metadata(meeting_id, version_info_v1)
    print("Version 1 metadata created.")
    
    print("\nGenerating Version 2 with different AI model...")
    
    # Load transcript JSON
    with open(transcript_json_path_v1, 'r') as f:
        transcript_json = json.load(f)
    
    # Try a different model ID if available
    available_models = generator.aws_handler.list_available_models()
    if len(available_models) > 1:
        # Use a different model than the first one
        alt_model = next((m['id'] for m in available_models if m['id'] != generator.model_id), generator.model_id)
    else:
        alt_model = generator.model_id
        
    print(f"Using alternative model: {alt_model}")
    print_progress("Generating Version 2 notes...", 0)
    
    # Generate notes with different model
    notes_v2, notes_path_v2 = generator.retry_notes_generation(
        transcript_json=transcript_json,
        model_id=alt_model,
        timestamp=meeting_id,
        callback=print_progress
    )
    
    if notes_v2:
        print("\n" + "=" * 80)
        print("VERSION 2 NOTES (different AI model):")
        print("=" * 80)
        print(notes_v2[:500] + "..." if len(notes_v2) > 500 else notes_v2)
        print("\n" + "=" * 80)
        print(f"Version 2 notes saved to: {notes_path_v2}")
        
        # Create metadata for second version
        print("Creating metadata for Version 2...")
        version_info_v2 = {
            'version_num': 2,
            'notes_path': notes_path_v2,
            'transcript_path': transcript_path_v1,
            'transcript_json_path': transcript_json_path_v1,
            'model_id': alt_model,
            'transcription_service': generator.transcription_service_type,
            'creation_time': None,  # Use current time
            'is_default': False
        }
        
        version_manager.create_or_update_metadata(meeting_id, version_info_v2)
        print("Version 2 metadata created.")
    
    print("\nNow demonstrating version comparison...")
    
    # Get metadata for this meeting
    metadata = version_manager.get_metadata(meeting_id)
    if metadata and 'versions' in metadata:
        print(f"Found {len(metadata['versions'])} versions of meeting {meeting_id}:")
        
        for ver_num, ver_info in metadata['versions'].items():
            model_name = ver_info.get('model', {}).get('name', 'Unknown Model')
            service_name = ver_info.get('transcription_service', {}).get('name', 'Unknown Service')
            default_marker = " (DEFAULT)" if ver_info.get('is_default', False) else ""
            
            print(f"- Version {ver_num}{default_marker}: Generated using {model_name}, Transcribed with {service_name}")
            
        # Compare versions
        if len(metadata['versions']) > 1:
            print("\nComparing Version 1 and Version 2:")
            comparison = version_manager.compare_versions(meeting_id, "1", "2")
            
            if comparison:
                print("\nDifferences found between versions:")
                diff_lines = [line for line in comparison['diff'] if line.startswith('+') or line.startswith('-')]
                
                # Show just a few diff lines for demonstration
                for i, line in enumerate(diff_lines[:10]):
                    if line.startswith('+'):
                        print(f"\033[92m{line}\033[0m")  # Green for additions
                    elif line.startswith('-'):
                        print(f"\033[91m{line}\033[0m")  # Red for removals
                        
                if len(diff_lines) > 10:
                    print(f"... and {len(diff_lines) - 10} more differences")
    
    # Demonstrate the GUI version if tkinter is available
    show_gui = input("\nWould you like to see the version comparison in a GUI window? (y/n): ").strip().lower()
    if show_gui == 'y':
        demo_gui_version_comparison(notes_dir, version_manager, meeting_id)
    
    return True


def demo_gui_version_comparison(notes_dir, version_manager, meeting_id):
    """Show a simple GUI demonstration of version comparison."""
    try:
        # Create a simple tkinter window
        root = tk.Tk()
        root.title("Meeting Notes Version Comparison Demo")
        root.geometry("900x600")
        
        # Get meeting metadata
        metadata = version_manager.get_metadata(meeting_id)
        if not metadata or 'versions' not in metadata:
            print("No version metadata available for GUI demo.")
            return
        
        # Add a title
        ttk.Label(root, text="Meeting Notes Version Comparison", font=("", 16, "bold")).pack(pady=10)
        
        # Create a notebook for tabs
        notebook = ttk.Notebook(root)
        notebook.pack(fill=tk.BOTH, expand=True, pady=10, padx=10)
        
        # Side-by-side comparison tab
        side_frame = ttk.Frame(notebook)
        notebook.add(side_frame, text="Side by Side Comparison")
        
        # Split the frame into two columns
        side_paned = ttk.PanedWindow(side_frame, orient=tk.HORIZONTAL)
        side_paned.pack(fill=tk.BOTH, expand=True)
        
        # Left frame (Version 1)
        left_frame = ttk.Frame(side_paned)
        side_paned.add(left_frame, weight=1)
        
        ttk.Label(left_frame, text="Version 1", font=("", 12, "bold")).pack(pady=(5, 0))
        
        left_text = tk.Text(left_frame, wrap=tk.WORD, width=40, height=25)
        left_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Get Version 1 content
        ver1_path = metadata['versions']['1']['notes_path']
        with open(ver1_path, 'r') as f:
            ver1_content = f.read()
            left_text.insert(tk.END, ver1_content)
        left_text.config(state=tk.DISABLED)
        
        # Right frame (Version 2) - if available
        right_frame = ttk.Frame(side_paned)
        side_paned.add(right_frame, weight=1)
        
        ttk.Label(right_frame, text="Version 2", font=("", 12, "bold")).pack(pady=(5, 0))
        
        right_text = tk.Text(right_frame, wrap=tk.WORD, width=40, height=25)
        right_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Get Version 2 content if available
        if '2' in metadata['versions']:
            ver2_path = metadata['versions']['2']['notes_path']
            with open(ver2_path, 'r') as f:
                ver2_content = f.read()
                right_text.insert(tk.END, ver2_content)
        right_text.config(state=tk.DISABLED)
        
        # Diff view tab
        diff_frame = ttk.Frame(notebook)
        notebook.add(diff_frame, text="Differences View")
        
        # Get diff if Version 2 exists
        if '2' in metadata['versions']:
            # Diff text widget
            diff_text = tk.Text(diff_frame, wrap=tk.NONE)
            diff_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
            
            # Configure tags for diff highlighting
            diff_text.tag_configure("removed", foreground="red", background="#ffdddd")
            diff_text.tag_configure("added", foreground="green", background="#ddffdd")
            diff_text.tag_configure("header", foreground="blue", background="#eeeeff")
            
            # Insert diff content with syntax highlighting
            comparison = version_manager.compare_versions(meeting_id, "1", "2")
            if comparison and 'diff' in comparison:
                for line in comparison['diff']:
                    if line.startswith('-'):
                        diff_text.insert(tk.END, line + "\n", "removed")
                    elif line.startswith('+'):
                        diff_text.insert(tk.END, line + "\n", "added")
                    elif line.startswith('@@') or line.startswith('---') or line.startswith('+++'):
                        diff_text.insert(tk.END, line + "\n", "header")
                    else:
                        diff_text.insert(tk.END, line + "\n")
            
            diff_text.config(state=tk.DISABLED)
        
        else:
            ttk.Label(diff_frame, text="Version 2 not available for comparison").pack(pady=20)
        
        # Add a close button
        ttk.Button(root, text="Close", command=root.destroy).pack(pady=10)
        
        # Start the GUI event loop
        root.mainloop()
        
    except Exception as e:
        print(f"Error showing GUI demo: {e}")


def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="Meeting Notes Generator Demo")
    parser.add_argument("--file", "-f", help="Path to sample audio file (WAV format)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--show-versions", action="store_true", help="Demonstrate version management features")
    args = parser.parse_args()
    
    # Set log level
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)
    
    # Check for audio file
    file_path = args.file
    if not file_path:
        print("Error: Please provide a path to a sample audio file.")
        print("Usage: python demo.py --file path/to/audio_file.wav [--show-versions]")
        return 1
    
    # Process the file
    success = process_sample_file(file_path, args.show_versions)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
