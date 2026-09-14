# LCD Virtual-SD Browser

Klipper extension providing hierarchical, refresh-on-entry navigation of
directories below `[virtual_sdcard] path` on a character LCD.

## File-selection workflow

Folders appear before files and use Klipper's normal `>` container indicator.
Every directory is rescanned when it is entered, so newly uploaded files appear
after backing out and reopening that directory. Hidden entries, unsupported
extensions, directory symlinks, and links escaping the virtual-SD root are
omitted.

Selecting a file opens a confirmation page containing:

```text
..
Print now
example.gcode
Est 2h07m
```

The displayed duration is calculated as:

```text
slicer estimate + START_PRINT HEATSOAK minutes + 9 startup minutes
```

The parser recognizes OrcaSlicer/PrusaSlicer-style `estimated printing time`
metadata and Cura-style `;TIME:` seconds. It reads the actual, uncommented
`START_PRINT ... HEATSOAK=<minutes>` command near the beginning of the file. If
that parameter is omitted, `default_heatsoak_minutes` is used to match the
printer macro default. If no supported slicer estimate is found, the LCD shows
`Time unavailable` rather than presenting a misleading total.

Only bounded sections from the beginning and end of the file are read. Results
are cached using the file path, size, and modification time, so revisiting a
selection does not repeatedly scan the file.

`Print now` exits the LCD menu and starts the selected path with Klipper's
recursive `SDCARD_PRINT_FILE` implementation. The plugin passes an internal
numeric token through G-Code instead of interpolating the filename, allowing
spaces and punctuation without creating command-injection ambiguity.

Set `confirm_print: False` to make a file click start immediately. Confirmation
is recommended for a physical rotary encoder.

## Install and activate

Install through the repository manager. It creates this activation link:

```text
~/printer_data/config/custom_plugins/lcd-vsd-browser.cfg
  -> plugins/lcd_vsd_browser/activation/custom_plugins/lcd-vsd-browser.cfg
```

The linked file contains the small `[lcd_vsd_browser]` configuration directly.
It loads through the shared `custom_plugins/*.cfg` wildcard before the LCD
configuration. This avoids a plugin-specific include and does not depend on a
companion configuration-directory link. During migration, the installer also
removes its older `options/lcd/00-custom-plugin-lcd-vsd-browser.cfg` link.
Uninstall removes the current activation link.

Restart Klipper and verify it reaches Ready. The plugin replaces Klipper's
`vsdlist` implementation, so the existing `[menu __main __sdcard]` section in
`sovol-menu-moonraker.cfg` remains the authoritative menu definition. Its
dynamic browser intentionally ignores the old `__start` child used by the stock
two-step flow.

## Configuration

```ini
[lcd_vsd_browser]
extensions: gcode, g, gco
show_hidden: False
confirm_print: True
max_remembered_files: 256
startup_minutes: 9
default_heatsoak_minutes: 10
metadata_read_bytes: 262144
```

This is an initial implementation and requires pilot testing on the physical
display before fleet use.
