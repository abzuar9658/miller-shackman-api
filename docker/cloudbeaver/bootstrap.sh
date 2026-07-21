#!/bin/sh
set -eu

WORKSPACE_DIR="/opt/cloudbeaver/workspace"
DATASOURCE_DIR="$WORKSPACE_DIR/GlobalConfiguration/.dbeaver"
DATASOURCE_FILE="$DATASOURCE_DIR/data-sources.json"
TEMPLATE_FILE="/opt/cloudbeaver/init/data-sources.template.json"

mkdir -p "$DATASOURCE_DIR"

if [ ! -f "$DATASOURCE_FILE" ]; then
  cp "$TEMPLATE_FILE" "$DATASOURCE_FILE"
  echo "CloudBeaver: seeded shared datasource configuration."
else
  echo "CloudBeaver: existing datasource configuration found; leaving it unchanged."
fi

cd /opt/cloudbeaver
exec ./run-cloudbeaver-server.sh
