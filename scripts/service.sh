#!/bin/sh
set -eu
label="gui/$(id -u)/com.watchyard.server"
plist="$HOME/Library/LaunchAgents/com.watchyard.server.plist"
case "${1:-status}" in
  status) launchctl print "$label" ;;
  restart) launchctl kickstart -k "$label" ;;
  stop) launchctl bootout "gui/$(id -u)" "$plist" ;;
  start) launchctl bootstrap "gui/$(id -u)" "$plist" ;;
  *) echo "Usage: sh scripts/service.sh status|restart|stop|start"; exit 2 ;;
esac
