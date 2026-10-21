# LocalDrop

LocalDrop is a small, dependency-free, PIN-protected file-sharing website for your local network. Run it on your computer, enter the startup PIN on your phone or another device, then preview, upload, download, and manage files in a browser. Devices can connect through a Wi-Fi router or mobile hotspot. Internet access and an active mobile-data plan are not required; local network connectivity is enough.

- No cloud upload: files are served directly from your computer.
- No third-party Python packages required.
- Responsive interface with file search.
- Preview support for common images, PDFs, text files, and media formats.
- Other file types are offered as downloads.
- Upload files from a phone or another device into the host computer's `ShareFiles` folder.
- Delete individual shared files from the browser after confirmation.
- Stop the server from the browser using the **Stop server** button.
- Shared files are restricted to one dedicated folder inside the project by default.

> **Security:** LocalDrop uses a random four-digit startup PIN and in-memory browser sessions to deter casual access. Five incorrect PIN attempts from the same client IP trigger a 60-second cooldown. The PIN is required again to stop the server. However, LocalDrop uses plain HTTP, not HTTPS, so traffic on the local network is not encrypted and the PIN/session cookie could be observed by someone monitoring that network. Use it only on a trusted local network and do not expose it to the public internet.

## Requirements

- Windows, macOS, or Linux
- Python 3.10 or newer recommended

No `pip install` step is required. LocalDrop uses Python's standard library.

## Quick start

### 1. Download the project

Clone the repository:

```powershell
git clone https://github.com/Markandeshwaragoudapatil/Local-Drop.git
cd Local-Drop
```

Or choose **Code → Download ZIP** on GitHub and extract the archive.

### 2. Start the server

From the repository root:

```powershell
python localdrop/server.py
```

On some Windows installations, use:

```powershell
py localdrop/server.py
```

The server creates the `ShareFiles` folder inside the project if it does not already exist. Each time it starts, it prints a new random four-digit **Access PIN** in the terminal. Keep the terminal open long enough to read the PIN; you'll need it to sign in from a browser. The PIN changes after every restart.

### 3. Add files

Copy files you want to share into the project's `ShareFiles` folder, or use the **Add files to LocalDrop** form on the website to upload files from your phone or another device to the computer. You can also create subfolders manually. Refresh the page after adding files.

```text
Local-Drop/
├── ShareFiles/
│   ├── assignment.pdf
│   ├── photo.jpg
│   └── notes/
│       └── lecture-notes.txt
├── localdrop/
│   ├── server.py
│   └── templates/
│       └── index.html
├── .gitignore
├── LICENSE
└── README.md
```

**Important:** `.gitignore` should ignore files placed in `ShareFiles/`. Your shared documents, photos, and other personal files should not be committed to Git.

### 4. Open LocalDrop on your computer

Visit:

```text
http://localhost:8000
```

Enter the four-digit **Access PIN** displayed in the terminal. The page does not show the file list until you sign in. After a successful login, the browser receives a session cookie and can use the site without entering the PIN again for each file. Sessions are stored only in memory and become invalid after a server restart; they expire after 12 hours.

### 5. Open LocalDrop on your phone

1. Connect your computer and phone to the same **local network**. You can connect both to the same Wi-Fi router, or turn on your phone's hotspot and connect your computer to it.
2. Find your computer's local IPv4 address.
   - **Windows:** run `ipconfig` in PowerShell and find `IPv4 Address` under the active Wi-Fi adapter. Use the adapter that connects to the router or phone hotspot.
   - **macOS/Linux:** use your system's network settings or network-interface tools.
3. On your phone, open `http://<COMPUTER-IP>:8000`, replacing `<COMPUTER-IP>` with your computer's actual IPv4 address.

**Internet is not required.** In hotspot mode, the phone and computer can communicate locally even when the SIM has no active data package, as long as the hotspot allows connected devices to communicate with each other.

For example:

```text
http://192.168.1.25:8000
```

The example IP is only illustrative; use the address assigned to your computer.

If your phone cannot connect:

