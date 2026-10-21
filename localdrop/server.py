"""LocalDrop: share selected files with devices on your local network."""

from __future__ import annotations

import hashlib
import html
import mimetypes
import os
import re
import secrets
import threading
import time
from http.cookies import CookieError, SimpleCookie
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

HOST = os.environ.get("LOCALDROP_HOST", "0.0.0.0")
PORT = int(os.environ.get("LOCALDROP_PORT", "8000"))
SHARE_DIR = Path(
    os.environ.get(
        "LOCALDROP_SHARE_DIR",
        str(Path(__file__).resolve().parent.parent / "ShareFiles"),
    )
).expanduser().resolve()

TEMPLATE_PATH = Path(__file__).parent / "templates" / "index.html"
MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100 MiB per request

# PIN/session state is held in memory and resets whenever LocalDrop restarts.
SERVER_PIN = f"{secrets.randbelow(10_000):04d}"
SESSION_TTL_SECONDS = 12 * 60 * 60
SESSIONS: dict[str, float] = {}
SESSION_LOCK = threading.Lock()

# Five incorrect PIN attempts from one client IP trigger a 60-second cooldown.
MAX_PIN_FAILURES = 5
PIN_COOLDOWN_SECONDS = 60
PIN_FAILURES: dict[str, tuple[int, float]] = {}
PIN_FAILURES_LOCK = threading.Lock()

LOGIN_TEMPLATE_PATH = Path(__file__).parent / "templates" / "login.html"

# Only these types may be previewed inline. Other types download as attachments.
PREVIEW_TYPES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp",
    ".pdf", ".txt", ".md", ".csv", ".log",
    ".mp4", ".webm", ".ogg", ".mp3", ".wav", ".opus",
}


def create_session() -> str:
    """Create a random in-memory session token with a limited lifetime."""
    token = secrets.token_urlsafe(32)
    now = time.monotonic()
    with SESSION_LOCK:
        for expired_token, expiry in list(SESSIONS.items()):
            if expiry <= now:
                SESSIONS.pop(expired_token, None)
        SESSIONS[token] = now + SESSION_TTL_SECONDS
    return token


def is_valid_session(token: str) -> bool:
    """Check a session token and discard it if expired."""
    if not token:
        return False
    now = time.monotonic()
    with SESSION_LOCK:
        expires_at = SESSIONS.get(token)
        if expires_at is None:
            return False
        if expires_at <= now:
            SESSIONS.pop(token, None)
            return False
        return True


def get_session_token(cookie_header: str) -> str:
    """Extract the LocalDrop session cookie safely."""
    cookie = SimpleCookie()
    try:
        cookie.load(cookie_header)
    except CookieError:
        return ""
    morsel = cookie.get("localdrop_session")
    return morsel.value if morsel else ""


def pin_cooldown_remaining(client_ip: str) -> int:
    """Return remaining PIN lockout seconds for a client IP, if any."""
    now = time.monotonic()
    with PIN_FAILURES_LOCK:
        record = PIN_FAILURES.get(client_ip)
        if record is None:
            return 0
        failures, blocked_until = record
        if blocked_until > now:
            return max(1, int(blocked_until - now + 0.999))
        if blocked_until:
            PIN_FAILURES.pop(client_ip, None)
        return 0


def record_pin_failure(client_ip: str) -> int:
    """Record a wrong PIN and start a cooldown after too many failures."""
    now = time.monotonic()
    with PIN_FAILURES_LOCK:
        failures, blocked_until = PIN_FAILURES.get(client_ip, (0, 0.0))
        if blocked_until > now:
            return max(1, int(blocked_until - now + 0.999))
        failures += 1
        if failures >= MAX_PIN_FAILURES:
            PIN_FAILURES[client_ip] = (failures, now + PIN_COOLDOWN_SECONDS)
            return PIN_COOLDOWN_SECONDS
        PIN_FAILURES[client_ip] = (failures, 0.0)
        return 0


def clear_pin_failures(client_ip: str) -> None:
    """Clear a client's failed-attempt counter after a correct PIN."""
    with PIN_FAILURES_LOCK:
        PIN_FAILURES.pop(client_ip, None)


