"""FastAPI entrypoint for the ChatKit starter backend."""

from __future__ import annotations

import logging
from pathlib import Path

from dotenv import load_dotenv

from chatkit.server import StreamingResult
from fastapi import FastAPI, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

# Load environment variables from .env file
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from .server import StarterChatServer
from .config import is_oauth_configured, OAUTH_REDIRECT_URI, SERVER_BASE_URL

app = FastAPI(title="ChatKit Starter API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

chatkit_server = StarterChatServer()


# =============================================================================
# OAuth Endpoints
# =============================================================================

@app.get("/oauth/login")
async def oauth_login(
    user_id: str = Query(default="default", description="User identifier for token storage"),
    redirect_to: str = Query(default="/", description="URL to redirect to after successful auth"),
) -> Response:
    """
    Initiate OAuth login flow.
    
    Redirects the user to SWU Stats authorization page.
    After authorization, the user will be redirected back to /oauth/callback.
    """
    if not is_oauth_configured():
        return JSONResponse(
            status_code=503,
            content={
                "error": "oauth_not_configured",
                "message": "OAuth is not configured. Please set SWUSTATS_CLIENT_ID and SWUSTATS_CLIENT_SECRET environment variables.",
            }
        )
    
    from .oauth import get_oauth_service
    oauth = get_oauth_service()
    
    # Get authorization URL
    auth_url, state = oauth.get_authorization_url(user_id)
    
    # Store the redirect_to URL for after callback (if state exists)
    if state:
        oauth._pending_states[state]["redirect_to"] = redirect_to
    else:
        # If no state, use user_id as the key for storing redirect_to
        if not hasattr(oauth, "_redirect_urls"):
            oauth._redirect_urls = {}
        oauth._redirect_urls[user_id] = redirect_to
    
    logger.info(f"🔐 Redirecting user {user_id} to OAuth authorization")
    return RedirectResponse(url=auth_url, status_code=302)


@app.get("/oauth/debug")
async def oauth_debug() -> JSONResponse:
    """
    Debug endpoint to show the OAuth configuration and URL that would be generated.
    
    Use this to verify your OAuth setup matches what's registered with SWU Stats.
    """
    from .config import (
        OAUTH_CLIENT_ID,
        OAUTH_CLIENT_SECRET,
        OAUTH_REDIRECT_URI,
        OAUTH_SCOPE,
        OAUTH_AUTHORIZE_URL,
    )
    from .oauth import get_oauth_service
    
    oauth = get_oauth_service()
    auth_url, state = oauth.get_authorization_url("debug_user")
    
    return JSONResponse({
        "oauth_configured": is_oauth_configured(),
        "client_id": OAUTH_CLIENT_ID[:8] + "..." if OAUTH_CLIENT_ID else None,
        "client_secret_set": bool(OAUTH_CLIENT_SECRET),
        "redirect_uri": OAUTH_REDIRECT_URI,
        "scopes": OAUTH_SCOPE,
        "auth_base_url": OAUTH_AUTHORIZE_URL,
        "generated_auth_url": auth_url,
        "state_enabled": state is not None,
        "instructions": {
            "1": "Copy the 'redirect_uri' value EXACTLY",
            "2": "Go to your SWU Stats app settings",
            "3": "Make sure the registered redirect URI matches EXACTLY (including trailing slash or lack thereof)",
            "4": "The 302 redirect means SWU Stats is rejecting the request, usually due to redirect_uri mismatch",
        }
    })


@app.get("/oauth/callback")
async def oauth_callback(
    code: str = Query(default=None, description="Authorization code from SWU Stats"),
    state: str = Query(default=None, description="State parameter for CSRF protection"),
    error: str = Query(default=None, description="Error code if authorization failed"),
    error_description: str = Query(default=None, description="Error description"),
) -> Response:
    """
    Handle OAuth callback from SWU Stats.
    
    This endpoint receives the authorization code and exchanges it for tokens.
    """
    # Handle errors from the OAuth provider
    if error:
        logger.error(f"❌ OAuth error: {error} - {error_description}")
        return HTMLResponse(
            status_code=400,
            content=f"""
            <!DOCTYPE html>
            <html>
            <head><title>Authorization Failed</title></head>
            <body style="font-family: system-ui; padding: 2rem; text-align: center;">
                <h1>❌ Authorization Failed</h1>
                <p><strong>Error:</strong> {error}</p>
                <p>{error_description or 'No additional details available.'}</p>
                <p><a href="/oauth/login">Try Again</a></p>
            </body>
            </html>
            """
        )
    
    if not code:
        return HTMLResponse(
            status_code=400,
            content="""
            <!DOCTYPE html>
            <html>
            <head><title>Invalid Request</title></head>
            <body style="font-family: system-ui; padding: 2rem; text-align: center;">
                <h1>❌ Invalid Request</h1>
                <p>Missing authorization code.</p>
                <p><a href="/oauth/login">Try Again</a></p>
            </body>
            </html>
            """
        )
    
    from .oauth import get_oauth_service
    oauth = get_oauth_service()
    
    # Get redirect_to URL
    redirect_to = "/"
    if state:
        # If state is provided, get redirect_to from state metadata (before it's consumed)
        state_metadata = oauth._pending_states.get(state, {})
        redirect_to = state_metadata.get("redirect_to", "/")
    else:
        # If no state, get redirect_to from user_id (default user)
        if hasattr(oauth, "_redirect_urls"):
            redirect_to = oauth._redirect_urls.get("default", "/")
    
    # Exchange code for tokens
    token = await oauth.exchange_code(code, state)
    
    if token is None:
        return HTMLResponse(
            status_code=400,
            content="""
            <!DOCTYPE html>
            <html>
            <head><title>Token Exchange Failed</title></head>
            <body style="font-family: system-ui; padding: 2rem; text-align: center;">
                <h1>❌ Token Exchange Failed</h1>
                <p>Could not exchange authorization code for tokens.</p>
                <p>This may be due to an expired or invalid code, or a state mismatch.</p>
                <p><a href="/oauth/login">Try Again</a></p>
            </body>
            </html>
            """
        )
    
    # Success! Redirect to the original destination
    logger.info(f"✅ OAuth flow completed successfully, redirecting to {redirect_to}")
    
    # If this is an API-style request, return JSON
    if redirect_to.startswith("/api"):
        return JSONResponse({
            "status": "authenticated",
            "message": "Successfully authenticated with SWU Stats",
        })
    
    # For browser requests, show success page then redirect
    return HTMLResponse(
        content=f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Authorization Successful</title>
            <meta http-equiv="refresh" content="2;url={redirect_to}">
        </head>
        <body style="font-family: system-ui; padding: 2rem; text-align: center;">
            <h1>✅ Authorization Successful</h1>
            <p>You have been successfully authenticated with SWU Stats.</p>
            <p>Redirecting you back to the application...</p>
            <p><a href="{redirect_to}">Click here if not redirected</a></p>
        </body>
        </html>
        """
    )


@app.get("/oauth/status")
async def oauth_status(
    user_id: str = Query(default="default", description="User identifier"),
) -> JSONResponse:
    """
    Check OAuth authentication status.
    
    Returns information about whether the user is authenticated
    and token status.
    """
    if not is_oauth_configured():
        # Check for legacy token
        from .config import SWUSTATS_ACCESS_TOKEN
        return JSONResponse({
            "oauth_configured": False,
            "authenticated": bool(SWUSTATS_ACCESS_TOKEN),
            "mode": "legacy" if SWUSTATS_ACCESS_TOKEN else "none",
            "message": "Using legacy access token" if SWUSTATS_ACCESS_TOKEN else "No authentication configured",
        })
    
    from .oauth import get_oauth_service
    oauth = get_oauth_service()
    
    token = oauth.token_store.get(user_id)
    
    if token is None:
        return JSONResponse({
            "oauth_configured": True,
            "authenticated": False,
            "mode": "oauth",
            "login_url": f"{SERVER_BASE_URL}/oauth/login?user_id={user_id}",
            "message": "Not authenticated. Please log in.",
        })
    
    return JSONResponse({
        "oauth_configured": True,
        "authenticated": True,
        "mode": "oauth",
        "token_expired": token.is_expired,
        "has_refresh_token": token.refresh_token is not None,
        "expires_at": token.expires_at,
        "message": "Authenticated" if not token.is_expired else "Token expired, will refresh on next request",
    })


@app.get("/oauth/userinfo")
async def oauth_userinfo(
    user_id: str = Query(default="default", description="User identifier"),
) -> JSONResponse:
    """
    Get user information from SWU Stats.
    
    Requires valid OAuth authentication.
    """
    if not is_oauth_configured():
        return JSONResponse(
            status_code=503,
            content={"error": "oauth_not_configured"}
        )
    
    from .oauth import get_oauth_service
    oauth = get_oauth_service()
    
    user_info = await oauth.get_user_info(user_id)
    
    if user_info is None:
        return JSONResponse(
            status_code=401,
            content={
                "error": "not_authenticated",
                "login_url": f"{SERVER_BASE_URL}/oauth/login?user_id={user_id}",
            }
        )
    
    return JSONResponse(user_info)


@app.post("/oauth/logout")
async def oauth_logout(
    user_id: str = Query(default="default", description="User identifier"),
) -> JSONResponse:
    """
    Log out and clear stored tokens.
    """
    if not is_oauth_configured():
        return JSONResponse({"status": "ok", "message": "No OAuth configured"})
    
    from .oauth import get_oauth_service
    oauth = get_oauth_service()
    oauth.logout(user_id)
    
    return JSONResponse({
        "status": "ok",
        "message": "Successfully logged out",
    })


@app.post("/chatkit")
async def chatkit_endpoint(request: Request) -> Response:
    """Proxy the ChatKit web component payload to the server implementation."""
    payload = await request.body()
    
    # Log the raw payload to see what's being received
    logger.info(f"📥 ========== CHATKIT ENDPOINT ==========")
    logger.info(f"📥 Raw payload length: {len(payload)} bytes")
    try:
        import json
        payload_json = json.loads(payload)
        logger.info(f"📥 Payload type: {payload_json.get('type', 'unknown')}")
        logger.info(f"📥 Payload keys: {list(payload_json.keys())}")
        if 'action' in payload_json:
            logger.info(f"📥 ACTION DETECTED: {payload_json.get('action')}")
    except Exception as e:
        logger.warning(f"📥 Could not parse payload as JSON: {e}")
    
    result = await chatkit_server.process(payload, {"request": request})

    if isinstance(result, StreamingResult):
        return StreamingResponse(result, media_type="text/event-stream")
    if hasattr(result, "json"):
        return Response(content=result.json, media_type="application/json")
    return JSONResponse(result)


@app.get("/api/deck-state/{thread_id}")
async def get_deck_state(thread_id: str) -> JSONResponse:
    """Get the active deck state for a thread, including deck contents if loaded."""
    from .tools import fetch_deck_contents
    
    logger.info(f"🔍 Fetching deck state for thread: {thread_id}")
    
    state = chatkit_server.deck_manager.to_dict(thread_id)
    deck_id = state.get("active_deck_id")
    
    # If there's an active deck but no contents loaded, fetch them
    if deck_id and not state.get("deck_contents"):
        logger.info(f"📦 Loading deck contents for deck {deck_id}")
        contents = await fetch_deck_contents(deck_id)
        state["deck_contents"] = contents
        # Store in manager for caching
        deck_state = chatkit_server.deck_manager.get_state(thread_id)
        deck_state.deck_contents = contents
    
    return JSONResponse(state)


@app.get("/api/deck/{deck_id}")
async def get_deck_contents(deck_id: int) -> JSONResponse:
    """Get the contents of a specific deck."""
    from .tools import fetch_deck_contents
    
    logger.info(f"📦 Fetching deck contents for deck: {deck_id}")
    contents = await fetch_deck_contents(deck_id)
    
    return JSONResponse(contents)


# Serve the built frontend
frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")