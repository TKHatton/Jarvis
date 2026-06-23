import logging
import os
import io
import base64
import requests
import subprocess
import tempfile
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from pathlib import Path
from typing import Literal, Optional

from livekit.agents import function_tool, RunContext
from langchain_community.tools import DuckDuckGoSearchRun

# Output directory for file operations
OUTPUT_DIR = Path(os.getenv("JARVIS_OUTPUT_DIR", Path.home() / "jarvis_output"))

# Store the most recent draft ID for send_email
_last_draft_id: Optional[str] = None


@function_tool
async def get_weather(
    context: RunContext,  # type: ignore
    location: str
) -> str:
    """
    Get the current weather for a given location.
    """

    try:
        response = requests.get(
            f"https://wttr.in/{location}?format=3"
        )

        if response.status_code == 200:
            logging.info(
                f"Weather for {location}: {response.text.strip()}"
            )
            return response.text.strip()

        else:
            logging.error(
                f"Failed to get weather for {location}: {response.status_code}"
            )
            return f"Could not retrieve weather for {location}."

    except Exception as e:
        logging.error(
            f"Error retrieving weather for {location}: {e}"
        )
        return f"An error occurred while retrieving weather for {location}."

@function_tool
async def search_web(
    context: RunContext,  # type: ignore
    query: str
) -> str:
    """
    Search the web using DuckDuckGo.
    """

    try:
        results = DuckDuckGoSearchRun().run(
            tool_input=query
        )

        logging.info(
            f"Search results for '{query}': {results}"
        )

        return results

    except Exception as e:
        logging.error(
            f"Error searching the web for '{query}': {e}"
        )

        return (
            f"An error occurred while searching the web for '{query}'."
        )


# ---------------------------------------------------------------------------
# File Tools
# ---------------------------------------------------------------------------

ALLOWED_EXTENSIONS = {".txt", ".md", ".html", ".py", ".json", ".csv"}


@function_tool
async def create_file(
    context: RunContext,  # type: ignore
    filename: str,
    content: str
) -> str:
    """
    Create a file in the Jarvis output directory.
    Supports: .txt, .md, .html, .py, .json, .csv
    """
    try:
        # Security: reject path traversal and absolute paths
        if ".." in filename or filename.startswith("/") or filename.startswith("\\"):
            return "Error: Invalid filename. Path traversal is not allowed."

        if ":" in filename:  # Windows absolute path check
            return "Error: Invalid filename. Absolute paths are not allowed."

        # Check extension
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            return f"Error: File type '{ext}' not allowed. Supported: {', '.join(ALLOWED_EXTENSIONS)}"

        # Create output directory if needed
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        # Write file
        filepath = OUTPUT_DIR / filename
        filepath.parent.mkdir(parents=True, exist_ok=True)  # Allow subdirs within OUTPUT_DIR
        filepath.write_text(content, encoding="utf-8")

        logging.info(f"Created file: {filepath}")
        return f"Successfully created '{filename}' ({len(content)} characters)"

    except Exception as e:
        logging.error(f"Error creating file '{filename}': {e}")
        return f"Error creating file: {e}"


@function_tool
async def read_file(
    context: RunContext,  # type: ignore
    filename: str
) -> str:
    """
    Read a file from the Jarvis output directory.
    Returns first 5000 characters if file is larger.
    """
    try:
        # Security: reject path traversal and absolute paths
        if ".." in filename or filename.startswith("/") or filename.startswith("\\"):
            return "Error: Invalid filename. Path traversal is not allowed."

        if ":" in filename:
            return "Error: Invalid filename. Absolute paths are not allowed."

        filepath = OUTPUT_DIR / filename

        if not filepath.exists():
            return f"Error: File '{filename}' not found in output directory."

        content = filepath.read_text(encoding="utf-8")

        if len(content) > 5000:
            content = content[:5000] + "\n\n...truncated (file has more content)"

        logging.info(f"Read file: {filepath} ({len(content)} chars)")
        return content

    except Exception as e:
        logging.error(f"Error reading file '{filename}': {e}")
        return f"Error reading file: {e}"


@function_tool
async def list_files(
    context: RunContext  # type: ignore
) -> str:
    """
    List all files in the Jarvis output directory with sizes and dates.
    """
    try:
        if not OUTPUT_DIR.exists():
            return "Output directory is empty (not yet created)."

        files = list(OUTPUT_DIR.rglob("*"))
        files = [f for f in files if f.is_file()]

        if not files:
            return "Output directory is empty."

        lines = [f"Files in {OUTPUT_DIR}:\n"]
        for f in sorted(files):
            rel_path = f.relative_to(OUTPUT_DIR)
            size = f.stat().st_size
            mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")

            if size < 1024:
                size_str = f"{size} B"
            elif size < 1024 * 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size / (1024 * 1024):.1f} MB"

            lines.append(f"  {rel_path} ({size_str}, {mtime})")

        return "\n".join(lines)

    except Exception as e:
        logging.error(f"Error listing files: {e}")
        return f"Error listing files: {e}"


