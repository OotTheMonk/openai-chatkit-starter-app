"""
Shared configuration for the ChatKit backend.

This module handles configuration for OAuth 2.0 with SWU Stats API.
Configuration can be set via environment variables or a .env file.
"""

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .oauth import OAuthService

# =============================================================================
# API Configuration
# =============================================================================

# API base URL for SWU Stats
SWUSTATS_API_BASE = os.getenv(
    "SWUSTATS_API_BASE",
    "https://swustats.net/TCGEngine/APIs"
)

# =============================================================================
# OAuth 2.0 Configuration
# =============================================================================

# OAuth client credentials (required - register at SWU Stats)
OAUTH_CLIENT_ID = os.getenv("SWUSTATS_CLIENT_ID", "")
OAUTH_CLIENT_SECRET = os.getenv("SWUSTATS_CLIENT_SECRET", "")

# OAuth endpoints
OAUTH_AUTHORIZE_URL = f"{SWUSTATS_API_BASE}/OAuth/authorize.php"
OAUTH_TOKEN_URL = f"{SWUSTATS_API_BASE}/OAuth/token.php"
OAUTH_USERINFO_URL = f"{SWUSTATS_API_BASE}/OAuth/userinfo.php"

# OAuth scope (space-separated list of permissions)
OAUTH_SCOPE = os.getenv("SWUSTATS_OAUTH_SCOPE", "openid profile decks")

# =============================================================================
# Redirect URI Configuration
# =============================================================================
# The redirect URI must match exactly what you registered with SWU Stats.
# For local development, this is typically http://localhost:PORT/oauth/callback
# For production, use your deployed domain.

# Server configuration
SERVER_HOST = os.getenv("SERVER_HOST", "localhost")
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))
SERVER_BASE_URL = os.getenv(
    "SERVER_BASE_URL",
    f"http://{SERVER_HOST}:{SERVER_PORT}"
)

# OAuth redirect URI - this is where SWU Stats will redirect after authorization
# Can be overridden for production deployments
OAUTH_REDIRECT_URI = os.getenv(
    "SWUSTATS_REDIRECT_URI",
    f"{SERVER_BASE_URL}/oauth/callback"
)

# =============================================================================
# Legacy Support (deprecated - use OAuth instead)
# =============================================================================

# Legacy hardcoded access token - only used if OAuth is not configured
# This is deprecated and will be removed in a future version
SWUSTATS_ACCESS_TOKEN = os.getenv("SWUSTATS_ACCESS_TOKEN", "")


def is_oauth_configured() -> bool:
    """Check if OAuth credentials are configured."""
    return bool(OAUTH_CLIENT_ID and OAUTH_CLIENT_SECRET)


def create_oauth_service() -> "OAuthService":
    """
    Create and configure the OAuth service.
    
    Returns:
        Configured OAuthService instance
    
    Raises:
        ValueError: If OAuth is not properly configured
    """
    from .oauth import OAuthService, OAuthConfig, OAuthTokenStore
    
    if not is_oauth_configured():
        raise ValueError(
            "OAuth not configured. Please set SWUSTATS_CLIENT_ID and "
            "SWUSTATS_CLIENT_SECRET environment variables. "
            "Register your application at https://swustats.net to get credentials."
        )
    
    config = OAuthConfig(
        client_id=OAUTH_CLIENT_ID,
        client_secret=OAUTH_CLIENT_SECRET,
        authorize_url=OAUTH_AUTHORIZE_URL,
        token_url=OAUTH_TOKEN_URL,
        userinfo_url=OAUTH_USERINFO_URL,
        redirect_uri=OAUTH_REDIRECT_URI,
        scope=OAUTH_SCOPE,
    )
    
    return OAuthService(config)


async def get_access_token(user_id: str = "default") -> str | None:
    """
    Get a valid access token for API requests.
    
    This function handles the complexity of OAuth vs legacy token:
    1. If OAuth is configured, gets token from OAuth service (with auto-refresh)
    2. Falls back to legacy hardcoded token if OAuth not configured
    
    Args:
        user_id: User identifier for OAuth token lookup
    
    Returns:
        Access token string, or None if not authenticated
    """
    if is_oauth_configured():
        from .oauth import get_oauth_service
        oauth = get_oauth_service()
        return await oauth.get_valid_token(user_id)
    
    # Legacy fallback
    if SWUSTATS_ACCESS_TOKEN:
        return SWUSTATS_ACCESS_TOKEN
    
    return None
