from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from flask_cors import CORS
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
from math import log, sqrt, erf
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv
import os
from functools import wraps
import secrets

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# Enable CORS for all routes (configure allowed origins in production)
CORS(app, resources={
    r"/api/*": {
        "origins": "*",  # Change to specific domains in production: ["https://yourbubbleapp.com"]
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "X-API-Key"]
    }
})

# Google OAuth credentials check
OAUTH_CONFIGURED = (
    os.environ.get('GOOGLE_CLIENT_ID') and 
    os.environ.get('GOOGLE_CLIENT_ID') != 'your_client_id_here.apps.googleusercontent.com' and
    os.environ.get('GOOGLE_CLIENT_SECRET') and 
    os.environ.get('GOOGLE_CLIENT_SECRET') != 'your_client_secret_here'
)

# OAuth Setup - only if credentials are configured
if OAUTH_CONFIGURED:
    oauth = OAuth(app)
    google = oauth.register(
        name='google',
        client_id=os.environ.get('GOOGLE_CLIENT_ID'),
        client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={'scope': 'openid email profile'}
    )

# human-readable data provider/source
DATA_PROVIDER = 'Yahoo Finance (yfinance)'

# Configuration for scoring model
WEIGHTS = {
    'probability': 0.70,  # 70% weight on probability of profit (increased to show higher probability trades)
    'roi': 0.20,          # 20% weight on expected ROI
    'risk': 0.10          # 10% weight on risk exposure
}

# Strike selection configuration - minimum distance from spot for safer recommendations
MIN_OTM_PERCENT = 2.5  # Minimum 2.5% out-of-the-money for short strikes
MIN_SPREAD_WIDTH_DOLLARS = 5.0  # Minimum $5 width between short and long strikes

# Advanced probability calculation parameters
RISK_FREE_RATE = 0.045  # Current risk-free rate (4.5% - approximate 10Y Treasury)
IV_WEIGHT = 0.7  # Weight for implied volatility in blend
HV_WEIGHT = 0.3  # Weight for historical volatility in blend
MIN_VOL_FLOOR = 0.20  # Minimum 20% volatility floor (realistic for stocks)

def blend_volatility(implied_vol, historical_vol, iv_weight=IV_WEIGHT, hv_weight=HV_WEIGHT):
    """Blend implied and historical volatility with configurable weights"""
    # If IV is suspiciously low (< 10%), trust HV more
    if implied_vol > 0 and implied_vol < 0.10 and historical_vol > 0:
        # IV is unrealistic, use mostly historical
        blended = 0.2 * implied_vol + 0.8 * historical_vol
    elif implied_vol > 0 and historical_vol > 0:
        blended = iv_weight * implied_vol + hv_weight * historical_vol
    elif implied_vol > 0:
        blended = implied_vol
    elif historical_vol > 0:
        blended = historical_vol
    else:
        blended = MIN_VOL_FLOOR
    
    # Always apply minimum floor
    return max(blended, MIN_VOL_FLOOR)


# Authentication decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # If OAuth not configured, create a demo session
        if not OAUTH_CONFIGURED and 'user' not in session:
            session['user'] = {
                'email': 'demo@stratify.app',
                'name': 'Demo User',
                'picture': 'https://ui-avatars.com/api/?name=Demo+User&background=43D9B8&color=fff'
            }
        
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def norm_cdf(x):
    # cumulative distribution function for standard normal
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def days_to_years(days):
    return max(days / 365.0, 1e-6)


def estimate_historical_vol(ticker, days=90):
    """Calculate historical volatility (annualized) using 60-90 day window
    Longer period provides more stable estimates than 30-day
    """
    try:
        # Use 90-day default for better stability
        hist = ticker.history(period=f"{days}d")['Close']
        returns = np.log(hist / hist.shift(1)).dropna()
        vol = returns.std() * np.sqrt(252)
        return float(vol)
    except Exception:
        return 0.30  # More realistic fallback than 0.5


def calculate_rsi(prices, period=14):
    """Calculate Relative Strength Index"""
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def get_dividend_yield(ticker):
    """Get dividend yield for dividend-adjusted risk-free rate"""
    try:
        info = ticker.info
        div_yield = info.get('dividendYield', 0.0)
        return float(div_yield) if div_yield else 0.0
    except Exception:
        return 0.0


def get_adjusted_risk_free_rate(ticker):
    """Get dividend-adjusted risk-free rate: r_adj = r - dividend_yield"""
    div_yield = get_dividend_yield(ticker)
    return RISK_FREE_RATE - div_yield


def calculate_bollinger_bands(prices, period=20, std_dev=2):
    """Calculate Bollinger Bands"""
    sma = prices.rolling(window=period).mean()
    std = prices.rolling(window=period).std()
    upper_band = sma + (std * std_dev)
    lower_band = sma - (std * std_dev)
    return sma, upper_band, lower_band


def get_current_rsi(ticker, period=14):
    """Get current RSI value for a ticker"""
    try:
        hist = ticker.history(period='3mo')  # 3 months for RSI calculation
        if hist.empty or len(hist) < period + 1:
            return None
        close_prices = hist['Close']
        rsi = calculate_rsi(close_prices, period=period)
        current_rsi = float(rsi.iloc[-1])
        return round(current_rsi, 1) if not np.isnan(current_rsi) else None
    except Exception:
        return None


def estimate_intrinsic_value(ticker):
    """Estimate intrinsic value using DCF with 10-year projection"""
    try:
        info = ticker.info
        eps = info.get('trailingEps', 0) or info.get('forwardEps', 0)
        if not eps or eps <= 0:
            return None, None
        
        # Get company size to adjust growth expectations
        market_cap = info.get('marketCap', 0)
        
        # Get revenue growth as more reliable indicator than earnings growth
        revenue_growth = info.get('revenueGrowth') or 0.08
        earnings_growth = info.get('earningsGrowth')
        
        # For large cap companies (>100B), use conservative assumptions
        if market_cap > 100e9:  # > $100B market cap
            # Large mature companies: use revenue growth or cap at 12%
            growth_rate = min(revenue_growth, 0.12) if revenue_growth else 0.08
        else:
            # Smaller companies: average revenue and earnings, but still cap
            if earnings_growth and 0 < earnings_growth < 1.0:  # Valid range
                growth_rate = (revenue_growth + earnings_growth) / 2
            else:
                growth_rate = revenue_growth
            growth_rate = min(growth_rate, 0.25)  # Cap at 25%
        
        # Floor at -10% for distressed companies
        growth_rate = max(growth_rate, -0.10)
        
        # Calculate discount rate using CAPM-like approach
        # Risk-free rate (approximate 10-year Treasury)
        risk_free_rate = 0.045  # ~4.5% (current 10-year Treasury as of late 2025)
        
        # Get company beta (measure of volatility vs market)
        beta = info.get('beta')
        if not beta or beta <= 0:
            beta = 1.0  # Default to market beta if not available
        
        # Market risk premium (historical average S&P 500 return - risk-free rate)
        market_risk_premium = 0.08  # 8% historical average
        
        # CAPM: discount_rate = risk_free_rate + (beta * market_risk_premium)
        discount_rate = risk_free_rate + (beta * market_risk_premium)
        
        # Sanity check: keep between 6% and 20%
        discount_rate = min(max(discount_rate, 0.06), 0.20)
        
        terminal_growth = 0.03  # 3% perpetual growth (GDP-like)
        years = 10
        
        # Project future earnings and discount them
        present_value = 0
        future_eps = eps
        calculation_steps = []
        
        for year in range(1, years + 1):
            future_eps = future_eps * (1 + growth_rate)
            discount_factor = 1 / ((1 + discount_rate) ** year)
            pv = future_eps * discount_factor
            present_value += pv
            if year <= 3:  # Show first 3 years in breakdown
                calculation_steps.append({
                    'year': year,
                    'eps': round(future_eps, 2),
                    'pv': round(pv, 2)
                })
        
        # Terminal value (perpetuity beyond year 10)
        terminal_eps = future_eps * (1 + terminal_growth)
        terminal_value = terminal_eps / (discount_rate - terminal_growth)
        terminal_pv = terminal_value / ((1 + discount_rate) ** years)
        present_value += terminal_pv
        
        intrinsic = present_value
        
        # Build calculation breakdown
        breakdown = {
            'method': 'Discounted Cash Flow (DCF)',
            'current_eps': round(eps, 2),
            'growth_rate': round(growth_rate * 100, 1),
            'growth_source': f'Revenue: {round(revenue_growth*100,1)}%, Earnings: {round(earnings_growth*100,1) if earnings_growth else "N/A"}%',
            'market_cap_billions': round(market_cap / 1e9, 1) if market_cap else None,
            'beta': round(beta, 2),
            'discount_rate': round(discount_rate * 100, 1),
            'discount_calculation': f'{risk_free_rate*100:.1f}% + ({beta:.2f} × {market_risk_premium*100:.1f}%)',
            'years_projected': years,
            'terminal_growth': round(terminal_growth * 100, 1),
            'sample_years': calculation_steps,
            'terminal_value_pv': round(terminal_pv, 2),
            'total_intrinsic_value': round(intrinsic, 2)
        }
        
        return float(intrinsic) if intrinsic > 0 else None, breakdown
    except Exception:
        return None, None


