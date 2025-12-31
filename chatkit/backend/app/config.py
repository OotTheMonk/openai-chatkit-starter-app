"""
Shared configuration for the ChatKit backend.
"""

import os

# SWU Stats API access token
# Can be overridden via environment variable
SWUSTATS_ACCESS_TOKEN = os.getenv(
    "SWUSTATS_ACCESS_TOKEN",
    "f11a7e328ccf39ff5438af87706fc754ba124a94"
)

# API base URL
SWUSTATS_API_BASE = "https://swustats.net/TCGEngine/APIs"
