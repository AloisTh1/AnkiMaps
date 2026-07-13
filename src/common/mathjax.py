import hashlib
import html
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Optional


_MATHJAX_PATTERN = re.compile(
    r"(?P<display>\\\[(?P<display_body>.*?)\\\])" r"|(?P<inline>\\\((?P<inline_body>.*?)\\\))",
    re.IGNORECASE | re.DOTALL,
)
_SKIP_TAGS = {
    "annotation",
    "annotation-xml",
    "code",
    "noscript",
    "pre",
    "script",
    "style",
    "textarea",
}
_VOID_TAGS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


@dataclass(frozen=True)
class _HtmlTag:
    start: int
    end: int
    name: str
    closing: bool
    self_closing: bool
    attributes: dict[str, str]


@dataclass(frozen=True)
class MathJaxFragment:
    original: str
    tex: str
    display: bool
    start: int
    end: int


def _parse_tag_attributes(tag_text: str, tag_name: str) -> dict[str, str]:
    attributes: dict[str, str] = {}
    cursor = 1
    if cursor < len(tag_text) and tag_text[cursor] == "/":
        cursor += 1
    while cursor < len(tag_text) and tag_text[cursor].isspace():
        cursor += 1
    cursor += len(tag_name)

    while cursor < len(tag_text):
        while cursor < len(tag_text) and tag_text[cursor].isspace():
            cursor += 1
        if cursor >= len(tag_text) or tag_text[cursor] in "/>":
            break

        name_start = cursor
        while cursor < len(tag_text) and (tag_text[cursor].isalnum() or tag_text[cursor] in "_:.-"):
            cursor += 1
        if cursor == name_start:
            cursor += 1
            continue
        attribute_name = tag_text[name_start:cursor].lower()

        while cursor < len(tag_text) and tag_text[cursor].isspace():
            cursor += 1
        attribute_value = ""
        if cursor < len(tag_text) and tag_text[cursor] == "=":
            cursor += 1
            while cursor < len(tag_text) and tag_text[cursor].isspace():
                cursor += 1
            if cursor < len(tag_text) and tag_text[cursor] in {'"', "'"}:
                quote = tag_text[cursor]
                cursor += 1
                value_start = cursor
                while cursor < len(tag_text) and tag_text[cursor] != quote:
                    cursor += 1
                attribute_value = tag_text[value_start:cursor]
                if cursor < len(tag_text):
                    cursor += 1
            else:
                value_start = cursor
                while cursor < len(tag_text) and not tag_text[cursor].isspace() and tag_text[cursor] != ">":
                    cursor += 1
                attribute_value = tag_text[value_start:cursor]
        attributes[attribute_name] = html.unescape(attribute_value)
    return attributes


def _scan_html(html_content: str) -> tuple[list[_HtmlTag], list[tuple[int, int]]]:
    """Locate HTML tags without treating ``>`` inside quoted attributes as an endpoint."""
    tags: list[_HtmlTag] = []
    comments: list[tuple[int, int]] = []
    index = 0
    content_length = len(html_content)
    while index < content_length:
        start = html_content.find("<", index)
        if start < 0:
            break
        if html_content.startswith("<!--", start):
            closing = html_content.find("-->", start + 4)
            index = content_length if closing < 0 else closing + 3
            comments.append((start, index))
            continue

        cursor = start + 1
        closing = cursor < content_length and html_content[cursor] == "/"
        if closing:
            cursor += 1
        while cursor < content_length and html_content[cursor].isspace():
            cursor += 1
        name_match = re.match(r"[A-Za-z][A-Za-z0-9:_-]*", html_content[cursor:])
        if not name_match:
            index = start + 1
            continue

        name = name_match.group(0).lower()
        quote: Optional[str] = None
        end = cursor + len(name_match.group(0))
        while end < content_length:
            character = html_content[end]
            if quote:
                if character == quote:
                    quote = None
            elif character in {'"', "'"}:
                quote = character
            elif character == ">":
                tag_text = html_content[start : end + 1]
                tags.append(
                    _HtmlTag(
                        start=start,
                        end=end + 1,
                        name=name,
                        closing=closing,
                        self_closing=tag_text.rstrip().endswith("/>") or name in _VOID_TAGS,
                        attributes=_parse_tag_attributes(tag_text, name),
                    )
                )
                end += 1
                break
            end += 1
        else:
            index = start + 1
            continue
        index = end
    return tags, comments


def _html_tags(html_content: str) -> list[_HtmlTag]:
    return _scan_html(html_content)[0]


def _html_comment_ranges(html_content: str) -> list[tuple[int, int]]:
    return _scan_html(html_content)[1]


