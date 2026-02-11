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
import pyotp
import pyperclip
from pathlib import Path

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
from kivy.animation import Animation

# ── Window size for desktop testing (ignored on mobile) ──────────────
Window.size = (400, 720)


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
DATA_DIR = Path(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = DATA_DIR / "services.json"


def load_services() -> list:
    """Load services list from JSON file."""
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
    return []


def save_services(services: list):
    """Save services list to JSON file."""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(services, f, ensure_ascii=False, indent=2)


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
KV = """
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
            pos_hint: {"center_y": .5}

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
            pos_hint: {"center_y": .5}

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
            pos_hint: {"center_y": .5}

        MDIconButton:
            icon: "delete"
            theme_text_color: "Custom"
            text_color: [0.9, 0.3, 0.3, 1]
            on_release: root.confirm_delete()
            pos_hint: {"center_y": .5}


<MainScreen>:
    name: "main"

    MDBoxLayout:
        orientation: "vertical"

        MDTopAppBar:
            title: "Аутентификатор"
            anchor_title: "center"
            elevation: 0
            md_bg_color: app.theme_cls.primary_color
            specific_text_color: 1, 1, 1, 1
            left_action_items: [["", lambda x: None]]
            right_action_items: [["plus", lambda x: root.open_add_screen(), "Добавить сервис"]]

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
                    text: "Еще нет сервисов.\\nНажмите + чтобы добавить первый сервис."
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
            title: "Добавить сервис"
            anchor_title: "center"
            elevation: 0
            md_bg_color: app.theme_cls.primary_color
            specific_text_color: 1, 1, 1, 1
            left_action_items: [["arrow-left", lambda x: root.go_back()]]
            right_action_items: [["", lambda x: None]]

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
                    hint_text: "Название *"
                    helper_text: "например, Google, GitHub, Discord"
                    helper_text_mode: "on_focus"
                    icon_left: "tag"
                    required: True
                    size_hint_y: None
                    height: dp(48)

                MDTextField:
                    id: field_url
                    hint_text: "URL сервиса"
                    helper_text: "например, https://accounts.google.com"
                    helper_text_mode: "on_focus"
                    icon_left: "web"
                    size_hint_y: None
                    height: dp(48)

                MDTextField:
                    id: field_secret
                    hint_text: "Секретный ключ *"
                    helper_text: "Base32 закодированный секрет от сервиса"
                    helper_text_mode: "on_focus"
                    icon_left: "key"
                    required: True
                    size_hint_y: None
                    height: dp(48)

                MDTextField:
                    id: field_account
                    hint_text: "Аккаунт"
                    helper_text: "например, user@gmail.com"
                    helper_text_mode: "on_focus"
                    icon_left: "account"
                    size_hint_y: None
                    height: dp(48)

                MDTextField:
                    id: field_backup
                    hint_text: "Резервные коды"
                    helper_text: "Запятая-разделенные резервные коды"
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
                    text: "SAVE"
                    md_bg_color: app.theme_cls.primary_color
                    pos_hint: {"center_x": .5}
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
            title: "Резервные коды"
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
"""


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
            pyperclip.copy(code)
            toast(f"Код скопирован: {self.totp_code}")
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
            title="Delete Service",
            text=f'Delete "{self.title}"? This cannot be undone.',
            buttons=[
                MDFlatButton(
                    text="CANCEL",
                    theme_text_color="Custom",
                    text_color=app.theme_cls.primary_color,
                    on_release=lambda x: self._delete_dialog.dismiss(),
                ),
                MDRaisedButton(
                    text="DELETE",
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
            self.ids.toolbar.title = "Редактировать сервис"
            self.ids.field_title.text = service.get("title", "")
            self.ids.field_url.text = service.get("url", "")
            self.ids.field_secret.text = service.get("secret", "")
            self.ids.field_account.text = service.get("account", "")
            self.ids.field_backup.text = service.get("backup_codes", "")
            self.ids.save_btn.text = "ОБНОВИТЬ"
        else:
            self.ids.toolbar.title = "Добавить сервис"
            self.ids.field_title.text = ""
            self.ids.field_url.text = ""
            self.ids.field_secret.text = ""
            self.ids.field_account.text = ""
            self.ids.field_backup.text = ""
            self.ids.save_btn.text = "СОХРАНИТЬ"

    def save_service(self):
        """Validate and save the service."""
        title = self.ids.field_title.text.strip()
        secret = self.ids.field_secret.text.strip()

        if not title:
            self.ids.field_title.error = True
            self.ids.field_title.helper_text = "Название обязательно"
            self.ids.field_title.helper_text_mode = "on_error"
            return

        if not secret:
            self.ids.field_secret.error = True
            self.ids.field_secret.helper_text = "Секретный ключ обязательно"
            self.ids.field_secret.helper_text_mode = "on_error"
            return

        # Validate secret key
        try:
            secret_clean = secret.replace(" ", "").upper()
            pyotp.TOTP(secret_clean).now()
        except Exception:
            self.ids.field_secret.error = True
            self.ids.field_secret.helper_text = "Неверный Base32 секретный ключ"
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
            msg = f'"{title}" updated'
        else:
            app.services.append(service_data)
            msg = f'"{title}" added'

        save_services(app.services)
        app.refresh_main_screen()

        toast(msg)

        self.go_back()

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


class AuthenticatorApp(MDApp):
    """Main application class."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.services: list = []
        self.sm: MDScreenManager | None = None
        self._update_event = None
        self._cards: list[ServiceCard] = []
        self._ntp_dialog = None
        self._time_offset: float = 0.0  # offset in seconds vs NTP

    def build(self):
        # Theme configuration
        self.theme_cls.theme_style = "Dark"
        self.theme_cls.primary_palette = "Teal"
        self.theme_cls.accent_palette = "Cyan"
        self.theme_cls.material_style = "M3"

        Builder.load_string(KV)

        # Load saved services
        self.services = load_services()

        # Screen manager
        self.sm = MDScreenManager()
        self.main_screen = MainScreen()
        self.add_edit_screen = AddEditScreen()
        self.backup_screen = BackupCodesScreen()

        self.sm.add_widget(self.main_screen)
        self.sm.add_widget(self.add_edit_screen)
        self.sm.add_widget(self.backup_screen)

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
            direction = "ahead" if offset > 0 else "behind"
            self._ntp_dialog = MDDialog(
                title="Clock Out of Sync",
                text=(
                    f"Ваше системное время на {abs_offset:.1f}s {direction} "
                    f"от фактического времени.\n\n"
                    f"TOTP коды могут не работать правильно, если смещение "
                    f"превышает 30 секунд.\n\n"
                    f"Пожалуйста, синхронизируйте ваше системное время:\n"
                    f"Настройки > Время и дата > Синхронизировать сейчас"
                ),
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
            toast(f"Часы синхронизированы (смещение: {abs_offset:.1f}s)")

    def refresh_main_screen(self):
        """Rebuild the services list on main screen."""
        container = self.main_screen.ids.services_list
        container.clear_widgets()
        self._cards.clear()

        if not self.services:
            # Show empty state
            empty_label = MDLabel(
                text="Еще нет сервисов.\nНажмите [b]+[/b] чтобы добавить первый сервис.",
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
            toast(f'"{removed.get("title", "")}" удален')

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
                    text="Нет резервных кодов.",
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