# ---------------------------------------------------------------------------
# Memory Tools
# ---------------------------------------------------------------------------

@function_tool
async def remember_this(
    context: RunContext,  # type: ignore
    content: str,
    memory_type: str = "fact"
) -> str:
    """
    Store a memory for later recall.
    memory_type can be: fact, preference, goal, learning
    """
    try:
        from jarvis_memory import JarvisMemory

        # Validate memory type
        valid_types = {"fact", "preference", "goal", "learning"}
        if memory_type not in valid_types:
            memory_type = "fact"

        memory = JarvisMemory()

        # Store as a user message so the extraction works
        count = await memory.add(
            messages=[{"role": "user", "content": content}],
            user_id="Ma'am"
        )

        logging.info(f"Stored memory: {content[:50]}...")
        return f"Remembered: '{content[:100]}{'...' if len(content) > 100 else ''}'"

    except Exception as e:
        logging.error(f"Error storing memory: {e}")
        return f"Error storing memory: {e}"


@function_tool
async def recall(
    context: RunContext,  # type: ignore
    topic: str
) -> str:
    """
    Search memories for a topic and return matching results.
    """
    try:
        from jarvis_memory import JarvisMemory

        memory = JarvisMemory()
        results = await memory.search(
            query=topic,
            filters={"user_id": "Ma'am"},
            limit=5
        )

        if not results:
            return f"No memories found about '{topic}'."

        lines = [f"Found {len(results)} memories about '{topic}':\n"]
        for r in results:
            mem_type = r.get("type", "fact")
            mem_text = r.get("memory", "")
            score = r.get("score", 0)
            lines.append(f"  [{mem_type}] {mem_text}")

        logging.info(f"Recalled {len(results)} memories for '{topic}'")
        return "\n".join(lines)

    except Exception as e:
        logging.error(f"Error recalling memories: {e}")
        return f"Error recalling memories: {e}"


@function_tool
async def memory_stats(
    context: RunContext  # type: ignore
) -> str:
    """
    Get statistics about stored memories.
    """
    try:
        from jarvis_memory import JarvisMemory

        memory = JarvisMemory()
        stats = await memory.get_stats("Ma'am")

        if not stats or stats.get("total", 0) == 0:
            return "No memories stored yet."

        return (
            f"Memory Statistics:\n"
            f"  Total: {stats.get('total', 0)}\n"
            f"  Facts: {stats.get('facts', 0)}\n"
            f"  Preferences: {stats.get('preferences', 0)}\n"
            f"  Goals: {stats.get('goals', 0)}\n"
            f"  Active: {stats.get('active', 0)}\n"
            f"  Deprecated: {stats.get('deprecated', 0)}"
        )

    except Exception as e:
        logging.error(f"Error getting memory stats: {e}")
        return f"Error getting memory stats: {e}"


# ---------------------------------------------------------------------------
# Gmail Tools
# ---------------------------------------------------------------------------

def _get_gmail_service():
    """Get Gmail service, returns None if not configured."""
    try:
        from google_auth import get_gmail_service
        return get_gmail_service()
    except ImportError:
        return None


@function_tool
async def check_email(
    context: RunContext,  # type: ignore
    count: int = 5
) -> str:
    """
    Check the most recent emails in your inbox.
    Returns subject, sender, and snippet of the N most recent emails.
    """
    service = _get_gmail_service()
    if not service:
        return "Gmail is not configured. Please set up Google OAuth first."

    try:
        # Get recent messages
        results = service.users().messages().list(
            userId="me",
            maxResults=count,
            labelIds=["INBOX"]
        ).execute()

        messages = results.get("messages", [])
        if not messages:
            return "Your inbox is empty."

        lines = [f"Your {len(messages)} most recent emails:\n"]

        for msg in messages:
            msg_data = service.users().messages().get(
                userId="me",
                id=msg["id"],
                format="metadata",
                metadataHeaders=["Subject", "From", "Date"]
            ).execute()

            headers = {h["name"]: h["value"] for h in msg_data.get("payload", {}).get("headers", [])}
            subject = headers.get("Subject", "(no subject)")
            sender = headers.get("From", "Unknown")
            snippet = msg_data.get("snippet", "")[:100]

            lines.append(f"  From: {sender}")
            lines.append(f"  Subject: {subject}")
            lines.append(f"  Preview: {snippet}...")
            lines.append("")

        logging.info(f"Retrieved {len(messages)} emails")
        return "\n".join(lines)

    except Exception as e:
        logging.error(f"Error checking email: {e}")
        return f"Error checking email: {e}"


