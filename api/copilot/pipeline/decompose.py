"""Step 2: the brief becomes search queries, one for each part of the strategy.

No model is involved. Each query is searched by itself, so every part of
the strategy gets its own notes; the whole brief is never searched as one.
"""

from copilot.pipeline.brief import Brief


def decompose(brief: Brief) -> list[str]:
    queries: list[str] = []
    if brief.kind == "strategy":
        queries.extend([brief.entry, brief.exit])
    else:
        queries.append(brief.goal)
    queries.extend(brief.stops)
    if brief.sizing:
        queries.append(f"position size {brief.sizing}")
    queries.extend(brief.time_rules)
    queries.extend(brief.other_requirements)
    return list(dict.fromkeys(query.strip() for query in queries if query.strip()))
