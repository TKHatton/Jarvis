"""
Google OAuth Helper for Jarvis

SETUP OPTIONS:

Option A: Local Development (file-based)
1. Go to https://console.cloud.google.com/
2. Create a new project (or select existing)
3. Enable APIs: Gmail, Calendar, Drive
4. Create OAuth 2.0 Client ID (Desktop app)
5. Download JSON as 'credentials.json'
6. Run: python google_auth.py
7. Token saved to 'token.json'

Option B: Cloud Deployment (env var-based)
1. Complete Option A locally first to get token.json
2. Copy the ENTIRE contents of token.json
3. Set as GOOGLE_TOKEN_JSON environment variable in Railway
4. The app will use this instead of file

The token auto-refreshes. If it expires completely, re-run locally and update the env var.
"""

import os
import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Paths for credentials (local development)
CREDENTIALS_DIR = Path(__file__).parent
CREDENTIALS_FILE = CREDENTIALS_DIR / "credentials.json"
TOKEN_FILE = CREDENTIALS_DIR / "token.json"

# For cloud: check /data directory too
DATA_DIR = Path("/data")
CLOUD_TOKEN_FILE = DATA_DIR / "token.json"

# Scopes needed for Gmail, Calendar, and Drive
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive.readonly",
]

_cached_creds = None


def get_google_creds():
    """
    Get valid Google OAuth credentials.

    Priority:
    1. GOOGLE_TOKEN_JSON env var (for cloud deployment)
    2. /data/token.json (Railway persistent volume)
    3. Local token.json file
    4. Run OAuth flow (local only)
    """
    global _cached_creds

    # Return cached creds if still valid
    if _cached_creds and _cached_creds.valid:
        return _cached_creds

    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow

        creds = None

        # Priority 1: Environment variable (cloud deployment)
        token_json = os.getenv("GOOGLE_TOKEN_JSON")
        if token_json:
            try:
                token_data = json.loads(token_json)
                creds = Credentials.from_authorized_user_info(token_data, SCOPES)
                logger.info("Loaded Google credentials from GOOGLE_TOKEN_JSON env var")
            except Exception as e:
                logger.warning(f"Failed to parse GOOGLE_TOKEN_JSON: {e}")

        # Priority 2: Cloud token file (/data/token.json)
        if not creds and CLOUD_TOKEN_FILE.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(CLOUD_TOKEN_FILE), SCOPES)
                logger.info("Loaded Google credentials from /data/token.json")
            except Exception as e:
                logger.warning(f"Failed to load /data/token.json: {e}")

        # Priority 3: Local token file
        if not creds and TOKEN_FILE.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
                logger.info("Loaded Google credentials from local token.json")
            except Exception as e:
                logger.warning(f"Failed to load local token.json: {e}")

        # Refresh if expired
        if creds and creds.expired and creds.refresh_token:
            logger.info("Refreshing Google token...")
            creds.refresh(Request())

            # Save refreshed token
            _save_token(creds)

        # Priority 4: Run OAuth flow (local development only)
        if not creds or not creds.valid:
            if CREDENTIALS_FILE.exists():
                logger.info("Starting OAuth flow...")
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(CREDENTIALS_FILE), SCOPES
                )
                creds = flow.run_local_server(port=0)
                _save_token(creds)
            else:
                logger.warning(
                    "Google credentials not configured.\n"
                    "For local dev: Place credentials.json in project root and run: python google_auth.py\n"
                    "For cloud: Set GOOGLE_TOKEN_JSON env var with contents of token.json"
                )
                return None

        _cached_creds = creds
        return creds

    except ImportError:
        logger.error(
            "Google API packages not installed. Run:\n"
            "pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client"
        )
        return None
    except Exception as e:
        logger.error("Failed to get Google credentials: %s", e)
        return None


def _save_token(creds):
    """Save token to appropriate location."""
    token_json = creds.to_json()

    # Try to save to /data first (Railway persistent volume)
    if DATA_DIR.exists():
        try:
            CLOUD_TOKEN_FILE.write_text(token_json)
            logger.info(f"Token saved to {CLOUD_TOKEN_FILE}")
            return
        except Exception as e:
            logger.warning(f"Could not save to /data: {e}")

    # Fall back to local file
    try:
        TOKEN_FILE.write_text(token_json)
        logger.info(f"Token saved to {TOKEN_FILE}")
    except Exception as e:
        logger.warning(f"Could not save token locally: {e}")


def get_gmail_service():
    """Get Gmail API service client."""
    creds = get_google_creds()
    if not creds:
        return None

    try:
        from googleapiclient.discovery import build
        return build("gmail", "v1", credentials=creds)
    except Exception as e:
        logger.error("Failed to create Gmail service: %s", e)
        return None


def get_calendar_service():
    """Get Google Calendar API service client."""
    creds = get_google_creds()
    if not creds:
        return None

    try:
        from googleapiclient.discovery import build
        return build("calendar", "v3", credentials=creds)
    except Exception as e:
        logger.error("Failed to create Calendar service: %s", e)
        return None


def get_drive_service():
    """Get Google Drive API service client."""
    creds = get_google_creds()
    if not creds:
        return None

    try:
        from googleapiclient.discovery import build
        return build("drive", "v3", credentials=creds)
    except Exception as e:
        logger.error("Failed to create Drive service: %s", e)
        return None


# ---------------------------------------------------------------------------
# Run this file directly to set up OAuth (local development)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Google OAuth Setup for Jarvis")
    print("=" * 40)

    if not CREDENTIALS_FILE.exists():
        print(f"\nERROR: credentials.json not found!")
        print(f"Expected location: {CREDENTIALS_FILE}")
        print("\nTo set up:")
        print("1. Go to https://console.cloud.google.com/")
        print("2. Create/select a project")
        print("3. Enable Gmail API, Calendar API, and Drive API")
        print("4. Go to APIs & Services > Credentials")
        print("5. Create OAuth 2.0 Client ID (Desktop app)")
        print("6. Download the JSON and save as 'credentials.json' here")
        exit(1)

    print("\nStarting OAuth flow...")
    print("A browser window will open for authorization.\n")

    creds = get_google_creds()

    if creds:
        print("\nSUCCESS! Google OAuth is configured.")
        print(f"Token saved to: {TOKEN_FILE}")

        # Test the services
        print("\nTesting services...")

        gmail = get_gmail_service()
        if gmail:
            profile = gmail.users().getProfile(userId="me").execute()
            print(f"  Gmail: Connected as {profile.get('emailAddress')}")

        calendar = get_calendar_service()
        if calendar:
            cal_list = calendar.calendarList().list().execute()
            print(f"  Calendar: Found {len(cal_list.get('items', []))} calendars")

        drive = get_drive_service()
        if drive:
            about = drive.about().get(fields="user").execute()
            print(f"  Drive: Connected as {about.get('user', {}).get('emailAddress')}")

        print("\n" + "=" * 40)
        print("FOR RAILWAY DEPLOYMENT:")
        print("=" * 40)
        print("\nCopy this entire JSON and set as GOOGLE_TOKEN_JSON env var:\n")
        print(TOKEN_FILE.read_text())
        print("\nJarvis is ready to use Gmail, Calendar, and Drive!")
    else:
        print("\nFailed to set up OAuth. Check the errors above.")
