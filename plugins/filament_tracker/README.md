# Filament Tracker

Klipper extension for persistent single-spool accounting and LCD print
preflight. It integrates with `lcd_vsd_browser`: a selected file shows a compact
`xxHxxM xxxxg` estimate, and **Filament check** compares its slicer metadata
with the recorded spool before the virtual-SD print starts.

The supplied activation file also adds **New Spool** to the idle Filament menu
and the paused Runout recovery menu. The amount editor starts at 3000 g, changes
by 1 g during normal encoder rotation, and uses Klipper's native 10x fast-rate
step during quick rotation.

## Metadata

The browser recognizes common slicer comments for total filament weight and
length, including OrcaSlicer/PrusaSlicer `filament used [g]` and `filament used
[mm]` fields and Cura-style filament/material weight and length fields. Missing
metadata is shown as unavailable and requires an explicit **Continue anyway**.

## Accounting

State is atomically stored in:

```text
~/printer_data/config/filament-tracker.json
```

An append-only audit log is stored in:

```text
~/printer_data/config/filament-events.csv
```

When both expected length and weight are present, terminal print consumption is
calculated from Klipper's actual `print_stats.filament_used` and the file's own
grams-per-millimetre ratio. A completed print with weight but no length deducts
the expected weight. Cancelled or errored prints without a usable ratio are
logged without an inferred deduction.

Loading a replacement spool while paused first charges the observed print
usage to the old spool, then checkpoints the active job so only later extrusion
is charged to the replacement spool.

## Install

Install both dependencies on the pilot:

```bash
./install-plugins.sh lcd_vsd_browser filament_tracker
```

Restart Klipper and verify it reaches Ready. No installation or physical LCD
validation is performed from this repository workspace.
