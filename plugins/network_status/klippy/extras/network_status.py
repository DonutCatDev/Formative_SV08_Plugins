# Moonraker-backed on-demand network status for Klipper LCD menus
#
# Design goals:
#   * get_status() is cache-only and performs no I/O.
#   * Network information is refreshed only when the configured LCD menu
#     is populated, or when NETWORK_STATUS_REFRESH is issued manually.
#   * Moonraker's cached /machine/system_info data supplies IP/MAC data.
#   * SSID is queried with iwgetid only from a background worker thread.
#
# Compatible with Python 3.9+ (as used by current Klipper installations).

import json
import logging
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request


class NetworkStatus:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object("gcode")

        # Read every supported config option during construction. Klipper
        # rejects options that a module does not consume.
        self.menu_namespace = config.get(
            "menu_namespace", "__main __network"
        ).strip()
        self.moonraker_url = config.get(
            "moonraker_url", "http://127.0.0.1:7125"
        ).strip().rstrip("/")
        self.eth_interface = config.get(
            "ethernet_interface", "eth0"
        ).strip()
        self.wifi_interface = config.get(
            "wifi_interface", "wlan0"
        ).strip()
        self.extra_mcu_name = config.get(
            "extra_mcu_name", "extra_mcu"
        ).strip()
        self.api_key = config.get("api_key", "").strip()
        self.request_timeout = config.getfloat(
            "request_timeout", 1.0, minval=0.1, maxval=10.0
        )
        self.command_timeout = config.getfloat(
            "command_timeout", 1.0, minval=0.1, maxval=10.0
        )

        hostname = socket.gethostname().strip() or "N/A"
        klipper_version = self.printer.get_start_args().get(
            "software_version", "N/A"
        )

        self._lock = threading.Lock()
        self._refreshing = False
        self._status = {
            "hostname": hostname,
            "mdns": (hostname + ".local") if hostname != "N/A" else "N/A",
            "klipper_version": klipper_version,
            "mcu_version": "N/A",
            "extra_mcu_version": "N/A",
            "moonraker_ok": False,
            "moonraker_state": "unknown",
            "moonraker_version": "N/A",
            "ethip": "N/A",
            "ethmac": "N/A",
            "wifiip": "N/A",
            "wifimac": "N/A",
            "wifissid": "N/A",
            "active_interface": "N/A",
            "active_ip": "N/A",
            "refreshing": False,
            "last_update": 0.0,
            "last_error": "Not refreshed yet",
        }

        # MCU version data is already local to Klippy; capture it after the
        # MCU identify/connect sequence. No host/network I/O occurs here.
        self.printer.register_event_handler(
            "klippy:connect", self._handle_connect
        )

        # Klipper MenuElement.send_event('populate') routes through the menu
        # manager, producing "menu:<namespace>:populate". For
        # [menu __main __network], this is "menu:__main __network:populate".
        self.printer.register_event_handler(
            "menu:%s:populate" % self.menu_namespace,
            self._handle_menu_populate,
        )

        self.gcode.register_command(
            "NETWORK_STATUS_REFRESH",
            self.cmd_NETWORK_STATUS_REFRESH,
            desc="Refresh Moonraker-backed network status asynchronously",
        )

    def _handle_connect(self):
        updates = {}
        try:
            mcu = self.printer.lookup_object("mcu", None)
            if mcu is not None:
                updates["mcu_version"] = mcu.get_status().get(
                    "mcu_version", "N/A"
                )
        except Exception:
            logging.exception("network_status: unable to read main MCU version")

        try:
            extra_object_name = (
                "mcu " + self.extra_mcu_name
                if self.extra_mcu_name != "mcu"
                else "mcu"
            )
            extra = self.printer.lookup_object(extra_object_name, None)
            if extra is not None:
                updates["extra_mcu_version"] = extra.get_status().get(
                    "mcu_version", "N/A"
                )
        except Exception:
            logging.exception("network_status: unable to read extra MCU version")

        if updates:
            with self._lock:
                self._status.update(updates)

    def _handle_menu_populate(self, *args):
        self._start_refresh()

    def cmd_NETWORK_STATUS_REFRESH(self, gcmd):
        if self._start_refresh():
            gcmd.respond_info("Network status refresh started")
        else:
            gcmd.respond_info("Network status refresh already in progress")

    def _start_refresh(self):
        with self._lock:
            if self._refreshing:
                return False
            self._refreshing = True
            self._status["refreshing"] = True

        thread = threading.Thread(
            target=self._refresh_worker,
            name="klipper-network-status",
            daemon=True,
        )
        thread.start()
        return True

    def _http_get_json(self, path):
        url = self.moonraker_url + path
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["X-Api-Key"] = self.api_key
        request = urllib.request.Request(url, headers=headers, method="GET")
        with urllib.request.urlopen(
            request, timeout=self.request_timeout
        ) as response:
            raw = response.read()
        payload = json.loads(raw.decode("utf-8"))
        # Moonraker REST responses may be wrapped in {"result": ...}.
        if isinstance(payload, dict) and "result" in payload:
            payload = payload["result"]
        return payload

    @staticmethod
    def _ipv4_for_interface(interface):
        if not isinstance(interface, dict):
            return "N/A"
        addresses = interface.get("ip_addresses", [])
        # Prefer a normal non-link-local IPv4 address for the small LCD.
        for addr in addresses:
            if not isinstance(addr, dict):
                continue
            if (
                str(addr.get("family", "")).lower() == "ipv4"
                and not addr.get("is_link_local", False)
                and addr.get("address")
            ):
                return str(addr["address"])
        # Fall back to any IPv4 address if Moonraker only reports link-local.
        for addr in addresses:
            if not isinstance(addr, dict):
                continue
            if (
                str(addr.get("family", "")).lower() == "ipv4"
                and addr.get("address")
            ):
                return str(addr["address"])
        return "N/A"

    @staticmethod
    def _mac_for_interface(interface):
        if not isinstance(interface, dict):
            return "N/A"
        mac = interface.get("mac_address")
        return str(mac) if mac else "N/A"

    def _get_ssid(self):
        try:
            result = subprocess.run(
                ["iwgetid", self.wifi_interface, "-r"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=self.command_timeout,
                check=False,
            )
            if result.returncode == 0:
                ssid = result.stdout.strip()
                if ssid:
                    return ssid
        except (OSError, subprocess.SubprocessError):
            logging.exception("network_status: iwgetid failed")
        return "N/A"

    def _refresh_worker(self):
        try:
            system_payload = self._http_get_json("/machine/system_info")
            server_payload = self._http_get_json("/server/info")

            if not isinstance(system_payload, dict):
                raise ValueError("Unexpected /machine/system_info response")
            if not isinstance(server_payload, dict):
                raise ValueError("Unexpected /server/info response")

            system_info = system_payload.get("system_info", system_payload)
            network = system_info.get("network", {})
            if not isinstance(network, dict):
                network = {}

            eth = network.get(self.eth_interface, {})
            wifi = network.get(self.wifi_interface, {})

            ethip = self._ipv4_for_interface(eth)
            wifiip = self._ipv4_for_interface(wifi)
            ethmac = self._mac_for_interface(eth)
            wifimac = self._mac_for_interface(wifi)

            # Query SSID only if Moonraker sees an active Wi-Fi interface.
            wifissid = self._get_ssid() if wifi else "N/A"

            if ethip != "N/A":
                active_interface = self.eth_interface
                active_ip = ethip
            elif wifiip != "N/A":
                active_interface = self.wifi_interface
                active_ip = wifiip
            else:
                active_interface = "N/A"
                active_ip = "N/A"

            updates = {
                "moonraker_ok": True,
                "moonraker_state": str(
                    server_payload.get("klippy_state", "unknown")
                ),
                "moonraker_version": str(
                    server_payload.get("moonraker_version", "N/A")
                ),
                "ethip": ethip,
                "ethmac": ethmac,
                "wifiip": wifiip,
                "wifimac": wifimac,
                "wifissid": wifissid,
                "active_interface": active_interface,
                "active_ip": active_ip,
                "last_update": time.time(),
                "last_error": "",
            }
            with self._lock:
                self._status.update(updates)

            logging.info(
                "network_status: refreshed from Moonraker (%s=%s, %s=%s)",
                self.eth_interface,
                ethip,
                self.wifi_interface,
                wifiip,
            )

        except Exception as exc:
            # Keep last-known-good network values, but mark Moonraker stale.
            logging.warning("network_status: refresh failed: %s", exc)
            with self._lock:
                self._status["moonraker_ok"] = False
                self._status["last_error"] = str(exc)
        finally:
            with self._lock:
                self._refreshing = False
                self._status["refreshing"] = False

    def get_status(self, eventtime):
        # Critical real-time rule: this method is cache-only. It performs no
        # subprocess, HTTP, filesystem, or other potentially blocking I/O.
        with self._lock:
            return dict(self._status)


def load_config(config):
    return NetworkStatus(config)
