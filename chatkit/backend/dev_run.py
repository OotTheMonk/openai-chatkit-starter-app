"""
Development startup script for ChatKit backend.

Automatically configures ngrok for OAuth development and starts the server.
"""

import os
import sys
import subprocess
import time
import requests
import json
from pathlib import Path
from typing import Optional
import logging
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables from .env file FIRST
env_path = Path(__file__).parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
    logger.info(f"📁 Loaded environment from {env_path}")

# Add parent directory to path so we can import config
sys.path.insert(0, str(Path(__file__).parent))

def check_ngrok_installed() -> bool:
    """Check if ngrok is installed and available."""
    try:
        subprocess.run(["ngrok", "--version"], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def install_ngrok() -> bool:
    """Try to install ngrok using pip."""
    try:
        print("Installing pyngrok...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyngrok"], check=True)
        return True
    except subprocess.CalledProcessError:
        print("❌ Failed to install pyngrok")
        return False


def get_existing_ngrok_url() -> str | None:
    """
    Check if ngrok is already running and return its public URL.
    
    This prevents creating multiple tunnels when restarting the dev server.
    Only returns URL if the tunnel is actually responding.
    """
    try:
        import requests
        # ngrok's local API runs on 4040 by default
        resp = requests.get("http://localhost:4040/api/tunnels", timeout=2)
        if resp.status_code == 200:
            data = resp.json()
            # Find the HTTP tunnel
            for tunnel in data.get("tunnels", []):
                if tunnel.get("proto") == "http":
                    public_url = tunnel.get("public_url")
                    if public_url:
                        # Verify the tunnel is actually online by checking it can be reached
                        try:
                            test_resp = requests.get(f"{public_url}", timeout=2)
                            # If we can reach it, it's alive
                            logger.info(f"Found existing ngrok tunnel: {public_url}")
                            return public_url
                        except:
                            # Tunnel exists but is offline, don't reuse it
                            logger.warning(f"Found ngrok tunnel but it's offline: {public_url}")
                            return None
    except Exception:
        pass
    return None


def start_ngrok(port: int = 8000) -> Optional[str]:
    """
    Start ngrok tunnel to localhost.
    
    First checks if ngrok is already running and reuses that tunnel.
    Configures authentication token if provided in environment.
    
    Returns:
        The public URL if successful, None otherwise
    """
    # Check if ngrok is already running
    existing_url = get_existing_ngrok_url()
    if existing_url:
        print(f"♻️  Reusing existing ngrok tunnel: {existing_url}")
        return existing_url
    
    try:
        from pyngrok import ngrok, conf
        
        # Configure auth token if provided
        auth_token = os.getenv("NGROK_AUTHTOKEN")
        if auth_token:
            ngrok.set_auth_token(auth_token)
            logger.info("🔑 ngrok authenticated with token from .env")
        
        print(f"🔗 Starting ngrok tunnel to localhost:{port}...")
        tunnel = ngrok.connect(port, "http")
        # Extract the public URL string from the tunnel object
        public_url = str(tunnel.public_url) if hasattr(tunnel, 'public_url') else str(tunnel)
        print(f"✅ ngrok tunnel active: {public_url}")
        return public_url
    except Exception as e:
        logger.warning(f"⚠️  pyngrok failed: {e}")
        logger.info("Trying ngrok CLI as fallback...")
        
        # Fallback: try using ngrok CLI directly
        try:
            auth_token = os.getenv("NGROK_AUTHTOKEN")
            if auth_token:
                # Configure auth token via CLI
                subprocess.run(
                    ["ngrok", "config", "add-authtoken", auth_token],
                    capture_output=True,
                    timeout=5
                )
                logger.info("🔑 Configured ngrok auth token via CLI")
            
            # Start ngrok via CLI
            result = subprocess.run(
                ["ngrok", "http", str(port)],
                capture_output=False,
                timeout=10
            )
        except Exception as cli_error:
            print(f"⚠️  Failed to start ngrok: {e}")
            return None
        
        return None


