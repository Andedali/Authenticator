"""
Authenticator — 2FA TOTP Authenticator App
Built with KivyMD for beautiful Material Design UI.
Can be compiled to APK via Buildozer.
"""

import os
import json
import time
import struct
import socket
import threading
import tempfile
import urllib.parse
import numpy as np
import pyotp
from kivy.core.clipboard import Clipboard
from pathlib import Path

# Disable multitouch emulation (red dots on right/middle click) — desktop only
from kivy.config import Config
from kivy.utils import platform as _plat
if _plat not in ('android', 'ios'):
    Config.set('input', 'mouse', 'mouse,multitouch_on_demand')

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.properties import StringProperty, NumericProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.lang import Builder

from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton, MDIconButton, MDFillRoundFlatIconButton
from kivymd.uix.card import MDCard
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.list import MDList
from kivymd.uix.screen import MDScreen
from kivymd.uix.screenmanager import MDScreenManager
from kivymd.uix.scrollview import MDScrollView
from kivymd.uix.textfield import MDTextField
from kivymd.uix.toolbar import MDTopAppBar
from kivymd.uix.progressbar import MDProgressBar
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.camera import Camera
from kivy.animation import Animation
from kivy.graphics import PushMatrix, PopMatrix, Rotate

# ── Window size for desktop testing (ignored on mobile) ──────────────
from kivy.utils import platform
if platform not in ("android", "ios"):
    Window.size = (400, 720)

# ── Locale: Russian if system is Russian, else English ───────────────
_IS_RUSSIAN_CACHED = None

def _is_russian():
    """Check if system locale is Russian. Cached after first call."""
    global _IS_RUSSIAN_CACHED
    if _IS_RUSSIAN_CACHED is not None:
        return _IS_RUSSIAN_CACHED
    
    # Check Android first (most reliable)
    if platform == "android":
        try:
            from jnius import autoclass
            Locale = autoclass("java.util.Locale")
            lang = Locale.getDefault().getLanguage() or "en"
            _IS_RUSSIAN_CACHED = lang == "ru"
            return _IS_RUSSIAN_CACHED
        except Exception:
            pass
    
    # Fallback to locale module
    try:
        import locale
        loc = (locale.getlocale() or ("en",))[0] or (locale.getdefaultlocale() or ("en",))[0] or "en"
        if loc:
            _IS_RUSSIAN_CACHED = loc.split("_")[0].lower() == "ru"
            return _IS_RUSSIAN_CACHED
    except Exception:
        pass
    
    _IS_RUSSIAN_CACHED = False
    return False


def t(en: str, ru: str) -> str:
    """Return Russian string if system locale is Russian, else English."""
    return ru if _is_russian() else en

# ── White background image for bubble menu ──
from PIL import Image as _PILImage

# ── QR scan dependencies (pyzbar or opencv fallback) ──
def _decode_qr_from_path(path):
    """Decode QR from image path with preprocessing."""
    try:
        import cv2

        img = cv2.imread(path)
        if img is None:
            return None

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Increase contrast
        gray = cv2.equalizeHist(gray)

        detector = cv2.QRCodeDetector()
        data, _, _ = detector.detectAndDecode(gray)

        if data:
            return data

    except Exception:
        pass

    try:
        from pyzbar import pyzbar
        img = _PILImage.open(path).convert("RGB")
        decoded = pyzbar.decode(img)
        if decoded:
            return decoded[0].data.decode("utf-8", errors="ignore")
    except Exception:
        pass

    return None


def _decode_qr_from_frame(frame_bgr):
    """Decode QR from numpy array (BGR)."""
    try:
        import cv2
        detector = cv2.QRCodeDetector()
        data, _, _ = detector.detectAndDecode(frame_bgr)
        if data:
            return data
    except Exception:
        pass

    try:
        import cv2
        from pyzbar import pyzbar
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        img = _PILImage.fromarray(frame_rgb)
        decoded = pyzbar.decode(img)
        if decoded:
            return decoded[0].data.decode("utf-8", errors="ignore")
    except Exception:
        pass

    return None


