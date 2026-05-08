# FAQ

### LazyrosPlus says "ROS 2 unavailable" but I'm in a sourced terminal

Confirm `python3 -c 'import rclpy'` works in the same terminal. If
`lazyrosplus` was installed in a different virtualenv than the one your shell
is using now, source the right venv first. With Ubuntu 22/24, prefer:

```bash
python3 -m venv --system-site-packages ~/.venvs/lazyrosplus
source ~/.venvs/lazyrosplus/bin/activate
pip install lazyrosplus
```

so the system `rclpy` remains visible inside the venv.

### Why not use rqt / plotjuggler / rviz?

Those are great GUI tools. LazyrosPlus is the keyboard-driven equivalent —
runs on headless robots, over SSH, in tmux, on a phone via Termius.

### Can I subscribe to a sensor topic?

Yes — `lazyrosplus` auto-negotiates QoS based on the publisher endpoints, so
`BEST_EFFORT` topics (the typical sensor profile) are received correctly
without manual configuration. If you want to force a specific profile,
use `--config` and set `[ros] qos_profile`.

### Plot panel never shows data for a topic

Check:

1. The topic appears in panel 1 with a non-zero publisher count.
2. You pressed `Enter` on the topic to subscribe (the row highlights bold).
3. The field path you picked is numeric (`is_numeric` is true).
4. The publisher is actually emitting messages (look at the hz column).

If the field is non-numeric, the status bar will say so when you press
`p`/`Enter` on it.

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

`echo` dumps raw messages to a terminal. LazyrosPlus adds discovery, filter,
hz/bw, multi-topic subscription with auto-QoS, message-tree navigation
and live plotting in one tool. For one-off taps `echo` is still faster.
