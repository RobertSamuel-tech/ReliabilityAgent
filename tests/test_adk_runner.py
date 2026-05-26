import asyncio
from google.adk.agents import Agent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

async def test_minimal_adk():
    print("Testing minimal ADK runner...")

    # Simple echo agent
    agent = Agent(
        model="gemini-1.5-pro",
        name="test_agent",
        description="Minimal test",
        instruction="You are a test agent. Reply with 'OK' to any message.",
    )

    runner = Runner(
        agent=agent,
        app_name="test-app",
        session_service=InMemorySessionService(),
    )

    session = await runner.session_service.create_session(
        app_name="test-app",
        user_id="test-user"
    )

    print(f"Session created: {session.id}")

    # Test async generator iteration
    result = None
    event_count = 0

    async for event in runner.run_async(
        session_id=session.id,
        user_id="test-user",
        new_message=types.Content(role="user", parts=[types.Part(text="Hello")])
    ):
        result = event
        event_count += 1
        print(f"Event {event_count}: {type(event).__name__}")

    print(f"Total events: {event_count}")
    print(f"Final result type: {type(result).__name__}")
    print(f"Final result: {str(result)[:200]}")
    print("ADK runner works correctly under this Python version")

if __name__ == "__main__":
    asyncio.run(test_minimal_adk())
