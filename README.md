# Formative SV08 Custom Plugins

This nested repository contains optional Klipper extensions developed for the
Formative SV08 fleet. It is intentionally separate from the shared printer
configuration repository so plugins can be installed, updated, and removed
without replacing machine configuration.

Available plugins:

- `lcd_updates`: on-demand LCD updates for explicitly allowed Moonraker modules.

- `lcd_vsd_browser`: a hierarchical browser with explicit print confirmation
  for files below Klipper's `virtual_sdcard` directory.
- `network_status`: Moonraker-backed, on-demand network status for the stock
  Klipper LCD menu.

- `print_outcome`: modal post-print accepted-quantity entry and persistent CSV
  outcome logging for the stock Klipper LCD.

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

Plugins provide small activation entrypoints linked into the shared
`custom_plugins/*.cfg` include point. For example:

```text
custom_plugins/network-status.cfg
custom_plugins/lcd-vsd-browser.cfg
```

The installer removes only activation links it owns.

## Usage

```bash
./install-plugins.sh
./install-plugins.sh --list
./install-plugins.sh lcd_vsd_browser
./install-plugins.sh network_status
./install-plugins.sh --all
./install-plugins.sh --all -r
./install-plugins.sh --all -u
./install-plugins.sh --all --rl
./install-plugins.sh --uninstall lcd_vsd_browser
./install-plugins.sh --uninstall network_status
```

Running `install-plugins.sh` without arguments opens an interactive menu. It
lists every plugin and its installation status; selecting a plugin opens its
Install/repair and Uninstall actions. Explicit plugin names and `--all` retain a
noninteractive path for automation. Use `--no-restart` to defer restarting
Klipper and Moonraker. Uninstall removes only links that still point into this
repository; it does not delete replacement files or edit printer configuration.

Include `[release]` in the final commit message pushed to `main` to have
GitHub Actions create the annotated release tag automatically:

```text
Add network status support [release]
```

The generated `vYYYY.M.DDHHMMSS` tag format gives Moonraker's `git_repo`
Update Manager a release version to display. The workflow can also be run
manually from GitHub Actions. `./tag-release.sh` remains available as a local
fallback.

Environment overrides are documented by each script's `--help` output.

The `network_status` menu also offers **Remove legacy installation**. After
confirmation, it removes only a `network_status.py` symlink that resolves inside
`~/klipper_network_status` and then removes that Git repository. It refuses a
regular module file, a link to any other location, or a non-Git directory.

Noninteractive actions accept `--all` or named plugins: `-u` / `--uninstall`,
`-r` / `--repair`, and `--rl` / `--remove-legacy`. Select only one action.
Repair installs missing payloads and recreates existing installer-owned links;
it refuses to overwrite local files or unrelated links. Uninstall scans all
available plugins and removes only their owned links, including partial installs.
Legacy removal invokes every selected plugin's `legacy-cleanup.sh` without an
additional prompt and skips plugins without one. Currently Network Status has
that action: it deletes the recognized legacy Git checkout and legacy module
link, while preserving an installed replacement module link. Existing cleanup
path and ownership checks still apply. Use `--no-restart` to defer restarts.
