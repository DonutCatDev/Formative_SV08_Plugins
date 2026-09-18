# Persistent single-spool tracking and LCD preflight for Klipper.
# Copyright (C) 2026 Formative; GNU GPLv3.
import csv
import datetime
import json
import math
import os
import tempfile

from .display import menu as display_menu


TERMINAL_STATES = frozenset(("complete", "cancelled", "error"))


def _display_grams(value):
    if value is None:
        return "unknown"
    return "%dg" % int(math.ceil(max(0., value)))


class SpoolAmountInput(display_menu.MenuInput):
    def __init__(self, manager, plugin):
        self.plugin = plugin
        super().__init__(
            manager, None, input=plugin.selected_amount, input_min=0,
            input_max=plugin.maximum_spool_grams, input_step=1,
            realtime=True, gcode=self._store)

    def _render_name(self):
        value = self.get_context()["menu"]["input"]
        return "Amount: %dg" % int(value)

    def _eval_value(self, context):
        return float(self.plugin.selected_amount)

    def _store(self, element, context):
        self.plugin.selected_amount = int(context["menu"]["input"])
        return ""


class MenuNewSpool(display_menu.MenuList):
    def __init__(self, manager, plugin):
        self.plugin = plugin
        super().__init__(manager, None, name="New spool")

    def _names_aslist(self):
        return []

    def _populate(self):
        self._viewport_top = 0
        self.insert_item(self.manager.menuitem_from(
            "command", name="New spool", gcode=lambda el, ctx: ""))
        self.insert_item(SpoolAmountInput(self.manager, self.plugin))
        self.insert_item(self.manager.menuitem_from(
            "command", name="Confirm", gcode=self._confirm))
        self.insert_item(self.manager.menuitem_from(
            "command", name="Cancel", gcode=self._cancel))

    def init_selection(self):
        self.select_at(1)

    def _confirm(self, element, context):
        return "FILAMENT_TRACKER_SET_SPOOL AMOUNT=%d" % (
            self.plugin.selected_amount,)

    def _cancel(self, element, context):
        return "FILAMENT_TRACKER_CANCEL"


class MenuFilamentCheck(display_menu.MenuList):
    def __init__(self, manager, plugin):
        self.plugin = plugin
        super().__init__(manager, None, name="Filament check")

    def _names_aslist(self):
        return []

    def _populate(self):
        self._viewport_top = 0
        pending = self.plugin.pending
        needed = pending["expected_g"]
        remaining = self.plugin.remaining_grams
        self.insert_item(self.manager.menuitem_from(
            "command", name="Need %s" % _display_grams(needed),
            gcode=lambda el, ctx: ""))
        self.insert_item(self.manager.menuitem_from(
            "command", name="Spool %s" % _display_grams(remaining),
            gcode=lambda el, ctx: ""))
        if needed is None:
            comparison = "Usage unavailable"
        elif remaining is None:
            comparison = "Spool not set"
        elif remaining >= needed + self.plugin.safety_margin_grams:
            comparison = "After %s" % _display_grams(remaining - needed)
        else:
            comparison = "Short %s" % _display_grams(
                needed + self.plugin.safety_margin_grams - remaining)
        self.insert_item(self.manager.menuitem_from(
            "command", name=comparison, gcode=lambda el, ctx: ""))
        safe = (needed is not None and remaining is not None and
                remaining >= needed + self.plugin.safety_margin_grams)
        self.insert_item(self.manager.menuitem_from(
            "command", name=("Start print" if safe else "Continue anyway"),
            gcode=self._start))
        self.insert_item(self.manager.menuitem_from(
            "command", name="New spool", gcode=self._new_spool))
        self.insert_item(self.manager.menuitem_from(
            "command", name="Cancel", gcode=self._cancel))

    def init_selection(self):
        self.select_at(3)

    def _start(self, element, context):
        return "FILAMENT_TRACKER_START TOKEN=%d" % self.plugin.pending["token"]

    def _new_spool(self, element, context):
        return "FILAMENT_TRACKER_NEW_SPOOL RETURN_TO_CHECK=1"

    def _cancel(self, element, context):
        return "FILAMENT_TRACKER_CANCEL"