def _take_picture_android(on_complete):
    """
    Launch Android camera. On API 29+ uses MediaStore to get content URI and EXTRA_OUTPUT
    so the camera writes to our URI; on older or fallback reads getData() or thumbnail bitmap.
    """
    try:
        import android.activity
        from jnius import autoclass

        Intent = autoclass("android.content.Intent")
        MediaStore = autoclass("android.provider.MediaStore")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Build = autoclass("android.os.Build")
        Bitmap = autoclass("android.graphics.Bitmap")
        ContentValues = autoclass("android.content.ContentValues")
        Activity = autoclass("android.app.Activity")

        context = PythonActivity.mActivity
        resolver = context.getContentResolver()
        REQUEST_IMAGE = 0x124
        intent = Intent(MediaStore.ACTION_IMAGE_CAPTURE)

        output_uri = None
        if Build.VERSION.SDK_INT >= 29:
            try:
                values = ContentValues()
                values.put(MediaStore.MediaColumns.DISPLAY_NAME, "qr_capture_" + str(int(time.time())) + ".jpg")
                values.put(MediaStore.MediaColumns.MIME_TYPE, "image/jpeg")
                try:
                    MediaColumns = autoclass("android.provider.MediaStore$MediaColumns")
                    values.put(MediaColumns.RELATIVE_PATH, "Pictures/Authenticator")
                except Exception:
                    try:
                        values.put(MediaStore.MediaColumns.RELATIVE_PATH, "Pictures/Authenticator")
                    except Exception:
                        values.put("relative_path", "Pictures/Authenticator")
                output_uri = resolver.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values)
                if output_uri is not None:
                    intent.putExtra(MediaStore.EXTRA_OUTPUT, output_uri)
                    intent.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION)
                    intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            except Exception:
                output_uri = None

        def read_uri_to_temp(uri):
            path = None
            try:
                inp = resolver.openInputStream(uri)
                fd, path = tempfile.mkstemp(suffix=".jpg")
                try:
                    with os.fdopen(fd, "wb") as f:
                        buf = inp.read()
                        if buf:
                            f.write(buf if isinstance(buf, bytes) else bytes(list(buf)))
                finally:
                    try:
                        inp.close()
                    except Exception:
                        pass
            except Exception:
                pass
            return path

        def on_result(request_code, result_code, intent_obj):
            if request_code != REQUEST_IMAGE:
                return
            android.activity.unbind(on_activity_result=on_result)
            result_ok = getattr(Activity, "RESULT_OK", -1)
            is_ok = result_code == result_ok or result_code == -1
            path = None
            try:
                if output_uri is not None and is_ok:
                    path = read_uri_to_temp(output_uri)
                    if path:
                        try:
                            resolver.delete(output_uri, None, None)
                        except Exception:
                            pass
                if path is None and intent_obj is not None:
                    uri = intent_obj.getData()
                    if uri is not None:
                        path = read_uri_to_temp(uri)
                if path is None and intent_obj is not None:
                    bitmap = None
                    try:
                        if Build.VERSION.SDK_INT >= 33:
                            bitmap = intent_obj.getParcelableExtra("data", Bitmap)
                        else:
                            bitmap = intent_obj.getParcelableExtra("data")
                    except Exception:
                        pass
                    if bitmap is None:
                        extras = intent_obj.getExtras()
                        if extras is not None:
                            bitmap = extras.get("data")
                    if bitmap is not None:
                        fd, path = tempfile.mkstemp(suffix=".jpg")
                        try:
                            out = os.fdopen(fd, "wb")
                            ByteArrayOutputStream = autoclass("java.io.ByteArrayOutputStream")
                            bos = ByteArrayOutputStream()
                            JPEG = autoclass("android.graphics.Bitmap$CompressFormat").JPEG
                            bitmap.compress(JPEG, 95, bos)
                            arr = bos.toByteArray()
                            out.write(arr if isinstance(arr, bytes) else bytes(list(arr)))
                            out.close()
                        except Exception:
                            try:
                                os.close(fd)
                            except Exception:
                                pass
                            try:
                                os.remove(path)
                            except Exception:
                                pass
                            path = None
                Clock.schedule_once(lambda dt: on_complete(path), 0)
            except Exception as e:
                Clock.schedule_once(lambda dt: on_complete(None), 0)

        android.activity.bind(on_activity_result=on_result)
        PythonActivity.mActivity.startActivityForResult(intent, REQUEST_IMAGE)
    except Exception:
        Clock.schedule_once(lambda dt: on_complete(None), 0)


def _get_android_display_rotation():
    """
    Get display rotation on Android (0, 90, 180, 270).
    Surface.ROTATION_0=0, ROTATION_90=1, ROTATION_180=2, ROTATION_270=3.
    Returns degrees for preview rotation.
    """
    if platform != "android":
        return 0
    try:
        from jnius import autoclass
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Context = autoclass("android.content.Context")
        ctx = PythonActivity.mActivity
        wm = ctx.getSystemService(Context.WINDOW_SERVICE)
        display = wm.getDefaultDisplay()
        rotation = display.getRotation()
        return {0: 90, 1: 0, 2: -90, 3: 180}.get(rotation, 0)
    except Exception:
        return 0


def _has_qr_decoder():
    """Check if QR decoder is available. On Android we allow scan anyway (decode tried on photo)."""
    if platform == "android":
        return True  # opencv is in build; decode will be tried when photo is taken
    try:
        from pyzbar import pyzbar
        return True
    except ImportError:
        pass
    try:
        import cv2
        _ = cv2.QRCodeDetector()
        return True
    except Exception:
        pass
    return False
_white_bg = os.path.join(tempfile.gettempdir(), '_kivy_white_bg.png').replace('\\', '/')
if not os.path.exists(_white_bg):
    _PILImage.new('RGBA', (4, 4), (247, 247, 247, 255)).save(_white_bg)

# ── Override bubble menu style via KV (no Python monkey-patching) ─────
_cut = t("Cut", "Вырезать")
_copy = t("Copy", "Копировать")
_paste = t("Paste", "Вставить")
_selectall = t("Select all", "Выбрать всё")
from kivy.lang import Builder
Builder.load_string(f'''
<-TextInputCutCopyPaste>:
    content: content.__self__
    but_cut: cut.__self__
    but_copy: copy.__self__
    but_paste: paste.__self__
    but_selectall: selectall.__self__
    size_hint: None, None
    size: '250sp', '50sp'
    background_image: '{_white_bg}'
    background_color: 1, 1, 1, 1
    arrow_image: '{_white_bg}'
    BubbleContent:
        id: content
        background_image: '{_white_bg}'
        background_color: 1, 1, 1, 1
        BubbleButton:
            id: cut
            text: '{_cut}'
            on_release: root.do('cut')
            background_normal: ''
            background_down: ''
            background_color: 0.97, 0.97, 0.97, 1
            color: 0.1, 0.1, 0.1, 1
        BubbleButton:
            id: copy
            text: '{_copy}'
            on_release: root.do('copy')
            background_normal: ''
            background_down: ''
            background_color: 0.97, 0.97, 0.97, 1
            color: 0.1, 0.1, 0.1, 1
        BubbleButton:
            id: paste
            text: '{_paste}'
            on_release: root.do('paste')
            background_normal: ''
            background_down: ''
            background_color: 0.97, 0.97, 0.97, 1
            color: 0.1, 0.1, 0.1, 1
        BubbleButton:
            id: selectall
            text: '{_selectall}'
            on_release: root.do('selectall')
            background_normal: ''
            background_down: ''
            background_color: 0.97, 0.97, 0.97, 1
            color: 0.1, 0.1, 0.1, 1
''')

# ── Position bubble above the text field (safe: only moves the widget) ──
from kivy.uix.textinput import TextInput
_orig_show_ccp = TextInput._show_cut_copy_paste

