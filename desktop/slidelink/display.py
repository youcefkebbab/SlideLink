"""High-DPI support. Without this, Windows treats Python/Tk as DPI-unaware and
bitmap-stretches the whole window on scaled displays (125%-200%), which makes
slides and text look blurry no matter how well they were rendered."""
import sys


def enable_high_dpi() -> str:
    """Call ONCE, before the first tk.Tk(). Returns the mode that was applied."""
    if sys.platform != "win32":
        return "not-windows"
    import ctypes
    try:  # Per-Monitor V2: crisp on every monitor, including a projector with a different scale
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return "per-monitor-v2"
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return "per-monitor"
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
        return "system"
    except (AttributeError, OSError):
        return "none"


def dpi_scale(root) -> float:
    """1.0 at 96 DPI, 1.5 at 150 %, ... (used to size windows in physical pixels)."""
    try:
        return max(1.0, root.winfo_fpixels("1i") / 96.0)
    except Exception:
        return 1.0
