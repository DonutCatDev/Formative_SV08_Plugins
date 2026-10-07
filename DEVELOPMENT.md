# Plugin development

Each plugin is an independent payload beneath `plugins/<name>/`, while the root
installer owns discovery, link creation, repair, uninstall, and restart behavior.

## Layout contract

```text
plugins/<name>/
  klippy/extras/       Klipper Python modules
  activation/          Files linked below ~/printer_data/config
  README.md            User behavior, install, and acceptance notes
  legacy-cleanup.sh    Optional narrowly scoped legacy removal
```

Not every plugin needs every directory. Do not add an activation include or
cleanup operation unless the payload requires it.

## Change checklist

1. Identify config, LCD, Moonraker, and plugin callers of the affected API.
2. Keep state and file writes bounded to documented printer-data locations.
3. Preserve the installer's no-clobber and link-ownership checks.
4. Add or update focused tests and the plugin README.
5. Test install, repair, uninstall, and deferred restart behavior when relevant.
6. Validate the actual menu or printer lifecycle on the pilot.

Plugin installation can require Klipper/Moonraker restarts. A local test does
not authorize a fleet rollout, and a successful pilot does not make calibration
or hardware values shareable.
