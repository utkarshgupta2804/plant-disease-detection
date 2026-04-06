# =============================================================================
# camera_capture.py — Pi Camera v2 Image Capture (picamera2)
#
# Wiring:
#   Pi Camera v2 ribbon → RPi CSI port (physical CSI-2 ribbon connector)
#   Enable with: sudo raspi-config → Interface Options → Camera → Enable
#   OR add "camera=1" to /boot/config.txt
#
# Install: sudo apt install python3-picamera2  (do NOT pip install)
# =============================================================================

import time
from pathlib import Path
from picamera2 import Picamera2
from libcamera import controls

from config import CAMERA_RESOLUTION, CAMERA_CAPTURE_PATH

_camera = None


def _get_camera() -> Picamera2:
    global _camera
    if _camera is None:
        cam = Picamera2()
        config = cam.create_still_configuration(
            main={
                "size":   CAMERA_RESOLUTION,
                "format": "RGB888",
            },
            controls={"AfMode": controls.AfModeEnum.Continuous},
        )
        cam.configure(config)
        cam.start()
        time.sleep(2)   # warm-up / auto-exposure settle
        _camera = cam
    return _camera


def capture_image(save_path: str = CAMERA_CAPTURE_PATH) -> str:
    """
    Capture a still image and save as JPEG.
    Returns the absolute path to the saved file.
    """
    cam = _get_camera()
    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
    cam.capture_file(save_path)
    return save_path


def cleanup():
    global _camera
    if _camera:
        try:
            _camera.stop()
            _camera.close()
        except Exception:
            pass
        _camera = None


# --- Quick self-test ---
if __name__ == "__main__":
    try:
        path = capture_image()
        print(f"Image saved to: {path}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        cleanup()