def _blocked_html_text_ranges(tags: list[_HtmlTag], content_length: int) -> list[tuple[int, int]]:
    """Return text regions MathJax itself would skip when scanning an HTML document."""
    ranges: list[tuple[int, int]] = []
    stack: list[tuple[str, bool, Optional[str]]] = []

    def is_blocked() -> bool:
        # MathJax does not descend into a skipped tag unless that tag itself opts in.
        if any(skip_tag and marker != "process" for _name, skip_tag, marker in stack):
            return True
        for _name, skip_tag, marker in reversed(stack):
            if marker:
                return marker == "ignore"
        return False

    cursor = 0
    for tag in tags:
        if cursor < tag.start and is_blocked():
            ranges.append((cursor, tag.start))
        if tag.closing:
            for index in range(len(stack) - 1, -1, -1):
                if stack[index][0] == tag.name:
                    del stack[index:]
                    break
        elif not tag.self_closing:
            classes = {value.lower() for value in tag.attributes.get("class", "").split()}
            marker = None
            if "mathjax_process" in classes:
                marker = "process"
            elif "mathjax_ignore" in classes:
                marker = "ignore"
            stack.append((tag.name, tag.name in _SKIP_TAGS, marker))
        cursor = tag.end

    if cursor < content_length and is_blocked():
        ranges.append((cursor, content_length))
    return ranges


def _overlaps(start: int, end: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start < range_end and end > range_start for range_start, range_end in ranges)


def _custom_fragment_is_display(attributes: dict[str, str]) -> bool:
    if "block" not in attributes:
        return False
    value = attributes["block"]
    return not value or value.strip().lower() not in {"0", "false", "no"}


def normalize_mathjax_tex(source: str) -> str:
    """Convert the HTML stored inside an Anki math fragment back to TeX text."""
    pieces: list[str] = []
    cursor = 0
    tags_by_start = {tag.start: tag for tag in _html_tags(source)}
    removable_ranges = [(tag.start, tag.end) for tag in tags_by_start.values()]
    removable_ranges.extend(_html_comment_ranges(source))
    for start, end in sorted(removable_ranges):
        if end <= cursor:
            continue
        start = max(start, cursor)
        pieces.append(source[cursor:start])
        tag = tags_by_start.get(start)
        if tag and tag.name == "br" and not tag.closing:
            pieces.append("\n")
        cursor = end
    pieces.append(source[cursor:])
    return html.unescape("".join(pieces)).strip("\n")


def find_mathjax_fragments(html_content: str) -> list[MathJaxFragment]:
    tags = _html_tags(html_content)
    tag_ranges = [(tag.start, tag.end) for tag in tags]
    comment_ranges = _html_comment_ranges(html_content)
    blocked_ranges = _blocked_html_text_ranges(tags, len(html_content))
    blocked_ranges.extend(comment_ranges)

    custom_fragments: list[MathJaxFragment] = []
    custom_stack: list[_HtmlTag] = []
    for tag in tags:
        if tag.name != "anki-mathjax":
            continue
        if not tag.closing and not tag.self_closing:
            custom_stack.append(tag)
        elif tag.closing and custom_stack:
            opening_tag = custom_stack.pop()
            if custom_stack or _overlaps(opening_tag.start, tag.end, blocked_ranges):
                continue
            custom_fragments.append(
                MathJaxFragment(
                    original=html_content[opening_tag.start : tag.end],
                    tex=normalize_mathjax_tex(html_content[opening_tag.end : tag.start]),
                    display=_custom_fragment_is_display(opening_tag.attributes),
                    start=opening_tag.start,
                    end=tag.end,
                )
            )

    custom_ranges = [(fragment.start, fragment.end) for fragment in custom_fragments]
    fragments: list[MathJaxFragment] = list(custom_fragments)
    for match in _MATHJAX_PATTERN.finditer(html_content):
        if _overlaps(match.start(), match.end(), blocked_ranges + custom_ranges):
            continue
        opening_delimiter = (match.start(), match.start() + 2)
        closing_delimiter = (match.end() - 2, match.end())
        if _overlaps(*opening_delimiter, tag_ranges) or _overlaps(*closing_delimiter, tag_ranges):
            # Delimiters in attributes are metadata, not note-body math.
            continue

        if match.group("display") is not None:
            source = match.group("display_body") or ""
            display = True
        else:
            source = match.group("inline_body") or ""
            display = False

        fragments.append(
            MathJaxFragment(
                original=match.group(0),
                tex=normalize_mathjax_tex(source),
                display=display,
                start=match.start(),
                end=match.end(),
            )
        )
    return sorted(fragments, key=lambda fragment: fragment.start)


def replace_mathjax_fragments(
    html_content: str,
    replacement: Callable[[MathJaxFragment], Optional[str]],
) -> str:
    """Replace complete fragments while retaining the original text when rendering is unavailable."""
    fragments = find_mathjax_fragments(html_content)
    if not fragments:
        return html_content

    result: list[str] = []
    cursor = 0
    for fragment in fragments:
        result.append(html_content[cursor : fragment.start])
        result.append(replacement(fragment) or fragment.original)
        cursor = fragment.end
    result.append(html_content[cursor:])
    return "".join(result)


def mathjax_cache_key(
    tex: str,
    display: bool,
    font_px: float,
    foreground: str,
    device_pixel_ratio: float,
    max_width: Optional[float] = None,
) -> str:
    payload = json.dumps(
        [
            "mathjax-3.2.2-svg-v2",
            tex,
            display,
            round(font_px, 3),
            foreground.lower(),
            round(device_pixel_ratio, 2),
            round(max_width, 2) if max_width is not None else None,
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def mathjax_resource_url(cache_key: str) -> str:
    """Keep the 64-character cache key out of the URL host, where Qt applies DNS limits."""
    return f"ankimaps-math://resource/{cache_key}"