def human_size(size: int) -> str:
    """Return a human-readable file size."""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def resolve_shared_file(relative_path: str) -> Path | None:
    """Resolve a requested path and reject paths outside the shared directory."""
    try:
        candidate = (SHARE_DIR / relative_path).resolve(strict=True)
        candidate.relative_to(SHARE_DIR)
        if candidate.is_file():
            return candidate
    except (OSError, ValueError):
        return None
    return None


def build_file_rows() -> tuple[int, str, str]:
    """Build escaped HTML rows for the files currently in the shared directory."""
    files = sorted(
        (path for path in SHARE_DIR.rglob("*") if path.is_file()),
        key=lambda path: str(path.relative_to(SHARE_DIR)).lower(),
    )
    rows: list[str] = []
    file_metadata: list[tuple[str, int, int]] = []

    image_types = {
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".heic", ".avif",
    }
    video_types = {
        ".mp4", ".webm", ".mov", ".m4v", ".avi", ".mkv", ".mpeg", ".mpg", ".3gp",
    }
    audio_types = {
        ".mp3", ".wav", ".ogg", ".opus", ".m4a", ".aac", ".flac", ".wma",
    }

    # Simple inline SVGs stay sharp on high-resolution screens and need no image assets.
    icon_svgs = {
        "image": (
            '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" '
            'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
            'stroke-linejoin="round" aria-hidden="true">'
            '<rect x="3" y="4" width="18" height="16" rx="2"/>'
            '<circle cx="8.5" cy="9" r="1.5"/>'
            '<path d="m4 17 5-5 4 4 3-3 4 4"/></svg>'
        ),
        "pdf": (
            '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" '
            'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
            'stroke-linejoin="round" aria-hidden="true">'
            '<path d="M6 2.8h8l4 4V21H6z"/>'
            '<path d="M14 3v5h5"/>'
            '<path d="M8 12h8M8 15h3"/>'
            '<text x="8" y="19" font-size="4.5" font-weight="800" fill="currentColor" '
            'stroke="none">PDF</text></svg>'
        ),
        "video": (
            '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" '
            'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
            'stroke-linejoin="round" aria-hidden="true">'
            '<rect x="2.8" y="5" width="18.4" height="14" rx="2.5"/>'
            '<path d="m10 9 5 3-5 3z" fill="currentColor" stroke="none"/></svg>'
        ),
        "audio": (
            '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" '
            'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
            'stroke-linejoin="round" aria-hidden="true">'
            '<path d="M9 18V5l11-2v13"/>'
            '<circle cx="6" cy="18" r="3"/>'
            '<circle cx="17" cy="16" r="3"/>'
            '<path d="M9 8l11-2"/></svg>'
        ),
        "file": (
            '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" '
            'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
            'stroke-linejoin="round" aria-hidden="true">'
            '<path d="M6 2.8h8l4 4V21H6z"/>'
            '<path d="M14 3v5h5M9 12h6M9 16h6"/></svg>'
        ),
    }

    for path in files:
        try:
            stat_result = path.stat()
        except OSError:
            # A file might be deleted while the list is being built.
            continue

        if not path.is_file():
            continue

        relative = path.relative_to(SHARE_DIR).as_posix()
        file_metadata.append((relative, stat_result.st_size, stat_result.st_mtime_ns))
        escaped_name = html.escape(relative)
        search_name = html.escape(relative.lower(), quote=True)
        encoded_path = quote(relative, safe="")
        suffix = path.suffix.lower()

        if suffix in image_types:
            icon_type = "image"
        elif suffix == ".pdf":
            icon_type = "pdf"
        elif suffix in video_types:
            icon_type = "video"
        elif suffix in audio_types:
            icon_type = "audio"
        else:
            icon_type = "file"

        icon_svg = icon_svgs[icon_type]

        rows.append(
            f'<article class="file" data-name="{search_name}">'
            f'<div class="fileicon fileicon-{icon_type}" aria-hidden="true">{icon_svg}</div>'
            f'<div class="meta"><div class="name">{escaped_name}</div>'
            f'<div class="sub">{human_size(stat_result.st_size)}</div></div>'
            f'<div class="actions">'
            f'<a class="btn" href="/view?file={encoded_path}" target="_blank" rel="noopener">View</a>'
            f'<a class="btn primary" href="/download?file={encoded_path}">Download</a>'
            f'<form class="inline-form" action="/delete" method="post" '
            f'onsubmit="return confirm(\'Permanently delete this file?\')">'
            f'<input type="hidden" name="file" value="{html.escape(relative, quote=True)}">'
            f'<button class="btn danger" type="submit">Delete</button>'
            f'</form>'
            f"</div></article>"
        )

    if not rows:
        content = (
            '<div class="empty">No files yet.<br>'
            "Copy files into your shared folder, then refresh this page.</div>"
        )
    else:
        content = "\n".join(rows)
    version = hash_file_metadata(file_metadata)
    return len(rows), content, version