@function_tool
async def search_email(
    context: RunContext,  # type: ignore
    query: str
) -> str:
    """
    Search Gmail with a query string.
    Examples: "from:boss@company.com", "subject:meeting", "is:unread"
    """
    service = _get_gmail_service()
    if not service:
        return "Gmail is not configured. Please set up Google OAuth first."

    try:
        results = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=5
        ).execute()

        messages = results.get("messages", [])
        if not messages:
            return f"No emails found matching '{query}'."

        lines = [f"Found {len(messages)} emails matching '{query}':\n"]

        for msg in messages:
            msg_data = service.users().messages().get(
                userId="me",
                id=msg["id"],
                format="metadata",
                metadataHeaders=["Subject", "From", "Date"]
            ).execute()

            headers = {h["name"]: h["value"] for h in msg_data.get("payload", {}).get("headers", [])}
            subject = headers.get("Subject", "(no subject)")
            sender = headers.get("From", "Unknown")
            date = headers.get("Date", "")
            snippet = msg_data.get("snippet", "")[:80]

            lines.append(f"  From: {sender}")
            lines.append(f"  Date: {date}")
            lines.append(f"  Subject: {subject}")
            lines.append(f"  Preview: {snippet}...")
            lines.append("")

        logging.info(f"Found {len(messages)} emails for query: {query}")
        return "\n".join(lines)

    except Exception as e:
        logging.error(f"Error searching email: {e}")
        return f"Error searching email: {e}"


@function_tool
async def draft_email(
    context: RunContext,  # type: ignore
    to: str,
    subject: str,
    body: str
) -> str:
    """
    Create an email draft (does NOT send it).
    Say 'send it' to send the draft, or 'edit it' to revise.
    """
    global _last_draft_id

    service = _get_gmail_service()
    if not service:
        return "Gmail is not configured. Please set up Google OAuth first."

    try:
        # Create message
        message = MIMEText(body)
        message["to"] = to
        message["subject"] = subject

        # Encode the message
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

        # Create draft
        draft = service.users().drafts().create(
            userId="me",
            body={"message": {"raw": raw}}
        ).execute()

        _last_draft_id = draft["id"]

        logging.info(f"Created draft {_last_draft_id} to {to}")
        return (
            f"Draft created!\n"
            f"  To: {to}\n"
            f"  Subject: {subject}\n"
            f"  Body: {body[:100]}{'...' if len(body) > 100 else ''}\n\n"
            f"Say 'send it' to send, or 'edit it' to make changes."
        )

    except Exception as e:
        logging.error(f"Error creating draft: {e}")
        return f"Error creating draft: {e}"


@function_tool
async def send_email(
    context: RunContext  # type: ignore
) -> str:
    """
    Send the most recently created email draft.
    You must create a draft first using draft_email.
    """
    global _last_draft_id

    if not _last_draft_id:
        return "No draft to send. Please create a draft first using draft_email."

    service = _get_gmail_service()
    if not service:
        return "Gmail is not configured. Please set up Google OAuth first."

    try:
        # Get draft details first
        draft = service.users().drafts().get(
            userId="me",
            id=_last_draft_id
        ).execute()

        # Send the draft
        sent = service.users().drafts().send(
            userId="me",
            body={"id": _last_draft_id}
        ).execute()

        # Get message details for confirmation
        msg_data = service.users().messages().get(
            userId="me",
            id=sent["id"],
            format="metadata",
            metadataHeaders=["To", "Subject"]
        ).execute()

        headers = {h["name"]: h["value"] for h in msg_data.get("payload", {}).get("headers", [])}
        to = headers.get("To", "recipient")
        subject = headers.get("Subject", "(no subject)")

        # Clear the draft ID
        old_draft_id = _last_draft_id
        _last_draft_id = None

        logging.info(f"Sent draft {old_draft_id} to {to}")
        return f"Email sent successfully!\n  To: {to}\n  Subject: {subject}"

    except Exception as e:
        logging.error(f"Error sending email: {e}")
        return f"Error sending email: {e}"


# ---------------------------------------------------------------------------
# Google Calendar Tools
# ---------------------------------------------------------------------------

def _get_calendar_service():
    """Get Calendar service, returns None if not configured."""
    try:
        from google_auth import get_calendar_service
        return get_calendar_service()
    except ImportError:
        return None


