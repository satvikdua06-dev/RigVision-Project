import subprocess
import sys
import time
import os
import threading
from pathlib import Path

# Load .env before doing anything so all sub-processes inherit the env.
# override=True ensures the file always wins over stale shell env vars.
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env", override=True)
except ImportError:
    pass

# Force UTF-8 I/O in all subprocesses (avoids cp1252 encoding errors on Windows)
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

# ── Colours ───────────────────────────────────────────────────────────────────
RESET  = "\033[0m"
RED    = "\033[91m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
MAGENTA= "\033[95m"
BLUE   = "\033[94m"
WHITE  = "\033[97m"

# ── Service definitions ───────────────────────────────────────────────────────
#
# "delay_before" — seconds to wait after the PREVIOUS service started before
#                  launching this one.  Gives infrastructure time to bind.

processes_to_run = [
    # ── SCADA simulators (start first so the gateway finds them ready) ────────
    {
        "name":         "Modbus-Sim",
        "command":      ["python", "-m", "scada.simulators.modbus_server"],
        "cwd":          ".",
        "color":        BLUE,
        "delay_before": 0,
    },
    {
        "name":         "MQTT-Sim",
        "command":      ["python", "-m", "scada.simulators.mqtt_publisher"],
        "cwd":          ".",
        "color":        BLUE,
        "delay_before": 1.0,
    },
    # ── SCADA gateway ─────────────────────────────────────────────────────────
    {
        "name":         "SCADA-Gateway",
        "command":      ["python", "-m", "scada.gateway"],
        "cwd":          ".",
        "color":        CYAN,
        "delay_before": 1.5,   # give sims a moment to bind
    },
    # ── Application services ──────────────────────────────────────────────────
    {
        "name": "Backend",
        "command": ["python", "main.py"],
        "cwd": "backend",
        "color": GREEN,
        "delay_before": 1.0,
    },
    {
        "name": "Anomaly_Listener",
        "command": ["python", "knowledge/extraction/anomaly_listener.py"],
        "cwd": ".",
        "color": MAGENTA,
        "delay_before": 1.0,
    },
    {
        "name": "Pipeline",
        "command": ["python", "pipeline.py", "--mode", "video", "--cameras", "vid1.mp4", "vid2.mp4"],
        "cwd": "cv",
        "color": YELLOW,
        "delay_before": 1.0,
    },
    # ── Frontend services ─────────────────────────────────────────────────────
    {
        "name": "Frontend",
        "command": ["npm", "run", "dev"],
        "cwd": "frontend",
        "color": CYAN,
        "delay_before": 1.0,
    },
    {
        "name": "Auth",
        "command": ["npm", "run", "dev"],
        "cwd": "auth-rig",
        "color": CYAN,
        "delay_before": 0.5,
    },
]

running_processes = []

# ── DB initialisation ─────────────────────────────────────────────────────────

def _init_timescaledb() -> None:
    """
    Create the sensor_readings table (+ TimescaleDB hypertable if available).
    Runs synchronously before any service starts so the gateway finds the
    schema ready on first connect.
    """
    print(f"{WHITE}[init] Initialising TimescaleDB / PostgreSQL schema...{RESET}")
    try:
        from scada.init_db import init_db
        ok = init_db(retries=5, retry_delay=3.0)
        if ok:
            print(f"{GREEN}[init] Database schema ready{RESET}")
        else:
            print(f"{YELLOW}[init] Postgres unreachable — SCADA writes will be skipped "
                  f"(sensor data still flows to Redis){RESET}")
    except Exception as e:
        print(f"{YELLOW}[init] DB init error ({e}) — continuing without TimescaleDB{RESET}")

def get_python_executable(target_dir):
    """
    Finds the correct Python executable by checking common virtual environment
    directories in the target directory and the project root.
    """
    venv_names = ['venv', 'env', '.venv', 'ven', 'myenv']
    base_dirs = [target_dir, os.getcwd()]
    
    for base in base_dirs:
        for venv in venv_names:
            if sys.platform == "win32":
                py_path = os.path.join(base, venv, 'Scripts', 'python.exe')
            else:
                py_path = os.path.join(base, venv, 'bin', 'python')
                
            if os.path.isfile(py_path) and os.access(py_path, os.X_OK):
                return py_path
                
    return "python3" if sys.platform == "darwin" else "python"

def run_process(proc_info):
    name = proc_info["name"]
    cwd = proc_info["cwd"]
    cmd = proc_info["command"]
    color = proc_info["color"]
    reset = "\033[0m"

    try:
        # Start the process
        actual_cmd = list(cmd)
        target_dir = os.path.join(os.getcwd(), cwd) if cwd != "." else os.getcwd()
        
        # Use venv Python if running a python command
        if actual_cmd[0] in ("python", "python3"):
            actual_cmd[0] = get_python_executable(target_dir)

        if os.name == "nt" and actual_cmd[0] == "npm":
            actual_cmd[0] = "npm.cmd"

        p = subprocess.Popen(
            actual_cmd,
            cwd=target_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1
        )
        running_processes.append(p)

        print(f"{color}[{name}] Started (PID {p.pid}){reset}")

        # Read output line by line and print it with a prefix
        for line in iter(p.stdout.readline, ''):
            if line:
                print(f"{color}[{name}]{reset} {line.strip()}")

        p.stdout.close()
        p.wait()
        if p.returncode != 0 and p.returncode != -15: # Ignore graceful terminations
            print(f"{color}[{name}] Exited with code {p.returncode}{reset}")
            
    except Exception as e:
        print(f"{color}[{name}] Failed to start: {e}{reset}")

def main():
    print(f"{WHITE}RigVision-3D — starting all services{RESET}\n")
    print("Press Ctrl+C to stop everything.\n")
    
    # Step 1: initialise the database schema synchronously
    _init_timescaledb()
    print()

    threads = []
    
    # Start each process in the defined order
    for p_info in processes_to_run:
        delay = p_info.get("delay_before", 1.0)
        if delay > 0:
            time.sleep(delay)

        t = threading.Thread(target=run_process, args=(p_info,))
        t.daemon = True
        t.start()
        threads.append(t)
        
    try:
        # Keep main thread alive
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n{WHITE}Stopping all services...{RESET}")
        for p in running_processes:
            try:
                # Terminate gracefully
                p.terminate()
            except Exception:
                pass
                
        # Wait a brief moment to allow graceful shutdown
        time.sleep(1.5)
        print(f"{GREEN}All services stopped.{RESET}")
        sys.exit(0)

if __name__ == "__main__":
    main()
