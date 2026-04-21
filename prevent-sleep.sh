#!/bin/bash
# Run this on the display computer before opening the browser.

# Disable X11 screen blanking and DPMS
xset s 0 0
xset s noblank
xset -dpms

# Inhibit KDE screen locker via D-Bus
qdbus org.freedesktop.ScreenSaver /ScreenSaver \
    org.freedesktop.ScreenSaver.Inhibit "Malaqatin" "Performance" > /dev/null 2>&1

# Hold a systemd idle/sleep inhibit lock for the duration of the session
systemd-inhibit \
    --what=idle:sleep \
    --who="Malaqatin Performance" \
    --why="Performance in progress" \
    --mode=block \
    sleep infinity &
disown

echo "Display sleep disabled. Open the browser now."
