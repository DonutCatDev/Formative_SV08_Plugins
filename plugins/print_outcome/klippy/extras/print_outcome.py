# Post-print operator outcome logging for Klipper character LCDs.
# Copyright (C) 2026 Formative; GNU GPLv3.
import csv
import datetime
import os
import re
import tempfile

from .display import menu as display_menu


QTY_RE = re.compile(r"(?:^|[^A-Z0-9])QTY([0-9]+)$", re.IGNORECASE)
ACTIVE_PRINT_STATES = ("printing", "paused", "error")
OUTCOME_COMMENTS = ("Test", "Machine", "Filament")
LEGACY_CSV_HEADER = (
    "filename", "start_time", "end_time", "total_duration_seconds",
    "accepted_count")
CSV_HEADER = LEGACY_CSV_HEADER + ("comment",)


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


class MenuOutcomeComment(display_menu.MenuList):
    def __init__(self, manager, plugin):
        self.plugin = plugin
        super().__init__(manager, None, name="Outcome reason")

    def _names_aslist(self):
        return []

    def _populate(self):
        # This is a modal prompt: omit MenuList's automatic back item.
        self._viewport_top = 0
        self.insert_item(self.manager.menuitem_from(
            "command", name="Reason for zero?", gcode=lambda el, ctx: ""))
        for comment in OUTCOME_COMMENTS:
            self.insert_item(self.manager.menuitem_from(
                "command", name=comment,
                gcode=lambda el, ctx, value=comment:
                    "PRINT_OUTCOME_COMMENT TOKEN=%d COMMENT=%s" % (
                        self.plugin.pending_token, value)))

    def init_selection(self):
        self.select_at(1)


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
        self.gcode.register_command(
            "PRINT_OUTCOME_COMMENT", self.cmd_PRINT_OUTCOME_COMMENT,
            desc="Classify and log a pending zero-print outcome")
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
        elif state == "cancelled" and self.last_state in ACTIVE_PRINT_STATES:
            self._begin_cancel_prompt(status, eventtime)
        self.last_state = state
        return eventtime + self.poll_interval

    def _outcome_for(self, status):
        end_time = datetime.datetime.now().astimezone()
        duration = max(0., float(status.get("total_duration", 0.)))
        return {
            "filename": status.get("filename", ""),
            "start_time": end_time - datetime.timedelta(seconds=duration),
            "end_time": end_time,
            "total_duration": duration,
        }

    def _begin_prompt(self, status, eventtime):
        self.pending_token += 1
        self.pending = self._outcome_for(status)
        self.pending["token"] = self.pending_token
        self.pending["stage"] = "quantity"
        self.quantity_limit = self._quantity_for(
            self.pending["filename"], eventtime)
        self.selected_quantity = self.quantity_limit
        self._open_dialog(MenuPrintOutcome(self.menu, self), eventtime)

    def _begin_cancel_prompt(self, status, eventtime):
        self.pending_token += 1
        self.pending = self._outcome_for(status)
        self.pending.update({
            "token": self.pending_token,
            "stage": "comment",
            "accepted_count": 0,
        })
        self.selected_quantity = 0
        self.quantity_limit = 0
        self._show_comment_prompt(eventtime)

    def _show_comment_prompt(self, eventtime):
        self._open_dialog(MenuOutcomeComment(self.menu, self), eventtime)

    def _open_dialog(self, dialog, eventtime):
        if self.menu.is_running():
            self.menu.exit(force=True)
        self.menu.begin(eventtime)
        if not self.menu.push_container(dialog):
            self.pending = None
            raise self.printer.command_error(
                "Unable to open the print outcome LCD prompt")

    def _upgrade_legacy_log(self):
        old_stat = os.stat(self.log_path)
        parent = os.path.dirname(self.log_path) or "."
        temporary_path = None
        try:
            with open(self.log_path, newline="", encoding="utf-8") as source:
                reader = csv.reader(source)
                header = next(reader, None)
                if tuple(header or ()) != LEGACY_CSV_HEADER:
                    raise ValueError("Unsupported print outcome CSV header")
                with tempfile.NamedTemporaryFile(
                        "w", newline="", encoding="utf-8", dir=parent,
                        prefix=".print-outcomes-", delete=False) as temporary:
                    temporary_path = temporary.name
                    writer = csv.writer(temporary)
                    writer.writerow(CSV_HEADER)
                    for row in reader:
                        if len(row) != len(LEGACY_CSV_HEADER):
                            raise ValueError(
                                "Malformed legacy print outcome CSV row")
                        writer.writerow(tuple(row) + ("",))
                    temporary.flush()
                    os.fsync(temporary.fileno())
            os.chmod(temporary_path, old_stat.st_mode & 0o7777)
            os.replace(temporary_path, self.log_path)
            temporary_path = None
        finally:
            if temporary_path is not None:
                try:
                    os.unlink(temporary_path)
                except FileNotFoundError:
                    pass

    def _prepare_log(self):
        if not os.path.exists(self.log_path) or os.path.getsize(
                self.log_path) == 0:
            return True
        with open(self.log_path, newline="", encoding="utf-8") as logfile:
            header = tuple(next(csv.reader(logfile), ()))
        if header == CSV_HEADER:
            return False
        if header == LEGACY_CSV_HEADER:
            self._upgrade_legacy_log()
            return False
        raise ValueError("Unsupported print outcome CSV header")

    def _append_log(self, outcome, count, comment=""):
        parent = os.path.dirname(self.log_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        needs_header = self._prepare_log()
        with open(self.log_path, "a", newline="", encoding="utf-8") as logfile:
            writer = csv.writer(logfile)
            if needs_header:
                writer.writerow(CSV_HEADER)
            writer.writerow((
                outcome["filename"],
                outcome["start_time"].isoformat(timespec="seconds"),
                outcome["end_time"].isoformat(timespec="seconds"),
                "%.3f" % outcome["total_duration"], count, comment))
            logfile.flush()
            os.fsync(logfile.fileno())

    def cmd_PRINT_OUTCOME_ACCEPT(self, gcmd):
        token = gcmd.get_int("TOKEN", minval=1)
        count = gcmd.get_int("COUNT", minval=0)
        if (self.pending is None or token != self.pending["token"]
                or self.pending["stage"] != "quantity"):
            raise gcmd.error("Print outcome selection expired")
        if count > self.quantity_limit:
            raise gcmd.error("Accepted count exceeds the pending quantity")
        if count == 0:
            self.pending["stage"] = "comment"
            self.pending["accepted_count"] = 0
            self.selected_quantity = 0
            self.quantity_limit = 0
            self._show_comment_prompt(self.reactor.monotonic())
            gcmd.respond_info("Select a reason for the zero outcome")
            return
        self.pending["accepted_count"] = count
        self._finish_pending(gcmd, "")

    def cmd_PRINT_OUTCOME_COMMENT(self, gcmd):
        token = gcmd.get_int("TOKEN", minval=1)
        comment = gcmd.get("COMMENT")
        if (self.pending is None or token != self.pending["token"]
                or self.pending["stage"] != "comment"):
            raise gcmd.error("Print outcome comment selection expired")
        if comment not in OUTCOME_COMMENTS:
            raise gcmd.error("Unknown print outcome comment")
        self._finish_pending(gcmd, comment)

    def _finish_pending(self, gcmd, comment):
        count = self.pending["accepted_count"]
        self._append_log(self.pending, count, comment)
        self.pending = None
        self.selected_quantity = 0
        self.quantity_limit = 0
        if self.menu.is_running():
            self.menu.exit(force=True)
        # This handler is already running inside MenuManager's gcode.run_script
        # mutex. Dispatch directly from the active command to avoid reacquiring
        # that non-reentrant mutex and stalling before the LCD reset executes.
        self.gcode.run_script_from_command(self.reset_gcode.render())
        suffix = " (%s)" % comment if comment else ""
        gcmd.respond_info("Print outcome logged: %d accepted%s" % (
            count, suffix))

    def get_status(self, eventtime):
        return {
            "pending": self.pending is not None,
            "filename": "" if self.pending is None else self.pending["filename"],
            "quantity_limit": self.quantity_limit,
            "selected_quantity": self.selected_quantity,
            "stage": "" if self.pending is None else self.pending["stage"],
            "log_path": self.log_path,
        }


def load_config(config):
    return PrintOutcome(config)
