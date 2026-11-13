"""Jalankan SEKALI di laptop untuk mendapatkan GOOGLE_REFRESH_TOKEN.

    pip install google-auth-oauthlib
    python get_token.py

Butuh file client_secret.json (OAuth client tipe "Desktop app") di folder ini.
"""

from google_auth_oauthlib.flow import InstalledAppFlow

flow = InstalledAppFlow.from_client_secrets_file(
    "client_secret.json", ["https://www.googleapis.com/auth/drive"]
)
creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")

print("\nSalin ke environment variables (Railway / .env):\n")
print(f"GOOGLE_CLIENT_ID={creds.client_id}")
print(f"GOOGLE_CLIENT_SECRET={creds.client_secret}")
print(f"GOOGLE_REFRESH_TOKEN={creds.refresh_token}")
