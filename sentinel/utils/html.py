import html.parser


class _HTMLStripper(html.parser.HTMLParser):
    """Simple HTML tag stripper using stdlib html.parser."""

    def __init__(self):
        super().__init__()
        self.reset()
        self._pieces: list[str] = []

    def handle_data(self, data: str) -> None:
        self._pieces.append(data)

    def get_text(self) -> str:
        return "".join(self._pieces)


def strip_html(text: str) -> str:
    """Remove HTML tags from text, returning plain text."""
    stripper = _HTMLStripper()
    try:
        stripper.feed(text)
        return stripper.get_text()
    except Exception:
        return text
