from unittest.mock import MagicMock, patch

from gitlabform.gitlab import GitLab
from gitlabform.processors import AbstractProcessor


class _TestableProcessor(AbstractProcessor):
    def _process_configuration(self, project_or_project_and_group: str, configuration: dict) -> None:
        pass


def _make_processor(name: str = "test_section") -> _TestableProcessor:
    with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
        return _TestableProcessor(name, MagicMock(GitLab))


class TestPrintDiff:
    def test_logs_not_supported_at_debug_when_current_state_returns_none(self, caplog) -> None:
        # Base class implementation of _get_current_state returns None (opt out)
        processor = _make_processor("some_section")

        with caplog.at_level("DEBUG"):
            processor._print_diff("group/project", {"foo": 1}, diff_only_changed=False)

        matching = [r for r in caplog.records if "Diffing for section 'some_section'" in r.message]
        assert len(matching) == 1
        assert matching[0].levelname == "DEBUG"

    def test_desired_state_defaults_to_entity_config_unchanged(self) -> None:
        class CurrentOnlyProcessor(_TestableProcessor):
            def _get_current_state(self, project_or_project_and_group):
                return {"foo": "from-gitlab"}

        with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
            processor = CurrentOnlyProcessor("test_section", MagicMock(GitLab))

        with patch("gitlabform.processors.abstract_processor.DifferenceLogger") as logger:
            processor._print_diff("group/project", {"foo": "from-config"}, diff_only_changed=True)

        logger.log_diff.assert_called_once_with(
            "test_section changes",
            {"foo": "from-gitlab"},
            {"foo": "from-config"},
            only_changed=True,
            removed_marker=None,
        )

    def test_current_state_receives_project_path(self) -> None:
        received: dict = {}

        class OverridingProcessor(_TestableProcessor):
            def _get_current_state(self, project_or_project_and_group):
                received["path"] = project_or_project_and_group
                return {}

        with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
            processor = OverridingProcessor("t", MagicMock(GitLab))

        with patch("gitlabform.processors.abstract_processor.DifferenceLogger"):
            processor._print_diff("group/project", {"cfg": 1}, diff_only_changed=False)

        assert received == {"path": "group/project"}

    def test_desired_state_override_normalizes_config(self) -> None:
        class NormalizingProcessor(_TestableProcessor):
            def _get_current_state(self, project_or_project_and_group):
                return {"foo": "gl:x"}

            def _get_desired_state(self, entity_config):
                return {k: f"cfg:{v}" for k, v in entity_config.items() if k != "meta"}

        with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
            processor = NormalizingProcessor("t", MagicMock(GitLab))

        with patch("gitlabform.processors.abstract_processor.DifferenceLogger") as logger:
            processor._print_diff("group/project", {"foo": "y", "meta": "drop"}, diff_only_changed=False)

        logger.log_diff.assert_called_once_with(
            "t changes",
            {"foo": "gl:x"},
            {"foo": "cfg:y"},
            only_changed=False,
            removed_marker=None,
        )


class TestRemovedSideOfTheDiff:
    """Which sections report an entity that is in GitLab and not in the config."""

    class _EntityKeyedProcessor(_TestableProcessor):
        diff_keys_are_entities = True

        def _get_current_state(self, project_or_project_and_group):
            return {"kept": {"access_level": 30}, "gone": {"access_level": 40}}

    @staticmethod
    def _make(cls, name="test_section"):
        with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
            return cls(name, MagicMock(GitLab))

    def test_attribute_keyed_section_reports_no_removals(self, caplog) -> None:
        class SettingsLikeProcessor(_TestableProcessor):
            def _get_current_state(self, project_or_project_and_group):
                return {"declared": 1, "never_configured": "whatever"}

        processor = self._make(SettingsLikeProcessor)

        with caplog.at_level("INFO"):
            processor._print_diff("group/project", {"declared": 1}, diff_only_changed=True)

        assert "never_configured" not in caplog.text

    def test_entity_keyed_section_without_enforce_says_only_in_gitlab(self, caplog) -> None:
        processor = self._make(self._EntityKeyedProcessor)

        with caplog.at_level("INFO"):
            processor._print_diff("group/project", {"kept": {"access_level": 30}}, diff_only_changed=True)

        assert "gone" in caplog.text
        assert "(only in GitLab)" in caplog.text

    def test_entity_keyed_section_with_enforce_says_it_will_be_removed(self, caplog) -> None:
        processor = self._make(self._EntityKeyedProcessor)

        with caplog.at_level("INFO"):
            processor._print_diff(
                "group/project",
                {"enforce": True, "kept": {"access_level": 30}},
                diff_only_changed=True,
            )

        assert "gone" in caplog.text
        assert "(will be removed by enforce)" in caplog.text

    def test_marker_is_none_for_a_section_that_is_not_entity_keyed(self) -> None:
        processor = self._make(_TestableProcessor)

        assert processor._diff_removed_marker({"enforce": True}) is None


