#!/bin/sh
set -eu
scope="gui/$(id -u)"
case "${1:-status}" in
  status) launchctl print "$scope/com.watchyard.server"; launchctl print "$scope/com.watchyard.gateway" ;;
  restart) launchctl kickstart -k "$scope/com.watchyard.server"; launchctl kickstart -k "$scope/com.watchyard.gateway" ;;
  stop) launchctl bootout "$scope" "$HOME/Library/LaunchAgents/com.watchyard.gateway.plist"; launchctl bootout "$scope" "$HOME/Library/LaunchAgents/com.watchyard.server.plist" ;;
  start) launchctl bootstrap "$scope" "$HOME/Library/LaunchAgents/com.watchyard.server.plist"; launchctl bootstrap "$scope" "$HOME/Library/LaunchAgents/com.watchyard.gateway.plist" ;;
  *) echo "Usage: sh scripts/service.sh status|restart|stop|start"; exit 2 ;;
esac
