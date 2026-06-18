import chainlit as cl
from agents.garmin_trainer.agent import parse_report_command, run_agent as run_garmin
# from agents.adhd_life_aid.agent import run_agent as run_adhd

AGENTS = {
    "garmin": {
        "run": run_garmin,
        "welcome": (
            "Garmin coach ready. I'll review your recent training using the 80/20 rule. "
            "Ask about training or recovery, or use `/report [days] [days_ago]` to roll the data window (default 7 days)."
        ),
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
    cl.user_session.set("report_days", 7)
    cl.user_session.set("days_ago", 0)

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
    report_days = cl.user_session.get("report_days", 7)
    days_ago = cl.user_session.get("days_ago", 0)

    _, parsed_days, parsed_days_ago, used_report_command = parse_report_command(
        message.content
    )
    if used_report_command:
        report_days = parsed_days if parsed_days is not None else report_days
        days_ago = parsed_days_ago if parsed_days_ago is not None else days_ago
        cl.user_session.set("report_days", report_days)
        cl.user_session.set("days_ago", days_ago)

    response = await agent["run"](
        message.content,
        user_id=user_id,
        thread_id=thread_id,
        report_days=report_days,
        days_ago=days_ago,
    )
    await cl.Message(content=response).send()
