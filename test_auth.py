import asyncio
from httpx import AsyncClient
from backend.main import app

async def test():
    async with AsyncClient(app=app, base_url="http://test") as ac:
        resp = await ac.post("/api/auth/login", json={"username": "joyeaal", "password": "virat18"})
        print(resp.status_code)
        print(resp.text)

asyncio.run(test())