def update_env_file(ngrok_url: str) -> None:
    """Update .env file with ngrok URL."""
    env_path = Path(__file__).parent / ".env"
    
    # Read existing env
    env_vars = {}
    if env_path.exists():
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    env_vars[key] = value
    
    # Update redirect URI
    env_vars["SERVER_BASE_URL"] = ngrok_url
    env_vars["SWUSTATS_REDIRECT_URI"] = f"{ngrok_url}/oauth/callback"
    env_vars["NGROK_URL"] = ngrok_url  # Keep track that we're using ngrok
    
    # Write back
    with open(env_path, "w") as f:
        for key, value in env_vars.items():
            f.write(f"{key}={value}\n")
    
    print(f"✅ Updated .env with redirect URI: {ngrok_url}/oauth/callback")


def is_dev_mode() -> bool:
    """Check if we're in development mode."""
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return True
    
    with open(env_path, "r") as f:
        content = f.read()
        # If already configured with ngrok or no client ID, we're in dev
        return "ngrok" in content.lower() or "SWUSTATS_CLIENT_ID=" in content


def main():
    """Main startup routine."""
    print("\n" + "="*70)
    print("🚀 ChatKit Backend Dev Startup")
    print("="*70 + "\n")
    
    # Load config
    try:
        from app.config import OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET, SERVER_BASE_URL
        
        has_oauth = OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET
        has_ngrok_token = os.getenv("NGROK_AUTHTOKEN")
        
        if has_oauth:
            print("✅ OAuth credentials found in .env")
        else:
            print("⚠️  OAuth not configured yet")
        
        # For local development, ALWAYS set up ngrok if we have an auth token
        # This ensures we have a fresh, working tunnel even if the old one expired
        if has_ngrok_token:
            print("📍 Setting up ngrok tunnel...\n")
            
            # Check ngrok
            if not check_ngrok_installed():
                print("📦 pyngrok not found, installing...")
                if not install_ngrok():
                    print("\n❌ Could not set up ngrok")
                    print("   You'll need to:")
                    print("   1. Install pyngrok: pip install pyngrok")
                    print("   2. Or manually set SERVER_BASE_URL to your tunnel URL")
                    sys.exit(1)
            
            # Start ngrok
            ngrok_url = start_ngrok(8000)
            if ngrok_url:
                update_env_file(ngrok_url)
                print(f"\n📍 Your dev URL: {ngrok_url}")
                if not has_oauth:
                    print("\n   📝 Next steps:")
                    print("   1. Go to https://swustats.net and register your app")
                    print(f"   2. Set Redirect URI to: {ngrok_url}/oauth/callback")
                    print("   3. Copy your Client ID and Client Secret")
                    print("   4. Add them to backend/.env:")
                    print("      SWUSTATS_CLIENT_ID=your_client_id")
                    print("      SWUSTATS_CLIENT_SECRET=your_client_secret")
                    print("   5. Restart this script")
                else:
                    print("   ✅ ngrok tunnel is active and .env updated\n")
            else:
                print("\n⚠️  Could not start ngrok")
                if not has_oauth:
                    print("   You'll need ngrok to complete OAuth setup\n")
                else:
                    print("   OAuth may not work with stale ngrok URL\n")
        elif "localhost" in SERVER_BASE_URL or "127.0.0.1" in SERVER_BASE_URL:
            print("⚠️  Using localhost - add NGROK_AUTHTOKEN to .env to enable remote testing\n")
    
    except Exception as e:
        print(f"⚠️  Error checking config: {e}\n")
    
    print("="*70)
    print("✅ Starting FastAPI server...")
    print("="*70 + "\n")
    
    # Start uvicorn
    try:
        import uvicorn
        uvicorn.run(
            "app.main:app",
            host="0.0.0.0",
            port=8000,
            reload=True,
            reload_dirs=["app"],
        )
    except KeyboardInterrupt:
        print("\n\n🛑 Server stopped")
        sys.exit(0)


if __name__ == "__main__":
    main()
