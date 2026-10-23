"""Stop only verified cep. application instances on local ports."""
import json
import re
import urllib.request
import time
import os
from pathlib import Path
import argparse
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int)
args = parser.parse_args()
base_path = Path(__file__).resolve().parent
runtime = Path(os.environ.get('YOUTUBE_APP_DATA', base_path / '.data')) / 'runtime.json'


def stop_legacy(port):
    # Compatibility for sessions launched before the graceful shutdown route existed.
    # Revalidate both PID and the exact launcher path before stopping any process.
    if os.name != 'nt' or not runtime.exists():
        return
    data = json.loads(runtime.read_text(encoding='utf-8'))
    if data.get('port') != port or not isinstance(data.get('pid'), int):
        return
    environment = dict(os.environ, CEP_STOP_PID=str(data['pid']), CEP_STOP_LAUNCHER=str(base_path / 'start.py'))
    subprocess.run(['powershell.exe', '-NoProfile', '-Command',
        '$taskProc = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $env:CEP_STOP_PID); '
        'if ($taskProc -and $taskProc.Name -match "^pythonw?\\.exe$" -and '
        '$taskProc.CommandLine.Contains($env:CEP_STOP_LAUNCHER)) { Stop-Process -Id $taskProc.ProcessId }'],
        env=environment, check=True, creationflags=subprocess.CREATE_NO_WINDOW)

for port in ([args.port] if args.port else range(8765, 8775)):
    base = f'http://127.0.0.1:{port}'
    try:
        with urllib.request.urlopen(base + '/api/state', timeout=1) as response:
            if json.load(response).get('app') != 'cep-video':
                continue
        with urllib.request.urlopen(base, timeout=1) as response:
            html = response.read().decode('utf-8')
        token = re.search(r'<meta name="app-token" content="([^"]+)"', html).group(1)
        request = urllib.request.Request(base + '/api/shutdown', data=b'{}', headers={'X-App-Token': token, 'Content-Type': 'application/json'}, method='POST')
        try:
            with urllib.request.urlopen(request, timeout=3) as response:
                print('Uygulama kapatiliyor.')
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
            stop_legacy(port)
        for _ in range(100):
            try:
                urllib.request.urlopen(base + '/api/state', timeout=0.3).close()
                time.sleep(0.1)
            except OSError:
                break
    except OSError:
        continue
