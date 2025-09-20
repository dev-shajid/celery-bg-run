"""
OpenAI Computer Use Assistant (CUA) Integration

This example demonstrates how to integrate OpenAI's Computer Use Assistant as a fallback
action when standard browser actions are insufficient to achieve the desired goal.
The CUA can perform complex computer interactions that might be difficult to achieve
through regular browser-use actions.
"""

import asyncio
import base64
import os
import sys
from io import BytesIO
from time import time
from hyperbrowser import AsyncHyperbrowser
from hyperbrowser.models import CreateSessionParams
from PIL import Image
from dotenv import load_dotenv

from browser_use.browser.events import NavigateToUrlEvent
import logging
from pathlib import Path

PROMPT_FILE = Path(__file__).resolve().with_name("vision_system_prompt.md")

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


load_dotenv()
logger = logging.getLogger(__name__)

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from browser_use import Agent, ChatGoogle, Tools
from browser_use.agent.views import ActionResult
from browser_use.tools.views import SendKeysAction
from browser_use.browser import BrowserSession
from browser_use.browser.events import SendKeysEvent


class OpenAICUAAction(BaseModel):
  """Parameters for OpenAI Computer Use Assistant action."""

  description: str = Field(..., description='Description of your next goal')


class NavigateAction(BaseModel):
    url: str = Field(..., description="URL to navigate to")
    new_tab: bool = Field(default=False, description="Open in a new tab if True")



async def handle_model_action(browser_session: BrowserSession, action) -> ActionResult:
  """
  Given a computer action (e.g., click, double_click, etc.),
  execute the corresponding operation using CDP.
  """
  action_type = action.type
  ERROR_MSG: str = 'Could not execute the CUA action.'

  if not browser_session.agent_focus:
    return ActionResult(error='No active browser session')

  try:
    match action_type:
      case 'click':
        x, y = action.x, action.y
        button = action.button
        print(f"Action: click at ({x}, {y}) with button '{button}'")
        # Not handling things like middle click, etc.
        if button != 'left' and button != 'right':
          button = 'left'

        # Use CDP to click
        await browser_session.agent_focus.cdp_client.send.Input.dispatchMouseEvent(
          params={
            'type': 'mousePressed',
            'x': x,
            'y': y,
            'button': button,
            'clickCount': 1,
          },
          session_id=browser_session.agent_focus.session_id,
        )
        await browser_session.agent_focus.cdp_client.send.Input.dispatchMouseEvent(
          params={
            'type': 'mouseReleased',
            'x': x,
            'y': y,
            'button': button,
          },
          session_id=browser_session.agent_focus.session_id,
        )
        msg = f'Clicked at ({x}, {y}) with button {button}'
        return ActionResult(extracted_content=msg, include_in_memory=True, long_term_memory=msg)

      case 'scroll':
          direction = getattr(action, "direction", "down")
          amount = getattr(action, "amount", 500)
          x = getattr(action, "x", 500)
          y = getattr(action, "y", 500)
          print(f"🚀 Action: scroll {direction} by {amount}px at ({x}, {y})")
          # Positive amount for down, negative for up
          pixels = amount if direction == "down" else -amount
          await browser_session.agent_focus.cdp_client.send.Input.dispatchMouseEvent(
              params={
                  'type': 'mouseWheel',
                  'x': x,
                  'y': y,
                  'deltaX': 0,
                  'deltaY': pixels,
              },
              session_id=browser_session.agent_focus.session_id,
          )
          msg = f'Scrolled {direction} by {amount}px'
          return ActionResult(extracted_content=msg, include_in_memory=True, long_term_memory=msg)

      case 'keypress':
          keys = action.keys
          for k in keys:
              print(f"Action: keypress '{k}'")
              # A simple mapping for common keys; expand as needed.
              key_code = k
              if k.lower() == 'enter':
                  key_code = 'Enter'
              elif k.lower() == 'space':
                  key_code = 'Space'

              # Use CDP to send key
              await browser_session.agent_focus.cdp_client.send.Input.dispatchKeyEvent(
                  params={
                      'type': 'keyDown',
                      'key': key_code,
                  },
                  session_id=browser_session.agent_focus.session_id,
              )
              await browser_session.agent_focus.cdp_client.send.Input.dispatchKeyEvent(
                  params={
                      'type': 'keyUp',
                      'key': key_code,
                  },
                  session_id=browser_session.agent_focus.session_id,
              )
          msg = f'Pressed keys: {keys}'
          return ActionResult(extracted_content=msg, include_in_memory=True, long_term_memory=msg)

      case 'type':
        text = getattr(action, 'text', None)
        if not text:
          return ActionResult(error='No text provided for typing')
        print(f"Action: type text '{text}'")
        # Type text character by character using CDP
        for char in text:
          await browser_session.agent_focus.cdp_client.send.Input.dispatchKeyEvent(
            params={
              'type': 'char',
              'text': char,
            },
            session_id=browser_session.agent_focus.session_id,
          )
        msg = f"Typed text: {text}"
        await asyncio.sleep(1)
        return ActionResult(extracted_content=msg, include_in_memory=True, long_term_memory=msg)

      case 'wait':
        print('Action: wait')
        await asyncio.sleep(2)
        msg = 'Waited for 2 seconds'
        return ActionResult(extracted_content=msg, include_in_memory=True, long_term_memory=msg)

      case 'screenshot':
        # Nothing to do as screenshot is taken at each turn
        print('Action: screenshot')
        return ActionResult(error=ERROR_MSG)
      # Handle other actions here

      case _:
        print(f'Unrecognized action: {action}')
        return ActionResult(error=ERROR_MSG)

  except Exception as e:
    print(f'Error handling action {action}: {e}')
    return ActionResult(error=ERROR_MSG)


