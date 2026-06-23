"""
Jarvis Web Server — Serves the UI and exposes memory API.

Run:
    pip install fastapi uvicorn
    python jarvis_server.py

Then open http://localhost:8080 in your browser.

Security:
    Set JARVIS_PIN in .env to enable PIN authentication.
    If JARVIS_PIN is not set, the UI is open (good for local testing).
    PIN is entered once per browser session (stored in a signed cookie).

Endpoints:
    GET  /                          → Serves the Jarvis UI (or PIN page)
    POST /auth                      → Verify PIN, set session cookie
    GET  /api/memories?user_id=X    → Fetch memories for a user
    POST /api/memories/search       → Semantic search memories
    GET  /api/memories/stats        → Memory statistics
    POST /api/memories/add          → Manually add a memory
    DELETE /api/memories/<id>        → Deprecate a memory
    GET  /api/token                 → Generate LiveKit room token (if configured)
"""

import os
import hashlib
import secrets
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Query, HTTPException, Request, Response, Cookie, Depends
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

from jarvis_memory import JarvisMemory

load_dotenv(".env")
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="J.A.R.V.I.S", version="1.0.0")

# Allow CORS for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Authentication ────────────────────────────────────────────

JARVIS_PIN = os.getenv("JARVIS_PIN", "")  # Empty = no auth required
# Secret key for signing cookies — generated fresh each restart
# (means cookies invalidate on server restart, which is fine)
COOKIE_SECRET = os.getenv("JARVIS_COOKIE_SECRET", secrets.token_hex(32))
SESSION_COOKIE_NAME = "jarvis_session"

# Track failed attempts per IP (basic rate limiting)
_failed_attempts: dict[str, int] = {}
MAX_FAILED_ATTEMPTS = 5


def _make_session_token(pin: str) -> str:
    """Create a signed session token from the PIN."""
    return hashlib.sha256(f"{pin}:{COOKIE_SECRET}".encode()).hexdigest()


def _auth_enabled() -> bool:
    return bool(JARVIS_PIN.strip())


def _verify_session(session_token: str) -> bool:
    """Check if the session cookie is valid."""
    if not _auth_enabled():
        return True
    expected = _make_session_token(JARVIS_PIN)
    return secrets.compare_digest(session_token, expected)


async def require_auth(request: Request):
    """Dependency that checks authentication on API routes."""
    if not _auth_enabled():
        return  # No PIN set, allow everything

    token = request.cookies.get(SESSION_COOKIE_NAME, "")
    if not _verify_session(token):
        raise HTTPException(401, "Authentication required")


# Memory instance (shared across requests)
memory = JarvisMemory(db_path=os.getenv("JARVIS_MEMORY_DB", "jarvis_memory.db"))


# ── Models ────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query: str
    user_id: str = "Ma'am"
    limit: int = 10

class AddMemoryRequest(BaseModel):
    text: str
    user_id: str = "Ma'am"
    memory_type: str = "fact"

class PinRequest(BaseModel):
    pin: str


# ── PIN Login Page ────────────────────────────────────────────

