# FAQ

### Rosight says "ROS 2 unavailable" but I'm in a sourced terminal

Confirm `python3 -c 'import rclpy'` works in the same terminal. If
`rosight` was installed in a different virtualenv than the one your shell
is using now, source the right venv first. With Ubuntu 22/24, prefer:

```bash
python3 -m venv --system-site-packages ~/.venvs/rosight
source ~/.venvs/rosight/bin/activate
pip install rosight
```

so the system `rclpy` remains visible inside the venv.

### Why not use rqt / plotjuggler / rviz?

Those are great GUI tools. Rosight is the keyboard-driven equivalent —
runs on headless robots, over SSH, in tmux, on a phone via Termius.

### Can I subscribe to a sensor topic?

Yes — `rosight` auto-negotiates QoS based on the publisher endpoints, so
`BEST_EFFORT` topics (the typical sensor profile) are received correctly
without manual configuration. If you want to force a specific profile,
use `--config` and set `[ros] qos_profile`.

### Plot panel always says "no series — press \[p] in the message tree to add a field"

That hint is correct behaviour: the Plot tab plots specific *numeric fields*,
not whole topics. A `nav_msgs/Odometry` message has dozens of fields — the
app doesn't guess. Full workflow:

1. **Messages tab** — cursor over a topic with a non-zero `Pub` count.
2. **Enter** → subscribe. Focus moves to the message tree on the right.
3. Use arrow keys / Space to drill into sub-messages (`pose` → `position` → `x`).
4. With the cursor on a **numeric leaf** (int / float; not string / array / sub-message), press **p**. The series is added and the Plot tab opens.

If `p` does nothing on a leaf, check that the field is numeric — a toast
will tell you `field <path> is not numeric — skipped` for the wrong kind.

### I can't copy text out of the app — Ctrl+C just quits

Two things going on:

- `Ctrl+C` is bound to **quit** in Rosight (lazygit-style). Don't use it for copy.
- Textual captures the mouse, so a normal drag doesn't reach your terminal's selection. Hold your terminal's **bypass modifier** while dragging:
  - GNOME Terminal / Konsole / xterm / WSL / Windows Terminal → **Shift**
  - macOS Terminal.app / iTerm2 → **Option / Alt**
  - tmux → `Prefix [` (copy-mode), then `v` / `y`

### The theme I picked from `Ctrl+P` disappears on restart

Rosight persists your theme choice in
`$XDG_CONFIG_HOME/rosight/state.toml`. If that file isn't being written:

- Check that `~/.config/rosight/` is writable.
- Check the log (`--log-file /tmp/rosight.log --log-level DEBUG`) for
  `could not persist theme`.

Delete the state file to fall back to the built-in default.

### How do I switch ROS_DOMAIN_ID without restarting?

Press `:` to open the command palette and type:

```
domain 5
```

rclpy is reinitialised on the new domain; all active subscriptions are
dropped (the rclpy context owns them). The status bar's `DOMAIN_ID=`
field updates immediately to show the live value.

### Can I record a bag of just selected topics?

Yes. Open the Bags panel (`8`), set the args field to the topics you
want (e.g. `/odom /scan`), and press `R`. Recording continues until you
press `R` again, even if you exit the TUI.

### How do I file a bug?

Open an issue on GitHub with:

- distro and Python version
- the contents of `--log-file` (run with `--log-level DEBUG`)
- a reproducer if possible

### Does it work on macOS / Windows?

The TUI portion runs anywhere Textual runs. The ROS-aware features
require rclpy, which is best-supported on Linux. macOS support depends
on whether you can install rclpy locally. Windows requires a
ROS-on-Windows distro and isn't actively tested.

### How is this different from `ros2 topic echo`?

`echo` dumps raw messages to a terminal. Rosight adds discovery, filter,
hz/bw, multi-topic subscription with auto-QoS, message-tree navigation
and live plotting in one tool. For one-off taps `echo` is still faster.
