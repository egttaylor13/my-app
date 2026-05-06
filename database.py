from sqlalchemy import create_engine, Column, Integer, String, Float, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker

DATABASE_URL = "sqlite:///./app.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class OAuthToken(Base):
    __tablename__ = "oauth_tokens"
    id = Column(Integer, primary_key=True, index=True)
    service = Column(String, unique=True)
    access_token = Column(String)
    refresh_token = Column(String)
    token_expiry = Column(String)
    realm_id = Column(String, nullable=True)


class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(Integer, primary_key=True, index=True)
    qb_id = Column(String, unique=True)
    date = Column(String)
    vendor = Column(String)
    amount = Column(Float)
    category = Column(String)
    txn_type = Column(String)
    matched_receipt_id = Column(Integer, nullable=True)


class Receipt(Base):
    __tablename__ = "receipts"
    id = Column(Integer, primary_key=True, index=True)
    email_id = Column(String, unique=True)
    date = Column(String)
    vendor = Column(String)
    subject = Column(String)
    snippet = Column(String)
    matched = Column(Boolean, default=False)