PIN_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>J.A.R.V.I.S — Access Required</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Courier New', monospace;
            background: #000;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            color: #d4af37;
        }
        .grid-bg {
            position: fixed; inset: 0;
            background-image:
                linear-gradient(rgba(212,175,55,0.05) 1px, transparent 1px),
                linear-gradient(90deg, rgba(212,175,55,0.05) 1px, transparent 1px);
            background-size: 50px 50px;
            animation: drift 20s linear infinite;
        }
        @keyframes drift { to { transform: translate(50px, 50px); } }

        .auth-box {
            position: relative; z-index: 1;
            background: rgba(0,0,0,0.85);
            border: 1px solid rgba(212,175,55,0.3);
            padding: 3rem 2.5rem;
            text-align: center;
            min-width: 360px;
        }
        .auth-box::before {
            content: '';
            position: absolute; top: 0; left: 0; right: 0;
            height: 2px;
            background: linear-gradient(90deg, transparent, #d4af37, transparent);
            animation: scan 3s linear infinite;
        }
        @keyframes scan { 0%{transform:translateX(-100%)} 100%{transform:translateX(100%)} }

        h1 {
            font-size: 2rem; font-weight: 300;
            letter-spacing: 8px;
            text-shadow: 0 0 10px rgba(212,175,55,0.5);
            margin-bottom: 0.5rem;
        }
        .sub { font-size: 0.7rem; color: rgba(212,175,55,0.5); letter-spacing: 2px; margin-bottom: 2rem; }

        .pin-label {
            font-size: 0.7rem; letter-spacing: 2px;
            color: rgba(212,175,55,0.7);
            margin-bottom: 0.75rem;
            text-transform: uppercase;
        }

        .pin-row {
            display: flex; gap: 12px; justify-content: center; margin-bottom: 1.5rem;
        }
        .pin-digit {
            width: 52px; height: 60px;
            background: rgba(0,0,0,0.6);
            border: 1px solid rgba(212,175,55,0.3);
            color: #d4af37;
            font-family: 'Courier New', monospace;
            font-size: 1.8rem;
            text-align: center;
            transition: border-color 0.2s, box-shadow 0.2s;
        }
        .pin-digit:focus {
            outline: none;
            border-color: #d4af37;
            box-shadow: 0 0 12px rgba(212,175,55,0.3);
        }
        .pin-digit.error {
            border-color: #c0392b;
            animation: shake 0.4s ease;
        }
        @keyframes shake { 25%{transform:translateX(-4px)} 75%{transform:translateX(4px)} }

        .btn {
            width: 100%; padding: 0.8rem;
            background: rgba(212,175,55,0.1);
            border: 1px solid #d4af37;
            color: #d4af37;
            font-family: 'Courier New', monospace;
            font-size: 0.85rem; letter-spacing: 3px;
            cursor: pointer; text-transform: uppercase;
            transition: all 0.2s;
        }
        .btn:hover { background: rgba(212,175,55,0.2); box-shadow: 0 0 15px rgba(212,175,55,0.3); }
        .btn:disabled { opacity: 0.3; cursor: not-allowed; }

        .error-msg {
            color: #c0392b; font-size: 0.75rem;
            margin-top: 1rem; min-height: 1.2em;
            letter-spacing: 1px;
        }
        .attempts {
            font-size: 0.6rem; color: rgba(212,175,55,0.25);
            margin-top: 1rem; letter-spacing: 1px;
        }
    </style>
</head>
<body>
    <div class="grid-bg"></div>
    <div class="auth-box">
        <h1>J.A.R.V.I.S</h1>
        <div class="sub">AUTHORIZATION REQUIRED</div>

        <div class="pin-label">ENTER ACCESS CODE</div>
        <div class="pin-row">
            <input class="pin-digit" type="password" maxlength="1" inputmode="numeric" autofocus>
            <input class="pin-digit" type="password" maxlength="1" inputmode="numeric">
            <input class="pin-digit" type="password" maxlength="1" inputmode="numeric">
            <input class="pin-digit" type="password" maxlength="1" inputmode="numeric">
            <input class="pin-digit" type="password" maxlength="1" inputmode="numeric">
            <input class="pin-digit" type="password" maxlength="1" inputmode="numeric">
        </div>

        <button class="btn" id="submitBtn" onclick="submitPin()">AUTHENTICATE</button>
        <div class="error-msg" id="errorMsg"></div>
        <div class="attempts" id="attempts"></div>
    </div>

<script>
const digits = document.querySelectorAll('.pin-digit');

// Auto-advance on input
digits.forEach((d, i) => {
    d.addEventListener('input', () => {
        if (d.value && i < digits.length - 1) digits[i + 1].focus();
    });
    d.addEventListener('keydown', (e) => {
        if (e.key === 'Backspace' && !d.value && i > 0) {
            digits[i - 1].focus();
            digits[i - 1].value = '';
        }
        if (e.key === 'Enter') submitPin();
    });
    // Handle paste
    d.addEventListener('paste', (e) => {
        e.preventDefault();
        const text = (e.clipboardData || window.clipboardData).getData('text').trim();
        for (let j = 0; j < Math.min(text.length, digits.length - i); j++) {
            digits[i + j].value = text[j];
        }
        const next = Math.min(i + text.length, digits.length - 1);
        digits[next].focus();
    });
});

async function submitPin() {
    const pin = Array.from(digits).map(d => d.value).join('');
    if (pin.length < 4) {
        showError('Enter at least 4 digits');
        return;
    }

    const btn = document.getElementById('submitBtn');
    btn.disabled = true;
    btn.textContent = 'VERIFYING...';

    try {
        const res = await fetch('/auth', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pin }),
        });

        if (res.ok) {
            window.location.href = '/';
        } else {
            const data = await res.json();
            showError(data.detail || 'ACCESS DENIED');
            digits.forEach(d => { d.value = ''; d.classList.add('error'); });
            setTimeout(() => digits.forEach(d => d.classList.remove('error')), 500);
            digits[0].focus();
        }
    } catch (err) {
        showError('Connection error');
    }

    btn.disabled = false;
    btn.textContent = 'AUTHENTICATE';
}

