from collections.abc import Iterable, Mapping, Sequence

UNDEFINED = "Undefined"

CategoryRanges = Mapping[str, Sequence[tuple[int, int]]]

# Top-level categories of the Newznab/Torznab standard category list.
DEFAULT_CATEGORY_RANGES: dict[str, list[tuple[int, int]]] = {
    "Console": [(1000, 1999)],
    "Movies": [(2000, 2999)],
    "Audio": [(3000, 3999)],
    "PC": [(4000, 4999)],
    "TV": [(5000, 5999)],
    "XXX": [(6000, 6999)],
    "Books": [(7000, 7999)],
    "Other": [(8000, 8999)],
}


def merge_ranges(
    defaults: CategoryRanges, overrides: CategoryRanges | None
) -> dict[str, list[tuple[int, int]]]:
    """Feed-specific entries come first so they win over the defaults."""
    merged = {name: list(ranges) for name, ranges in (overrides or {}).items()}
    for name, ranges in defaults.items():
        merged.setdefault(name, list(ranges))
    return merged


def map_categories(category_ids: Iterable[int], ranges: CategoryRanges) -> list[str]:
    """Map category ids to unique names, keeping the order of first appearance.

    Ids outside every range (e.g. the custom 100000+ ones) are ignored. If
    nothing maps at all, the result is ``["Undefined"]``.
    """
    names: list[str] = []
    for category_id in category_ids:
        for name, name_ranges in ranges.items():
            if any(low <= category_id <= high for low, high in name_ranges):
                if name not in names:
                    names.append(name)
                break
    return names or [UNDEFINED]
