# Standalone deckbuilding workspace

Open http://localhost:8000/ for the standalone builder (separate from the personal ChatGPT app on port 8002).

## Working together

1. Choose a deck from the compact library. Search, Favorites, Recent (opened on this device), and sorting are available.
2. The selected deck is explicit above the composer and in the collection. Navigation collapses; drag the separator or focus it and use Left/Right to resize the deck pane (35–60%, 48% default).
3. Choose an improvement goal or describe your own. The assistant reads the current draft, looks up verified cards, and produces an adds/cuts table with reasons.
4. Review **Apply changes**, **Adjust proposal**, or **Dismiss**. Apply modifies only the local draft. **Undo** restores the previous draft (up to 20 steps).
5. **Export draft** downloads card IDs/counts in a deck JSON document. It does not save back to SWUStats.

Conversation and draft state are stored locally under the ignored backend `.workspace/` folder. Switching decks preserves each draft in that conversation. Reloads restore the last conversation on this device. Different conversations have separate drafts. Protect/backup that directory if you want to keep your work.

The transcript and fixed composer render in React, using the existing ChatKit backend event stream. No remote ChatKit UI iframe is needed. Basic message text, links, bold text, deck-list widgets, card-search text, history, streaming, and widget actions are supported.

Card metadata is cached from the [SWU-DB API](https://www.swu-db.com/api) for one day. The curve uses printed resource costs, not aspect penalties. The summary checks basic Premier deck size/copy counts; it is not a full format/ban/special-card legality validator. Missing metadata is labeled rather than guessed. Changes require known card identifiers; draft apply is revision-checked and one-time.

## Validation

From `backend`: `python -m unittest discover -s tests`

From `frontend`:

```powershell
node node_modules/typescript/bin/tsc --noEmit
node node_modules/eslint/bin/eslint.js . --ext ts,tsx --max-warnings=0
node node_modules/vite/bin/vite.js build
```

Run the backend with `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000` from `backend`. It serves the frontend build. Node 20.19+ or 22.12+ is recommended by the installed Vite version.

Browser acceptance checks covered a real agent proposal, applying and undoing local counts/curve changes, compact saved-deck widgets, active selection, keyboard resizing, and responsive layout. The test swap was undone; SWUStats was never modified.
