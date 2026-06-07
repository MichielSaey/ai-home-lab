# Training Plan

Goal: keep the current apps in a working state while you start iterating safely.

## Task 1: Add a `/profile` command in the Garmin trainer UI
Hint: parse a JSON payload in `on_message`, encrypt the password with `encrypt_secret`, and persist with `upsert_user_profile`.
Expectation: after submission, the user sees a short confirmation and the coach can access Garmin data on the next message.

## Task 2: Add a friendly MCP health path
Hint: if the MCP weekly report returns an `error`, surface a clear user-facing message instead of a silent failure.
Expectation: users get an actionable message like "Garmin service unavailable" or "Missing credentials".

## Task 3: Verify LiteLLM proxy wiring
Hint: set `LITELLM_API_BASE`, `LITELLM_API_KEY`, and `LITELLM_MODEL` in `.env`, then run a short prompt.
Expectation: the Chainlit UI responds successfully using the LiteLLM proxy.

## Task 4: refactor review of of past garmin data
- Make the period variable. Allow the agent to specify the time range for data review (e.g., last week, last month).
- Could atomate it to be a review since the last review, so the agent alsways starts a session with the most recent data.

## Task 5: Add user guidence commands
- `/goals` to set training goals (e.g., "I want to run a marathon in 6 months").
- `/preferences` to set training preferences (e.g., "I prefer morning runs", "I have access to a gym", "I want one weighted run per week").

## Task 6: Introduce structured workout creation and scheduling
- Creation and scheduling of workouts should be done through a structured interface, not free-form text.
- Have four predefined workout types (e.g., Endurance, Interval, Recovery, Strength) with specific parameters.
- Implement a nutrition plan calcultar that teeks estemated team, and used a premade matrix to suggest what to eat before, during, and after runs.
