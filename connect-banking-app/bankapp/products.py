"""
products.py
===========
The mortgage products the application form lists: the mortgage service's own illustrative catalogue
(connect-livesync-mortgage backend/src/products.js), the same list its assistant reads through
listEligibleProducts. Rates are examples, not offers. Keep the two the same.
"""

PRODUCTS = [
    {"id": "FX2-999", "name": "2 year fixed", "fixedTermYears": 2, "rate": 4.19, "fee": 999, "maxLtv": 90},
    {"id": "FX2-NF", "name": "2 year fixed, no fee", "fixedTermYears": 2, "rate": 4.49, "fee": 0, "maxLtv": 90},
    {"id": "FX5-999", "name": "5 year fixed", "fixedTermYears": 5, "rate": 4.09, "fee": 999, "maxLtv": 90},
    {"id": "FX5-NF", "name": "5 year fixed, no fee", "fixedTermYears": 5, "rate": 4.29, "fee": 0, "maxLtv": 90},
    {"id": "FX5-95", "name": "5 year fixed, 95% LTV", "fixedTermYears": 5, "rate": 4.79, "fee": 0, "maxLtv": 95},
]
