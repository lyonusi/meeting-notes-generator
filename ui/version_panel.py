"""
Version management UI components for Meeting Notes Generator.
Contains UI components for version management panel.
"""

import os
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import difflib

class VersionHistoryPanel(ttk.Frame):
    """Version history panel UI component."""
    
    def __init__(self, parent, version_manager):
        """Initialize version history panel.
        
        Args:
            parent: Parent widget.
            version_manager: Instance of VersionManager class.
        """
        super().__init__(parent)
        self.parent = parent
        self.version_manager = version_manager
        
        self.current_meeting_id = None
        self.comparison_window = None
        
        self._create_widgets()
    
    def _create_widgets(self):
        """Create the UI widgets."""
        # Title label
        self.title_label = ttk.Label(self, text="Version History", font=("", 14, "bold"))
        self.title_label.pack(pady=(5, 10), anchor=tk.W)
        
        # Version list frame with scrollbar
        self.versions_frame = ttk.Frame(self)
        self.versions_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Create a treeview with columns
        self.version_tree = ttk.Treeview(
            self.versions_frame, 
            columns=("Name", "Model", "Transcription", "Date"),
            selectmode="extended",
            height=8
        )
        
        # Configure columns
        self.version_tree.column("#0", width=30, stretch=tk.NO)  # Icon column
        self.version_tree.column("Name", width=150, anchor=tk.W)
        self.version_tree.column("Model", width=120, anchor=tk.W)
        self.version_tree.column("Transcription", width=120, anchor=tk.W)
        self.version_tree.column("Date", width=150, anchor=tk.W)
        
        # Configure headings
        self.version_tree.heading("#0", text="")
        self.version_tree.heading("Name", text="Version Name")
        self.version_tree.heading("Model", text="AI Model")
        self.version_tree.heading("Transcription", text="Transcription")
        self.version_tree.heading("Date", text="Date & Time")
        
        # Add scrollbar
        self.version_scrollbar = ttk.Scrollbar(self.versions_frame, orient="vertical", command=self.version_tree.yview)
        self.version_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.version_tree.configure(yscrollcommand=self.version_scrollbar.set)
        
        # Pack the tree
        self.version_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Bind events
        self.version_tree.bind("<Double-1>", self._on_version_double_click)
        self.version_tree.bind("<Button-3>", self._show_version_context_menu)  # Right-click
        
        # Create context menu
        self.version_context_menu = tk.Menu(self.version_tree, tearoff=0)
        self.version_context_menu.add_command(label="Open Version", command=self._open_selected_version)
        self.version_context_menu.add_command(label="Set as Default", command=self._set_selected_as_default)
        self.version_context_menu.add_command(label="Rename Version", command=self._rename_selected_version)
        self.version_context_menu.add_command(label="Add Comments", command=self._add_comments_to_version)
        self.version_context_menu.add_command(label="Compare with Default", command=self._compare_with_default)
        self.version_context_menu.add_separator()
        self.version_context_menu.add_command(label="Delete Version", command=self._delete_selected_version)
        
        # Action buttons frame
        self.action_frame = ttk.Frame(self)
        self.action_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Set as Default button
        self.set_default_button = ttk.Button(
            self.action_frame,
            text="Set as Default",
            command=self._set_selected_as_default
        )
        self.set_default_button.pack(side=tk.LEFT, padx=5)
        
        # Compare button
        self.compare_button = ttk.Button(
            self.action_frame,
            text="Compare Selected",
            command=self._compare_selected_versions
        )
        self.compare_button.pack(side=tk.LEFT, padx=5)
        
        # Timeline button
        self.timeline_button = ttk.Button(
            self.action_frame,
            text="View Timeline",
            command=self._show_timeline
        )
        self.timeline_button.pack(side=tk.LEFT, padx=5)
    
    def load_meeting_versions(self, meeting_id):
        """Load versions for a specific meeting.
        
        Args:
            meeting_id: Meeting ID (timestamp).
        """
        self.current_meeting_id = meeting_id
        
        # Clear existing items
        for item in self.version_tree.get_children():
            self.version_tree.delete(item)
            
        if not meeting_id:
            self.title_label.config(text="No Meeting Selected")
            return
            
        # Get metadata for this meeting
        metadata = self.version_manager.get_metadata(meeting_id)
        if not metadata or 'versions' not in metadata:
            self.title_label.config(text=f"No Versions Found")
            return
            
        # Set title with meeting date
        meeting_date = metadata.get('display_date', 'Unknown Date')
        self.title_label.config(text=f"Versions for Meeting: {meeting_date}")
        
        # Sort versions by number
        versions = sorted([
            (int(ver_num), ver_info) 
            for ver_num, ver_info in metadata['versions'].items()
        ])
        
        # Add each version to the tree
        for ver_num, ver_info in versions:
            # Set icon if it's the default version
            icon = "★" if ver_info.get('is_default', False) else ""
            
            # Get values
            name = ver_info.get('name', f"Version {ver_num}")
            model = ver_info.get('model', {}).get('name', 'Unknown Model')
            transcription = ver_info.get('transcription_service', {}).get('name', 'Unknown Service')
            
            # Format creation date
            try:
                from datetime import datetime
                creation_time = ver_info.get('creation_time')
                if creation_time:
                    dt = datetime.fromisoformat(creation_time)
                    date_str = dt.strftime("%Y-%m-%d %H:%M")
                else:
                    date_str = "Unknown"
            except Exception:
                date_str = "Unknown"
            
            # Insert into tree
            self.version_tree.insert(
                "", "end", 
                text=icon,
                values=(name, model, transcription, date_str),
                tags=(str(ver_num),)
            )
    
    def _on_version_double_click(self, event):
        """Handle double-click on a version."""
        self._open_selected_version()
    
    def _show_version_context_menu(self, event):
        """Show context menu on right-click."""
        try:
            # Get the item under the cursor
            item_id = self.version_tree.identify("item", event.x, event.y)
            if item_id:
                # Select the item
                self.version_tree.selection_set(item_id)
                self.version_tree.focus(item_id)
                # Show the menu
                self.version_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.version_context_menu.grab_release()
    
    def _get_selected_version(self):
        """Get the selected version number.
        
        Returns:
            Tuple containing (version_num, item_id) or (None, None) if no selection.
        """
        selected = self.version_tree.selection()
        if not selected:
            messagebox.showerror("Error", "No version selected")
            return None, None
            
        item_id = selected[0]
        version_num = None
        
        # Find the version number from the tags
        tags = self.version_tree.item(item_id, "tags")
        if tags and tags[0]:
            version_num = tags[0]
        
        if not version_num:
            messagebox.showerror("Error", "Could not determine version number")
            return None, None
            
        return version_num, item_id
    
    def _open_selected_version(self):
        """Open the selected version."""
        if not self.current_meeting_id:
            return
            
        version_num, _ = self._get_selected_version()
        if not version_num:
            return
            
        # Get metadata for this meeting
        metadata = self.version_manager.get_metadata(self.current_meeting_id)
        if not metadata or 'versions' not in metadata:
            messagebox.showerror("Error", "No version metadata found")
            return
            
        # Get version info
        version_info = metadata['versions'].get(version_num)
        if not version_info:
            messagebox.showerror("Error", f"Version {version_num} not found in metadata")
            return
            
        # Get notes path and transcript path
        notes_path = version_info.get('notes_path')
        transcript_path = version_info.get('transcript_path')
        
        if not notes_path:
            messagebox.showerror("Error", "No notes file found for this version")
            return
            
        # Load and display notes - this requires accessing the notes display component
        main_window = self.winfo_toplevel()
        if hasattr(main_window, 'notes_display'):
            try:
                # Read notes content
                with open(notes_path, 'r') as f:
                    notes_content = f.read()
                
                # Read transcript if available
                transcript_content = None
                if transcript_path and os.path.exists(transcript_path):
                    with open(transcript_path, 'r') as f:
                        transcript_content = f.read()
                
                # Display in notes display
                main_window.notes_display.display_notes(notes_content, transcript_content, notes_path)
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load version: {e}")
        else:
            messagebox.showerror("Error", "Notes display component not available")
    
    def _set_selected_as_default(self):
        """Set the selected version as the default."""
        if not self.current_meeting_id:
            return
            
        version_num, _ = self._get_selected_version()
        if not version_num:
            return
            
        # Update the default version
        updated_metadata = self.version_manager.set_default_version(
            self.current_meeting_id, 
            version_num
        )
        
        if updated_metadata:
            # Reload the versions list
            self.load_meeting_versions(self.current_meeting_id)
            messagebox.showinfo("Success", f"Version {version_num} is now the default")
        else:
            messagebox.showerror("Error", "Failed to set default version")
    
    def _rename_selected_version(self):
        """Rename the selected version."""
        if not self.current_meeting_id:
            return
            
        version_num, _ = self._get_selected_version()
        if not version_num:
            return
            
        # Get current name
        metadata = self.version_manager.get_metadata(self.current_meeting_id)
        if not metadata or 'versions' not in metadata:
            return
            
        current_name = metadata['versions'].get(version_num, {}).get('name', f"Version {version_num}")
        
        # Create rename dialog
        rename_dialog = tk.Toplevel(self)
        rename_dialog.title("Rename Version")
        rename_dialog.geometry("400x150")
        rename_dialog.transient(self.winfo_toplevel())  # Make dialog a child of parent window
        rename_dialog.grab_set()  # Make dialog modal
        
        # Form
        ttk.Label(rename_dialog, text="Enter new name:").pack(pady=(20, 5))
        
        name_var = tk.StringVar(value=current_name)
        name_entry = ttk.Entry(rename_dialog, textvariable=name_var, width=40)
        name_entry.pack(pady=5, padx=20, fill=tk.X)
        name_entry.select_range(0, tk.END)  # Select all text
        name_entry.focus_set()  # Focus the entry
        
        # Buttons
        button_frame = ttk.Frame(rename_dialog)
        button_frame.pack(fill=tk.X, pady=(15, 10), padx=10)
        
        # Cancel button
        ttk.Button(
            button_frame,
            text="Cancel",
            command=rename_dialog.destroy
        ).pack(side=tk.RIGHT, padx=5)
        
        # Save button
        def on_save():
            new_name = name_var.get().strip()
            if not new_name:
                messagebox.showerror("Error", "Name cannot be empty")
                return
                
            # Update name
            updated_metadata = self.version_manager.rename_version(
                self.current_meeting_id, 
                version_num,
                new_name
            )
            
            if updated_metadata:
                # Reload the versions list
                self.load_meeting_versions(self.current_meeting_id)
                rename_dialog.destroy()
            else:
                messagebox.showerror("Error", "Failed to rename version")
                
        ttk.Button(
            button_frame,
            text="Save",
            command=on_save
        ).pack(side=tk.RIGHT, padx=5)
    
    def _add_comments_to_version(self):
        """Add comments to the selected version."""
        if not self.current_meeting_id:
            return
            
        version_num, _ = self._get_selected_version()
        if not version_num:
            return
            
        # Get current comments
        metadata = self.version_manager.get_metadata(self.current_meeting_id)
        if not metadata or 'versions' not in metadata:
            return
            
        current_comments = metadata['versions'].get(version_num, {}).get('comments', "")
        
        # Create comments dialog
        comments_dialog = tk.Toplevel(self)
        comments_dialog.title("Version Comments")
        comments_dialog.geometry("500x300")
        comments_dialog.transient(self.winfo_toplevel())  # Make dialog a child of parent window
        comments_dialog.grab_set()  # Make dialog modal
        
        # Form
        ttk.Label(comments_dialog, text="Enter comments:").pack(pady=(20, 5), padx=20, anchor=tk.W)
        
        # Comments text field
        comments_text = tk.Text(comments_dialog, height=10, width=50, wrap=tk.WORD)
        comments_text.pack(pady=5, padx=20, fill=tk.BOTH, expand=True)
        comments_text.insert(tk.END, current_comments)
        comments_text.focus_set()  # Focus the text field
        
        # Buttons
        button_frame = ttk.Frame(comments_dialog)
        button_frame.pack(fill=tk.X, pady=(15, 10), padx=10)
        
        # Cancel button
        ttk.Button(
            button_frame,
            text="Cancel",
            command=comments_dialog.destroy
        ).pack(side=tk.RIGHT, padx=5)
        
        # Save button
        def on_save():
            comments = comments_text.get(1.0, tk.END).strip()
                
            # Update comments
            updated_metadata = self.version_manager.add_comments(
                self.current_meeting_id, 
                version_num,
                comments
            )
            
            if updated_metadata:
                comments_dialog.destroy()
                messagebox.showinfo("Success", "Comments saved successfully")
            else:
                messagebox.showerror("Error", "Failed to save comments")
                
        ttk.Button(
            button_frame,
            text="Save",
            command=on_save
        ).pack(side=tk.RIGHT, padx=5)
    
    def _compare_selected_versions(self):
        """Compare two selected versions."""
        if not self.current_meeting_id:
            return
            
        # Get selected versions
        selected = self.version_tree.selection()
        if len(selected) != 2:
            messagebox.showerror("Error", "Please select exactly two versions to compare")
            return
            
        version1 = None
        version2 = None
        
        # Get version numbers from tags
        for item_id in selected:
            tags = self.version_tree.item(item_id, "tags")
            if tags and tags[0]:
                if version1 is None:
                    version1 = tags[0]
                else:
                    version2 = tags[0]
        
        if version1 is None or version2 is None:
            messagebox.showerror("Error", "Could not determine version numbers")
            return
            
        self._show_comparison(version1, version2)
    
    def _compare_with_default(self):
        """Compare the selected version with the default version."""
        if not self.current_meeting_id:
            return
            
        version_num, _ = self._get_selected_version()
        if not version_num:
            return
            
        # Get the default version
        default_version = self.version_manager.get_default_version(self.current_meeting_id)
        if not default_version:
            messagebox.showerror("Error", "No default version found")
            return
            
        # Don't compare a version with itself
        if version_num == default_version:
            messagebox.showinfo("Information", "Selected version is already the default version")
            return
            
        self._show_comparison(version_num, default_version)
    
    def _show_comparison(self, version1, version2):
        """Show comparison between two versions.
        
        Args:
            version1: First version number.
            version2: Second version number.
        """
        # Get comparison data
        comparison = self.version_manager.compare_versions(self.current_meeting_id, version1, version2)
        if not comparison:
            messagebox.showerror("Error", "Failed to compare versions")
            return
        
        # If there's already a comparison window open, close it
        if self.comparison_window and self.comparison_window.winfo_exists():
            self.comparison_window.destroy()
        
        # Create comparison window
        self.comparison_window = tk.Toplevel(self)
        self.comparison_window.title("Version Comparison")
        self.comparison_window.geometry("1000x600")
        
        # Get version names
        version1_name = comparison['version1']['name']
        version2_name = comparison['version2']['name']
        
        # Create notebook for different views
        notebook = ttk.Notebook(self.comparison_window)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Side-by-side view
        side_frame = ttk.Frame(notebook)
        notebook.add(side_frame, text="Side by Side")
        
        # Split into two panes
        side_paned = ttk.PanedWindow(side_frame, orient=tk.HORIZONTAL)
        side_paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Left side (Version 1)
        left_frame = ttk.Frame(side_paned, relief="solid", borderwidth=1)
        side_paned.add(left_frame, weight=1)
        
        ttk.Label(left_frame, text=f"Version {version1}: {version1_name}", font=("", 11, "bold")).pack(pady=(5, 0))
        
        left_text = tk.Text(left_frame, wrap=tk.WORD, width=40, height=25)
        left_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        left_text.insert(tk.END, comparison['version1']['content'])
        left_text.config(state=tk.DISABLED)  # Make read-only
        
        # Left scrollbar
        left_scrollbar = ttk.Scrollbar(left_frame, orient="vertical", command=left_text.yview)
        left_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        left_text.config(yscrollcommand=left_scrollbar.set)
        
        # Right side (Version 2)
        right_frame = ttk.Frame(side_paned, relief="solid", borderwidth=1)
        side_paned.add(right_frame, weight=1)
        
        ttk.Label(right_frame, text=f"Version {version2}: {version2_name}", font=("", 11, "bold")).pack(pady=(5, 0))
        
        right_text = tk.Text(right_frame, wrap=tk.WORD, width=40, height=25)
        right_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        right_text.insert(tk.END, comparison['version2']['content'])
        right_text.config(state=tk.DISABLED)  # Make read-only
        
        # Right scrollbar
        right_scrollbar = ttk.Scrollbar(right_frame, orient="vertical", command=right_text.yview)
        right_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        right_text.config(yscrollcommand=right_scrollbar.set)
        
        # Diff view
        diff_frame = ttk.Frame(notebook)
        notebook.add(diff_frame, text="Differences")
        
        # Diff text widget
        diff_text = tk.Text(diff_frame, wrap=tk.NONE, width=80, height=30)
        diff_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Diff horizontal scrollbar
        diff_hscrollbar = ttk.Scrollbar(diff_frame, orient="horizontal", command=diff_text.xview)
        diff_hscrollbar.pack(side=tk.BOTTOM, fill=tk.X)
        
        # Diff vertical scrollbar
        diff_vscrollbar = ttk.Scrollbar(diff_frame, orient="vertical", command=diff_text.yview)
        diff_vscrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        diff_text.config(xscrollcommand=diff_hscrollbar.set, yscrollcommand=diff_vscrollbar.set)
        
        # Configure tags for diff highlighting
        diff_text.tag_configure("removed", foreground="red", background="#ffdddd")
        diff_text.tag_configure("added", foreground="green", background="#ddffdd")
        diff_text.tag_configure("header", foreground="blue", background="#eeeeff")
        diff_text.tag_configure("section", foreground="purple", background="#f8f8f8")
        
        # Insert diff content with syntax highlighting
        for line in comparison['diff']:
            if line.startswith('---') or line.startswith('+++'):
                diff_text.insert(tk.END, line + "\n", "header")
            elif line.startswith('-'):
                diff_text.insert(tk.END, line + "\n", "removed")
            elif line.startswith('+'):
                diff_text.insert(tk.END, line + "\n", "added")
            elif line.startswith('@@'):
                diff_text.insert(tk.END, line + "\n", "section")
            else:
                diff_text.insert(tk.END, line + "\n")
        
        diff_text.config(state=tk.DISABLED)  # Make read-only
    
    def _delete_selected_version(self):
        """Delete the selected version."""
        if not self.current_meeting_id:
            return
            
        version_num, _ = self._get_selected_version()
        if not version_num:
            return
            
        # Get metadata
        metadata = self.version_manager.get_metadata(self.current_meeting_id)
        if not metadata or 'versions' not in metadata:
            return
            
        # Check if this is the only version
        if len(metadata['versions']) <= 1:
            messagebox.showerror("Error", "Cannot delete the only version of this meeting")
            return
            
        # Confirm deletion
        if not messagebox.askyesno("Confirm Delete", 
                                 f"Are you sure you want to delete version {version_num}?\n\nThis will remove this version from the history but keep the files."):
            return
            
        # Delete the version
        updated_metadata = self.version_manager.delete_version(self.current_meeting_id, version_num)
        
        # Reload the versions list
        self.load_meeting_versions(self.current_meeting_id)
        
        messagebox.showinfo("Success", f"Version {version_num} has been removed from history")
    
    def _show_timeline(self):
        """Show the version timeline for this meeting."""
        if not self.current_meeting_id:
            return
            
        # Get metadata
        metadata = self.version_manager.get_metadata(self.current_meeting_id)
        if not metadata or 'versions' not in metadata:
            messagebox.showinfo("Timeline", "No version history found for this meeting")
            return
            
        # Create timeline window
        timeline_window = tk.Toplevel(self)
        timeline_window.title("Version Timeline")
        timeline_window.geometry("800x400")
        
        # Meeting info at the top
        meeting_date = metadata.get('display_date', 'Unknown Date')
        ttk.Label(timeline_window, text=f"Timeline for Meeting: {meeting_date}", font=("", 14, "bold")).pack(pady=(10, 5))
        
        # Canvas for drawing the timeline
        canvas = tk.Canvas(timeline_window, bg="white")
        canvas.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
        
        # Sort versions by number
        versions = sorted([
            (int(ver_num), ver_info) 
            for ver_num, ver_info in metadata['versions'].items()
        ])
        
        # Draw timeline
        timeline_y = 100
        node_radius = 15
        horizontal_spacing = 150
        
        # Calculate total width needed
        total_width = len(versions) * horizontal_spacing
        
        # Configure canvas scrolling if needed
        if total_width > 760:  # Adjust based on window width
            hscrollbar = ttk.Scrollbar(timeline_window, orient="horizontal", command=canvas.xview)
            hscrollbar.pack(side=tk.BOTTOM, fill=tk.X)
            canvas.configure(xscrollcommand=hscrollbar.set)
            canvas.configure(scrollregion=(0, 0, total_width, 300))
            
        # Draw horizontal timeline line
        canvas.create_line(
            50, timeline_y, 
            50 + (len(versions) - 1) * horizontal_spacing, timeline_y,
            width=2, fill="gray"
        )
        
        # Draw nodes and labels
        for i, (ver_num, ver_info) in enumerate(versions):
            x_pos = 50 + i * horizontal_spacing
            
            # Draw node
            fill_color = "gold" if ver_info.get('is_default', False) else "lightblue"
            canvas.create_oval(
                x_pos - node_radius, timeline_y - node_radius,
                x_pos + node_radius, timeline_y + node_radius,
                fill=fill_color, outline="black", width=2
            )
            
            # Version number in node
            canvas.create_text(
                x_pos, timeline_y,
                text=str(ver_num),
                font=("", 10, "bold")
            )
            
            # Version name above
            canvas.create_text(
                x_pos, timeline_y - 40,
                text=ver_info.get('name', f"Version {ver_num}"),
                font=("", 9, "bold"),
                anchor=tk.CENTER
            )
            
            # Model below
            model_name = ver_info.get('model', {}).get('name', 'Unknown Model')
            canvas.create_text(
                x_pos, timeline_y + 40,
                text=model_name,
                font=("", 8),
                anchor=tk.CENTER
            )
            
            # Date below model
            try:
                from datetime import datetime
                creation_time = ver_info.get('creation_time')
                if creation_time:
                    dt = datetime.fromisoformat(creation_time)
                    date_str = dt.strftime("%Y-%m-%d %H:%M")
                else:
                    date_str = "Unknown"
            except Exception:
                date_str = "Unknown"
                
            canvas.create_text(
                x_pos, timeline_y + 60,
                text=date_str,
                font=("", 8),
                anchor=tk.CENTER
            )
            
            # Add transcription service even lower
            service_name = ver_info.get('transcription_service', {}).get('name', 'Unknown Service')
            canvas.create_text(
                x_pos, timeline_y + 80,
                text=service_name,
                font=("", 8),
                anchor=tk.CENTER,
                fill="dark gray"
            )
            
        # Close button at bottom
        ttk.Button(
            timeline_window,
            text="Close",
            command=timeline_window.destroy
        ).pack(pady=(5, 10))


