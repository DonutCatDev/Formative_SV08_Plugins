import csv
import datetime
import importlib.util
import pathlib
import sys
import tempfile
import types
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE = ROOT / "plugins/print_outcome/klippy/extras/print_outcome.py"


display_menu = types.ModuleType("testpkg.display.menu")
display_menu.MenuInput = type("MenuInput", (), {})
display_menu.MenuList = type("MenuList", (), {})
display_pkg = types.ModuleType("testpkg.display")
display_pkg.menu = display_menu
sys.modules["testpkg"] = types.ModuleType("testpkg")
sys.modules["testpkg.display"] = display_pkg
sys.modules["testpkg.display.menu"] = display_menu
spec = importlib.util.spec_from_file_location("testpkg.print_outcome", MODULE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeGcmd:
    def __init__(self, token, count=None, comment=None):
        self.values = {"TOKEN": token}
        if count is not None:
            self.values["COUNT"] = count
        if comment is not None:
            self.values["COMMENT"] = comment
        self.responses = []

    def get_int(self, name, minval=None):
        value = self.values[name]
        if minval is not None and value < minval:
            raise ValueError(name)
        return value

    def error(self, message):
        return RuntimeError(message)

    def get(self, name):
        return self.values[name]

    def respond_info(self, message):
        self.responses.append(message)


class FakeMenu:
    def __init__(self):
        self.running = True
        self.exited = False

    def is_running(self):
        return self.running

    def exit(self, force=False):
        self.exited = force
        self.running = False


class FakeTemplate:
    def render(self):
        return "RESET_LCD"


class FakeGcode:
    def __init__(self):
        self.scripts = []

    def run_script_from_command(self, script):
        self.scripts.append(script)


class FakePrintStats:
    def __init__(self, status):
        self.status = status

    def get_status(self, eventtime):
        return self.status


class FakePrinter:
    def __init__(self, status):
        self.print_stats = FakePrintStats(status)

    def lookup_object(self, name):
        if name == "print_stats":
            return self.print_stats
        raise KeyError(name)


class PrintOutcomeTests(unittest.TestCase):
    def test_quantity_suffix(self):
        self.assertEqual(module.quantity_from_filename("part_QTY24.gcode"), 24)
        self.assertEqual(module.quantity_from_filename("A qty7.GCO"), 7)
        self.assertEqual(module.quantity_from_filename("QTY0.gcode"), 0)
        self.assertIsNone(module.quantity_from_filename("QTY8_repaired.gcode"))
        self.assertIsNone(module.quantity_from_filename("equality8.gcode"))

    def test_quantity_source_order_and_cap(self):
        plugin = object.__new__(module.PrintOutcome)
        plugin.maximum_quantity = 50
        plugin.default_quantity = 1
        plugin._object_count = lambda eventtime: 6
        self.assertEqual(plugin._quantity_for("part_QTY8.gcode", 10.), 8)
        self.assertEqual(plugin._quantity_for("part_QTY80.gcode", 10.), 50)
        self.assertEqual(plugin._quantity_for("part.gcode", 10.), 6)
        plugin._object_count = lambda eventtime: None
        self.assertEqual(plugin._quantity_for("part.gcode", 10.), 1)

    def test_committed_zero_remains_the_display_value(self):
        plugin = types.SimpleNamespace(selected_quantity=1)
        quantity_input = object.__new__(module.OutcomeQuantityInput)
        quantity_input.plugin = plugin
        quantity_input._store(None, {"menu": {"input": 0.0}})
        self.assertEqual(plugin.selected_quantity, 0)
        self.assertEqual(quantity_input._eval_value({}), 0.0)

    def test_activation_resets_screen_color_immediately(self):
        activation = (ROOT / "plugins/print_outcome/activation/custom_plugins"
                      / "print-outcome.cfg").read_text()
        self.assertIn(
            "SET_LED LED=Screen_Colour RED=0.5 GREEN=0.4 BLUE=0.7 SYNC=0",
            activation)

    def test_comment_menu_has_the_three_metric_categories(self):
        manager = types.SimpleNamespace(
            menuitem_from=lambda item_type, **kwargs: kwargs)
        plugin = types.SimpleNamespace(pending_token=12)
        dialog = object.__new__(module.MenuOutcomeComment)
        dialog.plugin = plugin
        dialog.manager = manager
        items = []
        dialog.insert_item = items.append

        dialog._populate()

        self.assertEqual(
            [item["name"] for item in items],
            ["Reason for zero?", "Test", "Machine", "Filament"])
        self.assertEqual(
            [item["gcode"](None, {}) for item in items[1:]],
            [
                "PRINT_OUTCOME_COMMENT TOKEN=12 COMMENT=Test",
                "PRINT_OUTCOME_COMMENT TOKEN=12 COMMENT=Machine",
                "PRINT_OUTCOME_COMMENT TOKEN=12 COMMENT=Filament",
            ])

    def test_csv_append_and_accept(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin = object.__new__(module.PrintOutcome)
            plugin.log_path = str(pathlib.Path(directory) / "outcomes.csv")
            plugin.pending_token = 3
            plugin.pending = {
                "token": 3,
                "stage": "quantity",
                "filename": "widgets_QTY4.gcode",
                "start_time": datetime.datetime(
                    2026, 9, 16, 10, 0, tzinfo=datetime.timezone.utc),
                "end_time": datetime.datetime(
                    2026, 9, 16, 10, 2, tzinfo=datetime.timezone.utc),
                "total_duration": 120.25,
            }
            plugin.quantity_limit = 4
            plugin.selected_quantity = 3
            plugin.menu = FakeMenu()
            plugin.reset_gcode = FakeTemplate()
            plugin.gcode = FakeGcode()
            gcmd = FakeGcmd(3, 3)

            plugin.cmd_PRINT_OUTCOME_ACCEPT(gcmd)

            with open(plugin.log_path, newline="", encoding="utf-8") as stream:
                rows = list(csv.reader(stream))
            self.assertEqual(rows[0][-2:], ["accepted_count", "comment"])
            self.assertEqual(rows[1][0], "widgets_QTY4.gcode")
            self.assertEqual(rows[1][3:], ["120.250", "3", ""])
            self.assertIsNone(plugin.pending)
            self.assertTrue(plugin.menu.exited)
            self.assertEqual(plugin.gcode.scripts, ["RESET_LCD"])

    def test_zero_accept_requires_comment_before_logging(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin = object.__new__(module.PrintOutcome)
            plugin.log_path = str(pathlib.Path(directory) / "outcomes.csv")
            plugin.pending_token = 5
            plugin.pending = {
                "token": 5,
                "stage": "quantity",
                "filename": "failed_QTY2.gcode",
                "start_time": datetime.datetime(
                    2026, 9, 16, 10, 0, tzinfo=datetime.timezone.utc),
                "end_time": datetime.datetime(
                    2026, 9, 16, 10, 2, tzinfo=datetime.timezone.utc),
                "total_duration": 120.0,
            }
            plugin.quantity_limit = 2
            plugin.selected_quantity = 0
            plugin.reactor = types.SimpleNamespace(monotonic=lambda: 20.0)
            shown = []
            plugin._show_comment_prompt = shown.append

            accept = FakeGcmd(5, 0)
            plugin.cmd_PRINT_OUTCOME_ACCEPT(accept)

            self.assertFalse(pathlib.Path(plugin.log_path).exists())
            self.assertEqual(plugin.pending["stage"], "comment")
            self.assertEqual(plugin.pending["accepted_count"], 0)
            self.assertEqual(shown, [20.0])
            self.assertEqual(
                accept.responses, ["Select a reason for the zero outcome"])

            plugin.menu = FakeMenu()
            plugin.reset_gcode = FakeTemplate()
            plugin.gcode = FakeGcode()
            comment = FakeGcmd(5, comment="Machine")
            plugin.cmd_PRINT_OUTCOME_COMMENT(comment)

            with open(plugin.log_path, newline="", encoding="utf-8") as stream:
                rows = list(csv.reader(stream))
            self.assertEqual(rows[1][3:], ["120.000", "0", "Machine"])
            self.assertEqual(plugin.gcode.scripts, ["RESET_LCD"])

    def test_cancelled_print_prompts_for_comment_then_logs_and_resets(self):
        for previous_state in ("printing", "paused", "error"):
            with self.subTest(previous_state=previous_state), \
                    tempfile.TemporaryDirectory() as directory:
                status = {
                    "state": "cancelled",
                    "filename": "cancelled_QTY4.gcode",
                    "total_duration": 42.5,
                }
                plugin = object.__new__(module.PrintOutcome)
                plugin.printer = FakePrinter(status)
                plugin.log_path = str(
                    pathlib.Path(directory) / "outcomes.csv")
                plugin.last_state = previous_state
                plugin.pending_token = 0
                plugin.poll_interval = 0.25
                shown = []
                plugin._show_comment_prompt = shown.append

                next_poll = plugin._poll(10.0)
                plugin._poll(next_poll)

                self.assertFalse(pathlib.Path(plugin.log_path).exists())
                self.assertEqual(shown, [10.0])
                self.assertEqual(plugin.pending["stage"], "comment")
                self.assertEqual(plugin.pending["accepted_count"], 0)
                self.assertEqual(plugin.pending_token, 1)
                plugin.menu = FakeMenu()
                plugin.reset_gcode = FakeTemplate()
                plugin.gcode = FakeGcode()
                plugin.cmd_PRINT_OUTCOME_COMMENT(
                    FakeGcmd(1, comment="Filament"))

                with open(plugin.log_path, newline="",
                          encoding="utf-8") as stream:
                    rows = list(csv.reader(stream))
                self.assertEqual(len(rows), 2)
                self.assertEqual(rows[1][0], "cancelled_QTY4.gcode")
                self.assertEqual(rows[1][3:], [
                    "42.500", "0", "Filament"])
                self.assertEqual(plugin.last_state, "cancelled")
                self.assertEqual(next_poll, 10.25)
                self.assertEqual(plugin.gcode.scripts, ["RESET_LCD"])

    def test_legacy_csv_is_upgraded_before_append(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin = object.__new__(module.PrintOutcome)
            plugin.log_path = str(pathlib.Path(directory) / "outcomes.csv")
            with open(plugin.log_path, "w", newline="", encoding="utf-8") \
                    as stream:
                writer = csv.writer(stream)
                writer.writerow(module.LEGACY_CSV_HEADER)
                writer.writerow(("old.gcode", "start", "end", "1.000", 1))
            outcome = {
                "filename": "new.gcode",
                "start_time": datetime.datetime(
                    2026, 9, 16, 10, 0, tzinfo=datetime.timezone.utc),
                "end_time": datetime.datetime(
                    2026, 9, 16, 10, 1, tzinfo=datetime.timezone.utc),
                "total_duration": 60.0,
            }

            plugin._append_log(outcome, 0, "Test")

            with open(plugin.log_path, newline="", encoding="utf-8") as stream:
                rows = list(csv.reader(stream))
            self.assertEqual(tuple(rows[0]), module.CSV_HEADER)
            self.assertEqual(rows[1][-1], "")
            self.assertEqual(rows[2][-2:], ["0", "Test"])

    def test_rejects_stale_or_out_of_range_accept(self):
        plugin = object.__new__(module.PrintOutcome)
        plugin.pending = {"token": 8, "stage": "quantity"}
        plugin.quantity_limit = 2
        with self.assertRaisesRegex(RuntimeError, "expired"):
            plugin.cmd_PRINT_OUTCOME_ACCEPT(FakeGcmd(7, 1))
        with self.assertRaisesRegex(RuntimeError, "exceeds"):
            plugin.cmd_PRINT_OUTCOME_ACCEPT(FakeGcmd(8, 3))

    def test_rejects_stale_or_unknown_comment(self):
        plugin = object.__new__(module.PrintOutcome)
        plugin.pending = {"token": 8, "stage": "comment"}
        with self.assertRaisesRegex(RuntimeError, "expired"):
            plugin.cmd_PRINT_OUTCOME_COMMENT(
                FakeGcmd(7, comment="Machine"))
        with self.assertRaisesRegex(RuntimeError, "Unknown"):
            plugin.cmd_PRINT_OUTCOME_COMMENT(
                FakeGcmd(8, comment="Other"))


if __name__ == "__main__":
    unittest.main()
