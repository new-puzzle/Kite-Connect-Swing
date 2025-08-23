import os
import json
from typing import List

from fastapi import FastAPI, Query
from starlette.responses import RedirectResponse
from kiteconnect import KiteConnect
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Initialize FastAPI app
app = FastAPI()

# Get API key and secret from environment variables
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")

# --- Helper function to get a Kite connect instance with a valid token ---
def get_authenticated_kite():
    access_token = os.getenv("KITE_ACCESS_TOKEN")
    if not access_token:
        return None # User needs to set KITE_ACCESS_TOKEN env var
    
    kite = KiteConnect(api_key=API_KEY)
    try:
        kite.set_access_token(access_token)
    except Exception:
        # This could be due to an expired token
        return None
        
    return kite


@app.get("/")
def root():
    """Lists all available API routes."""
    return {"routes": ["/auth/login", "/portfolio/holdings", "/portfolio/positions", "/quote?symbols=NSE:RELIANCE"]}


@app.get("/auth/login")
def login():
    """Redirects the user to the Kite login page."""
    kite = KiteConnect(api_key=API_KEY)
    login_url = kite.login_url()
    return RedirectResponse(url=login_url)


@app.get("/auth/callback")
def auth_callback(request_token: str):
    """
    Handles the callback from Kite after a successful login.
    Generates a session and returns the access token for manual setup.
    """
    try:
        kite = KiteConnect(api_key=API_KEY)
        session_data = kite.generate_session(request_token, api_secret=API_SECRET)
        access_token = session_data["access_token"]
        
        return {
            "status": "success",
            "message": "Access token generated. Please set this as a Vercel Environment Variable named KITE_ACCESS_TOKEN.",
            "access_token": access_token
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/portfolio/holdings")
def get_holdings():
    """Fetches portfolio holdings."""
    kite = get_authenticated_kite()
    if not kite:
        return {"status": "error", "message": "User not logged in. Please go to /auth/login"}
    try:
        return kite.holdings()
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/portfolio/positions")
def get_positions():
    """Fetches current positions."""
    kite = get_authenticated_kite()
    if not kite:
        return {"status": "error", "message": "User not logged in. Please go to /auth/login"}
    try:
        return kite.positions()
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/quote")
def get_quote(symbols: List[str] = Query(..., description="List of symbols, e.g., ['NSE:RELIANCE', 'BSE:TCS']")):
    """Fetches real-time quotes for a list of symbols."""
    kite = get_authenticated_kite()
    if not kite:
        return {"status": "error", "message": "User not logged in. Please go to /auth/login"}
    try:
        return kite.quote(symbols)
    except Exception as e:
        return {"status": "error", "message": str(e)}
