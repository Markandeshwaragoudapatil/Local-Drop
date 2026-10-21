"""LocalDrop: share selected files with devices on your local network."""

from __future__ import annotations

import html
import mimetypes
import os
import re
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

# Only these types may be previewed inline. Other types download as attachments.
PREVIEW_TYPES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp",
    ".pdf", ".txt", ".md", ".csv", ".log",
    ".mp4", ".webm", ".ogg", ".mp3", ".wav", ".opus",
}


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


def build_file_rows() -> tuple[int, str]:
    """Build escaped HTML rows for the files currently in the shared directory."""
    files = sorted(
        (path for path in SHARE_DIR.rglob("*") if path.is_file()),
        key=lambda path: str(path.relative_to(SHARE_DIR)).lower(),
    )
    rows: list[str] = []

    image_types = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
    document_types = {".pdf", ".txt", ".md", ".csv"}

    for path in files:
        relative = path.relative_to(SHARE_DIR).as_posix()
        escaped_name = html.escape(relative)
        search_name = html.escape(relative.lower(), quote=True)
        encoded_path = quote(relative, safe="")
        suffix = path.suffix.lower()
        icon = "🖼️" if suffix in image_types else ("📄" if suffix in document_types else "📦")

        rows.append(
            f'<article class="file" data-name="{search_name}">'
            f'<div class="fileicon" aria-hidden="true">{icon}</div>'
            f'<div class="meta"><div class="name">{escaped_name}</div>'
            f'<div class="sub">{human_size(path.stat().st_size)}</div></div>'
            f'<div class="actions">'
            f'<a class="btn" href="/view?file={encoded_path}" target="_blank" rel="noopener">View</a>'
            f'<a class="btn primary" href="/download?file={encoded_path}">Download</a>'
            f"</div></article>"
        )

    if not rows:
        content = (
            '<div class="empty">No files yet.<br>'
            "Copy files into your shared folder, then refresh this page.</div>"
        )
    else:
        content = "\n".join(rows)
    return len(files), content


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

    server_version = "LocalDrop/1.1"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if parsed.path in ("/", "/index.html"):
            self.serve_index()
        elif parsed.path in ("/view", "/download"):
            self.serve_file(query.get("file", [""])[0], parsed.path == "/view")
        else:
            self.send_error(404, "Not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/upload":
            self.send_error(404, "Not found")
            return

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

        message = f"Uploaded {saved_count} file(s) successfully."
        self.send_response(303)
        self.send_header("Location", "/?message=" + quote(message))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def serve_index(self) -> None:
        count, file_rows = build_file_rows()
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
            .replace("{{MESSAGE}}", safe_message)
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
    print(f"Shared folder: {SHARE_DIR}")
    print(f"On this computer: http://localhost:{PORT}")
    print(f"On another device on the same Wi-Fi: http://<LAPTOP-IPv4>:{PORT}")
    print("Copy files into the shared folder to make them available.")
    print("Press Ctrl+C to stop. Do not expose this server directly to the public internet.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping LocalDrop...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
