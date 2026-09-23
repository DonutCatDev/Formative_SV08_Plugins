# On-demand Moonraker updates for Klipper character LCDs.
# Copyright (C) 2026 Formative; GNU GPLv3.
import json
import threading
import urllib.request

from .display import menu as display_menu


def update_available(info):
    if not isinstance(info, dict):
        return False
    if info.get('configured_type') == 'system':
        return info.get('package_count', 0) > 0
    if not info.get('is_valid', False) or info.get('is_dirty') or info.get('corrupt'):
        return False
    if info.get('configured_type') == 'git_repo':
        current, remote = info.get('current_hash'), info.get('remote_hash')
    else:
        current, remote = info.get('version'), info.get('remote_version')
    return bool(current and remote and current != remote
                and remote not in ('?', 'unknown'))


class MenuUpdateConfirm(display_menu.MenuList):
    def __init__(self, manager, plugin, module):
        self.plugin, self.module = plugin, module
        super().__init__(manager, None, name=module)

    def _names_aslist(self):
        return []

    def _populate(self):
        super()._populate()
        def confirm(element, context):
            # Numeric selection IDs keep arbitrary module names out of G-code.
            token = self.plugin.remember(self.module)
            return 'LCD_UPDATE_MODULE TOKEN=%d' % token
        self.insert_item(self.manager.menuitem_from(
            'command', name='Update now?', gcode=confirm))
        self.insert_item(self.manager.menuitem_from(
            'command', name=self.module, gcode=lambda el, ctx: ''))


class MenuUpdateAllConfirm(display_menu.MenuList):
    def __init__(self, manager, plugin, modules):
        self.plugin, self.modules = plugin, tuple(modules)
        super().__init__(manager, None, name='Update all (%d)' % len(self.modules))

    def _names_aslist(self):
        return []

    def _populate(self):
        super()._populate()
        def confirm(element, context):
            token = self.plugin.remember(self.modules)
            return 'LCD_UPDATE_ALL TOKEN=%d' % token
        self.insert_item(self.manager.menuitem_from(
            'command', name='Update all now?', gcode=confirm))
        self.insert_item(self.manager.menuitem_from(
            'command', name='%d allowed updates' % len(self.modules),
            gcode=lambda el, ctx: ''))


class MenuUpdates(display_menu.MenuList):
    def __init__(self, manager, config, **kwargs):
        self.plugin = manager.printer.lookup_object('lcd_updates')
        self.revision = -1
        super().__init__(manager, config, **kwargs)

    def _names_aslist(self):
        return []

    def _populate(self):
        self.plugin.start_refresh()
        self._build()

    def _build(self):
        self._allitems = []
        super()._populate()
        status = self.plugin.get_status(0)
        self.revision = status['revision']
        self.insert_item(self.manager.menuitem_from(
            'command', name='Refresh',
            gcode=lambda el, ctx: 'LCD_UPDATES_REFRESH'))
        label = ('Working...' if status['busy'] else
                 'Status uncertain' if status['uncertain'] else
                 'Refresh failed' if status['error'] else
                 'No allowed updates' if not status['available_modules'] else '')
        if label:
            self.insert_item(self.manager.menuitem_from(
                'command', name=label, gcode=lambda el, ctx: ''))
        if not status['busy'] and not status['error'] and not status['uncertain']:
            if status['available_modules']:
                self.insert_item(MenuUpdateAllConfirm(
                    self.manager, self.plugin, status['available_modules']))
            for module in status['available_modules']:
                self.insert_item(MenuUpdateConfirm(self.manager, self.plugin, module))

    def draw_container(self, nrows, eventtime):
        # Rebuild only on a cache revision, on the Klipper reactor thread.
        if self.plugin.get_status(eventtime)['revision'] != self.revision:
            self._build()
            self.update_items()
            self.init_selection()
        super().draw_container(nrows, eventtime)


