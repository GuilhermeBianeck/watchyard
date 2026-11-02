#!/bin/sh
set -eu
scope="gui/$(id -u)"
case "${1:-status}" in
 status|restart|stop|start) action="${1:-status}" ;;
 *) echo "Usage: sh scripts/service.sh status|restart|stop|start"; exit 2 ;;
esac
for name in server gateway watchdog; do
 case "$action" in
  status) launchctl print "$scope/com.watchyard.$name" ;;
  restart) launchctl kickstart -k "$scope/com.watchyard.$name" ;;
  stop) launchctl bootout "$scope" "$HOME/Library/LaunchAgents/com.watchyard.$name.plist" ;;
  start) launchctl bootstrap "$scope" "$HOME/Library/LaunchAgents/com.watchyard.$name.plist" ;;
 esac
done