def _positioned_show_ccp(self, pos, win, parent_changed=False, mode='',
                         pos_in_window=False, *l):
    _orig_show_ccp(self, pos, win, parent_changed, mode, pos_in_window, *l)
    bubble = self._bubble
    if bubble is None or parent_changed:
        return
    t_pos = self.to_window(pos[0], pos[1]) if not pos_in_window else pos
    bw = bubble.size[0]
    bx = t_pos[0] - bw / 2
    bx = max(dp(4), min(bx, win.width - bw - dp(4)))
    field_top_y = self.to_window(0, self.top)[1]
    by = field_top_y + dp(8)
    if by + bubble.height > win.height:
        field_bottom_y = self.to_window(0, self.y)[1]
        by = field_bottom_y - bubble.height - dp(8)
    bubble_pos = self.to_widget(bx, by, relative=True)
    bubble.center_x = bubble_pos[0] + bw / 2
    bubble.y = bubble_pos[1]
    bubble.arrow_pos = 'bottom_mid'

TextInput._show_cut_copy_paste = _positioned_show_ccp


def toast(text, duration=2.5):
    """Custom toast with text wrapping support. Fade in/out, no slide."""
    from kivy.uix.boxlayout import BoxLayout as _BL
    from kivy.graphics import Color, RoundedRectangle

    # Pre-calculate size using a temporary label
    label = Label(
        text=text,
        font_size=dp(14),
        color=(1, 1, 1, 1),
        halign="center",
        valign="middle",
        size_hint=(None, None),
        padding=(dp(20), dp(12)),
    )
    label.text_size = (min(dp(350), Window.width - dp(60)), None)
    label.texture_update()
    w = min(label.texture_size[0] + dp(40), Window.width - dp(40))
    h = label.texture_size[1] + dp(24)
    label.size = (w, h)

    container = _BL(padding=0, size_hint=(None, None), size=(w, h))
    with container.canvas.before:
        Color(0.2, 0.2, 0.2, 0.92)
        bg = RoundedRectangle(pos=container.pos, size=container.size, radius=[dp(8)])
    container.bind(pos=lambda *a: setattr(bg, 'pos', container.pos))
    container.bind(size=lambda *a: setattr(bg, 'size', container.size))
    container.add_widget(label)

    # Use ModalView with NO open/close animation
    view = ModalView(
        size_hint=(None, None),
        size=(w, h),
        background_color=(0, 0, 0, 0),
        overlay_color=(0, 0, 0, 0),
        auto_dismiss=True,
        pos_hint={"center_x": 0.5, "y": 0.05},
    )
    view.add_widget(container)

    # Disable default ModalView slide animation
    view.opacity = 0
    view.open(animation=False)

    # Fade in
    anim_in = Animation(opacity=1, duration=0.2)
    anim_in.start(view)

    # Schedule fade out + dismiss
    def _fade_out(dt):
        anim_out = Animation(opacity=0, duration=0.3)
        anim_out.bind(on_complete=lambda *a: view.dismiss(animation=False))
        anim_out.start(view)

    Clock.schedule_once(_fade_out, duration)

# ── Data file path ───────────────────────────────────────────────────
# Will be set properly in AuthenticatorApp.build() for Android support
_data_file = None


def _get_data_file():
    """Get the data file path, with Android-safe fallback."""
    global _data_file
    if _data_file is not None:
        return _data_file
    # Fallback for desktop
    _data_file = Path(os.path.dirname(os.path.abspath(__file__))) / "services.json"
    return _data_file


def set_data_dir(directory):
    """Set data directory (called from App.build with user_data_dir on Android)."""
    global _data_file
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    _data_file = d / "services.json"


