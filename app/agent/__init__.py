"""Controlled agent workflows: fixed sequences of steps, an audit trail, and human approval.

There is deliberately no free-form loop where a model picks its own next tool. Code decides the
sequence; the LLM only fills defined steps with structured output that is validated afterwards.
"""
