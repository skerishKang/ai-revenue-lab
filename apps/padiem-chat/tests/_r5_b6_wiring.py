"""B6: read a module's deps block from either create({...}) or the
create(Object.setPrototypeOf({...}, app)) form. Scope widened, not replaced:
both shapes describe the same dependency surface.
"""


def create_block(app: str, start: int) -> str:
    i = app.index("{", start)
    depth = 0
    for k in range(i, len(app)):
        if app[k] == "{":
            depth += 1
        elif app[k] == "}":
            depth -= 1
            if depth == 0:
                return app[i : k + 1]
    raise AssertionError("unbalanced create block")


def context_names(app: str) -> set[str]:
    import re
    from pathlib import Path
    start = app.index("window.PadiemChatAppContext.create(")
    block = create_block(app, start)
    names = set(re.findall(r"\b(?:get|set) (\w+)\(", block))
    tail = app[start + app[start:].index(block) + len(block):]
    if tail.lstrip().startswith(", {"):
        owners = create_block(tail, 0)
        context = (Path(__file__).resolve().parents[1] / "static/chat-app-context.js").read_text(encoding="utf-8")
        table = create_block(context, context.index("const DEFERRED_API_NAMES"))
        for owner in re.findall(r"\b(\w+):\s*\(\)\s*=>", owners):
            match = re.search(r"\b" + owner + r":\s*\[([^]]*)\]", table)
            if match:
                names.update(re.findall(r'"(\w+)"', match[1]))
    context = (Path(__file__).resolve().parents[1] / "static/chat-app-context.js").read_text(encoding="utf-8")
    state = create_block(context, context.index("const state ="))
    names.update(re.findall(r"^\s*(\w+):", state, re.M))
    return names


def create_receives_app_context(app: str, factory: str) -> str:
    """B6 review: the module's create() must mount the real shared context as
    the deps prototype (`create(Object.setPrototypeOf({...}, app))`). A getter
    missing from the deps literal is only legitimate when the module actually
    receives the context — the name existing somewhere in the context is not
    enough. Returns the deps block for the surface checks."""
    assert "const app = window.PadiemChatAppContext.create(" in app, (
        "the shared context must be the PadiemChatAppContext.create result"
    )
    start = app.index(factory + ".create(")
    block = create_block(app, start)
    end = app.index("{", start) + len(block)
    assert app[end : end + 7] == ", app))", (
        factory + ": create() must mount the shared app context as the deps prototype"
    )
    return block
