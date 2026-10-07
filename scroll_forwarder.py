#!/usr/bin/env python3
"""Forward mouse wheel events to X11 (XWayland) apps that miss them on Wayland.

Runs as a daemon: waits for a window whose WM_CLASS matches, forwards scroll
events while that window is focused, and keeps waiting if the window goes away
and comes back. Needs read access to /dev/input (see README), not root.
"""
import argparse
import errno
import logging
import os
import select
import signal
import sys
import time

import evdev
from evdev import InputDevice, ecodes
from Xlib import X, Xatom, display, error
from Xlib.ext import xtest

logger = logging.getLogger("scroll_forwarder")

SCROLL_CODES = (ecodes.REL_WHEEL, ecodes.REL_HWHEEL)
WINDOW_POLL_SECS = 2.0      # how often to look for the window while it is missing
WINDOW_CHECK_SECS = 2.0     # how often to verify a found window still exists
DEVICE_RESCAN_SECS = 5.0    # hotplug rescan interval


class ScrollForwarder:
    def __init__(self, target_classes, check_focus=True):
        self.target_classes = [c.lower() for c in target_classes]
        self.check_focus = check_focus
        self.display = None
        self.root = None
        self.target_window = None
        self.devices = {}  # fd -> InputDevice
        self.poller = select.poll()
        self.running = True
        self._net_active = None
        self._net_client_list = None

    # ---- X connection -------------------------------------------------

    def connect_display(self):
        """Connect to X, retrying so the daemon can start before the session is ready."""
        while self.running:
            try:
                self.display = display.Display()
                self.root = self.display.screen().root
                self._net_active = self.display.intern_atom("_NET_ACTIVE_WINDOW")
                self._net_client_list = self.display.intern_atom("_NET_CLIENT_LIST")
                return True
            except Exception as e:
                logger.warning("Cannot open X display (%s); retrying in 5s", e)
                time.sleep(5)
        return False

    # ---- window tracking ----------------------------------------------

    def matches(self, window):
        try:
            wm_class = window.get_wm_class()
        except error.XError:
            return False
        if not wm_class:
            return False
        return any(c.lower() in self.target_classes for c in wm_class)

    def find_window(self):
        """Look through the WM's client list, falling back to a tree walk."""
        try:
            prop = self.root.get_full_property(self._net_client_list, Xatom.WINDOW)
            if prop is not None and len(prop.value):
                for wid in prop.value:
                    window = self.display.create_resource_object("window", int(wid))
                    if self.matches(window):
                        return window
                return None
        except error.XError:
            pass
        return self._walk(self.root)

    def _walk(self, window):
        if self.matches(window):
            return window
        try:
            children = window.query_tree().children
        except error.XError:
            return None
        for child in children:
            found = self._walk(child)
            if found:
                return found
        return None

    def window_exists(self):
        try:
            self.target_window.get_geometry()
            return True
        except error.XError:
            return False

    def target_is_focused(self):
        """True if the target window (or a child of it) has focus."""
        if not self.check_focus:
            return True
        try:
            prop = self.root.get_full_property(self._net_active, Xatom.WINDOW)
            if prop is not None and len(prop.value) and int(prop.value[0]) == self.target_window.id:
                return True
            focus = self.display.get_input_focus().focus
            # Walk up from the focused window; clients often focus a child.
            for _ in range(8):
                if not hasattr(focus, "id"):
                    return False
                if focus.id == self.target_window.id:
                    return True
                focus = focus.query_tree().parent
                if focus.id == self.root.id:
                    return False
        except error.XError:
            pass
        return False

    # ---- input devices ------------------------------------------------

    def scan_devices(self):
        """Add any newly attached devices that can scroll."""
        denied = 0
        known = {d.path for d in self.devices.values()}
        for path in evdev.list_devices():
            if path in known:
                continue
            try:
                device = InputDevice(path)
            except PermissionError:
                denied += 1
                continue
            except OSError:
                continue
            rel = device.capabilities().get(ecodes.EV_REL, [])
            if not any(code in rel for code in SCROLL_CODES):
                device.close()
                continue
            self.devices[device.fd] = device
            self.poller.register(device.fd, select.POLLIN)
            logger.info("Monitoring %s (%s)", device.name, path)
        return denied

    def drop_device(self, fd, reason):
        device = self.devices.pop(fd, None)
        if device is None:
            return
        logger.info("Lost %s (%s)", device.name, reason)
        try:
            self.poller.unregister(fd)
        except (KeyError, ValueError):
            pass
        try:
            device.close()
        except OSError:
            pass

    # ---- forwarding ---------------------------------------------------

    def inject(self, code, value):
        if code == ecodes.REL_WHEEL:
            button = 4 if value > 0 else 5
        else:
            button = 6 if value < 0 else 7
        for _ in range(abs(value)):
            xtest.fake_input(self.display, X.ButtonPress, button)
            xtest.fake_input(self.display, X.ButtonRelease, button)

    def handle_device(self, fd, revents):
        device = self.devices.get(fd)
        if device is None:
            return
        if revents & (select.POLLHUP | select.POLLERR | select.POLLNVAL):
            self.drop_device(fd, "disconnected")
            return
        try:
            scrolls = [(e.code, e.value) for e in device.read()
                       if e.type == ecodes.EV_REL and e.code in SCROLL_CODES]
        except BlockingIOError:
            return
        except OSError as e:
            if e.errno == errno.ENODEV:
                self.drop_device(fd, "disconnected")
            return
        # Only ask X about focus when there is something to forward.
        if not scrolls or self.target_window is None or not self.target_is_focused():
            return
        try:
            for code, value in scrolls:
                self.inject(code, value)
            self.display.sync()
        except error.XError as e:
            logger.debug("X error while injecting: %s", e)

    # ---- main loop ----------------------------------------------------

    def stop(self, *_):
        self.running = False

    def run(self):
        if not self.connect_display():
            return
        if self.scan_devices() and not self.devices:
            logger.error("Permission denied reading /dev/input/event*. See README: "
                         "install the udev rule or join the 'input' group.")
            sys.exit(1)
        logger.info("Waiting for window class %s", self.target_classes)

        next_window = next_check = next_scan = 0.0
        try:
            while self.running:
                now = time.monotonic()
                # Sleep until input, or until the next housekeeping deadline.
                wake = min(t for t in (next_window if self.target_window is None else next_check,
                                       next_scan))
                timeout_ms = max(0, int((wake - now) * 1000))
                for fd, revents in self.poller.poll(timeout_ms):
                    self.handle_device(fd, revents)

                now = time.monotonic()
                if now >= next_scan:
                    next_scan = now + DEVICE_RESCAN_SECS
                    self.scan_devices()

                if self.target_window is None:
                    if now >= next_window:
                        next_window = now + WINDOW_POLL_SECS
                        self.target_window = self.find_window()
                        if self.target_window:
                            logger.info("Found window %s", hex(self.target_window.id))
                            next_check = now + WINDOW_CHECK_SECS
                elif now >= next_check:
                    next_check = now + WINDOW_CHECK_SECS
                    if not self.window_exists():
                        logger.info("Window closed; waiting for it to return")
                        self.target_window = None
                        next_window = now
        finally:
            for fd in list(self.devices):
                self.drop_device(fd, "shutdown")
            logger.info("Stopped")


def main():
    parser = argparse.ArgumentParser(
        description="Forward scroll wheel events to X11 apps running on Wayland.")
    parser.add_argument("window_class", nargs="+",
                        help="WM_CLASS of the app (find with: xprop WM_CLASS), e.g. GeForceNOW")
    parser.add_argument("--no-focus-check", action="store_true",
                        help="forward scrolls even when the window is not focused")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    args = parser.parse_args()

    logging.basicConfig(format="%(levelname)s: %(message)s",
                        level=logging.DEBUG if args.verbose else logging.INFO)

    forwarder = ScrollForwarder(args.window_class, check_focus=not args.no_focus_check)
    signal.signal(signal.SIGINT, forwarder.stop)
    signal.signal(signal.SIGTERM, forwarder.stop)
    forwarder.run()


if __name__ == "__main__":
    main()
