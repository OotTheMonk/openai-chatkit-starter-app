# Turn-one residual board simulation: proof of concept

## Goal

Estimate how often a working deck has surviving units after the opponent gets the first attack of round two. The run uses real SWUSim setup and actions so the same runner can later stop at a later checkpoint. A result describes this scripted opening under the named play policies; it is not a match win-rate estimate.

## Existing seams

- `TCGEngine/DevTools/SWUSimBotSelfPlayTest.php` starts two real decks in bot practice with a reproducible seed, forced first player, and a separate chooser for each seat. Its setup path includes the real pregame decisions and resourcing.
- `TCGEngine/SWUSim/BotLegalActions.php` enumerates legal free-play actions and uses `DevTools/TestAutomationBridge.php` for decision answers. `BotController.php` applies the chosen action through the engine.
- `TCGEngine/SWUSim/BotHeuristic.php` registers chooser policies. `Tests/BotFixtures/meta-2026-09/` and `meta-2026-09-field/` contain candidate opposing lists.
- This app already holds the current working draft, its revision, leader, base, and main-deck card IDs and counts in `starter/chatkit/backend/app/deck_state.py`.

## First runnable slice

Add a separate SWUSim CLI runner using the self-play setup and action loop. Do not change the existing full-game harness's stopping behavior. Inputs are two complete deck lists, a seed, the opponent's first-player seat, and policy IDs. The app can initially invoke it with one working-deck snapshot and one selected fixture; batch pairings can follow.

1. Start a normal game. Let the engine handle shuffle, opening hands, mulligan, starting resources, card effects, priority, and regroup. Every stochastic choice comes from the seeded engine state.
2. During round one, each policy chooses from actual legal actions. The opening policy prefers deploying a unit, but permits a second play when legal, including two one-cost units or cost-changing effects. It must respond to any card decisions those plays create. If no desired play is available, it claims initiative or passes according to its rule. Record every action and its policy rule.
3. Advance through the normal regroup. In round two, the opponent selects its first legal unit attack against one of our units. If several attacker/defender pairs are legal, evaluate each by applying the attack to a copied game state, including triggered abilities and choices. Select the outcome that is best for the opponent by the board metric below. If no such attack is legal, stop with `no_unit_attack` and record why. Do not invent a cross-arena target or assume an attack is legal from printed stats.
4. Stop after that attack and all resulting decisions and triggers resolve. Save the board before attack and at the stop point. A later experiment can move the checkpoint to our first attack or an entire round.

The first implementation should accept existing fixture deck files directly. The app adapter can then serialize its working draft to the fixture format in a temporary file, pinned to deck ID and revision. The sideboard is excluded unless a later experiment adds sideboarding. Reject missing or unmapped card IDs and invalid deck lists explicitly.

## Play policy contract

Keep action choice separate from legal-action enumeration and engine execution. A policy receives a read-only state summary, the current decision context, and the exact legal candidates. It returns one candidate ID plus a rule ID and a short explanation. The runner checks membership in the candidate set before applying it. No policy writes game state directly.

Start with a small, versioned rule set for opening decisions: mulligan, starting resource, unit choice, follow-up play, initiative/pass, card-trigger answers, and best-trade attack. The AI can propose or edit these rules as code, but changes run in a development/test workflow and receive a new policy version; a simulation request selects a known version. This makes results repeatable and lets us compare a changed rule against the previous one on the same deck pair and seeds. The existing heuristic policies are useful baselines, but they should not silently decide scenario-specific actions.

For the best-trade step, evaluate the *resolved* candidate attack states. Rank them from the opponent's perspective by (1) opponent surviving-unit count minus our surviving-unit count, (2) opponent surviving total remaining unit health minus ours, then (3) base-health swing. Keep this ranking configurable. An equal-body trade may still be the best available attack. If applying a candidate fails or presents an unsupported decision, mark the sample failed rather than scoring a guessed outcome.

## Per-sample output

Return machine-readable JSON with: deck snapshot hash/revision, opponent fixture and source date, engine and policy versions, seed, seats, first player, opening hand and mulligan/resource choices, ordered action trace, legal attack candidates considered, selected attack, both arena boards before and after combat, base health on each side, stop reason, and any engine/policy error. Store card IDs alongside names so a report can be audited and replayed.

Primary metric: surviving unit count for each player and the difference (ours minus opponent's) after the attack. Report ground and space counts separately as well as the total. Secondary metric: remaining health on surviving units, also by player and arena. Base health stays a separate axis. A sample with no legal unit attack remains in the denominator and gets its own outcome category; it must not be silently treated as a favorable trade.

Aggregate by opponent fixture and across fixtures: sample count, successful/failed count, rates of ahead/equal/behind on surviving units, `no_unit_attack` rate, mean surviving-unit difference, and the distribution of remaining unit health and base health. Show the most common opening lines and links to individual seeds. Keep the opponent deck/version and policy/version visible beside every result.

## Integration order and checks

1. Build the CLI runner in TCGEngine around the existing self-play setup. Run one fixed seed with two existing fixture files and inspect the action trace and checkpoint.
2. Add an exact replay check: same deck files, policy versions, seed, and engine revision must produce the same trace and result. Add a combat fixture with a clear kill-survive, a mutual trade, a different-arena unit, and a two-one-drop opening.
3. Run a small paired-seed sweep against one curated meta fixture. Fail samples loudly on an unhandled decision, rejected action, non-progress loop, or missing checkpoint. Do not count failed samples as board losses.
4. Add the app-side draft-to-fixture adapter and a read-only simulation endpoint. Pin each run to a deck revision so editing the draft cannot relabel old results. Then add the first UI report.

The current self-play `--max-rounds` cap is not the desired checkpoint: it stops by round number and reports game completion as its success criterion. The new runner needs a checkpoint result and partial-game success criterion.
