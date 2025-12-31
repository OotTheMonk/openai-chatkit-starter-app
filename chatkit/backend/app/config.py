"""
Shared configuration for the ChatKit backend.
"""

import os

# SWU Stats API access token
# Can be overridden via environment variable
SWUSTATS_ACCESS_TOKEN = os.getenv(
    "SWUSTATS_ACCESS_TOKEN",
    "4fd1d0367088595aa4466645d495fc8e471e24f2"
)

# API base URL
SWUSTATS_API_BASE = "https://swustats.net/TCGEngine/APIs"