- Confirm both devices are connected to the same local network. A phone hotspot is fine; an internet connection or active mobile-data plan is not required.
- Make sure the server is still running.
- Use the computer's IPv4 address for the active network adapter connected to that local network, not `127.0.0.1` or an unrelated virtual-adapter address.
- Check your firewall settings. Only allow incoming connections on a trusted private network if appropriate.
- School, office, guest, and public Wi-Fi networks may block communication between connected devices through client isolation.

## Using LocalDrop

- **View** opens supported file types in the browser where possible.
- **Download** downloads the file to the device you are using.
- **Delete** permanently removes the selected file from the shared folder after confirmation.
- The PIN is required once per browser session; normal file preview, upload, download, and deletion do not ask for it repeatedly.
- Click **Stop server** and enter the same four-digit PIN again to stop LocalDrop. The server redirects the browser home before shutting down.
- Use the search field to filter the list.
- Use **Add files to LocalDrop** to upload one or more files from the device you're currently using to the computer's `ShareFiles` folder. Uploads are limited to 100 MiB per request; existing files are not overwritten (a numbered filename is used instead).
- Reload the page to refresh the available files.

## Stop and restart LocalDrop

Click **Stop server** at the bottom of the web page and confirm. LocalDrop redirects the browser back to the home page, then shuts down a moment later so refreshing the page will not repeat the stop request. This disconnects all connected devices. If you cannot use the browser, press `Ctrl+C` in the terminal running the server.

To start LocalDrop again, run:

```powershell
python localdrop/server.py
```

Whether a file can be previewed depends on browser support. PDFs and images often open directly; formats such as DOCX generally download instead.

## Configuration

LocalDrop supports these environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `LOCALDROP_HOST` | `0.0.0.0` | Network interface to bind to |
| `LOCALDROP_PORT` | `8000` | TCP port |
| `LOCALDROP_SHARE_DIR` | `<project-root>/ShareFiles` | Directory to share |

For example, to use port `8080` in PowerShell:

```powershell
$env:LOCALDROP_PORT = "8080"
python localdrop/server.py
```

Then use port `8080` in the browser URL.

To share a different directory, set an absolute path:

```powershell
$env:LOCALDROP_SHARE_DIR = "D:\FilesToShare"
python localdrop/server.py
```

Environment variables set this way apply to the current PowerShell session. Open a new terminal or clear the variables to return to the defaults.

## How it works

1. Python's `ThreadingHTTPServer` listens for HTTP requests.
2. The home page lists files in the configured shared directory.
3. **View** requests a file through `/view`; supported file types are sent inline for browser preview.
4. **Download** requests a file through `/download`; files are sent as attachments.
5. File contents are streamed from your computer to the requesting browser over the local network. They are not uploaded to a cloud service.
6. Uploads use an HTTP `POST` multipart form request and save files into the configured shared directory.
7. The browser submits the PIN once to `/login`. The server validates it and sets a random, HttpOnly session cookie; protected requests validate the session in the background.
8. **Delete** sends a URL-encoded `POST` request to `/delete`. The server validates that the selected file is inside the shared directory before removing it.
9. **Stop server** requires a valid browser session and the startup PIN again, then redirects home and shuts down cleanly.

The server validates requested paths to help prevent access outside the configured shared directory. All file-related routes require an active server-side session. This is useful protection, but it does not replace HTTPS or a security review.

## Limitations

- The four-digit PIN is basic protection against casual access, not strong authentication.
- HTTP traffic is unencrypted; do not use LocalDrop on an untrusted network.
- Anyone who has authenticated may upload, download, or delete files. Shutting down also requires re-entering the startup PIN.
- Intended for trusted local networks only.
- Uploads are limited to 100 MiB per request. Large batches that exceed this limit must be split into smaller uploads.
- Transfer speed depends on your network and devices.

## Project structure

```text
Local-Drop/
├── .gitignore
├── LICENSE
├── README.md
├── ShareFiles/              # Created automatically when the server starts
└── localdrop/
    ├── server.py
    └── templates/
        └── index.html
```

## Contributing

Issues and pull requests are welcome. For a bug report, include your operating system, Python version, steps to reproduce, and relevant error messages. Do not attach private files.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