class TestEmptySectionInDryRun:
    def test_empty_section_reaches_the_diff_as_an_empty_config(self) -> None:
        seen: list = []

        class RecordingProcessor(_TestableProcessor):
            def _get_current_state(self, project_or_project_and_group):
                return {"foo": "from-gitlab"}

            def _get_desired_state(self, entity_config):
                seen.append(entity_config)
                return {k: v for k, v in entity_config.items()}

        with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
            processor = RecordingProcessor("test_section", MagicMock(GitLab))

        processor.process("group/project", {"test_section": None}, True, True, MagicMock())

        assert seen == [{}]

    def test_empty_section_produces_no_diff_output(self, caplog) -> None:
        class CurrentOnlyProcessor(_TestableProcessor):
            def _get_current_state(self, project_or_project_and_group):
                return {"foo": "from-gitlab"}

        with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
            processor = CurrentOnlyProcessor("test_section", MagicMock(GitLab))

        with caplog.at_level("INFO"):
            processor.process("group/project", {"test_section": None}, True, True, MagicMock())

        assert not [r for r in caplog.records if "test_section changes" in r.message]

    def test_empty_project_section_does_not_break_other_sections(self) -> None:
        class CurrentOnlyProcessor(_TestableProcessor):
            def _get_current_state(self, project_or_project_and_group):
                return {"foo": "from-gitlab"}

        with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
            processor = CurrentOnlyProcessor("test_section", MagicMock(GitLab))

        processor.process(
            "group/project",
            {"project": None, "test_section": {"foo": "from-config"}},
            True,
            True,
            MagicMock(),
        )


class TestRecursiveDiffAnalyzer:
    _cfg_a = [
        {
            "access_level": 40,
            "access_level_description": "Maintainers",
            "user_id": None,
            "group_id": None,
            "group_inheritance_type": 0,
        },
        {
            "access_level": 40,
            "access_level_description": "John Doe",
            "user_id": 967,
            "group_id": None,
            "group_inheritance_type": 0,
        },
    ]

    _cfg_b = [
        {"access_level": 40, "group_inheritance_type": 0},
        {"user_id": 967},
    ]

    def test__equal_configurations(self) -> None:
        assert not AbstractProcessor.recursive_diff_analyzer("deploy_access_levels", self._cfg_a, self._cfg_b)

    def test__unequal_configurations(self) -> None:
        modified_cfg = self._cfg_b.copy()

        modified_cfg[1]["group_inheritance_type"] = 1

        assert AbstractProcessor.recursive_diff_analyzer("deploy_access_levels", self._cfg_a, modified_cfg)


