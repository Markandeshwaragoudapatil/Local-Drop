# LocalDrop

LocalDrop is a small, dependency-free file-sharing website for your local network. Run it on your computer, open it from a phone or another computer on the same Wi-Fi, then preview or download files through a browser.

- No cloud upload: files are served directly from your computer.
- No third-party Python packages required.
- Responsive interface with file search.
- Preview support for common images, PDFs, text files, and media formats.
- Other file types are offered as downloads.
- Upload files from a phone or another device into the host computer's `ShareFiles` folder.
- Delete individual shared files from the browser after confirmation.
- Stop the server from the browser using the **Stop server** button.
- Shared files are restricted to one dedicated folder inside the project by default.

> **Security:** LocalDrop has no login or user authentication. Anyone who can reach the server may upload, download, delete shared files, or stop the server. Use it only on a trusted local network. Do not share sensitive files or expose the server directly to the public internet.

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

The server creates the `ShareFiles` folder inside the project if it does not already exist.

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

### 5. Open LocalDrop on your phone

1. Connect your computer and phone to the same Wi-Fi network.
2. Find your computer's local IPv4 address.
   - **Windows:** run `ipconfig` in PowerShell and find `IPv4 Address` under the active Wi-Fi adapter.
   - **macOS/Linux:** use your system's network settings or network-interface tools.
3. On your phone, open `http://<COMPUTER-IP>:8000`, replacing `<COMPUTER-IP>` with your computer's actual IPv4 address.

For example:

```text
http://192.168.1.25:8000
```

The example IP is only illustrative; use the address assigned to your computer.

If your phone cannot connect:

- Confirm both devices are connected to the same Wi-Fi.
- Make sure the server is still running.
- Use the computer's active Wi-Fi IPv4 address, not `127.0.0.1` or an unrelated virtual-adapter address.
- Check your firewall settings. Only allow incoming connections on a trusted private network if appropriate.
- School, office, guest, and public Wi-Fi networks may block communication between connected devices through client isolation.

## Using LocalDrop

- **View** opens supported file types in the browser where possible.
- **Download** downloads the file to the device you are using.
- **Delete** permanently removes the selected file from the shared folder after confirmation.
- Use the search field to filter the list.
- Use **Add files to LocalDrop** to upload one or more files from the device you're currently using to the computer's `ShareFiles` folder. Uploads are limited to 100 MiB per request; existing files are not overwritten (a numbered filename is used instead).
- Reload the page to refresh the available files.

## Stop and restart LocalDrop

Click **Stop server** at the bottom of the web page and confirm. This shuts down LocalDrop for all connected devices. If you cannot use the browser, press `Ctrl+C` in the terminal running the server.

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
7. **Delete** sends a URL-encoded `POST` request to `/delete`. The server validates that the selected file is inside the shared directory before removing it.
8. **Stop server** sends a confirmed `POST` request to `/shutdown`; the server replies and then shuts down cleanly.

The server validates requested paths to help prevent access outside the configured shared directory. This is useful protection, but it does not replace authentication or a security review.

## Limitations

- No login or user authentication.
- Anyone who can reach the server may upload files to, download files from, delete files in, or stop the server.
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
