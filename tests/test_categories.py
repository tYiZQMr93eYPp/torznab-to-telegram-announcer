from torznab_to_telegram_announcer.categories import (
    DEFAULT_CATEGORY_RANGES,
    UNDEFINED,
    map_categories,
    merge_ranges,
)


def test_standard_ranges():
    assert map_categories([2040], DEFAULT_CATEGORY_RANGES) == ["Movies"]
    assert map_categories([5070], DEFAULT_CATEGORY_RANGES) == ["TV"]
    assert map_categories([1010, 3000, 4050, 6010, 7020, 8010], DEFAULT_CATEGORY_RANGES) == [
        "Console",
        "Audio",
        "PC",
        "XXX",
        "Books",
        "Other",
    ]


def test_range_boundaries():
    assert map_categories([2000], DEFAULT_CATEGORY_RANGES) == ["Movies"]
    assert map_categories([2999], DEFAULT_CATEGORY_RANGES) == ["Movies"]
    assert map_categories([3000], DEFAULT_CATEGORY_RANGES) == ["Audio"]


def test_custom_ids_are_ignored_when_a_standard_one_matches():
    assert map_categories([5000, 100002], DEFAULT_CATEGORY_RANGES) == ["TV"]
    assert map_categories([100001, 2000], DEFAULT_CATEGORY_RANGES) == ["Movies"]


def test_names_are_unique_and_ordered():
    assert map_categories([5040, 2000, 5070], DEFAULT_CATEGORY_RANGES) == ["TV", "Movies"]


def test_undefined_only_when_nothing_matches():
    assert map_categories([], DEFAULT_CATEGORY_RANGES) == [UNDEFINED]
    assert map_categories([100001, 0], DEFAULT_CATEGORY_RANGES) == [UNDEFINED]


def test_feed_overrides_take_precedence_and_extend():
    ranges = merge_ranges(DEFAULT_CATEGORY_RANGES, {"Anime": [(5070, 5070)], "Movies": [(2000, 2050)]})

    assert map_categories([5070], ranges) == ["Anime"]
    assert map_categories([5040], ranges) == ["TV"]
    assert map_categories([2060], ranges) == [UNDEFINED]
