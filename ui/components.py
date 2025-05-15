"""
UI components for Meeting Notes Generator.
Contains reusable UI components for the application.
"""

import os
import json
import threading
from datetime import datetime, timedelta
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox


class RecordingControls(ttk.Frame):
    """Recording controls UI component."""
    
    def __init__(self, parent, start_callback, pause_callback, stop_callback):
        """Initialize recording controls.
        
        Args:
            parent: Parent widget.
            start_callback: Function to call when start/resume button is clicked.
            pause_callback: Function to call when pause button is clicked.
            stop_callback: Function to call when stop button is clicked.
        """
        super().__init__(parent)
        self.parent = parent
        self.start_callback = start_callback
        self.pause_callback = pause_callback
        self.stop_callback = stop_callback
        
        self.is_recording = False
        self.is_paused = False
        self.start_time = None
        self.elapsed_time = timedelta(0)
        self.timer_id = None
        
        self._create_widgets()
    
    def _create_widgets(self):
        """Create the UI widgets."""
        # Status label
        self.status_var = tk.StringVar(value="Ready to record")
        self.status_label = ttk.Label(self, textvariable=self.status_var, font=("", 14))
        self.status_label.pack(pady=(0, 10))
        
        # Timer display
        self.timer_var = tk.StringVar(value="00:00:00")
        self.timer_label = ttk.Label(self, textvariable=self.timer_var, font=("", 24))
        self.timer_label.pack(pady=(0, 20))
        
        # Control buttons frame
        self.control_frame = ttk.Frame(self)
        self.control_frame.pack(fill=tk.X, expand=True)
        
        # Start button
        self.start_button = ttk.Button(
            self.control_frame,
            text="Start",
            command=self.toggle_recording,
            width=15
        )
        self.start_button.pack(side=tk.LEFT, padx=5)
        
        # Pause button
        self.pause_button = ttk.Button(
            self.control_frame,
            text="Pause",
            command=self.toggle_pause,
            width=15,
            state=tk.DISABLED
        )
        self.pause_button.pack(side=tk.LEFT, padx=5)
        
        # Stop button
        self.stop_button = ttk.Button(
            self.control_frame,
            text="Stop",
            command=self.stop_recording,
            width=15,
            state=tk.DISABLED
        )
        self.stop_button.pack(side=tk.LEFT, padx=5)
    
    def toggle_recording(self):
        """Toggle recording state."""
        if self.is_recording:
            # Already recording, so this is a resume action
            if self.is_paused:
                self.is_paused = False
                self.start_button.config(text="Pause", state=tk.DISABLED)
                self.pause_button.config(text="Pause", state=tk.NORMAL)
                self.status_var.set("Recording...")
                self._start_timer()
                self.start_callback()  # Call the resume callback
        else:
            # Start a new recording
            self.is_recording = True
            self.is_paused = False
            self.start_button.config(text="Resume", state=tk.DISABLED)
            self.pause_button.config(state=tk.NORMAL)
            self.stop_button.config(state=tk.NORMAL)
            self.status_var.set("Recording...")
            self.elapsed_time = timedelta(0)
            self._start_timer()
            self.start_callback()  # Call the start callback
    
    def toggle_pause(self):
        """Toggle pause state."""
        if not self.is_recording or not self.start_callback:
            return
        
        if self.is_paused:
            # Resume recording
            self.is_paused = False
            self.pause_button.config(text="Pause")
            self.start_button.config(state=tk.DISABLED)
            self.status_var.set("Recording...")
            self._start_timer()
            self.start_callback()  # Call the resume callback
        else:
            # Pause recording
            self.is_paused = True
            self.pause_button.config(text="Resume")
            self.start_button.config(state=tk.DISABLED)
            self.status_var.set("Paused")
            self._stop_timer()
            self.pause_callback()  # Call the pause callback
    
    def stop_recording(self):
        """Stop recording."""
        if not self.is_recording:
            return
        
        self.is_recording = False
        self.is_paused = False
        self._stop_timer()
        self.start_button.config(text="Start", state=tk.NORMAL)
        self.pause_button.config(text="Pause", state=tk.DISABLED)
        self.stop_button.config(state=tk.DISABLED)
        self.status_var.set("Processing recording...")
        
        self.stop_callback()  # Call the stop callback
    
    def _start_timer(self):
        """Start the timer."""
        self.start_time = datetime.now() - self.elapsed_time
        self._update_timer()
    
    def _stop_timer(self):
        """Stop the timer."""
        if self.timer_id:
            self.after_cancel(self.timer_id)
            self.timer_id = None
        
        # Update the elapsed time
        if self.start_time:
            self.elapsed_time = datetime.now() - self.start_time
    
    def _update_timer(self):
        """Update the timer display."""
        if not self.is_recording or self.is_paused:
            return
        
        elapsed = datetime.now() - self.start_time
        hours, remainder = divmod(int(elapsed.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        self.timer_var.set(f"{hours:02}:{minutes:02}:{seconds:02}")
        
        # Schedule the next update
        self.timer_id = self.after(1000, self._update_timer)
    
    def reset(self):
        """Reset the recording controls."""
        self.is_recording = False
        self.is_paused = False
        self._stop_timer()
        self.start_button.config(text="Start", state=tk.NORMAL)
        self.pause_button.config(text="Pause", state=tk.DISABLED)
        self.stop_button.config(state=tk.DISABLED)
        self.timer_var.set("00:00:00")
        self.status_var.set("Ready to record")


class ProgressFrame(ttk.Frame):
    """Progress display UI component."""
    
    def __init__(self, parent):
        """Initialize progress display."""
        super().__init__(parent)
        self.parent = parent
        self._create_widgets()
    
    def _create_widgets(self):
        """Create the UI widgets."""
        # Status label
        self.status_var = tk.StringVar(value="")
        self.status_label = ttk.Label(self, textvariable=self.status_var)
        self.status_label.pack(pady=(5, 5), fill=tk.X)
        
        # Progress bar
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(
            self,
            variable=self.progress_var,
            maximum=100,
            mode='determinate',
            length=300
        )
        self.progress_bar.pack(pady=(0, 10), fill=tk.X)
    
    def update_progress(self, message, percentage):
        """Update the progress display.
        
        Args:
            message: Status message to display.
            percentage: Progress percentage (0-100, or -1 for error).
        """
        self.status_var.set(message)
        
        if percentage < 0:
            # Error state
            self.progress_bar.config(mode='indeterminate')
            self.progress_bar.start(10)
        else:
            # Normal progress
            self.progress_bar.config(mode='determinate')
            self.progress_bar.stop()
            self.progress_var.set(percentage)
        
        # Update UI
        self.update_idletasks()
    
    def reset(self):
        """Reset the progress display."""
        self.status_var.set("")
        self.progress_bar.config(mode='determinate')
        self.progress_bar.stop()
        self.progress_var.set(0)


class NotesDisplay(ttk.Frame):
    """Notes display UI component."""
    
    def __init__(self, parent):
        """Initialize notes display."""
        super().__init__(parent)
        self.parent = parent
        self._create_widgets()
    
    def clear(self):
        """Clear the notes display."""
        self.notes_text.delete(1.0, tk.END)
        self.notes_text.insert(tk.END, "No notes to display.")
        self.notes_content = None
        self.transcript_content = None
        self.current_notes_path = None
        
        # Disable buttons
        self.save_button.config(state=tk.DISABLED)
        self.copy_button.config(state=tk.DISABLED)
        self.view_transcript_button.config(state=tk.DISABLED)
    
    def _create_widgets(self):
        """Create the UI widgets."""
        # Title label
        self.title_label = ttk.Label(self, text="Generated Notes", font=("", 16))
        self.title_label.pack(pady=(5, 5), anchor=tk.W)
        
        # Notes text widget with scrollbars - not readonly to allow editing
        self.notes_text = scrolledtext.ScrolledText(
            self,
            wrap=tk.WORD,
            width=80,
            height=20,
            font=("", 12)
        )
        self.notes_text.pack(fill=tk.BOTH, expand=True, pady=(0, 5))
        
        # Add a toolbar frame for text editing controls
        self.toolbar_frame = ttk.Frame(self)
        self.toolbar_frame.pack(fill=tk.X, expand=False, pady=(0, 5))
        
        # Add save button
        self.save_edit_button = ttk.Button(
            self.toolbar_frame,
            text="Save",
            command=self._save_edited_notes,
            state=tk.DISABLED  # Enabled only when notes are loaded
        )
        self.save_edit_button.pack(side=tk.LEFT, padx=5)
        
        # Buttons frame
        self.buttons_frame = ttk.Frame(self)
        self.buttons_frame.pack(fill=tk.X, expand=True, pady=(0, 10))
        
        # Save button
        self.save_button = ttk.Button(
            self.buttons_frame,
            text="Save Notes As...",
            command=self.save_notes
        )
        self.save_button.pack(side=tk.LEFT, padx=5)
        
        # Copy button
        self.copy_button = ttk.Button(
            self.buttons_frame,
            text="Copy to Clipboard",
            command=self.copy_to_clipboard
        )
        self.copy_button.pack(side=tk.LEFT, padx=5)
        
        # View transcript button
        self.view_transcript_button = ttk.Button(
            self.buttons_frame,
            text="View Transcript",
            command=self.view_transcript
        )
        self.view_transcript_button.pack(side=tk.LEFT, padx=5)
        
        # Variables
        self.notes_content = None
        self.transcript_content = None
        self.current_notes_path = None
    
    def display_notes(self, notes_content, transcript_content=None, file_path=None):
        """Display generated notes.
        
        Args:
            notes_content: Notes content to display.
            transcript_content: Transcript content (optional).
            file_path: Path to the notes file (optional).
        """
        self.notes_text.delete(1.0, tk.END)
        
        if notes_content:
            self.notes_text.insert(tk.END, notes_content)
            self.notes_content = notes_content
            self.transcript_content = transcript_content
            self.current_notes_path = file_path
            
            # Enable buttons
            self.save_button.config(state=tk.NORMAL)
            self.save_edit_button.config(state=tk.NORMAL)  # Enable Save button when notes are loaded
            self.copy_button.config(state=tk.NORMAL)
            self.view_transcript_button.config(state=tk.NORMAL if transcript_content else tk.DISABLED)
            
            # Bind Ctrl+S / Cmd+S for saving
            self.notes_text.bind("<Control-s>", lambda e: self._save_edited_notes())
            self.notes_text.bind("<Command-s>", lambda e: self._save_edited_notes())
        else:
            self.notes_text.insert(tk.END, "No notes generated yet.")
            self.notes_content = None
            self.transcript_content = None
            self.current_notes_path = None
            
            # Disable buttons
            self.save_button.config(state=tk.DISABLED)
            self.save_edit_button.config(state=tk.DISABLED)
            self.copy_button.config(state=tk.DISABLED)
            self.view_transcript_button.config(state=tk.DISABLED)
            
            # Unbind keyboard shortcuts
            self.notes_text.unbind("<Control-s>")
            self.notes_text.unbind("<Command-s>")
    
    def save_notes(self):
        """Save notes to a file."""
        if not self.notes_content:
            return
        
        file_path = filedialog.asksaveasfilename(
            defaultextension=".md",
            filetypes=[("Markdown Files", "*.md"), ("Text Files", "*.txt"), ("All Files", "*.*")],
            initialfile="meeting_notes.md"
        )
        
        if file_path:
            try:
                with open(file_path, 'w') as f:
                    f.write(self.notes_content)
                messagebox.showinfo("Success", f"Notes saved to {file_path}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save notes: {e}")
    
    def copy_to_clipboard(self):
        """Copy notes content to clipboard."""
        if not self.notes_content:
            return
        
        self.clipboard_clear()
        self.clipboard_append(self.notes_content)
        
        # Show brief notification
        self.title_label.config(text="Copied to clipboard!")
        self.after(2000, lambda: self.title_label.config(text="Generated Notes"))
    
    def view_transcript(self):
        """View the transcript in a new window with speaker highlighting."""
        if not self.transcript_content:
            return
        
        # Check if we have the JSON transcript to show speaker labels
        json_path = None
        if self.current_notes_path:
            base_path = self.current_notes_path.replace("meeting_notes_", "transcript_").replace(".md", ".json")
            if os.path.exists(base_path):
                json_path = base_path
        
        # Create transcript window
        transcript_window = tk.Toplevel(self)
        transcript_window.title("Meeting Transcript")
        transcript_window.geometry("900x700")
        
        # Create a notebook with tabs
        notebook = ttk.Notebook(transcript_window)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Tab for plain transcript
        plain_tab = ttk.Frame(notebook)
        notebook.add(plain_tab, text="Plain Transcript")
        
        # Text widget for plain transcript
        plain_text = scrolledtext.ScrolledText(
            plain_tab,
            wrap=tk.WORD,
            width=80,
            height=30,
            font=("", 12)
        )
        plain_text.pack(fill=tk.BOTH, expand=True)
        
        # Insert transcript content
        plain_text.insert(tk.END, self.transcript_content)
        plain_text.config(state=tk.DISABLED)  # Make read-only
        
        # Tab for speaker-separated transcript (if available)
        if json_path:
            speaker_tab = ttk.Frame(notebook)
            notebook.add(speaker_tab, text="Speaker Separated")
            
            # Text widget with tags for different speakers
            speaker_text = scrolledtext.ScrolledText(
                speaker_tab,
                wrap=tk.WORD,
                width=80,
                height=30,
                font=("", 12)
            )
            speaker_text.pack(fill=tk.BOTH, expand=True)
            
            # Define colors for different speakers
            colors = ["#FF5733", "#33A8FF", "#9A33FF", "#33FF57", "#FFBD33", "#FF33BD"]
            
            try:
                # Load the JSON transcript
                with open(json_path, 'r') as f:
                    transcript_json = json.load(f)
                
                # Configure tags for speakers
                if 'results' in transcript_json and 'speaker_labels' in transcript_json['results']:
                    speakers = transcript_json['results']['speaker_labels']['speakers']
                    segments = transcript_json['results']['speaker_labels']['segments']
                    
                    # Set up tags for each speaker
                    for i, _ in enumerate(speakers):
                        speaker_label = f"spk_{i}"
                        color = colors[i % len(colors)]
                        speaker_text.tag_configure(speaker_label, foreground=color, font=("", 12, "bold"))
                    
                    # Format the speaker-separated transcript
                    speaker_text.insert(tk.END, "--- Speaker Separated Transcript ---\n\n")
                    
                    for segment in segments:
                        speaker_label = segment['speaker_label']
                        tag = f"spk_{int(speaker_label.split('_')[1])}"
                        
                        start_time = float(segment.get('start_time', 0))
                        end_time = float(segment.get('end_time', 0))
                        
                        # Format as mm:ss
                        time_str = f"[{int(start_time//60):02d}:{int(start_time%60):02d}] "
                        
                        # Insert speaker header
                        speaker_text.insert(tk.END, f"{time_str}{speaker_label}: ", tag)
                        
                        # Find all items that fall within this segment's time range
                        segment_content = []
                        for item in transcript_json['results']['items']:
                            if 'start_time' in item and 'end_time' in item:
                                item_start = float(item['start_time'])
                                item_end = float(item['end_time'])
                                
                                if (item_start >= start_time and item_end <= end_time):
                                    segment_content.append(item['alternatives'][0]['content'])
                        
                        # Insert the segment content
                        if segment_content:
                            speaker_text.insert(tk.END, f"{' '.join(segment_content)}\n\n")
                        else:
                            speaker_text.insert(tk.END, "[No content]\n\n")
                    
                    speaker_text.config(state=tk.DISABLED)  # Make read-only
                else:
                    speaker_text.insert(tk.END, "Speaker labels not available in this transcript.")
                    speaker_text.config(state=tk.DISABLED)
                    
            except Exception as e:
                speaker_text.insert(tk.END, f"Error parsing speaker information: {e}")
                speaker_text.config(state=tk.DISABLED)
        
        # Copy buttons - one for each tab
        buttons_frame = ttk.Frame(transcript_window)
        buttons_frame.pack(pady=(0, 10))
        
        # Copy plain transcript
        copy_plain_button = ttk.Button(
            buttons_frame,
            text="Copy Plain Transcript",
            command=lambda: self._copy_transcript_to_clipboard(plain_text)
        )
        copy_plain_button.pack(side=tk.LEFT, padx=10)
        
        # Copy speaker transcript if available
        if json_path:
            copy_speaker_button = ttk.Button(
                buttons_frame,
                text="Copy Speaker Transcript",
                command=lambda: self._copy_transcript_to_clipboard(speaker_text)
            )
            copy_speaker_button.pack(side=tk.LEFT, padx=10)

    def _toggle_edit_mode(self):
        """Toggle between edit and read-only modes for the notes."""
        if not self.current_notes_path:
            messagebox.showwarning("No Notes", "No notes are currently loaded to edit.")
            return
            
        self.edit_mode = not self.edit_mode
        
        if self.edit_mode:
            # Enable editing
            self.edit_button.config(text="Cancel Edit")
            self.save_edit_button.config(state=tk.NORMAL)
            self.title_label.config(text="Editing Notes")
            # Make text widget editable with a visual indicator
            self.notes_text.config(bg="#FFFFF0")  # Light yellow background to indicate edit mode
        else:
            # Disable editing - revert to original content
            self.edit_button.config(text="Edit Notes")
            self.save_edit_button.config(state=tk.DISABLED)
            self.title_label.config(text="Generated Notes")
            # Reset text widget appearance and revert content
            self.notes_text.config(bg="white")
            
            # Reload the original content
            self.notes_text.delete(1.0, tk.END)
            self.notes_text.insert(tk.END, self.notes_content)
    
    def _save_edited_notes(self):
        """Save the edited notes to the current file."""
        if not self.current_notes_path:
            return
            
        # Get current content from text widget
        edited_content = self.notes_text.get(1.0, tk.END).rstrip()
        
        try:
            # Save back to the same file
            with open(self.current_notes_path, 'w') as f:
                f.write(edited_content)
                
            # Update the stored content
            self.notes_content = edited_content
            
            # Show success notification
            self.title_label.config(text="Notes Saved Successfully")
            
            # Reset title after a delay
            self.after(2000, lambda: self.title_label.config(text="Generated Notes"))
            
            # Refresh the meetings list in the main window to update any title changes
            main_window = self.winfo_toplevel()
            if hasattr(main_window, '_refresh_meetings_list'):
                main_window._refresh_meetings_list()
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save notes: {e}")
    
    def _copy_transcript_to_clipboard(self, text_widget):
        """Copy transcript content to clipboard."""
        transcript = text_widget.get(1.0, tk.END)
        self.clipboard_clear()
        self.clipboard_append(transcript)
        
        # Show brief notification
        messagebox.showinfo("Copied", "Transcript copied to clipboard")
