# LCD Updates

Self-contained Klipper extension for on-demand Moonraker Update Manager access.
It uses the dynamic `MenuList` approach from `lcd_vsd_browser`. No shell-command
extension, helper script, or network-status changes are required.

## Install

Run `./install-plugins.sh lcd_updates` on the pilot host when ready to install.
The standard installer discovers this plugin automatically and links its module
and `custom_plugins/lcd-updates.cfg` activation file. The shared machine config
already includes `custom_plugins/*.cfg` before the LCD definition, which is
required to register the custom menu type. Uninstall with
`./install-plugins.sh --uninstall lcd_updates`.

No installation or update on a physical printer has been performed here.

## Configuration

The activation file supplies:

```ini
[lcd_updates]
allowed_modules:
    formative_sv08_plugins,
    formative_sv08_configs
moonraker_url: http://127.0.0.1:7125
request_timeout: 120
update_timeout: 3600

[menu __main __formative_updates]
type: lcd_updates
name: Updates
```

Every discovered updater defaults to disallowed. Add its exact Moonraker entry
name to `allowed_modules` to allow it, remove it to disallow it, or leave the
option empty to disallow everything. Names are comma-separated; multiline lists
must keep the commas. Changes take effect after Klipper restart. Discovery is
read-only and never writes an automatically populated config.

The installed activation file is a repository symlink. To keep a machine-local
allowlist across repository updates, replace that symlink with a regular local
copy before editing it. The installer deliberately refuses to replace local
files; retain/manage that copy manually during later install or uninstall work.
Do not add a second `[lcd_updates]` section.

Optional `api_key` provides Moonraker authentication when localhost is not
trusted. Keep credentials in the local activation copy. The default connection
is to localhost; remote authenticated connections should use HTTPS.

## LCD workflow

Open **Updates** to discover modules and refresh only allowed, registered modules
through Moonraker. While the background worker runs, the LCD shows **Working...**.
The list rebuilds from cached status when the worker finishes, without requiring
a menu reopen. Only allowed modules with updates appear, including newly
configured modules once explicitly allowed. Select a module, then **Update now?**
to confirm; `..` cancels. **Refresh** repeats the on-demand query.

No background polling occurs. `get_status()` and display drawing perform no
network I/O. `printer.lcd_updates.modules` exposes discovered names with
`allowed` and `update_available` flags for inspection. Invalid, dirty, or corrupt
repositories do not appear as available updates. Git updaters compare hashes;
release updaters compare versions; system uses package count.

The plugin requires an idle, unpaused printer locally and checks those conditions
again through Moonraker before the named upgrade. Moonraker independently rejects
updates during printing. This is not a transaction lock against another client
starting work in the final interval; use the LCD maintenance workflow on an idle
pilot. Each request always carries an explicit module name; no full update,
recovery, rollback, or automatic retries are exposed.

Moonraker may restart Klipper when updating these repositories. If submission
or subsequent status retrieval loses its connection, **Status uncertain** blocks
further plugin requests for the current Klipper session. Inspect Moonraker/Mainsail
and verify the update has finished, then restart Klipper to clear that condition.
Do not retry blindly. Ordinary discovery/refresh errors show **Refresh failed**;
inspect `printer.lcd_updates.error` and use Refresh after correcting the cause.

## Local checks and pending pilot acceptance

Local evidence: [validation report](../../../validation/lcd-updates/REPORT.md).
Verify on the pilot before fleet propagation:

- Installed plugin reaches Ready and Updates renders on the physical LCD.
- Both allowed repository names are registered with Moonraker.
- A module with an available update appears; other modules stay hidden.
- Allowlist edits and an empty allowlist behave as documented after restart.
- Async completion rebuilds the LCD list and confirmation/back navigation works.
- A named repository update completes and expected restart behavior is understood.
- Paused/printing/busy states reject updates; API failure and restart recovery work.

API basis: [Moonraker Update Manager](https://moonraker.readthedocs.io/en/latest/external_api/update_manager/)
(`/status`, named `/refresh`, named `/upgrade`, API 1.5.0+) and
[upstream Klipper menu implementation](https://github.com/Klipper3d/klipper/blob/master/klippy/extras/display/menu.py).
