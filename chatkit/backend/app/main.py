"""FastAPI entrypoint for the ChatKit starter backend."""

from __future__ import annotations

import logging
from pathlib import Path

from dotenv import load_dotenv

from chatkit.server import StreamingResult
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

# Load environment variables from .env file
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from .server import StarterChatServer

app = FastAPI(title="ChatKit Starter API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

chatkit_server = StarterChatServer()


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

# Serve the built frontend
frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")