def get_vix_level():
    """Fetch current VIX level for market volatility context"""
    try:
        vix = yf.Ticker("^VIX")
        vix_hist = vix.history(period='1d')
        if not vix_hist.empty:
            return float(vix_hist['Close'].iloc[-1])
    except Exception:
        pass
    return 20.0  # default middle VIX


def calculate_iv_rank(ticker, current_iv):
    """Calculate IV rank: where current IV sits in 52-week range"""
    try:
        hist_vol_52w = []
        for period in [30, 60, 90, 180, 252]:
            vol = estimate_historical_vol(ticker, days=min(period, 252))
            if vol > 0:
                hist_vol_52w.append(vol)
        if hist_vol_52w:
            min_iv = min(hist_vol_52w)
            max_iv = max(hist_vol_52w)
            if max_iv > min_iv:
                iv_rank = ((current_iv - min_iv) / (max_iv - min_iv)) * 100.0
                return round(iv_rank, 1)
    except Exception:
        pass
    return 50.0  # default mid-range


def check_earnings_proximity(ticker):
    """Check if earnings is within next 30 days"""
    try:
        info = ticker.info
        earnings_date = info.get('earningsDate', info.get('nextEarningsDate'))
        if earnings_date:
            if isinstance(earnings_date, list) and earnings_date:
                earnings_date = earnings_date[0]
            if isinstance(earnings_date, (int, float)):
                earnings_dt = datetime.fromtimestamp(earnings_date)
                days_to_earnings = (earnings_dt.date() - date.today()).days
                if 0 <= days_to_earnings <= 30:
                    return True, days_to_earnings
    except Exception:
        pass
    return False, None


def calculate_composite_score(probability, roi, risk_score):
    """
    Calculate composite score using weighted model:
    - Probability: 70% (prioritize high probability trades)
    - ROI: 20%
    - Risk: 10%
    Returns score 0-100
    """
    # Normalize inputs to 0-100 scale
    prob_norm = min(max(probability, 0), 100)
    roi_norm = min(max(roi * 1.5, 0), 100)  # scale ROI (0-67% -> 0-100)
    risk_norm = min(max(risk_score, 0), 100)
    
    score = (
        WEIGHTS['probability'] * prob_norm +
        WEIGHTS['roi'] * roi_norm +
        WEIGHTS['risk'] * risk_norm
    )
    return round(score, 2)


def analyze_bull_put_spread(symbol, expiry=None):
    t = yf.Ticker(symbol)

    # Calculate RSI
    current_rsi = get_current_rsi(t)

    # spot
    try:
        hist = t.history(period='2d')
        spot = float(hist['Close'].iloc[-1])
        try:
            price_timestamp = hist.index[-1].to_pydatetime().isoformat() + 'Z'
        except Exception:
            price_timestamp = None
    except Exception:
        spot = None
        price_timestamp = None

    exps = t.options
    if not exps:
        return {'symbol': symbol, 'error': 'no options available'}

    if expiry is None:
        expiry = exps[0]
    try:
        opt = t.option_chain(expiry)
        puts = opt.puts
    except Exception:
        return {'symbol': symbol, 'error': 'failed to fetch option chain'}

    # find short and long put strikes for a single bull put spread
    # Target: short strike at least MIN_OTM_PERCENT below spot, reasonable spread width
    puts_sorted = puts.sort_values('strike')
    min_short_strike = spot * (1 - MIN_OTM_PERCENT / 100)
    puts_below_target = puts_sorted[puts_sorted['strike'] <= min_short_strike]
    
    if puts_below_target.empty:
        # fallback: use strikes below spot
        puts_below_spot = puts_sorted[puts_sorted['strike'] < spot]
        if puts_below_spot.empty:
            short = puts_sorted.iloc[-1]
            long = puts_sorted.iloc[max(len(puts_sorted)-2,0)]
        else:
            short = puts_below_spot.iloc[-1]
            idx = puts_sorted.index.get_loc(short.name)
            long_idx = max(0, idx - 1)
            long = puts_sorted.iloc[long_idx]
    else:
        # Pick short strike closest to target (but below it)
        short = puts_below_target.iloc[-1]
        # Find long strike for adequate spread width
        target_long_strike = float(short['strike']) - MIN_SPREAD_WIDTH_DOLLARS
        puts_for_long = puts_sorted[puts_sorted['strike'] < float(short['strike'])]
        if not puts_for_long.empty:
            # Pick strike closest to target long strike
            puts_for_long['distance'] = abs(puts_for_long['strike'] - target_long_strike)
            long = puts_for_long.loc[puts_for_long['distance'].idxmin()]
        else:
            idx = puts_sorted.index.get_loc(short.name)
            long_idx = max(0, idx - 1)
            long = puts_sorted.iloc[long_idx]

    # use available prices/bid/ask, fallback to lastPrice
    short_bid = float(short.get('bid', 0.0) or short.get('lastPrice', 0.0) or 0.0)
    long_ask = float(long.get('ask', 0.0) or long.get('lastPrice', 0.0) or 0.0)
    
    # If still 0, skip this strategy
    if short_bid == 0.0 or long_ask == 0.0:
        return {'symbol': symbol, 'error': 'no pricing data available for options'}
    
    credit = max(short_bid - long_ask, 0.0)

    strike_short = float(short['strike'])
    strike_long = float(long['strike'])
    strike_diff = abs(strike_short - strike_long)

    max_profit = credit
    max_loss = strike_diff - credit
    roi = (credit / max(1e-6, max_loss)) * 100.0 if max_loss > 0 else 0.0

    # days to expiry
    exp_date = datetime.strptime(expiry, '%Y-%m-%d').date()
    dt = (exp_date - date.today()).days
    T = days_to_years(dt)

    # implied vol fallback
    iv = float(short.get('impliedVol') or 0.0)
    iv_fallback = False
    if iv == 0.0 or np.isnan(iv):
        iv = estimate_historical_vol(t, days=30)
        iv_fallback = True

    # Calculate historical volatility (60-90 day)
    hist_vol = estimate_historical_vol(t, days=90)
    
    # Blend IV and HV
    sigma = blend_volatility(iv, hist_vol)
    
    # Get dividend-adjusted risk-free rate
    r_adj = get_adjusted_risk_free_rate(t)
    
    # P(Max Profit): Probability spot stays above short strike at expiration
    # Using risk-neutral drift: μ = r - 0.5σ²
    # Z = [ln(K/S) - (r - 0.5σ²)T] / (σ√T)
    try:
        S = spot
        K_short = strike_short
        
        if sigma <= 0:
            prob_max_profit = 50.0
            prob_any_profit = 50.0
        else:
            # Risk-neutral drift
            drift = r_adj - 0.5 * sigma * sigma
            sigma_sqrt_T = sigma * np.sqrt(T)
            
            # P(Max Profit): P(S_T > K_short)
            Z_max = (np.log(S / K_short) - drift * T) / sigma_sqrt_T
            prob_max_profit = norm_cdf(Z_max) * 100.0
            
            # P(Any Profit): Adjust strike by credit received
            # Break-even: K_short - credit
            K_breakeven = strike_short - credit
            Z_profit = (np.log(S / K_breakeven) - drift * T) / sigma_sqrt_T
            prob_any_profit = norm_cdf(Z_profit) * 100.0
    except Exception:
        prob_max_profit = 50.0
        prob_any_profit = 50.0

    fetched_at = datetime.utcnow().isoformat() + 'Z'

    # Calculate risk score (0-100): higher if strike is far below spot
    strike_distance_pct = ((spot - strike_short) / spot) * 100.0
    risk_score = min(100, max(0, strike_distance_pct * 5))  # scale distance to 0-100
    
    # Calculate composite score using prob_any_profit
    composite_score = calculate_composite_score(prob_any_profit, roi, risk_score)

    result = {
        'symbol': symbol,
        'spot': spot,
        'expiry': expiry,
        'days_to_expiry': dt,
        'strategy': 'Bull Put Spread',
        'short_strike': f"{strike_short:.2f}p",
        'long_strike': f"{strike_long:.2f}p",
        'credit': round(credit * 100, 2),
        'max_profit': round(max_profit * 100, 2),
        'max_loss': round(max_loss * 100, 2),
        'roi_percent': round(roi, 2),
        'probability_success_percent': round(prob_any_profit, 1),  # Use P(Profit > 0)
        'prob_max_profit': round(prob_max_profit, 1),  # P(Max Profit)
        'breakeven': round(K_breakeven, 2) if 'K_breakeven' in locals() else round(strike_short - credit, 2),
        'composite_score': composite_score,
        'risk_score': round(risk_score, 1),
        'rsi': current_rsi,
        # metadata
        'data_timestamp': fetched_at,
        'price_timestamp': price_timestamp,
        'data_source': DATA_PROVIDER,
        'iv_used': round(float(sigma), 4),
        'hv_used': round(float(hist_vol), 4),
        'iv_source': 'blended (70% IV + 30% HV, 60-90 day)' if not iv_fallback else 'historical only (60-90 day)',
        'iv_source_detail': ('historical: computed from 30-day close returns' if iv_fallback
                    else 'implied: taken from option chain short leg')
    }

    return result