class VersionComparePanel(ttk.Frame):
    """Version comparison panel for side-by-side comparison."""
    
    def __init__(self, parent, version_manager):
        """Initialize version comparison panel.
        
        Args:
            parent: Parent widget.
            version_manager: Instance of VersionManager class.
        """
        super().__init__(parent)
        self.parent = parent
        self.version_manager = version_manager
        
        self.current_meeting_id = None
        self.version1 = None
        self.version2 = None
        
        self._create_widgets()
    
    def _create_widgets(self):
        """Create the UI widgets."""
        # Title label
        self.title_label = ttk.Label(self, text="Version Comparison", font=("", 14, "bold"))
        self.title_label.pack(pady=(5, 10), anchor=tk.W)
        
        # Version selection frame
        selection_frame = ttk.Frame(self)
        selection_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Left version selection
        ttk.Label(selection_frame, text="Version 1:").grid(row=0, column=0, padx=5, pady=5, sticky=tk.W)
        self.version1_var = tk.StringVar()
        self.version1_combo = ttk.Combobox(selection_frame, textvariable=self.version1_var, state="readonly", width=30)
        self.version1_combo.grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)
        
        # Right version selection
        ttk.Label(selection_frame, text="Version 2:").grid(row=1, column=0, padx=5, pady=5, sticky=tk.W)
        self.version2_var = tk.StringVar()
        self.version2_combo = ttk.Combobox(selection_frame, textvariable=self.version2_var, state="readonly", width=30)
        self.version2_combo.grid(row=1, column=1, padx=5, pady=5, sticky=tk.W)
        
        # Compare button
        ttk.Button(selection_frame, text="Compare", command=self._compare_versions).grid(row=1, column=2, padx=5, pady=5)
        
        # Text frames for displaying comparison
        self.compare_frame = ttk.Frame(self)
        self.compare_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        
        # Split into two panes
        self.paned = ttk.PanedWindow(self.compare_frame, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True)
        
        # Left panel
        self.left_frame = ttk.Frame(self.paned)
        self.paned.add(self.left_frame, weight=1)
        
        # Right panel
        self.right_frame = ttk.Frame(self.paned)
        self.paned.add(self.right_frame, weight=1)
        
        # Left version text
        left_label_frame = ttk.LabelFrame(self.left_frame, text="Version 1")
        left_label_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.left_text = tk.Text(left_label_frame, wrap=tk.WORD, width=40, height=25)
        self.left_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.left_text.config(state=tk.DISABLED)  # Make read-only
        
        # Left scrollbar
        left_scrollbar = ttk.Scrollbar(left_label_frame, orient="vertical", command=self.left_text.yview)
        left_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.left_text.config(yscrollcommand=left_scrollbar.set)
        
        # Right version text
        right_label_frame = ttk.LabelFrame(self.right_frame, text="Version 2")
        right_label_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.right_text = tk.Text(right_label_frame, wrap=tk.WORD, width=40, height=25)
        self.right_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.right_text.config(state=tk.DISABLED)  # Make read-only
        
        # Right scrollbar
        right_scrollbar = ttk.Scrollbar(right_label_frame, orient="vertical", command=self.right_text.yview)
        right_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.right_text.config(yscrollcommand=right_scrollbar.set)
    
    def load_meeting_versions(self, meeting_id):
        """Load versions for a specific meeting.
        
        Args:
            meeting_id: Meeting ID (timestamp).
        """
        self.current_meeting_id = meeting_id
        
        # Clear existing content
        self.left_text.config(state=tk.NORMAL)
        self.left_text.delete(1.0, tk.END)
        self.left_text.config(state=tk.DISABLED)
        
        self.right_text.config(state=tk.NORMAL)
        self.right_text.delete(1.0, tk.END)
        self.right_text.config(state=tk.DISABLED)
        
        if not meeting_id:
            self.version1_combo["values"] = []
            self.version2_combo["values"] = []
            self.title_label.config(text="No Meeting Selected")
            return
            
        # Get metadata for this meeting
        metadata = self.version_manager.get_metadata(meeting_id)
        if not metadata or 'versions' not in metadata:
            self.version1_combo["values"] = []
            self.version2_combo["values"] = []
            self.title_label.config(text=f"No Versions Found")
            return
            
        # Set title with meeting date
        meeting_date = metadata.get('display_date', 'Unknown Date')
        self.title_label.config(text=f"Compare Versions for Meeting: {meeting_date}")
        
        # Get version names
        versions = []
        for ver_num, ver_info in metadata['versions'].items():
            name = ver_info.get('name', f"Version {ver_num}")
            versions.append(f"{name} (#{ver_num})")
        
        # Set dropdown values
        self.version1_combo["values"] = versions
        self.version2_combo["values"] = versions
        
        # Try to select first and last versions by default
        if len(versions) >= 2:
            self.version1_combo.current(0)
            self.version2_combo.current(len(versions) - 1)
        elif len(versions) == 1:
            self.version1_combo.current(0)
            self.version2_combo.current(0)
    
    def _compare_versions(self):
        """Compare the selected versions."""
        if not self.current_meeting_id:
            return
            
        # Get selected versions
        ver1_idx = self.version1_combo.current()
        ver2_idx = self.version2_combo.current()
        
        if ver1_idx < 0 or ver2_idx < 0:
            messagebox.showerror("Error", "Please select versions to compare")
            return
            
        # Extract version numbers from strings
        ver1_str = self.version1_combo.get()
        ver2_str = self.version2_combo.get()
        
        try:
            version1 = ver1_str.split("(#")[1].strip(")")
            version2 = ver2_str.split("(#")[1].strip(")")
        except (IndexError, ValueError):
            messagebox.showerror("Error", "Could not parse version numbers")
            return
            
        # Get comparison data
        comparison = self.version_manager.compare_versions(self.current_meeting_id, version1, version2)
        if not comparison:
            messagebox.showerror("Error", "Failed to compare versions")
            return
            
        # Update text widgets
        self.left_text.config(state=tk.NORMAL)
        self.left_text.delete(1.0, tk.END)
        self.left_text.insert(tk.END, comparison['version1']['content'])
        self.left_text.config(state=tk.DISABLED)
        
        self.right_text.config(state=tk.NORMAL)
        self.right_text.delete(1.0, tk.END)
        self.right_text.insert(tk.END, comparison['version2']['content'])
        self.right_text.config(state=tk.DISABLED)
