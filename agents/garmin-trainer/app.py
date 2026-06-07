import chainlit as cl

from agent import run_agent


@cl.on_chat_start
async def on_chat_start() -> None:
    if cl.user_session.get("user_id") is None:
        cl.user_session.set("user_id", "default")
    if cl.user_session.get("thread_id") is None:
        user_id = cl.user_session.get("user_id")
        cl.user_session.set("thread_id", f"{user_id}-garmin")
    await cl.Message(content="Garmin coach ready. Ask about your training or recovery.").send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    user_id = cl.user_session.get("user_id", "default")
    thread_id = cl.user_session.get("thread_id", user_id)
    response = await run_agent(message.content, user_id=user_id, thread_id=thread_id)
    await cl.Message(content=response).send()
