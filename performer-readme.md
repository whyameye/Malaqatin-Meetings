# Malaqatin-Meetings — Notes for the performer

## One-time setup (display computer)

Edit `/etc/systemd/logind.conf` and ensure these lines are set (add or uncomment them):
```
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
IdleAction=ignore
```
Then restart logind:
```
sudo systemctl restart systemd-logind
```
This prevents systemd from suspending or blanking the display when the lid is closed or the machine is idle, regardless of what KDE or the browser does. Only needs to be done once.

---

## Pre-show setup (display computer)

Before opening the browser, run the sleep-prevention script from the Desktop:
```
bash ~/Desktop/prevent-sleep.sh
```
This disables X11 blanking, DPMS, the KDE screen locker, and systemd idle sleep. You should see:
```
Display sleep disabled. Open the browser now.
```
Then open Chrome and navigate to the display URL.

---

## Performer (`perform.html`)

### Keyboard
*subset of keyboard commands in performer for setup and performance. See README for all keyboard commands.*

| Key | Description |
|---|---|
| 1 / 2 / 3 | Load movement — crossfades to new movement, plays audio cue when ready |
| Enter | Fade in from black |
| X | Fade to black |
| Left / Right arrow | Crossfade to previous / next scene within the current movement (no wrap) |
| K | Toggle fullscreen |
| Space | Conductor tap — one tap per quarter-note beat|
| Backspace | Reset conductor to bar 1 |
| [ | Conductor: back 1 beat (also switches scene if crossing a scene boundary) |
| ] | Conductor: open jump-to-bar dialog (type measure number, Enter to jump, Escape to cancel) |

#### Keyboard commands that affect the display computer only
| Key | Description |
|---|---|
| 4 / 5 | Move display image left / right (10px; Shift = 1px) |
| 6 / 7 | Move display image up / down (10px; Shift = 1px) |
| 8 / 9 | Shrink / enlarge display image (10px; Shift = 1px) — scales from top-left |
| 0 | Reset display image to full screen |