def load_services():
    """Load services list from JSON file."""
    data_file = _get_data_file()
    if data_file.exists():
        try:
            with open(data_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
    return []


def save_services(services):
    """Save services list to JSON file."""
    data_file = _get_data_file()
    try:
        data_file.parent.mkdir(parents=True, exist_ok=True)
        with open(data_file, "w", encoding="utf-8") as f:
            json.dump(services, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Authenticator] Error saving services: {e}")


def check_ntp_offset(callback, timeout=5):
    """
    Check system clock offset against NTP server in a background thread.
    Calls callback(offset_seconds) on completion, or callback(None) on failure.
    Uses raw NTP packet (no external dependencies).
    """
    def _worker():
        NTP_SERVERS = [
            "pool.ntp.org",
            "time.google.com",
            "time.windows.com",
            "time.cloudflare.com",
        ]
        NTP_EPOCH = 2208988800  # seconds between 1900-01-01 and 1970-01-01

        for server in NTP_SERVERS:
            try:
                # Build NTP request packet (48 bytes, version 3, client mode)
                packet = b'\x1b' + 47 * b'\0'

                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.settimeout(timeout)
                sock.sendto(packet, (server, 123))

                local_send = time.time()
                data, _ = sock.recvfrom(1024)
                local_recv = time.time()
                sock.close()

                if len(data) < 48:
                    continue

                # Extract transmit timestamp (bytes 40-47)
                ntp_time = struct.unpack('!I', data[40:44])[0] - NTP_EPOCH
                ntp_fraction = struct.unpack('!I', data[44:48])[0] / (2**32)
                ntp_timestamp = ntp_time + ntp_fraction

                # Calculate offset (simplified: assume symmetric delay)
                local_mid = (local_send + local_recv) / 2
                offset = ntp_timestamp - local_mid

                callback(offset)
                return
            except (socket.error, OSError, struct.error):
                continue

        callback(None)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()


# ── KV Language UI definition ────────────────────────────────────────
# KV will be built in build() after Android initialization with proper translations


class ServiceCard(MDCard):
    """Card widget displaying a single 2FA service with live TOTP code."""

    title = StringProperty("")
    account = StringProperty("")
    totp_code = StringProperty("------")
    timer_progress = NumericProperty(100)
    timer_seconds = NumericProperty(30)
    service_index = NumericProperty(0)

    def __init__(self, service_data: dict, index: int, **kwargs):
        super().__init__(**kwargs)
        self.service_data = service_data
        self.service_index = index
        self.title = service_data.get("title", "Unknown")
        self.account = service_data.get("account", "")
        self.secret = service_data.get("secret", "")
        self._update_code()

    def _update_code(self, *_args):
        """Generate current TOTP code and update timer."""
        try:
            secret_clean = self.secret.replace(" ", "").upper()
            totp = pyotp.TOTP(secret_clean)
            code = totp.now()
            # Format code as "XXX XXX" for readability
            self.totp_code = f"{code[:3]} {code[3:]}"

            # Timer: seconds remaining in current 30s window
            now = time.time()
            elapsed = now % 30
            remaining = 30 - elapsed
            self.timer_seconds = remaining
            self.timer_progress = (remaining / 30) * 100
        except Exception:
            self.totp_code = "ERR KEY"
            self.timer_progress = 0
            self.timer_seconds = 0

    def copy_code(self):
        """Copy current TOTP code to clipboard."""
        try:
            code = self.totp_code.replace(" ", "")
            Clipboard.copy(code)
            toast(t("Code copied", "Код скопирован") + f": {self.totp_code}")
        except Exception:
            pass

    def edit_service(self):
        """Navigate to edit screen for this service."""
        app = MDApp.get_running_app()
        app.open_edit_screen(self.service_index)

    def confirm_delete(self):
        """Show confirmation dialog before deleting."""
        app = MDApp.get_running_app()
        self._delete_dialog = MDDialog(
            title=t("Delete Service", "Удалить сервис"),
            text=t('Delete "{0}"? This cannot be undone.', 'Удалить "{0}"? Это нельзя отменить.').format(self.title),
            buttons=[
                MDFlatButton(
                    text=t("CANCEL", "ОТМЕНА"),
                    theme_text_color="Custom",
                    text_color=app.theme_cls.primary_color,
                    on_release=lambda x: self._delete_dialog.dismiss(),
                ),
                MDRaisedButton(
                    text=t("DELETE", "УДАЛИТЬ"),
                    md_bg_color=[0.9, 0.3, 0.3, 1],
                    on_release=lambda x: self._do_delete(),
                ),
            ],
        )
        self._delete_dialog.open()

    def _do_delete(self):
        """Delete this service."""
        self._delete_dialog.dismiss()
        app = MDApp.get_running_app()
        app.delete_service(self.service_index)


class MainScreen(MDScreen):
    """Main screen showing list of 2FA services."""

    def open_add_screen(self):
        app = MDApp.get_running_app()
        app.open_add_screen()


class AddEditScreen(MDScreen):
    """Screen for adding or editing a service."""

    editing_index = NumericProperty(-1)  # -1 = adding new

    def on_enter(self):
        """Populate fields if editing existing service."""
        if self.editing_index >= 0:
            app = MDApp.get_running_app()
            service = app.services[self.editing_index]
            self.ids.toolbar.title = t("Edit Service", "Редактировать сервис")
            self.ids.field_title.text = service.get("title", "")
            self.ids.field_url.text = service.get("url", "")
            self.ids.field_secret.text = service.get("secret", "")
            self.ids.field_account.text = service.get("account", "")
            self.ids.field_backup.text = service.get("backup_codes", "")
            self.ids.save_btn.text = t("UPDATE", "ОБНОВИТЬ")
        else:
            self.ids.toolbar.title = t("Add Service", "Добавить сервис")
            self.ids.field_title.text = ""
            self.ids.field_url.text = ""
            self.ids.field_secret.text = ""
            self.ids.field_account.text = ""
            self.ids.field_backup.text = ""
            self.ids.save_btn.text = t("SAVE", "СОХРАНИТЬ")

    def save_service(self):
        """Validate and save the service."""
        title = self.ids.field_title.text.strip()
        secret = self.ids.field_secret.text.strip()

        if not title:
            self.ids.field_title.error = True
            self.ids.field_title.helper_text = t("Name is required", "Название обязательно")
            self.ids.field_title.helper_text_mode = "on_error"
            return

        if not secret:
            self.ids.field_secret.error = True
            self.ids.field_secret.helper_text = t("Secret key is required", "Секретный ключ обязательно")
            self.ids.field_secret.helper_text_mode = "on_error"
            return

        # Validate secret key
        try:
            secret_clean = secret.replace(" ", "").upper()
            pyotp.TOTP(secret_clean).now()
        except Exception:
            self.ids.field_secret.error = True
            self.ids.field_secret.helper_text = t("Invalid Base32 secret key", "Неверный Base32 секретный ключ")
            self.ids.field_secret.helper_text_mode = "on_error"
            return

        service_data = {
            "title": title,
            "url": self.ids.field_url.text.strip(),
            "secret": secret.replace(" ", "").upper(),
            "account": self.ids.field_account.text.strip(),
            "backup_codes": self.ids.field_backup.text.strip(),
        }

        app = MDApp.get_running_app()

        if self.editing_index >= 0:
            app.services[self.editing_index] = service_data
            msg = f'"{title}" ' + t("updated", "обновлено")
        else:
            app.services.append(service_data)
            msg = f'"{title}" ' + t("added", "добавлено")

        save_services(app.services)
        app.refresh_main_screen()

        toast(msg)

        self.go_back()

    def scan_qr(self):
        """Open live camera scanner (or file picker on desktop) to scan QR and fill fields."""
        if not _has_qr_decoder():
            toast(t("QR scanner not available", "Сканер QR недоступен"))
            return

        def on_image(path_or_paths):
            path = path_or_paths[0] if isinstance(path_or_paths, list) else path_or_paths
            if not path or not os.path.exists(path):
                toast(t("No image selected", "Изображение не выбрано"))
                return
            data = _decode_qr_from_path(path)
            if not data:
                toast(t("QR code not found in image", "QR-код не найден на изображении"))
                return
            self._apply_otpauth(data)

        if platform == "android":
            app = MDApp.get_running_app()
            app.sm.transition.direction = "left"
            app.sm.current = "qr_scan"
        else:
            def _pick_file():
                try:
                    from plyer import filechooser
                    result = filechooser.open_file(
                        filters=[["Images", "*.png", "*.jpg", "*.jpeg", "*.bmp"]],
                    )
                    if result:
                        Clock.schedule_once(lambda dt: on_image(result), 0)
                except Exception as e:
                    Clock.schedule_once(lambda dt: toast(t("Error", "Ошибка") + f": {e}"), 0)

            threading.Thread(target=_pick_file, daemon=True).start()

    def _on_camera_done(self, path):
        """Called when camera capture completes on Android."""
        if not path or not os.path.exists(path):
            toast(t("Photo not received", "Фото не получено"))
            return
        try:
            data = _decode_qr_from_path(path)
            try:
                os.remove(path)
            except Exception:
                pass
            if not data:
                toast(t("QR code not found", "QR-код не найден"))
                return
            self._apply_otpauth(data)
        except Exception as e:
            toast(t("Error", "Ошибка") + f": {e}")

    def _apply_otpauth(self, uri: str):
        """Parse otpauth:// URI and fill form fields."""
        uri = uri.strip()
        if not uri.lower().startswith("otpauth://"):
            toast(t("Invalid format (expected otpauth://)", "Неверный формат (ожидается otpauth://)"))
            return
        try:
            parsed = urllib.parse.urlparse(uri)
            params = urllib.parse.parse_qs(parsed.query)
            secret = (params.get("secret", [""]) or [""])[0]
            issuer = (params.get("issuer", [""]) or [""])[0]
            label = urllib.parse.unquote((parsed.path or "").lstrip("/").replace("totp/", "").strip())
            if ":" in label:
                parts = label.split(":", 1)
                if not issuer:
                    issuer = parts[0].strip()
                account = parts[1].strip() if len(parts) > 1 else ""
            else:
                account = label.strip()
            self.ids.field_secret.text = secret.replace(" ", "").upper()
            self.ids.field_secret.error = False
            self.ids.field_title.text = issuer or account or "unknown"
            self.ids.field_title.error = False
            self.ids.field_account.text = account
            self.ids.field_title.helper_text_mode = "on_focus"
            self.ids.field_secret.helper_text_mode = "on_focus"
            toast(t("QR code scanned", "QR-код считан"))
        except Exception as e:
            toast(t("Parse error", "Ошибка разбора") + f": {e}")

    def go_back(self):
        app = MDApp.get_running_app()
        app.sm.transition.direction = "right"
        app.sm.current = "main"


class BackupCodesScreen(MDScreen):
    """Screen showing backup codes for a service."""

    def go_back(self):
        app = MDApp.get_running_app()
        app.sm.transition.direction = "right"
        app.sm.current = "main"


# ── QRScanScreen — ФИКС ПОВОРОТА: angle=90 + надёжный origin + reapply после layout ──
# (Kivy Camera на Android по умолчанию даёт -90° offset в превью — компенсируем +90°)

class QRScanScreen(MDScreen):
    """
    Стабильный QR-сканер для Android (Kivy Camera + OpenCV)
    
    ИСПРАВЛЕНИЯ (основаны на логах ROTATION_90 + опыте Kivy/SO):
    - Превью: фиксированный angle=90 (компенсирует встроенный -90° Kivy Camera)
    - Origin: width/2, height/2 (более надёжно, чем center_x/y)
    - Reapply: после добавления камеры (через Clock, чтобы layout прошёл)
    - Frame для QR: авто-ротация на основе _get_android_display_rotation()
    - Debug: логи в консоль (adb logcat | grep QR)
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._camera = None
        self._scanning = False
        self._last_data = None
        self._scan_interval = 0.08  # ~12 FPS для скорости

        try:
            import cv2
            self._detector = cv2.QRCodeDetector()
        except Exception:
            self._detector = None

    # ========================
    # SCREEN EVENTS
    # ========================

    def on_enter(self):
        Clock.schedule_once(lambda dt: self.start_camera(), 0.2)

    def on_leave(self, *args):
        self.stop_camera()

    # ========================
    # CAMERA CONTROL
    # ========================

    def start_camera(self):
        self.stop_camera()

        try:
            self._camera = Camera(
                index=0,
                resolution=(640, 480),
                play=True,
                allow_stretch=True,
                keep_ratio=True,
                size_hint=(1, 1),
            )

            self.ids.camera_container.clear_widgets()
            self.ids.camera_container.add_widget(self._camera)

            self._scanning = True

            # ── ФИКС ПОВОРОТА ПРЕВЬЮ (Kivy Android) ──
            if platform == "android":
                Clock.schedule_once(self._apply_camera_rotation, 0.3)  # После layout

            # Сканирование
            Clock.schedule_interval(self._scan_frame, self._scan_interval)

        except Exception as e:
            self.ids.camera_container.clear_widgets()
            lbl = MDLabel(
                text=f"Ошибка камеры:\n{e}",
                halign="center",
                valign="middle",
                theme_text_color="Error",
            )
            self.ids.camera_container.add_widget(lbl)

    def _apply_camera_rotation(self, *_):
        """Применяем Rotate к камере (компенсируем -90°).
        PopMatrix в canvas.after — иначе вращение не применяется к отрисовке камеры.
        """
        if not self._camera:
            return

        angle = -90  # ← ОСНОВНОЙ ФИКС (попробуй -90 / 0 / 180 если не так)
        print(f"[QR] Applying preview rotation: {angle}°")

        with self._camera.canvas.before:
            PushMatrix()
            self._camera._rot = Rotate(
                angle=angle,
                origin=(self._camera.center_x, self._camera.center_y),
            )

        with self._camera.canvas.after:
            PopMatrix()

        def update_rot(widget, *args):
            if hasattr(widget, "_rot"):
                widget._rot.origin = (widget.center_x, widget.center_y)

        self._camera.bind(pos=update_rot, size=update_rot)
        self._camera.canvas.ask_update()

    def stop_camera(self):
        self._scanning = False
        Clock.unschedule(self._scan_frame)

        if self._camera:
            try:
                self._camera.play = False
            except Exception:
                pass
            self._camera = None

        if "camera_container" in self.ids:
            self.ids.camera_container.clear_widgets()

    # ========================
    # FRAME SCANNING
    # ========================

    def _scan_frame(self, dt):
        if not self._scanning or not self._camera:
            return

        try:
            import cv2
            import numpy as np

            if platform == "android":
                provider = getattr(self._camera, "_camera", None)
                if not provider or not hasattr(provider, "grab_frame"):
                    return

                buf = provider.grab_frame()
                if not buf:
                    return

                buf = bytes(buf) if not isinstance(buf, bytes) else buf
                w, h = getattr(provider, "_resolution", (640, 480))

                need = (h + h // 2) * w
                if len(buf) < need:
                    return

                arr = np.frombuffer(buf[:need], dtype=np.uint8)
                arr = arr.reshape((h + h // 2, w))
                frame = cv2.cvtColor(arr, cv2.COLOR_YUV2BGR_NV21)
                # NV21 на Android почти всегда приходит повёрнут на 90° против часовой
                frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)

            else:
                texture = self._camera.texture
                if not texture or not texture.pixels:
                    return

                image_data = texture.pixels
                image_data = bytes(image_data) if not isinstance(image_data, bytes) else image_data
                w, h = texture.size

                expected = w * h * 4
                if len(image_data) < expected:
                    return

                arr = np.frombuffer(image_data[:expected], dtype=np.uint8)
                frame = arr.reshape((h, w, 4))
                frame = cv2.cvtColor(frame, cv2.COLOR_RGBA2BGR)

            data = _decode_qr_from_frame(frame)

            if data and data.strip() and data != self._last_data:
                self._last_data = data
                print(f"[QR] DETECTED: {data[:60]}...")
                Clock.schedule_once(lambda dt: self.on_qr_found(data), 0)

        except Exception as e:
            print(f"[QR] scan error: {e}")

    # ========================
    # QR RESULT
    # ========================

    def on_qr_found(self, data):
        print(f"[QR] FOUND: {data}")
        self.stop_camera()

        app = MDApp.get_running_app()
        app.sm.transition.direction = "right"
        app.sm.current = "add_edit"

        add_screen = app.sm.get_screen("add_edit")
        add_screen._apply_otpauth(data)

    # ========================
    # FILE PICKER
    # ========================

    def pick_image(self):
        from plyer import filechooser

        def _cb(selection):
            if not selection:
                return
            path = selection[0]
            data = _decode_qr_from_path(path)
            if data:
                self.on_qr_found(data)

        filechooser.open_file(on_selection=_cb)


class AuthenticatorApp(MDApp):
    """Main application class."""

    _is_desktop = platform not in ('android', 'ios')

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.services = []
        self.sm = None
        self._update_event = None
        self._cards = []
        self._ntp_dialog = None
        self._time_offset = 0.0  # offset in seconds vs NTP

    def build(self):
        # Set data directory (Android-safe: uses app private storage)
        set_data_dir(self.user_data_dir)
        print(f"[Authenticator] Data dir: {self.user_data_dir}")

        # Request CAMERA permission at runtime (required on Android 6+)
        if platform == "android":
            try:
                from android.permissions import request_permissions, Permission
                request_permissions([Permission.CAMERA])
            except Exception as e:
                print(f"[Authenticator] Permission request: {e}")

        # Theme configuration
        self.theme_cls.theme_style = "Dark"
        self.theme_cls.primary_palette = "Teal"
        self.theme_cls.accent_palette = "Cyan"
        self.theme_cls.material_style = "M3"

        # Compute translation variables after Android initialization
        _app_title = t("Authenticator", "Аутентификатор")
        _add_service = t("Add Service", "Добавить сервис")
        _empty_services = t("No services yet.\\nTap + to add the first one.", "Еще нет сервисов.\\nНажмите + чтобы добавить первый сервис.")
        _edit_service = t("Edit Service", "Редактировать сервис")
        _backup_codes = t("Backup Codes", "Резервные коды")
        _hint_title = t("Name *", "Название *")
        _hint_title_help = t("e.g. Google, GitHub, Discord", "например, Google, GitHub, Discord")
        _hint_url = t("Service URL", "URL сервиса")
        _hint_url_help = t("e.g. https://accounts.google.com", "например, https://accounts.google.com")
        _hint_secret = t("Secret Key *", "Секретный ключ *")
        _hint_secret_help = t("Base32-encoded secret from the service", "Base32 закодированный секрет от сервиса")
        _hint_account = t("Account", "Аккаунт")
        _hint_account_help = t("e.g. user@gmail.com", "например, user@gmail.com")
        _hint_backup = t("Backup Codes", "Резервные коды")
        _hint_backup_help = t("Comma-separated backup codes", "Запятая-разделенные резервные коды")
        _btn_save = t("SAVE", "СОХРАНИТЬ")
        _btn_update = t("UPDATE", "ОБНОВИТЬ")
        _scan_qr_title = t("Scan QR Code", "Сканировать QR-код")

        # Build KV with translations using f-string
        KV = f"""
#:import Clock kivy.clock.Clock

<ServiceCard>:
    orientation: "vertical"
    size_hint_y: None
    height: dp(140)
    padding: dp(16), dp(12), dp(16), dp(8)
    spacing: dp(4)
    md_bg_color: app.theme_cls.bg_darkest
    radius: [dp(16)]
    elevation: 3
    ripple_behavior: False

    MDBoxLayout:
        orientation: "horizontal"
        size_hint_y: None
        height: dp(28)

        MDLabel:
            id: title_label
            text: root.title
            font_style: "Subtitle1"
            theme_text_color: "Secondary"
            size_hint_x: 0.7

        MDLabel:
            id: account_label
            text: root.account
            font_style: "Caption"
            theme_text_color: "Hint"
            halign: "right"
            size_hint_x: 0.3

    MDBoxLayout:
        orientation: "horizontal"
        size_hint_y: None
        height: dp(56)
        spacing: dp(8)

        MDLabel:
            id: code_label
            text: root.totp_code
            font_style: "H4"
            theme_text_color: "Primary"
            bold: True
            halign: "left"
            size_hint_x: 0.7

        MDIconButton:
            icon: "content-copy"
            theme_text_color: "Custom"
            text_color: app.theme_cls.primary_color
            on_release: root.copy_code()
            pos_hint: {{"center_y": .5}}

    MDBoxLayout:
        orientation: "horizontal"
        size_hint_y: None
        height: dp(32)
        spacing: dp(8)

        MDProgressBar:
            id: timer_bar
            value: root.timer_progress
            color: app.theme_cls.primary_color
            size_hint_y: None
            height: dp(4)
            pos_hint: {{"center_y": .5}}

        MDLabel:
            id: timer_label
            text: str(int(root.timer_seconds)) + "s"
            font_style: "Caption"
            theme_text_color: "Hint"
            size_hint_x: None
            width: dp(30)
            halign: "right"

        MDIconButton:
            icon: "pencil"
            theme_text_color: "Custom"
            text_color: app.theme_cls.accent_color
            on_release: root.edit_service()
            pos_hint: {{"center_y": .5}}

        MDIconButton:
            icon: "delete"
            theme_text_color: "Custom"
            text_color: [0.9, 0.3, 0.3, 1]
            on_release: root.confirm_delete()
            pos_hint: {{"center_y": .5}}


<MainScreen>:
    name: "main"

    MDBoxLayout:
        orientation: "vertical"

        MDTopAppBar:
            title: "{_app_title}"
            anchor_title: "center"
            elevation: 0
            md_bg_color: app.theme_cls.primary_color
            specific_text_color: 1, 1, 1, 1
            left_action_items: [["", lambda x: None]]
            right_action_items: [["plus", lambda x: root.open_add_screen(), "{_add_service}"]] if app._is_desktop else [["plus", lambda x: root.open_add_screen()]]

        MDScrollView:
            id: scroll_view
            do_scroll_x: False

            MDBoxLayout:
                id: services_list
                orientation: "vertical"
                padding: dp(12), dp(12)
                spacing: dp(12)
                size_hint_y: None
                height: self.minimum_height

                MDLabel:
                    id: empty_label
                    text: "{_empty_services}"
                    halign: "center"
                    theme_text_color: "Hint"
                    font_style: "Subtitle1"
                    size_hint_y: None
                    height: dp(200)
                    opacity: 1


<AddEditScreen>:
    name: "add_edit"

    MDBoxLayout:
        orientation: "vertical"

        MDTopAppBar:
            id: toolbar
            title: "{_add_service}"
            anchor_title: "center"
            elevation: 0
            md_bg_color: app.theme_cls.primary_color
            specific_text_color: 1, 1, 1, 1
            left_action_items: [["arrow-left", lambda x: root.go_back()]]
            right_action_items: [["camera", lambda x: root.scan_qr()]]

        MDScrollView:
            do_scroll_x: False

            MDBoxLayout:
                orientation: "vertical"
                padding: dp(24), dp(24)
                spacing: dp(16)
                size_hint_y: None
                height: self.minimum_height

                MDTextField:
                    id: field_title
                    hint_text: "{_hint_title}"
                    helper_text: "{_hint_title_help}"
                    helper_text_mode: "on_focus"
                    icon_left: "tag"
                    required: True
                    size_hint_y: None
                    height: dp(48)

                MDTextField:
                    id: field_url
                    hint_text: "{_hint_url}"
                    helper_text: "{_hint_url_help}"
                    helper_text_mode: "on_focus"
                    icon_left: "web"
                    size_hint_y: None
                    height: dp(48)

                MDTextField:
                    id: field_secret
                    hint_text: "{_hint_secret}"
                    helper_text: "{_hint_secret_help}"
                    helper_text_mode: "on_focus"
                    icon_left: "key"
                    required: True
                    size_hint_y: None
                    height: dp(48)

                MDTextField:
                    id: field_account
                    hint_text: "{_hint_account}"
                    helper_text: "{_hint_account_help}"
                    helper_text_mode: "on_focus"
                    icon_left: "account"
                    size_hint_y: None
                    height: dp(48)

                MDTextField:
                    id: field_backup
                    hint_text: "{_hint_backup}"
                    helper_text: "{_hint_backup_help}"
                    helper_text_mode: "on_focus"
                    icon_left: "shield-key"
                    multiline: True
                    size_hint_y: None
                    height: dp(100)

                Widget:
                    size_hint_y: None
                    height: dp(16)

                MDRaisedButton:
                    id: save_btn
                    text: "{_btn_save}"
                    md_bg_color: app.theme_cls.primary_color
                    pos_hint: {{"center_x": .5}}
                    size_hint_x: 0.6
                    on_release: root.save_service()

                Widget:
                    size_hint_y: None
                    height: dp(24)


<BackupCodesScreen>:
    name: "backup_codes"

    MDBoxLayout:
        orientation: "vertical"

        MDTopAppBar:
            title: "{_backup_codes}"
            anchor_title: "center"
            elevation: 0
            md_bg_color: app.theme_cls.primary_color
            specific_text_color: 1, 1, 1, 1
            left_action_items: [["arrow-left", lambda x: root.go_back()]]
            right_action_items: [["", lambda x: None]]

        MDScrollView:
            do_scroll_x: False

            MDBoxLayout:
                id: codes_container
                orientation: "vertical"
                padding: dp(24), dp(24)
                spacing: dp(8)
                size_hint_y: None
                height: self.minimum_height


<QRScanScreen>:
    name: "qr_scan"

    MDBoxLayout:
        orientation: "vertical"

        MDTopAppBar:
            title: "Scan QR"
            elevation: 4
            left_action_items: [["arrow-left", lambda x: app.go_back()]]
            right_action_items: [["camera-plus", lambda x: root.pick_image()]]

        BoxLayout:
            id: camera_container
"""

        Builder.load_string(KV)

        # Load saved services
        self.services = load_services()

        # Screen manager
        self.sm = MDScreenManager()
        self.main_screen = MainScreen()
        self.add_edit_screen = AddEditScreen()
        self.backup_screen = BackupCodesScreen()
        self.qr_scan_screen = QRScanScreen()

        self.sm.add_widget(self.main_screen)
        self.sm.add_widget(self.add_edit_screen)
        self.sm.add_widget(self.backup_screen)
        self.sm.add_widget(self.qr_scan_screen)

        # Populate services list
        self.refresh_main_screen()

        # Schedule TOTP code updates every second
        self._update_event = Clock.schedule_interval(self._update_all_codes, 1)

        # Check system clock against NTP in background
        check_ntp_offset(self._on_ntp_result)

        return self.sm

    def _on_ntp_result(self, offset):
        """Called from background thread with NTP offset result."""
        # Schedule UI update on main thread
        Clock.schedule_once(lambda dt: self._handle_ntp_offset(offset))

    def _handle_ntp_offset(self, offset):
        """Handle NTP check result on main thread."""
        if offset is None:
            # Could not reach NTP servers — no internet or firewall
            return

        self._time_offset = offset
        abs_offset = abs(offset)

        if abs_offset > 5:
            direction_ru = "спешат" if offset > 0 else "отстают"
            direction_en = "ahead" if offset > 0 else "behind"
            direction = direction_ru if _is_russian() else direction_en
            title_ntp = t("Clock Out of Sync", "Часы рассинхронизированы")
            text_ntp = (
                f"Ваше системное время на {abs_offset:.1f}s {direction} "
                f"от фактического времени.\n\n"
                f"TOTP коды могут не работать правильно, если смещение "
                f"превышает 30 секунд.\n\n"
                f"Пожалуйста, синхронизируйте ваше системное время:\n"
                f"Настройки > Система > Время и дата > Синхронизировать сейчас"
            ) if _is_russian() else (
                f"Your system time is {abs_offset:.1f}s {direction} of actual time.\n\n"
                "TOTP codes may not work correctly if the offset exceeds 30 seconds.\n\n"
                "Please sync your system time:\n"
                "Settings > System > Date & time > Sync now"
            )
            self._ntp_dialog = MDDialog(
                title=title_ntp,
                text=text_ntp,
                buttons=[
                    MDFlatButton(
                        text="OK",
                        theme_text_color="Custom",
                        text_color=self.theme_cls.primary_color,
                        on_release=lambda x: self._ntp_dialog.dismiss(),
                    ),
                ],
            )
            self._ntp_dialog.open()
        else:
            toast(t("Clock synced (offset: {:.1f}s)", "Часы синхронизированы (смещение: {:.1f}s)").format(abs_offset))

    def go_back(self):
        """Navigate back from QR scan to add_edit screen."""
        if hasattr(self, "qr_scan_screen") and self.qr_scan_screen:
            self.qr_scan_screen.stop_camera()
        self.sm.transition.direction = "right"
        self.sm.current = "add_edit"

    def refresh_main_screen(self):
        """Rebuild the services list on main screen."""
        container = self.main_screen.ids.services_list
        container.clear_widgets()
        self._cards.clear()

        if not self.services:
            # Show empty state
            empty_label = MDLabel(
                text=t("No services yet.\nTap [b]+[/b] to add the first one.", "Еще нет сервисов.\nНажмите [b]+[/b] чтобы добавить первый сервис."),
                halign="center",
                theme_text_color="Hint",
                font_style="Subtitle1",
                size_hint_y=None,
                height=dp(200),
                markup=True,
            )
            container.add_widget(empty_label)
        else:
            for i, service in enumerate(self.services):
                card = ServiceCard(service_data=service, index=i)
                self._cards.append(card)
                container.add_widget(card)

    def _update_all_codes(self, dt):
        """Update TOTP codes on all visible cards."""
        for card in self._cards:
            card._update_code()

    def open_add_screen(self):
        """Navigate to add service screen."""
        self.add_edit_screen.editing_index = -1
        self.sm.transition.direction = "left"
        self.sm.current = "add_edit"

    def open_edit_screen(self, index: int):
        """Navigate to edit service screen."""
        self.add_edit_screen.editing_index = index
        self.sm.transition.direction = "left"
        self.sm.current = "add_edit"

    def delete_service(self, index: int):
        """Delete a service by index."""
        if 0 <= index < len(self.services):
            removed = self.services.pop(index)
            save_services(self.services)
            self.refresh_main_screen()
            toast(f'"{removed.get("title", "")}" ' + t("deleted", "удален"))

    def open_backup_codes(self, index: int):
        """Show backup codes for a service."""
        service = self.services[index]
        container = self.backup_screen.ids.codes_container
        container.clear_widgets()

        title = MDLabel(
            text=service.get("title", ""),
            font_style="H5",
            theme_text_color="Primary",
            size_hint_y=None,
            height=dp(48),
        )
        container.add_widget(title)

        codes_text = service.get("backup_codes", "")
        if codes_text:
            codes = [c.strip() for c in codes_text.replace("\n", ",").split(",") if c.strip()]
            for code in codes:
                code_label = MDLabel(
                    text=f"  {code}",
                    font_style="H6",
                    theme_text_color="Secondary",
                    size_hint_y=None,
                    height=dp(40),
                )
                container.add_widget(code_label)
        else:
            container.add_widget(
                MDLabel(
                    text=t("No backup codes.", "Нет резервных кодов."),
                    theme_text_color="Hint",
                    size_hint_y=None,
                    height=dp(48),
                )
            )

        self.sm.transition.direction = "left"
        self.sm.current = "backup_codes"

    def on_stop(self):
        """Save data on app exit."""
        if self._update_event:
            self._update_event.cancel()
        save_services(self.services)


if __name__ == "__main__":
    AuthenticatorApp().run()