tools = Tools(exclude_actions=[
    'click_element_by_index',
    'select_dropdown_option',
    'scroll',
    'get_dropdown_options',
    'switch_tab',
    'close_tab',
    'upload_file_to_element',
    'extract_structured_data',
    'scroll_to_text',
    'click_element_by_index',
])

@tools.registry.action(
    "Navigate to HTTP/HTTPS URLs ONLY for actual web page navigation. NEVER use for JavaScript code execution, canvas interactions, or placeholder URLs. For any UI interactions use openai_cua_fallback instead.",
    param_model=NavigateAction,
)
async def go_to_url(params: NavigateAction, browser_session: BrowserSession):
    """
    Navigates to the specified HTTP/HTTPS URL using the browser session.
    Strictly blocks JavaScript URLs and non-HTTP schemes to prevent misuse on canvas/Flutter UIs.
    """
    try:
        # Block JavaScript URLs completely - they don't work on canvas/Flutter UIs
        if params.url.lower().startswith('javascript:'):
            msg = "JavaScript URLs are BLOCKED. Canvas/Flutter UIs don't support JavaScript execution. Use openai_cua_fallback for ALL UI interactions instead."
            print(f"BLOCKED JavaScript URL: {params.url}")
            return ActionResult(error=msg)

        # Block any non-HTTP/HTTPS URLs
        if not (params.url.lower().startswith('http://') or params.url.lower().startswith('https://')):
            msg = f"BLOCKED invalid URL scheme: {params.url}. Only HTTP/HTTPS URLs allowed. For UI interactions, use openai_cua_fallback."
            print(f"BLOCKED invalid URL: {params.url}")
            return ActionResult(error=msg)

        # Block placeholder or console.log URLs
        if 'console.log' in params.url.lower() or 'placeholder' in params.url.lower():
            msg = "BLOCKED placeholder/debug URL. Use openai_cua_fallback for canvas UI interactions."
            print(f"BLOCKED placeholder URL: {params.url}")
            return ActionResult(error=msg)

        event = browser_session.event_bus.dispatch(
            NavigateToUrlEvent(url=params.url, new_tab=params.new_tab)
        )
        await event
        await event.event_result(raise_if_any=True, raise_if_none=False)
        msg = f"Navigated to {params.url} (new_tab={params.new_tab})"
        print(msg)
        return ActionResult(extracted_content=msg, long_term_memory=msg)
    except Exception as e:
        msg = f"Navigation to {params.url} failed: {e}"
        print(msg)
        return ActionResult(error=msg)



class SimpleInputTextAction(BaseModel):
    text: str = Field(..., description="Text to type into the currently focused input field")

@tools.registry.action(
    "Type the EXACT text provided in the 'text' parameter. Before typing make sure focused/select the input filed by `openai_cua_fallback` action to click.",
    param_model=SimpleInputTextAction,
)
async def input_text(params: SimpleInputTextAction, browser_session: BrowserSession):
    """
    Types the given text into the currently focused input field using CDP key events.
    """
    try:
        if not browser_session.agent_focus:
            return ActionResult(error='No active browser session')

        print(f"⌨️ Typing text: {params.text}")
        # Type text character by character
        for char in params.text:
            await browser_session.agent_focus.cdp_client.send.Input.dispatchKeyEvent(
                params={
                    'type': 'char',
                    'text': char,
                },
                session_id=browser_session.agent_focus.session_id,
            )
        msg = f"Typed text: {params.text}"
        await asyncio.sleep(1)
        return ActionResult(extracted_content=msg, long_term_memory=msg)
    except Exception as e:
        msg = f"Error typing text: {e}"
        print(f"❌ {msg}")
        return ActionResult(error=msg)


