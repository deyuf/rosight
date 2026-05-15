# Changelog

All notable changes to Rosight are documented in this file. The format is
loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versions follow [PEP 440](https://peps.python.org/pep-0440/).

## [Unreleased]

### Added

- **1D-array snapshot plotting** — the Plot tab now accepts numeric *array*
  fields (e.g. `sensor_msgs/LaserScan.ranges`, `sensor_msgs/JointState.position`)
  alongside scalar time-series. Press `Enter` on a numeric array in the
  message tree (look for the green `[plot ↵]` marker), or use
  `:plot-array <topic> <field>`. When both kinds are present, the chart
  splits into stacked subplots (time on top, index on bottom).
- **Image preview modal** — press `v` on a `sensor_msgs/Image` or
  `sensor_msgs/CompressedImage` topic to open a live preview overlay.
  Supports `rgb8`/`bgr8`/`rgba8`/`bgra8`/`mono8`/`mono16`/`32FC1` raw
  encodings plus JPEG/PNG-compressed. Depth (`mono16`, `32FC1`) is
  rendered through a built-in turbo / viridis / gray colormap (cycle
  with `m`). Other modal keys: `space` pause, `s` save PNG, `q`/`Esc`
  close. Throttled to ~5 Hz.
- Command palette: `plot-array <topic> <field>` and `view <topic>`.
- CSV export now writes a `kind` column to distinguish time-series rows
  (`time`) from snapshot rows (`snapshot`).

### Changed

- `FieldEntry` gained `is_array_numeric: bool` — set on container entries
  whose element type is numeric. Mostly internal; default `False` keeps
  backwards compatibility.
- `MessageTree.FieldSelected` gained `kind: Literal["scalar", "array"]`
  with default `"scalar"` — backwards compatible.
- Sequence-typed ROS fields (`sequence<float32>`, `float64[N]`) are now
  walked into a container entry rather than emitted as a single
  primitive leaf, so the tree correctly reflects their shape.

### Dependencies

- Added `numpy>=1.24`, `Pillow>=10.0`, `textual-image>=0.6` as core
  runtime dependencies (needed for image decode / render). They install
  via `pip` with no system packages.
