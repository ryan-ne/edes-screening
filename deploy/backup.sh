#!/usr/bin/env sh
# Safe online backup of the screening database to ./backups/
# Usage (on the VPS, in the project folder): sh deploy/backup.sh
set -eu
mkdir -p backups
STAMP=$(date +%Y%m%d-%H%M%S)
docker compose exec -T app python -c "
import sqlite3
src = sqlite3.connect('/app/data/screening.db')
dst = sqlite3.connect('/app/data/backup.db')
src.backup(dst); dst.close(); src.close()
"
docker compose cp app:/app/data/backup.db "backups/screening-$STAMP.db"
docker compose exec -T app rm -f /app/data/backup.db
chmod 600 "backups/screening-$STAMP.db"
# keep last 30 backups
ls -1t backups/screening-*.db | tail -n +31 | xargs -r rm -f
echo "Backup saved: backups/screening-$STAMP.db"