def analyze_bear_call_spread(symbol, expiry=None):
    # mirror of bull put for calls: sell call just above spot, buy next higher call
    t = yf.Ticker(symbol)
    
    # Calculate RSI
    current_rsi = get_current_rsi(t)
    
    try:
        hist = t.history(period='2d')
        spot = float(hist['Close'].iloc[-1])
        try:
            price_timestamp = hist.index[-1].to_pydatetime().isoformat() + 'Z'
        except Exception:
            price_timestamp = None
    except Exception:
        spot = None
        price_timestamp = None

    exps = t.options
    if not exps:
        return {'symbol': symbol, 'error': 'no options available'}

    if expiry is None:
        expiry = exps[0]
    try:
        opt = t.option_chain(expiry)
        calls = opt.calls
    except Exception:
        return {'symbol': symbol, 'error': 'failed to fetch option chain'}

    calls_sorted = calls.sort_values('strike')
    min_short_strike = spot * (1 + MIN_OTM_PERCENT / 100)
    calls_above_target = calls_sorted[calls_sorted['strike'] >= min_short_strike]
    
    if calls_above_target.empty:
        # fallback: use strikes above spot
        calls_above_spot = calls_sorted[calls_sorted['strike'] > spot]
        if calls_above_spot.empty:
            short = calls_sorted.iloc[0]
            long = calls_sorted.iloc[min(1, len(calls_sorted)-1)]
        else:
            short = calls_above_spot.iloc[0]
            idx = calls_sorted.index.get_loc(short.name)
            long_idx = min(len(calls_sorted)-1, idx + 1)
            long = calls_sorted.iloc[long_idx]
    else:
        # Pick short strike closest to target (but above it)
        short = calls_above_target.iloc[0]
        # Find long strike for adequate spread width
        target_long_strike = float(short['strike']) + MIN_SPREAD_WIDTH_DOLLARS
        calls_for_long = calls_sorted[calls_sorted['strike'] > float(short['strike'])]
        if not calls_for_long.empty:
            # Pick strike closest to target long strike
            calls_for_long['distance'] = abs(calls_for_long['strike'] - target_long_strike)
            long = calls_for_long.loc[calls_for_long['distance'].idxmin()]
        else:
            idx = calls_sorted.index.get_loc(short.name)
            long_idx = min(len(calls_sorted)-1, idx + 1)
            long = calls_sorted.iloc[long_idx]

    short_bid = float(short.get('bid', 0.0) or short.get('lastPrice', 0.0) or 0.0)
    long_ask = float(long.get('ask', 0.0) or long.get('lastPrice', 0.0) or 0.0)
    
    # If still 0, skip this strategy
    if short_bid == 0.0 or long_ask == 0.0:
        return {'symbol': symbol, 'error': 'no pricing data available for options'}
    
    credit = max(short_bid - long_ask, 0.0)

    strike_short = float(short['strike'])
    strike_long = float(long['strike'])
    strike_diff = abs(strike_long - strike_short)

    max_profit = credit
    max_loss = strike_diff - credit
    roi = (credit / max(1e-6, max_loss)) * 100.0 if max_loss > 0 else 0.0

    exp_date = datetime.strptime(expiry, '%Y-%m-%d').date()
    dt = (exp_date - date.today()).days
    T = days_to_years(dt)

    iv_short = float(short.get('impliedVol') or 0.0)
    iv_long = float(long.get('impliedVol') or 0.0)
    iv_fallback = False
    iv = iv_short if iv_short > 0 else (iv_long if iv_long > 0 else 0.0)
    if iv == 0.0 or np.isnan(iv):
        iv = estimate_historical_vol(t, days=30)
        iv_fallback = True

    # Calculate historical volatility (60-90 day)
    hist_vol = estimate_historical_vol(t, days=90)
    
    # Blend IV and HV
    sigma = blend_volatility(iv, hist_vol)
    
    # Get dividend-adjusted risk-free rate
    r_adj = get_adjusted_risk_free_rate(t)

    # P(Max Profit): Probability spot stays below short strike at expiration
    # Z = [ln(K/S) - (r - 0.5σ²)T] / (σ√T)
    try:
        S = spot
        K_short = strike_short
        
        if sigma <= 0:
            prob_max_profit = 50.0
            prob_any_profit = 50.0
        else:
            # Risk-neutral drift
            drift = r_adj - 0.5 * sigma * sigma
            sigma_sqrt_T = sigma * np.sqrt(T)
            
            # P(Max Profit): P(S_T < K_short)
            Z_max = (np.log(K_short / S) - drift * T) / sigma_sqrt_T
            prob_max_profit = norm_cdf(Z_max) * 100.0
            
            # P(Any Profit): Adjust strike by credit received
            # Break-even: K_short + credit
            K_breakeven = strike_short + credit
            Z_profit = (np.log(K_breakeven / S) - drift * T) / sigma_sqrt_T
            prob_any_profit = norm_cdf(Z_profit) * 100.0
    except Exception:
        prob_max_profit = 50.0
        prob_any_profit = 50.0

    fetched_at = datetime.utcnow().isoformat() + 'Z'
    iv_source_detail = ('historical: computed from 30-day close returns' if iv_fallback
                        else 'implied: taken from option chain short/long legs')

    # Calculate risk score and composite score
    strike_distance_pct = ((strike_short - spot) / spot) * 100.0
    risk_score = min(100, max(0, strike_distance_pct * 5))
    composite_score = calculate_composite_score(prob_any_profit, roi, risk_score)

    result = {
        'symbol': symbol,
        'spot': spot,
        'expiry': expiry,
        'days_to_expiry': dt,
        'strategy': 'Bear Call Spread',
        'short_strike': f"{strike_short:.2f}c",
        'long_strike': f"{strike_long:.2f}c",
        'credit': round(credit * 100, 2),
        'max_profit': round(max_profit * 100, 2),
        'max_loss': round(max_loss * 100, 2),
        'roi_percent': round(roi, 2),
        'probability_success_percent': round(prob_any_profit, 1),
        'prob_max_profit': round(prob_max_profit, 1),
        'breakeven': round(K_breakeven, 2) if 'K_breakeven' in locals() else round(strike_short + credit, 2),
        'composite_score': composite_score,
        'risk_score': round(risk_score, 1),
        'rsi': current_rsi,
        'data_timestamp': fetched_at,
        'price_timestamp': price_timestamp,
        'data_source': DATA_PROVIDER,
        'iv_used': round(float(sigma), 4),
        'hv_used': round(float(hist_vol), 4),
        'iv_source': 'blended (70% IV + 30% HV, 60-90 day)' if not iv_fallback else 'historical only (60-90 day)',
    }

    return result


