# Post-print operator outcome logging for Klipper character LCDs.
# Copyright (C) 2026 Formative; GNU GPLv3.
import csv
import datetime
import os
import re

from .display import menu as display_menu


QTY_RE = re.compile(r"(?:^|[^A-Z0-9])QTY([0-9]+)$", re.IGNORECASE)


def quantity_from_filename(filename):
    stem = os.path.splitext(os.path.basename(filename or ""))[0]
    match = QTY_RE.search(stem)
    return int(match.group(1)) if match else None


class OutcomeQuantityInput(display_menu.MenuInput):
    def __init__(self, manager, plugin):
        self.plugin = plugin
        super().__init__(
            manager, None, input=plugin.selected_quantity, input_min=0,
            input_max=plugin.quantity_limit, input_step=1, realtime=True,
            gcode=self._store)

    def _render_name(self):
        value = self.get_context()["menu"]["input"]
        return "Accepted: %d" % int(value)

    def _eval_value(self, context):
        # Klipper clears its temporary edit buffer on the second click. Read
        # the committed plugin value afterward instead of the initial maximum.
        return float(self.plugin.selected_quantity)

    def _store(self, element, context):
        self.plugin.selected_quantity = int(context["menu"]["input"])
        return ""


class MenuPrintOutcome(display_menu.MenuList):
    def __init__(self, manager, plugin):
        self.plugin = plugin
        super().__init__(manager, None, name="Print outcome")

    def _names_aslist(self):
        return []

    def _populate(self):
        # This is a modal prompt: omit MenuList's automatic back item.
        self._viewport_top = 0
        self.insert_item(self.manager.menuitem_from(
            "command", name="Print success?", gcode=lambda el, ctx: ""))
        self.insert_item(OutcomeQuantityInput(self.manager, self.plugin))
        self.insert_item(self.manager.menuitem_from(
            "command", name="Confirm", gcode=self._confirm))

    def init_selection(self):
        self.select_at(1)

    def _confirm(self, element, context):
        return "PRINT_OUTCOME_ACCEPT TOKEN=%d COUNT=%d" % (
            self.plugin.pending_token, self.plugin.selected_quantity)


class PrintOutcome:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.reactor = self.printer.get_reactor()
        self.gcode = self.printer.lookup_object("gcode")
        default_log = "~/printer_data/config/print-outcomes.csv"
        self.log_path = os.path.abspath(os.path.expanduser(
            config.get("log_path", default_log)))
        self.poll_interval = config.getfloat(
            "poll_interval", 0.25, above=0.)
        self.default_quantity = config.getint(
            "default_quantity", 1, minval=0)
        self.maximum_quantity = config.getint(
            "maximum_quantity", 9999, minval=1)
        self.reset_gcode = self.printer.load_object(
            config, "gcode_macro").load_template(
                config, "on_accept_gcode", """
SET_LED LED=Screen_Colour RED=0.5 GREEN=0.4 BLUE=0.7 SYNC=0
SET_DISPLAY_GROUP GROUP=sv08_home
M117
""")
        self.last_state = None
        self.pending = None
        self.pending_token = 0
        self.selected_quantity = 0
        self.quantity_limit = 0
        self.menu = None
        self.timer = self.reactor.register_timer(self._poll)
        self.gcode.register_command(
            "PRINT_OUTCOME_ACCEPT", self.cmd_PRINT_OUTCOME_ACCEPT,
            desc="Accept and log the pending completed-print outcome")
        self.printer.register_event_handler("klippy:ready", self._handle_ready)

    def _handle_ready(self):
        stats = self.printer.lookup_object("print_stats")
        self.last_state = stats.get_status(self.reactor.monotonic())["state"]
        self.menu = self.printer.lookup_object("menu")
        self.reactor.update_timer(self.timer, self.reactor.NOW)

    def _object_count(self, eventtime):
        exclude_object = self.printer.lookup_object("exclude_object", None)
        if exclude_object is None:
            return None
        objects = exclude_object.get_status(eventtime).get("objects", ())
        return len(objects) or None

    def _quantity_for(self, filename, eventtime):
        quantity = quantity_from_filename(filename)
        if quantity is None:
            quantity = self._object_count(eventtime)
        if quantity is None:
            quantity = self.default_quantity
        return min(quantity, self.maximum_quantity)

    def _poll(self, eventtime):
        status = self.printer.lookup_object("print_stats").get_status(eventtime)
        state = status["state"]
        if state == "complete" and self.last_state in ("printing", "paused"):
            self._begin_prompt(status, eventtime)
        self.last_state = state
        return eventtime + self.poll_interval

    def _begin_prompt(self, status, eventtime):
        end_time = datetime.datetime.now().astimezone()
        duration = max(0., float(status.get("total_duration", 0.)))
        self.pending_token += 1
        self.pending = {
            "token": self.pending_token,
            "filename": status.get("filename", ""),
            "start_time": end_time - datetime.timedelta(seconds=duration),
            "end_time": end_time,
            "total_duration": duration,
        }
        self.quantity_limit = self._quantity_for(
            self.pending["filename"], eventtime)
        self.selected_quantity = self.quantity_limit
        dialog = MenuPrintOutcome(self.menu, self)
        if self.menu.is_running():
            self.menu.exit(force=True)
        self.menu.begin(eventtime)
        if not self.menu.push_container(dialog):
            self.pending = None
            raise self.printer.command_error(
                "Unable to open the print outcome LCD prompt")

    def _append_log(self, count):
        parent = os.path.dirname(self.log_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        needs_header = not os.path.exists(self.log_path) or os.path.getsize(
            self.log_path) == 0
        with open(self.log_path, "a", newline="", encoding="utf-8") as logfile:
            writer = csv.writer(logfile)
            if needs_header:
                writer.writerow(("filename", "start_time", "end_time",
                                 "total_duration_seconds", "accepted_count"))
            writer.writerow((
                self.pending["filename"],
                self.pending["start_time"].isoformat(timespec="seconds"),
                self.pending["end_time"].isoformat(timespec="seconds"),
                "%.3f" % self.pending["total_duration"], count))
            logfile.flush()
            os.fsync(logfile.fileno())

    def cmd_PRINT_OUTCOME_ACCEPT(self, gcmd):
        token = gcmd.get_int("TOKEN", minval=1)
        count = gcmd.get_int("COUNT", minval=0)
        if self.pending is None or token != self.pending["token"]:
            raise gcmd.error("Print outcome selection expired")
        if count > self.quantity_limit:
            raise gcmd.error("Accepted count exceeds the pending quantity")
        self._append_log(count)
        self.pending = None
        self.selected_quantity = 0
        self.quantity_limit = 0
        if self.menu.is_running():
            self.menu.exit(force=True)
        # This handler is already running inside MenuManager's gcode.run_script
        # mutex. Dispatch directly from the active command to avoid reacquiring
        # that non-reentrant mutex and stalling before the LCD reset executes.
        self.gcode.run_script_from_command(self.reset_gcode.render())
        gcmd.respond_info("Print outcome logged: %d accepted" % count)

    def get_status(self, eventtime):
        return {
            "pending": self.pending is not None,
            "filename": "" if self.pending is None else self.pending["filename"],
            "quantity_limit": self.quantity_limit,
            "selected_quantity": self.selected_quantity,
            "log_path": self.log_path,
        }


def load_config(config):
    return PrintOutcome(config)
