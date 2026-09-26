from .candidates import RULE_VERSION, Edge, rules
from .decoder import decode
from .models import Component, Evidence, Judgment, Span, Unit
from .questions import PROMPT_VERSION, ROLE_CRITERIA, Question, boundary_questions, marked_span


def component_graph(unit: Unit) -> list[Edge]:
    """A separate graph in parent-local coordinates; no edge can cross the parent."""
    text = unit.text
    edges = []
    for start in range(len(text)):
        for end in range(start + 1, min(len(text), start + 16) + 1):
            word = text[start:end]
            # Entity type is unused here; roles are assigned by a distinct Choice.
            score = -0.5 * len(word) - 0.8
            if start == 0:
                score += 0.3 * len(word)
            if word in rules()["suffixes"] and end == len(text):
                score += 2
            edges.append(
                Edge(start, end, word, sources={"component_candidate"}, feature_score=score)
            )
    return edges


def compile_components(unit: Unit, edges: list[Edge]) -> list[Question]:
    prefix = f"component:{unit.id}"
    questions = boundary_questions(unit.text, prefix, component=True)
    for question in questions:
        question.instructions["parent_name"] = unit.text
        question.instructions["parent_type"] = unit.entity_type
    selected = sorted(edges, key=lambda e: (-e.feature_score, e.start, e.end))[:48]
    for edge in selected:
        hint = "generic" if edge.text in rules()["suffixes"] else "proper_name"
        questions.append(
            Question(
                id=f"{prefix}:role:{edge.key}",
                kind="choice",
                edge_key=edge.key,
                hint=hint,
                instructions={
                    "question": "假设候选是父名称内部的一个完整成分，其角色是什么？",
                    "parent_name": unit.text,
                    "parent_type": unit.entity_type,
                    "candidate": edge.text,
                    "marked_text": marked_span(unit.text, edge.start, edge.end),
                    "left_context": unit.text[: edge.start],
                    "right_context": unit.text[edge.end :],
                    "policy": "只判定内部角色，不把借用地名升级成独立城市实体。",
                },
                criteria=ROLE_CRITERIA,
            )
        )
    return questions


def resolve_components(unit: Unit, edges: list[Edge], answers: dict[str, Judgment]):
    prefix = f"component:{unit.id}"
    cuts = {
        gap: answers[f"{prefix}:cut:{gap}"].noul
        for gap in range(1, len(unit.text))
        if f"{prefix}:cut:{gap}" in answers
    }
    roles = {
        edge.key: answers[f"{prefix}:role:{edge.key}"]
        for edge in edges
        if f"{prefix}:role:{edge.key}" in answers
    }
    paths = decode(len(unit.text), edges, cuts, roles, top_k=1)
    unit.components = []
    for i, edge in enumerate(paths[0].edges):
        answer = roles.get(edge.key)
        role = answer.choice if answer else "unknown"
        unit.components.append(
            Component(
                id=f"{unit.id}:c{i}",
                parent_id=unit.id,
                text=edge.text,
                span=Span(start=unit.span.start + edge.start, end=unit.span.start + edge.end),
                role=role,
                evidence=[
                    Evidence(
                        source=answer.source if answer else "component_rule",
                        version=PROMPT_VERSION if answer else RULE_VERSION,
                        detail=answer.question_id if answer else None,
                    )
                ],
            )
        )
