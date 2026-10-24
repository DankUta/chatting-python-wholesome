# Countdown Video Generator (`chatting`)

An automated Python pipeline that generates a 1080p countdown video from your Google Sheet rankings, complete with YouTube clips, voter score sidebars, average ratings, nominator avatars, and on-screen comment boxes.

---

## 📋 Prerequisites

Before running the script, make sure you have the following installed on your machine:

1. **Python 3.9+**
   * Download from [python.org](https://www.python.org/downloads/) (check **"Add Python to PATH"** during installation).
2. **FFmpeg** (Required for cutting clips, overlaying graphics, and concatenating videos)
   * **Windows (via PowerShell / Terminal):**
     ```powershell
     winget install Gyan.FFmpeg
     ```
     *(Restart your terminal or IDE after installing so `ffmpeg` is recognized in your `PATH`, or place `ffmpeg.exe` directly inside this project folder).*
   * **macOS (via Homebrew):** `brew install ffmpeg`
   * **Linux (Ubuntu/Debian):** `sudo apt install ffmpeg`
3. **Python Dependencies**
   Install the required packages via `pip`:
   ```bash
   pip install pandas pillow yt-dlp