import os
import base64
import requests

QB_AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
QB_TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
QB_BASE = "https://quickbooks.api.intuit.com"
QB_SCOPE = "com.intuit.quickbooks.accounting"


def _redirect_uri():
    return os.getenv("APP_URL", "http://localhost:8000") + "/auth/quickbooks/callback"


def get_auth_url(state):
    params = {
        "client_id": os.getenv("QB_CLIENT_ID", ""),
        "response_type": "code",
        "scope": QB_SCOPE,
        "redirect_uri": _redirect_uri(),
        "state": state,
    }
    req = requests.Request("GET", QB_AUTH_URL, params=params).prepare()
    return req.url


def exchange_code(code, realm_id):
    client_id = os.getenv("QB_CLIENT_ID", "")
    client_secret = os.getenv("QB_CLIENT_SECRET", "")
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()

    resp = requests.post(
        QB_TOKEN_URL,
        headers={
            "Authorization": f"Basic {credentials}",
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": _redirect_uri(),
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    return {"access_token": data["access_token"], "refresh_token": data["refresh_token"]}


def _headers(access_token):
    return {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}


def _query(access_token, realm_id, q):
    url = f"{QB_BASE}/v3/company/{realm_id}/query"
    resp = requests.get(
        url, headers=_headers(access_token),
        params={"query": q, "minorversion": "65"},
        timeout=15,
    )
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
