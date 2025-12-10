# Probability Calculation Guide

## Overview
This document explains the comprehensive probability calculation methodology implemented in the options analysis application.

## Key Changes Implemented

### 1. ✅ Updated Z-Score Formula
**OLD Formula:**
```
Z = ln(K/S) / (σ√T)
```

**NEW Formula (Risk-Neutral Drift):**
```
Z = [ln(K/S) - (r - 0.5σ²)T] / (σ√T)
```

Where:
- `r = 0.045` (4.5% risk-free rate - approximate 10Y Treasury)
- `r_adj = r - dividend_yield` (dividend-adjusted when applicable)
- `μ = r - 0.5σ²` (risk-neutral drift)

### 2. ✅ Enhanced Volatility Calculation
**OLD:**
- 30-day historical volatility
- Simple max(IV, HV, 0.15)

**NEW:**
- **60-90 day historical volatility** (more stable estimates)
- **Blended volatility:** `σ = 0.7 * IV + 0.3 * HV`
- **Smart blending:** When IV < 10%, use `σ = 0.2 * IV + 0.8 * HV` (trust HV more)
- **Strike-specific IV** for iron condors (separate put/call side IVs)
- **Volatility floor:** `max(blended_σ, 0.20)` (20% minimum for realistic stock options)

### 3. ✅ Time Calculation
**Confirmed:** Using calendar days
```python
T = days_to_expiration / 365.0
```
(NOT 252 trading days)

### 4. ✅ Dual Probability Calculations
Each strategy now reports **TWO probabilities:**

#### P(Max Profit)
- Probability of achieving maximum theoretical profit
- Uses actual strike prices
- Example: Bull Put Spread → P(S_T > K_short)

#### P(Profit > 0)
- Probability of any profit (break-even probability)
- **Adjusts strikes by premium received/paid**
- Examples:
  - Sell $465 put for $5 → P(Profit) uses K=$460
  - Sell $490 call for $3 → P(Profit) uses K=$493
  - Bull Put Spread $460-$465 for $2 credit → P(Profit) uses K=$463
  - Iron Condor: Adjusts both put and call sides by net credit

**Primary Metric:** `P(Profit > 0)` is used for composite score (more realistic)

### 5. ✅ Removed 95% Probability Cap
**OLD:** `prob = min(95.0, calculated_prob)`

**NEW:** No artificial cap
```python
prob = min(100.0, max(0.0, calculated_prob))
```
- Only ensures valid range (0-100%)
- Let the math speak - no arbitrary limitations
- More realistic probabilities (expect 20-60% range for most trades)

### 6. ✅ Dividend Adjustment
**NEW Function:**
```python
def get_adjusted_risk_free_rate(ticker):
    """r_adj = r - dividend_yield"""
    div_yield = get_dividend_yield(ticker)
    return RISK_FREE_RATE - div_yield
```
- Automatically adjusts risk-free rate for dividend-paying stocks
- More accurate pricing for high-dividend stocks

### 7. ✅ Risk-Free Rate Constant
```python
RISK_FREE_RATE = 0.045  # 4.5% - current Fed funds rate
```
**Recommendation:** Update quarterly as Fed rates change

## Strategy-Specific Implementations

### Bull Put Spread
```python
# P(Max Profit): P(S_T > K_short)
Z_max = (ln(S/K_short) - drift*T) / (σ√T)
prob_max = Φ(Z_max)

# P(Profit): P(S_T > K_short - credit)
K_breakeven = K_short - credit
Z_profit = (ln(S/K_breakeven) - drift*T) / (σ√T)
prob_profit = Φ(Z_profit)
```

### Bear Call Spread
```python
# P(Max Profit): P(S_T < K_short)
Z_max = (ln(K_short/S) - drift*T) / (σ√T)
prob_max = Φ(Z_max)

# P(Profit): P(S_T < K_short + credit)
K_breakeven = K_short + credit
Z_profit = (ln(K_breakeven/S) - drift*T) / (σ√T)
prob_profit = Φ(Z_profit)
```

### Iron Condor
```python
# Separate volatilities for put and call sides
σ_put = blend_volatility(IV_short_put, HV)
σ_call = blend_volatility(IV_short_call, HV)

# Apply volatility skew adjustment
skew_factor = 1.0 + (max(IVs) - min(IVs)) * 0.5
σ_put_final = max(σ_put * skew_factor, 0.20)
σ_call_final = max(σ_call * skew_factor, 0.20)

# P(Max Profit): P(K_put < S_T < K_call)
Z_put = (ln(K_put/S) - drift_put*T) / (σ_put√T)
Z_call = (ln(K_call/S) - drift_call*T) / (σ_call√T)
P_lower = Φ(Z_put)  # P(S_T < K_put)
P_upper = 1 - Φ(Z_call)  # P(S_T > K_call)
prob_max = (1 - P_lower - P_upper) * 100

# P(Profit): Adjust strikes by net credit
K_put_BE = K_put - net_credit
K_call_BE = K_call + net_credit
# ... similar calculation with adjusted strikes
```

