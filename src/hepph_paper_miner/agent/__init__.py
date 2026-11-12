"""A minimal tool-calling loop: one question in, tool calls through MCP, one answer out.

    prompt.py   everything the loop itself says to the model, and the form of the answer
    model.py    one call to a model: the Claude API, or anything else with the same shape
    loop.py     the loop, its limits and the reasons it ends
    trace.py    the record of a run: a public file without paper text, a private one with it

Run one question with:  python -m hepph_paper_miner.agent --question-id dev-01
"""
