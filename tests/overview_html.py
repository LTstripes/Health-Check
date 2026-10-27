"""Small structural assertions for the Overview route tests (stdlib only)."""

from dataclasses import dataclass, field
from html.parser import HTMLParser


@dataclass
class Element:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    @property
    def text(self):
        return "".join(child.text if isinstance(child, Element) else child
                       for child in self.children)

    def find(self, tag=None, *, classes=(), **attrs):
        found = []
        for child in self.children:
            if isinstance(child, Element):
                if ((tag is None or child.tag == tag)
                        and all(key in child.attrs and child.attrs[key] == value
                                for key, value in attrs.items())
                        and set(classes) <= set(child.attrs.get("class", "").split())):
                    found.append(child)
                found.extend(child.find(tag, classes=classes, **attrs))
        return found

    def one(self, tag=None, *, classes=(), **attrs):
        found = self.find(tag, classes=classes, **attrs)
        assert len(found) == 1, (tag, attrs, classes, len(found))
        return found[0]


def parse_overview(html):
    class Parser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.root = Element("document")
            self.stack = [self.root]

        def handle_starttag(self, tag, attrs):
            element = Element(tag, dict(attrs))
            self.stack[-1].children.append(element)
            if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input",
                           "link", "meta", "param", "source", "track", "wbr"}:
                self.stack.append(element)

        def handle_startendtag(self, tag, attrs):
            self.stack[-1].children.append(Element(tag, dict(attrs)))

        def handle_endtag(self, tag):
            if any(element.tag == tag for element in self.stack[1:]):
                while self.stack.pop().tag != tag:
                    pass

        def handle_data(self, text):
            self.stack[-1].children.append(text)

    parser = Parser()
    parser.feed(html)
    parser.close()
    return parser.root
