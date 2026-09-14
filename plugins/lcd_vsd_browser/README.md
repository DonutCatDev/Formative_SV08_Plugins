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
12.4 MB
```

`Print now` exits the LCD menu and starts the selected path with Klipper's
recursive `SDCARD_PRINT_FILE` implementation. The plugin passes an internal
numeric token through G-Code instead of interpolating the filename, allowing
spaces and punctuation without creating command-injection ambiguity.

Set `confirm_print: False` to make a file click start immediately. Confirmation
is recommended for a physical rotary encoder.

## Install and activate

Install through the repository manager, then add this include **before** the
existing `options/lcd/*.cfg` include:

```ini
[include custom_plugins/lcd_vsd_browser/lcd_vsd_browser.cfg]
[include options/lcd/*.cfg]
```

Restart Klipper and verify it reaches Ready. The plugin overrides the existing
`[menu __main __sdcard]` definition with `type: vsd_browser`; its dynamic browser
intentionally ignores the old `__start` child used by the stock two-step flow.

## Configuration

```ini
[lcd_vsd_browser]
extensions: gcode, g, gco
show_hidden: False
confirm_print: True
max_remembered_files: 256
```

This is an initial implementation and requires pilot testing on the physical
display before fleet use.
