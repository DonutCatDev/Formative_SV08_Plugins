# Hierarchical virtual-SD browser for Klipper character displays.
#
# Copyright (C) 2026 Formative
#
# This file may be distributed under the terms of the GNU GPLv3 license.

import collections
import logging
import math
import os
import re

from .display import menu as display_menu


def _is_within(root, candidate):
    """Return True when candidate resolves to root or one of its children."""
    try:
        return os.path.commonpath((root, candidate)) == root
    except ValueError:
        return False


_HUMAN_TIME_RE = re.compile(
    r"estimated\s+printing\s+time(?:\s*\([^)]*\))?\s*=\s*"
    r"(?:(\d+)\s*d\s*)?(?:(\d+)\s*h\s*)?"
    r"(?:(\d+)\s*m\s*)?(?:(\d+(?:\.\d+)?)\s*s)?",
    re.IGNORECASE)
_CURA_TIME_RE = re.compile(r"^\s*;\s*TIME\s*:\s*(\d+(?:\.\d+)?)", re.MULTILINE)
_HEATSOAK_RE = re.compile(
    r"^\s*START_PRINT\b[^\r\n;]*?\bHEATSOAK\s*=\s*"
    r"([+]?(?:\d+(?:\.\d*)?|\.\d+))",
    re.IGNORECASE | re.MULTILINE)


def _parse_slicer_seconds(text):
    match = _HUMAN_TIME_RE.search(text)
    if match is not None and any(value is not None for value in match.groups()):
        days, hours, minutes, seconds = (
            float(value or 0) for value in match.groups())
        return days * 86400 + hours * 3600 + minutes * 60 + seconds
    match = _CURA_TIME_RE.search(text)
    return float(match.group(1)) if match is not None else None


def _parse_heatsoak_minutes(text):
    match = _HEATSOAK_RE.search(text)
    return float(match.group(1)) if match is not None else None


def _format_estimate(seconds):
    if seconds is None:
        return "Time unavailable"
    total_minutes = int(math.ceil(seconds / 60.0))
    hours, minutes = divmod(total_minutes, 60)
    if hours:
        return "Est %dh%02dm" % (hours, minutes)
    return "Est %dm" % (minutes,)


class MenuLCDVSDFile(display_menu.MenuList):
    def __init__(self, manager, plugin, relative_path, size):
        self.plugin = plugin
        self.relative_path = relative_path
        self.file_size = size
        super(MenuLCDVSDFile, self).__init__(
            manager, None, name=os.path.basename(relative_path))

    def _names_aslist(self):
        # Dynamic containers must not inherit statically configured children.
        return []

    def _populate(self):
        super(MenuLCDVSDFile, self)._populate()
        filename = os.path.basename(self.relative_path)

        def start_print(element, context):
            token = self.plugin.remember_file(self.relative_path)
            element.manager.exit()
            return "LCD_VSD_PRINT TOKEN=%d" % (token,)

        self.insert_item(self.manager.menuitem_from(
            "command", name="Print now", gcode=start_print))
        self.insert_item(self.manager.menuitem_from(
            "command", name=filename, gcode=lambda element, context: ""))
        estimate = self.plugin.estimate_file(self.relative_path)
        self.insert_item(self.manager.menuitem_from(
            "command", name=_format_estimate(estimate),
            gcode=lambda element, context: ""))


class MenuLCDVSDDirectory(display_menu.MenuList):
    def __init__(self, manager, config, **kwargs):
        self.plugin = manager.printer.lookup_object("lcd_vsd_browser")
        self.relative_path = kwargs.pop("relative_path", "")
        super(MenuLCDVSDDirectory, self).__init__(manager, config, **kwargs)

    def _names_aslist(self):
        # In particular, omit the stock __start item below __main __sdcard.
        return []

    def _populate(self):
        super(MenuLCDVSDDirectory, self)._populate()
        try:
            directories, files = self.plugin.list_directory(self.relative_path)
        except OSError:
            logging.exception(
                "LCD virtual-SD browser could not read %r", self.relative_path)
            self.insert_item(self.manager.menuitem_from(
                "command", name="Directory error",
                gcode=lambda element, context: ""))
            return

        for name in directories:
            child_path = os.path.join(self.relative_path, name)
            self.insert_item(MenuLCDVSDDirectory(
                self.manager, None, name=name, relative_path=child_path))

        for name, size in files:
            child_path = os.path.join(self.relative_path, name)
            if self.plugin.confirm_print:
                item = MenuLCDVSDFile(
                    self.manager, self.plugin, child_path, size)
            else:
                def start_print(element, context, path=child_path):
                    token = self.plugin.remember_file(path)
                    element.manager.exit()
                    return "LCD_VSD_PRINT TOKEN=%d" % (token,)
                item = self.manager.menuitem_from(
                    "command", name=name, gcode=start_print)
            self.insert_item(item)

        if not directories and not files:
            self.insert_item(self.manager.menuitem_from(
                "command", name="(empty)",
                gcode=lambda element, context: ""))