def _parse_natural_time(time_str: str) -> datetime:
    """
    Parse natural language time into datetime.
    Supports: "tomorrow at 2pm", "Thursday 10am", "2024-01-15 14:00", etc.
    """
    try:
        # Try dateutil parser first (handles most formats)
        from dateutil import parser as dateutil_parser
        from dateutil.relativedelta import relativedelta

        time_lower = time_str.lower().strip()
        now = datetime.now()

        # Handle relative terms
        if "tomorrow" in time_lower:
            base = now + timedelta(days=1)
            time_part = time_lower.replace("tomorrow", "").strip()
            if time_part:
                if "at" in time_part:
                    time_part = time_part.replace("at", "").strip()
                parsed_time = dateutil_parser.parse(time_part, fuzzy=True)
                return base.replace(
                    hour=parsed_time.hour,
                    minute=parsed_time.minute,
                    second=0,
                    microsecond=0
                )
            return base.replace(hour=9, minute=0, second=0, microsecond=0)

        if "today" in time_lower:
            base = now
            time_part = time_lower.replace("today", "").strip()
            if time_part:
                if "at" in time_part:
                    time_part = time_part.replace("at", "").strip()
                parsed_time = dateutil_parser.parse(time_part, fuzzy=True)
                return base.replace(
                    hour=parsed_time.hour,
                    minute=parsed_time.minute,
                    second=0,
                    microsecond=0
                )
            return base.replace(hour=9, minute=0, second=0, microsecond=0)

        # Handle day names
        days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        for i, day in enumerate(days):
            if day in time_lower:
                current_day = now.weekday()
                days_ahead = i - current_day
                if days_ahead <= 0:
                    days_ahead += 7
                base = now + timedelta(days=days_ahead)

                time_part = time_lower.replace(day, "").strip()
                if time_part:
                    if "at" in time_part:
                        time_part = time_part.replace("at", "").strip()
                    parsed_time = dateutil_parser.parse(time_part, fuzzy=True)
                    return base.replace(
                        hour=parsed_time.hour,
                        minute=parsed_time.minute,
                        second=0,
                        microsecond=0
                    )
                return base.replace(hour=9, minute=0, second=0, microsecond=0)

        # Default: try to parse directly
        return dateutil_parser.parse(time_str, fuzzy=True)

    except Exception:
        # Fallback: return tomorrow at 9am
        return datetime.now() + timedelta(days=1)


@function_tool
async def check_schedule(
    context: RunContext,  # type: ignore
    days: int = 1
) -> str:
    """
    Check your calendar for today and upcoming days.
    Returns events with time, title, and location.
    """
    service = _get_calendar_service()
    if not service:
        return "Google Calendar is not configured. Please set up Google OAuth first."

    try:
        now = datetime.utcnow()
        time_min = now.isoformat() + "Z"
        time_max = (now + timedelta(days=days)).isoformat() + "Z"

        events_result = service.events().list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            maxResults=20,
            singleEvents=True,
            orderBy="startTime"
        ).execute()

        events = events_result.get("items", [])

        if not events:
            if days == 1:
                return "No events scheduled for today."
            return f"No events scheduled for the next {days} days."

        lines = [f"Your schedule for the next {days} day(s):\n"]

        current_date = None
        for event in events:
            start = event["start"].get("dateTime", event["start"].get("date"))

            # Parse the start time
            if "T" in start:
                event_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                event_date = event_dt.strftime("%A, %B %d")
                event_time = event_dt.strftime("%I:%M %p")
            else:
                event_date = start
                event_time = "All day"

            # Add date header if new day
            if event_date != current_date:
                if current_date is not None:
                    lines.append("")
                lines.append(f"  {event_date}:")
                current_date = event_date

            title = event.get("summary", "(No title)")
            location = event.get("location", "")

            if location:
                lines.append(f"    {event_time} - {title} @ {location}")
            else:
                lines.append(f"    {event_time} - {title}")

        logging.info(f"Retrieved {len(events)} calendar events")
        return "\n".join(lines)

    except Exception as e:
        logging.error(f"Error checking schedule: {e}")
        return f"Error checking schedule: {e}"


@function_tool
async def create_event(
    context: RunContext,  # type: ignore
    title: str,
    start_time: str,
    duration_minutes: int = 60,
    description: str = ""
) -> str:
    """
    Create a calendar event.
    start_time can be natural language like "tomorrow at 2pm" or "Thursday 10am".
    """
    service = _get_calendar_service()
    if not service:
        return "Google Calendar is not configured. Please set up Google OAuth first."

    try:
        # Parse the start time
        start_dt = _parse_natural_time(start_time)
        end_dt = start_dt + timedelta(minutes=duration_minutes)

        event = {
            "summary": title,
            "description": description,
            "start": {
                "dateTime": start_dt.isoformat(),
                "timeZone": "America/Los_Angeles",  # You may want to make this configurable
            },
            "end": {
                "dateTime": end_dt.isoformat(),
                "timeZone": "America/Los_Angeles",
            },
        }

        created_event = service.events().insert(
            calendarId="primary",
            body=event
        ).execute()

        logging.info(f"Created event: {title} at {start_dt}")
        return (
            f"Event created!\n"
            f"  Title: {title}\n"
            f"  When: {start_dt.strftime('%A, %B %d at %I:%M %p')}\n"
            f"  Duration: {duration_minutes} minutes"
        )

    except Exception as e:
        logging.error(f"Error creating event: {e}")
        return f"Error creating event: {e}"


