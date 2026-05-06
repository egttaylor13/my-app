import os
import re
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


def _redirect_uri():
    return os.getenv("APP_URL", "http://localhost:8000") + "/auth/gmail/callback"


def get_flow():
    client_config = {
        "web": {
            "client_id": os.getenv("GMAIL_CLIENT_ID"),
            "client_secret": os.getenv("GMAIL_CLIENT_SECRET"),
            "redirect_uris": [_redirect_uri()],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    return Flow.from_client_config(client_config, scopes=SCOPES, redirect_uri=_redirect_uri())


def get_credentials(token_row):
    if not token_row:
        return None
    creds = Credentials(
        token=token_row.access_token,
        refresh_token=token_row.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.getenv("GMAIL_CLIENT_ID"),
        client_secret=os.getenv("GMAIL_CLIENT_SECRET"),
        scopes=SCOPES,
    )
    return creds


def refresh_if_needed(creds, token_row, db):
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_row.access_token = creds.token
        db.commit()


def fetch_receipts(token_row, db):
    creds = get_credentials(token_row)
    if not creds:
        return []
    refresh_if_needed(creds, token_row, db)

    service = build("gmail", "v1", credentials=creds)
    query = 'subject:(receipt OR invoice OR "order confirmation" OR "your order") newer_than:90d'
    result = service.users().messages().list(userId="me", q=query, maxResults=200).execute()
    messages = result.get("messages", [])

    receipts = []
    for msg in messages:
        try:
            full = service.users().messages().get(
                userId="me",
                id=msg["id"],
                format="metadata",
                metadataHeaders=["Subject", "From", "Date"],
            ).execute()
            headers = {h["name"]: h["value"] for h in full["payload"]["headers"]}

            from_field = headers.get("From", "")
            vendor = re.sub(r"<.*?>", "", from_field).strip().strip('"')

            snippet = full.get("snippet", "")
            amount = None
            m = re.search(r"\$[\d,]+\.?\d*", snippet)
            if m:
                try:
                    amount = float(m.group().replace("$", "").replace(",", ""))
                except ValueError:
                    pass

            receipts.append({
                "email_id": msg["id"],
                "subject": headers.get("Subject", "")[:500],
                "vendor": vendor[:200],
                "date": headers.get("Date", "")[:100],
                "snippet": snippet[:1000],
                "amount": amount,
            })
        except Exception:
            continue

    return receipts
