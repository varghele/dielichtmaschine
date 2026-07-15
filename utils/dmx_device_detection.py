# utils/dmx_device_detection.py
# USB DMX device detection utility

import sys
from typing import List, Dict

from utils import user_warnings


def get_available_dmx_devices() -> List[Dict[str, str]]:
    """Detect available USB DMX devices.

    Returns:
        List of dicts with 'name' and 'port' keys for each detected device
    """
    devices = []

    try:
        import serial.tools.list_ports

        # Get all serial ports
        ports = serial.tools.list_ports.comports()

        # Filter for known DMX interfaces
        dmx_keywords = [
            'DMX', 'ENTTEC', 'FT232', 'FTDI', 'USB Serial',
            'CH340', 'CP210', 'Arduino', 'Prolific'
        ]

        for port in ports:
            # Check if port description contains DMX-related keywords
            description = port.description.upper()
            manufacturer = (port.manufacturer or '').upper()

            is_dmx_device = any(keyword.upper() in description or
                               keyword.upper() in manufacturer
                               for keyword in dmx_keywords)

            if is_dmx_device or port.vid is not None:  # Has vendor ID
                device_name = f"{port.description}"
                if port.manufacturer:
                    device_name = f"{port.manufacturer} - {port.description}"

                devices.append({
                    'name': device_name,
                    'port': port.device,
                    'description': port.description,
                    'hwid': port.hwid
                })

    except ImportError:
        # pyserial not installed, return empty list
        user_warnings.warn(
            "pyserial is not installed; USB DMX device detection is "
            "unavailable (pip install pyserial)",
            category="output", once_key="pyserial-missing")

    except Exception as e:
        user_warnings.warn(f"USB DMX device detection failed: {e}",
                           category="output", once_key="usb-detect")

    # Add a "None" option
    if not devices:
        devices.append({
            'name': 'No devices detected',
            'port': '',
            'description': 'No USB DMX devices found',
            'hwid': ''
        })

    return devices


def get_device_display_names() -> List[str]:
    """Get display names for USB DMX devices.

    Returns:
        List of human-readable device names
    """
    devices = get_available_dmx_devices()
    return [f"{dev['name']} ({dev['port']})" if dev['port'] else dev['name']
            for dev in devices]


def get_device_port_by_display_name(display_name: str) -> str:
    """Extract port from display name.

    Args:
        display_name: Display name like "FTDI USB Serial (COM3)"

    Returns:
        Port string like "COM3" or empty string
    """
    if '(' in display_name and ')' in display_name:
        start = display_name.rfind('(')
        end = display_name.rfind(')')
        return display_name[start+1:end]
    return ''
