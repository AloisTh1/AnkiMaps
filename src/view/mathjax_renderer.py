import json
import logging
import math
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Optional

from aqt import mw
from aqt.qt import QByteArray, QImage, QObject, QPainter, QRectF, QTimer, QUrl, Qt, pyqtSignal
from aqt.webview import AnkiWebPage, AnkiWebViewKind
from PyQt6.QtSvg import QSvgRenderer

from ..common.constants import ANKIMAPS_CONSTANTS
from ..common.mathjax import mathjax_cache_key


logger = logging.getLogger(ANKIMAPS_CONSTANTS.ADD_ON_NAME.value)


@dataclass(frozen=True)
class MathJaxRequest:
    tex: str
    display: bool
    font_px: float
    foreground: str
    device_pixel_ratio: float = 2.0
    max_width: float = 1200.0

    @property
    def key(self) -> str:
        return mathjax_cache_key(
            self.tex,
            self.display,
            self.font_px,
            self.foreground,
            self.device_pixel_ratio,
            self.max_width,
        )


@dataclass(frozen=True)
class MathJaxImage:
    key: str
    image: QImage
    logical_width: float
    logical_height: float
    vertical_align: float


class MathJaxRenderer(QObject):
    """Asynchronously converts TeX to cached, transparent images through one WebEngine page."""

    result_ready = pyqtSignal(str)

    _MAX_CACHE_ENTRIES = 512
    _MAX_CACHE_BYTES = 64 * 1024 * 1024
    _READY_POLL_INTERVAL_MS = 50
    _MAX_READY_POLLS = 100
    _REQUEST_TIMEOUT_MS = 5000
    _MAX_RASTER_DIMENSION = 4096
    _MAX_RASTER_PIXELS = 1_000_000

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self._page: Optional[AnkiWebPage] = None
        self._cache: OrderedDict[str, MathJaxImage] = OrderedDict()
        self._cache_bytes = 0
        self._failed: dict[str, str] = {}
        self._queue: deque[tuple[str, MathJaxRequest]] = deque()
        self._queued_keys: set[str] = set()
        self._active: Optional[tuple[str, MathJaxRequest]] = None
        self._ready = False
        self._starting = False
        self._closed = False
        self._ready_polls = 0
        self._disabled_reason: Optional[str] = None

    def get_or_request(self, request: MathJaxRequest) -> tuple[str, Optional[MathJaxImage]]:
        key = request.key
        if cached := self._cache.get(key):
            self._cache.move_to_end(key)
            return key, cached
        if key in self._failed:
            return key, None
        if self._disabled_reason or self._closed:
            self._failed[key] = self._disabled_reason or "The MathJax renderer has been shut down."
            return key, None

        if key not in self._queued_keys and (not self._active or self._active[0] != key):
            self._queue.append((key, request))
            self._queued_keys.add(key)

        self._ensure_started()
        self._process_next()
        return key, None

    def failure_for(self, key: str) -> Optional[str]:
        return self._failed.get(key)

    def _ensure_started(self) -> None:
        if self._closed or self._disabled_reason or self._page or self._starting:
            return
        self._starting = True
        try:
            if not mw or not mw.addonManager:
                raise RuntimeError("Anki is not ready to start the MathJax renderer.")

            addon_package = mw.addonManager.addonFromModule(__name__)
            base_url = mw.serverURL().rstrip("/")
            script_url = f"{base_url}/_addons/{addon_package}/src/view/assets/mathjax/tex-svg-full.js"
            self._page = AnkiWebPage(lambda _command: None, AnkiWebViewKind.DEFAULT, self)
            self._page.loadFinished.connect(self._on_page_loaded)
            if hasattr(self._page, "renderProcessTerminated"):
                self._page.renderProcessTerminated.connect(self._on_render_process_terminated)
            self._page.setHtml(self._shell_html(script_url), QUrl(f"{base_url}/"))
        except Exception as exc:
            self._starting = False
            self._disable(f"Could not start MathJax: {exc}")

    @staticmethod
    def _shell_html(script_url: str) -> str:
        escaped_url = script_url.replace("&", "&amp;").replace('"', "&quot;")
        return f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<script>
