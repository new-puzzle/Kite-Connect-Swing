import os
import json
import datetime
from typing import List

from fastapi import FastAPI, Query, HTTPException
from starlette.responses import RedirectResponse, JSONResponse
from kiteconnect import KiteConnect
from dotenv import load_dotenv

# Load environment variables from .env file for local development
load_dotenv()

# Initialize FastAPI app
app = FastAPI(
    title="Kite Connect API",
    description="An API to interact with Kite Connect, with daily data caching.",
    servers=[{"url": "https://kite-connect-swing.vercel.app"}]
)

# Get API key and secret from environment variables
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
CACHE_FILE_PATH = "/tmp/portfolio_data.json"

# --- Helper Functions ---

def get_authenticated_kite():
    """
    Creates a KiteConnect instance and authenticates it using the access token
    from environment variables. Returns None if authentication fails.
    """
    access_token = os.getenv("KITE_ACCESS_TOKEN")
    if not access_token:
        return None
    
    kite = KiteConnect(api_key=API_KEY)
    try:
        kite.set_access_token(access_token)
    except Exception:
        return None  # Token likely expired or invalid
        
    return kite

def calculate_and_build_portfolio_data(kite: KiteConnect):
    """
    Fetches holdings and quotes, then calculates and structures the portfolio data
    as per the specified JSON format.
    """
    build_start_time = datetime.datetime.now()
    
    # Fetch holdings and positions
    try:
        holdings = kite.holdings()
        # In a real scenario, you might want to merge positions as well
        # positions = kite.positions()['net']
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch holdings: {e}")

    if not holdings:
        return {"holdings": [], "totals": {}, "quotes": {}, "build_metrics": {"error": "No holdings found"}}

    # Prepare list of instruments for quote fetching
    instrument_tokens = [h['instrument_token'] for h in holdings]
    
    # Fetch quotes for all instruments in one call
    try:
        quotes = kite.quote(instrument_tokens)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch quotes: {e}")

    # --- Data Enrichment and Calculation ---
    enriched_holdings = []
    total_invested = 0
    total_current_value = 0
    total_todays_pnl = 0

    for h in holdings:
        symbol = h['tradingsymbol']
        instrument_token = h['instrument_token']
        quote = quotes.get(str(instrument_token))

        if not quote:
            continue

        invested_value = h['average_price'] * h['quantity']
        current_value = quote['last_price'] * h['quantity']
        net_pnl_abs = current_value - invested_value
        net_pnl_pct = (net_pnl_abs / invested_value) * 100 if invested_value != 0 else 0
        
        todays_pnl_abs = (quote['last_price'] - quote['ohlc']['close']) * h['quantity']
        todays_pnl_pct = (todays_pnl_abs / invested_value) * 100 if invested_value != 0 else 0

        enriched_holdings.append({
            "symbol": symbol,
            "exchange": h['exchange'],
            "qty": h['quantity'],
            "avg_price": h['average_price'],
            "invested_value": round(invested_value, 2),
            "ltp": quote['last_price'],
            "current_value": round(current_value, 2),
            "net_pnl_abs": round(net_pnl_abs, 2),
            "net_pnl_pct": round(net_pnl_pct, 2),
            "todays_pnl_abs": round(todays_pnl_abs, 2),
            "todays_pnl_pct": round(todays_pnl_pct, 2)
        })
        
        total_invested += invested_value
        total_current_value += current_value
        total_todays_pnl += todays_pnl_abs

    # --- Totals Calculation ---
    total_net_pnl = total_current_value - total_invested
    total_net_pnl_pct = (total_net_pnl / total_invested) * 100 if total_invested != 0 else 0
    total_todays_pnl_pct = (total_todays_pnl / total_invested) * 100 if total_invested != 0 else 0

    build_end_time = datetime.datetime.now()
    build_duration = (build_end_time - build_start_time).total_seconds() * 1000

    return {
        "holdings": enriched_holdings,
        "totals": {
            "invested_value": round(total_invested, 2),
            "current_value": round(total_current_value, 2),
            "net_pnl_abs": round(total_net_pnl, 2),
            "net_pnl_pct": round(total_net_pnl_pct, 2),
            "todays_pnl_abs": round(total_todays_pnl, 2),
            "todays_pnl_pct": round(total_todays_pnl_pct, 2)
        },
        "quotes": {
            str(q['instrument_token']): {
                "close": q['ohlc']['close'],
                "ltp": q['last_price']
            } for q in quotes.values()
        },
        "build_metrics": {
            "build_ms": round(build_duration),
            "quotes_ok": True,
            "holdings_ok": True,
            "timestamp_utc": build_end_time.isoformat()
        }
    }

def load_snapshot():
    """
    Loads the cached portfolio data from the file system.
    Returns None if the file does not exist or cannot be loaded.
    """
    if os.path.exists(CACHE_FILE_PATH):
        try:
            with open(CACHE_FILE_PATH, 'r') as f:
                return json.load(f)
        except Exception:
            return None
    return None

# --- API Endpoints ---

