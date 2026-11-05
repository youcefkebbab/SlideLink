"""Presenter settings, saved next to paired.json."""
import json, os
from pathlib import Path

LASER_MIN, LASER_MAX, LASER_DEFAULT = 4, 60, 14   # px on a 1080-line-high screen


def clamp_laser(v) -> int:
    return max(LASER_MIN, min(LASER_MAX, int(round(float(v)))))


class Settings:
    def __init__(self, path=None):
        base = Path(os.environ.get("APPDATA") or Path.home() / ".config")
        self.path = Path(path) if path else base / "slidelink" / "settings.json"
        self.laser_enabled, self.laser_size, self.cache_mb = True, LASER_DEFAULT, 1024
        try:
            d = json.loads(self.path.read_text())
            self.laser_enabled = bool(d.get("laser_enabled", True))
            self.laser_size = clamp_laser(d.get("laser_size", LASER_DEFAULT))
            self.cache_mb = max(64, int(d.get("cache_mb", 1024)))
        except Exception:
            pass                      # first run / damaged file -> defaults

    def save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"laser_enabled": self.laser_enabled, "laser_size": self.laser_size,
                                       "cache_mb": self.cache_mb}))
            tmp.replace(self.path)    # atomic
        except OSError:
            pass                      # an unwritable profile must never break a presentation