window.MathJax = {{
    loader: {{load: ['[tex]/noerrors', '[tex]/mathtools', '[tex]/mhchem']}},
    tex: {{packages: {{'[+]': ['noerrors', 'mathtools', 'mhchem'], '[-]': ['textmacros']}}}},
    svg: {{fontCache: 'local'}},
    startup: {{typeset: false}}
}};
</script>
<script src="{escaped_url}"></script>
</head>
<body style="margin:0; padding:0;"></body>
</html>"""

    def _on_page_loaded(self, success: bool) -> None:
        self._starting = False
        if self._closed:
            return
        if not success:
            self._disable("The MathJax renderer page failed to load.")
            return
        self._ready_polls = 0
        self._poll_ready()

    def _poll_ready(self) -> None:
        if self._closed or self._disabled_reason or not self._page:
            return
        if self._ready_polls >= self._MAX_READY_POLLS:
            self._disable("MathJax did not become ready before the timeout.")
            return
        self._ready_polls += 1
        self._page.runJavaScript(
            "Boolean(window.MathJax && MathJax.startup && MathJax.startup.document "
            "&& typeof MathJax.tex2svg === 'function')",
            self._on_ready_checked,
        )

    def _on_ready_checked(self, ready: object) -> None:
        if self._closed or self._disabled_reason:
            return
        if bool(ready):
            self._ready = True
            logger.info("MathJax SVG renderer is ready.")
            self._process_next()
        else:
            QTimer.singleShot(self._READY_POLL_INTERVAL_MS, self._poll_ready)

    def _process_next(self) -> None:
        if (
            self._closed
            or self._disabled_reason
            or not self._ready
            or not self._page
            or self._active
            or not self._queue
        ):
            return

        key, request = self._queue.popleft()
        self._queued_keys.discard(key)
        self._active = (key, request)
        self._page.runJavaScript(
            self._render_script(request),
            lambda result, active_key=key: self._on_javascript_result(active_key, result),
        )
        QTimer.singleShot(
            self._REQUEST_TIMEOUT_MS,
            lambda active_key=key: self._on_request_timeout(active_key),
        )

    @staticmethod
    def _render_script(request: MathJaxRequest) -> str:
        tex = json.dumps(request.tex, ensure_ascii=False)
        foreground = json.dumps(request.foreground)
        display = "true" if request.display else "false"
        font_px = json.dumps(float(request.font_px))
        return f"""(() => {{
    try {{
        const wrapper = MathJax.tex2svg({tex}, {{display: {display}}});
        wrapper.style.fontSize = `${{{font_px}}}px`;
        wrapper.style.color = {foreground};
        document.body.replaceChildren(wrapper);
        const svg = wrapper.querySelector('svg');
        if (!svg) {{ throw new Error('MathJax returned no SVG element.'); }}
        const errorNode = svg.querySelector('[data-mml-node="merror"][data-mjx-error]');
        if (errorNode) {{
            throw new Error(errorNode.getAttribute('data-mjx-error') || 'Invalid TeX input.');
        }}
        const rect = svg.getBoundingClientRect();
        const verticalAlign = parseFloat(getComputedStyle(svg).verticalAlign) || 0;
        svg.setAttribute('width', `${{rect.width}}px`);
        svg.setAttribute('height', `${{rect.height}}px`);
        svg.setAttribute('color', {foreground});
        svg.style.color = {foreground};
        const markup = svg.outerHTML.replaceAll('currentColor', {foreground});
        return JSON.stringify({{
            ok: true,
            svg: markup,
            width: rect.width,
            height: rect.height,
            verticalAlign: verticalAlign
        }});
    }} catch (error) {{
        return JSON.stringify({{ok: false, error: String(error)}});
    }}
}})()"""

    def _on_javascript_result(self, key: str, raw_result: object) -> None:
        if self._closed or not self._active or self._active[0] != key:
            return
        try:
            result = json.loads(raw_result) if isinstance(raw_result, str) else raw_result
            if not isinstance(result, dict) or not result.get("ok"):
                error = (
                    result.get("error", "Unknown MathJax error") if isinstance(result, dict) else str(result)
                )
                raise RuntimeError(error)

            width = float(result["width"])
            height = float(result["height"])
            if not (math.isfinite(width) and math.isfinite(height) and width > 0 and height > 0):
                raise ValueError("MathJax returned invalid image dimensions.")
            if width > 10000 or height > 10000:
                raise ValueError("MathJax formula is too large to render safely.")

            request = self._active[1]
            output_scale = min(1.0, max(float(request.max_width), 1.0) / width)
            output_width = width * output_scale
            output_height = height * output_scale
            image = self._rasterize_svg(
                str(result["svg"]),
                output_width,
                output_height,
                request.device_pixel_ratio,
            )
            rendered = MathJaxImage(
                key=key,
                image=image,
                logical_width=output_width,
                logical_height=output_height,
                vertical_align=float(result.get("verticalAlign", 0.0)) * output_scale,
            )
            self._cache[key] = rendered
            self._cache_bytes += int(image.sizeInBytes())
            self._cache.move_to_end(key)
            while len(self._cache) > self._MAX_CACHE_ENTRIES or self._cache_bytes > self._MAX_CACHE_BYTES:
                _evicted_key, evicted = self._cache.popitem(last=False)
                self._cache_bytes -= int(evicted.image.sizeInBytes())
            logger.info("Rendered MathJax formula %s", key[:10])
        except Exception as exc:
            self._failed[key] = str(exc)
            logger.warning("Could not render MathJax formula %s: %s", key[:10], exc)
        finally:
            self._active = None
            self.result_ready.emit(key)
            QTimer.singleShot(0, self._process_next)

    @staticmethod
    def _rasterize_svg(svg: str, width: float, height: float, device_pixel_ratio: float) -> QImage:
        ratio = max(1.0, min(float(device_pixel_ratio), 4.0))
        pixel_width = max(1, math.ceil(width * ratio))
        pixel_height = max(1, math.ceil(height * ratio))
        if (
            pixel_width > MathJaxRenderer._MAX_RASTER_DIMENSION
            or pixel_height > MathJaxRenderer._MAX_RASTER_DIMENSION
        ):
            raise ValueError("MathJax formula exceeds the maximum raster dimension.")
        if pixel_width * pixel_height > MathJaxRenderer._MAX_RASTER_PIXELS:
            raise ValueError("MathJax formula exceeds the maximum raster size.")
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        if not renderer.isValid():
            raise ValueError("MathJax returned invalid SVG data.")

        image = QImage(pixel_width, pixel_height, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter, QRectF(0, 0, pixel_width, pixel_height))
        painter.end()
        image.setDevicePixelRatio(ratio)
        return image

    def _on_request_timeout(self, key: str) -> None:
        if self._closed or not self._active or self._active[0] != key:
            return
        self._failed[key] = "MathJax rendering timed out."
        self._active = None
        logger.warning("MathJax rendering timed out for %s", key[:10])
        self.result_ready.emit(key)
        self._process_next()

    def _on_render_process_terminated(self, *_args) -> None:
        if not self._closed:
            self._disable("The MathJax WebEngine process terminated unexpectedly.")

    def _disable(self, reason: str) -> None:
        logger.warning(reason)
        self._disabled_reason = reason
        self._starting = False
        self._ready = False
        if self._active:
            self._failed[self._active[0]] = reason
            self.result_ready.emit(self._active[0])
            self._active = None
        while self._queue:
            key, _request = self._queue.popleft()
            self._queued_keys.discard(key)
            self._failed[key] = reason
            self.result_ready.emit(key)
        if self._page:
            self._page.deleteLater()
            self._page = None

    def shutdown(self) -> None:
        self._closed = True
        self._queue.clear()
        self._queued_keys.clear()
        self._active = None
        self._cache.clear()
        self._cache_bytes = 0
        if self._page:
            self._page.deleteLater()
            self._page = None
