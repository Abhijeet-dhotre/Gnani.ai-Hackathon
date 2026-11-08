# AI Chat Robot for Children
Video demo :- https://www.youtube.com/watch?v=6qxjWUGYwhE

A child-friendly AI voice assistant built with ESP32-S3 and Python. The robot listens to children, responds with AI-generated answers, and displays emotions on OLED eyes.

## What It Does

- **Voice Input**: Child holds button to speak
- **Speech Recognition**: Converts audio to text using Whisper
- **AI Response**: Generates child-friendly responses using Llama LLM
- **Emotion Detection**: Detects if child is happy, sad, angry, etc.
- **Text-to-Speech**: Speaks the response using Edge TTS
- **Visual Feedback**: OLED eyes show matching emotions

<img width="883" height="558" alt="image" src="https://github.com/user-attachments/assets/1a5cf196-ea79-43cc-a6e5-77a8f4860a81" />


## Parts Needed

### Electronics
| Part | Quantity | Notes |
|------|----------|-------|
| ESP32-S3 (XIAO) | 1 | Or any ESP32-S3 board |
| Microphone (I2S) | 1 | e.g., INMP441 or SPH0645 |
| Audio Amplifier | 1 | I2S amplifier (MAX98357A) |
| Speaker | 1 | 4Ω 3W speaker |
| OLED Display | 1 | 128x64 SSD1306, I2C |
| Push Button | 1 | Any momentary button |
| Capacitive Touch Sensor | 1 | TTP223 3-pin module (alternative to button) |
| LED | 1 | Any color (optional) |
| Wires | ~20 | Dupont connectors |

### Tools
- Computer with USB
- Soldering iron (optional)
- 3D printed case (optional)

## Wiring Diagram