@function_tool
async def check_conflicts(
    context: RunContext,  # type: ignore
    start_time: str,
    duration_minutes: int = 60
) -> str:
    """
    Check if a proposed time conflicts with existing calendar events.
    """
    service = _get_calendar_service()
    if not service:
        return "Google Calendar is not configured. Please set up Google OAuth first."

    try:
        # Parse the start time
        start_dt = _parse_natural_time(start_time)
        end_dt = start_dt + timedelta(minutes=duration_minutes)

        # Query for events in this time range
        events_result = service.events().list(
            calendarId="primary",
            timeMin=start_dt.isoformat() + "Z",
            timeMax=end_dt.isoformat() + "Z",
            singleEvents=True,
            orderBy="startTime"
        ).execute()

        events = events_result.get("items", [])

        if not events:
            return (
                f"No conflicts! The time slot is free:\n"
                f"  {start_dt.strftime('%A, %B %d at %I:%M %p')} "
                f"({duration_minutes} minutes)"
            )

        lines = [
            f"Conflict detected for {start_dt.strftime('%A, %B %d at %I:%M %p')}:\n"
        ]

        for event in events:
            title = event.get("summary", "(No title)")
            start = event["start"].get("dateTime", event["start"].get("date"))
            if "T" in start:
                event_time = datetime.fromisoformat(start.replace("Z", "+00:00")).strftime("%I:%M %p")
            else:
                event_time = "All day"
            lines.append(f"  - {event_time}: {title}")

        logging.info(f"Found {len(events)} conflicts for {start_time}")
        return "\n".join(lines)

    except Exception as e:
        logging.error(f"Error checking conflicts: {e}")
        return f"Error checking conflicts: {e}"


# ---------------------------------------------------------------------------
# Google Drive Tools
# ---------------------------------------------------------------------------

def _get_drive_service():
    """Get Drive service, returns None if not configured."""
    try:
        from google_auth import get_drive_service
        return get_drive_service()
    except ImportError:
        return None


def _get_or_create_folder(service, folder_name: str) -> str:
    """Get folder ID by name, create if it doesn't exist."""
    # Search for existing folder
    query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
    files = results.get('files', [])

    if files:
        return files[0]['id']

    # Create folder
    file_metadata = {
        'name': folder_name,
        'mimeType': 'application/vnd.google-apps.folder'
    }
    folder = service.files().create(body=file_metadata, fields='id').execute()
    return folder.get('id')


@function_tool
async def upload_to_drive(
    context: RunContext,  # type: ignore
    filename: str,
    folder_name: str = "Jarvis Output"
) -> str:
    """
    Upload a file from the local output directory to Google Drive.
    Returns a shareable link to the file.
    """
    service = _get_drive_service()
    if not service:
        return "Google Drive is not configured. Please set up Google OAuth first."

    try:
        from googleapiclient.http import MediaFileUpload

        # Check if file exists locally
        filepath = OUTPUT_DIR / filename
        if not filepath.exists():
            return f"Error: File '{filename}' not found in output directory."

        # Get or create target folder
        folder_id = _get_or_create_folder(service, folder_name)

        # Determine mime type
        ext = filepath.suffix.lower()
        mime_types = {
            '.txt': 'text/plain',
            '.md': 'text/markdown',
            '.html': 'text/html',
            '.py': 'text/x-python',
            '.json': 'application/json',
            '.csv': 'text/csv',
            '.pdf': 'application/pdf',
        }
        mime_type = mime_types.get(ext, 'application/octet-stream')

        # Upload file
        file_metadata = {
            'name': filename,
            'parents': [folder_id]
        }
        media = MediaFileUpload(str(filepath), mimetype=mime_type)
        file = service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, webViewLink'
        ).execute()

        # Make it shareable
        service.permissions().create(
            fileId=file['id'],
            body={'type': 'anyone', 'role': 'reader'}
        ).execute()

        link = file.get('webViewLink', f"https://drive.google.com/file/d/{file['id']}")
        logging.info(f"Uploaded {filename} to Drive: {link}")
        return f"Uploaded '{filename}' to Drive!\nLink: {link}"

    except Exception as e:
        logging.error(f"Error uploading to Drive: {e}")
        return f"Error uploading to Drive: {e}"


