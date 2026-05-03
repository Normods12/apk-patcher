#!/usr/bin/env bash
set -euo pipefail

# Safe JVM options: prefer existing _JAVA_OPTIONS or JAVA_TOOL_OPTIONS
if [ -z "${_JAVA_OPTIONS:-}" ] && [ -z "${JAVA_TOOL_OPTIONS:-}" ]; then
  export JAVA_TOOL_OPTIONS="-Xms${JAVA_XMS:-512m} -Xmx${JAVA_XMX:-2048m}"
fi

# Ensure persistent directories exist
mkdir -p /app/automation/output_files /app/automation/logs /app/automation/locks /app/automation/input_files /backups

# Initialize sqlite schema if needed
python - <<'PY'
from automation.database.db import init_db
init_db()
print('DB initialized or already present')
PY

# Exec the container CMD (e.g., python automation/main.py)
exec "$@"
