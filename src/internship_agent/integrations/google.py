import json
import keyring
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SERVICE="personal.internship-agent"
SCOPES=["https://www.googleapis.com/auth/gmail.readonly","https://www.googleapis.com/auth/spreadsheets"]


def authorize(path):
    flow=InstalledAppFlow.from_client_secrets_file(path,SCOPES)
    creds=flow.run_local_server(port=0,access_type="offline",prompt="consent")
    if not creds.refresh_token:
        raise ValueError("Google did not issue an offline refresh token")
    keyring.set_password(SERVICE,"google",creds.to_json())


def client(name,version):
    value=keyring.get_password(SERVICE,"google")
    if not value:
        raise RuntimeError("Google OAuth setup required")
    creds=Credentials.from_authorized_user_info(json.loads(value),SCOPES)
    if not creds.valid:
        creds.refresh(Request())
        keyring.set_password(SERVICE,"google",creds.to_json())
    return build(name,version,credentials=creds,cache_discovery=False)