def analyze_all_strategies(symbol, max_days=21, top_n=10):
    """
    Evaluate all strategy types across all available expirations within max_days.
    Returns top 5 opportunities ranked by composite score.
    """
    t = yf.Ticker(symbol)
    exps = t.options
    if not exps:
        return {'symbol': symbol, 'strategies': [], 'error': 'no options available'}
    
    # Filter expirations within max_days (minimum 1 day to avoid same-day expiries)
    today = date.today()
    valid_exps = []
    for exp in exps:
        try:
            exp_date = datetime.strptime(exp, '%Y-%m-%d').date()
            days_diff = (exp_date - today).days
            if 1 <= days_diff <= max_days:  # Changed from 0 to 1 to exclude same-day
                valid_exps.append(exp)
        except Exception:
            continue
    
    if not valid_exps:
        return {'symbol': symbol, 'strategies': [], 'error': 'no expirations within range'}
    
    # Evaluate all strategies for all valid expirations
    all_strategies = []
    strategy_funcs = [
        analyze_bull_put_spread,
        analyze_bear_call_spread,
        covered_call,
        cash_secured_put,
        long_call,
        bull_call_spread,
        iron_condor
    ]
    
    for exp in valid_exps:
        for func in strategy_funcs:
            try:
                result = func(symbol, expiry=exp)
                if 'error' not in result and result.get('composite_score') is not None:
                    all_strategies.append(result)
            except Exception:
                continue
    
    # Sort by composite score descending
    all_strategies.sort(key=lambda x: x.get('composite_score', 0), reverse=True)
    
    # Ensure strategy diversity - pick best from each strategy type first
    strategy_types = {}
    for strat in all_strategies:
        strategy_name = strat.get('strategy', '')
        if strategy_name not in strategy_types:
            strategy_types[strategy_name] = []
        strategy_types[strategy_name].append(strat)
    
    # Get top 1-2 from each strategy type to ensure diversity
    diversified_strategies = []
    strategies_per_type = max(1, int(top_n) // len(strategy_types)) if strategy_types else 1
    
    for strategy_name, strats in strategy_types.items():
        diversified_strategies.extend(strats[:strategies_per_type])
    
    # Fill remaining slots with highest scoring strategies not yet included
    remaining_slots = max(1, int(top_n)) - len(diversified_strategies)
    if remaining_slots > 0:
        for strat in all_strategies:
            if strat not in diversified_strategies:
                diversified_strategies.append(strat)
                remaining_slots -= 1
                if remaining_slots <= 0:
                    break
    
    # Final sort by composite score
    diversified_strategies.sort(key=lambda x: x.get('composite_score', 0), reverse=True)
    top_strategies = diversified_strategies[:max(1, int(top_n))]
    
    return {'symbol': symbol, 'strategies': top_strategies}


def covered_call(symbol, expiry=None):
    t = yf.Ticker(symbol)
    
    # Calculate RSI
    current_rsi = get_current_rsi(t)
    
    try:
        hist = t.history(period='2d')
        spot = float(hist['Close'].iloc[-1])
        try:
            price_timestamp = hist.index[-1].to_pydatetime().isoformat() + 'Z'
        except Exception:
            price_timestamp = None
    except Exception:
        spot = None
        price_timestamp = None

    exps = t.options
    if not exps:
        return {'symbol': symbol, 'error': 'no options available'}

    if expiry is None:
        expiry = exps[0]
    try:
        opt = t.option_chain(expiry)
        calls = opt.calls
    except Exception:
        return {'symbol': symbol, 'error': 'failed to fetch option chain'}

    calls_sorted = calls.sort_values('strike')
    min_short_strike = spot * (1 + MIN_OTM_PERCENT / 100)
    calls_above_target = calls_sorted[calls_sorted['strike'] >= min_short_strike]
    
    if calls_above_target.empty:
        # fallback: use strikes above spot
        calls_above = calls_sorted[calls_sorted['strike'] > spot]
        if calls_above.empty:
            short = calls_sorted.iloc[-1]
        else:
            short = calls_above.iloc[0]
    else:
        # Pick strike closest to target OTM level
        short = calls_above_target.iloc[0]

    short_bid = float(short.get('bid', 0.0) or short.get('lastPrice', 0.0) or 0.0)
    strike_short = float(short['strike'])
    
    # If no pricing data, skip
    if short_bid == 0.0:
        return {'symbol': symbol, 'error': 'no pricing data available for options'}

    credit = short_bid
    # covered call max profit: capital gain up to strike + credit
    max_profit = max(0.0, strike_short - spot) + credit
    max_loss = max(0.0, spot - credit)
    roi = (max_profit / max(1e-6, spot)) * 100.0 if spot else 0.0

    fetched_at = datetime.utcnow().isoformat() + 'Z'
    iv_fallback = not (short.get('impliedVol') and short.get('impliedVol') > 0)
    iv_source_detail = ('implied: taken from option chain short leg' if not iv_fallback
                        else 'historical: computed from 30-day close returns')

    # For covered call: risk is capping upside, measure distance of strike from spot
    if spot:
        strike_distance_pct = ((strike_short - spot) / spot) * 100.0
        risk_score = min(100, max(0, 100 - strike_distance_pct * 5))  # closer strike = higher risk (capped upside)
    else:
        risk_score = 50.0
    
    # Calculate probability using risk-neutral drift
    exp_date = datetime.strptime(expiry, '%Y-%m-%d').date()
    dt = (exp_date - date.today()).days
    T = days_to_years(dt)
    
    iv = float(short.get('impliedVolatility', 0.0) or 0.0)
    hist_vol = estimate_historical_vol(t, days=90)
    sigma = blend_volatility(iv, hist_vol)
    
    # Get dividend-adjusted risk-free rate
    r_adj = get_adjusted_risk_free_rate(t)
    
    try:
        if sigma > 0 and spot:
            S = spot
            K_short = strike_short
            
            # Risk-neutral drift
            drift = r_adj - 0.5 * sigma * sigma
            sigma_sqrt_T = sigma * np.sqrt(T)
            
            # P(Max Profit): P(S_T < K_short) - stock stays below strike
            Z_max = (np.log(K_short / S) - drift * T) / sigma_sqrt_T
            prob_max_profit = norm_cdf(Z_max) * 100.0
            
            # P(Any Profit): Always profitable on covered call unless stock drops below (spot - credit)
            # Break-even: spot - credit
            K_breakeven = spot - credit
            Z_profit = (np.log(K_breakeven / S) - drift * T) / sigma_sqrt_T
            prob_any_profit = norm_cdf(Z_profit) * 100.0
        else:
            prob_max_profit = 50.0
            prob_any_profit = 50.0
    except Exception:
        prob_max_profit = 50.0
        prob_any_profit = 50.0
    
    composite_score = calculate_composite_score(prob_any_profit, roi, risk_score)

    return {
        'symbol': symbol,
        'spot': spot,
        'expiry': expiry,
        'days_to_expiry': (datetime.strptime(expiry, '%Y-%m-%d').date() - date.today()).days,
        'strategy': 'Covered Call',
        'short_strike': f"{strike_short:.2f}c",
        'long_strike': None,
        'credit': round(credit * 100, 2),
        'max_profit': round(max_profit * 100, 2),
        'max_loss': round(max_loss * 100, 2),
        'roi_percent': round(roi, 2),
        'probability_success_percent': round(prob_any_profit, 1),
        'prob_max_profit': round(prob_max_profit, 1),
        'breakeven': round(K_breakeven, 2) if 'K_breakeven' in locals() else round(spot - credit, 2),
        'composite_score': composite_score,
        'risk_score': round(risk_score, 1),
        'rsi': current_rsi,
        'data_timestamp': fetched_at,
        'price_timestamp': price_timestamp,
        'data_source': DATA_PROVIDER,
        'iv_used': round(float(sigma), 4),
        'hv_used': round(float(hist_vol), 4),
        'iv_source': 'blended (70% IV + 30% HV, 60-90 day)',
    }


def cash_secured_put(symbol, expiry=None):
    t = yf.Ticker(symbol)
    
    # Calculate RSI
    current_rsi = get_current_rsi(t)
    
    try:
        hist = t.history(period='2d')
        spot = float(hist['Close'].iloc[-1])
        try:
            price_timestamp = hist.index[-1].to_pydatetime().isoformat() + 'Z'
        except Exception:
            price_timestamp = None
    except Exception:
        spot = None
        price_timestamp = None

    exps = t.options
    if not exps:
        return {'symbol': symbol, 'error': 'no options available'}

    if expiry is None:
        expiry = exps[0]
    try:
        opt = t.option_chain(expiry)
        puts = opt.puts
    except Exception:
        return {'symbol': symbol, 'error': 'failed to fetch option chain'}

    puts_sorted = puts.sort_values('strike')
    min_short_strike = spot * (1 - MIN_OTM_PERCENT / 100)
    puts_below_target = puts_sorted[puts_sorted['strike'] <= min_short_strike]
    
    if puts_below_target.empty:
        # fallback: use strikes below spot
        puts_below = puts_sorted[puts_sorted['strike'] < spot]
        if puts_below.empty:
            short = puts_sorted.iloc[-1]
        else:
            short = puts_below.iloc[-1]
    else:
        # Pick strike closest to target OTM level
        short = puts_below_target.iloc[-1]

    short_bid = float(short.get('bid', 0.0) or short.get('lastPrice', 0.0) or 0.0)
    strike_short = float(short['strike'])
    
    # If no pricing data, skip
    if short_bid == 0.0:
        return {'symbol': symbol, 'error': 'no pricing data available for options'}

    credit = short_bid
    # cash-secured put: worst-case we buy stock at strike; max loss = strike - credit
    max_profit = credit
    max_loss = max(0.0, strike_short - credit)
    roi = (credit / max(1e-6, strike_short)) * 100.0

    fetched_at = datetime.utcnow().isoformat() + 'Z'
    iv_fallback = not (short.get('impliedVol') and short.get('impliedVol') > 0)
    iv_source_detail = ('implied: taken from option chain short leg' if not iv_fallback
                        else 'historical: computed from 30-day close returns')

    # Calculate risk score: distance from strike to spot (farther = lower risk)
    if spot:
        strike_distance_pct = ((spot - strike_short) / spot) * 100.0
        risk_score = min(100, max(0, strike_distance_pct * 5))
    else:
        risk_score = 50.0

    # Calculate probability using risk-neutral drift: P(S_T > K_short)
    exp_date = datetime.strptime(expiry, '%Y-%m-%d').date()
    dt = (exp_date - date.today()).days
    T = days_to_years(dt)
    
    iv = float(short.get('impliedVolatility', 0.0) or 0.0)
    hist_vol = estimate_historical_vol(t, days=90)
    sigma = blend_volatility(iv, hist_vol)
    
    # Get dividend-adjusted risk-free rate
    r_adj = get_adjusted_risk_free_rate(t)
    
    try:
        if sigma > 0 and spot:
            S = spot
            K_short = strike_short
            
            # Risk-neutral drift
            drift = r_adj - 0.5 * sigma * sigma
            sigma_sqrt_T = sigma * np.sqrt(T)
            
            # P(Max Profit): P(S_T > K_short) - stock stays above strike
            Z_max = (np.log(S / K_short) - drift * T) / sigma_sqrt_T
            prob_max_profit = norm_cdf(Z_max) * 100.0
            
            # P(Any Profit): Stock stays above (K_short - credit)
            K_breakeven = strike_short - credit
            Z_profit = (np.log(S / K_breakeven) - drift * T) / sigma_sqrt_T
            prob_any_profit = norm_cdf(Z_profit) * 100.0
        else:
            prob_max_profit = 50.0
            prob_any_profit = 50.0
    except Exception:
        prob_max_profit = 50.0
        prob_any_profit = 50.0
    
    composite_score = calculate_composite_score(prob_any_profit, roi, risk_score)

    return {
        'symbol': symbol,
        'spot': spot,
        'expiry': expiry,
        'days_to_expiry': (datetime.strptime(expiry, '%Y-%m-%d').date() - date.today()).days,
        'strategy': 'Cash-Secured Put',
        'short_strike': f"{strike_short:.2f}p",
        'long_strike': None,
        'credit': round(credit * 100, 2),
        'max_profit': round(max_profit * 100, 2),
        'max_loss': round(max_loss * 100, 2),
        'roi_percent': round(roi, 2),
        'probability_success_percent': round(prob_any_profit, 1),
        'prob_max_profit': round(prob_max_profit, 1),
        'breakeven': round(K_breakeven, 2) if 'K_breakeven' in locals() else round(strike_short - credit, 2),
        'composite_score': composite_score,
        'risk_score': round(risk_score, 1),
        'rsi': current_rsi,
        'data_timestamp': fetched_at,
        'price_timestamp': price_timestamp,
        'data_source': DATA_PROVIDER,
        'iv_used': round(float(sigma), 4),
        'hv_used': round(float(hist_vol), 4),
        'iv_source': 'blended (70% IV + 30% HV, 60-90 day)',
    }


def long_call(symbol, expiry=None):
    # simple long call (buy one call) - report cost and prob ITM
    t = yf.Ticker(symbol)
    
    # Calculate RSI
    current_rsi = get_current_rsi(t)
    
    try:
        hist = t.history(period='2d')
        spot = float(hist['Close'].iloc[-1])
        try:
            price_timestamp = hist.index[-1].to_pydatetime().isoformat() + 'Z'
        except Exception:
            price_timestamp = None
    except Exception:
        spot = None
        price_timestamp = None

    exps = t.options
    if not exps:
        return {'symbol': symbol, 'error': 'no options available'}

    if expiry is None:
        expiry = exps[0]
    try:
        opt = t.option_chain(expiry)
        calls = opt.calls
    except Exception:
        return {'symbol': symbol, 'error': 'failed to fetch option chain'}

    calls_sorted = calls.sort_values('strike')
    # Pick call at least MIN_OTM_PERCENT above spot for safer directional bet
    min_strike = spot * (1 + MIN_OTM_PERCENT / 100)
    calls_above_target = calls_sorted[calls_sorted['strike'] >= min_strike]
    
    if calls_above_target.empty:
        # fallback: pick nearest OTM call
        calls_above = calls_sorted[calls_sorted['strike'] >= spot]
        if calls_above.empty:
            call = calls_sorted.iloc[-1]
        else:
            call = calls_above.iloc[0]
    else:
        # Pick strike closest to target OTM level
        call = calls_above_target.iloc[0]

    ask = float(call.get('ask', 0.0) or call.get('lastPrice', 0.0) or 0.0)
    strike = float(call['strike'])
    
    # If no pricing data, skip
    if ask == 0.0:
        return {'symbol': symbol, 'error': 'no pricing data available for options'}

    # Get IV with fallback to historical volatility and 15% floor
    iv = float(call.get('impliedVolatility', 0.0) or 0.0)
    hist_vol = estimate_historical_vol(t, days=30)
    sigma = max(iv, hist_vol, 0.15)  # Use max for realistic volatility
    
    iv_fallback = (iv == 0.0 or iv < hist_vol)
    fetched_at = datetime.utcnow().isoformat() + 'Z'
    iv_source_detail = ('historical: computed from 30-day close returns' if iv_fallback
                        else 'implied: taken from option chain')

    # For long call: risk is losing full premium, but upside unlimited
    # Risk score based on distance to strike (closer = lower risk)
    if spot:
        strike_distance_pct = ((strike - spot) / spot) * 100.0
        risk_score = min(100, max(0, 100 - strike_distance_pct * 3))  # OTM = higher risk
    else:
        risk_score = 50.0

    # Calculate probability using risk-neutral drift: P(S_T > K)
    exp_date = datetime.strptime(expiry, '%Y-%m-%d').date()
    dt = (exp_date - date.today()).days
    T = days_to_years(dt)
    
    iv = float(call.get('impliedVolatility', 0.0) or 0.0)
    hist_vol = estimate_historical_vol(t, days=90)
    sigma = blend_volatility(iv, hist_vol)
    
    # Get dividend-adjusted risk-free rate
    r_adj = get_adjusted_risk_free_rate(t)
    
    try:
        if sigma > 0 and spot:
            S = spot
            K_strike = strike
            
            # Risk-neutral drift
            drift = r_adj - 0.5 * sigma * sigma
            sigma_sqrt_T = sigma * np.sqrt(T)
            
            # P(Max Profit): P(S_T > K) - ITM at expiration
            Z_max = (np.log(S / K_strike) - drift * T) / sigma_sqrt_T
            prob_max_profit = norm_cdf(Z_max) * 100.0
            
            # P(Any Profit): P(S_T > K + premium_paid)
            K_breakeven = strike + ask
            Z_profit = (np.log(S / K_breakeven) - drift * T) / sigma_sqrt_T
            prob_any_profit = norm_cdf(Z_profit) * 100.0
        else:
            prob_max_profit = 50.0
            prob_any_profit = 50.0
    except Exception:
        prob_max_profit = 50.0
        prob_any_profit = 50.0
    
    # ROI: theoretical unlimited, use 100% as baseline
    roi = 100.0
    composite_score = calculate_composite_score(prob_any_profit, roi, risk_score)

    return {
        'symbol': symbol,
        'spot': spot,
        'expiry': expiry,
        'days_to_expiry': (datetime.strptime(expiry, '%Y-%m-%d').date() - date.today()).days,
        'strategy': 'Long Call',
        'short_strike': f"{strike:.2f}c",
        'long_strike': None,
        'credit': -round(ask * 100, 2),
        'max_profit': None,
        'max_loss': round(ask * 100, 2),
        'roi_percent': round(roi, 2),
        'probability_success_percent': round(prob_any_profit, 1),
        'prob_max_profit': round(prob_max_profit, 1),
        'breakeven': round(K_breakeven, 2) if 'K_breakeven' in locals() else round(strike + ask, 2),
        'composite_score': composite_score,
        'risk_score': round(risk_score, 1),
        'rsi': current_rsi,
        'data_timestamp': fetched_at,
        'price_timestamp': price_timestamp,
        'data_source': DATA_PROVIDER,
        'iv_used': round(float(sigma), 4),
        'hv_used': round(float(hist_vol), 4),
        'iv_source': 'blended (70% IV + 30% HV, 60-90 day)',
    }


def bull_call_spread(symbol, expiry=None):
    # buy lower strike call, sell higher strike call
    t = yf.Ticker(symbol)
    
    # Calculate RSI
    current_rsi = get_current_rsi(t)
    
    try:
        hist = t.history(period='2d')
        spot = float(hist['Close'].iloc[-1])
        try:
            price_timestamp = hist.index[-1].to_pydatetime().isoformat() + 'Z'
        except Exception:
            price_timestamp = None
    except Exception:
        spot = None
        price_timestamp = None

    exps = t.options
    if not exps:
        return {'symbol': symbol, 'error': 'no options available'}

    if expiry is None:
        expiry = exps[0]
    try:
        opt = t.option_chain(expiry)
        calls = opt.calls
    except Exception:
        return {'symbol': symbol, 'error': 'failed to fetch option chain'}

    calls_sorted = calls.sort_values('strike')
    # Choose strikes with adequate OTM distance and spread width
    min_low_strike = spot * (1 + MIN_OTM_PERCENT / 100)
    calls_above_target = calls_sorted[calls_sorted['strike'] >= min_low_strike]
    
    if len(calls_above_target) >= 2:
        low = calls_above_target.iloc[0]
        # Find high strike for adequate spread width
        target_high_strike = float(low['strike']) + MIN_SPREAD_WIDTH_DOLLARS
        calls_for_high = calls_sorted[calls_sorted['strike'] > float(low['strike'])]
        if not calls_for_high.empty:
            calls_for_high['distance'] = abs(calls_for_high['strike'] - target_high_strike)
            high = calls_for_high.loc[calls_for_high['distance'].idxmin()]
        else:
            high = calls_above_target.iloc[1] if len(calls_above_target) > 1 else calls_sorted.iloc[-1]
    else:
        # fallback: choose first two strikes above spot
        idxs = calls_sorted.index[calls_sorted['strike'] >= spot]
        if len(idxs) >= 2:
            low = calls_sorted.loc[idxs[0]]
            high = calls_sorted.loc[idxs[1]]
        else:
            low = calls_sorted.iloc[-2]
            high = calls_sorted.iloc[-1]

    buy_ask = float(low.get('ask', 0.0) or low.get('lastPrice', 0.0) or 0.0)
    sell_bid = float(high.get('bid', 0.0) or high.get('lastPrice', 0.0) or 0.0)
    
    # If no pricing data, skip
    if buy_ask == 0.0 or sell_bid == 0.0:
        return {'symbol': symbol, 'error': 'no pricing data available for options'}
    
    debit = max(buy_ask - sell_bid, 0.0)
    strike_low = float(low['strike'])
    strike_high = float(high['strike'])
    strike_diff = strike_high - strike_low

    max_profit = strike_diff - debit
    max_loss = debit
    roi = (max_profit / max(1e-6, max_loss)) * 100.0 if max_loss > 0 else 0.0

    iv_low = float(low.get('impliedVol') or 0.0)
    iv_high = float(high.get('impliedVol') or 0.0)
    iv = iv_low if iv_low > 0 else (iv_high if iv_high > 0 else estimate_historical_vol(t, days=30))
    iv_fallback = False
    if iv == 0.0 or np.isnan(iv):
        iv = estimate_historical_vol(t, days=30)
        iv_fallback = True

    fetched_at = datetime.utcnow().isoformat() + 'Z'
    iv_source_detail = ('historical: computed from 30-day close returns' if iv_fallback
                        else 'implied: taken from option chain')

    # Risk score: distance of long strike from spot (closer = lower risk)
    if spot:
        strike_distance_pct = ((strike_low - spot) / spot) * 100.0
        risk_score = min(100, max(0, 100 - abs(strike_distance_pct) * 3))
    else:
        risk_score = 50.0

    # Probability: calculate using risk-neutral drift for long (buy) call strike
    # Bull call spread profits when spot > long strike at expiry
    hist_vol = estimate_historical_vol(t, days=90)
    sigma = blend_volatility(iv, hist_vol)
    
    # Get dividend-adjusted risk-free rate
    r_adj = get_adjusted_risk_free_rate(t)
    
    prob_max_profit = 50.0
    prob_any_profit = 50.0
    try:
        S = spot
        K_low = strike_low  # LONG (buy) strike
        K_high = strike_high  # SHORT (sell) strike
        T = max((datetime.strptime(expiry, '%Y-%m-%d').date() - date.today()).days / 365.0, 1e-6)
        
        if sigma <= 0:
            prob_max_profit = 50.0
            prob_any_profit = 50.0
        else:
            # Risk-neutral drift
            drift = r_adj - 0.5 * sigma * sigma
            sigma_sqrt_T = sigma * np.sqrt(T)
            
            # P(Max Profit): P(S_T > K_high) - above short strike
            Z_max = (np.log(S / K_high) - drift * T) / sigma_sqrt_T
            prob_max_profit = norm_cdf(Z_max) * 100.0
            
            # P(Any Profit): P(S_T > K_low + debit)
            K_breakeven = strike_low + debit
            Z_profit = (np.log(S / K_breakeven) - drift * T) / sigma_sqrt_T
            prob_any_profit = norm_cdf(Z_profit) * 100.0
    except Exception:
        prob_max_profit = 50.0
        prob_any_profit = 50.0
    
    composite_score = calculate_composite_score(prob_any_profit, roi, risk_score)

    return {
        'symbol': symbol,
        'spot': spot,
        'expiry': expiry,
        'days_to_expiry': (datetime.strptime(expiry, '%Y-%m-%d').date() - date.today()).days,
        'strategy': 'Bull Call Spread',
        'short_strike': f"{strike_high:.2f}c",
        'long_strike': f"{strike_low:.2f}c",
        'credit': -round(debit * 100, 2),
        'max_profit': round(max_profit * 100, 2),
        'max_loss': round(max_loss * 100, 2),
        'roi_percent': round(roi, 2),
        'probability_success_percent': round(prob_any_profit, 1),
        'prob_max_profit': round(prob_max_profit, 1),
        'breakeven': round(K_breakeven, 2) if 'K_breakeven' in locals() else round(strike_low + debit, 2),
        'composite_score': composite_score,
        'risk_score': round(risk_score, 1),
        'rsi': current_rsi,
        'data_timestamp': fetched_at,
        'price_timestamp': price_timestamp,
        'data_source': DATA_PROVIDER,
        'iv_used': round(float(sigma), 4),
        'hv_used': round(float(hist_vol), 4),
        'iv_source': 'blended (70% IV + 30% HV, 60-90 day)',
    }


def iron_condor(symbol, expiry=None):
    # combine a bull put spread and a bear call spread with one strike gap
    t = yf.Ticker(symbol)
    
    # Calculate RSI
    current_rsi = get_current_rsi(t)
    
    try:
        hist = t.history(period='2d')
        spot = float(hist['Close'].iloc[-1])
    except Exception:
        spot = None

    exps = t.options
    if not exps:
        return {'symbol': symbol, 'error': 'no options available'}

    if expiry is None:
        expiry = exps[0]
    try:
        opt = t.option_chain(expiry)
        puts = opt.puts.sort_values('strike')
        calls = opt.calls.sort_values('strike')
    except Exception:
        return {'symbol': symbol, 'error': 'failed to fetch option chain'}

    # Iron condor: pick strikes with adequate OTM distance for safer, higher probability trades
    # Short strikes should be at least MIN_OTM_PERCENT away from current price
    min_put_strike = spot * (1 - MIN_OTM_PERCENT / 100)
    min_call_strike = spot * (1 + MIN_OTM_PERCENT / 100)
    
    puts_below_target = puts[puts['strike'] <= min_put_strike]
    if len(puts_below_target) >= 2:
        # Pick highest strike below target for short put
        short_put = puts_below_target.iloc[-1]
        # Pick one more strike below for long put (adds spread width)
        target_long_put = float(short_put['strike']) - MIN_SPREAD_WIDTH_DOLLARS
        puts_for_long = puts[puts['strike'] < float(short_put['strike'])]
        if not puts_for_long.empty:
            puts_for_long_copy = puts_for_long.copy()
            puts_for_long_copy['distance'] = abs(puts_for_long_copy['strike'] - target_long_put)
            long_put = puts_for_long_copy.loc[puts_for_long_copy['distance'].idxmin()]
        else:
            long_put = puts_below_target.iloc[-2] if len(puts_below_target) > 1 else puts.iloc[0]
    else:
        # Fallback: use strikes below spot
        puts_below = puts[puts['strike'] < spot]
        if len(puts_below) >= 2:
            short_put = puts_below.iloc[-1]
            long_put = puts_below.iloc[-2]
        else:
            short_put = puts.iloc[0]
            long_put = puts.iloc[1]

    calls_above_target = calls[calls['strike'] >= min_call_strike]
    if len(calls_above_target) >= 2:
        # Pick lowest strike above target for short call
        short_call = calls_above_target.iloc[0]
        # Pick one more strike above for long call (adds spread width)
        target_long_call = float(short_call['strike']) + MIN_SPREAD_WIDTH_DOLLARS
        calls_for_long = calls[calls['strike'] > float(short_call['strike'])]
        if not calls_for_long.empty:
            calls_for_long_copy = calls_for_long.copy()
            calls_for_long_copy['distance'] = abs(calls_for_long_copy['strike'] - target_long_call)
            long_call = calls_for_long_copy.loc[calls_for_long_copy['distance'].idxmin()]
        else:
            long_call = calls_above_target.iloc[1] if len(calls_above_target) > 1 else calls.iloc[-1]
    else:
        # Fallback: use strikes above spot
        calls_above = calls[calls['strike'] > spot]
        if len(calls_above) >= 2:
            short_call = calls_above.iloc[0]
            long_call = calls_above.iloc[1]
        else:
            short_call = calls.iloc[-2]
            long_call = calls.iloc[-1]

    # Get pricing with fallback to lastPrice
    short_put_bid = float(short_put.get('bid', 0.0) or short_put.get('lastPrice', 0.0) or 0.0)
    long_put_ask = float(long_put.get('ask', 0.0) or long_put.get('lastPrice', 0.0) or 0.0)
    short_call_bid = float(short_call.get('bid', 0.0) or short_call.get('lastPrice', 0.0) or 0.0)
    long_call_ask = float(long_call.get('ask', 0.0) or long_call.get('lastPrice', 0.0) or 0.0)
    
    # If no pricing data, skip
    if short_put_bid == 0.0 or long_put_ask == 0.0 or short_call_bid == 0.0 or long_call_ask == 0.0:
        return {'symbol': symbol, 'error': 'no pricing data available for options'}
    
    put_credit = max(short_put_bid - long_put_ask, 0.0)
    call_credit = max(short_call_bid - long_call_ask, 0.0)
    net_credit = put_credit + call_credit

    put_width = abs(float(short_put['strike']) - float(long_put['strike']))
    call_width = abs(float(long_call['strike']) - float(short_call['strike']))
    max_loss = max(put_width - put_credit, call_width - call_credit)
    roi = (net_credit / max(1e-6, max_loss)) * 100.0 if max_loss > 0 else 0.0

    try:
        price_timestamp = hist.index[-1].to_pydatetime().isoformat() + 'Z'
    except Exception:
        price_timestamp = None
    fetched_at = datetime.utcnow().isoformat() + 'Z'
    iv_source_detail = 'mixed: implied where available, historical otherwise'

    # Calculate probability using Black-Scholes
    # Probability stock stays between short strikes: P(short_put < S_T < short_call)
    exp_date = datetime.strptime(expiry, '%Y-%m-%d').date()
    dt = (exp_date - date.today()).days
    T = days_to_years(dt)
    
    # For very short-term expiries (< 1 day), use simple distance-based probability
    if dt < 1:
        # Same-day expiry: use current position relative to strikes
        if spot:
            K_put = float(short_put['strike'])
            K_call = float(short_call['strike'])
            
            # If already outside the range, probability is ~0
            if spot <= K_put or spot >= K_call:
                prob_success = 5.0  # Small chance
            else:
                # Inside range: estimate based on distance to strikes
                range_width = K_call - K_put
                distance_to_put = spot - K_put
                distance_to_call = K_call - spot
                min_distance = min(distance_to_put, distance_to_call)
                # Higher probability if centered in range
                prob_success = min(95.0, 50.0 + (min_distance / range_width) * 40.0)
        else:
            prob_success = 50.0
    else:
        # Advanced probability calculation with blended volatility and risk-neutral drift
        # Get strike-specific implied volatilities
        iv_short_put = float(short_put.get('impliedVolatility', 0.0) or 0.0)
        iv_long_put = float(long_put.get('impliedVolatility', 0.0) or 0.0)
        iv_short_call = float(short_call.get('impliedVolatility', 0.0) or 0.0)
        iv_long_call = float(long_call.get('impliedVolatility', 0.0) or 0.0)
        
        # Calculate historical volatility (60-90 day window for stability)
        hist_vol = estimate_historical_vol(t, days=90)
        
        # Use strike-specific IVs for put and call sides
        iv_put = iv_short_put if iv_short_put > 0 else (iv_long_put if iv_long_put > 0 else 0)
        iv_call = iv_short_call if iv_short_call > 0 else (iv_long_call if iv_long_call > 0 else 0)
        
        # Blend IV and HV (70% IV, 30% HV) for each side
        sigma_put = blend_volatility(iv_put, hist_vol)
        sigma_call = blend_volatility(iv_call, hist_vol)
        
        # Calculate volatility skew adjustment (put vol typically > call vol)
        ivs = [iv for iv in [iv_short_put, iv_long_put, iv_short_call, iv_long_call] if iv > 0]
        if ivs:
            avg_iv = np.mean(ivs)
            skew_factor = 1.0 + (max(ivs) - min(ivs)) * 0.5  # Skew adjustment
        else:
            avg_iv = hist_vol
            skew_factor = 1.0
        
        # Apply skew and floor
        sigma_put_final = max(sigma_put * skew_factor, MIN_VOL_FLOOR)
        sigma_call_final = max(sigma_call * skew_factor, MIN_VOL_FLOOR)
        
        # Get dividend-adjusted risk-free rate
        r_adj = get_adjusted_risk_free_rate(t)
        
        try:
            if spot and sigma_put_final > 0 and sigma_call_final > 0:
                S = spot
                K_put = float(short_put['strike'])
                K_call = float(short_call['strike'])
                
                # Risk-neutral drift: μ = r - 0.5σ²
                drift_put = r_adj - 0.5 * sigma_put_final * sigma_put_final
                drift_call = r_adj - 0.5 * sigma_call_final * sigma_call_final
                
                # Time-adjusted volatility
                sigma_put_sqrt_T = sigma_put_final * np.sqrt(T)
                sigma_call_sqrt_T = sigma_call_final * np.sqrt(T)
                
                # CORRECTED Z-score formula: Z = [ln(K/S) - (r - 0.5σ²)T] / (σ√T)
                # Note: For lower bound (put), we want P(S_T < K_put)
                # For upper bound (call), we want P(S_T > K_call)
                Z_put = (np.log(K_put / S) - drift_put * T) / sigma_put_sqrt_T
                Z_call = (np.log(K_call / S) - drift_call * T) / sigma_call_sqrt_T
                
                # P(Max Profit): Probability of staying in range
                P_lower = norm_cdf(Z_put)  # P(S_T < K_put)
                P_upper = 1.0 - norm_cdf(Z_call)  # P(S_T > K_call)
                prob_max_profit = (1.0 - (P_lower + P_upper)) * 100.0
                
                # P(Any Profit): Adjust strikes by net credit received
                # Put side break-even: K_put - net_credit
                # Call side break-even: K_call + net_credit
                K_put_breakeven = K_put - net_credit
                K_call_breakeven = K_call + net_credit
                
                Z_put_profit = (np.log(K_put_breakeven / S) - drift_put * T) / sigma_put_sqrt_T
                Z_call_profit = (np.log(K_call_breakeven / S) - drift_call * T) / sigma_call_sqrt_T
                
                P_lower_profit = norm_cdf(Z_put_profit)
                P_upper_profit = 1.0 - norm_cdf(Z_call_profit)
                prob_any_profit = (1.0 - (P_lower_profit + P_upper_profit)) * 100.0
                
                # Use prob_any_profit as main probability (more realistic)
                prob_success = prob_any_profit
                
                # No arbitrary cap - let the math speak
                # Only ensure it's within valid range
                prob_success = min(100.0, max(0.0, prob_success))
                prob_max_profit = min(100.0, max(0.0, prob_max_profit))
                
                # Debug logging
                print(f"IC {symbol}: Spot=${S:.2f} | Strikes: ${K_put:.0f}-${K_call:.0f} | Range: ${K_call - K_put:.2f} ({((K_call-K_put)/S)*100:.1f}%) | Prob(Profit): {prob_success:.1f}% | Prob(Max): {prob_max_profit:.1f}% | σ_put: {sigma_put_final:.3f} | σ_call: {sigma_call_final:.3f} | Days: {dt}")
            else:
                prob_success = 50.0
                prob_max_profit = 50.0
        except Exception as e:
            print(f"Error calculating probability for {symbol}: {e}")
            prob_success = 50.0
            prob_max_profit = 50.0

    # Risk score: average distance of short strikes from spot
    if spot:
        put_distance = ((spot - float(short_put['strike'])) / spot) * 100.0
        call_distance = ((float(short_call['strike']) - spot) / spot) * 100.0
        avg_distance = (put_distance + call_distance) / 2.0
        risk_score = min(100, max(0, avg_distance * 3))
    else:
        risk_score = 50.0

    # Composite score calculation using prob_any_profit
    composite_score = calculate_composite_score(prob_success, roi, risk_score)

    return {
        'symbol': symbol,
        'spot': spot,
        'expiry': expiry,
        'days_to_expiry': (datetime.strptime(expiry, '%Y-%m-%d').date() - date.today()).days,
        'strategy': 'Iron Condor',
        'short_strike': f"{float(short_put['strike']):.2f}p / {float(short_call['strike']):.2f}c",
        'long_strike': f"{float(long_put['strike']):.2f}p / {float(long_call['strike']):.2f}c",
        'credit': round(net_credit * 100, 2),
        'max_profit': round(net_credit * 100, 2),
        'max_loss': round(max_loss * 100, 2),
        'roi_percent': round(roi, 2),
        'probability_success_percent': round(prob_success, 1),  # P(Profit > 0)
        'prob_max_profit': round(prob_max_profit, 1) if 'prob_max_profit' in locals() else round(prob_success, 1),  # P(Max Profit)
        'breakeven_lower': round(float(short_put['strike']) - net_credit, 2),
        'breakeven_upper': round(float(short_call['strike']) + net_credit, 2),
        'composite_score': composite_score,
        'risk_score': round(risk_score, 1),
        'rsi': current_rsi,
        'data_timestamp': fetched_at,
        'price_timestamp': price_timestamp,
        'data_source': DATA_PROVIDER,
        'historical_vol': round(estimate_historical_vol(t, days=30), 4),
        'iv_used': round(float(avg_iv), 4) if 'avg_iv' in locals() else None,
        'iv_source': 'mixed',
        'iv_source_detail': iv_source_detail
    }


# Authentication Routes
@app.route('/login')
def login():
    if 'user' in session:
        return redirect(url_for('index'))
    
    # If OAuth not configured, show setup instructions
    if not OAUTH_CONFIGURED:
        return render_template('login.html', oauth_configured=False)
    
    return render_template('login.html', oauth_configured=True)


@app.route('/auth/google')
def auth_google():
    if not OAUTH_CONFIGURED:
        return redirect(url_for('login'))
    
    redirect_uri = url_for('auth_callback', _external=True)
    return google.authorize_redirect(redirect_uri)


@app.route('/auth/callback')
def auth_callback():
    if not OAUTH_CONFIGURED:
        return redirect(url_for('login'))
    
    try:
        token = google.authorize_access_token()
        user_info = token.get('userinfo')
        
        if user_info:
            session['user'] = {
                'email': user_info.get('email'),
                'name': user_info.get('name'),
                'picture': user_info.get('picture')
            }
            return redirect(url_for('index'))
        else:
            return redirect(url_for('login'))
    except Exception as e:
        print(f"Auth error: {e}")
        return redirect(url_for('login'))


@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))


