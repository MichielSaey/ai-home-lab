# Training Plan

Goal: iterate on Garmin coaching through Odysseus + garmin-mcp.

## Task 1: Add profile management via MCP tools
Hint: extend garmin-mcp with profile tools (goals, injuries, preferences) so Odysseus presets can read/write user context.
Expectation: coach preset can access and update user profile through MCP.

## Task 2: Add a friendly MCP health path
Hint: if the MCP weekly report returns an `error`, surface a clear user-facing message instead of a silent failure.
Expectation: users get an actionable message like "Garmin service unavailable" or "Missing credentials".

## Task 3: Verify LLM provider wiring in Odysseus
Hint: configure your LLM provider in Odysseus Settings, then run a short coach prompt.
Expectation: the Odysseus Garmin preset responds successfully using your configured model.

## Task 4: Refactor review of past Garmin data
- Make the period variable. Allow the agent to specify the time range for data review (e.g., last week, last month).
- Could automate it to be a review since the last review, so the agent always starts a session with the most recent data.

## Task 5: Add user guidance via Odysseus preset
- Training goals (e.g., "I want to run a marathon in 6 months").
- Training preferences (e.g., "I prefer morning runs", "I have access to a gym", "I want one weighted run per week").

## Task 6: Introduce structured workout creation and scheduling
- Creation and scheduling of workouts should be done through a structured interface, not free-form text.
- Have predefined workout types (Recovery, Easy, Tempo, Threshold, Long, Sprint) with specific parameters.
- Implement a nutrition plan calculator that uses a premade matrix to suggest what to eat before, during, and after runs.
