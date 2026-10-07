# wayland-scroll-forwarder

This script fixes scroll wheel when using apps designed for X11 on Wayland.

It is designed for **NVIDIA GeForce NOW** (the Linux Flatpak client, window class `GeForceNOW`), where the mouse wheel does not work on Wayland. It works the same way for any other X11/XWayland app: pass that app's `WM_CLASS` instead.

Developed and tested on **CachyOS (Arch Linux)** with KDE Plasma on Wayland. Other distributions and desktops should work but are untested.

> **Independent fork.** This is a separate, maintained-by-me version of [enexam/wayland-scroll-forwarder](https://github.com/enexam/wayland-scroll-forwarder), which provided the original idea and code (GPL-3.0). The rewrite, install script and AUR package here are my own changes. The original author doesn't support or maintain them, so please report issues here, not upstream.

## Installation

### Dependencies

Install dependencies `libXtst`, `python-evdev`, `python-xlib`

Ubuntu / Debian (apt):

```bash
sudo apt install python3-evdev python3-xlib libxtst6
```

Arch / EndeavourOS (pacman):

```bash
sudo pacman -S python-evdev python-xlib libxtst
```

Fedora (dnf):

```bash
sudo dnf install python3-evdev python3-xlib libXtst
```

### Wayland Scroll Forwarder

Install `wayland_scroll_forwarder`

```bash
sudo curl -sL https://raw.githubusercontent.com/Throdne/wayland-scroll-forwarder/main/scroll_forwarder.py -o /usr/local/bin/wayland_scroll_forwarder && sudo chmod +x /usr/local/bin/wayland_scroll_forwarder
```

### First use

Start the X11 app. Example: GeForce Now

```bash
flatpak run com.nvidia.geforcenow
```

DO NOT LAUNCH A GAME (or the subprocess needing the fix) YET.

Get the window class name. In another terminal:

```bash
xprop WM_CLASS
```

Then click inside the app window. It returns the window class (last string).

```bash
WM_CLASS(STRING) = "GeForceNOW", "GeForceNOW"
```

Start the python script in sudo with the window class.

```bash
sudo wayland_scroll_forwarder GeForceNOW
```

The scroll forwarder will stop when closing your app (such as GFN).
You can also press CTRL+C in the terminal running the scroll forwarder to stop it.

### Arch Linux (AUR)

Available on the AUR as [`wayland-scroll-forwarder-git`](https://aur.archlinux.org/packages/wayland-scroll-forwarder-git):

```bash
yay -S wayland-scroll-forwarder-git      # or paru -S, or any AUR helper
systemctl --user enable --now wayland-scroll-forwarder@GeForceNOW
```

The service name after `@` is the app's `WM_CLASS`.

### Quick install (other distributions)

One line, straight from the repo (replace `GeForceNOW` with your app's WM_CLASS):

```bash
d=$(mktemp -d) && git clone -q --depth 1 https://github.com/Throdne/wayland-scroll-forwarder.git "$d" && "$d/install.sh" GeForceNOW
```

`install.sh` installs the script to `~/.local/bin`, writes a systemd user service for your app, and starts it. From a local clone:

```bash
./install.sh GeForceNOW          # or any WM_CLASS; several can be listed
./install.sh --udev GeForceNOW   # also install the udev rule (mouse access without sudo)
./install.sh --uninstall         # remove everything
```

The sections below describe the same steps manually.

### Run without sudo

The script only needs to read mouse devices. Either install the udev rule (mice only):

```bash
sudo cp contrib/99-scroll-forwarder.rules /etc/udev/rules.d/
sudo udevadm control --reload && sudo udevadm trigger --subsystem-match=input
```

or add yourself to the `input` group (also exposes keyboards; log out and in afterwards).
Then run `wayland_scroll_forwarder GeForceNOW` as a normal user.

### Run automatically as a daemon

The forwarder waits for the window, forwards scrolls only while it is focused, and keeps
waiting if the window closes and reopens, so it can simply stay running.

```bash
mkdir -p ~/.local/bin ~/.config/systemd/user
cp scroll_forwarder.py ~/.local/bin/wayland_scroll_forwarder && chmod +x ~/.local/bin/wayland_scroll_forwarder
cp contrib/wayland-scroll-forwarder.service ~/.config/systemd/user/
systemctl --user enable --now wayland-scroll-forwarder
journalctl --user -u wayland-scroll-forwarder -f   # logs
```

Options: several window classes can be given, `--no-focus-check` forwards even when the
window is unfocused, `-v` enables debug logging.

## Multiplayer

Not tested against anti-cheat softwares. USE AT YOUR OWN RISK.

## Troubleshooting

Please [report issues](https://github.com/Throdne/wayland-scroll-forwarder/issues/new) you are facing.

### Common issues

Well... I don't know yet.
