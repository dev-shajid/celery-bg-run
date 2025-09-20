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

HYPERBROWSER_API_KEY = os.getenv('HYPERBROWSER_API_KEY')
if not HYPERBROWSER_API_KEY:
	raise ValueError('HYPERBROWSER_API_KEY is not set')

api_key = os.getenv('GOOGLE_API_KEY')
if not api_key:
	raise ValueError('GOOGLE_API_KEY is not set')

llm = ChatGoogle(model='gemini-2.5-flash', api_key=api_key)


async def run_search(task: str = 'give me price of samsung s24'):
    try:
        client = AsyncHyperbrowser(api_key=HYPERBROWSER_API_KEY)
    
        # Create a Hyperbrowser session
        session = await client.sessions.create(
            params=CreateSessionParams(
                use_stealth=True,  # Enable stealth mode
            )
        )

        # Retrieve the CDP URL
        cdp_url = session.ws_endpoint
        if not cdp_url:
            raise ValueError("Failed to retrieve CDP URL from Hyperbrowser session.")

        # Set up the BrowserProfile and BrowserSession
        profile = BrowserProfile()
        browser_session = BrowserSession(browser_profile=profile, cdp_url=cdp_url)
        
        print("🚀 Browser session started.", session.live_url)
        
        agent = Agent(
            task=task,
            llm=llm,
            browser_session=browser_session,
        )

        return await agent.run(max_steps=25)
    finally:
        # Close the browser session
        await browser_session.kill()
        await client.close()
        print("🔥 Browser session closed.")


if __name__ == '__main__':
	asyncio.run(run_search())
