# LocalDrop

**LocalDrop** is a small, dependency-free file-sharing website for your local network. Run it on your computer, open the page from a phone or another computer on the same Wi-Fi, then preview or download files.

- No cloud upload: files are served directly from your computer.
- No third-party Python packages required.
- Responsive interface with file search.
- Preview support for common images, PDFs, text files, and media formats.
- Other file types are offered as downloads.
- Shared files are restricted to one dedicated folder.

> **Security:** This is a simple local-network utility, not a hardened internet-facing file server. Anyone who can reach the server may be able to access files in the shared folder. Do not put sensitive files in that folder, do not expose the server directly to the public internet, and stop it when finished.

## Requirements

- Windows, macOS, or Linux
- Python 3.10 or newer (Python 3.10+ is recommended)

No `pip install` step is needed; LocalDrop uses Python's standard library.

## Quick start

### 1. Get the code

Clone the repository:

```powershell
git clone https://github.com/Markandeshwaragoudapatil/Local-Drop.git
cd localdrop
```

Or use **Code → Download ZIP** on GitHub and extract the archive.

### 2. Start the server

From the repository root:

```powershell
python localdrop/server.py
```

On some Windows installations, this may be:

```powershell
py localdrop/server.py
```

The first run creates a `ShareFiles` folder in your user home directory, usually:

```text
C:\Users\YOUR-NAME\ShareFiles
```

The terminal prints the folder location and the local URL.

### 3. Add files

Copy the files you want to share into the displayed `ShareFiles` folder. You can create subfolders too. Refresh the LocalDrop page to update the list.

Example:

```text
ShareFiles/
├── assignment.pdf
├── photo.jpg
└── notes/
    └── lecture-notes.txt
```

The `ShareFiles` folder is outside the Git repository by default, so your personal files are not accidentally committed when you push the project.

### 4. Open LocalDrop on your computer

Visit:

```text
http://localhost:8000
```

### 5. Open it on your phone

1. Connect the phone and computer to the same Wi-Fi network.
2. Find the computer's local IPv4 address.
   - **Windows:** run `ipconfig` in PowerShell and look under the active Wi-Fi adapter for `IPv4 Address`.
   - **macOS/Linux:** use your system's network settings or an appropriate network-interface command.
3. On your phone, open `http://<COMPUTER-IP>:8000`, replacing `<COMPUTER-IP>` with that address.

For example:

```text
http://192.168.1.25:8000
```

Your actual address will differ. Do not copy the example IP blindly.

If the phone cannot connect:
- Confirm both devices are on the same Wi-Fi.
- Check that the server is still running.
- Check that you used the computer's active Wi-Fi IPv4 address, not `127.0.0.1` or an unrelated virtual-adapter address.
- Check Windows Firewall. Only allow access on a trusted private network if you understand and intend to allow it.
- Some school, office, guest, and public Wi-Fi networks block communication between connected devices. Client isolation may prevent LocalDrop from working even when both devices show the same Wi-Fi name.

## Using LocalDrop

- **View** opens supported file types in the browser where possible.
- **Download** downloads the file to the device you're using.
- Use the search box to filter the visible file list.
- The list is refreshed when you reload the page.
- Stop the server with `Ctrl+C` in the terminal.

Browser support determines whether a file can be previewed. For example, a PDF may open in the browser, while a DOCX file will generally download.

## Configuration

LocalDrop supports environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `LOCALDROP_HOST` | `0.0.0.0` | Network interface to bind to |
| `LOCALDROP_PORT` | `8000` | TCP port |
| `LOCALDROP_SHARE_DIR` | `~/ShareFiles` | Directory to expose |

PowerShell example using a custom port:

```powershell
$env:LOCALDROP_PORT = "8080"
python localdrop/server.py
```

Then use port `8080` in the URL. If you set a custom shared directory, use an absolute path:

```powershell
$env:LOCALDROP_SHARE_DIR = "D:\FilesToShare"
python localdrop/server.py
```

These environment variables apply to that PowerShell session. Open a new terminal or clear them if you want to return to the defaults.

## How it works

1. Python's `ThreadingHTTPServer` listens for HTTP requests.
2. The web page lists files found in the configured shared directory.
3. **View** requests a file through `/view`; supported types are sent inline for browser preview.
4. **Download** requests a file through `/download`; it is sent as an attachment.
5. Files are streamed from the computer to the requesting browser over the local network. They are not uploaded to a cloud service.

The server validates requested paths to help prevent access outside the configured shared directory. This is useful protection, but it does not replace authentication or a security review.

## Limitations

- No login or user authentication.
- Anyone who can reach the server may access files in the shared directory.
- Intended for trusted local networks only.
- No upload-from-phone feature; this project sends files from the host computer to clients.
- Large files are streamed, but transfer speed depends on the network and devices.

## Project structure

```text
localdrop/
├── .gitignore
├── LICENSE
├── README.md
├── ShareFiles/
│   └── .gitkeep
└── localdrop/
    ├── server.py
    └── templates/
        └── index.html
```

## Contributing

Issues and pull requests are welcome. For a feature request or bug report, include your operating system, Python version, steps to reproduce, and any relevant error message. Do not attach private files.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