@function_tool
async def search_drive(
    context: RunContext,  # type: ignore
    query: str
) -> str:
    """
    Search Google Drive for files matching the query.
    Returns file names, types, last modified dates, and links.
    """
    service = _get_drive_service()
    if not service:
        return "Google Drive is not configured. Please set up Google OAuth first."

    try:
        # Search for files (name contains query, not trashed)
        search_query = f"name contains '{query}' and trashed=false"
        results = service.files().list(
            q=search_query,
            spaces='drive',
            fields='files(id, name, mimeType, modifiedTime, webViewLink)',
            pageSize=10
        ).execute()

        files = results.get('files', [])
        if not files:
            return f"No files found matching '{query}'."

        lines = [f"Found {len(files)} files matching '{query}':\n"]

        for f in files:
            name = f.get('name', 'Unknown')
            mime = f.get('mimeType', '').split('.')[-1]  # Get last part of mime type
            modified = f.get('modifiedTime', '')[:10]  # Just the date
            link = f.get('webViewLink', '')

            lines.append(f"  {name}")
            lines.append(f"    Type: {mime}, Modified: {modified}")
            lines.append(f"    Link: {link}")
            lines.append("")

        logging.info(f"Found {len(files)} Drive files for: {query}")
        return "\n".join(lines)

    except Exception as e:
        logging.error(f"Error searching Drive: {e}")
        return f"Error searching Drive: {e}"


@function_tool
async def read_drive_file(
    context: RunContext,  # type: ignore
    file_name: str
) -> str:
    """
    Read and return the content of a text file from Google Drive.
    Returns the first 5000 characters.
    """
    service = _get_drive_service()
    if not service:
        return "Google Drive is not configured. Please set up Google OAuth first."

    try:
        # Find the file
        query = f"name='{file_name}' and trashed=false"
        results = service.files().list(
            q=query,
            spaces='drive',
            fields='files(id, name, mimeType)',
            pageSize=1
        ).execute()

        files = results.get('files', [])
        if not files:
            return f"File '{file_name}' not found on Drive."

        file = files[0]
        file_id = file['id']
        mime_type = file.get('mimeType', '')

        # Handle Google Docs - export as plain text
        if 'google-apps' in mime_type:
            if 'document' in mime_type:
                content = service.files().export(
                    fileId=file_id,
                    mimeType='text/plain'
                ).execute()
            elif 'spreadsheet' in mime_type:
                content = service.files().export(
                    fileId=file_id,
                    mimeType='text/csv'
                ).execute()
            else:
                return f"Cannot read Google {mime_type.split('.')[-1]} files directly."

            if isinstance(content, bytes):
                content = content.decode('utf-8')
        else:
            # Regular file - download content
            content = service.files().get_media(fileId=file_id).execute()
            if isinstance(content, bytes):
                content = content.decode('utf-8')

        # Truncate if too long
        if len(content) > 5000:
            content = content[:5000] + "\n\n...truncated (file has more content)"

        logging.info(f"Read Drive file: {file_name} ({len(content)} chars)")
        return content

    except Exception as e:
        logging.error(f"Error reading Drive file: {e}")
        return f"Error reading Drive file: {e}"


# ---------------------------------------------------------------------------
# Code Execution Tool
# ---------------------------------------------------------------------------

@function_tool
async def run_python(
    context: RunContext,  # type: ignore
    code: str
) -> str:
    """
    Execute Python code and return the output.
    Use this for calculations, data processing, or testing code snippets.
    """
    try:
        # Security: basic checks
        dangerous_imports = ['subprocess', 'os.system', 'eval', 'exec', '__import__']
        code_lower = code.lower()
        for danger in dangerous_imports:
            if danger in code_lower and 'run_python' not in code_lower:
                return f"Error: Code contains potentially dangerous operation: {danger}"

        # Write code to temp file
        with tempfile.NamedTemporaryFile(
            mode='w',
            suffix='.py',
            delete=False,
            dir=OUTPUT_DIR if OUTPUT_DIR.exists() else None
        ) as f:
            f.write(code)
            temp_path = f.name

        try:
            # Run with timeout
            result = subprocess.run(
                ['python', temp_path],
                capture_output=True,
                text=True,
                timeout=30,  # 30 second timeout
                cwd=str(OUTPUT_DIR) if OUTPUT_DIR.exists() else None
            )

            output = ""
            if result.stdout:
                output += result.stdout
            if result.stderr:
                if output:
                    output += "\n--- Errors ---\n"
                output += result.stderr

            if not output.strip():
                output = "(No output)"

            # Truncate if too long
            if len(output) > 5000:
                output = output[:5000] + "\n\n...truncated"

            logging.info(f"Executed Python code ({len(code)} chars)")
            return output

        finally:
            # Clean up temp file
            try:
                os.unlink(temp_path)
            except Exception:
                pass

    except subprocess.TimeoutExpired:
        return "Error: Code execution timed out (30 second limit)"
    except Exception as e:
        logging.error(f"Error executing Python code: {e}")
        return f"Error executing code: {e}"


