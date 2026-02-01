"""
OAuth 2.0 implementation for SWU Stats API.

This module handles the complete OAuth 2.0 authorization code flow including:
- Authorization URL generation
- Token exchange
- Token refresh
- Token storage and retrieval
"""

from __future__ import annotations

import logging
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import json
import os
import httpx
from urllib.parse import urlencode

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class OAuthToken:
    """Represents an OAuth token with metadata."""
    access_token: str
    refresh_token: str | None = None
    token_type: str = "Bearer"
    expires_at: float | None = None  # Unix timestamp
    scope: str | None = None
    
    @property
    def is_expired(self) -> bool:
        """Check if the token is expired (with 5 min buffer)."""
        if self.expires_at is None:
            return False
        return time.time() >= (self.expires_at - 300)  # 5 min buffer
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "token_type": self.token_type,
            "expires_at": self.expires_at,
            "scope": self.scope,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OAuthToken":
        """Create from dictionary."""
        return cls(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            token_type=data.get("token_type", "Bearer"),
            expires_at=data.get("expires_at"),
            scope=data.get("scope"),
        )


@dataclass
class OAuthConfig:
    """OAuth configuration settings."""
    client_id: str
    client_secret: str
    authorize_url: str
    token_url: str
    userinfo_url: str
    redirect_uri: str
    scope: str = "openid profile"


class OAuthTokenStore:
    """
    Persistent storage for OAuth tokens.
    
    Stores tokens in a JSON file for persistence across server restarts.
    In production, you might want to use a database or secure vault.
    """
    
    def __init__(self, storage_path: Path | None = None):
        if storage_path is None:
            # Default to a file in the app directory
            storage_path = Path(__file__).parent / ".oauth_tokens.json"
        self.storage_path = storage_path
        self._tokens: dict[str, OAuthToken] = {}
        self._load()
    
    def _load(self) -> None:
        """Load tokens from disk."""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r") as f:
                    data = json.load(f)
                    self._tokens = {
                        k: OAuthToken.from_dict(v) 
                        for k, v in data.items()
                    }
                logger.info(f"📁 Loaded {len(self._tokens)} OAuth tokens from storage")
            except Exception as e:
                logger.warning(f"⚠️ Failed to load OAuth tokens: {e}")
                self._tokens = {}
    
    def _save(self) -> None:
        """Save tokens to disk."""
        try:
            data = {k: v.to_dict() for k, v in self._tokens.items()}
            with open(self.storage_path, "w") as f:
                json.dump(data, f, indent=2)
            logger.info(f"💾 Saved {len(self._tokens)} OAuth tokens to storage")
        except Exception as e:
            logger.error(f"❌ Failed to save OAuth tokens: {e}")
    
    def get(self, user_id: str = "default") -> OAuthToken | None:
        """Get token for a user."""
        return self._tokens.get(user_id)
    
    def set(self, token: OAuthToken, user_id: str = "default") -> None:
        """Store token for a user."""
        self._tokens[user_id] = token
        self._save()
    
    def delete(self, user_id: str = "default") -> None:
        """Delete token for a user."""
        if user_id in self._tokens:
            del self._tokens[user_id]
            self._save()
    
    def has_valid_token(self, user_id: str = "default") -> bool:
        """Check if user has a valid (non-expired) token."""
        token = self.get(user_id)
        return token is not None and not token.is_expired


