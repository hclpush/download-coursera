# Coursera Video Downloader

Downloads all video lectures from a Coursera course module using Selenium (for authentication) and yt-dlp (for downloading).

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- Google Chrome installed
- A Coursera account with access to the course

## Setup

```bash
git clone <this-repo>
cd download-coursera
uv sync
```

## Configuration

Before running, open `coursera_downloader.py` and update the two constants at the top:

```python
COURSE_URL = "https://www.coursera.org/learn/<course-slug>/home/module/<module-id>"
OUTPUT_DIR = Path("/your/desired/output/directory")
```

- **`COURSE_URL`**: The URL of the course module page (not an individual lecture).
- **`OUTPUT_DIR`**: Local folder where videos will be saved. Created automatically if it does not exist.

## Usage

```bash
uv run python coursera_downloader.py
```

You will be prompted for your Coursera email and password. The script then:

1. Opens a Chrome window and logs in to Coursera.
2. Navigates to the module page and collects all lecture URLs.
3. Downloads each video with yt-dlp, skipping any already downloaded.
4. Deletes the temporary cookie file on exit.

Videos are saved as `01_Lecture Title.mp4`, `02_Lecture Title.mp4`, etc.

## Notes

- The Chrome window is visible by default so you can handle MFA or CAPTCHA if prompted.
- To run headless (no window), change `make_driver(headless=False)` to `make_driver(headless=True)` in `main()`.
- Already-downloaded videos are detected by filename and skipped automatically.
- If no lectures are found, the course page structure may have changed — inspect it manually in the browser window.
