"""Безопасный рендер Markdown для текста ДЗ.

Текст пишется в боте (Markdown), а на сайте показывается уже как HTML.
Для безопасности HTML санитизируется через bleach.
Если markdown/bleach не установлены — отдаём экранированный plain text.
"""
from markupsafe import Markup

try:
    import markdown as _markdown
except ImportError:  # pragma: no cover
    _markdown = None

try:
    import bleach as _bleach
except ImportError:  # pragma: no cover
    _bleach = None


ALLOWED_TAGS = [
    'p', 'br', 'strong', 'b', 'em', 'i', 'u', 's', 'code', 'pre', 'a',
    'ul', 'ol', 'li', 'blockquote', 'hr',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'span',
]
ALLOWED_ATTRS = {'a': ['href', 'title'], 'span': ['class']}


def render(text):
    """Markdown -> безопасный HTML (Markup, готов к {{ ... | md }})."""
    if not text:
        return Markup('')
    if _markdown is None:
        # без markdown — хотя бы экранируем
        if _bleach is not None:
            return Markup(_bleach.clean(text, tags=[], strip=True))
        return Markup(str(text).replace('&', '&amp;').replace('<', '&lt;'))
    html = _markdown.markdown(text, extensions=['nl2br', 'sane_lists'])
    if _bleach is not None:
        html = _bleach.clean(
            html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS,
            protocols=['http', 'https', 'mailto'], strip=True,
        )
    return Markup(html)
