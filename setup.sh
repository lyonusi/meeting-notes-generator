#!/bin/bash
# Setup script for Meeting Notes Generator

echo "Setting up Meeting Notes Generator..."

# Check for Python 3.7+
python3 --version 2>&1 | grep -q "Python 3.[789]" || python3 --version 2>&1 | grep -q "Python 3.[1-9][0-9]"
if [ $? -ne 0 ]; then
    echo "Error: Python 3.7 or higher is required"
    exit 1
fi

# Create virtual environment (optional)
read -p "Create a virtual environment? (y/n): " CREATE_VENV
if [[ "$CREATE_VENV" == "y" || "$CREATE_VENV" == "Y" ]]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    
    if [ -d "venv" ]; then
        echo "Activating virtual environment..."
        source venv/bin/activate
    else
        echo "Failed to create virtual environment. Continuing with system Python..."
    fi
fi

# Install dependencies
echo "Installing dependencies..."
pip3 install -r requirements.txt

# macOS specific setup
if [[ "$OSTYPE" == "darwin"* ]]; then
    echo "Detected macOS system"
    
    # Check if PyAudio is installed correctly
    python3 -c "import pyaudio" 2>/dev/null
    if [ $? -ne 0 ]; then
        echo "PyAudio is not installed correctly."
        echo "If installation fails, you might need to install portaudio first:"
        echo "  brew install portaudio"
        echo "  pip3 install pyaudio"
    fi
    
    # Check for BlackHole (virtual audio device)
    system_profiler SPAudioDataType 2>&1 | grep -q "BlackHole"
    if [ $? -ne 0 ]; then
        echo "BlackHole virtual audio device is not detected."
        echo "To capture system audio, install BlackHole:"
        echo "  brew install blackhole-2ch"
        echo "Then set up a Multi-Output Device in Audio MIDI Setup."
        echo "See README.md for detailed instructions."
    else
        echo "BlackHole virtual audio device is installed."
    fi
fi

# Check AWS CLI configuration
if command -v aws &> /dev/null; then
    aws --version
    echo "Checking AWS credentials..."
    aws sts get-caller-identity &> /dev/null
    if [ $? -eq 0 ]; then
        echo "AWS credentials are configured correctly."
    else
        echo "AWS credentials are not configured or invalid."
        echo "Please set up your AWS credentials as described in README.md"
    fi
else
    echo "AWS CLI is not installed. Cannot verify credentials."
    echo "Please ensure your AWS credentials are configured."
fi

# Make scripts executable
chmod +x main.py
chmod +x demo.py
chmod +x test_profile.sh

# Check for tkinter installation (needed for version management UI)
echo "Checking for tkinter (required for version management UI)..."
python3 -c "import tkinter" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "WARNING: tkinter is not installed, which is required for the version management UI."
    echo "On macOS: Install python-tk using Homebrew:"
    echo "  brew install python-tk"
    echo "On Ubuntu/Debian: Install python3-tk package:"
    echo "  sudo apt-get install python3-tk"
    echo "On Fedora: Install python3-tkinter package:"
    echo "  sudo dnf install python3-tkinter"
else
    echo "tkinter is installed correctly."
fi

# Create metadata directory for version management
mkdir -p "notes/metadata"
echo "Created version management metadata directory."

# Check for AWS Bedrock access and inference profiles if AWS CLI is available
if command -v aws &> /dev/null; then
    echo "Checking AWS Bedrock access..."
    AWS_PROFILE=${AWS_PROFILE:-"bedrock"}
    
    # Try to list Bedrock models (this will fail gracefully if no access)
    aws bedrock list-foundation-models --profile "$AWS_PROFILE" &> /dev/null
    if [ $? -eq 0 ]; then
        echo "AWS Bedrock access confirmed."
        echo "Checking for inference profiles..."
        aws bedrock list-inference-profiles --profile "$AWS_PROFILE" &> /dev/null
        if [ $? -eq 0 ]; then
            NUM_PROFILES=$(aws bedrock list-inference-profiles --profile "$AWS_PROFILE" --query 'inferenceProfiles | length(@)' --output text)
            if [ "$NUM_PROFILES" -gt 0 ]; then
                echo "Found $NUM_PROFILES inference profiles."
            else
                echo "No inference profiles found. You may need to create them for newer Claude models."
                echo "See README.md for detailed instructions on inference profiles."
            fi
        else
            echo "Unable to check inference profiles. Make sure your AWS credentials have bedrock:ListInferenceProfiles permission."
        fi
    else
        echo "AWS Bedrock access not detected or not authorized."
        echo "To use Claude models, ensure your AWS account has Bedrock access."
    fi
fi

echo ""
echo "Setup completed!"
echo "To run the application: ./main.py"
echo "To run the demo with version management features: ./demo.py --file path/to/audio.wav --show-versions"
echo "To test your inference profile setup: ./test_profile.sh [aws-profile-name]"
echo "See README.md for detailed usage instructions."
