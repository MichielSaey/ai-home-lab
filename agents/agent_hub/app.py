import chainlit as cl
from agents.garmin_trainer.agent import run_agent as run_garmin
# from agents.adhd_life_aid.agent import run_agent as run_adhd

AGENTS = {
    "garmin": {
        "run": run_garmin,
        "welcome": "Garmin coach ready. Ask about training or recovery.",
        "thread_suffix": "garmin",
    },
    # "adhd": {
    #     "run": run_adhd,
    #     "welcome": "ADHD life aid ready.",
    #     "thread_suffix": "adhd",
    # },
}

@cl.set_chat_profiles
async def chat_profiles():
    return [
        cl.ChatProfile(name="Garmin Coach", markdown_description="Running coach", icon="🏃"),
        # cl.ChatProfile(name="ADHD Life Aid", markdown_description="Local assistant", icon="🧠"),
    ]

PROFILE_TO_AGENT = {
    "Garmin Coach": "garmin",
    # "ADHD Life Aid": "adhd",
}

@cl.on_chat_start
async def on_chat_start():
    user_id = cl.user_session.get("user_id") or "default"
    cl.user_session.set("user_id", user_id)

    profile_name = cl.user_session.get("chat_profile")
    agent_key = PROFILE_TO_AGENT[profile_name]
    agent = AGENTS[agent_key]

    cl.user_session.set("agent_key", agent_key)
    cl.user_session.set("thread_id", f"{user_id}-{agent['thread_suffix']}")

    await cl.Message(content=agent["welcome"]).send()

@cl.on_message
async def on_message(message: cl.Message):
    agent_key = cl.user_session.get("agent_key")
    agent = AGENTS[agent_key]
    user_id = cl.user_session.get("user_id", "default")
    thread_id = cl.user_session.get("thread_id")

    response = await agent["run"](message.content, user_id=user_id, thread_id=thread_id)
    await cl.Message(content=response).send()