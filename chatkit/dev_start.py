"""
Full-stack development startup script.

Starts both the backend (with ngrok) and frontend simultaneously.
"""

import os
import sys
import subprocess
import time
from pathlib import Path

def main():
    """Start both backend and frontend."""
    print("\n" + "="*70)
    print("🚀 ChatKit Full-Stack Dev Startup")
    print("="*70 + "\n")
    
    chatkit_root = Path(__file__).parent
    backend_dir = chatkit_root / "backend"
    frontend_dir = chatkit_root / "frontend"
    
    # Check directories exist
    if not backend_dir.exists():
        print("❌ Backend directory not found")
        sys.exit(1)
    
    if not frontend_dir.exists():
        print("❌ Frontend directory not found")
        sys.exit(1)
    
    processes = []
    
    try:
        # Start backend with dev_run.py (handles ngrok automatically)
        print("📡 Starting backend with OAuth setup...")
        
        if sys.platform == "win32":
            # On Windows, start in new console window
            backend_process = subprocess.Popen(
                f'start "ChatKit Backend" cmd /k "cd /d {backend_dir} && python dev_run.py"',
                shell=True
            )
        else:
            backend_process = subprocess.Popen(
                [sys.executable, "dev_run.py"],
                cwd=str(backend_dir)
            )
        processes.append(("Backend", backend_process))
        
        # Give backend a moment to start
        time.sleep(3)
        
        # Start frontend
        print("🎨 Starting frontend...")
        
        if sys.platform == "win32":
            # On Windows, start in new console window
            frontend_process = subprocess.Popen(
                f'start "ChatKit Frontend" cmd /k "cd /d {frontend_dir} && npm run dev"',
                shell=True
            )
        else:
            frontend_process = subprocess.Popen(
                ["npm", "run", "dev"],
                cwd=str(frontend_dir)
            )
        processes.append(("Frontend", frontend_process))
        
        print("\n" + "="*70)
        print("✅ Servers starting in separate windows!")
        print("="*70)
        print("\n📍 URLs:")
        print("   Frontend: http://localhost:3000")
        print("   Backend:  http://localhost:8000")
        print("   Backend (ngrok): Check backend console for public URL")
        print("\n💡 Close the console windows to stop the servers")
        print("="*70 + "\n")
        
        # On Windows with 'start', process returns immediately
        # so we just exit successfully
        if sys.platform == "win32":
            print("✅ Dev environment launched!")
            sys.exit(0)
        
        # Keep this process alive to monitor on non-Windows
        while True:
            time.sleep(1)
            # Check if processes are still running
            for name, proc in processes:
                if proc.poll() is not None:
                    print(f"\n⚠️  {name} process exited with code {proc.returncode}")
    
    except KeyboardInterrupt:
        print("\n\n🛑 Stopping servers...")
        for name, proc in processes:
            try:
                proc.terminate()
                print(f"   Stopped {name}")
            except:
                pass
        sys.exit(0)


if __name__ == "__main__":
    main()
