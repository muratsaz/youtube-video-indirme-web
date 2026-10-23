"""Launch the local service and reuse it if already running."""
import json
import socket
import threading
import urllib.request
import webbrowser
import uvicorn
import sys
import argparse
import os

HOST = '127.0.0.1'


def running(port):
    try:
        with urllib.request.urlopen(f'http://{HOST}:{port}/api/state', timeout=0.4) as response:
            return json.load(response).get('app') == 'cep-video'
    except Exception:
        return False


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--port', type=int)
    args = parser.parse_args()
    for port in ([args.port] if args.port else range(8765, 8775)):
        if running(port):
            if '--no-browser' not in sys.argv:
                webbrowser.open(f'http://{HOST}:{port}')
            break
        with socket.socket() as probe:
            try:
                probe.bind((HOST, port))
            except OSError:
                continue
        def show_when_ready(port=port):
            import time
            for _ in range(100):
                if running(port):
                    webbrowser.open(f'http://{HOST}:{port}')
                    return
                time.sleep(0.2)
        if '--no-browser' not in sys.argv:
            threading.Thread(target=show_when_ready, daemon=True).start()
        from app import app, EVENTS, LOCK, DATA
        server = uvicorn.Server(uvicorn.Config(app, host=HOST, port=port, log_config=None, access_log=False))
        app.state.request_shutdown = lambda: setattr(server, 'should_exit', True)
        runtime = DATA / 'runtime.json'
        runtime.write_text(json.dumps({'pid': os.getpid(), 'port': port}), encoding='utf-8')
        try:
            server.run()
        finally:
            with LOCK:
                for event in EVENTS.values():
                    event.set()
            runtime.unlink(missing_ok=True)
        break
    else:
        raise SystemExit('8765-8774 portları dolu. Açık uygulamaları kontrol edin.')