class LCDVSDFileBrowser:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object("gcode")
        extensions = config.getlist(
            "extensions", ("gcode", "g", "gco"))
        self.extensions = frozenset(
            value.lower().lstrip(".") for value in extensions if value.strip())
        if not self.extensions:
            raise config.error("lcd_vsd_browser requires at least one extension")
        self.show_hidden = config.getboolean("show_hidden", False)
        self.confirm_print = config.getboolean("confirm_print", True)
        self.max_tokens = config.getint("max_remembered_files", 256, minval=16)
        self.startup_minutes = config.getfloat(
            "startup_minutes", 9.0, minval=0.0)
        self.default_heatsoak_minutes = config.getfloat(
            "default_heatsoak_minutes", 10.0, minval=0.0)
        self.metadata_read_bytes = config.getint(
            "metadata_read_bytes", 262144, minval=4096)
        self._next_token = 1
        self._files = collections.OrderedDict()
        self._estimate_cache = {}
        self.gcode.register_command(
            "LCD_VSD_PRINT", self.cmd_LCD_VSD_PRINT,
            desc="Print a file selected by the LCD virtual-SD browser")

        # Replace the stock vsdlist implementation before [display] constructs
        # configured menu items. Keep a distinct alias for optional custom use.
        display_menu.menu_items["vsdlist"] = MenuLCDVSDDirectory
        display_menu.menu_items["vsd_browser"] = MenuLCDVSDDirectory

    def _virtual_sd(self):
        sdcard = self.printer.lookup_object("virtual_sdcard", None)
        if sdcard is None:
            raise self.printer.command_error(
                "lcd_vsd_browser requires [virtual_sdcard]")
        return sdcard

    def _root(self):
        return os.path.realpath(self._virtual_sd().sdcard_dirname)

    def _resolve(self, relative_path):
        root = self._root()
        candidate = os.path.realpath(os.path.join(root, relative_path))
        if not _is_within(root, candidate):
            raise self.printer.command_error(
                "LCD virtual-SD path escapes the configured root")
        return root, candidate

    def list_directory(self, relative_path):
        root, directory = self._resolve(relative_path)
        directories = []
        files = []
        with os.scandir(directory) as entries:
            for entry in entries:
                if not self.show_hidden and entry.name.startswith("."):
                    continue
                # Directory symlinks are omitted to prevent loops and aliases.
                if entry.is_dir(follow_symlinks=False):
                    directories.append(entry.name)
                    continue
                if not entry.is_file(follow_symlinks=True):
                    continue
                resolved = os.path.realpath(entry.path)
                if not _is_within(root, resolved):
                    continue
                extension = entry.name.rsplit(".", 1)[-1].lower()
                if extension not in self.extensions:
                    continue
                files.append((entry.name, entry.stat().st_size))
        directories.sort(key=str.lower)
        files.sort(key=lambda item: item[0].lower())
        return directories, files

    def remember_file(self, relative_path):
        # Keep raw paths out of generated G-Code. A numeric token avoids parser
        # ambiguity for spaces, quotes, comment characters, and Unicode names.
        token = self._next_token
        self._next_token += 1
        self._files[token] = relative_path
        while len(self._files) > self.max_tokens:
            self._files.popitem(last=False)
        return token

    def estimate_file(self, relative_path):
        root, filename = self._resolve(relative_path)
        stat = os.stat(filename)
        cache_key = (filename, stat.st_size, stat.st_mtime_ns)
        if cache_key in self._estimate_cache:
            return self._estimate_cache[cache_key]

        read_size = self.metadata_read_bytes
        with open(filename, "rb") as gcode_file:
            head = gcode_file.read(read_size)
            if stat.st_size > read_size:
                gcode_file.seek(max(0, stat.st_size - read_size))
                tail = gcode_file.read(read_size)
            else:
                tail = b""
        head_text = head.decode("utf-8", "replace")
        tail_text = tail.decode("utf-8", "replace")
        slicer_seconds = _parse_slicer_seconds(tail_text)
        if slicer_seconds is None:
            slicer_seconds = _parse_slicer_seconds(head_text)
        if slicer_seconds is None:
            estimate = None
        else:
            heatsoak = _parse_heatsoak_minutes(head_text)
            if heatsoak is None:
                heatsoak = self.default_heatsoak_minutes
            estimate = slicer_seconds + 60.0 * (
                heatsoak + self.startup_minutes)

        # Retain only current entries and keep cache growth bounded.
        self._estimate_cache = {
            key: value for key, value in self._estimate_cache.items()
            if key[0] != filename
        }
        self._estimate_cache[cache_key] = estimate
        while len(self._estimate_cache) > self.max_tokens:
            self._estimate_cache.pop(next(iter(self._estimate_cache)))
        return estimate

    def cmd_LCD_VSD_PRINT(self, gcmd):
        token = gcmd.get_int("TOKEN", minval=1)
        relative_path = self._files.get(token)
        if relative_path is None:
            raise gcmd.error("LCD file selection expired; select the file again")
        root, filename = self._resolve(relative_path)
        if not os.path.isfile(filename):
            raise gcmd.error("Selected LCD file no longer exists")
        extension = filename.rsplit(".", 1)[-1].lower()
        if extension not in self.extensions:
            raise gcmd.error("Selected LCD file is not an allowed G-Code file")
        sdcard = self._virtual_sd()
        if sdcard.is_active():
            raise gcmd.error("SD busy")
        normalized = os.path.relpath(filename, root)
        print_gcmd = self.gcode.create_gcode_command(
            "SDCARD_PRINT_FILE", "SDCARD_PRINT_FILE",
            {"FILENAME": normalized})
        sdcard.cmd_SDCARD_PRINT_FILE(print_gcmd)
        del self._files[token]

    def get_status(self, eventtime):
        return {
            "extensions": sorted(self.extensions),
            "confirm_print": self.confirm_print,
            "show_hidden": self.show_hidden,
            "startup_minutes": self.startup_minutes,
            "default_heatsoak_minutes": self.default_heatsoak_minutes,
        }


def load_config(config):
    return LCDVSDFileBrowser(config)
