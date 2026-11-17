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
    start = app.index("window.PadiemChatAppContext.create(")
    block = create_block(app, start)
    return set(re.findall(r"\b(?:get|set) (\w+)\(", block))
