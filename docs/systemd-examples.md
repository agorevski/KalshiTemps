# systemd timer examples (documentation only)

These are examples for running the one-shot scheduler and monitoring commands. They are not installed by this repository. Review paths, user, permissions, network policy, data-source terms, backup/restore procedures, alert routing, and logging before adapting them. Installing these snippets still does not make the app production-ready until they are configured, monitored, and soaked.

`/etc/systemd/system/kalshi-temps-collectors.service`:

```ini
[Unit]
Description=Kalshi Temps one-shot collectors
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=kalshi-temps
WorkingDirectory=/opt/kalshi-temps
Environment=PYTHONPATH=/opt/kalshi-temps/src
Environment=KALSHI_TEMPS_DB=/var/lib/kalshi-temps/kalshi_temps.sqlite3
Environment=KALSHI_TEMPS_COLLECTORS=nws_discussion,metar
Environment=KALSHI_TEMPS_SCHEDULER_LOCKFILE=/var/lock/kalshi-temps/collectors.lock
ExecStart=/opt/kalshi-temps/scripts/run_collectors_once.sh
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/kalshi-temps /var/lock/kalshi-temps
```

`/etc/systemd/system/kalshi-temps-collectors.timer`:

```ini
[Unit]
Description=Run Kalshi Temps collectors periodically

[Timer]
OnBootSec=5min
OnUnitActiveSec=15min
RandomizedDelaySec=60
Persistent=true

[Install]
WantedBy=timers.target
```

Security caveats: keep the app on localhost or trusted private networks, protect the SQLite database, do not log secrets, set least-privilege ownership, and validate data-source rate limits. These examples do not provide production authentication, trading controls, compliance review, or automated order entry.

Optional monitoring service/timer example:

`/etc/systemd/system/kalshi-temps-monitoring.service`:

```ini
[Unit]
Description=Kalshi Temps monitoring checks and daily report export
After=network-online.target

[Service]
Type=oneshot
User=kalshi-temps
WorkingDirectory=/opt/kalshi-temps
Environment=PYTHONPATH=/opt/kalshi-temps/src
Environment=KALSHI_TEMPS_DB=/var/lib/kalshi-temps/kalshi_temps.sqlite3
ExecStart=/usr/bin/python -m kalshi_temps run-monitoring-checks
ExecStart=/usr/bin/python -m kalshi_temps export-daily-report --output /var/lib/kalshi-temps/reports/daily-report.md --format markdown
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/kalshi-temps
```

`/etc/systemd/system/kalshi-temps-monitoring.timer`:

```ini
[Unit]
Description=Run Kalshi Temps monitoring periodically

[Timer]
OnBootSec=10min
OnUnitActiveSec=1h
RandomizedDelaySec=120
Persistent=true

[Install]
WantedBy=timers.target
```

Operational checks before enabling timers:

```bash
PYTHONPATH=src python -m kalshi_temps scheduler-status
PYTHONPATH=src python -m kalshi_temps db-check
PYTHONPATH=src python -m kalshi_temps verify-backup data/backups/<backup>.sqlite3
PYTHONPATH=src python -m kalshi_temps prune-backups --dry-run
```

Backups and restores should remain explicit operator procedures unless a separate, reviewed backup timer and restore drill process is added.
