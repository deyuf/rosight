# Keybindings

`lazyros` ships with a vim-leaning, lazygit-style keymap. Press `?` in the
running app for the same reference.

## Global

| Key | Action |
|-----|--------|
| `q` / `Ctrl+C` | quit |
| `?` | toggle help overlay |
| `:` | command palette |
| `/` | filter the focused panel |
| `r` | refresh discovery |
| `Tab` / `Shift+Tab` | cycle focus across panes |
| `1`-`9` | switch to panel 1-9 |

## Topics panel (`1`)

| Key | Action |
|-----|--------|
| `Enter` | subscribe (echo) |
| `i` | info / QoS |
| `h` | hz monitor (auto-subscribes) |
| `b` | bandwidth monitor (auto-subscribes) |
| `Space` | pause/resume tree refresh |
| `P` | publish (form — planned) |
| `/` | filter |

In the message tree:

| Key | Action |
|-----|--------|
| `j` / `k` / arrows | navigate |
| `Enter` / `p` | add highlighted leaf to the Plot panel |

## Nodes panel (`2`)

| Key | Action |
|-----|--------|
| `Enter` | show endpoints |
| `/` | filter |

## Services panel (`3`)

| Key | Action |
|-----|--------|
| `Enter` | inspect |
| `c` | call (form — planned) |
| `/` | filter |

## Actions panel (`4`)

| Key | Action |
|-----|--------|
| `Enter` | inspect |
| `/` | filter |

## Parameters panel (`5`)

| Key | Action |
|-----|--------|
| `Enter` | load parameters for the highlighted node |
| `g` | get value |
| `/` | filter |

## Plot panel (`6`)

| Key | Action |
|-----|--------|
| `Space` | pause/resume |
| `+` / `=` | grow time window |
| `-` | shrink time window |
| `c` | clear all series |
| `l` | toggle legend |
| `d` | delete highlighted series |
| `s` | export all series to CSV |

## TF panel (`7`)

| Key | Action |
|-----|--------|
| `r` | redraw tree |

## Bags panel (`8`)

| Key | Action |
|-----|--------|
| `R` | start/stop record |
| `p` | play |
| `s` | stop |
| `i` | bag info |

## Interfaces panel (`9`)

| Key | Action |
|-----|--------|
| `Enter` | show definition |
| `/` | filter |

## Customisation

Keymaps are not yet user-configurable — the design will follow Textual's
binding inheritance once the action surface stabilises. Track the
[development guide](development.md) for the schema.