### Covered Call
```python
# P(Max Profit): P(S_T < K_short) - stock stays below strike
Z_max = (ln(K_short/S) - drift*T) / (σ√T)
prob_max = Φ(Z_max)

# P(Profit): P(S_T > spot - credit)
K_breakeven = spot - credit
Z_profit = (ln(K_breakeven/S) - drift*T) / (σ√T)
prob_profit = Φ(Z_profit)
```

### Cash Secured Put
```python
# P(Max Profit): P(S_T > K_short) - stock stays above strike
Z_max = (ln(S/K_short) - drift*T) / (σ√T)
prob_max = Φ(Z_max)

# P(Profit): P(S_T > K_short - credit)
K_breakeven = K_short - credit
Z_profit = (ln(S/K_breakeven) - drift*T) / (σ√T)
prob_profit = Φ(Z_profit)
```

### Long Call
```python
# P(Max Profit): P(S_T > K) - ITM at expiration
Z_max = (ln(S/K) - drift*T) / (σ√T)
prob_max = Φ(Z_max)

# P(Profit): P(S_T > K + premium_paid)
K_breakeven = K + premium_paid
Z_profit = (ln(S/K_breakeven) - drift*T) / (σ√T)
prob_profit = Φ(Z_profit)
```

### Bull Call Spread
```python
# P(Max Profit): P(S_T > K_high) - above short strike
Z_max = (ln(S/K_high) - drift*T) / (σ√T)
prob_max = Φ(Z_max)

# P(Profit): P(S_T > K_low + debit_paid)
K_breakeven = K_low + debit_paid
Z_profit = (ln(S/K_breakeven) - drift*T) / (σ√T)
prob_profit = Φ(Z_profit)
```

## Expected Results

### Before Changes
- MSFT iron condor: 92-95% probability (unrealistic)
- Narrow ranges showing high probabilities
- Yahoo Finance IV often 4-5% (unrealistic)

### After Changes
- MSFT iron condor: Expected 30-50% probability (realistic)
- Probabilities reflect true market risk
- 20% volatility floor prevents unrealistic low-vol scenarios
- Dual probabilities provide more complete picture

## Mathematical Foundation

### Risk-Neutral Pricing
- Uses risk-neutral measure (Q-measure) for option pricing
- Drift term: `μ = r - 0.5σ²` (not real-world drift)
- Consistent with Black-Scholes framework
- Accounts for volatility drag

### Cumulative Distribution Function
```python
Φ(z) = 0.5 * (1 + erf(z / √2))
```
Standard normal CDF for probability calculations

### Volatility Blending Rationale
- IV reflects forward-looking market expectations
- HV reflects actual historical price movement
- 70/30 blend balances both perspectives
- Smart blending detects unreliable IV data

## Data Sources

### Primary: Yahoo Finance
- Implied Volatility: `option_chain[strike]['impliedVolatility']`
- Strike-specific IVs for iron condors
- Historical prices for HV calculation

### Fallbacks
1. If IV unavailable → use HV only
2. If IV < 10% → weight HV at 80% (smart blending)
3. Always enforce 20% minimum floor

## Validation & Monitoring

### Debug Logging
Iron condor calculations include detailed logging:
```
IC MSFT: Spot=$477.73 | Strikes: $465-$490 | Range: $25.00 (5.2%) | 
Prob(Profit): 45.2% | Prob(Max): 38.1% | σ_put: 0.235 | σ_call: 0.228 | Days: 8
```

### Key Metrics to Watch
- Volatilities should be 15-40% for most stocks
- Probabilities should be 20-70% for reasonable trades
- Break-even points should align with common sense

## Maintenance

### Quarterly Updates
1. Update `RISK_FREE_RATE` to match current Fed funds rate
2. Review volatility floor (0.20) - may need seasonal adjustment
3. Validate against real market outcomes

### When Markets Change
- High VIX environment: May need higher vol floor
- Low VIX environment: Current settings appropriate
- Earnings season: Consider event-specific vol adjustments

## Technical Implementation

### All Strategies Updated
✅ Bull Put Spread
✅ Bear Call Spread  
✅ Covered Call
✅ Cash Secured Put
✅ Long Call
✅ Bull Call Spread
✅ Iron Condor

### New Response Fields
Each strategy now returns:
```json
{
  "probability_success_percent": 45.2,  // P(Profit > 0)
  "prob_max_profit": 38.1,              // P(Max Profit)
  "breakeven": 462.50,                  // Break-even price
  "iv_used": 0.2350,                    // Final blended volatility
  "hv_used": 0.2180,                    // Historical volatility (60-90 day)
  "iv_source": "blended (70% IV + 30% HV, 60-90 day)"
}
```

## References
- Black-Scholes Model
- Risk-Neutral Valuation
- Options Pricing Theory
- Volatility Surface Analysis

---

**Last Updated:** December 4, 2025
**Version:** 7.0 (Comprehensive Probability Overhaul)
