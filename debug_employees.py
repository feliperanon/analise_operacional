
import asyncio
from main import _employees_page_impl, update_vacation_statuses
from database import engine
from sqlmodel import Session
from fastapi import Request
from unittest.mock import MagicMock

async def run_debug():
    print("Starting debug...")
    try:
        # Mock Request
        mock_request = MagicMock(spec=Request)
        mock_request.session = {"user": "debug_admin"}
        mock_request.form = asyncio.Future
        mock_request.form.set_result({})

        # Real DB Session
        with Session(engine) as session:
            print("Session created. Calling implementation...")
            response = await _employees_page_impl(mock_request, session)
            print("Response Status:", response.status_code)
            # print("Response Body:", response.body) # might be bytes
    except Exception:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(run_debug())
