# Formative SV08 Custom Plugins

This nested repository contains optional Klipper extensions developed for the
Formative SV08 fleet. It is intentionally separate from the shared printer
configuration repository so plugins can be installed, updated, and removed
without replacing machine configuration.

The first planned plugin is `lcd_vsd_browser`, a hierarchical browser for files
below Klipper's `virtual_sdcard` directory. Its implementation will be added as
a separate change after the browser behavior and interfaces are specified.

## Repository layout

```text
plugins/<plugin-name>/
  klippy/extras/       Optional Klipper Python modules
  config/              Optional Klipper configuration fragments
```

The root installer links payloads into the printer rather than copying them:

- `klippy/extras/*` -> `~/klipper/klippy/extras/`
- `config/` -> `~/printer_data/config/custom_plugins/<plugin-name>/`

Installed configuration fragments are not activated implicitly. The printer
configuration must explicitly include the desired plugin file, for example:

```ini
[include custom_plugins/lcd_vsd_browser/lcd_vsd_browser.cfg]
```

That separation makes installation reversible and keeps activation visible in
the normal configuration review.

## Usage

```bash
./install-plugins.sh --list
./install-plugins.sh lcd_vsd_browser
./uninstall-plugins.sh lcd_vsd_browser
```

With no plugin names, either script operates on every plugin in `plugins/`.
Use `--no-restart` to defer restarting Klipper and Moonraker. Uninstall removes
only links that still point into this repository; it does not delete replacement
files or edit printer configuration.

Environment overrides are documented by each script's `--help` output.

