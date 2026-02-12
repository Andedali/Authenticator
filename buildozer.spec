[app]

# (str) Title of your application
title = Authenticator

# (str) Package name
package.name = authenticator

# (str) Package domain (needed for android/ios packaging)
package.domain = org.andedali

# (str) Source code where the main.py lives
source.dir = .

# (list) Source files to include (let empty to include all the files)
source.include_exts = py,png,jpg,kv,atlas,json

# (list) Source files to exclude (let empty to not exclude anything)
source.exclude_dirs = .git,.github,.venv,__pycache__,bin

# (str) Application versioning
version = 1.0.0

# (list) Application requirements
# comma separated e.g. requirements = sqlite3,kivy
requirements = python3,kivy==2.3.1,kivymd==1.2.0,pyotp,pillow,materialyoucolor,exceptiongroup,asyncgui,asynckivy,filetype

# (str) Supported orientation (one of landscape, sensorLandscape, portrait or all)
orientation = portrait

# (bool) Indicate if the application should be fullscreen or not
fullscreen = 0

#
# Android specific
#

# (list) Permissions
android.permissions = INTERNET

# (int) Target Android API, should be as high as possible.
android.api = 33

# (int) Minimum API your APK / AAB will support.
android.minapi = 21

# (str) Android NDK version to use
android.ndk = 25b

# (bool) If True, then skip trying to update the Android sdk
# This can be useful to avoid excess Internet downloads or save time
# when an update is due and you just want to test/build your package
android.skip_update = False

# (bool) If True, then automatically accept SDK license
# agreements. This is intended for automation only. If set to False,
# the default, you will be shown the license when first running
# buildozer.
android.accept_sdk_license = True

# (list) The Android archs to build for
android.archs = arm64-v8a

# (str) The entry point of the application (default: main.py)
# Use Authenticator.py as the main entry
#android.entrypoint = org.kivy.android.PythonActivity

# (str) presplash color
android.presplash_color = #1a1a2e

# (bool) Allow backup of app data
android.allow_backup = True

# (str) Android logcat filters to use
android.logcat_filters = *:S python:D

# (str) Icon of the application
icon.filename = %(source.dir)s/icon.png

# (str) Presplash of the application
presplash.filename = %(source.dir)s/presplash.png

[buildozer]

# (int) Log level (0 = error only, 1 = info, 2 = debug (with command output))
log_level = 2

# (int) Display warning if buildozer is run as root (0 = False, 1 = True)
warn_on_root = 1
