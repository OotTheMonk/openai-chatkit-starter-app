# ChatKit Starter

Minimal Vite + React UI paired with a FastAPI backend that forwards chat
requests to OpenAI through the ChatKit server library.

## Quick start

**For local development with OAuth:**

```bash
# One-time setup
cd backend
cp .env.example .env
# Edit .env and add your SWUSTATS_CLIENT_ID and SWUSTATS_CLIENT_SECRET

# Start everything (from the chatkit directory)
cd ..
python dev_start.py
```

This automatically starts both frontend and backend with ngrok configured.

**For production or simple testing:**

```bash
npm install
npm run dev
```

What happens:

- `python dev_start.py` starts both backend (with ngrok) and frontend in separate windows
- `npm run dev` starts the FastAPI backend on `127.0.0.1:8000` and the Vite
  frontend on `127.0.0.1:3000` with a proxy at `/chatkit`.

## Required environment

- `OPENAI_API_KEY` (backend)
- `VITE_CHATKIT_API_URL` (optional, defaults to `/chatkit`)
- `VITE_CHATKIT_API_DOMAIN_KEY` (optional, defaults to `domain_pk_localhost_dev`)

Set `OPENAI_API_KEY` in your shell or in `.env.local` at the repo root before
running the backend. Register a production domain key in the OpenAI dashboard
and set `VITE_CHATKIT_API_DOMAIN_KEY` when deploying.

## SWU Stats OAuth Setup

This application uses OAuth 2.0 to authenticate with SWU Stats for accessing
user decks and other protected features.

### Quick Setup (with automatic ngrok)

1. Register at [SWU Stats](https://swustats.net) and get your **Client ID** and **Client Secret**

2. Copy and configure `.env`:
   ```bash
   cd backend
   cp .env.example .env
   ```

3. Edit `.env` with your credentials:
   ```env
   SWUSTATS_CLIENT_ID=your_client_id
   SWUSTATS_CLIENT_SECRET=your_client_secret
   ```

4. **For local development**, use the automatic dev startup script:
   ```bash
   # From the backend directory
   python dev_run.py
   ```
   
   This automatically:
   - Installs/starts ngrok (if needed)
   - Creates a public tunnel to your localhost
   - Updates your `.env` with the correct redirect URI
   - Displays your dev URL

5. When prompted, update your SWU Stats app registration's redirect URI with the ngrok URL shown

### Manual Setup (without automatic ngrok)

If you prefer manual configuration:

1. Install ngrok: https://ngrok.com/download

2. Start ngrok separately:
   ```bash
   ngrok http 8000
   # Note the URL, e.g., https://abc123.ngrok.io
   ```

3. Update `.env`:
   ```env
   SERVER_BASE_URL=https://abc123.ngrok.io
   SWUSTATS_REDIRECT_URI=https://abc123.ngrok.io/oauth/callback
   ```

4. Start the backend normally:
   ```bash
   python -m uvicorn main:app --reload
   ```

### 1. Register your application

1. Go to [SWU Stats](https://swustats.net) and register your application
2. You'll receive a **Client ID** and **Client Secret**
3. Register your redirect URI(s):
   - For local development: The ngrok URL (shown when you run `dev_run.py`)
   - For production: `https://your-domain.com/oauth/callback`

### 2. Configure environment variables

Copy the example environment file and fill in your credentials:

```bash
cd backend
cp .env.example .env
```

Edit `.env` with your OAuth credentials:

```env
SWUSTATS_CLIENT_ID=your_client_id
SWUSTATS_CLIENT_SECRET=your_client_secret
```

### 3. OAuth endpoints

The backend provides these OAuth endpoints:

| Endpoint | Description |
|----------|-------------|
| `GET /oauth/login` | Initiates OAuth flow, redirects to SWU Stats |
| `GET /oauth/callback` | Handles OAuth callback, exchanges code for tokens |
| `GET /oauth/status` | Check authentication status |
| `GET /oauth/userinfo` | Get authenticated user info |
| `POST /oauth/logout` | Clear stored tokens |

### 4. For production deployment

Update your `.env` for production:

```env
SERVER_BASE_URL=https://your-domain.com
SWUSTATS_REDIRECT_URI=https://your-domain.com/oauth/callback
```

Make sure the redirect URI in your `.env` matches exactly what you registered
with SWU Stats.

## Customize

- Update UI and connection settings in `frontend/src/lib/config.ts`.
- Adjust layout in `frontend/src/components/ChatKitPanel.tsx`.
- Swap the in-memory store in `backend/app/server.py` for persistence.