class TestRecursiveDiffAnalyzerIsOrderInsensitive:
    @staticmethod
    def _in_gitlab() -> list:
        return [
            {
                "access_level": 30,
                "access_level_description": "Developers",
                "user_id": None,
                "group_id": None,
                "group_inheritance_type": 0,
            },
            {
                "access_level": 40,
                "access_level_description": "John Doe",
                "user_id": 967,
                "group_id": None,
                "group_inheritance_type": 0,
            },
        ]

    @staticmethod
    def _in_config() -> list:
        return [
            {"access_level": 40, "user_id": 967},
            {"access_level": 30},
        ]

    def test__the_same_entries_in_another_order_are_not_a_difference(self) -> None:
        assert not AbstractProcessor.recursive_diff_analyzer(
            "deploy_access_levels", self._in_gitlab(), self._in_config()
        )

        assert not AbstractProcessor.recursive_diff_analyzer(
            "deploy_access_levels", list(reversed(self._in_gitlab())), self._in_config()
        )

        assert not AbstractProcessor.recursive_diff_analyzer(
            "deploy_access_levels", self._in_gitlab(), list(reversed(self._in_config()))
        )

    def test__another_composition_is_a_difference_in_every_order(self) -> None:
        in_config = self._in_config()
        in_config[0] = {"access_level": 40, "user_id": 968}

        assert AbstractProcessor.recursive_diff_analyzer("deploy_access_levels", self._in_gitlab(), in_config)

        assert AbstractProcessor.recursive_diff_analyzer(
            "deploy_access_levels", list(reversed(self._in_gitlab())), in_config
        )

        assert AbstractProcessor.recursive_diff_analyzer(
            "deploy_access_levels", self._in_gitlab(), list(reversed(in_config))
        )

    def test__an_entry_gitlab_reports_nothing_of_is_a_difference(self) -> None:
        in_config = self._in_config()
        in_config[1] = {"group_id": 12}

        assert AbstractProcessor.recursive_diff_analyzer("deploy_access_levels", self._in_gitlab(), in_config)

    def test__another_value_of_a_declared_key_is_a_difference(self) -> None:
        in_config = self._in_config()
        in_config[0] = {"access_level": 40, "user_id": 967, "group_inheritance_type": 1}

        assert AbstractProcessor.recursive_diff_analyzer("deploy_access_levels", self._in_gitlab(), in_config)

    def test__one_counterpart_is_not_spent_on_two_entries(self) -> None:
        in_gitlab = [
            {"access_level": 40, "user_id": 967},
            {"access_level": 40, "user_id": 968},
        ]
        in_config = [
            {"access_level": 40},
            {"access_level": 40},
        ]

        assert not AbstractProcessor.recursive_diff_analyzer("deploy_access_levels", in_gitlab, in_config)

        in_config[1] = {"access_level": 30}

        assert AbstractProcessor.recursive_diff_analyzer("deploy_access_levels", in_gitlab, in_config)

    def test__an_entry_with_a_choice_leaves_the_counterpart_another_entry_needs(self) -> None:
        in_gitlab = [
            {"access_level": 40, "user_id": 967},
            {"access_level": 40, "user_id": 968},
        ]
        in_config = [
            {"access_level": 40},
            {"user_id": 967},
        ]

        assert not AbstractProcessor.recursive_diff_analyzer("deploy_access_levels", in_gitlab, in_config)

        in_config[1] = {"user_id": 969}

        assert AbstractProcessor.recursive_diff_analyzer("deploy_access_levels", in_gitlab, in_config)

    def test__another_number_of_entries_is_a_difference(self) -> None:
        assert AbstractProcessor.recursive_diff_analyzer(
            "deploy_access_levels", self._in_gitlab(), self._in_config()[:1]
        )

    def test__nested_lists_are_compared_regardless_of_order(self) -> None:
        in_gitlab = [{"name": "prod", "rules": [{"user_id": 967}, {"user_id": 968}]}]
        in_config = [{"name": "prod", "rules": [{"user_id": 968}, {"user_id": 967}]}]

        assert not AbstractProcessor.recursive_diff_analyzer("protected_environments", in_gitlab, in_config)

        in_config[0]["rules"] = [{"user_id": 968}, {"user_id": 969}]

        assert AbstractProcessor.recursive_diff_analyzer("protected_environments", in_gitlab, in_config)

    def test__entries_that_are_not_dicts_are_compared_by_value(self) -> None:
        assert not AbstractProcessor.recursive_diff_analyzer("some_key", ["a", "b"], ["b", "a"])
        assert AbstractProcessor.recursive_diff_analyzer("some_key", ["a", "b"], ["a", "c"])


class TestNeedsUpdateReadsEveryKey:
    _ACCESS_LEVEL_LISTS = ("merge_access_levels", "push_access_levels", "unprotect_access_levels")

    @staticmethod
    def _processor_with_custom_analyzers() -> _TestableProcessor:
        processor = _make_processor("branches")
        for key in TestNeedsUpdateReadsEveryKey._ACCESS_LEVEL_LISTS:
            processor.custom_diff_analyzers[key] = AbstractProcessor.recursive_diff_analyzer
        return processor

    @staticmethod
    def _in_gitlab() -> dict:
        entity = {"approval_rules": [{"name": "default", "approvals_required": 1}]}
        for key in TestNeedsUpdateReadsEveryKey._ACCESS_LEVEL_LISTS:
            entity[key] = [{"access_level": 40, "user_id": None, "group_id": None}]
        return entity

    @staticmethod
    def _in_config() -> dict:
        entity = {"approval_rules": [{"name": "default", "approvals_required": 1}]}
        for key in TestNeedsUpdateReadsEveryKey._ACCESS_LEVEL_LISTS:
            entity[key] = [{"access_level": 40}]
        return entity

    def test__an_entity_that_matches_on_every_key_needs_no_update(self) -> None:
        assert not self._processor_with_custom_analyzers()._needs_update(self._in_gitlab(), self._in_config())

    def test__a_difference_behind_matching_custom_analyzed_keys_is_not_lost(self) -> None:
        in_config = self._in_config()
        in_config["approval_rules"] = [{"name": "default", "approvals_required": 2}]

        assert self._processor_with_custom_analyzers()._needs_update(self._in_gitlab(), in_config)

    def test__a_difference_in_one_custom_analyzed_key_survives_the_others(self) -> None:
        in_config = self._in_config()
        in_config["unprotect_access_levels"] = [{"access_level": 30}]

        assert self._processor_with_custom_analyzers()._needs_update(self._in_gitlab(), in_config)

    def test__every_custom_analyzed_key_is_read(self) -> None:
        read: list = []

        def recording_analyzer(key, in_gitlab, in_configuration) -> bool:
            read.append(key)
            return False

        processor = _make_processor("branches")
        for key in self._ACCESS_LEVEL_LISTS:
            processor.custom_diff_analyzers[key] = recording_analyzer

        assert not processor._needs_update(self._in_gitlab(), self._in_config())
        assert sorted(read) == sorted(self._ACCESS_LEVEL_LISTS)
