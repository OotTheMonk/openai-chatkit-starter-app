# Deck construction and editing

The agent now has an explicit construction workflow:

1. Read the working draft and set a build plan (opening turns, stabilization, win condition, dependencies and adjustable role/curve targets).
2. Retrieve aggregate statistical context for the exact leader and base. `get_build_candidates` performs this research and samples candidates across early units, midgame units, interaction, healing, defense, draw, space and finishers instead of ranking shared words.
3. Analyze the exact proposed changes. Analysis includes cost plus ordinary aspect penalties, curve, early units, opening-hand probability, role signals, conditional cards, unknown metadata, and quantity warnings.
4. Revise if needed, analyze again, then propose. The agent tool rejects proposals whose exact changes, build preferences, deck identity or revision differ from the analyzed version. The construction review and statistical evidence are attached to the review UI.

Strategic targets and roles are heuristics, not a proven optimizer or full rules engine. A role signal such as the word Sentinel can mean granting it to another unit; the assistant must inspect the full text and dependencies. Effective costs do not model alternative payment, discounts or special rules. The six-card opening probability excludes mulligans and uses a hypergeometric calculation. Small requested shells can be proposed, but are explicitly marked incomplete.

## SWUStats evidence for original playstyles

The builder now uses aggregate statistics, not reference decks. It does not fetch saved/public lists as construction templates, and the former public-reference URL adapter has been removed. Saved decks may still inform leader discovery preferences.

`research_build_statistics` calls the existing read-only `DeckMetaMatchupStatsAPI.php` and `CardMetaStatsAPI.php`. The latter returns a bulk array in live testing despite the single-card documentation example. Cards are matched by numeric ID; the bulk response is cached for 30 minutes by format/window. Live matchup queries use SET_NNN identifiers, so catalog printings map local card IDs to those keys. Opponent legacy color-only bases are labeled with unspecified type.

The default window is explicitly **all-time**, not recent meta. Optional `start_week`/`end_week` tool arguments pass known API week IDs without guessing a calendar mapping. Empty observations and unavailable services do not disqualify experimental cards. The adapter backs off for a minute after request errors and does not silently pass old cached evidence as fresh.

Candidate generation balances role and cost coverage without ranking by statistical popularity. It attaches candidate observations to the assistant's context; proposals also capture statistics for their added cards, visibly credited to SWUStats. Tables distinguish included observations from played observations and preserve missing values. A displayed when-played win rate is conditional, selection-biased and not the causal benefit of adding a card. Matchup aggregates span multiple lists/pilots, not this draft. No claim of proven strength or unique novelty follows from these data.

The assistant should start with the desired fun playstyle, propose a rules-grounded synergy hypothesis, explain supporting/conflicting observations and suggest a focused playtest. Targets remain adjustable. Original ideas with small or no samples remain valid candidates. Statistical validation and strategic quality are separate: passing software tests does not establish that the generated deck is competitive.

## Manual editing

Each row in the main deck and sideboard has Remove one and Remove all controls. Edits apply to the local working draft only, invalidate pending proposals, increment the revision, and can be undone. Requests carry both the active deck ID and revision so stale screens cannot modify another deck. Persistence uses the existing draft store.

The printed-cost curve follows the selected section. Clicking a cost toggles the filter; 7+ includes all higher costs, and Clear cost filter restores every card. Unknown-cost cards remain visible when the filter is clear. Selecting another deck clears the filter. Proposal analysis separately uses effective costs including ordinary aspect penalties.
