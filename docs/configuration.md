# Configuration

`rosight` reads a TOML config from `$XDG_CONFIG_HOME/rosight/config.toml`
(typically `~/.config/rosight/config.toml`). All keys are optional;
defaults are listed below.

```toml
[ui]
theme = "rosight-dark"     # ui theme name
refresh_hz = 10            # how often the status bar updates
discovery_period = 1.0     # seconds between background graph collections
vim_keys = true            # j / k / g / G motions in tables and trees
export_dir = "~/rosight"   # plot CSV, image PNG, bags (default: current dir)
bag_output_dir = "~/bags"  # overrides export_dir for ros2 bag record

[plot]
window_seconds = 30.0      # default sliding-window length
max_points = 5000          # per-series sample cap
refresh_hz = 15.0          # plot redraw rate
show_legend = true

[stats]
window_seconds = 5.0       # hz / bandwidth window
max_samples = 4096

[ros]
domain_id = 0              # leave unset to inherit ROS_DOMAIN_ID
qos_profile = "auto"       # auto | sensor_data | reliable | best_effort
queue_depth = 10           # default subscriber queue depth
```

## Overriding via CLI

```bash
rosight --config /path/to/alt.toml
rosight --domain-id 7
```

The CLI also accepts `ROSIGHT_CONFIG=path` as an env override.

## Where each setting goes

- **`ui.discovery_period`** controls how often the background graph
  monitor collects topics / nodes / services / actions. Panels read its
  snapshot, so this is the only place discovery cost is paid. Increase it
  on a very large graph; `r` forces an immediate collection.
- **`ui.export_dir`** is created on first use; notifications show the full
  path of every exported file.
- **`plot.window_seconds`** is the initial window; `+` and `-` scale it
  interactively at runtime.
- **`stats.window_seconds`** governs the smoothing on hz / bandwidth.
  Smaller values are more responsive but noisier on bursty topics.
- **`ros.qos_profile`** is a forward-looking knob. The default `auto`
  derives QoS from publisher endpoints (recommended); the others force a
  single profile for every subscription.

## Schema

Defined as plain dataclasses in `src/rosight/config.py`. Unknown keys are
silently ignored to keep older configs compatible.

## Persisted runtime state

Things you change inside the app are written to a separate small file next
to your config, so Rosight never rewrites your hand-edited `config.toml`:
the **theme** (`Ctrl+P → Change theme`), the **last tab**, every panel's
**filter**, the **plot series** and the **command-palette history**.

```
$XDG_CONFIG_HOME/rosight/state.toml
```

Example content:

```toml
"theme" = "textual-light"
"last_tab" = "plot"
"plot_series" = ["scalar|/odom|twist.twist.linear.x", "array|/scan|ranges"]
"command_history" = ["plot /odom twist.twist.linear.x", "domain 3"]

["filters"]
"topics" = "odom"
```

It is written when you quit. Delete it to start fresh (the theme then falls
back to `[ui] theme` in your config, or the built-in default).

## Runtime domain switch

You can change `ROS_DOMAIN_ID` *while the app is running* without losing the
session:

```
:           # open the command palette
domain 5    # rclpy is reinitialised on domain 5
```

The rclpy context, executor, and every active subscription are torn down and
recreated on the new domain (in the background, so the UI stays responsive).
The status bar's `DOMAIN_ID=` field updates to the live value, and plotted
topics resubscribe automatically once they appear on the new domain.
`:reconnect` does the same on the current domain — the status bar offers it
if the executor thread ever stops.
