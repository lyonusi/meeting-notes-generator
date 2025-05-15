"""
Main window for Meeting Notes Generator.
Creates the main application window and integrates all components.
"""

import os
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import sys

# Add parent directory to path to allow importing from parent modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from audio_capture import AudioRecorder
from notes_generator import NotesGenerator
from version_manager import VersionManager
from ui.components import RecordingControls, ProgressFrame, NotesDisplay
from ui.version_panel import VersionHistoryPanel, VersionComparePanel
from ui.version_updater import update_version_metadata


class MainWindow:
    """Main application window."""
    
    def __init__(self, root):
        """Initialize the main window.
        
        Args:
            root: Root Tkinter window.
        """
        self.root = root
        self.root.title("Meeting Notes Generator")
        self.root.geometry("1280x960")
        self.root.minsize(800, 600)
        
        # Set theme
        style = ttk.Style()
        try:
            style.theme_use("clam")  # More modern looking theme
        except tk.TclError:
            pass  # Fallback to default if theme not available
        
        # Load settings first
        self.settings_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "user_settings.json")
        self.settings = self._load_settings()
        
        # Initialize components with settings
        # Pass saved settings to AudioRecorder
        self.recorder = AudioRecorder(self.settings)
        
        # Configure notes generator with saved settings
        self.notes_generator = NotesGenerator(
            transcription_service=self.settings.get("transcription_service", "whisper"),
            model_id=self.settings.get("ai_model"),
            whisper_model_size=self.settings.get("whisper_model_size")
        )
        
        # Current recording file
        self.current_recording = None
        self.processing_thread = None
        
        # Reference to notes directory from the notes generator
        self.notes_dir = self.notes_generator.notes_dir
        
        # Settings storage - keeps track of user preferences
        self.settings_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "user_settings.json")
        self.settings = self._load_settings()
        
        # Create UI layout
        self._create_layout()
        
        # Configure protocol for window close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
    
    def _load_settings(self):
        """Load user settings from file."""
        try:
            if os.path.exists(self.settings_file):
                import json
                with open(self.settings_file, 'r') as f:
                    return json.load(f)
            return {
                "input_device": 0,  # Default input device index
                "output_device": 0,  # Default output device index
                "transcription_service": "aws",  # Default to AWS
                "whisper_model_size": "base",  # Default whisper model size
                "ai_model": None  # Will be populated when models are loaded
            }
        except Exception as e:
            print(f"Error loading settings: {e}")
            return {}
    
    def _save_settings(self):
        """Save user settings to file."""
        try:
            # Update settings dictionary with current values
            if hasattr(self, 'input_device_var'):
                input_selection = self.input_device_combo.get()
                try:
                    self.settings["input_device"] = int(input_selection.split(":")[0])
                except (ValueError, IndexError, AttributeError):
                    pass
                
            if hasattr(self, 'output_device_var'):
                output_selection = self.output_device_combo.get()
                try:
                    self.settings["output_device"] = int(output_selection.split(":")[0])
                except (ValueError, IndexError, AttributeError):
                    pass
                
            if hasattr(self, 'transcription_combo') and hasattr(self, 'available_services'):
                service_name = self.transcription_combo.get()
                if service_name in self.available_services:
                    self.settings["transcription_service"] = self.available_services[service_name]
            
            if hasattr(self, 'whisper_size_var'):
                self.settings["whisper_model_size"] = self.whisper_size_var.get()
                
            if hasattr(self, 'model_combo') and hasattr(self, 'available_models'):
                model_name = self.model_combo.get()
                if model_name in self.available_models:
                    self.settings["ai_model"] = self.available_models[model_name]
            
            # Save to file
            import json
            with open(self.settings_file, 'w') as f:
                json.dump(self.settings, f, indent=2)
        except Exception as e:
            print(f"Error saving settings: {e}")
    
    def _create_layout(self):
        """Create the main window layout."""
        # Main paned window
        self.main_pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.main_pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Left frame (controls)
        self.left_frame = ttk.Frame(self.main_pane)
        self.main_pane.add(self.left_frame, weight=45)
        
        # Right frame (notes display)
        self.right_frame = ttk.Frame(self.main_pane)
        self.main_pane.add(self.right_frame, weight=55)
        
        # Add components to left frame
        self._create_left_frame()
        
        # Add components to right frame
        self._create_right_frame()
    
    def _create_left_frame(self):
        """Create left frame with controls."""
        # Title label
        self.title_label = ttk.Label(self.left_frame, text="Meeting Notes Generator", font=("", 16, "bold"))
        self.title_label.pack(pady=(0, 20))
        
        # Audio device selection
        self.device_frame = ttk.LabelFrame(self.left_frame, text="Audio Device Selection")
        self.device_frame.pack(fill=tk.X, expand=False, pady=(0, 10))
        
        # Populate device selection
        self._create_device_selection()
        
        # Recording controls
        self.recording_controls = RecordingControls(
            self.left_frame,
            start_callback=self._start_recording,
            pause_callback=self._pause_recording,
            stop_callback=self._stop_recording
        )
        self.recording_controls.pack(fill=tk.X, expand=False, pady=(0, 10))
        
        # Progress frame
        self.progress_frame = ProgressFrame(self.left_frame)
        self.progress_frame.pack(fill=tk.X, expand=False, pady=(0, 10))
        
        # Previous recordings
        self.history_frame = ttk.LabelFrame(self.left_frame, text="Previous Recordings")
        self.history_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Populate history
        self._create_history_list()
    
    def _create_device_selection(self):
        """Create audio device selection UI."""
        # Get available devices
        devices = self.recorder.list_devices()
        
        # Input device selection
        input_frame = ttk.Frame(self.device_frame)
        input_frame.pack(fill=tk.X, expand=True, pady=5)
        
        ttk.Label(input_frame, text="Input Device:").pack(side=tk.LEFT, padx=5)
        
        # Input device combobox
        self.input_device_var = tk.StringVar()
        self.input_device_combo = ttk.Combobox(
            input_frame,
            textvariable=self.input_device_var,
            state="readonly",
            width=40
        )
        self.input_device_combo.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        
        # Populate input devices
        input_devices = [(idx, name) for idx, name in devices["input"]]
        self.input_device_combo["values"] = [f"{idx}: {name}" for idx, name in input_devices]
        
        # Use saved input device or default to first
        input_idx = self.settings.get("input_device", None)
        if input_idx is not None and input_devices:
            # Find the index in the combobox that matches the saved device
            combo_idx = 0
            for i, (idx, _) in enumerate(input_devices):
                if idx == input_idx:
                    combo_idx = i
                    break
            self.input_device_combo.current(combo_idx)
        elif input_devices:
            self.input_device_combo.current(0)
            
        self.input_device_combo.bind("<<ComboboxSelected>>", self._on_input_device_changed)
        
        # Output device selection
        output_frame = ttk.Frame(self.device_frame)
        output_frame.pack(fill=tk.X, expand=True, pady=5)
        
        ttk.Label(output_frame, text="Output Device:").pack(side=tk.LEFT, padx=5)
        
        # Output device combobox
        self.output_device_var = tk.StringVar()
        self.output_device_combo = ttk.Combobox(
            output_frame,
            textvariable=self.output_device_var,
            state="readonly",
            width=40
        )
        self.output_device_combo.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        
        # Populate output devices
        output_devices = [(idx, name) for idx, name in devices["output"]]
        self.output_device_combo["values"] = [f"{idx}: {name}" for idx, name in output_devices]
        
        # Use saved output device or default to first
        output_idx = self.settings.get("output_device", None)
        if output_idx is not None and output_devices:
            # Find the index in the combobox that matches the saved device
            combo_idx = 0
            for i, (idx, _) in enumerate(output_devices):
                if idx == output_idx:
                    combo_idx = i
                    break
            self.output_device_combo.current(combo_idx)
        elif output_devices:
            self.output_device_combo.current(0)
            
        self.output_device_combo.bind("<<ComboboxSelected>>", self._on_output_device_changed)
        
        # Create service selection notebook
        service_notebook = ttk.Notebook(self.device_frame)
        service_notebook.pack(fill=tk.X, expand=True, pady=5)
        
        # AI Model tab
        model_tab = ttk.Frame(service_notebook)
        service_notebook.add(model_tab, text="AI Model")
        
        # Transcription tab
        transcription_tab = ttk.Frame(service_notebook)
        service_notebook.add(transcription_tab, text="Transcription")
        
        # AI Model selection
        model_frame = ttk.Frame(model_tab)
        model_frame.pack(fill=tk.X, expand=True, pady=5)
        
        ttk.Label(model_frame, text="AI Model:").pack(side=tk.LEFT, padx=5)
        
        # Model combobox
        self.model_var = tk.StringVar()
        self.model_combo = ttk.Combobox(
            model_frame,
            textvariable=self.model_var,
            state="readonly",
            width=40
        )
        self.model_combo.pack(side=tk.LEFT, padx=5, fill=tk.X, expand=True)
        
        # Populate AI models
        # This will happen in a background thread to avoid UI freeze
        self.model_combo["values"] = ["Loading available models..."]
        self.model_combo.current(0)
        
        # Start thread to load models
        threading.Thread(target=self._load_ai_models, daemon=True).start()
        
        # Transcription service selection
        transcription_frame = ttk.Frame(transcription_tab)
        transcription_frame.pack(fill=tk.X, expand=True, pady=5)
        
        ttk.Label(transcription_frame, text="Service:").pack(side=tk.LEFT, padx=5)
        
        # Service combobox
        self.transcription_var = tk.StringVar(value="whisper")  # Default to Whisper
        self.transcription_combo = ttk.Combobox(
            transcription_frame,
            textvariable=self.transcription_var,
            state="readonly",
            width=20
        )
        self.transcription_combo.pack(side=tk.LEFT, padx=5)
        
        # Start thread to check available services
        threading.Thread(target=self._load_transcription_services, daemon=True).start()
        
        # Whisper model size (only visible when Whisper is selected)
        self.whisper_frame = ttk.Frame(transcription_tab)
        self.whisper_frame.pack(fill=tk.X, expand=True, pady=5)
        
        ttk.Label(self.whisper_frame, text="Whisper Model:").pack(side=tk.LEFT, padx=5)
        
        # Whisper model size combobox - use saved setting or default to "small"
        self.whisper_size_var = tk.StringVar(value=self.settings.get("whisper_model_size", "small"))
        self.whisper_size_combo = ttk.Combobox(
            self.whisper_frame,
            textvariable=self.whisper_size_var,
            state="readonly",
            width=15,
            values=["tiny", "base", "small", "medium", "large"]
        )
        self.whisper_size_combo.pack(side=tk.LEFT, padx=5)
        ttk.Label(self.whisper_frame, text="(smaller=faster, larger=more accurate)").pack(side=tk.LEFT, padx=5)
        
        # Initially hide the whisper frame unless whisper is selected
        self.whisper_frame.pack_forget()
        
        # Bind service selection changes
        self.transcription_combo.bind("<<ComboboxSelected>>", self._on_transcription_service_changed)
    
    def _on_input_device_changed(self, event):
        """Handle input device selection change."""
        selection = self.input_device_combo.get()
        try:
            device_idx = int(selection.split(":")[0])
            self.recorder.set_input_device(device_idx)
        except (ValueError, IndexError):
            pass
    
    def _on_output_device_changed(self, event):
        """Handle output device selection change."""
        selection = self.output_device_combo.get()
        try:
            device_idx = int(selection.split(":")[0])
            self.recorder.set_output_device(device_idx)
        except (ValueError, IndexError):
            pass
    
    def _load_ai_models(self):
        """Load available AI models from AWS Bedrock (runs in background thread)."""
        try:
            # Get available models
            models = self.notes_generator.aws_handler.list_available_models()
            
            # Format for display
            model_values = []
            self.available_models = {}  # Store mapping of display name to model ID
            
            for model in models:
                display_name = model.get('name') or model.get('id')
                model_id = model.get('id')
                if model_id:
                    model_values.append(display_name)
                    self.available_models[display_name] = model_id
            
            # Update UI from main thread
            self.root.after(0, lambda: self._update_model_dropdown(model_values))
        except Exception as e:
            # If there's an error, use default models
            from config import BEDROCK_MODEL_ID
            self.available_models = {"Default Model": BEDROCK_MODEL_ID}
            self.root.after(0, lambda: self._update_model_dropdown(["Default Model"]))
    
    def _update_model_dropdown(self, model_values):
        """Update the model dropdown with available models (called from main thread)."""
        if not model_values:
            model_values = ["Default Model"]
        
        self.model_combo["values"] = model_values
        
        # Try to select the saved model from settings
        saved_model_id = self.settings.get("ai_model", None)
        selected_index = 0
        
        if saved_model_id:
            print(f"Looking for saved model: {saved_model_id}")
            # Find the display name that corresponds to the saved model ID
            for i, display_name in enumerate(model_values):
                if display_name in self.available_models and self.available_models[display_name] == saved_model_id:
                    selected_index = i
                    print(f"Found saved model '{display_name}' at index {i}")
                    break
        
        # Set the current selection
        self.model_combo.current(selected_index)
        print(f"Selected model: {self.model_combo.get()}")
        
        # Bind selection change event
        self.model_combo.bind("<<ComboboxSelected>>", self._on_model_changed)
    
    def _load_transcription_services(self):
        """Load available transcription services (runs in background thread)."""
        try:
            # Get available services from the transcription module
            services = self.notes_generator.get_available_services()
            
            # Create friendly display names
            service_display = {
                "aws": "AWS Transcribe",
                "whisper": "OpenAI Whisper (Local)",
                "mac": "macOS Built-in"
            }
            
            service_values = [service_display.get(s, s) for s in services]
            service_map = {service_display.get(s, s): s for s in services}
            
            # Store the mapping for later use
            self.available_services = service_map
            
            # Update UI from main thread
            self.root.after(0, lambda: self._update_services_dropdown(service_values))
        except Exception as e:
            print(f"Error loading transcription services: {e}")
            # Just use AWS as fallback
            self.available_services = {"AWS Transcribe": "aws"}
            self.root.after(0, lambda: self._update_services_dropdown(["AWS Transcribe"]))
    
    def _update_services_dropdown(self, service_values):
        """Update services dropdown with available options."""
        if service_values:
            self.transcription_combo["values"] = service_values
            
            # Set current value based on what's configured in the notes generator
            current_service = self.notes_generator.transcription_service_type
            for display, value in self.available_services.items():
                if value == current_service:
                    self.transcription_var.set(display)
                    break
            
            # Bind selection change
            self.transcription_combo.bind("<<ComboboxSelected>>", self._on_transcription_service_changed)
    
    def _on_transcription_service_changed(self, event):
        """Handle transcription service selection change."""
        selection = self.transcription_combo.get()
        if selection in self.available_services:
            service_type = self.available_services[selection]
            
            # Update generator service
            if service_type == "whisper":
                # Get whisper settings and make sure the frame is visible
                self.whisper_frame.pack(fill=tk.X, expand=True, pady=5, after=self.transcription_combo.master)
                whisper_size = self.whisper_size_var.get()
                self.notes_generator.set_transcription_service(service_type, model_size=whisper_size)
            else:
                # Hide whisper settings for other services
                self.whisper_frame.pack_forget()
                self.notes_generator.set_transcription_service(service_type)
            
            print(f"Selected transcription service: {selection} ({service_type})")
    
    def _on_model_changed(self, event):
        """Handle model selection change."""
        selection = self.model_combo.get()
        if selection in self.available_models:
            model_id = self.available_models[selection]
            self.notes_generator.model_id = model_id
            print(f"Selected AI model: {selection} ({model_id})")
    
    def _create_history_list(self):
        """Create list of previous meetings."""
        # Create a tree view for meetings
        self.history_frame_inner = ttk.Frame(self.history_frame)
        self.history_frame_inner.pack(fill=tk.BOTH, expand=True, pady=(0, 5))
        
        # Create a treeview with columns - added Title column, and changed selectmode to allow multiple selections
        self.meeting_tree = ttk.Treeview(
            self.history_frame_inner, 
            columns=("Date", "Title", "Duration", "Status"),
            selectmode="extended",  # Allow multiple selections
            height=8
        )
        
        # Configure columns
        self.meeting_tree.column("#0", width=30, stretch=tk.NO)  # Icon column
        self.meeting_tree.column("Date", width=120, anchor=tk.W)  # Reduced width for date only
        self.meeting_tree.column("Title", width=250, anchor=tk.W)  # Increased width for title from 200 to 250
        self.meeting_tree.column("Duration", width=80, anchor=tk.CENTER)
        self.meeting_tree.column("Status", width=120, anchor=tk.W)
        
        # Configure headings
        self.meeting_tree.heading("#0", text="")
        self.meeting_tree.heading("Date", text="Date & Time")
        self.meeting_tree.heading("Title", text="Meeting Title")
        self.meeting_tree.heading("Duration", text="Duration")
        self.meeting_tree.heading("Status", text="Status")
        
        # Add scrollbar
        self.meeting_scrollbar = ttk.Scrollbar(self.history_frame_inner, orient="vertical", command=self.meeting_tree.yview)
        self.meeting_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.meeting_tree.configure(yscrollcommand=self.meeting_scrollbar.set)
        
        # Pack the tree
        self.meeting_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Bind events
        self.meeting_tree.bind("<Double-1>", self._on_meeting_double_click)
        self.meeting_tree.bind("<Button-3>", self._show_meeting_context_menu)  # Right-click
        self.meeting_tree.bind("<Delete>", lambda e: self._delete_selected_meeting())  # Delete key
        self.meeting_tree.bind("<BackSpace>", lambda e: self._delete_selected_meeting())  # Backspace key
        
        # Create context menu
        self.meeting_context_menu = tk.Menu(self.meeting_tree, tearoff=0)
        self.meeting_context_menu.add_command(label="Open Meeting", command=self._open_selected_meeting)
        self.meeting_context_menu.add_command(label="Regenerate Notes", command=self._regenerate_notes)
        self.meeting_context_menu.add_command(label="Retranscribe", command=self._retranscribe_meeting)
        self.meeting_context_menu.add_separator()
        self.meeting_context_menu.add_command(label="Delete Meeting", command=self._delete_selected_meeting)
        
        # Actions frame
        actions_frame = ttk.Frame(self.history_frame)
        actions_frame.pack(fill=tk.X, pady=(5, 0))
        
        # Refresh button
        self.refresh_button = ttk.Button(
            actions_frame,
            text="Refresh",
            command=self._refresh_meetings_list
        )
        self.refresh_button.pack(side=tk.LEFT, padx=5)
        
        # Import WAV button
        self.import_button = ttk.Button(
            actions_frame,
            text="Import WAV",
            command=self._import_audio_file
        )
        self.import_button.pack(side=tk.LEFT, padx=5)
        
        # Additional buttons frame (for more operations)
        additional_actions_frame = ttk.Frame(self.history_frame)
        additional_actions_frame.pack(fill=tk.X, pady=(5, 0))
        
        # Regenerate notes button
        self.regenerate_button = ttk.Button(
            additional_actions_frame,
            text="Regenerate Notes",
            command=self._regenerate_notes
        )
        self.regenerate_button.pack(side=tk.LEFT, padx=5)
        
        # Retranscribe button
        self.retranscribe_button = ttk.Button(
            additional_actions_frame,
            text="Retranscribe",
            command=self._retranscribe_meeting
        )
        self.retranscribe_button.pack(side=tk.LEFT, padx=5)
        
        # Delete button
        self.delete_button = ttk.Button(
            actions_frame,
            text="Delete Selected",
            command=self._delete_selected_meeting
        )
        self.delete_button.pack(side=tk.RIGHT, padx=5)
        
        # Populate list
        self._refresh_meetings_list()
        
    def _show_meeting_context_menu(self, event):
        """Show context menu on right-click in meeting tree."""
        try:
            # Get the item under the cursor
            item_id = self.meeting_tree.identify("item", event.x, event.y)
            if item_id:
                # Select the item
                self.meeting_tree.selection_set(item_id)
                self.meeting_tree.focus(item_id)
                # Show the menu
                self.meeting_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.meeting_context_menu.grab_release()
    
    def _delete_selected_recording(self):
        """Delete the selected recording and associated files."""
        try:
            # Get selected index
            index = self.history_list.curselection()[0]
            if 0 <= index < len(self.notes_history):
                note = self.notes_history[index]
                file_path = note["file_path"]
                
                # Confirm deletion
                if not messagebox.askyesno("Confirm Delete", 
                                         f"Are you sure you want to delete '{note['title']}'?\n\nThis will remove all associated files and cannot be undone."):
                    return
                    
                # Get paths for all associated files
                notes_file = file_path  # The .md file
                timestamp = note["timestamp"]
                
                # Define paths for associated files
                transcript_json = os.path.join(self.notes_dir, f"transcript_{timestamp}.json")
                transcript_txt = os.path.join(self.notes_dir, f"transcript_{timestamp}.txt")
                local_recording = os.path.join(self.notes_dir, f"local_recording_{timestamp}.wav")
                
                # Delete files if they exist
                deleted_files = []
                for f in [notes_file, transcript_json, transcript_txt, local_recording]:
                    if os.path.exists(f):
                        try:
                            os.remove(f)
                            deleted_files.append(os.path.basename(f))
                        except Exception as e:
                            messagebox.showerror("Error", f"Failed to delete {os.path.basename(f)}: {e}")
                
                # Refresh the list
                self._refresh_history_list()
                
                # Clear display if the deleted file was being viewed
                if hasattr(self, 'current_file') and self.current_file == file_path:
                    self.notes_display.clear()
                    
                # Show success message
                messagebox.showinfo("Files Deleted", 
                                  f"Successfully deleted {len(deleted_files)} files:\n" + 
                                  "\n".join(f"- {f}" for f in deleted_files))
                
        except (IndexError, AttributeError):
            messagebox.showerror("Error", "No item selected")
    
    def _refresh_meetings_list(self):
        """Refresh the meetings list with all recordings."""
        # Clear the tree
        for item in self.meeting_tree.get_children():
            self.meeting_tree.delete(item)
            
        # Get all meetings
        meetings = self._get_all_meetings()
        
        if not meetings:
            # Add a placeholder
            self.meeting_tree.insert("", "end", text="", values=("No meetings found", "", ""))
            return
        
        # Add each meeting to the tree
        for meeting in meetings:
            # Set icon based on status
            icon = "🔊" if meeting["has_recording"] else ""
            
            # Get the meeting title if available
            meeting_title = ""
            if meeting["has_notes"] and meeting["notes"]:
                # Sort notes by version (newest first)
                latest_notes = sorted(meeting["notes"], key=lambda x: x["version"], reverse=True)[0]
                try:
                    # Read the first line of the notes to get the title
                    with open(latest_notes["path"], 'r') as f:
                        first_line = f.readline().strip()
                        meeting_title = first_line.replace('#', '').strip()
                        if not meeting_title:
                            meeting_title = "Untitled Meeting"
                except Exception:
                    meeting_title = "Untitled Meeting"
            
            # Get date and title separately
            display_date = meeting["display_date"]
            
            # Set default title if none found
            if not meeting_title:
                meeting_title = "Untitled Meeting"
            
            # Format status and add version info if multiple notes versions exist
            status = ""
            if meeting["has_notes"] and meeting["has_transcript"]:
                status = "Complete"
                # Add version count if there are multiple versions
                if len(meeting["notes"]) > 1:
                    status = f"Complete ({len(meeting['notes'])} versions)"
            elif meeting["has_transcript"]:
                status = "Transcribed"
            elif meeting["has_recording"]:
                status = "Recorded"
            else:
                status = "Incomplete"
                
            # Insert into tree with separate date and title columns
            self.meeting_tree.insert(
                "", "end", 
                text=icon,
                values=(
                    display_date,   # Date column
                    meeting_title,  # Title column
                    meeting["duration"], 
                    status
                ),
                tags=(meeting["meeting_id"],)
            )
            
        # Store meetings reference
        self.meetings = meetings
    
    def _refresh_raw_list(self):
        """Refresh the list of raw recordings that haven't been transcribed."""
        self.raw_list.delete(0, tk.END)
        
        # Get all recording files from recordings directory
        recordings_dir = os.path.join(os.path.dirname(self.notes_dir), "recordings")
        if not os.path.exists(recordings_dir):
            self.raw_list.insert(tk.END, "No raw recordings found")
            return
        
        # Get all WAV files in the recordings directory
        raw_files = []
        for file in os.listdir(recordings_dir):
            if file.endswith(".wav"):
                # Extract timestamp from filename (meeting_YYYYMMDD_HHMMSS.wav)
                try:
                    timestamp = file.split('_')[1] + '_' + file.split('_')[2].split('.')[0]
                    date_str = f"{timestamp[:8]} {timestamp[9:11]}:{timestamp[11:13]}:{timestamp[13:15]}"
                    raw_files.append({
                        "file_path": os.path.join(recordings_dir, file),
                        "timestamp": timestamp,
                        "date": date_str,
                        "filename": file
                    })
                except (IndexError, ValueError):
                    # Skip files that don't match the expected format
                    continue
        
        # Sort by timestamp (newest first)
        raw_files.sort(key=lambda x: x["timestamp"], reverse=True)
        
        # Filter out files that already have transcripts
        transcript_timestamps = set()
        for file in os.listdir(self.notes_dir):
            if file.startswith("transcript_") and file.endswith(".json"):
                try:
                    transcript_timestamps.add(file.replace("transcript_", "").replace(".json", ""))
                except:
                    pass
        
        # Only keep files that don't have transcripts
        self.raw_history = [f for f in raw_files if f["timestamp"] not in transcript_timestamps]
        
        if not self.raw_history:
            self.raw_list.insert(tk.END, "No untranscribed recordings")
            return
        
        for raw_file in self.raw_history:
            self.raw_list.insert(tk.END, f"{raw_file['date']} - {raw_file['filename']}")
    
    def _on_raw_item_selected(self, event):
        """Handle double-click on a raw recording."""
        self._transcribe_selected_raw()
    
    def _show_raw_context_menu(self, event):
        """Show context menu on right-click in raw list."""
        try:
            # Get the index of the item under the cursor
            index = self.raw_list.nearest(event.y)
            if index >= 0:
                # Select the item
                self.raw_list.selection_clear(0, tk.END)
                self.raw_list.selection_set(index)
                self.raw_list.activate(index)
                self.raw_list.see(index)
                # Show the menu
                self.raw_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.raw_context_menu.grab_release()
    
    def _transcribe_selected_raw(self):
        """Transcribe selected raw recording."""
        try:
            index = self.raw_list.curselection()[0]
            if 0 <= index < len(self.raw_history):
                raw_file = self.raw_history[index]
                file_path = raw_file["file_path"]
                
                # Ask which service to use
                service_dialog = tk.Toplevel(self.root)
                service_dialog.title("Select Transcription Service")
                service_dialog.geometry("400x300")
                service_dialog.transient(self.root)  # Make dialog a child of parent window
                service_dialog.grab_set()  # Make dialog modal
                
                # Service selection
                service_frame = ttk.Frame(service_dialog, padding=10)
                service_frame.pack(fill=tk.X, expand=False)
                
                ttk.Label(service_frame, text="Select Transcription Service:").pack(anchor=tk.W, pady=5)
                
                # Service combobox
                service_var = tk.StringVar(value=self.transcription_combo.get())
                service_combo = ttk.Combobox(
                    service_frame,
                    textvariable=service_var,
                    state="readonly",
                    width=30,
                    values=list(self.available_services.keys())
                )
                service_combo.pack(fill=tk.X, pady=5)
                
                # Whisper options frame (only shown when Whisper is selected)
                whisper_frame = ttk.LabelFrame(service_dialog, text="Whisper Options", padding=10)
                
                ttk.Label(whisper_frame, text="Model Size:").pack(anchor=tk.W, pady=5)
                
                # Whisper model size combobox
                whisper_size_var = tk.StringVar(value=self.whisper_size_var.get())
                whisper_size_combo = ttk.Combobox(
                    whisper_frame,
                    textvariable=whisper_size_var,
                    state="readonly",
                    width=15,
                    values=["tiny", "base", "small", "medium", "large"]
                )
                whisper_size_combo.pack(fill=tk.X, pady=5)
                ttk.Label(whisper_frame, text="(smaller=faster, larger=more accurate)").pack(anchor=tk.W)
                
                # Initially show/hide Whisper frame based on current selection
                if "Whisper" in service_var.get():
                    whisper_frame.pack(fill=tk.X, padx=10, pady=5)
                
                # Update whisper frame visibility when service changes
                def on_service_changed(event):
                    if "Whisper" in service_var.get():
                        whisper_frame.pack(fill=tk.X, padx=10, pady=5)
                    else:
                        whisper_frame.pack_forget()
                
                service_combo.bind("<<ComboboxSelected>>", on_service_changed)
                
                # Status/progress
                status_var = tk.StringVar(value="")
                status_label = ttk.Label(service_dialog, textvariable=status_var)
                status_label.pack(pady=10, fill=tk.X, padx=10)
                
                progress_var = tk.DoubleVar(value=0)
                progress_bar = ttk.Progressbar(
                    service_dialog,
                    variable=progress_var,
                    maximum=100,
                    mode='determinate'
                )
                progress_bar.pack(fill=tk.X, padx=10, pady=5)
                progress_bar.pack_forget()  # Initially hidden
                
                # Buttons
                button_frame = ttk.Frame(service_dialog, padding=10)
                button_frame.pack(fill=tk.X, expand=False, pady=10)
                
                cancel_button = ttk.Button(
                    button_frame,
                    text="Cancel",
                    command=service_dialog.destroy
                )
                cancel_button.pack(side=tk.RIGHT, padx=5)
                
                def on_transcribe():
                    # Get selected service
                    service_name = service_var.get()
                    service_type = self.available_services.get(service_name)
                    
                    if not service_type:
                        messagebox.showerror("Error", "No service selected")
                        return
                    
                    # Additional options for Whisper
                    kwargs = {}
                    if service_type == "whisper":
                        kwargs['model_size'] = whisper_size_var.get()
                    
                    # Update UI
                    status_var.set("Transcribing audio...")
                    progress_bar.pack(fill=tk.X, padx=10, pady=5)
                    transcribe_button.config(state=tk.DISABLED)
                    cancel_button.config(state=tk.DISABLED)
                    service_dialog.update_idletasks()
                    
                    # Progress callback for updating the dialog
                    def update_progress(message, percentage):
                        status_var.set(message)
                        if percentage >= 0:
                            progress_var.set(percentage)
                        service_dialog.update_idletasks()
                    
                    # Execute in a separate thread to keep UI responsive
                    def transcribe_thread():
                        try:
                            # Set the transcription service first
                            self.notes_generator.set_transcription_service(service_type, **kwargs)
                            
                            # Call notes generator to process the raw recording
                            notes_content, transcript_content, notes_file_path = (
                                self.notes_generator.process_recording(
                                    file_path,
                                    callback=update_progress
                                )
                            )
                            
                            if notes_content and transcript_content:
                                # Close dialog
                                service_dialog.after(0, service_dialog.destroy)
                                
                                # Update display on main window
                                self.root.after(0, lambda: self.notes_display.display_notes(
                                    notes_content, transcript_content, notes_file_path
                                ))
                                self.root.after(0, self._refresh_meetings_list)  # Refresh just the meetings list
                            else:
                                service_dialog.after(0, lambda: messagebox.showerror(
                                    "Error", "Failed to process recording."
                                ))
                                service_dialog.after(0, lambda: service_dialog.destroy())
                        except Exception as e:
                            service_dialog.after(0, lambda: messagebox.showerror(
                                "Error", f"Error processing recording: {e}"
                            ))
                            service_dialog.after(0, lambda: service_dialog.destroy())
                    
                    # Start thread
                    threading.Thread(target=transcribe_thread, daemon=True).start()
                
                transcribe_button = ttk.Button(
                    button_frame,
                    text="Transcribe",
                    command=on_transcribe
                )
                transcribe_button.pack(side=tk.RIGHT, padx=5)
        except (IndexError, AttributeError):
            messagebox.showerror("Error", "No recording selected")
    
    def _delete_selected_raw(self):
        """Delete selected raw recording."""
        try:
            index = self.raw_list.curselection()[0]
            if 0 <= index < len(self.raw_history):
                raw_file = self.raw_history[index]
                file_path = raw_file["file_path"]
                
                # Confirm deletion
                if not messagebox.askyesno("Confirm Delete", 
                                         f"Are you sure you want to delete '{raw_file['filename']}'?\n\nThis will remove the recording file and cannot be undone."):
                    return
                
                # Delete the file
                try:
                    os.remove(file_path)
                    messagebox.showinfo("Success", f"Deleted {raw_file['filename']}")
                    self._refresh_raw_list()  # Refresh raw list
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to delete file: {e}")
        except (IndexError, AttributeError):
            messagebox.showerror("Error", "No recording selected")
    
    def _get_all_meetings(self):
        """Get all meetings from recordings and notes directories."""
        meetings = {}
        transcript_to_meeting_mapping = {}
        notes_to_meeting_mapping = {}
        original_meeting_ids = {}
        
        # First, gather all recording files to establish base meetings
        recordings_dir = os.path.join(os.path.dirname(self.notes_dir), "recordings")
        if os.path.exists(recordings_dir):
            for file in os.listdir(recordings_dir):
                if file.endswith(".wav") and file.startswith("meeting_"):
                    # Extract meeting ID (timestamp) from filename: meeting_YYYYMMDD_HHMMSS.wav
                    try:
                        timestamp = file.split('_')[1] + '_' + file.split('_')[2].split('.')[0]
                        meeting_id = timestamp
                        
                        # Get audio file info for duration
                        audio_path = os.path.join(recordings_dir, file)
                        import wave
                        with wave.open(audio_path, 'r') as wav:
                            frames = wav.getnframes()
                            rate = wav.getframerate()
                            duration = frames / rate  # Duration in seconds
                            
                        # Format duration as MM:SS
                        minutes = int(duration // 60)
                        seconds = int(duration % 60)
                        duration_str = f"{minutes:02}:{seconds:02}"
                        
                        # Format display date
                        year = timestamp[:4]
                        month = timestamp[4:6]
                        day = timestamp[6:8]
                        hour = timestamp[9:11]
                        minute = timestamp[11:13]
                        display_date = f"{year}-{month}-{day} {hour}:{minute}"
                        
                        # Add meeting to collection
                        meetings[meeting_id] = {
                            "meeting_id": meeting_id,
                            "recording_path": audio_path,
                            "display_date": display_date,
                            "duration": duration_str,
                            "has_recording": True,
                            "has_transcript": False,
                            "has_notes": False,
                            "transcripts": [],
                            "notes": []
                        }
                    except (IndexError, ValueError, wave.Error):
                        # Skip files that don't match the expected format
                        continue
        
        # Now add transcript information 
        for file in os.listdir(self.notes_dir):
            # Check for transcript files
            if file.startswith("transcript_") and file.endswith(".json"):
                try:
                    timestamp = file.replace("transcript_", "").replace(".json", "")
                    meeting_id = timestamp
                    
                    # Get related transcript text file
                    transcript_txt_path = os.path.join(self.notes_dir, f"transcript_{timestamp}.txt")
                    transcript_json_path = os.path.join(self.notes_dir, file)
                    
                    # If this is a meeting we don't have in our collection, create it
                    if meeting_id not in meetings:
                        # We don't have the original recording, but we have a transcript
                        year = timestamp[:4]
                        month = timestamp[4:6]
                        day = timestamp[6:8]
                        hour = timestamp[9:11]
                        minute = timestamp[11:13]
                        display_date = f"{year}-{month}-{day} {hour}:{minute}"
                        
                        meetings[meeting_id] = {
                            "meeting_id": meeting_id,
                            "recording_path": None,
                            "display_date": display_date,
                            "duration": "N/A",
                            "has_recording": False,
                            "has_transcript": True,
                            "has_notes": False,
                            "transcripts": [],
                            "notes": []
                        }
                    
                    # Mark as having transcript
                    meetings[meeting_id]["has_transcript"] = True
                    meetings[meeting_id]["transcripts"].append({
                        "json_path": transcript_json_path,
                        "txt_path": transcript_txt_path if os.path.exists(transcript_txt_path) else None
                    })
                    
                except (IndexError, ValueError):
                    continue
            
            # Check for notes files
            if file.startswith("meeting_notes_") and file.endswith(".md"):
                try:
                    # Handle versioned files (meeting_notes_YYYYMMDD_HHMMSS_v2.md)
                    import re
                    version_match = re.search(r'meeting_notes_(\d+_\d+)(?:_v(\d+))?\.md', file)
                    
                    if version_match:
                        timestamp = version_match.group(1)  # Get just the timestamp part
                        version = int(version_match.group(2)) if version_match.group(2) else 1
                        meeting_id = timestamp  # The meeting ID is just the timestamp, not including version
                        
                        notes_path = os.path.join(self.notes_dir, file)
                        
                        # If this is a meeting we don't have in our collection, create it
                        if meeting_id not in meetings:
                            # We don't have the original recording or transcript, but we have notes
                            year = timestamp[:4]
                            month = timestamp[4:6]
                            day = timestamp[6:8]
                            hour = timestamp[9:11]
                            minute = timestamp[11:13]
                            display_date = f"{year}-{month}-{day} {hour}:{minute}"
                            
                            meetings[meeting_id] = {
                                "meeting_id": meeting_id,
                                "recording_path": None,
                                "display_date": display_date,
                                "duration": "N/A",
                                "has_recording": False,
                                "has_transcript": False,
                                "has_notes": True,
                                "transcripts": [],
                                "notes": []
                            }
                        
                        # Mark as having notes and add this version
                        meetings[meeting_id]["has_notes"] = True
                        meetings[meeting_id]["notes"].append({
                            "path": notes_path,
                            "version": version  # Use the actual version number from the filename
                        })
                    
                except (IndexError, ValueError):
                    continue
        
        # Convert to list and sort by timestamp (newest first)
        meetings_list = list(meetings.values())
        meetings_list.sort(key=lambda x: x["meeting_id"], reverse=True)
        
        return meetings_list

    def _on_meeting_double_click(self, event):
        """Handle double-click on a meeting in the tree."""
        self._open_selected_meeting()
        
    def _open_selected_meeting(self):
        """Open the selected meeting notes."""
        selected = self.meeting_tree.selection()
        if not selected:
            messagebox.showerror("Error", "No meeting selected")
            return
            
        item_id = selected[0]
        meeting_id = None
        
        # Find the meeting ID from the tags
        tags = self.meeting_tree.item(item_id, "tags")
        if tags and tags[0]:
            meeting_id = tags[0]
        
        if not meeting_id:
            return
            
        # Find the meeting in our list
        meeting = next((m for m in self.meetings if m["meeting_id"] == meeting_id), None)
        if not meeting:
            messagebox.showerror("Error", "Meeting not found in data")
            return
            
        # If there are notes, display the latest version
        if meeting["has_notes"] and meeting["notes"]:
            # Sort notes by version (descending)
            latest_notes = sorted(meeting["notes"], key=lambda x: x["version"], reverse=True)[0]
            self._load_notes_file(latest_notes["path"])
        elif meeting["has_transcript"] and meeting["transcripts"]:
            # We have a transcript but no notes, offer to generate notes
            if messagebox.askyesno("Generate Notes", 
                                 "This meeting has a transcript but no notes. Would you like to generate notes?"):
                self._regenerate_notes()
        else:
            # We only have a recording, offer to transcribe
            if messagebox.askyesno("Transcribe Recording", 
                                 "This meeting has a recording but no transcript. Would you like to transcribe it?"):
                self._retranscribe_meeting()
                
    def _regenerate_notes(self):
        """Regenerate notes for the selected meeting using the currently selected AI model."""
        selected = self.meeting_tree.selection()
        if not selected:
            messagebox.showerror("Error", "No meeting selected")
            return
            
        item_id = selected[0]
        meeting_id = None
        
        # Find the meeting ID from the tags
        tags = self.meeting_tree.item(item_id, "tags")
        if tags and tags[0]:
            meeting_id = tags[0]
        
        if not meeting_id:
            return
            
        # Find the meeting in our list
        meeting = next((m for m in self.meetings if m["meeting_id"] == meeting_id), None)
        if not meeting:
            messagebox.showerror("Error", "Meeting not found in data")
            return
            
        # Check if we have a transcript
        if not meeting["has_transcript"] or not meeting["transcripts"]:
            messagebox.showerror("Error", "This meeting has no transcript available")
            return
            
        # Get the latest transcript
        latest_transcript = sorted(meeting["transcripts"], key=lambda x: os.path.getmtime(x["json_path"]), reverse=True)[0]
        transcript_json_path = latest_transcript["json_path"]
        
        # Use the currently selected model from the main window
        model_name = self.model_combo.get()
        model_id = self.available_models.get(model_name)
        
        if not model_id:
            messagebox.showerror("Error", "No AI model selected")
            return
            
        # Load the transcript JSON
        import json
        with open(transcript_json_path, 'r') as f:
            transcript_json = json.load(f)
        
        # Update progress frame in main window
        self.progress_frame.update_progress(f"Regenerating notes using {model_name}...", 10)
        
        # Force generation using the meeting's timestamp instead of a new timestamp
        explicit_timestamp = meeting["meeting_id"]
        
        # Progress callback for updating the main window
        def update_progress(message, percentage):
            self.root.after(0, lambda: self.progress_frame.update_progress(message, percentage))
        
        # Execute in a separate thread to keep UI responsive
        def regenerate_thread():
            try:
                # Call regeneration method with explicit timestamp
                notes_content, notes_path = self.notes_generator.retry_notes_generation(
                    transcript_json=transcript_json, 
                    model_id=model_id,
                    timestamp=explicit_timestamp,
                    callback=update_progress
                )
                
                if notes_content and notes_path:
                    # Read transcript content
                    transcript_path = transcript_json_path.replace(".json", ".txt")
                    transcript_content = None
                    if os.path.exists(transcript_path):
                        with open(transcript_path, 'r') as f:
                            transcript_content = f.read()
                    
                    # Update version metadata
                    from ui.version_updater import update_version_metadata
                    update_version_metadata(
                        self.version_manager,
                        explicit_timestamp,
                        notes_path,
                        transcript_path,
                        transcript_json_path,
                        model_id,
                        self.notes_generator.transcription_service_type,
                        is_default=True  # Make the new version the default
                    )
                    
                    # Update display
                    self.root.after(0, lambda: self.notes_display.display_notes(
                        notes_content, transcript_content, notes_path
                    ))
                    self.root.after(0, self._refresh_meetings_list)  # Refresh the list
                    self.root.after(0, lambda: self.version_history.load_meeting_versions(explicit_timestamp))  # Refresh versions panel
                    self.root.after(0, lambda: self.progress_frame.reset())  # Reset progress
                else:
                    self.root.after(0, lambda: messagebox.showerror(
                        "Error", "Failed to regenerate notes."
                    ))
                    self.root.after(0, lambda: self.progress_frame.reset())  # Reset progress
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror(
                    "Error", f"Error regenerating notes: {e}"
                ))
                self.root.after(0, lambda: self.progress_frame.reset())  # Reset progress
        
        # Start thread
        threading.Thread(target=regenerate_thread, daemon=True).start()
    
    def _retranscribe_meeting(self):
        """Retranscribe the selected meeting using the currently selected transcription service."""
        selected = self.meeting_tree.selection()
        if not selected:
            messagebox.showerror("Error", "No meeting selected")
            return
            
        item_id = selected[0]
        meeting_id = None
        
        # Find the meeting ID from the tags
        tags = self.meeting_tree.item(item_id, "tags")
        if tags and tags[0]:
            meeting_id = tags[0]
        
        if not meeting_id:
            return
            
        # Find the meeting in our list
        meeting = next((m for m in self.meetings if m["meeting_id"] == meeting_id), None)
        if not meeting:
            messagebox.showerror("Error", "Meeting not found in data")
            return
            
        # Check if we have a recording
        if not meeting["has_recording"] or not meeting["recording_path"]:
            messagebox.showerror("Error", "This meeting has no recording available")
            return
        
        # Get the current transcription service from the main window
        service_name = self.transcription_combo.get()
        service_type = self.available_services.get(service_name)
        
        if not service_type:
            messagebox.showerror("Error", "No transcription service selected")
            return
        
        # Additional options for Whisper
        kwargs = {}
        if service_type == "whisper":
            kwargs['model_size'] = self.whisper_size_var.get()
        
        # Update the progress frame
        service_display_name = self.transcription_combo.get()
        self.progress_frame.update_progress(f"Transcribing with {service_display_name}...", 10)
        
        # Progress callback for updating the main window
        def update_progress(message, percentage):
            self.root.after(0, lambda: self.progress_frame.update_progress(message, percentage))
        
        # Execute in a separate thread to keep UI responsive
        def transcribe_thread():
            try:
                # Import json here to avoid the 'json is not defined' error
                import json
                
                # Set the transcription service first
                self.notes_generator.set_transcription_service(service_type, **kwargs)
                
                # Process the recording - but preserve the original timestamp instead of making a new one
                timestamp = meeting["meeting_id"]
                
                # Get transcript json and txt paths
                transcript_json_path = os.path.join(self.notes_dir, f"transcript_{timestamp}.json")
                transcript_txt_path = os.path.join(self.notes_dir, f"transcript_{timestamp}.txt")
                
                # Find any existing transcript versions
                version_files = []
                for filename in os.listdir(self.notes_dir):
                    if filename.startswith(f"transcript_{timestamp}") and filename.endswith(".json"):
                        version_files.append(filename)
                        
                # Create version number
                version_num = len(version_files) + 1
                if version_num > 1:
                    # We need versioned transcript files
                    transcript_json_path = os.path.join(self.notes_dir, f"transcript_{timestamp}_v{version_num}.json")
                    transcript_txt_path = os.path.join(self.notes_dir, f"transcript_{timestamp}_v{version_num}.txt")
                
                # Transcribe and save directly to versioned files
                transcript_json = None
                transcript_text = None
                
                # For AWS we need S3
                s3_uri = None
                if service_type == "aws":
                    s3_uri = self.notes_generator.aws_handler.upload_audio_to_s3(meeting["recording_path"])
                    update_progress("Uploaded to S3, transcribing...", 30)
                
                # Transcribe the audio
                if service_type == "aws":
                    transcript_json = self.notes_generator.aws_handler.transcribe_audio(s3_uri)
                else:
                    transcript_json = self.notes_generator._get_transcription_service().transcribe(meeting["recording_path"], update_progress)
                
                if transcript_json and 'results' in transcript_json:
                    # Save JSON transcript
                    with open(transcript_json_path, 'w') as f:
                        json.dump(transcript_json, f, indent=2)
                    
                    # Extract and save plain text
                    transcript_text = transcript_json['results']['transcripts'][0]['transcript']
                    with open(transcript_txt_path, 'w') as f:
                        f.write(transcript_text)
                    
                    update_progress("Generating notes from transcript...", 70)
                    
                    # Generate notes with the same timestamp but versioned
                    notes_content = self.notes_generator.generate_notes_from_transcript(
                        transcript_json, 
                        self.notes_generator.model_id,
                        update_progress
                    )
                    
                    # Save notes to versioned file
                    notes_file_path = os.path.join(self.notes_dir, f"meeting_notes_{timestamp}")
                    if version_num > 1:
                        notes_file_path += f"_v{version_num}"
                    notes_file_path += ".md"
                    
                    with open(notes_file_path, 'w') as f:
                        f.write(notes_content)
                    
                    # Update version metadata
                    from ui.version_updater import update_version_metadata
                    update_version_metadata(
                        self.version_manager,
                        timestamp,
                        notes_file_path,
                        transcript_txt_path,
                        transcript_json_path,
                        self.notes_generator.model_id,
                        service_type,
                        is_default=True  # Make the new version the default
                    )
                    
                    # Update display on main window
                    self.root.after(0, lambda: self.notes_display.display_notes(
                        notes_content, transcript_text, notes_file_path
                    ))
                    self.root.after(0, self._refresh_meetings_list)  # Refresh list
                    self.root.after(0, lambda: self.version_history.load_meeting_versions(timestamp))  # Refresh versions
                    self.root.after(0, lambda: self.progress_frame.reset())  # Reset progress
                else:
                    self.root.after(0, lambda: messagebox.showerror(
                        "Error", "Failed to process recording."
                    ))
                    self.root.after(0, lambda: self.progress_frame.reset())  # Reset progress
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror(
                    "Error", f"Error processing recording: {e}"
                ))
                self.root.after(0, lambda: self.progress_frame.reset())  # Reset progress
        
        # Start thread
        threading.Thread(target=transcribe_thread, daemon=True).start()
    
    def _delete_selected_meeting(self):
        """Delete all files associated with the selected meetings."""
        selected = self.meeting_tree.selection()
        if not selected:
            messagebox.showerror("Error", "No meeting selected")
            return
        
        # Collect all meetings to delete
        meetings_to_delete = []
        for item_id in selected:
            # Find the meeting ID from the tags
            tags = self.meeting_tree.item(item_id, "tags")
            if tags and tags[0]:
                meeting_id = tags[0]
                # Find the meeting in our list
                meeting = next((m for m in self.meetings if m["meeting_id"] == meeting_id), None)
                if meeting:
                    meetings_to_delete.append(meeting)
        
        if not meetings_to_delete:
            messagebox.showerror("Error", "No valid meetings found to delete")
            return
            
        # Confirm deletion
        meeting_count = len(meetings_to_delete)
        if meeting_count == 1:
            meeting = meetings_to_delete[0]
            confirm_message = f"Are you sure you want to delete this meeting?\n\nDate: {meeting['display_date']}\n\nThis will remove all associated files and cannot be undone."
        else:
            confirm_message = f"Are you sure you want to delete these {meeting_count} meetings?\n\nThis will remove all associated files and cannot be undone."
            
        if not messagebox.askyesno("Confirm Delete", confirm_message):
            return
        
        # Collect all files to delete across all meetings
        all_deleted_files = []
        current_displayed_notes = None
        if hasattr(self.notes_display, 'current_notes_path'):
            current_displayed_notes = self.notes_display.current_notes_path
            
        # Track if any deleted meeting is currently being viewed
        should_clear_display = False
            
        # Process each meeting
        for meeting in meetings_to_delete:
            meeting_id = meeting["meeting_id"]
            files_to_delete = []
            
            # Recording file
            if meeting["has_recording"] and meeting["recording_path"]:
                files_to_delete.append(meeting["recording_path"])
                
            # Transcript files
            for transcript in meeting["transcripts"]:
                if transcript["json_path"]:
                    files_to_delete.append(transcript["json_path"])
                if transcript["txt_path"]:
                    files_to_delete.append(transcript["txt_path"])
                    
            # Notes files
            for note in meeting["notes"]:
                files_to_delete.append(note["path"])
                
                # Check if this file is currently being displayed
                if note["path"] == current_displayed_notes:
                    should_clear_display = True
                
            # Local copy in notes dir
            local_recording = os.path.join(self.notes_dir, f"local_recording_{meeting_id}.wav")
            if os.path.exists(local_recording):
                files_to_delete.append(local_recording)
                
            # Delete the files
            for file in files_to_delete:
                try:
                    os.remove(file)
                    all_deleted_files.append(os.path.basename(file))
                except Exception as e:
                    messagebox.showerror("Error", f"Failed to delete {os.path.basename(file)}: {e}")
        
        # Refresh the list
        self._refresh_meetings_list()
        
        # Clear display if any deleted meeting was being viewed
        if should_clear_display and hasattr(self, 'notes_display'):
            self.notes_display.clear()
                
        # Show success message
        messagebox.showinfo("Files Deleted", 
                          f"Successfully deleted {len(all_deleted_files)} files:\n" + 
                          "\n".join(f"- {f}" for f in all_deleted_files[:10]) +
                          (f"\n- and {len(all_deleted_files) - 10} more..." if len(all_deleted_files) > 10 else ""))
    
    def _import_audio_file(self):
        """Import an external audio file as a meeting recording."""
        from tkinter import filedialog
        import shutil
        import datetime
        
        # Ask for audio file
        file_path = filedialog.askopenfilename(
            title="Select Audio File",
            filetypes=[("WAV files", "*.wav"), ("All files", "*.*")]
        )
        
        if not file_path:
            return
            
        # Generate a timestamp for the new meeting
        now = datetime.datetime.now()
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        
        # Create destination path
        recordings_dir = os.path.join(os.path.dirname(self.notes_dir), "recordings")
        os.makedirs(recordings_dir, exist_ok=True)
        dest_path = os.path.join(recordings_dir, f"meeting_{timestamp}.wav")
        
        try:
            # Copy the file
            shutil.copy2(file_path, dest_path)
            
            # Ask if user wants to process it now
            if messagebox.askyesno("Process Recording", 
                                "Would you like to process this recording now?"):
                # Process the recording
                self.progress_frame.update_progress("Processing imported recording...", 10)
                
                def process_thread():
                    try:
                        notes_content, transcript_content, notes_file_path = (
                            self.notes_generator.process_recording(
                                dest_path,
                                callback=self._update_progress
                            )
                        )
                        
                        # Update UI
                        if notes_content and transcript_content:
                            # Use after() to update UI from main thread
                            self.root.after(0, lambda: self.notes_display.display_notes(
                                notes_content, transcript_content, notes_file_path
                            ))
                            self.root.after(0, self._refresh_meetings_list)
                        else:
                            self.root.after(0, lambda: messagebox.showerror(
                                "Error", "Failed to process imported recording."
                            ))
                            
                    except Exception as e:
                        self.root.after(0, lambda: messagebox.showerror(
                            "Error", f"Error processing imported recording: {e}"
                        ))
                        
                    finally:
                        # Reset progress
                        self.root.after(0, lambda: self.progress_frame.reset())
                
                # Start processing thread
                threading.Thread(target=process_thread, daemon=True).start()
            else:
                # Just refresh the list
                self._refresh_meetings_list()
                
            messagebox.showinfo("Import Successful", f"Audio file imported as meeting_{timestamp}.wav")
            
        except Exception as e:
            messagebox.showerror("Import Error", f"Failed to import audio file: {e}")
    
    def _on_history_item_selected(self, event):
        """Handle selection of a history item."""
        try:
            index = self.history_list.curselection()[0]
            if 0 <= index < len(self.notes_history):
                note = self.notes_history[index]
                self._load_notes_file(note["file_path"])
        except (IndexError, AttributeError):
            pass  # No valid selection
    
    def _load_notes_file(self, file_path):
        """Load and display notes from a file."""
        try:
            with open(file_path, 'r') as f:
                notes_content = f.read()
            
            # Try to find associated transcript
            transcript_content = None
            transcript_path = file_path.replace("meeting_notes_", "transcript_").replace(".md", ".txt")
            
            if os.path.exists(transcript_path):
                with open(transcript_path, 'r') as f:
                    transcript_content = f.read()
            
            # Display notes
            self.notes_display.display_notes(notes_content, transcript_content, file_path)
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load notes: {e}")
    
    def _create_right_frame(self):
        """Create right frame with notes display and version management."""
        # Create a notebook for multiple tabs
        self.right_notebook = ttk.Notebook(self.right_frame)
        self.right_notebook.pack(fill=tk.BOTH, expand=True)
        
        # Notes tab
        notes_tab = ttk.Frame(self.right_notebook)
        self.right_notebook.add(notes_tab, text="Notes")
        
        # Create version manager
        self.version_manager = VersionManager(self.notes_dir)
        
        # Version history tab
        version_tab = ttk.Frame(self.right_notebook)
        self.right_notebook.add(version_tab, text="Versions")
        
        # Notes display - pass notes_generator reference
        self.notes_display = NotesDisplay(notes_tab)
        self.notes_display.pack(fill=tk.BOTH, expand=True)
        
        # Give the display direct access to the notes generator
        self.notes_display.notes_generator = self.notes_generator
        
        # Create version history panel
        self.version_history = VersionHistoryPanel(version_tab, self.version_manager)
        self.version_history.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Bind selection event to update version panel when a meeting is selected
        self.meeting_tree.bind("<<TreeviewSelect>>", self._on_meeting_select)
    
    def _on_meeting_select(self, event):
        """Handle selection of a meeting in the tree."""
        selected = self.meeting_tree.selection()
        if not selected:
            return
            
        item_id = selected[0]
        meeting_id = None
        
        # Find the meeting ID from the tags
        tags = self.meeting_tree.item(item_id, "tags")
        if tags and tags[0]:
            meeting_id = tags[0]
        
        if meeting_id:
            # Update version history panel with selected meeting
            self.version_history.load_meeting_versions(meeting_id)
    
    def _start_recording(self):
        """Start or resume recording."""
        if self.recorder.start_recording():
            self.progress_frame.update_progress("Recording in progress...", 0)
    
    def _pause_recording(self):
        """Pause recording."""
        if self.recorder.pause_recording():
            self.progress_frame.update_progress("Recording paused", 0)
    
    def _stop_recording(self):
        """Stop recording and process the audio."""
        self.current_recording = self.recorder.stop_recording()
        
        if not self.current_recording:
            self.recording_controls.reset()
            self.progress_frame.reset()
            messagebox.showerror("Error", "No recording to process.")
            return
        
        # Process the recording in a separate thread
        self.progress_frame.update_progress("Processing recording...", 10)
        self.processing_thread = threading.Thread(target=self._process_recording)
        self.processing_thread.daemon = True
        self.processing_thread.start()
    
    def _process_recording(self):
        """Process the recording and generate notes."""
        try:
            # Process the recording
            notes_content, transcript_content, notes_file_path = (
                self.notes_generator.process_recording(
                    self.current_recording,
                    callback=self._update_progress
                )
            )
            
            # Update UI
            if notes_content and transcript_content:
                # Get meeting ID (timestamp) from notes file path
                import os
                import re
                filename = os.path.basename(notes_file_path)
                match = re.search(r'meeting_notes_(\d+_\d+)\.md', filename)
                if match:
                    meeting_id = match.group(1)
                    
                    # Get transcript paths
                    transcript_txt_path = os.path.join(self.notes_dir, f"transcript_{meeting_id}.txt")
                    transcript_json_path = os.path.join(self.notes_dir, f"transcript_{meeting_id}.json")
                    
                    # Update version metadata
                    from ui.version_updater import update_version_metadata
                    update_version_metadata(
                        self.version_manager,
                        meeting_id,
                        notes_file_path,
                        transcript_txt_path,
                        transcript_json_path,
                        self.notes_generator.model_id,
                        self.notes_generator.transcription_service_type,
                        is_default=True  # First version is default
                    )
                    
                    # Select this meeting in the versions panel
                    self.root.after(0, lambda mid=meeting_id: self.version_history.load_meeting_versions(mid))
                
                # Use after() to update UI from main thread
                self.root.after(0, lambda: self.notes_display.display_notes(
                    notes_content, transcript_content, notes_file_path
                ))
                self.root.after(0, self._refresh_meetings_list)
                self.root.after(0, lambda: self.recording_controls.reset())
            else:
                self.root.after(0, lambda: messagebox.showerror(
                    "Error", "Failed to generate notes from recording."
                ))
                self.root.after(0, lambda: self.recording_controls.reset())
                self.root.after(0, lambda: self.progress_frame.reset())
                
        except Exception as e:
            self.root.after(0, lambda: messagebox.showerror("Error", f"Error processing recording: {e}"))
            self.root.after(0, lambda: self.recording_controls.reset())
            self.root.after(0, lambda: self.progress_frame.reset())
    
    def _update_progress(self, message, percentage):
        """Update progress display from processing thread."""
        self.root.after(0, lambda: self.progress_frame.update_progress(message, percentage))
    
    def _on_close(self):
        """Handle window close event."""
        # Stop recording if in progress
        if self.recorder.recording:
            self.recorder.stop_recording()
        
        # Save user settings
        self._save_settings()
        
        # Clean up resources
        self.recorder.cleanup()
        
        # Close window
        self.root.destroy()


def run_app():
    """Run the application."""
    root = tk.Tk()
    app = MainWindow(root)
    root.mainloop()


if __name__ == "__main__":
    run_app()
