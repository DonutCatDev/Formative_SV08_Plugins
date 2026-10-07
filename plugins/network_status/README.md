# Network Status

`network_status` is an on-demand Klipper LCD extension for showing current
network information obtained through Moonraker. It preserves the project rule
that network queries occur when the relevant menu is opened rather than through
frequent background polling of Klipper's event loop.

## Payload

- `klippy/extras/network_status.py` — Klipper extra module.
- `activation/custom_plugins/network-status.cfg` — activation include installed
  below the printer configuration directory.
- `legacy-cleanup.sh` — narrowly scoped cleanup for the older standalone checkout.

Install from the repository root:

```bash
./install-plugins.sh network_status
```

Use `--repair` to recreate installer-owned links, `--uninstall` to remove only
owned links, and `--remove-legacy` to invoke the guarded legacy cleanup. Add
`--no-restart` when Klipper and Moonraker must not be restarted immediately.

## Safety and compatibility

The cleanup script removes the historical checkout only when its path, Git
identity, and module symlink match the expected legacy installation. It refuses
regular files, unrelated symlinks, and non-Git directories. The replacement
plugin link is preserved.

Changes to the module API must be reviewed with the active LCD menu callers in
the configuration repository. Verify menu rendering and on-demand refresh on a
pilot printer; local Python import checks do not prove Moonraker reachability or
LCD behavior.
