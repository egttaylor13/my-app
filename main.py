import os
import uuid
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db, engine, Base, OAuthToken, Transaction, Receipt
import gmail_service
import quickbooks_service

Base.metadata.create_all(bind=engine)

app = FastAPI()
templates = Jinja2Templates(directory="templates")

_oauth_states: dict[str, str] = {}


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    gmail_token = db.query(OAuthToken).filter_by(service="gmail").first()
    qb_token = db.query(OAuthToken).filter_by(service="quickbooks").first()

    transactions = db.query(Transaction).all()
    receipts = db.query(Receipt).all()

    income = sum(t.amount for t in transactions if t.txn_type == "income")
    expenses = sum(t.amount for t in transactions if t.txn_type == "expense")
    unmatched_count = sum(1 for r in receipts if not r.matched)

    categories: dict[str, float] = {}
    for t in transactions:
        if t.txn_type == "expense":
            categories[t.category] = categories.get(t.category, 0) + t.amount

    monthly: dict[str, dict] = {}
    for t in transactions:
        if t.date and len(t.date) >= 7:
            month = t.date[:7]
            monthly.setdefault(month, {"income": 0.0, "expense": 0.0})
            monthly[month][t.txn_type] += t.amount

    monthly_labels = sorted(monthly.keys())[-12:]
    monthly_income = [round(monthly.get(m, {}).get("income", 0), 2) for m in monthly_labels]
    monthly_expenses = [round(monthly.get(m, {}).get("expense", 0), 2) for m in monthly_labels]

    recent_txns = sorted(transactions, key=lambda t: t.date or "", reverse=True)[:20]
    unmatched_receipts = [r for r in receipts if not r.matched][:20]

    return templates.TemplateResponse("index.html", {
        "request": request,
        "gmail_connected": gmail_token is not None,
        "qb_connected": qb_token is not None,
        "income": income,
        "expenses": expenses,
        "net": income - expenses,
        "unmatched_count": unmatched_count,
        "categories": categories,
        "monthly_labels": monthly_labels,
        "monthly_income": monthly_income,
        "monthly_expenses": monthly_expenses,
        "recent_txns": recent_txns,
        "unmatched_receipts": unmatched_receipts,
    })


# ── Gmail OAuth ────────────────────────────────────────────────────────────────

@app.get("/auth/gmail")
def auth_gmail():
    flow = gmail_service.get_flow()
    state = str(uuid.uuid4())
    _oauth_states[state] = "gmail"
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        state=state,
        prompt="consent",
    )
    return RedirectResponse(auth_url)


@app.get("/auth/gmail/callback")
def auth_gmail_callback(code: str = "", state: str = "", db: Session = Depends(get_db)):
    if not code:
        return HTMLResponse("<html><body><h2>Gmail OAuth Callback</h2><p>This URL is used by the Dadsbooks app to complete Gmail sign-in. <a href='/'>Go to dashboard</a></p></body></html>")
    if state not in _oauth_states:
        return JSONResponse({"error": "Invalid OAuth state"}, status_code=400)
    _oauth_states.pop(state)

    flow = gmail_service.get_flow()
    flow.fetch_token(code=code)
    creds = flow.credentials

    token = db.query(OAuthToken).filter_by(service="gmail").first()
    if not token:
        token = OAuthToken(service="gmail")
        db.add(token)
    token.access_token = creds.token
    token.refresh_token = creds.refresh_token
    token.token_expiry = creds.expiry.isoformat() if creds.expiry else None
    db.commit()

    return RedirectResponse("/")


# ── QuickBooks OAuth ───────────────────────────────────────────────────────────

@app.get("/auth/quickbooks")
def auth_quickbooks():
    if not os.getenv("QB_CLIENT_ID"):
        return JSONResponse({"error": "QuickBooks credentials not configured"}, status_code=503)
    state = str(uuid.uuid4())
    _oauth_states[state] = "quickbooks"
    auth_url = quickbooks_service.get_auth_url(state)
    return RedirectResponse(auth_url)


@app.get("/auth/quickbooks/callback")
def auth_quickbooks_callback(
    code: str = "", realmId: str = "", state: str = "", db: Session = Depends(get_db)
):
    if not code:
        return HTMLResponse("<html><body><h2>QuickBooks OAuth Callback</h2><p>This URL is used by the Dadsbooks app to complete QuickBooks sign-in. <a href='/'>Go to dashboard</a></p></body></html>")
    if state and state not in _oauth_states:
        return JSONResponse({"error": "Invalid OAuth state"}, status_code=400)
    if state:
        _oauth_states.pop(state)

    tokens = quickbooks_service.exchange_code(code, realmId)

    token = db.query(OAuthToken).filter_by(service="quickbooks").first()
    if not token:
        token = OAuthToken(service="quickbooks")
        db.add(token)
    token.access_token = tokens["access_token"]
    token.refresh_token = tokens["refresh_token"]
    token.realm_id = realmId
    db.commit()

    return RedirectResponse("/")


# ── Sync ───────────────────────────────────────────────────────────────────────

@app.post("/sync")
def sync(db: Session = Depends(get_db)):
    results: dict = {"receipts_added": 0, "transactions_added": 0, "matched": 0, "errors": []}

    # Gmail receipts
    gmail_token = db.query(OAuthToken).filter_by(service="gmail").first()
    if gmail_token:
        try:
            for r in gmail_service.fetch_receipts(gmail_token, db):
                if not db.query(Receipt).filter_by(email_id=r["email_id"]).first():
                    db.add(Receipt(
                        email_id=r["email_id"],
                        date=r["date"],
                        vendor=r["vendor"],
                        subject=r["subject"],
                        snippet=r["snippet"],
                    ))
                    results["receipts_added"] += 1
            db.commit()
        except Exception as e:
            results["errors"].append(f"Gmail: {e}")

    # QuickBooks transactions
    qb_token = db.query(OAuthToken).filter_by(service="quickbooks").first()
    if qb_token:
        try:
            for t in quickbooks_service.fetch_transactions(qb_token):
                if not db.query(Transaction).filter_by(qb_id=t["qb_id"]).first():
                    db.add(Transaction(**t))
                    results["transactions_added"] += 1
            db.commit()
        except Exception as e:
            results["errors"].append(f"QuickBooks: {e}")

    # Match receipts to transactions by vendor name
    try:
        unmatched = db.query(Receipt).filter_by(matched=False).all()
        open_txns = db.query(Transaction).filter_by(matched_receipt_id=None).all()

        for receipt in unmatched:
            if not receipt.vendor:
                continue
            rv = receipt.vendor.lower()
            for txn in open_txns:
                if not txn.vendor:
                    continue
                tv = txn.vendor.lower()
                if rv in tv or tv in rv:
                    txn.matched_receipt_id = receipt.id
                    receipt.matched = True
                    results["matched"] += 1
                    open_txns.remove(txn)
                    break
        db.commit()
    except Exception as e:
        results["errors"].append(f"Matching: {e}")

    return results