def hash_file_metadata(file_metadata: list[tuple[str, int, int]]) -> str:
    """Return a stable version token for the names, sizes, and modification times."""
    records = sorted(file_metadata, key=lambda item: item[0].lower())
    payload = "\\n".join(
        f"{relative_path}\\0{size}\\0{modified_ns}"
        for relative_path, size, modified_ns in records
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def current_files_version() -> str:
    """Compute the current shared-folder state without reading any file contents."""
    file_metadata: list[tuple[str, int, int]] = []
    for path in SHARE_DIR.rglob("*"):
        try:
            if not path.is_file():
                continue
            stat_result = path.stat()
            relative = path.relative_to(SHARE_DIR).as_posix()
        except OSError:
            continue
        file_metadata.append((relative, stat_result.st_size, stat_result.st_mtime_ns))
    return hash_file_metadata(file_metadata)


def unique_destination(filename: str) -> Path:
    """Return a safe destination path without overwriting an existing file."""
    # Remove any path components supplied by the client and normalize the name.
    name = Path(filename.replace("\\", "/")).name.strip()
    name = re.sub(r'[\x00-\x1f<>:"/\\\\|?*]', "_", name).strip(" .")
    if not name or name in {".", ".."}:
        name = "uploaded-file"

    destination = SHARE_DIR / name
    if not destination.exists():
        return destination

    stem, suffix = Path(name).stem, Path(name).suffix
    counter = 1
    while True:
        candidate = SHARE_DIR / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def parse_uploaded_files(content_type: str, body: bytes) -> list[tuple[str, bytes]]:
    """Parse multipart form data using Python's standard-library email parser."""
    message_bytes = (
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("ascii")
        + body
    )
    message = BytesParser(policy=policy.default).parsebytes(message_bytes)
    if not message.is_multipart():
        raise ValueError("Expected a multipart file upload.")

    uploaded: list[tuple[str, bytes]] = []
    for part in message.iter_parts():
        filename = part.get_filename()
        if not filename:
            continue
        payload = part.get_payload(decode=True) or b""
        uploaded.append((filename, payload))
    return uploaded


class LocalDropHandler(BaseHTTPRequestHandler):
    """Handle the file list, previews, and downloads."""

    server_version = "LocalDrop/1.2"

    def is_authenticated(self) -> bool:
        """Only a current server-side session grants access to LocalDrop."""
        token = get_session_token(self.headers.get("Cookie", ""))
        return is_valid_session(token)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if not self.is_authenticated():
            login_message = query.get("login_message", [""])[0]
            self.serve_login(login_message)
            return


        if parsed.path == "/api/state":
            self.serve_files_state()
        elif parsed.path in ("/", "/index.html"):
            self.serve_index()
        elif parsed.path in ("/view", "/download"):
            self.serve_file(query.get("file", [""])[0], parsed.path == "/view")
        else:
            self.send_error(404, "Not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)

        # The login route is the only POST route open without an existing session.
        if parsed.path == "/login":
            self.handle_login()
            return

        if not self.is_authenticated():
            # Close the connection rather than leave an upload body unread.
            self.send_response(303)
            self.send_header("Location", "/")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.close_connection = True
            self.end_headers()
            return

        if parsed.path == "/upload":
            self.handle_upload()
        elif parsed.path == "/delete":
            self.handle_delete()
        elif parsed.path == "/shutdown":
            self.handle_shutdown()
        else:
            self.send_error(404, "Not found")

    def serve_login(self, message: str = "") -> None:
        """Show only the PIN screen to browsers without an active session."""
        try:
            template = LOGIN_TEMPLATE_PATH.read_text(encoding="utf-8")
        except OSError:
            self.send_error(500, "The LocalDrop login page could not be read.")
            return

        safe_message = html.escape(message)
        message_html = (
            f'<div class="message" role="alert">{safe_message}</div>'
            if safe_message
            else ""
        )
        body = template.replace("{{MESSAGE}}", message_html).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def redirect_to_login(self, message: str) -> None:
        """Use Post/Redirect/Get after a failed login to avoid form resubmission."""
        self.send_response(303)
        self.send_header("Location", "/?login_message=" + quote(message))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def handle_login(self) -> None:
        """Validate the startup PIN and create a session cookie."""
        # Read the bounded form first so even a rate-limited request's body is consumed.
        form = self.read_form_body(max_bytes=4096)
        if form is None:
            return

        client_ip = self.client_address[0]
        remaining = pin_cooldown_remaining(client_ip)
        if remaining:
            self.redirect_to_login(
                f"Too many incorrect attempts. Wait {remaining} seconds and try again."
            )
            return

        supplied_pin = form.get("pin", [""])[0]
        if not secrets.compare_digest(supplied_pin, SERVER_PIN):
            remaining = record_pin_failure(client_ip)
            if remaining:
                message = f"Too many incorrect attempts. Try again in {remaining} seconds."
            else:
                message = "Incorrect PIN. Please try again."
            self.redirect_to_login(message)
            return

        clear_pin_failures(client_ip)
        token = create_session()
        self.send_response(303)
        self.send_header("Location", "/")
        self.send_header(
            "Set-Cookie",
            f"localdrop_session={token}; Path=/; Max-Age={SESSION_TTL_SECONDS}; HttpOnly; SameSite=Strict",
        )
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def read_form_body(self, max_bytes: int = 16 * 1024) -> dict[str, list[str]] | None:
        """Read a bounded URL-encoded form body."""
        content_length = self.headers.get("Content-Length")
        if not content_length:
            self.send_error(411, "Content-Length is required")
            return None
        try:
            length = int(content_length)
        except ValueError:
            self.send_error(400, "Invalid Content-Length")
            return None
        if length < 0 or length > max_bytes:
            self.send_error(413, "Form data is too large")
            return None
        if not self.headers.get("Content-Type", "").lower().startswith(
            "application/x-www-form-urlencoded"
        ):
            self.send_error(400, "Expected URL-encoded form data")
            return None
        try:
            body = self.rfile.read(length).decode("utf-8")
        except UnicodeDecodeError:
            self.send_error(400, "Form data must be UTF-8")
            return None
        return parse_qs(body, keep_blank_values=True)

    def redirect_with_message(self, message: str) -> None:
        """Return the browser to the home page with a short status message."""
        self.send_response(303)
        self.send_header("Location", "/?message=" + quote(message))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def handle_upload(self) -> None:
        content_length = self.headers.get("Content-Length")
        if not content_length:
            self.send_error(411, "Content-Length is required")
            return
        try:
            length = int(content_length)
        except ValueError:
            self.send_error(400, "Invalid Content-Length")
            return
        if length <= 0:
            self.send_error(400, "No upload data received")
            return
        if length > MAX_UPLOAD_BYTES + 1024 * 1024:
            self.send_error(413, "Upload is too large. The limit is 100 MiB per request.")
            return

        content_type = self.headers.get("Content-Type", "")
        if not content_type.lower().startswith("multipart/form-data"):
            self.send_error(400, "Expected a multipart file upload")
            return

        body = self.rfile.read(length)
        try:
            uploads = parse_uploaded_files(content_type, body)
        except (ValueError, UnicodeError):
            self.send_error(400, "Could not parse uploaded files")
            return

        if not uploads:
            self.send_error(400, "Choose at least one file to upload")
            return

        saved_count = 0
        try:
            for filename, data in uploads:
                if not filename:
                    continue
                destination = unique_destination(filename)
                # Write to the destination without replacing existing files.
                with destination.open("xb") as file_handle:
                    file_handle.write(data)
                saved_count += 1
        except OSError:
            self.send_error(500, "Could not save the uploaded file")
            return

        self.redirect_with_message(f"Uploaded {saved_count} file(s) successfully.")

    def handle_delete(self) -> None:
        """Delete only a file that resolves inside the configured shared folder."""
        form = self.read_form_body()
        if form is None:
            return

        relative_path = form.get("file", [""])[0]
        file_path = resolve_shared_file(relative_path)
        if file_path is None:
            self.redirect_with_message("File not found; nothing was deleted.")
            return

        try:
            file_path.unlink()
        except OSError:
            self.send_error(500, "Could not delete the selected file")
            return

        self.redirect_with_message(f"Deleted {file_path.name}.")

    def handle_shutdown(self) -> None:
        """Require the startup PIN again before stopping the server."""
        form = self.read_form_body()
        if form is None:
            return
        if form.get("confirm", [""])[0] != "yes":
            self.send_error(400, "Shutdown was not confirmed")
            return

        client_ip = self.client_address[0]
        remaining = pin_cooldown_remaining(client_ip)
        if remaining:
            self.redirect_with_message(
                f"Too many incorrect PIN attempts. Try again in {remaining} seconds."
            )
            return

        supplied_pin = form.get("pin", [""])[0]
        if not secrets.compare_digest(supplied_pin, SERVER_PIN):
            remaining = record_pin_failure(client_ip)
            if remaining:
                message = f"Incorrect PIN. Shutdown blocked for {remaining} seconds."
            else:
                message = "Incorrect PIN. The server is still running."
            self.redirect_with_message(message)
            return

        clear_pin_failures(client_ip)
        # Redirect first so a refresh cannot repeat the shutdown POST.
        self.redirect_with_message(
            "LocalDrop is stopping. This device will disconnect shortly."
        )

        # Give the browser time to follow the redirect back to "/" before stopping.
        shutdown_timer = threading.Timer(2.0, self.server.shutdown)
        shutdown_timer.daemon = True
        shutdown_timer.start()

    def serve_files_state(self) -> None:
        """Return a compact token that authenticated browsers use to detect changes."""
        version = current_files_version().encode("ascii")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(version)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(version)

    def serve_index(self) -> None:
        count, file_rows, files_version = build_file_rows()
        try:
            template = TEMPLATE_PATH.read_text(encoding="utf-8")
        except OSError:
            self.send_error(500, "The LocalDrop HTML template could not be read.")
            return

        message = parse_qs(urlparse(self.path).query).get("message", [""])[0]
        safe_message = html.escape(message)
        page = (
            template.replace("{{COUNT}}", str(count))
            .replace("{{FILES}}", file_rows)
            .replace("{{FILES_VERSION}}", files_version)
            .replace(
                "{{MESSAGE}}",
                f'<div class="message" role="status">{safe_message}</div>' if safe_message else "",
            )
        )
        body = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def serve_file(self, relative_path: str, view_requested: bool) -> None:
        file_path = resolve_shared_file(relative_path)
        if file_path is None:
            self.send_error(404, "File not found in the shared folder")
            return

        suffix = file_path.suffix.lower()
        preview = view_requested and suffix in PREVIEW_TYPES
        mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        if not preview and suffix not in PREVIEW_TYPES:
            mime_type = "application/octet-stream"

        disposition = "inline" if preview else "attachment"
        # Keep the filename safe for the Content-Disposition header.
        safe_name = file_path.name.replace('"', "").replace("\r", "").replace("\n", "")
        try:
            size = file_path.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Length", str(size))
            self.send_header("Content-Disposition", f'{disposition}; filename="{safe_name}"')
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

            with file_path.open("rb") as file_handle:
                while chunk := file_handle.read(128 * 1024):
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            # The client may cancel a download or close a preview tab.
            pass

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.client_address[0]} - {fmt % args}")


def main() -> None:
    SHARE_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), LocalDropHandler)

    print("\nLocalDrop is running")
    print(f"Access PIN: {SERVER_PIN}")
    print("Enter this PIN in a browser to open LocalDrop. It changes on every restart.")
    print(f"Shared folder: {SHARE_DIR}")
    print(f"On this computer: http://localhost:{PORT}")
    print(f"On another device on the same local network or hotspot: http://<LAPTOP-IPv4>:{PORT}")
    print("Copy files into the shared folder to make them available.")
    print("Press Ctrl+C or use the browser's Stop server button. Do not expose this server directly to the public internet.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping LocalDrop...")
    finally:
        server.server_close()
        print("LocalDrop has stopped.")


if __name__ == "__main__":
    main()
