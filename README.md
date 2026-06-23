# J.A.R.V.I.S - Your AI Voice Assistant

A fully-featured AI voice assistant powered by LiveKit, Google Gemini, and a local memory system. JARVIS can manage your calendar, read emails, search the web, generate images, and much more.

---

## 📋 Table of Contents

- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running JARVIS](#running-jarvis)
- [Customization Guide](#customization-guide)
- [Troubleshooting](#troubleshooting)
- [Features](#features)

---

## Prerequisites

Before you begin, ensure you have the following:

- **Python 3.10+** installed
- **Git** installed
- **LiveKit account** (free tier available at [livekit.io](https://livekit.io))
- **API Keys:**
  - OpenAI API key (for embeddings and AI features)
  - Google API key (for Gemini model)
  - Google OAuth credentials (optional, for Gmail/Calendar/Drive)

---

## Installation

### 1. Clone the Repository

```bash
cd C:\Dev\GitHub
git clone <your-repo-url> Live_Kit_Jarvis
cd Live_Kit_Jarvis
```

### 2. Create Virtual Environment

```bash
python -m venv venv
```

### 3. Activate Virtual Environment

**Windows (PowerShell):**
```bash
.\venv\Scripts\Activate.ps1
```

**Windows (Command Prompt):**
```bash
.\venv\Scripts\activate.bat
```

**Linux/Mac:**
```bash
source venv/bin/activate
```

### 4. Install Dependencies

```bash
pip install -r requirements.txt
```

---

## Configuration

### 1. Set Up Environment Variables

Copy the `.env` file and configure the following variables:

```env
# LiveKit Configuration (REQUIRED)
LIVEKIT_URL=<your-livekit-url>
LIVEKIT_API_KEY=<your-api-key>
LIVEKIT_API_SECRET=<your-api-secret>

# Memory Database
JARVIS_MEMORY_DB=jarvis_memory.db

# Server Configuration
JARVIS_PORT=8080
PORT=8080

# AI API Keys
GOOGLE_API_KEY=<your-google-api-key>
OPENAI_API_KEY=<your-openai-api-key>

# Web UI Authentication
JARVIS_PIN=123456

# Google OAuth (Optional - for Gmail/Calendar/Drive)
GOOGLE_TOKEN_JSON=
```

### 2. Get LiveKit Credentials

**IMPORTANT:** Your LiveKit URL may expire or become invalid. Here's how to get fresh credentials:

1. Go to [LiveKit Cloud](https://cloud.livekit.io)
2. Sign in or create a free account
3. Create a new project or select existing one
4. Go to **Settings** → **Keys**
5. Copy:
   - **WebSocket URL** → `LIVEKIT_URL`
   - **API Key** → `LIVEKIT_API_KEY`
   - **API Secret** → `LIVEKIT_API_SECRET`

**Example LiveKit URL formats:**
- Cloud: `wss://your-project.livekit.cloud`
- Self-hosted: `ws://localhost:7880` or `wss://your-domain.com`

### 3. Get Google API Key

1. Go to [Google AI Studio](https://aistudio.google.com/app/apikey)
2. Create or select a project
3. Generate an API key
4. Copy the key to `GOOGLE_API_KEY` in `.env`

### 4. Get OpenAI API Key

1. Go to [OpenAI Platform](https://platform.openai.com/api-keys)
2. Sign in and create a new API key
3. Copy the key to `OPENAI_API_KEY` in `.env`

### 5. Set Up Google OAuth (Optional)

For Gmail, Calendar, and Drive features:

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project or select existing
3. Enable APIs: Gmail API, Calendar API, Drive API
4. Create OAuth 2.0 credentials
5. Download `credentials.json` to the project root
6. Run the OAuth flow:

```bash
python google_auth.py
```

This will create `token.json` for authenticated access.

---

## Running JARVIS

### Method 1: Web UI + Voice Agent (Recommended)

**Step 1: Start the Web Server**

```bash
python jarvis_server.py
```

This will start the web interface on `http://localhost:8080`

**Step 2: Start the LiveKit Agent**

Open a **new terminal** in the same directory:

```bash
# Activate virtual environment first
.\venv\Scripts\Activate.ps1  # Windows PowerShell
# OR
source venv/bin/activate     # Linux/Mac

# Run the agent
python agent.py start
```

**Step 3: Access the Web UI**

1. Open your browser to `http://localhost:8080`
2. Enter your PIN (default: `123456`)
3. Click "Connect to JARVIS"
4. Enter the LiveKit room details when prompted
5. Allow microphone permissions
6. Start talking to JARVIS!

### Method 2: Command Line Only

Run just the LiveKit agent:

```bash
python agent.py start
```

Connect using the LiveKit SDK in your preferred client.

---

## Customization Guide

### 🎭 Change JARVIS Personality

Edit `prompts.py`:

```python
AGENT_INSTRUCTION = """
# Persona
You are Jarvis, a highly capable virtual assistant...
[Modify the personality traits, tone, communication style]
"""

SESSION_INSTRUCTION = """
[Change the initial greeting]
"""
```

### 🔧 Add/Remove Tools

Edit `agent.py` to modify the tools array:

```python
tools=[
    # Core
    get_weather, search_web,
    # Add your custom tools here
    my_custom_tool,
],
```

Create new tools in `tools.py`:

```python
async def my_custom_tool(param: str) -> str:
    """Tool description for the AI."""
    # Your implementation
    return "result"
```

### 🎤 Change Voice

Edit `agent.py` to change the voice model:

```python
llm=google.beta.realtime.RealtimeModel(
    model="gemini-2.5-flash-native-audio-preview-12-2025",
    voice="Charon",  # ← Change this (options: Puck, Charon, Kore, Fenrir, Aoede)
    temperature=0.8,
),
```

Available voices:
- **Puck** - Cheerful, energetic
- **Charon** - Deep, authoritative (current)
- **Kore** - Warm, friendly
- **Fenrir** - Professional, neutral
- **Aoede** - Expressive, dynamic

### 🧠 Modify Memory System

Edit `jarvis_memory.py` to change:
- Embedding model
- Memory extraction prompts
- Search behavior
- Storage format

### 🎨 Customize Web UI

Edit `jarvis-ui.html` to change:
- Visual appearance
- Layout
- Colors and styling
- UI features

---

## Troubleshooting

### ❌ "LiveKit URL would not work / didn't connect"

**Problem:** The LiveKit URL in your `.env` may be expired or invalid.

**Solutions:**

1. **Get fresh LiveKit credentials:**
   - Go to [LiveKit Cloud](https://cloud.livekit.io)
   - Create a new project or navigate to existing
   - Get new API Key, Secret, and WebSocket URL
   - Update `.env` file

2. **Check LiveKit URL format:**
   - Cloud: Must start with `wss://` (secure WebSocket)
   - Local: Can use `ws://localhost:7880`
   - Remove trailing slashes

3. **Test connection:**
   ```bash
   # In the web UI console (F12), check for WebSocket errors
   # Or test using LiveKit CLI:
   lk room list --url <your-url> --api-key <key> --api-secret <secret>
   ```

4. **Firewall/Network issues:**
   - Ensure WebSocket connections (port 443/7880) aren't blocked
   - Try disabling VPN temporarily
   - Check corporate firewall settings

### ❌ Python Module Import Errors

```bash
# Reinstall dependencies
pip install -r requirements.txt --force-reinstall
```

### ❌ "Port 8080 already in use"

```bash
# Change port in .env
JARVIS_PORT=8081

# Or kill the process using the port (Windows)
netstat -ano | findstr :8080
taskkill /PID <process-id> /F

# Or kill the process using the port (Linux/Mac)
lsof -ti:8080 | xargs kill -9
```

### ❌ Memory/Database Issues

```bash
# Reset the database
rm jarvis_memory.db

# Restart the server - it will create a fresh database
python jarvis_server.py
```

### ❌ Google OAuth Errors

```bash
# Re-run the OAuth setup
python google_auth.py

# Delete old tokens if needed
rm token.json
```

### ❌ Virtual Environment Issues

```bash
# Recreate virtual environment
deactivate  # If currently activated
rm -rf venv  # Or rd /s /q venv on Windows
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

---

## Features

### 🧠 Memory System
- Persistent memory across sessions
- Semantic search using embeddings
- User-specific memory isolation
- Memory statistics and management via web UI

### 📧 Gmail Integration
- Check email
- Search messages
- Draft and send emails
- OAuth-authenticated

### 📅 Calendar Management
- Check schedule
- Create events
- Check for conflicts
- Natural language date parsing

### ☁️ Google Drive
- Upload files
- Search documents
- Read file contents

### 🌐 Web Tools
- Weather forecasts
- Web search (DuckDuckGo)
- Real-time information retrieval

### 💻 Code Execution
- Run Python code
- Save and execute scripts
- Sandboxed execution environment

### 🎨 Image Generation
- AI-powered image creation
- Custom prompts and styles

### 📚 Course Generation
- Generate course outlines
- Create lessons
- Design workbooks

### 📝 File Operations
- Create, read, and list files
- Local file management
- Directory operations

---

## Quick Reference Commands

### Start the system:
```bash
# Terminal 1: Web Server
python jarvis_server.py

# Terminal 2: Voice Agent
python agent.py start
```

### Stop the system:
```bash
# Press Ctrl+C in each terminal
```

### Update dependencies:
```bash
pip install -r requirements.txt --upgrade
```

### View logs:
```bash
# Logs appear in the terminal where each component is running
```

### Reset everything:
```bash
rm jarvis_memory.db
rm token.json
python jarvis_server.py  # Creates fresh database
```

---

## Support & Resources

- **LiveKit Docs:** https://docs.livekit.io
- **Google Gemini:** https://ai.google.dev
- **OpenAI API:** https://platform.openai.com/docs

---

## Security Notes

- Never commit `.env` file to version control
- Keep API keys secure and rotate regularly
- Change the default `JARVIS_PIN` immediately
- Use HTTPS in production
- Review OAuth scopes before granting access

---

**Made with ❤️ using LiveKit, Google Gemini, and OpenAI**
