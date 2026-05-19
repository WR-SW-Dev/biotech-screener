#!/usr/bin/env python3
"""Test tastytrade credentials and API connectivity."""

import os
import sys

from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

print("=" * 70)
print("TASTYTRADE CREDENTIAL TEST")
print("=" * 70)

# Check environment variables
tt_secret = os.environ.get("TT_SECRET")
tt_refresh = os.environ.get("TT_REFRESH")

print("\n1. Environment Variables:")
print(f"   TT_SECRET:  {'✓ SET' if tt_secret else '✗ NOT SET'}")
print(f"   TT_REFRESH: {'✓ SET' if tt_refresh else '✗ NOT SET'}")

if not tt_secret or not tt_refresh:
    print("\n❌ FAILED: Missing required environment variables")
    sys.exit(1)

print(f"\n   TT_SECRET:  {tt_secret[:20]}...")
print(f"   TT_REFRESH: {tt_refresh[:50]}...")

# Test tastytrade library import
print("\n2. Testing tastytrade library import:")
try:
    from tastytrade import Session

    print("   ✓ tastytrade library imported successfully")
except ImportError as e:
    print(f"   ✗ Failed to import tastytrade: {e}")
    sys.exit(1)

# Test Session creation
print("\n3. Testing tastytrade Session creation:")
try:
    session = Session(is_test=False)
    print("   ✓ Session created successfully")
    print(f"   ✓ User ID: {session.user.id if hasattr(session, 'user') else 'N/A'}")
except Exception as e:
    print(f"   ✗ Session creation failed: {e}")
    import traceback

    traceback.print_exc()
    sys.exit(1)

# Test API call - get customer info
print("\n4. Testing API call (get customer info):")
try:
    customer = session.get_customer()
    print("   ✓ API call successful")
    print(f"   ✓ Customer ID: {customer.id if hasattr(customer, 'id') else 'N/A'}")
    print(f"   ✓ Session token valid: {bool(session.session_token)}")
    print(f"   ✓ Session expires: {session.session_expiration}")
except Exception as e:
    print(f"   ✗ API call failed: {e}")
    import traceback

    traceback.print_exc()

print("\n" + "=" * 70)
print("✅ TASTYTRADE CREDENTIALS TEST PASSED")
print("=" * 70)