@tools.registry.action(
    'Send keys ONLY when user explicitly requests key presses for Canvas/Flutter UIs. Use for special keys (Escape, Enter, Tab, Delete) or shortcuts (Control+o, Control+Shift+T). Do NOT use for typing text - use input_text instead. ONLY use when user explicitly says to press specific keys.',
    param_model=SendKeysAction,
)
async def send_keys(params: SendKeysAction, browser_session: BrowserSession):
    # Dispatch send keys event
    try:
        event = browser_session.event_bus.dispatch(SendKeysEvent(keys=params.keys))
        await event
        await event.event_result(raise_if_any=True, raise_if_none=False)
        memory = f'Sent keys: {params.keys}'
        msg = f'⌨️  {memory}'
        logger.info(msg)
        return ActionResult(extracted_content=memory, long_term_memory=memory)
    except Exception as e:
        logger.error(f'Failed to dispatch SendKeysEvent: {type(e).__name__}: {e}')
        error_msg = f'Failed to send keys: {str(e)}'
        return ActionResult(error=error_msg)


@tools.registry.action(
    "Use this tool for Flutter, canvas, or custom UI when DOM actions (click, scroll) do not work or do not focus the correct element. Just perform the click operation when asked for a click, select, focus or any other operation that needs click. if scroll is necessary, determine the necessary coordinates and amount of scroll need with direction. If you have already performed the requested action, do not perform it again.",
    param_model=OpenAICUAAction,
)
async def openai_cua_fallback(params: OpenAICUAAction, browser_session: BrowserSession):
    """
    Fallback action that uses OpenAI's Computer Use Assistant to perform complex
    computer interactions when standard browser actions are insufficient.
    """
    print(f'🎯 CUA Action Starting - Goal: {params.description}')

    try:
        # Get browser state summary
        state = await browser_session.get_browser_state_summary()
        page_info = state.page_info
        if not page_info:
            raise Exception('Page info not found - cannot execute CUA action')

        print(f'📐 Viewport size: {page_info.viewport_width}x{page_info.viewport_height}')

        screenshot_b64 = state.screenshot
        if not screenshot_b64:
            raise Exception('Screenshot not found - cannot execute CUA action')

        print(f'📸 Screenshot captured (base64 length: {len(screenshot_b64)} chars)')

        # Debug: Check screenshot dimensions
        image = Image.open(BytesIO(base64.b64decode(screenshot_b64)))
        print(f'📏 Screenshot actual dimensions: {image.size[0]}x{image.size[1]}')

        # rescale the screenshot to the viewport size
        image = image.resize((page_info.viewport_width, page_info.viewport_height))
        # Save as PNG to bytes buffer
        buffer = BytesIO()
        image.save(buffer, format='PNG')
        buffer.seek(0)
        # Convert to base64
        screenshot_b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
        print(f'📸 Rescaled screenshot to viewport size: {page_info.viewport_width}x{page_info.viewport_height}')

        client = AsyncOpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        print('🔄 Sending request to OpenAI CUA...')

        prompt = f"""
        TASK: {params.description}

        You must perform a single action to interact with the target element described in the task.
        This action can be click or scroll, depending on what is visually required.

        INSTRUCTIONS:
        - Use the provided screenshot to visually locate the target element or understand the context.
        - If the target element is visible and needs clicking:
            - Identify the boundaries (left, right, top, bottom) of the element.
            - Calculate the center coordinate: x = (left + right) / 2, y = (top + bottom) / 2
            - Click exactly at this center point.
            - Respond with one computer_call action of type 'click'.
        - If scrolling is needed to bring content into view:
            - Decide the scroll direction ("down" or "up") and amount in pixels.
            - Choose the best origin (x, y) for the scroll event.
            - Respond with one computer_call action of type 'scroll'.

        Viewport size: width={page_info.viewport_width}, height={page_info.viewport_height}
        """

        response = await client.responses.create(
            model='computer-use-preview',
            tools=[
                {
                    'type': 'computer_use_preview',
                    'display_width': page_info.viewport_width,
                    'display_height': page_info.viewport_height,
                    'environment': 'browser',
                }
            ],
            input=[
                {
                    'role': 'user',
                    'content': [
                        {'type': 'input_text', 'text': prompt},
                        {
                            'type': 'input_image',
                            'detail': 'high',  # Changed to high for better precision
                            'image_url': f'data:image/png;base64,{screenshot_b64}',
                        },
                    ],
                }
            ],
            truncation='auto',
            temperature=0.1,
        )

        print(f'📥 CUA response received')

        # Extract computer calls more reliably
        computer_calls = []
        for item in response.output:
            if hasattr(item, 'type') and item.type == 'computer_call':
                computer_calls.append(item)

        if not computer_calls:
            # Check for a text message in the response
            for item in response.output:
                if hasattr(item, 'type') and item.type == 'output_text':
                    msg = getattr(item, 'text', None)
                    if msg:
                        print(f'✅ CUA text confirmation: {msg}')
                        # Return ActionResult with the confirmation message
                        return ActionResult(
                            extracted_content=msg,
                            long_term_memory=msg,
                            include_in_memory=True
                        )
            # If no text confirmation, log and return error as before
            print(f'❌ No computer calls found in response: {response.output}')
            return ActionResult(error='CUA did not return any computer_call actions or useful text confirmation.')

        computer_call = computer_calls[0]
        action = computer_call.action
        print(f'🎬 Executing CUA action: {action.type} - {action}')

        action_result = await handle_model_action(browser_session, action)
        await asyncio.sleep(0.2)  # Slight delay for UI updates

        print('✅ CUA action completed successfully')
        return action_result

    except Exception as e:
        msg = f'Error executing CUA action: {e}'
        print(f'❌ {msg}')
        return ActionResult(error=msg)


