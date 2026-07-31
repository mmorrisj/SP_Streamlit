"""Eval components. Importing this package registers all components."""
from evals.components import (  # noqa: F401
    extraction,
    events,
    entities,
    agent_tools,
    report_workflow,
)

# Retrieval / RAG-answer components import heavy ML deps lazily inside their
# eval functions, but the modules themselves must import to register.
from evals.components import retrieval, rag_answers  # noqa: F401