@app.route('/')
@login_required
def index():
    return render_template('index.html', user=session.get('user'))


@app.route('/chart')
@login_required
def chart():
    return render_template('chart.html')


@app.route('/api/analyze', methods=['POST'])
@login_required
def api_analyze():
    data = request.get_json() or {}
    symbols = data.get('symbols') or []
    max_days = data.get('max_days', 21)  # default 21 days (3 weeks)
    top_n = data.get('top_n', 20)        # default top 20 results (increased to show more high-probability trades)
    
    # Get configurable OTM and spread percentages from request
    global MIN_OTM_PERCENT, MIN_SPREAD_WIDTH_DOLLARS
    MIN_OTM_PERCENT = float(data.get('otm_percent', 2.5))
    MIN_SPREAD_WIDTH_DOLLARS = float(data.get('spread_width', 5.0))
    
    if isinstance(symbols, str):
        symbols = [symbols]

    results = []
    for s in symbols:
        try:
            r = analyze_all_strategies(s.strip().upper(), max_days=max_days, top_n=top_n)
        except Exception as e:
            r = {'symbol': s, 'error': str(e), 'strategies': []}
        results.append(r)

    return jsonify({'results': results})


@app.route('/api/chart/<symbol>', methods=['GET'])
@login_required
def api_chart(symbol):
    """Get chart data with technical indicators"""
    period = request.args.get('period', '3y')  # default 3 years
    
    # Map period to yfinance period format
    period_map = {
        '1d': '1d',
        '5d': '5d',
        '1mo': '1mo',
        '3mo': '3mo',
        '6mo': '6mo',
        '1y': '1y',
        '2y': '2y',
        '3y': '3y'
    }
    
    yf_period = period_map.get(period, '3y')
    
    try:
        ticker = yf.Ticker(symbol.upper())
        
        # Get historical data
        hist = ticker.history(period=yf_period)
        
        if hist.empty:
            return jsonify({'error': 'No data available for symbol'}), 404
        
        # Calculate technical indicators
        close_prices = hist['Close']
        
        # RSI
        rsi = calculate_rsi(close_prices)
        
        # Bollinger Bands
        sma, upper_band, lower_band = calculate_bollinger_bands(close_prices)
        
        # Intrinsic value (constant line)
        intrinsic, intrinsic_breakdown = estimate_intrinsic_value(ticker)
        
        # Current price
        current_price = float(close_prices.iloc[-1])
        
        # Prepare data for JSON
        dates = [d.isoformat() for d in hist.index]
        
        chart_data = {
            'symbol': symbol.upper(),
            'period': period,
            'current_price': round(current_price, 2),
            'intrinsic_value': round(intrinsic, 2) if intrinsic else None,
            'intrinsic_breakdown': intrinsic_breakdown,
            'dates': dates,
            'prices': [round(float(p), 2) for p in close_prices],
            'volume': [int(v) for v in hist['Volume']],
            'rsi': [round(float(r), 2) if not pd.isna(r) else None for r in rsi],
            'bollinger_upper': [round(float(b), 2) if not pd.isna(b) else None for b in upper_band],
            'bollinger_middle': [round(float(b), 2) if not pd.isna(b) else None for b in sma],
            'bollinger_lower': [round(float(b), 2) if not pd.isna(b) else None for b in lower_band],
            'data_timestamp': datetime.utcnow().isoformat() + 'Z',
            'data_source': DATA_PROVIDER
        }
        
        # Add company info
        try:
            info = ticker.info
            chart_data['company_name'] = info.get('longName', symbol.upper())
            chart_data['sector'] = info.get('sector', 'N/A')
            chart_data['industry'] = info.get('industry', 'N/A')
        except Exception:
            chart_data['company_name'] = symbol.upper()
        
        return jsonify(chart_data)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# API Key Authentication
