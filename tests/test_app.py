import importlib
import atexit
import logging
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

TEST_ROOT = tempfile.TemporaryDirectory()
os.environ['YOUTUBE_APP_DATA'] = str(Path(TEST_ROOT.name) / 'data')
os.environ['YOUTUBE_APP_DOWNLOADS'] = str(Path(TEST_ROOT.name) / 'downloads')
app = importlib.import_module('app')


def clean_test_files():
    logging.shutdown()
    TEST_ROOT.cleanup()


atexit.register(clean_test_files)


class FakeDownloader:
    fail = False
    cancel = False

    def __init__(self, options):
        self.options = options

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def extract_info(self, url, download):
        if self.fail:
            raise RuntimeError('Video unavailable')
        return {'id': 'BaW_jenozKc', 'title': 'Deneme videosu', 'channel': 'Test', 'duration': 10}

    def process_info(self, info):
        if self.cancel:
            next(iter(app.EVENTS.values())).set()
        self.options['progress_hooks'][0]({'status': 'downloading', 'total_bytes': 100, 'downloaded_bytes': 50, 'speed': 10, 'eta': 5})
        self.options['progress_hooks'][0]({'status': 'finished'})
        self.options['postprocessor_hooks'][0]({'status': 'finished'})
        work = Path(self.options['outtmpl']).parent
        ext = '.mp3' if self.options['format'] == 'bestaudio/best' else '.mp4'
        (work / ('Deneme videosu' + ext)).write_bytes(b'test-media')


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app.app)
        self.headers = {'X-App-Token': app.TOKEN}
        app.JOBS.clear()
        app.EVENTS.clear()
        FakeDownloader.fail = False
        FakeDownloader.cancel = False
        self.pool = patch.object(app.POOL, 'submit')
        self.pool.start()
        self.addCleanup(self.pool.stop)

    def enqueue(self, **kwargs):
        response = self.client.post('/api/downloads', headers=self.headers, json={'url': 'https://youtu.be/BaW_jenozKc', **kwargs})
        self.assertEqual(response.status_code, 202)
        return response.json()['id']

    def test_youtube_links_are_canonical_and_remove_playlist(self):
        for url in ['youtu.be/BaW_jenozKc?si=abc', 'https://www.youtube.com/watch?v=BaW_jenozKc&list=xyz',
                    'https://m.youtube.com/shorts/BaW_jenozKc', 'https://youtube.com/live/BaW_jenozKc',
                    'https://music.youtube.com/watch?v=BaW_jenozKc']:
            self.assertEqual(app.normalize_url(url), 'https://www.youtube.com/watch?v=BaW_jenozKc')

    def test_invalid_urls_and_local_addresses_are_rejected(self):
        for url in ['https://youtube.com.evil.test/watch?v=BaW_jenozKc', 'http://127.0.0.1/a',
                    'https://youtube.com/playlist?list=1', 'https://youtu.be/short',
                    'https://youtube.com:999/watch?v=BaW_jenozKc', 'https://user@youtube.com/watch?v=BaW_jenozKc']:
            response = self.client.post('/api/downloads', headers=self.headers, json={'url': url})
            self.assertEqual(response.status_code, 422, url)

    def test_mutation_requires_token_and_same_origin(self):
        self.assertEqual(self.client.post('/api/open-folder').status_code, 403)
        self.assertEqual(self.client.post('/api/open-folder', headers={**self.headers, 'Origin': 'https://evil.example'}).status_code, 403)
        self.assertEqual(self.client.get('/api/state', headers={'Host': 'evil.example'}).status_code, 403)

    def test_invalid_format_is_rejected(self):
        self.assertEqual(self.client.post('/api/downloads', headers=self.headers, json={'url': 'https://youtu.be/BaW_jenozKc', 'kind': 'exe'}).status_code, 422)

    def test_duplicate_active_job_is_reused(self):
        first = self.enqueue()
        self.assertEqual(self.enqueue(), first)
        self.assertEqual(len(app.JOBS), 1)

    def test_queue_limit(self):
        for index in range(10):
            app.JOBS[str(index)] = {'status': 'queued'}
        response = self.client.post('/api/downloads', headers=self.headers, json={'url': 'https://youtu.be/BaW_jenozKc'})
        self.assertEqual(response.status_code, 429)

    def test_video_and_audio_finish_and_files_are_accessible(self):
        for kind, extension in [('video', '.mp4'), ('audio', '.mp3')]:
            with self.subTest(kind=kind):
                job_id = self.enqueue(kind=kind)
                with patch.object(app.yt_dlp, 'YoutubeDL', FakeDownloader):
                    app.run_download(job_id)
                job = app.JOBS[job_id]
                self.assertEqual(job['status'], 'done')
                self.assertTrue(job['filename'].endswith(extension))
                self.assertEqual(self.client.get(f'/api/downloads/{job_id}/file').content, b'test-media')
                self.assertFalse((app.DOWNLOADS / '.partial' / job_id).exists())
                self.assertEqual(app.load_history()[job_id]['status'], 'done')

    def test_cancel_queued_job_never_extracts_video(self):
        job_id = self.enqueue()
        self.client.post(f'/api/downloads/{job_id}/cancel', headers=self.headers)
        self.assertEqual(app.JOBS[job_id]['status'], 'cancelled')
        with patch.object(app.yt_dlp, 'YoutubeDL') as extractor:
            app.run_download(job_id)
            extractor.assert_not_called()
        self.assertEqual(app.JOBS[job_id]['status'], 'cancelled')

    def test_cancel_during_download_cleans_staging(self):
        job_id = self.enqueue()
        FakeDownloader.cancel = True
        with patch.object(app.yt_dlp, 'YoutubeDL', FakeDownloader):
            app.run_download(job_id)
        self.assertEqual(app.JOBS[job_id]['status'], 'cancelled')
        self.assertFalse((app.DOWNLOADS / '.partial' / job_id).exists())

    def test_failure_is_readable_and_can_be_retried(self):
        job_id = self.enqueue()
        FakeDownloader.fail = True
        with patch.object(app.yt_dlp, 'YoutubeDL', FakeDownloader):
            app.run_download(job_id)
        self.assertEqual(app.JOBS[job_id]['status'], 'error')
        self.assertIn('kaldırılmış', app.JOBS[job_id]['error'])
        self.assertNotEqual(self.enqueue(), job_id)

    def test_file_path_cannot_leave_download_directory(self):
        app.JOBS['unsafe'] = {'status': 'done', 'filename': '../history.json'}
        self.assertEqual(self.client.get('/api/downloads/unsafe/file').status_code, 404)

    def test_interrupted_jobs_recover_as_errors(self):
        job_id = self.enqueue()
        self.assertEqual(app.load_history()[job_id]['status'], 'error')

    def test_page_renders_token_without_placeholder(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(app.TOKEN, response.text)
        self.assertNotIn('__APP_TOKEN__', response.text)
        self.assertIn("frame-ancestors 'none'", response.headers['Content-Security-Policy'])

    def test_shutdown_requests_exit_and_cancels_active_work(self):
        job_id = self.enqueue()
        triggered = threading.Event()
        with patch.object(app.app.state, 'request_shutdown', triggered.set, create=True):
            response = self.client.post('/api/shutdown', headers=self.headers)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(app.EVENTS[job_id].is_set())
            self.assertTrue(triggered.wait(2))


if __name__ == '__main__':
    unittest.main()
