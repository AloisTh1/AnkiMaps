import unittest
from urllib.parse import urlsplit

from src.common.mathjax import (
    find_mathjax_fragments,
    mathjax_cache_key,
    mathjax_resource_url,
    normalize_mathjax_tex,
    replace_mathjax_fragments,
)


class FindMathJaxFragmentsTests(unittest.TestCase):
    def test_finds_inline_and_display_math_in_order(self):
        content = r"Before \(x^2 + 1\), then \[\frac{a}{b}\]."

        fragments = find_mathjax_fragments(content)

        self.assertEqual(
            [(fragment.tex, fragment.display) for fragment in fragments],
            [
                ("x^2 + 1", False),
                (r"\frac{a}{b}", True),
            ],
        )

    def test_normalizes_editor_html_inside_math(self):
        content = r"\[a &lt; b<br><span>+ c</span>\]"

        fragment = find_mathjax_fragments(content)[0]

        self.assertEqual(fragment.tex, "a < b\n+ c")
        self.assertTrue(fragment.display)

    def test_supports_editor_custom_element_defensively(self):
        content = '<anki-mathjax block="true">x<br>+ y</anki-mathjax>'

        fragment = find_mathjax_fragments(content)[0]

        self.assertEqual(fragment.tex, "x\n+ y")
        self.assertTrue(fragment.display)

    def test_custom_element_attributes_are_quote_aware_and_exact(self):
        content = (
            '<anki-mathjax title="1 > 0" data-mathjax="x > y" block="true">x+y</anki-mathjax>'
            '<anki-mathjax data-block="true" class="block">z</anki-mathjax>'
        )

        fragments = find_mathjax_fragments(content)

        self.assertEqual(
            [(fragment.tex, fragment.display) for fragment in fragments],
            [("x+y", True), ("z", False)],
        )

    def test_ignores_delimiters_in_html_attributes(self):
        content = r'<img alt="formula \(x\)" title="\[y\]"> visible \(z\)'

        fragments = find_mathjax_fragments(content)

        self.assertEqual([(fragment.tex, fragment.display) for fragment in fragments], [("z", False)])

    def test_ignores_mathjax_skip_tags(self):
        content = (
            r"<code>\(code\)</code><pre>\[pre\]</pre>"
            r"<script>const value = '\(script\)'</script>"
            r"<style>.x::after { content: '\(style\)'; }</style>"
            r"<textarea>\(textarea\)</textarea><noscript>\(noscript\)</noscript>"
            r"<annotation>\(annotation\)</annotation>"
            r"<annotation-xml>\(annotation-xml\)</annotation-xml>"
            r"<span>\(visible\)</span>"
        )

        fragments = find_mathjax_fragments(content)

        self.assertEqual([(fragment.tex, fragment.display) for fragment in fragments], [("visible", False)])

    def test_honors_mathjax_ignore_and_nested_process_classes(self):
        content = (
            r'<div class="mathjax_ignore">\(ignored\)'
            r'<span class="mathjax_process">\(processed\)</span>\[ignored too\]</div>'
            r'<div class="mathjax_process"><span class="mathjax_ignore">\(nested ignore\)</span>'
            r"\[visible\]</div>"
        )

        fragments = find_mathjax_fragments(content)

        self.assertEqual(
            [(fragment.tex, fragment.display) for fragment in fragments],
            [("processed", False), ("visible", True)],
        )

    def test_context_attributes_are_exact_and_process_can_override_skip_tag(self):
        content = (
            r'<div data-class="mathjax_ignore">\(visible data attribute\)</div>'
            r'<code class="mathjax_process">\(visible code\)</code>'
        )

        fragments = find_mathjax_fragments(content)

        self.assertEqual(
            [(fragment.tex, fragment.display) for fragment in fragments],
            [("visible data attribute", False), ("visible code", False)],
        )

    def test_process_descendant_cannot_override_hard_skip_ancestor(self):
        content = r'<code><span class="mathjax_process">\(still skipped\)</span></code>'

        self.assertEqual(find_mathjax_fragments(content), [])

    def test_unquoted_url_attribute_does_not_hide_later_class_attribute(self):
        content = r"<div data-url=https://example.com class=mathjax_ignore>\(ignored\)</div> \(visible\)"

        fragments = find_mathjax_fragments(content)

        self.assertEqual([(fragment.tex, fragment.display) for fragment in fragments], [("visible", False)])

    def test_allows_formatting_tags_inside_formula(self):
        content = r"\(a<br><span>+b</span>\)"

        fragment = find_mathjax_fragments(content)[0]

        self.assertEqual(fragment.tex, "a\n+b")

    def test_normalizes_formatting_tag_with_greater_than_in_quoted_attribute(self):
        content = r'\(a<span title="1 > 0">+b</span>\)'

        fragment = find_mathjax_fragments(content)[0]

        self.assertEqual(fragment.tex, "a+b")

    def test_rejects_closing_delimiters_inside_attributes(self):
        inline = r'prefix \(x <span title="close \) here">tail</span>'
        display = r'prefix \[x <span title="close \] here">tail</span>'

        self.assertEqual(find_mathjax_fragments(inline), [])
        self.assertEqual(find_mathjax_fragments(display), [])
        self.assertEqual(replace_mathjax_fragments(inline, lambda _fragment: "<MATH>"), inline)
        self.assertEqual(replace_mathjax_fragments(display, lambda _fragment: "<MATH>"), display)

    def test_ignores_math_in_or_crossing_html_comments(self):
        inside = r"<!-- \(hidden\) --> visible \(shown\)"
        spanning = r"<!-- \(hidden --> visible \) tail"

        self.assertEqual(
            [(fragment.tex, fragment.display) for fragment in find_mathjax_fragments(inside)],
            [("shown", False)],
        )
        self.assertEqual(find_mathjax_fragments(spanning), [])
        self.assertEqual(replace_mathjax_fragments(spanning, lambda _fragment: "<MATH>"), spanning)

    def test_comment_markers_inside_attributes_are_not_comments(self):
        visible = r'<span title="<!--">title</span> \(visible\)'
        formatted = r'\(a<span title="<!-- -->">+b</span>\)'

        self.assertEqual(
            [(fragment.tex, fragment.display) for fragment in find_mathjax_fragments(visible)],
            [("visible", False)],
        )
        self.assertEqual(find_mathjax_fragments(formatted)[0].tex, "a+b")

    def test_does_not_treat_custom_element_text_in_an_attribute_as_markup(self):
        content = (
            '<div data-source="<anki-mathjax block=true>x</anki-mathjax>">attribute</div>'
            "<anki-mathjax block=true>y</anki-mathjax>"
        )

        fragments = find_mathjax_fragments(content)

        self.assertEqual([(fragment.tex, fragment.display) for fragment in fragments], [("y", True)])

    def test_unclosed_math_is_left_alone(self):
        content = r"Unclosed \(x + 1"

        self.assertEqual(find_mathjax_fragments(content), [])
        self.assertEqual(replace_mathjax_fragments(content, lambda _fragment: "changed"), content)

    def test_chemistry_and_repeated_formulas_are_preserved(self):
        content = r"\(\ce{H2O -> H+ + OH-}\) / \(\ce{H2O -> H+ + OH-}\)"

        fragments = find_mathjax_fragments(content)

        self.assertEqual(len(fragments), 2)
        self.assertEqual(fragments[0].tex, r"\ce{H2O -> H+ + OH-}")
        self.assertEqual(fragments[0].tex, fragments[1].tex)


