# Calibration History

Klipper extension that records calibration starts and successful completions in
an append-only CSV file. A start without a matching completion remains useful
evidence that the calibration was interrupted or failed.

The default log is:

```text
~/printer_data/config/calibration-history.csv
```

Each row contains a UTC timestamp, machine hostname, calibration type, status,
run identifier, elapsed seconds when available, and caller-supplied details.
The supplied SV08 macros record `pid_multi`, `belt_resonances`, and
`auto_calibrate`. PID details include the requested temperatures and whether
`SAVE_CONFIG` was requested. That field does not claim the subsequent Klipper
restart succeeded.

## Install

Install on the pilot printer:

```bash
./install-plugins.sh calibration_history
```

Restart Klipper, confirm it reaches Ready, and invoke a calibration through its
normal LCD or console macro. Inspect `calibration-history.csv` afterward.

The command interface is also available for future calibration macros:

```text
CALIBRATION_RECORD TYPE=<name> STATUS=started [DETAILS=<text>]
CALIBRATION_RECORD TYPE=<name> STATUS=completed [DETAILS=<text>]
```

Type names are normalized to lowercase and may contain letters, digits,
underscores, and hyphens. Details are limited to 1024 characters. Runtime
status is exposed as `printer.calibration_history`; it reports the configured
path, machine name, active calibration types, and the last event from the
current Klipper process.

No historical records are inferred or backfilled by this plugin. Uninstalling
the plugin removes installer-owned links but intentionally preserves the CSV.