class LCDUpdates:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object('gcode')
        self.allowed = frozenset(config.getlist('allowed_modules', ()))
        self.url = config.get('moonraker_url', 'http://127.0.0.1:7125').rstrip('/')
        self.api_key = config.get('api_key', '')
        self.timeout = config.getfloat('request_timeout', 120., minval=1.)
        self.update_timeout = config.getfloat('update_timeout', 3600., minval=1.)
        self.lock = threading.Lock()
        self.status = dict(busy=False, uncertain=False, error='', revision=0,
                           modules={}, available_modules=[])
        self.tokens = {}
        self.next_token = 0
        display_menu.menu_items['lcd_updates'] = MenuUpdates
        self.gcode.register_command('LCD_UPDATES_REFRESH', self.cmd_refresh)
        self.gcode.register_command('LCD_UPDATE_MODULE', self.cmd_update)
        self.gcode.register_command('LCD_UPDATE_ALL', self.cmd_update_all)

    def _http(self, path, body=None, timeout=None):
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['X-Api-Key'] = self.api_key
        request = urllib.request.Request(
            self.url + path, headers=headers,
            data=None if body is None else json.dumps(body).encode())
        with urllib.request.urlopen(request, timeout=timeout or self.timeout) as response:
            payload = json.load(response)
        if not isinstance(payload, dict) or 'result' not in payload:
            raise ValueError('Unexpected Moonraker response')
        return payload['result']

    def _publish(self, **values):
        with self.lock:
            self.status.update(values)
            self.status['revision'] += 1

    def _read_status(self, payload):
        modules = payload['version_info']
        if not isinstance(modules, dict):
            raise ValueError('Invalid Moonraker module list')
        available = sorted(name for name, info in modules.items()
                           if name in self.allowed and update_available(info))
        self._publish(modules={name: {'allowed': name in self.allowed,
                                     'update_available': update_available(info)}
                               for name, info in modules.items()},
                      available_modules=available)
        return modules

    def _idle(self):
        now = self.printer.get_reactor().monotonic()
        stats = self.printer.lookup_object('print_stats', None)
        idle = self.printer.lookup_object('idle_timeout', None)
        sd = self.printer.lookup_object('virtual_sdcard', None)
        return (stats is not None and idle is not None
                and stats.get_status(now).get('state') not in ('printing', 'paused')
                and idle.get_status(now).get('state') in ('Ready', 'Idle')
                and not (sd and sd.is_active()))

    def _start(self, worker):
        with self.lock:
            if self.status['busy'] or self.status['uncertain']:
                return False
            self.status.update(busy=True, error='')
            self.status['revision'] += 1
        threading.Thread(target=worker, daemon=True).start()
        return True

    def start_refresh(self):
        return self._start(self._refresh_worker)

    def _refresh_worker(self):
        try:
            payload = self._http('/machine/update/status')
            if payload.get('busy'):
                raise ValueError('Moonraker update manager busy')
            modules = payload['version_info']
            # Discovery includes every updater; remote refresh touches only allowed ones.
            for name in sorted(self.allowed.intersection(modules)):
                self._http('/machine/update/refresh', {'name': name})
            self._read_status(self._http('/machine/update/status'))
        except Exception as exc:
            self._publish(error=str(exc), available_modules=[])
        finally:
            self._publish(busy=False)

    def remember(self, module):
        self.next_token += 1
        self.tokens[self.next_token] = module
        while len(self.tokens) > 256:
            del self.tokens[next(iter(self.tokens))]
        return self.next_token

    def cmd_refresh(self, gcmd):
        if not self.start_refresh():
            gcmd.respond_info('Updates busy or status uncertain; inspect Moonraker')

    def cmd_update(self, gcmd):
        module = self.tokens.pop(gcmd.get_int('TOKEN', minval=1), None)
        if not isinstance(module, str) or module not in self.allowed:
            raise gcmd.error('Update selection expired or module disallowed')
        if not self._idle():
            raise gcmd.error('LCD updates require a ready, unpaused printer')
        if not self._start(lambda: self._update_worker(module)):
            raise gcmd.error('Updates busy or status uncertain; inspect Moonraker')

    def cmd_update_all(self, gcmd):
        modules = self.tokens.pop(gcmd.get_int('TOKEN', minval=1), None)
        if (not isinstance(modules, tuple) or not modules
                or any(module not in self.allowed for module in modules)):
            raise gcmd.error('Update selection expired or module disallowed')
        if not self._idle():
            raise gcmd.error('LCD updates require a ready, unpaused printer')
        if not self._start(lambda: self._update_all_worker(modules)):
            raise gcmd.error('Updates busy or status uncertain; inspect Moonraker')

    def _update_worker(self, module):
        submitted = False
        try:
            payload = self._http('/machine/update/status')
            if payload.get('busy'):
                raise ValueError('Moonraker update manager busy')
            modules = self._read_status(payload)
            if module not in self.allowed or not update_available(modules.get(module)):
                raise ValueError('Module disallowed or no update available')
            # Recheck printer state through Moonraker in the worker immediately
            # before submission. Never access Klipper objects from this thread.
            state = self._http('/printer/objects/query?print_stats&idle_timeout&virtual_sdcard')['status']
            if (state['print_stats']['state'] in ('printing', 'paused')
                    or state['idle_timeout']['state'] not in ('Ready', 'Idle')
                    or state['virtual_sdcard'].get('is_active')):
                raise ValueError('Printer is not ready for updates')
            submitted = True
            self._http('/machine/update/upgrade', {'name': module}, self.update_timeout)
            self._read_status(self._http('/machine/update/status'))
        except Exception as exc:
            # A dropped connection may occur after Moonraker accepted the update.
            # Never automatically retry an uncertain update request.
            self._publish(error=str(exc), uncertain=submitted, available_modules=[])
        finally:
            self._publish(busy=False)

    def _update_all_worker(self, selected_modules):
        submitted = False
        try:
            payload = self._http('/machine/update/status')
            if payload.get('busy'):
                raise ValueError('Moonraker update manager busy')
            modules = self._read_status(payload)
            # Rebuild the batch from current status. A module must still be both
            # selected and allowed, and it must still have an update available.
            batch = tuple(name for name in selected_modules
                          if name in self.allowed
                          and update_available(modules.get(name)))
            if not batch:
                raise ValueError('No selected allowed updates remain available')
            state = self._http('/printer/objects/query?print_stats&idle_timeout&virtual_sdcard')['status']
            if (state['print_stats']['state'] in ('printing', 'paused')
                    or state['idle_timeout']['state'] not in ('Ready', 'Idle')
                    or state['virtual_sdcard'].get('is_active')):
                raise ValueError('Printer is not ready for updates')

            # Each allowed updater manages Klipper, so the first completed
            # upgrade may restart this process. Submit every explicit named
            # request concurrently; Moonraker serializes/queues the work.
            errors = []
            error_lock = threading.Lock()
            def submit(module):
                try:
                    self._http('/machine/update/upgrade', {'name': module},
                               self.update_timeout)
                except Exception as exc:
                    with error_lock:
                        errors.append('%s: %s' % (module, exc))
            submitted = True
            workers = [threading.Thread(target=submit, args=(module,), daemon=True)
                       for module in batch]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join()
            if errors:
                raise ValueError('; '.join(errors))
            self._read_status(self._http('/machine/update/status'))
        except Exception as exc:
            # As with a single update, any lost response after submission is
            # uncertain and must never cause an automatic retry.
            self._publish(error=str(exc), uncertain=submitted,
                          available_modules=[])
        finally:
            self._publish(busy=False)

    def get_status(self, eventtime):
        with self.lock:
            result = dict(self.status)
            result['modules'] = {k: dict(v) for k, v in self.status['modules'].items()}
            result['available_modules'] = list(self.status['available_modules'])
            return result


def load_config(config):
    return LCDUpdates(config)
