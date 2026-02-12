"""Entry point for Buildozer (Android) builds."""
import traceback

try:
    from authenticator import AuthenticatorApp
except Exception as e:
    print(f"[Authenticator] IMPORT ERROR: {e}")
    traceback.print_exc()
    raise

if __name__ == "__main__":
    try:
        AuthenticatorApp().run()
    except Exception as e:
        print(f"[Authenticator] RUNTIME ERROR: {e}")
        traceback.print_exc()
        raise
