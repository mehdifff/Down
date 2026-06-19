from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
import sqlite3, os, requests, re
from datetime import datetime
from bs4 import BeautifulSoup
import yt_dlp

app = Flask(__name__)
CORS(app)

DB = 'downloads.db'
scheduler = BackgroundScheduler()
scheduler.start()

# ─── Database ───────────────────────────────────────────────
def init_db():
    with sqlite3.connect(DB) as con:
        con.execute('''CREATE TABLE IF NOT EXISTS downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            name TEXT,
            direct_url TEXT,
            status TEXT DEFAULT 'pending',
            sched_time TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            error TEXT
        )''')

def get_db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

# ─── Link Extractor ─────────────────────────────────────────
def extract_direct_link(page_url):
    """Try multiple methods to find direct download link."""

    # Method 1: yt-dlp (supports thousands of sites)
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'skip_download': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(page_url, download=False)
            if info and 'url' in info:
                return info['url'], info.get('title', '')
            if info and 'formats' in info:
                # pick best quality
                fmt = sorted(info['formats'], key=lambda x: x.get('quality', 0) or 0, reverse=True)
                for f in fmt:
                    if f.get('url'):
                        return f['url'], info.get('title', '')
    except Exception:
        pass

    # Method 2: Scrape HTML for direct video/mp4 links
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36',
            'Accept-Language': 'fa,en;q=0.9',
        }
        r = requests.get(page_url, headers=headers, timeout=15)
        html = r.text

        # Look for direct video URLs
        patterns = [
            r'(https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*)',
            r'(https?://[^\s"\'<>]+\.mkv[^\s"\'<>]*)',
            r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)',
            r'file["\']?\s*:\s*["\']?(https?://[^\s"\'<>,]+)',
            r'source\s+src=["\']?(https?://[^\s"\'<>]+)',
        ]

        for pat in patterns:
            matches = re.findall(pat, html, re.IGNORECASE)
            if matches:
                return matches[0], ''

        # Parse with BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        for tag in soup.find_all(['a', 'source', 'video']):
            href = tag.get('href') or tag.get('src') or ''
            if any(ext in href.lower() for ext in ['.mp4', '.mkv', '.avi', '.m3u8']):
                if href.startswith('http'):
                    return href, tag.get_text(strip=True) or ''

    except Exception as e:
        pass

    return None, None

# ─── Download Job ────────────────────────────────────────────
def process_download(download_id):
    with get_db() as con:
        row = con.execute('SELECT * FROM downloads WHERE id=?', (download_id,)).fetchone()
        if not row:
            return

        con.execute("UPDATE downloads SET status='extracting' WHERE id=?", (download_id,))
        con.commit()

        direct_url, title = extract_direct_link(row['url'])

        if direct_url:
            name = row['name'] or title or direct_url.split('/')[-1] or 'download'
            con.execute(
                "UPDATE downloads SET status='ready', direct_url=?, name=? WHERE id=?",
                (direct_url, name, download_id)
            )
        else:
            con.execute(
                "UPDATE downloads SET status='error', error='لینک دانلود پیدا نشد' WHERE id=?",
                (download_id,)
            )
        con.commit()

# ─── Routes ─────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/add', methods=['POST'])
def add_download():
    data = request.json
    url = data.get('url', '').strip()
    name = data.get('name', '').strip()
    sched_time = data.get('sched_time')  # ISO format: "2024-01-15T03:00"

    if not url:
        return jsonify({'error': 'لینک الزامی است'}), 400

    with get_db() as con:
        cur = con.execute(
            "INSERT INTO downloads (url, name, sched_time, status) VALUES (?,?,?,?)",
            (url, name, sched_time, 'scheduled' if sched_time else 'pending')
        )
        dl_id = cur.lastrowid
        con.commit()

    if sched_time:
        try:
            run_time = datetime.fromisoformat(sched_time)
            scheduler.add_job(
                process_download,
                trigger=DateTrigger(run_date=run_time),
                args=[dl_id],
                id=f'dl_{dl_id}'
            )
        except Exception as e:
            return jsonify({'error': f'زمان‌بندی نامعتبر: {e}'}), 400
    else:
        # Process immediately in background
        scheduler.add_job(process_download, args=[dl_id], id=f'dl_{dl_id}')

    return jsonify({'id': dl_id, 'status': 'added'})

@app.route('/api/list')
def list_downloads():
    with get_db() as con:
        rows = con.execute('SELECT * FROM downloads ORDER BY id DESC').fetchall()
        return jsonify([dict(r) for r in rows])

@app.route('/api/delete/<int:dl_id>', methods=['DELETE'])
def delete_download(dl_id):
    try:
        scheduler.remove_job(f'dl_{dl_id}')
    except Exception:
        pass
    with get_db() as con:
        con.execute('DELETE FROM downloads WHERE id=?', (dl_id,))
        con.commit()
    return jsonify({'ok': True})

@app.route('/api/retry/<int:dl_id>', methods=['POST'])
def retry_download(dl_id):
    with get_db() as con:
        con.execute("UPDATE downloads SET status='pending', error=NULL WHERE id=?", (dl_id,))
        con.commit()
    scheduler.add_job(process_download, args=[dl_id], id=f'dl_retry_{dl_id}')
    return jsonify({'ok': True})

if __name__ == '__main__':
    init_db()
    import os
port = int(os.environ.get('PORT', 5000))
app.run(host='0.0.0.0', port=port, debug=False)