@function_tool
async def save_script(
    context: RunContext,  # type: ignore
    filename: str,
    code: str,
    description: str = ""
) -> str:
    """
    Save a Python script to the output directory for later use.
    Unlike run_python, this saves the code as a reusable .py file.
    """
    try:
        # Ensure .py extension
        if not filename.endswith('.py'):
            filename = filename + '.py'

        # Security: reject path traversal
        if ".." in filename or filename.startswith("/") or filename.startswith("\\"):
            return "Error: Invalid filename. Path traversal is not allowed."

        if ":" in filename:
            return "Error: Invalid filename. Absolute paths are not allowed."

        # Create output directory if needed
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        # Add header comment if description provided
        if description:
            header = f'"""\n{description}\n\nGenerated by Jarvis\n"""\n\n'
            code = header + code

        # Write file
        filepath = OUTPUT_DIR / filename
        filepath.write_text(code, encoding="utf-8")

        logging.info(f"Saved script: {filepath}")
        return f"Saved script '{filename}' ({len(code)} characters)\nLocation: {filepath}"

    except Exception as e:
        logging.error(f"Error saving script '{filename}': {e}")
        return f"Error saving script: {e}"


# ---------------------------------------------------------------------------
# Course Generation Tools
# ---------------------------------------------------------------------------

async def _call_openai_chat(prompt: str, system_prompt: str = "", max_tokens: int = 2000) -> str:
    """Helper to call OpenAI chat completion."""
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.7,
        )

        return response.choices[0].message.content or ""

    except Exception as e:
        logging.error(f"OpenAI API error: {e}")
        raise


@function_tool
async def generate_course_outline(
    context: RunContext,  # type: ignore
    topic: str,
    num_lessons: int = 5,
    audience: str = "beginners"
) -> str:
    """
    Generate a structured course outline for a given topic.
    Saves the outline as a markdown file in the output directory.
    """
    try:
        system_prompt = """You are an expert instructional designer. Create well-structured,
        engaging course outlines that follow best practices in adult learning."""

        prompt = f"""Create a detailed course outline for: "{topic}"

Target audience: {audience}
Number of lessons: {num_lessons}

Include for each lesson:
- Lesson title
- Learning objectives (2-3 per lesson)
- Key topics covered
- Estimated duration

Also include:
- Course overview/description
- Prerequisites (if any)
- Course outcomes

Format as clean Markdown."""

        outline = await _call_openai_chat(prompt, system_prompt, max_tokens=2000)

        # Save to file
        filename = f"course_outline_{topic.lower().replace(' ', '_')[:30]}.md"
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        filepath = OUTPUT_DIR / filename
        filepath.write_text(outline, encoding="utf-8")

        logging.info(f"Generated course outline: {filename}")
        return f"Course outline generated!\n\nSaved to: {filename}\n\n{outline[:500]}..."

    except Exception as e:
        logging.error(f"Error generating course outline: {e}")
        return f"Error generating course outline: {e}"


@function_tool
async def generate_lesson(
    context: RunContext,  # type: ignore
    topic: str,
    lesson_title: str,
    style: str = "conversational"
) -> str:
    """
    Generate a complete lesson with objectives, content, takeaways, and exercises.
    Style can be: conversational, academic, or practical.
    """
    try:
        system_prompt = f"""You are an expert educator creating engaging lesson content.
        Write in a {style} style that keeps learners engaged.
        Use examples, analogies, and clear explanations."""

        prompt = f"""Create a complete lesson for the topic: "{topic}"
Lesson title: "{lesson_title}"

Include these sections:

## Learning Objectives
(3-4 specific, measurable objectives)

## Introduction
(Hook the learner, explain why this matters)

## Main Content
(Teach the material with clear explanations, examples, and analogies)

## Key Takeaways
(Bullet points summarizing the most important points)

## Practice Exercises
(3-5 exercises ranging from easy to challenging)

## Additional Resources
(Suggested further reading or practice)

Format as clean Markdown with proper headings."""

        lesson = await _call_openai_chat(prompt, system_prompt, max_tokens=3000)

        # Save to file
        safe_title = lesson_title.lower().replace(' ', '_')[:30]
        filename = f"lesson_{safe_title}.md"
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        filepath = OUTPUT_DIR / filename
        filepath.write_text(lesson, encoding="utf-8")

        # Extract objectives for summary
        lines = lesson.split('\n')
        summary_lines = [l for l in lines[:20] if l.strip()]

        logging.info(f"Generated lesson: {filename}")
        return f"Lesson generated!\n\nSaved to: {filename}\n\nPreview:\n{chr(10).join(summary_lines[:10])}..."

    except Exception as e:
        logging.error(f"Error generating lesson: {e}")
        return f"Error generating lesson: {e}"