class FilamentTracker:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.config_error = config.error
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object("gcode")
        default_state = "~/printer_data/config/filament-tracker.json"
        default_log = "~/printer_data/config/filament-events.csv"
        self.state_path = os.path.abspath(os.path.expanduser(
            config.get("state_path", default_state)))
        self.log_path = os.path.abspath(os.path.expanduser(
            config.get("log_path", default_log)))
        self.maximum_spool_grams = config.getint(
            "maximum_spool_grams", 3000, minval=1)
        self.default_spool_grams = config.getint(
            "default_spool_grams", self.maximum_spool_grams, minval=0,
            maxval=self.maximum_spool_grams)
        self.safety_margin_grams = config.getfloat(
            "safety_margin_grams", 0., minval=0.)
        self.poll_interval = config.getfloat("poll_interval", 0.5, above=0.)
        self.state = self._load_state()
        self.pending = None
        self.selected_amount = self.default_spool_grams
        self.return_to_check = False
        self.menu = None
        self.last_print_state = None
        self.timer = self.reactor.register_timer(self._poll)
        self.gcode.register_command(
            "FILAMENT_TRACKER_NEW_SPOOL", self.cmd_NEW_SPOOL,
            desc="Open the LCD amount prompt for a newly loaded spool")
        self.gcode.register_command(
            "FILAMENT_TRACKER_SET_SPOOL", self.cmd_SET_SPOOL,
            desc="Persist the amount on the newly loaded spool")
        self.gcode.register_command(
            "FILAMENT_TRACKER_START", self.cmd_START,
            desc="Start the file approved by the filament preflight")
        self.gcode.register_command(
            "FILAMENT_TRACKER_CANCEL", self.cmd_CANCEL,
            desc="Cancel the active filament tracker LCD workflow")
        self.printer.register_event_handler("klippy:ready", self._handle_ready)

    @property
    def remaining_grams(self):
        value = self.state.get("remaining_g")
        return None if value is None else max(0., float(value))

    def _load_state(self):
        default = {"schema_version": 1, "remaining_g": None,
                   "loaded_at": None, "active_job": None}
        try:
            with open(self.state_path, encoding="utf-8") as stream:
                loaded = json.load(stream)
        except FileNotFoundError:
            return default
        except (OSError, ValueError, TypeError) as exc:
            raise self.config_error(
                "Unable to load filament tracker state: %s" % exc)
        if not isinstance(loaded, dict) or loaded.get("schema_version") != 1:
            raise self.config_error(
                "Unsupported filament tracker state format")
        default.update(loaded)
        return default

    def _write_state(self):
        parent = os.path.dirname(self.state_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=".filament-tracker-", suffix=".tmp", dir=parent or ".")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(self.state, stream, sort_keys=True, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.state_path)
            if parent:
                directory_fd = os.open(parent, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _append_event(self, event, filename="", expected_g=None,
                      used_g=None, remaining_g=None, detail=""):
        parent = os.path.dirname(self.log_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        needs_header = not os.path.exists(self.log_path) or os.path.getsize(
            self.log_path) == 0
        with open(self.log_path, "a", newline="", encoding="utf-8") as stream:
            writer = csv.writer(stream)
            if needs_header:
                writer.writerow(("timestamp", "event", "filename",
                                 "expected_g", "used_g", "remaining_g",
                                 "detail"))
            writer.writerow((
                datetime.datetime.now().astimezone().isoformat(
                    timespec="seconds"), event, filename,
                "" if expected_g is None else "%.3f" % expected_g,
                "" if used_g is None else "%.3f" % used_g,
                "" if remaining_g is None else "%.3f" % remaining_g,
                detail))
            stream.flush()
            os.fsync(stream.fileno())

    def _handle_ready(self):
        self.menu = self.printer.lookup_object("menu")
        stats = self.printer.lookup_object("print_stats").get_status(
            self.reactor.monotonic())
        self.last_print_state = stats.get("state")
        if (self.state.get("active_job") is not None and
                self.last_print_state == "standby"):
            job = self.state["active_job"]
            self._append_event(
                "tracking_abandoned", job.get("filename", ""),
                job.get("expected_g"), remaining_g=self.remaining_grams,
                detail="Klipper restarted without recoverable print stats")
            self.state["active_job"] = None
            self._write_state()
        self.reactor.update_timer(self.timer, self.reactor.NOW)

    def _show_dialog(self, dialog):
        eventtime = self.reactor.monotonic()
        if self.menu.is_running():
            self.menu.exit(force=True)
        self.menu.begin(eventtime)
        if not self.menu.push_container(dialog):
            raise self.printer.command_error(
                "Unable to open the filament tracker LCD prompt")

    def begin_check(self, token, relative_path, expected_g, expected_mm):
        if self.state.get("active_job") is not None:
            raise self.printer.command_error(
                "Another filament-tracked print is still active")
        self.pending = {
            "token": token, "filename": relative_path,
            "expected_g": expected_g, "expected_mm": expected_mm,
        }
        self._show_dialog(MenuFilamentCheck(self.menu, self))

    def _current_filament_mm(self):
        stats = self.printer.lookup_object("print_stats").get_status(
            self.reactor.monotonic())
        return max(0., float(stats.get("filament_used", 0.)))

    def _job_usage_grams(self, job, current_mm, terminal_state=None):
        delta_mm = max(0., current_mm - float(job.get("accounted_mm", 0.)))
        expected_g = job.get("expected_g")
        expected_mm = job.get("expected_mm")
        if expected_g is not None and expected_mm not in (None, 0):
            return delta_mm * float(expected_g) / float(expected_mm)
        if terminal_state == "complete" and expected_g is not None:
            return max(0., float(expected_g))
        return 0.

    def _charge_active_segment(self, event, terminal_state=None):
        job = self.state.get("active_job")
        if job is None:
            return 0.
        current_mm = self._current_filament_mm()
        used_g = self._job_usage_grams(job, current_mm, terminal_state)
        remaining = self.remaining_grams
        if remaining is not None:
            self.state["remaining_g"] = max(0., remaining - used_g)
        job["accounted_mm"] = current_mm
        self._append_event(
            event, job.get("filename", ""), job.get("expected_g"), used_g,
            self.remaining_grams, terminal_state or "")
        return used_g

    def _poll(self, eventtime):
        stats = self.printer.lookup_object("print_stats").get_status(eventtime)
        state = stats.get("state")
        job = self.state.get("active_job")
        if job is not None and state in ("printing", "paused"):
            if not job.get("observed_active"):
                job["observed_active"] = True
                self._write_state()
        if (job is not None and job.get("observed_active") and
                state in TERMINAL_STATES):
            self._charge_active_segment("print_%s" % state, state)
            self.state["active_job"] = None
            self._write_state()
        self.last_print_state = state
        return eventtime + self.poll_interval

    def cmd_NEW_SPOOL(self, gcmd):
        stats = self.printer.lookup_object("print_stats").get_status(
            self.reactor.monotonic())
        if stats.get("state") == "printing":
            raise gcmd.error("Pause the print before loading a new spool")
        self.return_to_check = bool(gcmd.get_int(
            "RETURN_TO_CHECK", 0, minval=0, maxval=1))
        self.selected_amount = self.default_spool_grams
        self._show_dialog(MenuNewSpool(self.menu, self))

    def cmd_SET_SPOOL(self, gcmd):
        stats = self.printer.lookup_object("print_stats").get_status(
            self.reactor.monotonic())
        if stats.get("state") == "printing":
            raise gcmd.error("Pause the print before recording a new spool")
        amount = gcmd.get_int(
            "AMOUNT", minval=0, maxval=self.maximum_spool_grams)
        job = self.state.get("active_job")
        if job is not None:
            self._charge_active_segment("spool_segment_closed")
        self.state["remaining_g"] = float(amount)
        self.state["loaded_at"] = datetime.datetime.now().astimezone().isoformat(
            timespec="seconds")
        self._write_state()
        self._append_event(
            "spool_loaded", remaining_g=self.remaining_grams,
            detail=("during_print" if job is not None else "idle"))
        if self.return_to_check and self.pending is not None:
            self.return_to_check = False
            self._show_dialog(MenuFilamentCheck(self.menu, self))
        else:
            self.return_to_check = False
            if self.menu.is_running():
                self.menu.exit(force=True)
        gcmd.respond_info("Loaded spool recorded: %dg" % amount)

    def cmd_START(self, gcmd):
        token = gcmd.get_int("TOKEN", minval=1)
        if self.pending is None or token != self.pending["token"]:
            raise gcmd.error("Filament check selection expired")
        browser = self.printer.lookup_object("lcd_vsd_browser", None)
        if browser is None or browser.remembered_file(token) is None:
            raise gcmd.error("LCD file selection expired; select the file again")
        job = dict(self.pending)
        job["started_at"] = datetime.datetime.now().astimezone().isoformat(
            timespec="seconds")
        job["accounted_mm"] = 0.
        job["observed_active"] = False
        self.state["active_job"] = job
        self._write_state()
        self._append_event(
            "print_authorized", job["filename"], job.get("expected_g"),
            remaining_g=self.remaining_grams)
        try:
            browser.start_token(token)
        except Exception:
            self.state["active_job"] = None
            self._write_state()
            raise
        job["observed_active"] = True
        self._write_state()
        self.pending = None
        if self.menu.is_running():
            self.menu.exit(force=True)

    def cmd_CANCEL(self, gcmd):
        self.pending = None
        self.return_to_check = False
        if self.menu.is_running():
            self.menu.exit(force=True)

    def get_status(self, eventtime):
        job = self.state.get("active_job")
        return {
            "remaining_grams": self.remaining_grams,
            "pending": self.pending is not None,
            "active_filename": "" if job is None else job.get("filename", ""),
            "state_path": self.state_path,
            "log_path": self.log_path,
        }


def load_config(config):
    return FilamentTracker(config)
