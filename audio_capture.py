"""
Audio capture functionality for Meeting Notes Generator.
This module handles recording from both microphone and system audio output.
"""

import os
import wave
import time
import tempfile
import threading
import numpy as np
import pyaudio
from datetime import datetime

from config import CHANNELS, RATE, CHUNK, AUDIO_FORMAT, RECORDINGS_DIR


class AudioRecorder:
    """
    Records audio from microphone and system output.
    Note: For system audio capture on macOS, a virtual audio device like BlackHole is recommended.
    """
    def __init__(self, settings=None):
        self.pyaudio = pyaudio.PyAudio()
        self.recording = False
        self.paused = False
        self.audio_frames = []
        self.start_time = None
        self.recording_thread = None
        self.recording_filename = None
        
        # Ensure recordings directory exists
        os.makedirs(RECORDINGS_DIR, exist_ok=True)
        
        # Use provided settings or load from file
        if settings is not None:
            self.settings = settings
        else:
            self.settings_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "user_settings.json")
            self.settings = self._load_settings()
        
        # Get device info
        self.device_info = self._get_device_info()
    
    def _load_settings(self):
        """Load user settings from file."""
        try:
            if os.path.exists(self.settings_file):
                import json
                with open(self.settings_file, 'r') as f:
                    return json.load(f)
            return {}
        except Exception as e:
            print(f"Error loading settings: {e}")
            return {}
    
    def _get_device_info(self):
        """Get information about available audio devices."""
        info = {"input": None, "output": None}
        
        # List all available audio devices
        device_count = self.pyaudio.get_device_count()
        devices = {
            "input": [],
            "output": []
        }
        
        # First, collect all devices
        macbook_mic_idx = None
        macbook_speakers_idx = None
        built_in_mic_idx = None
        built_in_speakers_idx = None
        
        # Keywords that might indicate built-in MacBook devices
        macbook_mic_keywords = ["macbook", "built-in", "internal", "default"]
        macbook_speaker_keywords = ["macbook", "built-in", "internal", "default"]
        
        # Previously used devices from settings
        saved_input_device = self.settings.get("input_device")
        saved_output_device = self.settings.get("output_device")
        
        for i in range(device_count):
            device = self.pyaudio.get_device_info_by_index(i)
            name = device["name"].lower()
            
            if device["maxInputChannels"] > 0:
                devices["input"].append((i, device["name"]))
                # Check for MacBook Pro Microphone with different possible names
                if "macbook" in name and "micro" in name:
                    macbook_mic_idx = i
                elif any(keyword in name for keyword in macbook_mic_keywords) and "micro" in name:
                    built_in_mic_idx = i
            
            if device["maxOutputChannels"] > 0:
                devices["output"].append((i, device["name"]))
                # Check for MacBook Pro Speakers with different possible names
                if "macbook" in name and ("speak" in name or "output" in name):
                    macbook_speakers_idx = i
                elif any(keyword in name for keyword in macbook_speaker_keywords) and ("speak" in name or "output" in name):
                    built_in_speakers_idx = i
        
        # First prioritize MacBook devices, then built-in, then system default, then first available
        
        # Input device selection priority
        # First, try to use previously saved device from settings
        if saved_input_device is not None:
            # Make sure the device still exists
            if any(idx == saved_input_device for idx, _ in devices["input"]):
                info["input"] = saved_input_device
                print(f"Using previously selected input device: {self.pyaudio.get_device_info_by_index(saved_input_device)['name']}")
            else:
                print("Previously saved input device not found, selecting best available")
                
        # If no saved device or it's not available, use fallback logic
        if info["input"] is None:
            if macbook_mic_idx is not None:
                info["input"] = macbook_mic_idx
                print(f"Using MacBook Pro microphone as input device")
            elif built_in_mic_idx is not None:
                info["input"] = built_in_mic_idx
                print(f"Using built-in microphone as input device")
            else:
                # Try system default as fallback
                try:
                    info["input"] = self.pyaudio.get_default_input_device_info()["index"]
                    print(f"Using system default input device: {self.pyaudio.get_device_info_by_index(info['input'])['name']}")
                except IOError:
                    # Last resort: first available device
                    if devices["input"]:
                        info["input"] = devices["input"][0][0]
                        print(f"Using first available input device: {devices['input'][0][1]}")
        
        # Output device selection priority
        # First, try to use previously saved device from settings
        if saved_output_device is not None:
            # Make sure the device still exists
            if any(idx == saved_output_device for idx, _ in devices["output"]):
                info["output"] = saved_output_device
                print(f"Using previously selected output device: {self.pyaudio.get_device_info_by_index(saved_output_device)['name']}")
            else:
                print("Previously saved output device not found, selecting best available")
        
        # If no saved device or it's not available, use fallback logic
        if info["output"] is None:
            if macbook_speakers_idx is not None:
                info["output"] = macbook_speakers_idx
                print(f"Using MacBook Pro speakers as output device")
            elif built_in_speakers_idx is not None:
                info["output"] = built_in_speakers_idx
                print(f"Using built-in speakers as output device")
            else:
                # Try system default as fallback
                try:
                    info["output"] = self.pyaudio.get_default_output_device_info()["index"]
                    print(f"Using system default output device: {self.pyaudio.get_device_info_by_index(info['output'])['name']}")
                except IOError:
                    # Last resort: first available device
                    if devices["output"]:
                        info["output"] = devices["output"][0][0]
                        print(f"Using first available output device: {devices['output'][0][1]}")
        
        info["devices"] = devices
        return info
    
    def list_devices(self):
        """Return a list of available audio devices."""
        return self.device_info["devices"]
    
    def set_input_device(self, device_index):
        """Set the input device to use for recording."""
        self.device_info["input"] = device_index
    
    def set_output_device(self, device_index):
        """Set the output device to use for recording."""
        self.device_info["output"] = device_index
    
    def start_recording(self):
        """Start recording audio."""
        if self.recording:
            if self.paused:
                self.paused = False
                print("Recording resumed")
                return True
            return False  # Already recording and not paused
        
        self.recording = True
        self.paused = False
        self.audio_frames = []
        self.start_time = datetime.now()
        timestamp = self.start_time.strftime("%Y%m%d_%H%M%S")
        self.recording_filename = os.path.join(RECORDINGS_DIR, f"meeting_{timestamp}.{AUDIO_FORMAT}")
        
        # Start recording in a separate thread
        self.recording_thread = threading.Thread(target=self._record)
        self.recording_thread.daemon = True
        self.recording_thread.start()
        
        print(f"Recording started, saving to {self.recording_filename}")
        return True
    
    def pause_recording(self):
        """Pause the recording."""
        if not self.recording or self.paused:
            return False
        
        self.paused = True
        print("Recording paused")
        return True
    
    def stop_recording(self):
        """Stop recording and save the audio file."""
        if not self.recording:
            return None
        
        self.recording = False
        if self.recording_thread:
            self.recording_thread.join()
        
        # Save the recorded audio
        if self.audio_frames:
            self._save_recording()
            print(f"Recording saved to {self.recording_filename}")
            return self.recording_filename
        
        return None
    
    def _record(self):
        """Record audio from the selected input device."""
        try:
            # Get device info to check channel support
            input_device_info = self.pyaudio.get_device_info_by_index(self.device_info["input"])
            max_channels = int(input_device_info["maxInputChannels"])
            
            # Adjust channels if device doesn't support the configured number
            channels_to_use = min(CHANNELS, max_channels)
            if channels_to_use != CHANNELS:
                print(f"Notice: Device only supports {channels_to_use} channels, adjusting from {CHANNELS}")
            
            # Open audio stream with appropriate channel count
            stream = self.pyaudio.open(
                format=pyaudio.paInt16,
                channels=channels_to_use,
                rate=RATE,
                input=True,
                input_device_index=self.device_info["input"],
                frames_per_buffer=CHUNK
            )
            
            print(f"Recording started with {channels_to_use} channel(s)...")
            
            # Store the actual channels used for saving the file
            self._channels_used = channels_to_use
            recording_successful = False
            
            while self.recording:
                if not self.paused:
                    try:
                        data = stream.read(CHUNK, exception_on_overflow=False)
                        self.audio_frames.append(data)
                        recording_successful = True  # Mark as successful if we get at least some data
                    except Exception as e:
                        print(f"Error reading audio chunk: {e}")
                else:
                    time.sleep(0.1)  # Sleep when paused to reduce CPU usage
            
            stream.stop_stream()
            stream.close()
            
            if not recording_successful:
                print("Warning: No audio data was captured during recording")
            
        except Exception as e:
            print(f"Error during recording: {e}")
            self.recording = False
            self._channels_used = CHANNELS  # Fallback to default
    
    def _save_recording(self):
        """Save the recorded audio frames to a WAV file."""
        try:
            # Make sure we have audio frames to save
            if not self.audio_frames:
                print("Error: No audio frames to save")
                return None
                
            # Use the actual number of channels used during recording
            channels_to_save = getattr(self, '_channels_used', CHANNELS)
            
            with wave.open(self.recording_filename, 'wb') as wf:
                wf.setnchannels(channels_to_save)
                wf.setsampwidth(self.pyaudio.get_sample_size(pyaudio.paInt16))
                wf.setframerate(RATE)
                wf.writeframes(b''.join(self.audio_frames))
                
            # Verify the file was created
            if os.path.exists(self.recording_filename) and os.path.getsize(self.recording_filename) > 0:
                print(f"Successfully saved recording with {channels_to_save} channel(s)")
                return self.recording_filename
            else:
                print("Error: Recording file was not created properly")
                return None
        except Exception as e:
            print(f"Error saving recording: {e}")
            return None
    
    def get_recording_duration(self):
        """Get the current recording duration in seconds."""
        if not self.start_time:
            return 0
        
        return (datetime.now() - self.start_time).total_seconds()
    
    def cleanup(self):
        """Clean up resources."""
        if self.recording:
            self.stop_recording()
        self.pyaudio.terminate()


# For testing standalone functionality
if __name__ == "__main__":
    recorder = AudioRecorder()
    print("Available input devices:")
    for idx, name in recorder.list_devices()["input"]:
        print(f"  {idx}: {name}")
    
    print("Available output devices:")
    for idx, name in recorder.list_devices()["output"]:
        print(f"  {idx}: {name}")
    
    print("Recording for 5 seconds...")
    recorder.start_recording()
    time.sleep(5)
    filename = recorder.stop_recording()
    print(f"Recording saved to {filename}")
    recorder.cleanup()
