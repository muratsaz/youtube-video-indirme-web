"""Loopback-only YouTube downloader. Run with start.py or Baslat.vbs."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Literal
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import yt_dlp

BASE = Path(__file__).resolve().parent
DATA = Path(os.environ.get('YOUTUBE_APP_DATA', BASE / '.data'))
DOWNLOADS = Path(os.environ.get('YOUTUBE_APP_DOWNLOADS', Path.home() / 'Downloads' / 'YouTube')).resolve()
DATA.mkdir(parents=True, exist_ok=True)
HISTORY = DATA / 'history.json'
TOKEN = secrets.token_urlsafe(32)
LOCK = threading.RLock()
POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix='download')
EVENTS: dict[str, threading.Event] = {}
ACTIVE = {'queued', 'preparing', 'downloading', 'processing', 'cancelling'}
logging.basicConfig(filename=DATA / 'app.log', level=logging.INFO, encoding='utf-8')
log = logging.getLogger('youtube-local')


def load_history():
    try:
        rows = json.loads(HISTORY.read_text(encoding='utf-8'))
        if not isinstance(rows, dict):
            return {}
        for row in rows.values():
            if row['status'] in ACTIVE:
                row.update(status='error', error='Uygulama kapandığı için indirme yarıda kaldı. Tekrar deneyebilirsin.')
        return rows
    except (OSError, ValueError, KeyError, TypeError):
        return {}


JOBS = load_history()


def save():
    with LOCK:
        temporary = HISTORY.with_suffix('.tmp')
        temporary.write_text(json.dumps(JOBS, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(HISTORY)


def update(job_id, persist=False, **fields):
    with LOCK:
        JOBS[job_id].update(fields)
        if persist:
            save()


def normalize_url(value: str) -> str:
    value = value.strip()
    if not re.match(r'^https?://', value, re.I):
        value = 'https://' + value
    try:
        parsed = urlparse(value)
        host = (parsed.hostname or '').lower()
        if parsed.username or parsed.password or parsed.port not in (None, 80, 443):
            raise ValueError
        parts = parsed.path.strip('/').split('/')
        if host in {'youtu.be', 'www.youtu.be'}:
            video_id = parts[0]
        elif host in {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com', 'youtube-nocookie.com', 'www.youtube-nocookie.com'}:
            if parsed.path == '/watch':
                video_id = parse_qs(parsed.query).get('v', [''])[0]
            elif len(parts) == 2 and parts[0] in {'shorts', 'embed', 'live'}:
                video_id = parts[1]
            else:
                raise ValueError
        else:
            raise ValueError
        if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
            raise ValueError
        return 'https://www.youtube.com/watch?v=' + video_id
    except ValueError:
        raise HTTPException(422, 'Geçerli bir YouTube video bağlantısı yapıştır. Oynatma listeleri desteklenmiyor.')


def friendly_error(error):
    message = str(error).lower()
    if any(part in message for part in ('sign in', 'bot', 'login', 'cookies', 'confirm your age')):
        return 'YouTube bu video için oturum veya doğrulama istiyor. Oturum gerektirmeyen başka bir video deneyebilirsin.'
    if 'private' in message:
        return 'Bu video gizli; indirilemiyor.'
    if any(part in message for part in ('unavailable', 'removed', 'not available', 'copyright')):
        return 'Video kaldırılmış veya bulunduğun bölgede erişime kapalı olabilir.'
    if any(part in message for part in ('403', '429', 'forbidden')):
        return 'YouTube indirme isteğini geçici olarak engelledi. Biraz sonra yeniden dene; sorun sürerse Guncelle.cmd dosyasını çalıştır.'
    if any(part in message for part in ('network', 'timed out', 'resolve', 'connection')):
        return 'Bağlantı kurulamadı. İnternet bağlantını kontrol edip tekrar dene.'
    if 'no space' in message or 'disk full' in message:
        return 'Diskte yeterli boş alan yok.'
    if 'requested format' in message:
        return 'Bu kalite alınamadı. En yüksek kalite seçeneğiyle yeniden dene.'
    return 'İndirme tamamlanamadı. Yeniden dene; sorun sürerse Guncelle.cmd dosyasını çalıştır. Ayrıntılar .data/app.log dosyasında.'


class Cancelled(Exception):
    pass


class QuietLogger:
    def debug(self, message):
        pass

    def warning(self, message):
        log.warning(message)

    def error(self, message):
        log.error(message)


def run_download(job_id):
    event = EVENTS[job_id]
    work = (DOWNLOADS / '.partial' / job_id).resolve()
    last_tick = 0.0

    def check_cancel():
        if event.is_set():
            raise Cancelled()

    def progress(data):
        nonlocal last_tick
        check_cancel()
        if data['status'] == 'downloading':
            now = time.monotonic()
            if now - last_tick < 0.35:
                return
            last_tick = now
            total = data.get('total_bytes') or data.get('total_bytes_estimate') or 0
            downloaded = data.get('downloaded_bytes') or 0
            update(job_id, status='downloading', progress=min(99, round(downloaded / total * 100, 1)) if total else 0,
                   downloaded_bytes=downloaded, total_bytes=total, speed=data.get('speed'), eta=data.get('eta'))
        elif data['status'] == 'finished':
            update(job_id, status='processing', speed=None, eta=None)

    def postprocess(data):
        check_cancel()
        update(job_id, status='processing', speed=None, eta=None)

    try:
        check_cancel()
        update(job_id, persist=True, status='preparing')
        DOWNLOADS.mkdir(parents=True, exist_ok=True)
        work.mkdir(parents=True, exist_ok=True)
        with LOCK:
            job = dict(JOBS[job_id])
        options = {
            'noplaylist': True, 'quiet': True, 'no_warnings': True, 'logger': QuietLogger(),
            'windowsfilenames': True, 'outtmpl': str(work / '%(title).140B [%(id)s].%(ext)s'),
            'socket_timeout': 20, 'retries': 3, 'fragment_retries': 3,
            'js_runtimes': {'node': {'path': shutil.which('node')}},
            'progress_hooks': [progress], 'postprocessor_hooks': [postprocess],
        }
        if job['kind'] == 'audio':
            options.update(format='bestaudio/best', postprocessors=[{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'}])
        else:
            cap = '' if job['quality'] == 'best' else f"[height<={job['quality']}]"
            options.update(format=f'bv*{cap}+ba/b{cap}', merge_output_format='mp4',
                           postprocessors=[{'key': 'FFmpegVideoRemuxer', 'preferedformat': 'mp4'}])
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(job['url'], download=False)
            check_cancel()
            if not info or info.get('_type') in {'playlist', 'multi_video'}:
                raise ValueError('Video bilgisi alınamadı')
            if info.get('is_live') or info.get('live_status') == 'is_upcoming':
                raise ValueError('Canlı yayınlar desteklenmiyor. Yayın bittikten sonra yeniden dene.')
            update(job_id, persist=True, title=info.get('title') or 'YouTube videosu',
                   channel=info.get('channel') or info.get('uploader') or '',
                   duration=info.get('duration'), thumbnail=f"https://i.ytimg.com/vi/{info['id']}/mqdefault.jpg")
            downloader.process_info(info)
        check_cancel()
        extension = '.mp3' if job['kind'] == 'audio' else '.mp4'
        outputs = [path for path in work.iterdir() if path.is_file() and path.suffix == extension]
        if len(outputs) != 1:
            raise ValueError('İndirilen dosya bulunamadı')
        output = outputs[0]
        destination = DOWNLOADS / f'{output.stem} [{job_id[:6]}]{output.suffix}'
        with LOCK:
            check_cancel()
            output.replace(destination)
            update(job_id, persist=True, status='done', progress=100, filename=destination.name,
                   size=destination.stat().st_size, completed_at=time.time(), speed=None, eta=None)
    except Exception as error:
        if event.is_set() or isinstance(error, Cancelled):
            update(job_id, persist=True, status='cancelled', speed=None, eta=None)
        else:
            log.exception('Download %s failed', job_id)
            message = str(error) if 'Canlı yayınlar' in str(error) else friendly_error(error)
            update(job_id, persist=True, status='error', error=message, speed=None, eta=None)
    finally:
        # Only this job's private staging directory may be removed.
        if work.parent == (DOWNLOADS / '.partial').resolve() and work.name == job_id:
            shutil.rmtree(work, ignore_errors=True)
        with LOCK:
            EVENTS.pop(job_id, None)


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware('http')
async def local_guard(request: Request, call_next):
    host = request.url.hostname
    if host not in {'127.0.0.1', 'localhost', 'testserver'}:
        return JSONResponse({'detail': 'Yalnızca yerel erişim destekleniyor.'}, status_code=403)
    origin = request.headers.get('origin')
    if origin and origin not in {f'http://127.0.0.1:{request.url.port or 80}', f'http://localhost:{request.url.port or 80}'}:
        return JSONResponse({'detail': 'Bu kaynaktan erişim kapalı.'}, status_code=403)
    if request.method not in {'GET', 'HEAD'} and not secrets.compare_digest(request.headers.get('x-app-token', ''), TOKEN):
        return JSONResponse({'detail': 'Sayfayı yenileyip tekrar dene.'}, status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' https://i.ytimg.com; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    return response


@app.get('/', response_class=HTMLResponse)
def index():
    return (BASE / 'static' / 'index.html').read_text(encoding='utf-8').replace('__APP_TOKEN__', TOKEN)


@app.get('/api/state')
def state():
    with LOCK:
        return {'app': 'cep-video', 'jobs': sorted([dict(row) for row in JOBS.values()], key=lambda row: row['created_at'], reverse=True),
                'folder': str(DOWNLOADS), 'ffmpeg': bool(shutil.which('ffmpeg')), 'node': bool(shutil.which('node')),
                'engine': yt_dlp.version.__version__}


class DownloadRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    kind: Literal['video', 'audio'] = 'video'
    quality: Literal['360', '720', '1080', 'best'] = '1080'


@app.post('/api/downloads', status_code=202)
def download(body: DownloadRequest):
    url = normalize_url(body.url)
    if not shutil.which('ffmpeg') or not shutil.which('node'):
        raise HTTPException(503, 'FFmpeg veya Node.js bulunamadı. Kurulum yönergelerini kontrol et.')
    with LOCK:
        if sum(row['status'] in ACTIVE for row in JOBS.values()) >= 10:
            raise HTTPException(429, 'Sırada 10 indirme var. Birinin tamamlanmasını bekle.')
        for row in JOBS.values():
            if row['url'] == url and row['kind'] == body.kind and row['quality'] == body.quality and row['status'] in ACTIVE:
                return dict(row)
        job_id = uuid4().hex
        job = {'id': job_id, 'url': url, 'kind': body.kind, 'quality': body.quality, 'title': 'Video bilgileri alınıyor…',
               'status': 'queued', 'progress': 0, 'created_at': time.time(), 'error': None}
        JOBS[job_id] = job
        EVENTS[job_id] = threading.Event()
        save()
        POOL.submit(run_download, job_id)
        return dict(job)


@app.post('/api/downloads/{job_id}/cancel')
def cancel(job_id: str):
    with LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(404, 'İndirme bulunamadı.')
        if job['status'] in ACTIVE and job_id in EVENTS:
            EVENTS[job_id].set()
            update(job_id, persist=True, status='cancelled' if job['status'] == 'queued' else 'cancelling')
    return {'ok': True}


def completed_file(job_id):
    with LOCK:
        job = JOBS.get(job_id)
        if not job or job['status'] != 'done':
            raise HTTPException(404, 'Tamamlanan dosya bulunamadı.')
        path = (DOWNLOADS / job.get('filename', '')).resolve()
    if path.parent != DOWNLOADS or not path.is_file():
        raise HTTPException(404, 'Dosya taşınmış veya silinmiş olabilir.')
    return path


@app.get('/api/downloads/{job_id}/file')
def get_file(job_id: str):
    path = completed_file(job_id)
    return FileResponse(path, filename=path.name)


@app.post('/api/open-folder')
def open_folder():
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    if os.name == 'nt':
        os.startfile(str(DOWNLOADS))
    else:
        subprocess.Popen(['open' if os.sys.platform == 'darwin' else 'xdg-open', str(DOWNLOADS)])
    return {'ok': True}


@app.post('/api/shutdown')
def shutdown():
    callback = getattr(app.state, 'request_shutdown', None)
    if callback is None:
        raise HTTPException(409, 'Bu sunucuyu açık olduğu konsoldan kapatabilirsiniz.')
    with LOCK:
        for event in EVENTS.values():
            event.set()
    threading.Timer(0.3, callback).start()
    return {'ok': True}


@app.post('/api/downloads/{job_id}/reveal')
def reveal(job_id: str):
    path = completed_file(job_id)
    if os.name == 'nt':
        subprocess.Popen(['explorer.exe', '/select,', str(path)])
    return {'ok': True}


app.mount('/static', StaticFiles(directory=BASE / 'static'), name='static')
