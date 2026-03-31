# USB Ethernet Gadget (Werkstatt, Pi Zero 2W)

Use this when you want a **direct USB network** to a PC (e.g. Zorin laptop) **without** Wi-Fi or an extra USB–Ethernet dongle. The Pi appears as a USB network device.

This is **orthogonal** to `docs/HOTSPOT.md`. Switch runtime intent with:

```bash
cd ~/piB4ECU
sudo ./scripts/pib4ecu-net-mode.sh usb
```

If you enabled the boot auto-policy (`pib4ecu-net-mode-apply.service`), keep a maintenance lock during longer workshop sessions:

```bash
sudo ./scripts/pib4ecu-net-mode.sh lock
```

Then apply the boot configuration below and **reboot**.

## Prerequisites

- **Data-capable** micro-USB cable to the Pi’s **USB OTG** port (not power-only).
- You can still SSH over the new `usb0` interface once both ends have IP addresses.

## Raspberry Pi OS (Bookworm) — classic `g_ether`

1. **Firmware config** (paths may be `/boot/firmware/` on Bookworm):

   Append **one line** if missing:

   ```bash
   sudo nano /boot/firmware/config.txt
   ```

   Add:

   ```ini
   dtoverlay=dwc2
   ```

2. **Kernel command line** — append to the **existing single line** in `cmdline.txt` (do not add a second line):

   ```bash
   sudo nano /boot/firmware/cmdline.txt
   ```

   Append to the end of the line:

   ```text
   modules-load=dwc2,g_ether
   ```

3. **Optional: static IP on the Pi** (so you always know the address), e.g. in `dhcpcd.conf` or a small `systemd-networkd` snippet — only if you need a fixed `usb0` address. Many setups use link-local and mDNS (`raspberrypi.local`) once the link is up.

4. **Reboot** the Pi, plug USB into the PC, then on the PC check for a new interface (`usb0`, `enx…`) and configure routing if needed.

## Conflicts

- Do not run **hostapd** / **PassatECU hotspot** on the same boot profile if you want a clean gadget-only workshop setup. Use `pib4ecu-net-mode.sh usb` before enabling gadget modules.
- Wi-Fi and USB gadget can coexist on a Zero 2W, but for predictable workshop use, the `usb` mode script disables the usual client Wi-Fi stack.

## Recovery

If the Pi stops responding over USB, use **HDMI + keyboard** or edit the **boot partition** on another PC and remove the `modules-load=dwc2,g_ether` addition (or the `dtoverlay=dwc2` line) to return to a known-good boot.