class ReplaceMathJaxFragmentsTests(unittest.TestCase):
    def test_replaces_selected_fragments_without_changing_surrounding_html(self):
        content = r"<b>Energy</b>: \(E=mc^2\)<br>and \[x\]"

        result = replace_mathjax_fragments(
            content,
            lambda fragment: f'<img data-display="{str(fragment.display).lower()}">',
        )

        self.assertEqual(
            result,
            '<b>Energy</b>: <img data-display="false"><br>and <img data-display="true">',
        )

    def test_none_replacement_retains_raw_formula_as_fallback(self):
        content = r"Value: \(x\)"

        self.assertEqual(replace_mathjax_fragments(content, lambda _fragment: None), content)


class MathJaxCacheKeyTests(unittest.TestCase):
    def test_key_is_stable_and_includes_rendering_inputs(self):
        base = mathjax_cache_key("x", False, 16.0, "#000000", 2.0)

        self.assertEqual(base, mathjax_cache_key("x", False, 16.0, "#000000", 2.0))
        self.assertNotEqual(base, mathjax_cache_key("x", True, 16.0, "#000000", 2.0))
        self.assertNotEqual(base, mathjax_cache_key("x", False, 18.0, "#000000", 2.0))
        self.assertNotEqual(base, mathjax_cache_key("x", False, 16.0, "#ffffff", 2.0))
        self.assertNotEqual(base, mathjax_cache_key("x", False, 16.0, "#000000", 3.0))
        self.assertNotEqual(base, mathjax_cache_key("x", False, 16.0, "#000000", 2.0, 400.0))

    def test_normalizer_handles_empty_and_entities(self):
        self.assertEqual(normalize_mathjax_tex("<br>&amp;<br>"), "&")

    def test_resource_url_keeps_sha256_key_out_of_hostname(self):
        key = "a" * 64

        parsed = urlsplit(mathjax_resource_url(key))

        self.assertEqual(parsed.hostname, "resource")
        self.assertEqual(parsed.path, f"/{key}")
        self.assertLessEqual(len(parsed.hostname), 63)


if __name__ == "__main__":
    unittest.main()
