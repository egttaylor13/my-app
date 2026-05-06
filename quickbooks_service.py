import os
import requests
from intuitlib.client import AuthClient
from intuitlib.enums import Scopes

QB_BASE = "https://quickbooks.api.intuit.com"


def _redirect_uri():
    return os.getenv("APP_URL", "http://localhost:8000") + "/auth/quickbooks/callback"


def get_auth_client():
    return AuthClient(
        client_id=os.getenv("QB_CLIENT_ID", ""),
        client_secret=os.getenv("QB_CLIENT_SECRET", ""),
        redirect_uri=_redirect_uri(),
        environment="production",
    )


def get_auth_url(auth_client, state):
    url, _ = auth_client.get_authorization_url([Scopes.ACCOUNTING], state=state)
    return url


def exchange_code(auth_client, code, realm_id):
    auth_client.get_bearer_token(code, realm_id=realm_id)
    return {
        "access_token": auth_client.access_token,
        "refresh_token": auth_client.refresh_token,
    }


def _headers(access_token):
    return {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}


def _query(access_token, realm_id, q):
    url = f"{QB_BASE}/v3/company/{realm_id}/query"
    resp = requests.get(url, headers=_headers(access_token), params={"query": q, "minorversion": "65"}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def fetch_transactions(token_row):
    if not token_row:
        return []

    at = token_row.access_token
    rid = token_row.realm_id
    transactions = []

    try:
        data = _query(at, rid, "SELECT * FROM Purchase ORDER BY TxnDate DESC MAXRESULTS 100")
        for p in data.get("QueryResponse", {}).get("Purchase", []):
            transactions.append({
                "qb_id": f"purchase_{p['Id']}",
                "date": p.get("TxnDate", ""),
                "vendor": p.get("EntityRef", {}).get("name", "Unknown"),
                "amount": float(p.get("TotalAmt", 0)),
                "category": p.get("AccountRef", {}).get("name", "Uncategorized"),
                "txn_type": "expense",
            })
    except Exception:
        pass

    try:
        data = _query(at, rid, "SELECT * FROM Invoice ORDER BY TxnDate DESC MAXRESULTS 100")
        for inv in data.get("QueryResponse", {}).get("Invoice", []):
            transactions.append({
                "qb_id": f"invoice_{inv['Id']}",
                "date": inv.get("TxnDate", ""),
                "vendor": inv.get("CustomerRef", {}).get("name", "Unknown"),
                "amount": float(inv.get("TotalAmt", 0)),
                "category": "Income",
                "txn_type": "income",
            })
    except Exception:
        pass

    return transactions