```
ESP32-S3 → Microphone (INMP441)
┌─────────────────────────────┐
│  MIC_VDD   → 3.3V           │
│  MIC_GND   → GND            │
│  MIC_SCK   → GPIO5 (SCK)    │
│  MIC_WS    → GPIO4 (WS)     │
│  MIC_SD    → GPIO6 (SD)     │
└─────────────────────────────┘

ESP32-S3 → OLED Display
┌─────────────────────────────┐
│  OLED_SDA   → GPIO3 (SDA)   │
│  OLED_SCL   → GPIO44 (SCL)  │
│  OLED_VCC   → 3.3V          │
│  OLED_GND   → GND           │
└─────────────────────────────┘

ESP32-S3 → I2S Amplifier (MAX98357A)
┌─────────────────────────────┐
│  AMP_LRC   → GPIO7          │
│  AMP_BCLK  → GPIO8          │
│  AMP_DIN   → GPIO9 (D10)    │
│  AMP_SD/MODE (enable) → GPIO1 (D0)
│  AMP_VCC   → 5V             │
│  AMP_GND   → GND            │
│  AMP_OUT+  → Speaker +      │
│  AMP_OUT-  → Speaker -      │
└─────────────────────────────┘

ESP32-S3 → Touch Sensor (TTP223) & LED
┌─────────────────────────────┐
│  TOUCH_VCC → 3.3V           │
│  TOUCH_GND → GND            │
│  TOUCH_SIG → GPIO2          │
│  LED      → GPIO21 (via 330Ω)│
└─────────────────────────────┘
```
![WhatsApp Image 2026-04-03 at 07 33 38](https://github.com/user-attachments/assets/f6334f45-a84b-4a64-add3-623945d13686)

## Software Setup

### 1. Get Groq API Key (Free)

1. Go to [groq.com](https://groq.com)
2. Sign up for free account
3. Copy your API key from dashboard

### 2. Install Python

```bash
python --version
```

### 3. Install Dependencies

```bash
# Create virtual environment (recommended)
python -m venv venv

# Activate on Windows
venv\Scripts\activate

# Activate on Mac/Linux
source venv/bin/activate

# Install packages
pip install flask flask-cors joblib requests groq python-dotenv edge-tts
```

### 4. Install FFmpeg (Required for TTS)

**Windows:**
```bash
choco install ffmpeg
```
Or download from https://ffmpeg.org/download.html

**Mac:**
```bash
brew install ffmpeg
```

**Linux:**
```bash
sudo apt install ffmpeg
```

## ⚙️ Configuration

### 1. Create .env File

Create a file named `.env` in the project folder:

```env
GROQ_API_KEY=your_groq_api_key_here
```

### 2. Update ESP32 IP Address

In `esp32_robot/esp32_robot.ino`, change to your computer's IP:

```cpp
String server_url = "http://YOUR_PC_IP:5050";
```

To find your IP:
- **Windows**: Run `ipconfig` in cmd
- **Mac/Linux**: Run `hostname -I` in terminal

## Running the Server

### Option 1: Using Batch File (Windows)
```bash
run_server.bat
```

### Option 2: Manual Start

```bash
# Terminal 1 - Start TTS server (must run first!)
python tts_server.py

# Terminal 2 - Start main server
python server.py
```

### Verify It's Working
- Main server: http://localhost:5050
- TTS server: http://localhost:8000/tts (returns audio)

## Upload ESP32 Code

### 1. Install Arduino ESP32 Board

1. Open Arduino IDE
2. Go to File → Preferences
3. Add to "Additional Boards Manager URLs":
   ```
   https://espressif.github.io/arduino-esp32/package_esp32_index.json
   ```
4. Tools → Board → Board Manager
5. Search "ESP32" and install

### 2. Install Required Libraries

Sketch → Include Library → Manage Libraries:
- `WiFiManager` by tzapu
- `ArduinoJson` by bblanchon
- `Adafruit_GFX_Library` by adafruit
- `Adafruit_SSD1306` by adafruit

### 3. Upload Code

1. Open `esp32_robot/esp32_robot.ino` in Arduino IDE
2. Select board: "XIAO ESP32S3" or "ESP32S3 Dev Module"
3. Select port (USB)
4. Click Upload

### 4. Initial Setup

1. Power on the robot
2. It creates WiFi AP "XIAO-Robot-Setup"
3. Connect with phone/laptop
4. Enter your WiFi credentials
5. Robot restarts and connects to WiFi

## Using the Robot

1. Start servers on your computer
2. **Touch the sensor** on the robot (hold your finger on it)
3. Speak your message (up to 3 seconds)
4. **Remove your finger** from the sensor
5. Robot sends audio → gets response → speaks back
6. OLED eyes show the detected emotion

## Web Interface

| Page | URL | Purpose |
|------|-----|---------|
| Conversations | http://localhost:5050 | View chat history |
| Report | http://localhost:5050/report | Development report |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/upload` | POST | Send audio, get AI response |
| `/audio/<filename>` | GET | Get response audio |
| `/conversations` | GET | Get all conversations |
| `/conversations/<id>` | DELETE | Delete conversation |
| `/conversations/clear` | POST | Clear all history |
| `/conversations/recompute` | POST | Redetect emotions |
| `/api/report` | GET | Generate report |

## Troubleshooting

### "No WiFi" in Serial Monitor
- Check your WiFi credentials in the code
- Make sure ESP32 is within range

### "Connection Failed" Error
- Verify server is running on computer
- Check IP address in `esp32_robot.ino`
- Make sure firewall allows port 5050

### Audio Not Playing
- Check speaker is connected
- Verify TTS server is running on port 8000

### "API Key" Error
- Make sure `.env` file exists
- Check API key is correct

## Project Structure

```
ai-robot/
├── server.py                  # Main Flask server
├── tts_server.py              # Text-to-speech server
├── .env                       # API key (your file)
├── .gitignore                 # Git ignore rules
├── README.md                  # This file
├── run_server.bat             # Windows startup script
├── conversations.db           # Chat history (auto-created)
├── emotion_classifier*.pkl    # Emotion model
├── esp32_robot/
│   ├── esp32_robot.ino        # Robot firmware
│   └── RoboEyesSimple.h       # OLED eye library
└── templates/
    ├── conversations.html     # History web page
    └── report.html            # Report web page
```


## Credits

- [Groq](https://groq.com) - LLM and Whisper API
- [Edge TTS](https://github.com/rany2/edge-tts) - Free text-to-speech
- [WiFiManager](https://github.com/tzapu/WiFiManager) - ESP32 WiFi config
