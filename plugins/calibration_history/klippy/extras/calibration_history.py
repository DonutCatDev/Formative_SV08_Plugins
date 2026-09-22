# Append-only calibration event logging for Klipper.
# Copyright (C) 2026 Formative; GNU GPLv3.
import csv
import datetime
import os
import re
import socket
import uuid


CALIBRATION_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
VALID_STATUSES = frozenset(("started", "completed"))
CSV_HEADER = (
    "timestamp_utc", "machine", "calibration", "status", "run_id",
    "duration_seconds", "details")


class CalibrationHistory:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object("gcode")
        default_log = "~/printer_data/config/calibration-history.csv"
        self.log_path = os.path.abspath(os.path.expanduser(
            config.get("log_path", default_log)))
        self.machine = config.get("machine", socket.gethostname()).strip()
        if not self.machine:
            raise config.error("calibration_history machine must not be empty")
        self.active = {}
        self.last_event = None
        self.gcode.register_command(
            "CALIBRATION_RECORD", self.cmd_CALIBRATION_RECORD,
            desc="Append a start or completion event to calibration history")

    @staticmethod
    def _now():
        return datetime.datetime.now(datetime.timezone.utc)

    def _append_event(self, timestamp, calibration, status, run_id,
                      duration, details):
        parent = os.path.dirname(self.log_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        needs_header = not os.path.exists(self.log_path) or os.path.getsize(
            self.log_path) == 0
        event = {
            "timestamp_utc": timestamp.isoformat(timespec="seconds"),
            "machine": self.machine,
            "calibration": calibration,
            "status": status,
            "run_id": run_id,
            "duration_seconds": duration,
            "details": details,
        }
        with open(self.log_path, "a", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            if needs_header:
                writer.writerow(CSV_HEADER)
            writer.writerow((
                event["timestamp_utc"], event["machine"], calibration,
                status, run_id,
                "" if duration is None else "%.3f" % duration, details))
            stream.flush()
            os.fsync(stream.fileno())
        self.last_event = event

    def cmd_CALIBRATION_RECORD(self, gcmd):
        calibration = gcmd.get("TYPE").strip().lower()
        status = gcmd.get("STATUS").strip().lower()
        details = gcmd.get("DETAILS", "").strip()
        if not CALIBRATION_RE.match(calibration):
            raise gcmd.error(
                "Calibration TYPE must use 1-64 lowercase letters, digits, "
                "underscores, or hyphens")
        if status not in VALID_STATUSES:
            raise gcmd.error("Calibration STATUS must be started or completed")
        if len(details) > 1024:
            raise gcmd.error("Calibration DETAILS must not exceed 1024 characters")

        timestamp = self._now()
        duration = None
        if status == "started":
            run_id = uuid.uuid4().hex
            self.active[calibration] = (run_id, timestamp)
        else:
            active = self.active.pop(calibration, None)
            if active is None:
                # A completion is still useful after a Klipper restart, even
                # though its matching in-memory start and duration are gone.
                run_id = uuid.uuid4().hex
            else:
                run_id, started = active
                duration = max(0., (timestamp - started).total_seconds())

        self._append_event(
            timestamp, calibration, status, run_id, duration, details)
        gcmd.respond_info(
            "Calibration history: %s %s" % (calibration, status))

    def get_status(self, eventtime):
        return {
            "log_path": self.log_path,
            "machine": self.machine,
            "active": sorted(self.active),
            "last_event": self.last_event,
        }


def load_config(config):
    return CalibrationHistory(config)
