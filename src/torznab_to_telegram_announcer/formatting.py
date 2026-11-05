import re
from decimal import ROUND_HALF_UP, Decimal

from .categories import UNDEFINED, CategoryRanges, map_categories
from .models import Release

CATEGORY_EMOJI = {
    "Movies": "🎬",
    "TV": "📺",
    "Audio": "🎵",
    "PC": "💻",
    "Console": "🎮",
    "Books": "📚",
    "XXX": "🔞",
}
DEFAULT_EMOJI = "📦"

_SIZE_UNITS = ("KiB", "MiB", "GiB", "TiB", "PiB")
_MARKDOWN_SPECIALS = re.compile(r"[\\`*_{}\[\]()#+\-.!<>&~|]")


def escape_markdown(text: str) -> str:
    """Backslash-escape CommonMark punctuation; Apprise converts it for Telegram."""
    return _MARKDOWN_SPECIALS.sub(lambda match: "\\" + match.group(0), text)


def format_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    value = float(size)
    for unit in _SIZE_UNITS:
        value /= 1024
        if value < 1024 or unit == _SIZE_UNITS[-1]:
            return f"{value:.2f} {unit}"
    raise AssertionError("unreachable")


def format_percentage(value: Decimal) -> str:
    rounded = value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    text = format(rounded, "f")
    return (text.rstrip("0").rstrip(".") if "." in text else text) + "%"


def free_percentage(download_factor: Decimal) -> Decimal:
    """Share of the download that does not count: factor 0 is 100% free, 1 is 0%."""
    return min(max((1 - download_factor) * 100, Decimal(0)), Decimal(100))


def _code(text: str) -> str:
    return "`" + text.replace("`", "'") + "`"


def format_release(release: Release, ranges: CategoryRanges) -> str:
    categories = map_categories(release.category_ids, ranges)
    emoji = CATEGORY_EMOJI.get(categories[0], DEFAULT_EMOJI) if categories[0] != UNDEFINED else DEFAULT_EMOJI

    lines = [
        f"{emoji} **{escape_markdown(release.title)}**",
        "",
        f"📂 **Category:** {escape_markdown(', '.join(categories))}",
    ]
    if release.size is not None:
        lines.append(f"💾 **Size:** {format_size(release.size)}")
    lines.append(f"💸 **Free:** {format_percentage(free_percentage(release.download_factor))}")
    if release.tags:
        lines.append(f"🏷️ **Tags:** {_code(','.join(release.tags))}")
    if release.url:
        lines.append(f"🔗 <{release.url.replace('>', '%3E')}>")
    if release.imdb_id:
        lines.append(f"🎞️ **IMDb:** {_code('tt' + release.imdb_id)}")
    if release.tvdb_id:
        lines.append(f"📺 **TVDB:** {_code(release.tvdb_id)}")
    if release.tmdb_id:
        lines.append(f"🎥 **TMDB:** {_code(release.tmdb_id)}")
    return "\n".join(lines)
