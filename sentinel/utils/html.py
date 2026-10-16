import html.parser


class _HTMLStripper(html.parser.HTMLParser):
    """Simple HTML tag stripper using stdlib html.parser."""

    def __init__(self):
        super().__init__()
        self._pieces: list[str] = []

    def handle_data(self, data: str) -> None:
        self._pieces.append(data)

    def get_text(self) -> str:
        return "".join(self._pieces)


def strip_html(text: str) -> str:
    """Remove HTML tags from text, returning plain text.

    ``close()`` flushes the text the parser holds back while it waits for the
    end of a possible entity. Without it, a summary cut off after ``&`` (for
    example ``"… Więcej &raquo"``) lost its text after the last tag, or all of
    it when it had no tag.
    """
    stripper = _HTMLStripper()
    try:
        stripper.feed(text)
        stripper.close()
        return stripper.get_text()
    except Exception:
        return text
