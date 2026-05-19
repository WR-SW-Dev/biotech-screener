#!/usr/bin/env python3
"""Test tastytrade credentials with async API calls."""

import asyncio
import os
import sys

from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()


async def test_tastytrade():
    """Test tastytrade credentials with actual API call."""

    print("=" * 70)
    print("TASTYTRADE ASYNC API TEST")
    print("=" * 70)

    # Check environment variables
    tt_secret = os.environ.get("TT_SECRET")
    tt_refresh = os.environ.get("TT_REFRESH")

    print("\n1. Environment Variables:")
    print(f"   TT_SECRET:  {'✓ SET' if tt_secret else '✗ NOT SET'}")
    print(f"   TT_REFRESH: {'✓ SET' if tt_refresh else '✗ NOT SET'}")

    if not tt_secret or not tt_refresh:
        print("\n❌ FAILED: Missing required environment variables")
        return False

    # Test Session creation
    print("\n2. Creating tastytrade Session:")
    try:
        from tastytrade import Session

        session = Session(is_test=False)
        print("   ✓ Session created successfully")
    except Exception as e:
        print(f"   ✗ Session creation failed: {e}")
        return False

    # Test async API call
    print("\n3. Testing async API call (get customer):")
    try:
        customer = await session.get_customer()
        print("   ✓ API call successful")
        print(f"   ✓ Customer ID: {customer.id if hasattr(customer, 'id') else customer}")
        print(f"   ✓ Session token: {session.session_token[:20]}...")
        print(f"   ✓ Session expires: {session.session_expiration}")
    except Exception as e:
        print(f"   ✗ API call failed: {e}")
        import traceback

        traceback.print_exc()
        return False

    print("\n" + "=" * 70)
    print("✅ TASTYTRADE CREDENTIALS VERIFIED - ALL TESTS PASSED")
    print("=" * 70)
    return True


if __name__ == "__main__":
    result = asyncio.run(test_tastytrade())
    sys.exit(0 if result else 1)
