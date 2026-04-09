#!/usr/bin/env python3
# =============================================================================
# find_usb_devices.py — Print VID:PID for all USB serial devices
# Team OJAS · NIT Hamirpur
#
# Run this WITH both LilyGo and NodeMCU plugged in:
#   python3 find_usb_devices.py
#
# Copy the VID:PID values into 99-ojas-devices.rules
# =============================================================================

import subprocess
import serial.tools.list_ports

print("=" * 60)
print("USB Serial Devices detected:")
print("=" * 60)

ports = list(serial.tools.list_ports.comports())
if not ports:
    print("  No USB serial devices found.")
else:
    for p in sorted(ports, key=lambda x: x.device):
        vid = f"{p.vid:04X}" if p.vid else "????"
        pid = f"{p.pid:04X}" if p.pid else "????"
        print(f"  {p.device:<16} VID={vid}  PID={pid}  → {p.description}")
        print(f"              Manufacturer: {p.manufacturer or 'unknown'}")
        print(f"              Serial#     : {p.serial_number or 'none'}")
        print()

print("=" * 60)
print("Update 99-ojas-devices.rules with the VID/PID above.")
print("LilyGo  → SYMLINK+=\"lilygo\"")
print("NodeMCU → SYMLINK+=\"nodemcu\"")
print("=" * 60)
