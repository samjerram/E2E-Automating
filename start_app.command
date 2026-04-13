#!/bin/bash
# P2NNI CSV Upload – double-click to start. Keeps this window open; close it to stop.
# First run: sets up venv and installs dependencies (may take a few minutes).

cd "$(dirname "$0")"

if ! command -v python3 &>/dev/null; then
    echo "Python 3 not found. Please install Python 3 from python.org and try again."
    read -p "Press Enter to close."
    exit 1
fi

if [ ! -d "venv" ]; then
    echo ""
    echo "First run: the app needs to install dependencies (Python packages and a browser)."
    echo "This may take a few minutes. You only need to do this once."
    echo ""
    read -p "Install now? (y/n) " answer
    case "$(echo "$answer" | tr '[:upper:]' '[:lower:]')" in
        y|yes)
            echo "Setting up..."
            python3 -m venv venv
            source venv/bin/activate
            pip install -r requirements.txt
            playwright install chromium
            echo "Setup complete. Starting app..."
            ;;
        *)
            echo "Skipped. Run this again and choose y when ready, or see HOW_TO_START.txt for manual setup."
            read -p "Press Enter to close."
            exit 0
            ;;
    esac
else
    source venv/bin/activate
fi

# Use venv's Python explicitly (avoids PATH issues when launched from Finder)
exec ./venv/bin/python3 app.py
