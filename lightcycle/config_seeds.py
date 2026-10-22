_SEED_KEYS = [
    ("projects", "~/workspace/projects"),
    ("branch-prefix", "feat"),
    ("default-origin", "lightcycle"),
    ("workflows-remote", ""),
    ("max-agents", "5"),
    ("worktree-retries", "6"),
    ("worktree-retry-sleep", "0.25"),
    ("max-boot-seconds", "120"),
    ("max-session-seconds", "1800"),
    ("stall-seconds", "1800"),
    ("ci-check-ceiling-seconds", "3600"),
    ("ci-start-window-seconds", "600"),
    ("ci-no-workflows-wait-seconds", "60"),
    ("ci-unconfirmed-note-polls", "3"),
    ("release-hold-note-seconds", "60"),
    ("probe-cooldown-seconds", "1800"),
    ("spin-cap", "3"),
    ("poll-seconds", "5"),
    ("github-poll-seconds", "60"),
    ("github-reserve-calls", "750"),
    ("github-view-refresh-polls", "10"),
    ("worker-history", "20"),
    ("editor", "vi"),
    ("backups-dir", "~/.lightcycle-backups"),
    ("backup-interval-minutes", "15"),
    ("guidance-fetch-minutes", "5"),
    ("backup-retention", "96"),
    ("workflow-retention", "5"),
    ("max-title-length", "72"),
    ("tui-autostart-pool", "false"),
    ("tui-metrics", "false"),
    ("developer-mode", "false"),
    ("tui-upgrade-check-seconds", "900"),
    ("tui-doctor-check-seconds", "3600"),
    ("pool-upgrade-check-seconds", "900"),
    ("personal-origin", ""),
    ("price-sonnet-input-per-mtok", "2.00"),
    ("price-sonnet-output-per-mtok", "10.00"),
    ("price-sonnet-cache-write-per-mtok", "2.50"),
    ("price-sonnet-cache-read-per-mtok", "0.20"),
    ("price-opus-input-per-mtok", "5.00"),
    ("price-opus-output-per-mtok", "25.00"),
    ("price-opus-cache-write-per-mtok", "6.25"),
    ("price-opus-cache-read-per-mtok", "0.50"),
    ("price-haiku-input-per-mtok", "1.00"),
    ("price-haiku-output-per-mtok", "5.00"),
    ("price-haiku-cache-write-per-mtok", "1.25"),
    ("price-haiku-cache-read-per-mtok", "0.10"),
    ("shutdown-grace-seconds", "10"),
    ("tick-failure-cap", "5"),
    ("review-rounds-cap", "5"),
    ("context-artifact-types", "spec"),
    ("context-artifact-project", "specs"),
    ("audit-shortcode", "AUD"),
    ("held-comment-shortcode", "HLD"),
    ("guidance-shortcode", "GDN"),
    ("trusted-authors", ""),
    ("memory-reserve-fraction", "0.65"),
    ("guidance-budget-bytes", "6144"),
    ("guidance-unused-after-deliveries", "60"),
    ("guidance-dormant-days", "60"),
    ("schedules-paused", "false"),
    ("lifecycle-timeout-seconds", "300"),
    ("script-timeout-seconds", "300"),
    ("script-max-running", "4"),
]

_SEED_SCHEDULES = """\
schedule-retro-audit:
  enabled: true
  workflow: lightcycle/retro-audit
  project: guidance
  shortcode: AUD
  cron: 0 9 * * *
  guard: pending-reflections
  min: 30
schedule-material-audit:
  enabled: true
  workflow: lightcycle/material-audit
  project: guidance
  shortcode: AUD
  cron: 0 9 * * 1
  guard: materials-changed
schedule-daily-summary:
  enabled: true
  workflow: lightcycle/daily-summary
  project: guidance
  shortcode: SUM
  cron: 0 7 * * *
  guard: day-unsummarised
schedule-ratchet-sweep:
  enabled: true
  workflow: lightcycle/ratchet-sweep
  project: guidance
  shortcode: AUD
  cron: 0 9 * * 1
  guard: repos-active
"""


def default_config_text():
    return "".join("%s: %s\n" % (k, v) for k, v in _SEED_KEYS) + _SEED_SCHEDULES


def missing_seed_keys(existing):
    return [(k, v) for k, v in _SEED_KEYS if k not in existing]


def seed_key_names():
    return {k for k, v in _SEED_KEYS}


def with_trusted_authors(lines, login):
    lines = list(lines)
    for i, line in enumerate(lines):
        if line.split(":", 1)[0].strip() == "trusted-authors":
            lines[i] = "trusted-authors: %s\n" % login
            return lines
    lines.append("trusted-authors: %s\n" % login)
    return lines
