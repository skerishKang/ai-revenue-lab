"""Remove model-internal thought tags without exposing split streaming tags."""

class ThoughtFilter:
    _open = ("<thought>", "<thinking>")

    def __init__(self):
        self.pending = ""
        self.closing = None

    def feed(self, text, *, final=False):
        self.pending += text
        output = []
        while self.pending:
            lower = self.pending.lower()
            if self.closing:
                pos = lower.find(self.closing)
                if pos < 0:
                    # Only retain a possible prefix of the closing tag.
                    keep = 0
                    for n in range(1, min(len(lower), len(self.closing)-1)+1):
                        if lower.endswith(self.closing[:n]):
                            keep = n
                    self.pending = self.pending[-keep:] if keep else ""
                    break
                self.pending = self.pending[pos+len(self.closing):]
                self.closing = None
                continue
            matches = [(lower.find(tag), tag) for tag in self._open if lower.find(tag) >= 0]
            if matches:
                pos, tag = min(matches)
                output.append(self.pending[:pos])
                self.pending = self.pending[pos+len(tag):]
                self.closing = "</" + tag[1:]
                continue
            keep = 0
            if not final:
                for tag in self._open:
                    for n in range(1, min(len(lower), len(tag)-1)+1):
                        if lower.endswith(tag[:n]):
                            keep = max(keep, n)
            output.append(self.pending[:-keep] if keep else self.pending)
            self.pending = self.pending[-keep:] if keep else ""
            break
        return "".join(output)


def strip_thought_blocks(text):
    return ThoughtFilter().feed(text, final=True)
