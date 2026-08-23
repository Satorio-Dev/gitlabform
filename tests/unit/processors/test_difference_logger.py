import textwrap


from gitlabform.processors.util.difference_logger import DifferenceLogger


def test_empty_dict_current():
    current_config = dict()
    config_to_apply = {
        "foo": 123,
        "bar": "whatever",
    }
    result = DifferenceLogger.log_diff("test", current_config, config_to_apply, False, None, True)
    # the whitespace after "123" below is required!
    expected = textwrap.dedent("""
        test:
        foo: "???" => 123       
        bar: "???" => "whatever"
    """).strip()
    assert result == expected


def test_none_current():
    current_config = None
    config_to_apply = {
        "foo": 123,
        "bar": "whatever",
    }
    result = DifferenceLogger.log_diff("test", current_config, config_to_apply, False, None, True)
    # the whitespace after "123" below is required!
    expected = textwrap.dedent("""
        test:
        foo: "???" => 123       
        bar: "???" => "whatever"
    """).strip()
    assert result == expected


def test_diff_from_current():
    current_config = {
        "foo": 456,
        "bar": "whatever",
    }
    config_to_apply = {
        "foo": 123,
        "bar": "whatever",
    }
    result = DifferenceLogger.log_diff("test", current_config, config_to_apply, True, None, True)
    # the whitespace after "123" below is required!
    expected = textwrap.dedent("""
        test:
        foo: 456 => 123       
    """).strip()
    assert result == expected


def test_diff_output_no_changes():
    current_config = {
        "foo": 123,
        "bar": "whatever",
    }
    config_to_apply = {
        "foo": 123,
        "bar": "whatever",
    }
    result = DifferenceLogger.log_diff("test", current_config, config_to_apply, True, None, True)

    expected = textwrap.dedent("""

    """).strip()
    assert result == expected


class TestRemovedSide:
    @staticmethod
    def _diff(current, desired, **kwargs):
        return DifferenceLogger.log_diff("test", current, desired, test=True, **kwargs)

    def test_key_only_in_current_is_reported_with_the_marker(self):
        result = self._diff(
            {"kept": {"access_level": 30}, "gone": {"access_level": 40}},
            {"kept": {"access_level": 30}},
            removed_marker="(will be removed by enforce)",
        )

        assert "gone" in result
        assert "(will be removed by enforce)" in result

    def test_no_marker_means_that_side_stays_off(self):
        result = self._diff(
            {"declared": 1, "never_configured": "whatever"},
            {"declared": 1},
        )

        assert "never_configured" not in result

    def test_removal_survives_only_changed(self):
        result = self._diff(
            {"kept": 1, "gone": 2},
            {"kept": 1},
            only_changed=True,
            removed_marker="(only in GitLab)",
        )

        assert result == "test:\ngone: 2 => (only in GitLab)"

    def test_removal_is_reported_even_when_nothing_else_changes(self):
        result = self._diff({"gone": 2}, {}, removed_marker="(only in GitLab)")

        assert "gone" in result

    def test_hidden_key_stays_hidden_on_the_removal_side(self):
        result = self._diff(
            {"token": "s3cret"},
            {},
            hide_entries=["token"],
            removed_marker="(only in GitLab)",
        )

        assert "s3cret" not in result
        assert "<secret " in result
        assert "(only in GitLab)" in result
