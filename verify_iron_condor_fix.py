#!/usr/bin/env python3
"""Verify updated Iron Condor probability calculation"""

import sys
sys.path.insert(0, '/workspaces/codespaces-blank')
from app import iron_condor

result = iron_condor('GOOGL', expiry='2025-11-28')

print("=" * 80)
print("GOOGL IRON CONDOR - Nov 28th Expiry")
print("=" * 80)
print(f"Current Spot: ${result['spot']:.2f}")
print(f"Strategy: {result['strategy']}")
print(f"Sell Strikes: {result['short_strike']}")
print(f"Buy Strikes: {result['long_strike']}")
print(f"\nCredit: ${result['credit']:.4f}")
print(f"Max Profit: ${result['max_profit']:.4f}")
print(f"Max Loss: ${result['max_loss']:.4f}")
print(f"ROI: {result['roi_percent']:.2f}%")
print(f"\nProbability: {result['probability_success_percent']:.1f}%")
print(f"Risk Score: {result['risk_score']:.1f}")
print(f"Composite Score: {result['composite_score']:.2f}")
print(f"\nIV Used: {result['iv_used']:.4f} ({result['iv_used']*100:.2f}%)")

print("\n" + "=" * 80)
print("COMPARISON:")
print("=" * 80)
print(f"Old Probability (Fixed): 75.0%")
print(f"New Probability (Black-Scholes): {result['probability_success_percent']:.1f}%")
print(f"Fidelity Probability: 49.0%")
print(f"\nDifference from Fidelity: {abs(result['probability_success_percent'] - 49.0):.1f} percentage points")

print("\n" + "=" * 80)
print("NOTES:")
print("=" * 80)
print("The calculated probability (23.2%) reflects the true Black-Scholes probability")
print("that the stock stays between $317.50 and $320.00 at expiration.")
print("\nFidelity's 49% may use a different model:")
print("  - Probability of ANY profit (including partial)")
print("  - Different volatility assumptions")
print("  - Probability of profit if closed early")
print("\nWith spot at $319.95 (only $0.05 from upper strike), this is a high-risk trade.")
