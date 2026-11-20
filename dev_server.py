"""Run the catalog server and restart it when application files change."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
POLL_SECONDS = 0.4


def snapshot():
    paths = [
        *ROOT.glob('*.py'),
        ROOT / 'config.local.json',
    ]
    stamps = {}
    for path in paths:
        try:
            info = path.stat()
        except FileNotFoundError:
            continue
        stamps[path] = (info.st_mtime_ns, info.st_size, info.st_ino)
    return stamps


def stop_server(process):
    # Signal the whole group so an in-flight TTS subprocess cannot outlive the server.
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def main():
    process = None
    observed = snapshot()
    try:
        while True:
            process = subprocess.Popen(
                [sys.executable, '-u', str(ROOT / 'server.py')],
                cwd=ROOT,
                start_new_session=True,
            )
            print(f'Dev: сервер запущен, PID {process.pid}. Ctrl+C для выхода.', flush=True)
            reported_exit = False
            while True:
                time.sleep(POLL_SECONDS)
                new_snapshot = snapshot()
                if new_snapshot != observed:
                    changed = {
                        path.relative_to(ROOT) for path in observed.keys() | new_snapshot.keys()
                        if observed.get(path) != new_snapshot.get(path)
                    }
                    observed = new_snapshot
                    print('Dev: перезапуск после изменения ' + ', '.join(map(str, sorted(changed))), flush=True)
                    break
                if process.poll() is not None and not reported_exit:
                    print(f'Dev: сервер завершился с кодом {process.returncode}. Жду правок.', flush=True)
                    reported_exit = True
            stop_server(process)
            process = None
    except KeyboardInterrupt:
        pass
    finally:
        if process is not None:
            stop_server(process)


if __name__ == '__main__':
    main()
