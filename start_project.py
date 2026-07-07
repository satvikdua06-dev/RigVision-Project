import subprocess
import sys
import time
import os

import threading


processes_to_run = [
    {
        "name": "Frontend",
        "command": ["npm", "run", "dev"],
        "cwd": "frontend",
        "color": "\033[96m" # Cyan
    },
    {
        "name": "Auth",
        "command": ["npm", "run", "dev"],
        "cwd": "auth-rig",
        "color": "\033[96m" # Cyan
    },
    {
        "name": "Backend",
        "command": ["python", "main.py"],
        "cwd": "backend",
        "color": "\033[92m" # Green
    },
    {
        "name": "Anomaly_Listener",
        "command": ["python", "knowledge/extraction/anomaly_listener.py"],
        "cwd": ".",
        "color": "\033[95m" # Magenta
    },
    {
        "name": "Pipeline",
        "command": ["python", "pipeline.py", "--mode", "video", "--cameras", "vid1.mp4", "vid2.mp4"],
        "cwd": "cv",
        "color": "\033[93m" # Yellow
    },
]

running_processes = []

def run_process(proc_info):
    name = proc_info["name"]
    cwd = proc_info["cwd"]
    cmd = proc_info["command"]
    color = proc_info["color"]
    reset = "\033[0m"

    try:
        # Start the process
        actual_cmd = list(cmd)
        if os.name == "nt" and actual_cmd[0] == "npm":
            actual_cmd[0] = "npm.cmd"

        p = subprocess.Popen(
            actual_cmd,
            cwd=os.path.join(os.getcwd(), cwd) if cwd != "." else os.getcwd(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1
        )
        running_processes.append(p)

        print(f"{color}[{name}] Started with PID {p.pid}{reset}")

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
    print("🚀 Starting RigVision-3D Project...\n")
    print("Press [CTRL+C] at any time to gracefully stop all services.\n")
    
    threads = []
    
    # Start each process in the defined order
    for p_info in processes_to_run:
        t = threading.Thread(target=run_process, args=(p_info,))
        t.daemon = True
        t.start()
        threads.append(t)
        
        # Add a short delay to ensure they start sequentially
        time.sleep(1.5)
        
    try:
        # Keep main thread alive
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Interrupt received. Stopping all services...")
        for p in running_processes:
            try:
                # Terminate gracefully
                p.terminate()
            except Exception:
                pass
                
        # Wait a brief moment to allow graceful shutdown
        time.sleep(1)
        print("✅ All services stopped.")
        sys.exit(0)

if __name__ == "__main__":
    main()
