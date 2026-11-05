# SlideLink – Bluetooth presentation remote

**Developed by [youcefkebbab](https://github.com/youcefkebbab)**

Phone (Android / iPhone) → Bluetooth Low Energy → Computer (Windows 10/11, Ubuntu). No Wi-Fi, no Internet, no accounts.

## Use (2 minutes)
1. **Computer:** run the installer once – Windows: double-click `desktop/install_windows.bat`; Ubuntu: `bash desktop/install_ubuntu.sh`. (Internet is needed only for this one-time install.)
2. SlideLink Desktop opens and shows **“Ready”** plus a 6-digit code.
3. **Phone:** install the app, open it, tap your computer in the list.
4. First time only: type the code shown on the computer. After that it reconnects automatically.
5. On the computer click **Open PDF presentation** or **Open MP4 video (VLC)**. The phone switches to the matching remote by itself.

## Install the phone app
* **Android:** install the APK (`flutter build apk --release`, see `mobile/setup_platform_files.md`), allow “install unknown apps”, allow Bluetooth permission.
* **iPhone:** Apple does not allow APK-style installs. Build once on a Mac with Xcode (free Apple ID: app expires after 7 days – install the day before your talk; paid $99/yr account → TestFlight/App Store).


## iPhone without a Mac: browser remote (Wi-Fi / Hotspot, no app install)
Bluetooth from iPhone needs the native app (Mac + Xcode). As an alternative, SlideLink Desktop also runs a **browser remote**:
1. Join both devices to the same network – or turn on **Personal Hotspot** on the iPhone and connect the computer to it (works with no Internet).
2. On the computer, SlideLink Desktop shows an address like `http://172.20.10.2:8765`.
3. Open it in **Safari** on the iPhone, type the 6-digit code once. Tip: Share → *Add to Home Screen*.
4. Same PDF/video remote as the app. Keep Safari open and the screen on (the page requests this automatically on iOS 16.4+).
Notes: this uses Wi-Fi/hotspot, **not Bluetooth**; traffic is not encrypted but stays inside your private network. Windows may ask to allow SlideLink through the firewall the first time – choose *Private networks*. Hotspot/“client isolation” on some university Wi-Fi blocks device-to-device traffic – use your own hotspot there.

## What works (and what only works in the built-in PDF presenter)
| Feature | Built-in PDF presenter | Other viewers (PowerPoint, Okular, Evince, Adobe…) |
|---|---|---|
| Next / previous / first / last | ✅ | ✅ (sends arrow/Home/End keys) |
| Slide counter, go to page, progress | ✅ | ❌ not available |
| Start / exit / fullscreen | ✅ | ✅ (F5 / Esc / F11 – depends on app) |
| Black / white screen | ✅ | ⚠ uses B / W keys (PowerPoint, Okular presentation) |
| Laser pointer (drag on phone) + adjustable thickness | ✅ | ❌ |
| Timer | ✅ (on the phone, starts at first “Next”/“Start”; tap to reset) | ✅ |

Video (VLC 3.x): play/pause/stop, ±10 s, previous/next, volume ±10 %, mute, fullscreen, seek bar, time/duration, live sync. VLC is controlled through its HTTP interface on `127.0.0.1` only (never leaves the computer). The desktop app starts VLC for you with this enabled; a VLC you opened yourself is **not** controllable.

## PDF sharpness and the laser pointer (built-in presenter)
* **Sharp slides:** each page is rendered by MuPDF from the PDF's original vector content at the *exact pixel size of the window* (uncompressed, maximum anti-aliasing) – never by stretching a smaller image. The current page, the next 3 and the previous 1 are cached at full resolution (1 GB by default; `cache_mb` in `settings.json`). If a page is not ready yet, the previous sharp slide stays on screen (no blurry placeholder). Resizing, fullscreen and moving to another monitor re-render at the new exact size.
* **High-DPI (Windows):** SlideLink now declares itself DPI-aware. Without that, Windows stretches the whole Python/Tk window on 125–200 % displays, which blurs everything.
* **Laser thickness:** press **L** in the presenter, or click **Laser pointer settings…** in the main window, or use the **Laser** chip on the phone (slider, preview, value, Reset). Range 4–60, default 14, measured in pixels on a 1080-line screen and scaled with the screen height, so it looks the same on 1080p, 4K and projectors. Changes apply live and are saved in `%APPDATA%\slidelink\settings.json` (`~/.config/slidelink/` on Linux). The laser is an anti-aliased sprite with smoothed movement.
* Limits: PDFs only (no animations or embedded video), no password-protected PDFs; on Linux the window is drawn at the X11/Xwayland pixel size, so fractional scaling by the compositor can still soften it – use 100 %/200 % or Xorg.

## Security
Each connection uses X25519 key exchange + AES-256-GCM with replay protection. First pairing is authenticated with the 6-digit code (PBKDF2); the code expires after 5 min / 5 wrong tries / one use. Afterwards a random 256-bit secret is stored (phone: Keychain/Keystore; computer: `paired.json`, owner-only) and used for automatic reconnect. Limitation: a 6-digit code is only as strong as the minutes it is valid – pair at home, not on stage.

## Known limitations
* iPhone cannot use classic Bluetooth, so BLE with an app on both sides is the only option; the phone is *not* paired in the OS Bluetooth settings.
* Computer needs a Bluetooth adapter that supports BLE peripheral/advertising (most from the last ~6 years; some cheap USB dongles do not). The receiver shows an error if not.
* Windows 10 build 1703+ / Windows 11. Ubuntu 20.04+ (BlueZ 5.50+).
* Ubuntu Wayland blocks keystrokes to other apps → use “Ubuntu on Xorg” or the built-in presenter.
* Only one phone at a time. Range ≈ 5–10 m.

## Status of testing – read this
* ✅ Automated – including the browser remote over real HTTP (run `cd desktop && python -m pytest tests`): framing, handshake, pairing, wrong-PIN lockout, replay rejection, auto-reconnect secret, command routing, VLC HTTP commands/state, mode detection.
* ✅ Automated (`python -m pytest tests`, Tk tests need a display): exact-size rendering, raw output, anti-aliasing, cache/prefetch, stale-job dropping, laser sprite/thickness/smoothing/persistence, panel + slider + reset in a real Tk window, laser commands over BLE-controller and HTTP.
* ❌ **Not yet tested on real hardware:** Windows DPI awareness on a scaled screen/projector (written from the Windows API docs, only its fallback logic is unit-tested), the new laser slider in the Flutter app (not compiled) and in a real Safari/Chrome, the web page on a real iPhone/Safari, the actual BLE radio layer (bless on Windows/Ubuntu ↔ flutter_blue_plus on phones), the Flutter UI (not compiled in the build sandbox), the Tk presenter window, and the installers. Do the checklist in `docs/HARDWARE_TEST_CHECKLIST.md` before your presentation, and keep a USB/HDMI-keyboard fallback.