class OAuthService:
    """
    OAuth 2.0 service for SWU Stats API.
    
    Handles the complete OAuth flow including:
    - Generating authorization URLs with state
    - Exchanging authorization codes for tokens
    - Refreshing expired tokens
    - Validating and retrieving tokens
    """
    
    def __init__(self, config: OAuthConfig, token_store: OAuthTokenStore | None = None):
        self.config = config
        self.token_store = token_store or OAuthTokenStore()
        self._pending_states: dict[str, dict[str, Any]] = {}  # state -> metadata
    
    def get_authorization_url(self, user_id: str = "default", extra_params: dict[str, str] | None = None, include_state: bool = False) -> tuple[str, str | None]:
        """
        Generate an authorization URL for the OAuth flow.
        
        Args:
            user_id: User identifier for token storage
            extra_params: Additional parameters to include in the URL
            include_state: Whether to include CSRF protection state parameter
        
        Returns:
            Tuple of (authorization_url, state)
        """
        state = None
        if include_state:
            state = secrets.token_urlsafe(32)
            # Store state with metadata for validation
            self._pending_states[state] = {
                "user_id": user_id,
                "created_at": time.time(),
            }
        
        params = {
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
            "response_type": "code",
            "scope": self.config.scope,
        }
        
        if state:
            params["state"] = state
        
        if extra_params:
            params.update(extra_params)
        
        # Build URL with proper URL encoding
        query_string = urlencode(params)
        auth_url = f"{self.config.authorize_url}?{query_string}"
        
        logger.info(f"🔐 Generated authorization URL for user {user_id}")
        return auth_url, state
    
    def validate_state(self, state: str) -> dict[str, Any] | None:
        """
        Validate an OAuth state parameter.
        
        Args:
            state: The state parameter from the callback
        
        Returns:
            State metadata if valid, None otherwise
        """
        if state not in self._pending_states:
            logger.warning(f"⚠️ Invalid OAuth state: {state}")
            return None
        
        metadata = self._pending_states.pop(state)
        
        # Check if state is too old (10 minutes)
        if time.time() - metadata["created_at"] > 600:
            logger.warning(f"⚠️ OAuth state expired: {state}")
            return None
        
        return metadata
    
    async def exchange_code(self, code: str, state: str | None = None, user_id: str = "default") -> OAuthToken | None:
        """
        Exchange an authorization code for tokens.
        
        Args:
            code: The authorization code from the callback
            state: The state parameter for validation (optional)
            user_id: User identifier (used when state is not provided)
        
        Returns:
            OAuthToken if successful, None otherwise
        """
        # If state is provided, validate it and get user_id from metadata
        if state:
            metadata = self.validate_state(state)
            if metadata is None:
                logger.warning("⚠️ State validation failed, but continuing with default user_id")
            else:
                user_id = metadata.get("user_id", user_id)
        
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    self.config.token_url,
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": self.config.redirect_uri,
                        "client_id": self.config.client_id,
                        "client_secret": self.config.client_secret,
                    },
                    timeout=30.0,
                )
                
                logger.info(f"📥 Token exchange response status: {resp.status_code}")
                logger.info(f"📥 Token exchange response: {resp.text[:500]}")
                
                resp.raise_for_status()
                data = resp.json()
                
                # Calculate expiration time
                expires_at = None
                if "expires_in" in data:
                    expires_at = time.time() + int(data["expires_in"])
                
                token = OAuthToken(
                    access_token=data["access_token"],
                    refresh_token=data.get("refresh_token"),
                    token_type=data.get("token_type", "Bearer"),
                    expires_at=expires_at,
                    scope=data.get("scope"),
                )
                
                # Store the token
                self.token_store.set(token, user_id)
                logger.info(f"✅ Successfully exchanged code for tokens (user: {user_id})")
                
                return token
                
        except httpx.HTTPStatusError as e:
            logger.error(f"❌ Token exchange failed: {e.response.status_code} - {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"❌ Token exchange error: {e}", exc_info=True)
            return None
    
    async def refresh_token(self, user_id: str = "default") -> OAuthToken | None:
        """
        Refresh an expired access token using the refresh token.
        
        Args:
            user_id: User identifier
        
        Returns:
            New OAuthToken if successful, None otherwise
        """
        current_token = self.token_store.get(user_id)
        if current_token is None or current_token.refresh_token is None:
            logger.warning(f"⚠️ No refresh token available for user {user_id}")
            return None
        
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    self.config.token_url,
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": current_token.refresh_token,
                        "client_id": self.config.client_id,
                        "client_secret": self.config.client_secret,
                    },
                    timeout=30.0,
                )
                resp.raise_for_status()
                data = resp.json()
                
                # Calculate expiration time
                expires_at = None
                if "expires_in" in data:
                    expires_at = time.time() + int(data["expires_in"])
                
                # Some servers don't return a new refresh token
                new_refresh_token = data.get("refresh_token", current_token.refresh_token)
                
                token = OAuthToken(
                    access_token=data["access_token"],
                    refresh_token=new_refresh_token,
                    token_type=data.get("token_type", "Bearer"),
                    expires_at=expires_at,
                    scope=data.get("scope", current_token.scope),
                )
                
                # Store the new token
                self.token_store.set(token, user_id)
                logger.info(f"🔄 Successfully refreshed token for user {user_id}")
                
                return token
                
        except httpx.HTTPStatusError as e:
            logger.error(f"❌ Token refresh failed: {e.response.status_code} - {e.response.text}")
            # If refresh fails, delete the invalid tokens
            self.token_store.delete(user_id)
            return None
        except Exception as e:
            logger.error(f"❌ Token refresh error: {e}", exc_info=True)
            return None
    
    async def get_valid_token(self, user_id: str = "default") -> str | None:
        """
        Get a valid access token, refreshing if necessary.
        
        This is the main method tools should use to get tokens.
        
        Args:
            user_id: User identifier
        
        Returns:
            Valid access token string, or None if not authenticated
        """
        token = self.token_store.get(user_id)
        
        if token is None:
            logger.info(f"🔒 No token found for user {user_id}")
            return None
        
        # If token is expired, try to refresh
        if token.is_expired:
            logger.info(f"⏰ Token expired for user {user_id}, attempting refresh...")
            token = await self.refresh_token(user_id)
            if token is None:
                return None
        
        return token.access_token
    
    async def get_user_info(self, user_id: str = "default") -> dict[str, Any] | None:
        """
        Get user information from the OAuth provider.
        
        Args:
            user_id: User identifier
        
        Returns:
            User info dict if successful, None otherwise
        """
        access_token = await self.get_valid_token(user_id)
        if access_token is None:
            return None
        
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    self.config.userinfo_url,
                    params={"access_token": access_token},
                    timeout=10.0,
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.error(f"❌ Failed to get user info: {e}")
            return None
    
    def is_authenticated(self, user_id: str = "default") -> bool:
        """Check if user has stored tokens (may be expired)."""
        return self.token_store.get(user_id) is not None
    
    def logout(self, user_id: str = "default") -> None:
        """Remove stored tokens for a user."""
        self.token_store.delete(user_id)
        logger.info(f"🚪 Logged out user {user_id}")


# Singleton instance - initialized in config.py
_oauth_service: OAuthService | None = None


def get_oauth_service() -> OAuthService:
    """Get the global OAuth service instance."""
    global _oauth_service
    if _oauth_service is None:
        from .config import create_oauth_service
        _oauth_service = create_oauth_service()
    return _oauth_service


def set_oauth_service(service: OAuthService) -> None:
    """Set the global OAuth service instance (for testing)."""
    global _oauth_service
    _oauth_service = service