def load_system_message()->str:
    if not PROMPT_FILE.exists():
        raise FileNotFoundError(f"❌ System prompt file not found: {PROMPT_FILE}")

    text = PROMPT_FILE.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"❌ System prompt file is empty: {PROMPT_FILE}")

    return text


async def create_hyperbrowser_session() -> tuple[AsyncHyperbrowser | None, str | None]:
    """
    Create a Hyperbrowser client and session, returning (client, cdp_url).
    Returns (None, None) on any failure so caller can skip browser usage.
    """
    # if True:
    #     return None, None

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
    
async def run_cua():
  client: AsyncHyperbrowser | None = None
  browser_session: BrowserSession | None = None
  client, cdp_url = await create_hyperbrowser_session()

  # Initialize the language model
  api_key = os.getenv('GOOGLE_API_KEY')
  if not api_key:
    raise ValueError('GOOGLE_API_KEY is not set')

  llm = ChatGoogle(model='gemini-2.5-flash', api_key=api_key)

  browser_session = BrowserSession(cdp_url=cdp_url if client else None)
  print("🚀 Browser session started.")
      
  # This could be a complex interaction that's difficult with standard actions
  task = (
    "1. Open the dashboard login page using this URL https://dev.dashboard.qvin.com/signin\n"
    "2. Enter the Email ID as _super@qvin.com and press the Enter key.\n"
    "3. Click on Organization on the left hand menu\n"
    "4. Click on CREATE NEW button\n"
    "5. Enter the name - AI Lab Organization\n"
    "6. From Type Dropdown select Laboratory\n"
    "7. Click on SAVE button."
  )

  agent_kwargs = {"task": task, "llm": llm, "tools": tools, "override_system_message": load_system_message()}
  if browser_session:
      agent_kwargs["browser_session"] = browser_session
      
  # Create agent with our custom tools that includes CUA fallback
  agent = Agent(**agent_kwargs)

  print('🚀 Starting agent with CUA fallback support...')
  print(f'Task: {task}')
  print('-' * 50)

  try:
    # Run the agent
    start_time = time()
    result = await agent.run()
    end_time = time()
    print(f"\n⏱️ Agent run time: {end_time - start_time:.2f} seconds")
    print(f'\n✅ Task completed! Result: ')

    final_result = None
    if hasattr(result, "all_results") and result.all_results:
      for r in reversed(result.all_results):
        if getattr(r, "is_done", False):
          final_result = r
          break
      if final_result and getattr(final_result, "extracted_content", None):
        print(f"\n✅ Result: {final_result.extracted_content}")
      elif final_result and getattr(final_result, "long_term_memory", None):
        print(f"\n✅ Result: {final_result.long_term_memory}")
      else:
        print("\n❌ No final result found.")

  except Exception as e:
    print(f'\n❌ Error running agent: {e}')

  finally:
    # Clean up browser session
    await browser_session.kill()
    print('\n🧹 Browser session closed')


if __name__ == '__main__':
  # Example of different scenarios where CUA might be useful

  print('🔧 OpenAI Computer Use Assistant (CUA) Integration Example')
  print('=' * 60)
  print()
  print("This example shows how to integrate OpenAI's CUA as a fallback action")
  print('when standard browser-use actions cannot achieve the desired goal.')
  print()
  print('CUA is particularly useful for:')
  print('• Complex mouse interactions (drag & drop, precise clicking)')
  print('• Keyboard shortcuts and key combinations')
  print('• Actions that require pixel-perfect precision')
  print("• Custom UI elements that don't respond to standard actions")
  print()
  print('Make sure you have OPENAI_API_KEY set in your environment!')
  print()

  # Check if OpenAI API key is available
  if not os.getenv('OPENAI_API_KEY'):
    print('❌ Error: OPENAI_API_KEY environment variable not set')
    print('Please set your OpenAI API key to use CUA integration')
    sys.exit(1)

  # Run the example
  asyncio.run(run_cua())
