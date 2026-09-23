# Leader discovery

The standalone app now supports returning-player leader discovery from the navigation or the assistant. `discover_leaders` is the dedicated agent tool; semantic search is not the discovery mechanism.

The player confirms Premier/Eternal, a release window and an optional play style. The backend filters real Leader records, ranks them using saved leader aspects/traits/rules themes (favorites have triple weight), and shows five explained candidates with a diversity slot. These are tentative interest signals, not competitive rankings. More-like feedback outweighs library signals; Not-for-me excludes that exact leader. The comparison view shows aspects, deployment cost and inferred rules themes. Preferences and feedback are persisted per conversation after a successful search.

Choosing a leader and base creates a new conversation and a local draft with a negative numeric ID and `source=local`. It carries the format and build brief into the assistant. The existing proposal/apply/undo/export workflow handles the starting shell. No SWUStats deck is created or changed. Local drafts are never fetched as remote deck IDs by `ensure_draft`.

## Data and limits

SWU-DB supplies card identities, both sides of rules text, aspects, traits, images and printings. The catalog caches these for 24 hours. Reprints are joined by exact full card name (including subtitle) and type; a reprint does not count as a newly released leader. Unknown products and future previews are excluded from discovery.

`backend/app/discovery.py` contains a manually maintained release/rotation/known-suspension snapshot, checked September 19, 2026. It becomes visibly stale after September 26. It is **not** a live authoritative legality feed or complete deck validator. Adding a set, rotating the pool or updating suspensions requires updating this snapshot and its source links. Current recorded Premier pool is JTL through ASH. The UI deliberately describes recorded eligibility, not certified tournament legality. Draft additions with a chosen format are checked against this same recorded pool. Special deck construction rules and aspect penalties still need a complete validator.

Source pages are linked in the UI. The current rotation rule comes from the official Updates and Rotations article; suspension information comes from the official Cad Banned and Eternal Format Update: April 2026 articles. Release dates come from the official product pages. The snapshot omits supplemental products with unverified release/format status.

Rules themes use transparent text heuristics, not a trained preference model. Saved decks do not establish ownership of physical cards, budget, games played or win rate. Those claims are not made. Full-card rules are available on each recommendation to assess its actual plan.

## SWUStats API follow-up (separate repository)

**No API change blocks this version.** `GetUserDecks.php` already supplies `keyIndicator1`, `keyIndicator2`, deck name and `is_favorite` for personalization. Unconnected players can browse by explicit preferences.

For reliable production upkeep, the most valuable addition would be a machine-readable card/format endpoint with stable gameplay identity, all printings, set release dates, format eligibility, suspension effective/expiry dates, source URL and `verified_at`. Prefer an authoritative upstream rules feed if available; do not mark an old snapshot fresh merely because it was served again. This would replace the manual snapshot and cover supplemental products.

Optional personalization improvements: deck `updated_at`, explicitly recorded format, last-played date and aggregated match counts by leader. Any competitive ranking would additionally need dated format-specific matchup samples and sample sizes. A distinct, authorized deck-create/update API is needed to publish drafts back to SWUStats; discovery itself does not require write access.

## Validation

Run `python -m unittest discover -s tests` in `backend`, and TypeScript, ESLint and Vite build checks in `frontend`. Discovery tests cover release/rotation boundaries, unknown previews, suspension identity, reprints/deduplication, profile weighting, feedback, stale snapshots and local draft persistence/proposal/undo without remote reads or saved-deck mutation.