API_KEY = os.environ.get('API_KEY', 'dev-api-key-change-in-production')

def require_api_key(f):
    """Decorator to require API key for external API endpoints"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Get API key from header or query parameter
        api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
        
        if not api_key or api_key != API_KEY:
            return jsonify({
                'error': 'Unauthorized',
                'message': 'Invalid or missing API key. Include X-API-Key header or api_key parameter.'
            }), 401
        
        return f(*args, **kwargs)
    return decorated_function


@app.route('/api/webhook/analyze', methods=['POST', 'OPTIONS'])
@require_api_key
def webhook_analyze():
    """
    Webhook endpoint for external apps (like Bubble) to analyze options strategies.
    
    Expected JSON payload:
    {
        "symbols": ["AAPL", "MSFT", "GOOGL"],
        "max_days": 21,
        "top_n": 20,
        "otm_percent": 2.5,
        "spread_width": 5,
        "filters": {
            "min_roi": 10,
            "min_probability": 40,
            "max_rsi": 70
        }
    }
    
    Returns: Same format as /api/analyze endpoint
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400
        
        symbols = data.get('symbols', [])
        if not symbols:
            return jsonify({'error': 'symbols array is required'}), 400
        
        max_days = data.get('max_days', 21)
        top_n = data.get('top_n', 20)
        otm_percent = data.get('otm_percent', 2.5)
        spread_width = data.get('spread_width', 5)
        
        # Call the existing analyze logic
        results = analyze_symbols(symbols, max_days, otm_percent, spread_width)
        
        # Apply filters if provided
        filters = data.get('filters', {})
        if filters:
            min_roi = filters.get('min_roi', 0)
            min_probability = filters.get('min_probability', 0)
            max_rsi = filters.get('max_rsi', 100)
            
            # Filter results
            for symbol_data in results:
                if 'strategies' in symbol_data:
                    symbol_data['strategies'] = [
                        s for s in symbol_data['strategies']
                        if (s.get('roi_percent', 0) >= min_roi and
                            s.get('probability_success_percent', 0) >= min_probability and
                            (s.get('rsi') is None or s.get('rsi', 0) <= max_rsi))
                    ][:top_n]
        
        return jsonify({
            'success': True,
            'results': results,
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }), 500