@app.get("/")
def root():
    """Lists all available API routes."""
    return {
        "message": "Welcome to the Kite Connect API Bridge.",
        "routes": ["/auth/login", "/api/portfolio", "/api/save_daily_data", "/api/ohlc"]
    }

@app.get("/auth/login")
def login():
    """Redirects the user to the Kite login page to start the auth flow."""
    kite = KiteConnect(api_key=API_KEY)
    login_url = kite.login_url()
    return RedirectResponse(url=login_url)

@app.get("/auth/callback")
def auth_callback(request_token: str):
    """
    Handles the callback from Kite after a successful login.
    Generates an access token. The user must then manually set this
    as the KITE_ACCESS_TOKEN environment variable in Vercel.
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
        raise HTTPException(status_code=400, detail=f"Could not generate session: {e}")

@app.get("/api/portfolio")
def get_full_portfolio(
    mode: str = Query("auto", pattern="^(auto|live|cache)$")
):
    """
    **Primary endpoint for the GPT.**
    Fetches portfolio data based on the specified mode:
    - `auto`: Tries live first; if live fails, falls back to cached snapshot.
    - `live`: Forces live data fetch; returns 503 if live fails.
    - `cache`: Forces cached snapshot; returns 503 if no snapshot is available.
    """
    live_err = None

    # 1) FORCE LIVE ONLY
    if mode == "live":
        kite = get_authenticated_kite()
        if not kite:
            raise HTTPException(status_code=503, detail="Live fetch failed: Authentication failed or token invalid.")
        try:
            payload = calculate_and_build_portfolio_data(kite)
            payload["source"] = "LIVE"
            payload["mode_used"] = "live"
            return payload
        except HTTPException as e:
            raise HTTPException(status_code=503, detail=f"Live fetch failed: {e.detail}")

    # 2) FORCE CACHE ONLY
    elif mode == "cache":
        snapshot = load_snapshot()
        if snapshot and snapshot.get("holdings") is not None:
            snapshot["source"] = "EOD"
            snapshot["mode_used"] = "cache"
            return snapshot
        else:
            raise HTTPException(status_code=503, detail="No cached snapshot available.")

    # 3) AUTO MODE (try live, then fallback to cache)
    elif mode == "auto":
        kite = get_authenticated_kite()
        if kite:
            try:
                payload = calculate_and_build_portfolio_data(kite)
                payload["source"] = "LIVE"
                payload["mode_used"] = "auto_live"
                return payload
            except HTTPException as e:
                live_err = e.detail
        else:
            live_err = "Authentication failed or token invalid."

        # Fallback to cache if live failed or not authenticated
        snapshot = load_snapshot()
        if snapshot and snapshot.get("holdings") is not None:
            snapshot["source"] = "EOD"
            snapshot["mode_used"] = f"auto_fallback (live_error: {live_err})" if live_err else "auto_fallback"
            return snapshot
        else:
            raise HTTPException(
                status_code=503, 
                detail=f"Live fetch failed ({live_err}) and no cached snapshot available."
            )

@app.get("/api/save_daily_data")
def save_daily_data():
    """
    **Endpoint for Cron Job.**
    Fetches fresh portfolio data, calculates all metrics, and saves the result
    to a cache file for after-hours access.
    """
    kite = get_authenticated_kite()
    if not kite:
        raise HTTPException(
            status_code=401, 
            detail="Authentication failed. Cannot save daily data. Is KITE_ACCESS_TOKEN valid?"
        )
    
    try:
        portfolio_data = calculate_and_build_portfolio_data(kite)
        
        with open(CACHE_FILE_PATH, 'w') as f:
            json.dump(portfolio_data, f, indent=2)
            
        return {
            "status": "success",
            "message": f"Successfully saved portfolio data to {CACHE_FILE_PATH}",
            "timestamp_utc": portfolio_data['build_metrics']['timestamp_utc']
        }
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"An error occurred while generating or saving portfolio data: {e}"
        )

@app.get("/api/ohlc", summary="Fetch historical OHLC data")
def get_ohlc_data(
    instrument_token: str = Query(..., description="Instrument token for the stock"),
    from_date: str = Query(..., description="Start date in YYYY-MM-DD format"),
    to_date: str = Query(..., description="End date in YYYY-MM-DD format"),
    interval: str = Query(..., description="Data interval (e.g., '5minute', 'day')"),
):
    """
    Fetches historical Open, High, Low, Close (OHLC) data for a given instrument.
    """
    kite = get_authenticated_kite()
    if not kite:
        raise HTTPException(
            status_code=401, 
            detail="Authentication failed. Is KITE_ACCESS_TOKEN valid?"
        )
    
    try:
        # Validate date formats
        datetime.datetime.strptime(from_date, '%Y-%m-%d')
        datetime.datetime.strptime(to_date, '%Y-%m-%d')
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid date format. Please use YYYY-MM-DD."
        )

    try:
        historical_data = kite.historical_data(instrument_token, from_date, to_date, interval)
        return JSONResponse(content=historical_data)
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"An error occurred while fetching historical data: {e}"
        )