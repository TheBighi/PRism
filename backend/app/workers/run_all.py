import subprocess
import sys

WORKERS = [
    ("analysis:queue", "app.workers.analysis_worker"),
    ("explain:queue", "app.workers.explanation_worker"),
    ("history:queue", "app.workers.history_worker"),
]

if __name__ == "__main__":
    processes = []
    for queue, module in WORKERS:
        p = subprocess.Popen(
            [sys.executable, "-m", "arq", f"{module}.WorkerSettings"],
        )
        processes.append(p)
        print(f"Started {module} on {queue} (pid {p.pid})")

    try:
        for p in processes:
            p.wait()
    except KeyboardInterrupt:
        for p in processes:
            p.terminate()
