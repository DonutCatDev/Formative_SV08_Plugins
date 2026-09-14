# Formative SV08 Custom Plugins

This nested repository contains optional Klipper extensions developed for the
Formative SV08 fleet. It is intentionally separate from the shared printer
configuration repository so plugins can be installed, updated, and removed
without replacing machine configuration.

The first plugin is `lcd_vsd_browser`, a hierarchical browser with explicit
print confirmation for files below Klipper's `virtual_sdcard` directory.

## Repository layout

```text
plugins/<plugin-name>/
  klippy/extras/       Optional Klipper Python modules
  config/              Optional Klipper configuration fragments
  activation/          Files linked relative to ~/printer_data/config
```

The root installer links payloads into the printer rather than copying them:

- `klippy/extras/*` -> `~/klipper/klippy/extras/`
- `config/` -> `~/printer_data/config/custom_plugins/<plugin-name>/` when used
- `activation/*` -> the corresponding path below `~/printer_data/config/`

Plugins may provide a small activation include when an existing wildcard-owned
directory is available. For example, the LCD browser installs:

```text
options/lcd/00-custom-plugin-lcd-vsd-browser.cfg
```

The installer removes only activation links it owns.

## Usage

```bash
./install-plugins.sh
./install-plugins.sh --list
./install-plugins.sh lcd_vsd_browser
./install-plugins.sh --all
./install-plugins.sh --uninstall lcd_vsd_browser
```

Running `install-plugins.sh` without arguments opens an interactive menu. It
lists every plugin and its installation status; selecting a plugin opens its
Install/repair and Uninstall actions. Explicit plugin names and `--all` retain a
noninteractive path for automation. Use `--no-restart` to defer restarting
Klipper and Moonraker. Uninstall removes only links that still point into this
repository; it does not delete replacement files or edit printer configuration.

Publish an annotated release tag after committing and pushing a clean branch:

```bash
./tag-release.sh
```

The generated `vYYYY.M.DDHHMMSS` tag format gives Moonraker's `git_repo`
Update Manager a release version to display.

Environment overrides are documented by each script's `--help` output.