@app.route('/api/webhook/single-strategy', methods=['POST', 'OPTIONS'])
@require_api_key
def webhook_single_strategy():
    """
    Webhook to analyze a specific strategy for a single symbol.
    
    Expected JSON payload:
    {
        "symbol": "AAPL",
        "strategy": "iron_condor",  // or "bull_put", "bear_call", "covered_call", etc.
        "max_days": 21,
        "otm_percent": 2.5,
        "spread_width": 5
    }
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400
        
        symbol = data.get('symbol', '').upper()
        strategy_type = data.get('strategy', '').lower()
        
        if not symbol:
            return jsonify({'error': 'symbol is required'}), 400
        if not strategy_type:
            return jsonify({'error': 'strategy is required'}), 400
        
        max_days = data.get('max_days', 21)
        otm_percent = data.get('otm_percent', 2.5)
        spread_width = data.get('spread_width', 5)
        
        # Get stock data
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period='3mo')
        
        if hist.empty:
            return jsonify({'error': f'No data found for {symbol}'}), 404
        
        spot = float(hist['Close'].iloc[-1])
        
        # Get options data
        try:
            expirations = ticker.options
            if not expirations:
                return jsonify({'error': f'No options data for {symbol}'}), 404
        except Exception:
            return jsonify({'error': f'No options available for {symbol}'}), 404
        
        # Call appropriate strategy function
        strategy_map = {
            'bull_put': analyze_bull_put_spread,
            'bear_call': analyze_bear_call_spread,
            'iron_condor': analyze_iron_condor,
            'covered_call': analyze_covered_call,
            'cash_put': analyze_cash_secured_put,
            'long_call': analyze_long_call,
            'bull_call': analyze_bull_call_spread
        }
        
        if strategy_type not in strategy_map:
            return jsonify({
                'error': f'Invalid strategy. Choose from: {", ".join(strategy_map.keys())}'
            }), 400
        
        strategy_func = strategy_map[strategy_type]
        result = strategy_func(symbol, ticker, spot, expirations, max_days, otm_percent, spread_width)
        
        return jsonify({
            'success': True,
            'symbol': symbol,
            'strategy': strategy_type,
            'result': result,
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }), 500


@app.route('/api/generate-key', methods=['POST'])
def generate_api_key():
    """
    Generate a new API key for development/testing.
    In production, this should be protected or removed.
    """
    new_key = secrets.token_urlsafe(32)
    return jsonify({
        'api_key': new_key,
        'message': 'Add this to your .env file as API_KEY=<key>',
        'note': 'Store this securely - it will not be shown again'
    })


if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_ENV') != 'production'
    app.run(debug=debug, host='0.0.0.0', port=port)
