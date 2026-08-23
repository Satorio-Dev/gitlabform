import pytest

from gitlabform import util

CORRUPTED_WITHOUT_WIDTH = [
    "a  aaaaaaaaaaaaaAaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "|aaaaaaaaa\"aaaaaaaaa\\aaaaaaaaaaaaAaaaaaaaaa'aa\\a a",
    "aaaaaaaaaaaaaaaaaaaaaaaaaa'aaaaaAa\\aaaaaaaaaaaa\\: a",
]

LONG_REGEX = (
    r"^(?:MERCH-[0-9]{2,6}|RELEASE|HOTFIX)\s*[:-]\s*.{10,}"
    r"(?:\(refs?\s*#[0-9]+\))?\s*(?:\[skip ci\]|\[ci skip\])?\s*(?:@[a-z0-9._-]+)?$"
)


def _round_trip(value: str) -> str:
    """Exactly what ConfigurationTransformer.convert_to_simple_types does."""
    config = {"projects_and_groups": {"group/project": {"project_push_rules": {"commit_message_regex": value}}}}
    dumped = util.yaml_config_to_string(config)
    loaded = util.configure_ruamel_yaml_loader(typ="safe", pure=True).load(dumped)
    return loaded["projects_and_groups"]["group/project"]["project_push_rules"]["commit_message_regex"]


@pytest.mark.parametrize("value", CORRUPTED_WITHOUT_WIDTH + [LONG_REGEX])
def test_a_long_value_survives_the_config_round_trip(value):
    assert _round_trip(value) == value


def test_the_dumped_config_is_not_wrapped():
    dumped = util.yaml_config_to_string({"projects_and_groups": {"group/project": {"a_long_key": LONG_REGEX}}})
    value_lines = [line for line in dumped.splitlines() if LONG_REGEX[:20] in line]
    assert value_lines, "the value did not survive to the dumped document at all"
    assert LONG_REGEX in value_lines[0], "the value was wrapped across lines"
