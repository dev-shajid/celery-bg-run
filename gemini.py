import asyncio
import os
import sys
from hyperbrowser import AsyncHyperbrowser
from hyperbrowser.models import CreateSessionParams
from browser_use.browser import BrowserProfile, BrowserSession

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv

from browser_use import Agent, ChatGoogle

load_dotenv()

api_key = os.getenv('GOOGLE_API_KEY')
if not api_key:
	raise ValueError('GOOGLE_API_KEY is not set')

llm = ChatGoogle(model='gemini-2.5-flash', api_key=api_key)


async def create_hyperbrowser_session() -> tuple[AsyncHyperbrowser | None, str | None]:
    """
    Create a Hyperbrowser client and session, returning (client, cdp_url).
    Returns (None, None) on any failure so caller can skip browser usage.
    """
    if True:
        return None, None

    HYPERBROWSER_API_KEY = os.getenv('HYPERBROWSER_API_KEY')
    if not HYPERBROWSER_API_KEY:
        raise ValueError('HYPERBROWSER_API_KEY is not set')

    client = AsyncHyperbrowser(api_key=HYPERBROWSER_API_KEY)
    try:
        session = await client.sessions.create(
            params=CreateSessionParams(use_stealth=True)
        )
        cdp_url = session.ws_endpoint
        if not cdp_url:
            await client.close()
            return None, None
        return client, cdp_url
    except Exception:
        # Best-effort cleanup on failure
        try:
            await client.close()
        except Exception:
            pass
        return None, None
    
async def run_search(task: str = 'give me price of samsung s24'):
    client: AsyncHyperbrowser | None = None
    browser_session: BrowserSession | None = None
    try:
        client, cdp_url = await create_hyperbrowser_session()

        profile = BrowserProfile()
        browser_session = BrowserSession(browser_profile=profile, cdp_url=cdp_url if client else None)
        print("🚀 Browser session started.")
        agent_kwargs = {"task": task, "llm": llm}
        if browser_session:
            agent_kwargs["browser_session"] = browser_session

        agent = Agent(**agent_kwargs)
        return await agent.run(max_steps=25)
    finally:
        if browser_session:
            try:
                await browser_session.kill()
            except Exception:
                pass
        if client:
            try:
                await client.close()
            except Exception:
                pass
        if browser_session or client:
            print("🔥 Browser session closed.")

if __name__ == '__main__':
    asyncio.run(run_search())