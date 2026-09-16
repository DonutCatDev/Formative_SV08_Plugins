# Print Outcome

Klipper extension that opens a modal operator prompt on the stock character LCD
after a virtual-SD print reaches `complete`. The encoder starts on **Accepted**;
click it, rotate from zero through the detected job quantity, click again, then
select **Confirm**. Confirmation appends one durable CSV record, exits the menu,
returns to `sv08_home`, clears the LCD message, and restores the configured
screen color. Selecting zero records a fully unsuccessful print.

Cancelled and errored prints do not prompt or create a record. A completed job
that was already present when Klipper restarted is ignored, preventing a stale
prompt. Until the operator confirms, the prompt remains modal and no record is
written.

## Quantity detection

The upper bound is selected in this order:

1. A case-insensitive `QTY<number>` at the end of the filename stem, such as
   `bracket_QTY24.gcode`.
2. The count of objects declared to Klipper's `[exclude_object]` module.
3. `default_quantity` (1 in the supplied activation file).

The value is capped by `maximum_quantity` to keep malformed filenames from
creating an impractical encoder range.

## Install

Run `./install-plugins.sh print_outcome` on the pilot. The standard installer
links `print_outcome.py` into `~/klipper/klippy/extras/` and installs the
activation link at `~/printer_data/config/custom_plugins/print-outcome.cfg`.
Restart Klipper and confirm it reaches Ready. Uninstall with
`./install-plugins.sh --uninstall print_outcome`.

The default CSV location is:

```text
~/printer_data/config/print-outcomes.csv
```

Its columns are `filename`, `start_time`, `end_time`,
`total_duration_seconds`, and `accepted_count`. Times are local ISO-8601 values
with their UTC offset. The duration comes from Klipper's `print_stats`; because
Klipper exposes no completion event timestamp, the end time is sampled within
`poll_interval` of completion and the start time is reconstructed from the
duration.

Replace the activation symlink with a machine-local regular copy before changing
`log_path`, quantities, or `on_accept_gcode`; the installer intentionally does
not overwrite local files. Keep the log on local storage. The supplied accept
hook matches the current SV08 `Screen_Colour` LED and `sv08_home` display group.

No plugin installation or physical-printer validation has been performed from
this workspace.