function showError(msg) {
    document.getElementById('errorMsg').textContent = msg;
}
</script>
</body>
</html>"""


# ── Auth Routes ───────────────────────────────────────────────

@app.post("/auth")
async def authenticate(req: PinRequest, request: Request, response: Response):
    """Verify PIN and set session cookie."""
    if not _auth_enabled():
        return {"status": "ok", "message": "No PIN configured"}

    client_ip = request.client.host if request.client else "unknown"

    # Rate limiting
    if _failed_attempts.get(client_ip, 0) >= MAX_FAILED_ATTEMPTS:
        raise HTTPException(429, "Too many failed attempts. Try again later.")

    if not secrets.compare_digest(req.pin, JARVIS_PIN):
        _failed_attempts[client_ip] = _failed_attempts.get(client_ip, 0) + 1
        remaining = MAX_FAILED_ATTEMPTS - _failed_attempts[client_ip]
        logger.warning("Failed PIN attempt from %s (%d remaining)", client_ip, remaining)
        raise HTTPException(403, f"ACCESS DENIED — {remaining} attempts remaining")

    # Success — clear failed attempts and set cookie
    _failed_attempts.pop(client_ip, None)

    token = _make_session_token(JARVIS_PIN)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,     # Only over HTTPS (automatic on Railway/Render)
        samesite="lax",
        max_age=86400 * 7,  # 7 days
    )
    logger.info("Successful authentication from %s", client_ip)
    return {"status": "ok"}


# ── UI ────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_ui(request: Request):
    """Serve the Jarvis frontend, or PIN page if auth required."""
    # Check if auth is needed
    if _auth_enabled():
        token = request.cookies.get(SESSION_COOKIE_NAME, "")
        if not _verify_session(token):
            return HTMLResponse(PIN_PAGE_HTML)

    ui_path = Path(__file__).parent / "jarvis-ui.html"
    if not ui_path.exists():
        raise HTTPException(404, "jarvis-ui.html not found. Place it next to this file.")
    return HTMLResponse(ui_path.read_text())


# ── Memory API ────────────────────────────────────────────────

@app.get("/api/memories", dependencies=[Depends(require_auth)])
async def get_memories(
    user_id: str = Query(default="Ma'am"),
    limit: int = Query(default=20, le=100),
):
    """Fetch all active memories for a user (most recent first)."""
    try:
        results = await memory.search(
            query="everything",
            filters={"user_id": user_id},
            limit=limit,
        )
        return results
    except Exception as e:
        logger.error("Failed to fetch memories: %s", e)
        raise HTTPException(500, str(e))


@app.post("/api/memories/search", dependencies=[Depends(require_auth)])
async def search_memories(req: SearchRequest):
    """Semantic search across memories."""
    try:
        results = await memory.search(
            query=req.query,
            filters={"user_id": req.user_id},
            limit=req.limit,
        )
        return results
    except Exception as e:
        logger.error("Memory search failed: %s", e)
        raise HTTPException(500, str(e))


@app.get("/api/memories/stats", dependencies=[Depends(require_auth)])
async def memory_stats(user_id: str = Query(default="Ma'am")):
    """Get memory statistics."""
    try:
        return await memory.get_stats(user_id)
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/api/memories/add", dependencies=[Depends(require_auth)])
async def add_memory(req: AddMemoryRequest):
    """Manually add a single memory."""
    try:
        count = await memory.add(
            messages=[{"role": "user", "content": req.text}],
            user_id=req.user_id,
        )
        return {"stored": count}
    except Exception as e:
        logger.error("Failed to add memory: %s", e)
        raise HTTPException(500, str(e))


@app.delete("/api/memories/{memory_id}", dependencies=[Depends(require_auth)])
async def deprecate_memory(memory_id: int):
    """Soft-delete a memory."""
    try:
        await memory.deprecate(memory_id)
        return {"status": "deprecated", "id": memory_id}
    except Exception as e:
        raise HTTPException(500, str(e))


# ── File Access ───────────────────────────────────────────────

OUTPUT_DIR = Path(os.getenv("JARVIS_OUTPUT_DIR", Path.home() / "jarvis_output"))


@app.get("/api/files", dependencies=[Depends(require_auth)])
async def list_output_files():
    """List all files in the JARVIS output directory."""
    try:
        if not OUTPUT_DIR.exists():
            return {"files": [], "message": "Output directory is empty"}

        files = []
        for f in sorted(OUTPUT_DIR.rglob("*")):
            if f.is_file():
                rel_path = f.relative_to(OUTPUT_DIR)
                stat = f.stat()
                files.append({
                    "name": str(rel_path),
                    "size": stat.st_size,
                    "modified": stat.st_mtime,
                })

        return {"files": files, "directory": str(OUTPUT_DIR)}
    except Exception as e:
        logger.error("Error listing files: %s", e)
        raise HTTPException(500, str(e))


@app.get("/api/files/{filename:path}", dependencies=[Depends(require_auth)])
async def download_file(filename: str):
    """Download a file from the JARVIS output directory."""
    try:
        # Security: prevent path traversal
        if ".." in filename:
            raise HTTPException(400, "Invalid filename")

        filepath = OUTPUT_DIR / filename

        if not filepath.exists():
            raise HTTPException(404, f"File '{filename}' not found")

        if not filepath.is_file():
            raise HTTPException(400, "Not a file")

        # Determine media type
        suffix = filepath.suffix.lower()
        media_types = {
            ".txt": "text/plain",
            ".md": "text/markdown",
            ".html": "text/html",
            ".py": "text/x-python",
            ".json": "application/json",
            ".csv": "text/csv",
            ".pdf": "application/pdf",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
        }
        media_type = media_types.get(suffix, "application/octet-stream")

        return FileResponse(
            path=filepath,
            filename=filepath.name,
            media_type=media_type,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error downloading file: %s", e)
        raise HTTPException(500, str(e))


# ── LiveKit Token (optional) ─────────────────────────────────

@app.get("/api/token", dependencies=[Depends(require_auth)])
async def get_livekit_token(
    user_id: str = Query(default="Ma'am"),
    room: str = Query(default="jarvis-room"),
):
    """
    Generate a LiveKit room token.
    Requires LIVEKIT_API_KEY and LIVEKIT_API_SECRET in .env
    """
    api_key = os.getenv("LIVEKIT_API_KEY")
    api_secret = os.getenv("LIVEKIT_API_SECRET")

    if not api_key or not api_secret:
        raise HTTPException(
            501,
            "LiveKit credentials not configured. "
            "Set LIVEKIT_API_KEY and LIVEKIT_API_SECRET in .env"
        )

    try:
        from livekit.api import AccessToken, VideoGrants
        token = (
            AccessToken(api_key, api_secret)
            .with_identity(user_id)
            .with_grants(VideoGrants(room_join=True, room=room))
        )
        return {"token": token.to_jwt(), "url": os.getenv("LIVEKIT_URL", "")}
    except ImportError:
        raise HTTPException(501, "livekit-api package not installed. pip install livekit-api")


# ── Run ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("JARVIS_PORT", "8080"))
    logger.info("Starting J.A.R.V.I.S server on port %d", port)
    uvicorn.run(app, host="0.0.0.0", port=port)