@function_tool
async def generate_workbook(
    context: RunContext,  # type: ignore
    topic: str,
    num_exercises: int = 10
) -> str:
    """
    Generate a student workbook with exercises, fill-in-the-blank, and reflection questions.
    """
    try:
        system_prompt = """You are an expert educator creating student workbooks.
        Create engaging, varied exercises that reinforce learning."""

        prompt = f"""Create a student workbook for: "{topic}"

Include {num_exercises} total items with a mix of:

## Multiple Choice Questions
(3-4 questions with 4 options each, mark correct answer)

## Fill in the Blank
(3-4 sentences with key terms blanked out)

## Short Answer Questions
(2-3 questions requiring brief explanations)

## Practical Exercises
(2-3 hands-on activities or coding challenges if applicable)

## Reflection Questions
(2-3 deeper thinking questions)

## Answer Key
(Provide answers at the end)

Format as clean Markdown. Make exercises progressively more challenging."""

        workbook = await _call_openai_chat(prompt, system_prompt, max_tokens=3000)

        # Save to file
        filename = f"workbook_{topic.lower().replace(' ', '_')[:30]}.md"
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        filepath = OUTPUT_DIR / filename
        filepath.write_text(workbook, encoding="utf-8")

        logging.info(f"Generated workbook: {filename}")
        return f"Workbook generated with {num_exercises} exercises!\n\nSaved to: {filename}"

    except Exception as e:
        logging.error(f"Error generating workbook: {e}")
        return f"Error generating workbook: {e}"


# ---------------------------------------------------------------------------
# Image Generation Tool (Stable Diffusion)
# ---------------------------------------------------------------------------

# TODO: Add your Stable Diffusion API configuration here
# STABLE_DIFFUSION_API_KEY = os.getenv("STABLE_DIFFUSION_API_KEY")
# STABLE_DIFFUSION_API_URL = os.getenv("STABLE_DIFFUSION_API_URL", "https://api.stability.ai/v1/generation/stable-diffusion-xl-1024-v1-0/text-to-image")


@function_tool
async def generate_image(
    context: RunContext,  # type: ignore
    prompt: str,
    style: str = "professional"
) -> str:
    """
    Generate an image using Stable Diffusion.
    Style can be: professional, artistic, photorealistic, cartoon, anime.
    """
    try:
        import urllib.request
        import uuid

        # Enhance prompt with style
        style_modifiers = {
            "professional": "Professional, clean, modern design. High quality, 4k.",
            "artistic": "Artistic, creative, visually striking. Fine art style, masterpiece.",
            "photorealistic": "Photorealistic, highly detailed, like a photograph, 8k uhd.",
            "cartoon": "Cartoon style, colorful, fun and engaging illustration.",
            "anime": "Anime style, vibrant colors, detailed, studio quality.",
        }

        style_mod = style_modifiers.get(style.lower(), style_modifiers["professional"])
        enhanced_prompt = f"{prompt}, {style_mod}"

        # TODO: Replace this placeholder with actual Stable Diffusion API call
        # =====================================================================
        # Example structure for Stability AI API:
        #
        # import aiohttp
        #
        # api_key = os.getenv("STABLE_DIFFUSION_API_KEY")
        # if not api_key:
        #     return "Stable Diffusion API key not configured. Set STABLE_DIFFUSION_API_KEY in .env"
        #
        # async with aiohttp.ClientSession() as session:
        #     async with session.post(
        #         "https://api.stability.ai/v1/generation/stable-diffusion-xl-1024-v1-0/text-to-image",
        #         headers={
        #             "Authorization": f"Bearer {api_key}",
        #             "Content-Type": "application/json",
        #         },
        #         json={
        #             "text_prompts": [{"text": enhanced_prompt, "weight": 1}],
        #             "cfg_scale": 7,
        #             "height": 1024,
        #             "width": 1024,
        #             "samples": 1,
        #             "steps": 30,
        #         }
        #     ) as response:
        #         if response.status == 200:
        #             data = await response.json()
        #             image_data = data["artifacts"][0]["base64"]
        #             # Save image...
        # =====================================================================

        # Placeholder response until API is configured
        api_key = os.getenv("STABLE_DIFFUSION_API_KEY")
        if not api_key:
            return (
                "Stable Diffusion is not configured yet.\n\n"
                "To set up:\n"
                "1. Get an API key from stability.ai or your preferred SD provider\n"
                "2. Add STABLE_DIFFUSION_API_KEY to your .env file\n"
                "3. Update the generate_image function in tools.py with your API call\n\n"
                f"Prompt ready: {enhanced_prompt[:100]}..."
            )

        # Once configured, the actual API call goes here
        # For now, return placeholder
        return f"Stable Diffusion API configured but implementation pending.\nPrompt: {enhanced_prompt[:100]}..."

    except Exception as e:
        logging.error(f"Error generating image: {e}")
        return f"Error generating image: {e}"
