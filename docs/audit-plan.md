# Ferret Codebase Audit — April 2026

## Summary Stats

| Severity | Count |
|----------|-------|
| Critical | 1     |
| High     | 4     |
| Medium   | 7     |
| Low      | 6     |
| **Total** | **18** |

| Category     | Count |
|--------------|-------|
| Security     | 2     |
| Bug          | 4     |
| Dead code    | 2     |
| Code quality | 4     |
| Tech debt    | 3     |
| Testing      | 1     |
| Dependencies | 1     |
| Process      | 1     |

## Issues by Severity

### Critical
| # | Title | Category | Effort |
|---|-------|----------|--------|
| 1 | .env contains real API tokens and secrets | Security | Small |

### High
| # | Title | Category | Effort |
|---|-------|----------|--------|
| 2 | Misleading Sonarr method name | Bug/Naming | Small |
| 3 | Duplicate items flagged across overlapping cleanup rules | Bug | Medium |
| 4 | Dashboard exclude writes to .env (doesn't persist in Docker) | Bug | Medium |
| 5 | Dead templates, stale .env vars, orphaned WEB_DASHBOARD.md | Dead code | Small |

### Medium
| # | Title | Category | Effort |
|---|-------|----------|--------|
| 6 | No tests exist in the codebase | Testing | Large |
| 7 | Cleanup engine re-fetches Sonarr/Radarr data in deletion path | Performance | Small |
| 8 | protected_count inflated — counts same item once per rule | Bug | Small |
| 9 | Settings save missing new keys and Sonarr/Radarr/Cleanup settings | Tech debt | Medium |
| 10 | CI lint job silently passes — ruff errors piped to true | CI | Small |
| 11 | Redundant code in JellyfinEmby (duplicate get/post, no-op list copies) | Code quality | Small |
| 12 | JellyfinEmby library dedup check compares wrong dict | Bug | Small |
| 13 | Stale .env references to Tautulli | Config | Small |
| 15 | Dashboard exposes API tokens without auth or CSRF | Security | Medium |
| 19 | JellyfinEmby update_user_watched returns early on episode failure | Bug | Small |

### Low
| # | Title | Category | Effort |
|---|-------|----------|--------|
| 14 | Minor code quality issues (6 items) | Code quality | Small |
| 16 | 24 unpushed commits on main | Process | Small |
| 17 | CDN dependency for Tailwind CSS | Dependencies | Medium |
| 18 | ferret-logo.png tracked but unused | Dead code | Small |
| 20 | Missing .env.example for public repo | DX | Small |

## Recommended Order

### Phase 1: Security & Critical Fixes (do first)
1. **#1** — Create `.env.example`, verify no secrets in git history, rotate if needed
2. **#15** — Add auth warning banner, stop pre-filling tokens in settings HTML
3. **#16** — Push the 24 unpushed commits and deploy

### Phase 2: Bug Fixes (high impact, low effort)
4. **#2** — Rename `get_ended_unmonitored_series` → `get_ended_still_monitored_series`
5. **#12** — Fix the library dedup guard in `jellyfin_emby.py:514`
6. **#19** — Change `return` to `continue` in `jellyfin_emby.py:704`
7. **#8** — Use a set for protected titles to prevent inflation
8. **#3** — Deduplicate flagged items across cleanup rules

### Phase 3: Cleanup & Persistence (medium effort)
9. **#4** — Store exclusions in cleanup_state.json instead of .env
10. **#5** — Remove dead templates, endpoints, WEB_DASHBOARD.md
11. **#13** — Clean up stale Tautulli config
12. **#20** — Create .env.example

### Phase 4: Code Quality (when convenient)
13. **#10** — Remove `|| true` from CI lint
14. **#11** — Refactor JellyfinEmby.query(), remove no-op list copies
15. **#7** — Cache Sonarr/Radarr data between scan and deletion
16. **#9** — Expand settings page and fix save logic
17. **#14** — Address minor quality items when touching those files

### Phase 5: Long-term (plan separately)
18. **#6** — Write unit tests for critical paths
19. **#17** — Build Tailwind at image build time (optional)

## Quick Wins (< 5 min each)
- **#2** — rename one method
- **#12** — change one dict key check
- **#19** — change `return` to `continue`
- **#8** — add a set for dedup
- **#18** — `git rm ferret-logo.png`
- **#5** (partial) — `git rm WEB_DASHBOARD.md`
- **#10** — remove `|| true` from one CI line

## Dependency Chain
- #4 (exclusion persistence) should be done before #3 (dedup), since fixing persistence changes how exclusions work
- #1 (secrets) should be done before #16 (push), to ensure nothing sensitive is pushed
- #5 (dead templates) should verify no htmx polling targets those endpoints before deletion

## Estimated Effort
- **Small** (< 30 min): #1, #2, #5, #7, #8, #10, #11, #12, #13, #14, #16, #18, #19, #20
- **Medium** (30 min - 2 hrs): #3, #4, #9, #15, #17
- **Large** (2+ hrs): #6
