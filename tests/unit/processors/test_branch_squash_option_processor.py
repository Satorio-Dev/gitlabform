from typing import Any
from unittest.mock import MagicMock

import pytest
from gitlab import GitlabGetError, GitlabUpdateError
from gql.transport.exceptions import TransportQueryError

from gitlabform.constants import EXIT_INVALID_INPUT, EXIT_PROCESSING_ERROR
from gitlabform.processors.project.branch_squash_option_processor import (
    BranchSquashOptionProcessor,
)
from gitlabform.processors.project.branches_processor import BranchesProcessor

BRANCH_RULE_GID = "gid://gitlab/Projects::BranchRule/"
ALL_BRANCHES_GID = "gid://gitlab/Projects::AllBranchesRule/"


def _rule(name: str, rule_id: str, option: str | None = None, gid_prefix: str = BRANCH_RULE_GID):
    return {
        "id": f"{gid_prefix}{rule_id}",
        "name": name,
        "squashOption": None if option is None else {"option": option},
    }


def _page(nodes: list, has_next_page: bool = False, end_cursor: str | None = None):
    return {
        "project": {
            "branchRules": {
                "pageInfo": {"hasNextPage": has_next_page, "endCursor": end_cursor},
                "nodes": nodes,
            }
        }
    }


def _mutation_ok(field: str):
    payload: dict[str, Any] = {"errors": []}
    if field != "branchRuleSquashOptionDelete":
        payload["squashOption"] = {"option": "Require"}
    return {field: payload}


class TestVocabulary:
    """The three vocabularies of one setting are the trap of this API - pin them."""

    def test_write_and_read_vocabularies_describe_the_same_set_of_values(self):
        assert set(BranchSquashOptionProcessor.GITLAB_TEXT_TO_CONFIG.values()) == set(
            BranchSquashOptionProcessor.CONFIG_TO_ENUM
        )

    def test_config_values_are_the_graphql_enum_lowercased(self):
        for config_value, enum_value in BranchSquashOptionProcessor.CONFIG_TO_ENUM.items():
            assert enum_value == config_value.upper()

    def test_inherit_is_not_one_of_the_gitlab_values(self):
        assert BranchSquashOptionProcessor.INHERIT not in BranchSquashOptionProcessor.CONFIG_TO_ENUM


class TestDesiredState:
    def setup_method(self):
        self.processor = BranchSquashOptionProcessor(MagicMock(), strict=False)

    def test_takes_only_the_branches_that_declare_the_key(self):
        desired = self.processor._get_desired_state(
            {
                "avalon": {"protected": True, "squash_option": "always"},
                "production": {"protected": True, "squash_option": "never"},
                "main": {"protected": True, "allowed_to_push": [{"user_id": 1}]},
                "feature/*": {"protected": False},
            }
        )

        assert desired == {"avalon": "always", "production": "never"}

    def test_no_key_is_not_the_same_as_inherit(self):
        assert self.processor._get_desired_state({"main": {"protected": True}}) == {}
        assert self.processor._get_desired_state({"main": {"protected": True, "squash_option": "inherit"}}) == {
            "main": "inherit"
        }

    def test_unknown_value_is_refused_and_the_allowed_values_are_named(self, caplog):
        with pytest.raises(SystemExit) as exit_info, caplog.at_level("CRITICAL"):
            self.processor._get_desired_state({"main": {"protected": True, "squash_option": "yes"}})

        assert exit_info.value.code == EXIT_INVALID_INPUT
        assert "always" in caplog.text and "inherit" in caplog.text

    def test_project_level_value_is_refused_with_its_branch_level_equivalent(self, caplog):
        with pytest.raises(SystemExit), caplog.at_level("CRITICAL"):
            self.processor._get_desired_state({"main": {"protected": True, "squash_option": "default_off"}})

        assert "project_settings.squash_option" in caplog.text
        assert "'allowed'" in caplog.text

    def test_uppercase_enum_value_is_refused_with_a_hint(self, caplog):
        with pytest.raises(SystemExit), caplog.at_level("CRITICAL"):
            self.processor._get_desired_state({"main": {"protected": True, "squash_option": "ALWAYS"}})

        assert "Did you mean 'always'" in caplog.text

    def test_squash_option_on_an_unprotected_branch_is_refused(self, caplog):
        with pytest.raises(SystemExit) as exit_info, caplog.at_level("CRITICAL"):
            self.processor._get_desired_state({"main": {"protected": False, "squash_option": "always"}})

        assert exit_info.value.code == EXIT_INVALID_INPUT
        assert "not configured as" in caplog.text and "protected" in caplog.text


class TestCurrentState:
    def setup_method(self):
        self.processor = BranchSquashOptionProcessor(MagicMock(), strict=False)
        self.processor.gl = MagicMock()

    def test_maps_gitlab_text_to_config_values_and_no_override_to_inherit(self):
        self.processor.gl.graphql.execute.return_value = _page(
            [
                _rule("avalon", "1", "Require"),
                _rule("production", "2", "Do not allow"),
                _rule("develop", "3", "Encourage"),
                _rule("qa", "4", "Allow"),
                _rule("main", "5", None),
            ]
        )

        assert self.processor._get_current_state("group/project") == {
            "avalon": "always",
            "production": "never",
            "develop": "encouraged",
            "qa": "allowed",
            "main": "inherit",
        }

    def test_the_project_wide_pseudo_rule_is_not_a_branch(self):
        self.processor.gl.graphql.execute.return_value = _page(
            [
                _rule("All branches", "999", "Allow", gid_prefix=ALL_BRANCHES_GID),
                _rule("main", "1", "Require"),
            ]
        )

        assert self.processor._get_current_state("group/project") == {"main": "always"}

    def test_unknown_gitlab_text_is_refused_instead_of_guessed(self, caplog):
        self.processor.gl.graphql.execute.return_value = _page([_rule("main", "1", "Strongly encourage")])

        with pytest.raises(SystemExit) as exit_info, caplog.at_level("CRITICAL"):
            self.processor._get_current_state("group/project")

        assert exit_info.value.code == EXIT_PROCESSING_ERROR
        assert "Strongly encourage" in caplog.text

    def test_two_rules_with_the_same_name_are_refused_not_resolved(self, caplog):
        self.processor.gl.graphql.execute.return_value = _page(
            [_rule("main", "1", "Require"), _rule("main", "2", "Do not allow")]
        )

        with pytest.raises(SystemExit) as exit_info, caplog.at_level("CRITICAL"):
            self.processor._get_current_state("group/project")

        assert exit_info.value.code == EXIT_PROCESSING_ERROR
        assert "ambiguous" in caplog.text
        assert f"{BRANCH_RULE_GID}1" in caplog.text and f"{BRANCH_RULE_GID}2" in caplog.text

    def test_every_page_is_read(self):
        self.processor.gl.graphql.execute.side_effect = [
            _page([_rule("main", "1", "Require")], has_next_page=True, end_cursor="CURSOR"),
            _page([_rule("production", "2", "Do not allow")]),
        ]

        assert self.processor._get_current_state("group/project") == {
            "main": "always",
            "production": "never",
        }
        assert self.processor.gl.graphql.execute.call_args_list[1].kwargs["variable_values"]["after"] == "CURSOR"

    def test_a_truncated_list_without_a_cursor_is_refused(self, caplog):
        self.processor.gl.graphql.execute.return_value = _page(
            [_rule("main", "1", "Require")], has_next_page=True, end_cursor=None
        )

        with pytest.raises(SystemExit) as exit_info, caplog.at_level("CRITICAL"):
            self.processor._get_current_state("group/project")

        assert exit_info.value.code == EXIT_PROCESSING_ERROR
        assert "truncated" in caplog.text

    def test_missing_project_is_an_error_not_an_empty_result(self):
        self.processor.gl.graphql.execute.return_value = {"project": None}

        with pytest.raises(GitlabGetError):
            self.processor._get_current_state("group/project")

    def test_null_branch_rules_is_an_error_not_an_empty_result(self):
        self.processor.gl.graphql.execute.return_value = {"project": {"branchRules": None}}

        with pytest.raises(GitlabGetError):
            self.processor._get_current_state("group/project")


class TestReconciliation:
    """The three-state table: no override / an override / a different override."""

    def setup_method(self):
        self.processor = BranchSquashOptionProcessor(MagicMock(), strict=False)
        self.processor.gl = MagicMock()

    def _run(self, rules_page, config):
        self.processor.gl.graphql.execute.side_effect = [rules_page] + [
            _mutation_ok(field)
            for field in (
                "branchRuleSquashOptionCreate",
                "branchRuleSquashOptionUpdate",
                "branchRuleSquashOptionDelete",
            )
        ]
        self.processor._process_configuration("group/project", {"branches": config})
        return self.processor.gl.graphql.execute.call_args_list[1:]

    def test_no_override_and_a_value_creates_it(self):
        calls = self._run(
            _page([_rule("avalon", "10", None)]),
            {"avalon": {"protected": True, "squash_option": "always"}},
        )

        assert len(calls) == 1
        assert "branchRuleSquashOptionCreate" in calls[0].args[0]
        assert calls[0].kwargs["variable_values"] == {
            "branchRuleId": f"{BRANCH_RULE_GID}10",
            "squashOption": "ALWAYS",
        }

    def test_a_different_value_updates_it(self):
        calls = self._run(
            _page([_rule("avalon", "10", "Allow")]),
            {"avalon": {"protected": True, "squash_option": "always"}},
        )

        assert len(calls) == 1
        assert "branchRuleSquashOptionUpdate" in calls[0].args[0]
        assert calls[0].kwargs["variable_values"]["squashOption"] == "ALWAYS"

    def test_the_same_value_changes_nothing(self):
        assert (
            self._run(
                _page([_rule("avalon", "10", "Require")]),
                {"avalon": {"protected": True, "squash_option": "always"}},
            )
            == []
        )

    def test_inherit_deletes_an_existing_override(self):
        calls = self._run(
            _page([_rule("avalon", "10", "Require")]),
            {"avalon": {"protected": True, "squash_option": "inherit"}},
        )

        assert len(calls) == 1
        assert "branchRuleSquashOptionDelete" in calls[0].args[0]
        assert calls[0].kwargs["variable_values"] == {"branchRuleId": f"{BRANCH_RULE_GID}10"}

    def test_inherit_without_an_override_changes_nothing(self):
        assert (
            self._run(
                _page([_rule("avalon", "10", None)]),
                {"avalon": {"protected": True, "squash_option": "inherit"}},
            )
            == []
        )

    def test_a_branch_without_squash_option_is_not_touched(self):
        assert (
            self._run(
                _page([_rule("main", "10", "Require")]),
                {"main": {"protected": True, "allowed_to_push": [{"user_id": 1}]}},
            )
            == []
        )

    def test_no_branch_rule_is_loud_and_applies_nothing(self, caplog):
        with caplog.at_level("ERROR"):
            calls = self._run(
                _page([_rule("main", "10", None)]),
                {"avalon": {"protected": True, "squash_option": "always"}},
            )

        assert calls == []
        assert "NOT applied" in caplog.text
        assert "avalon" in caplog.text

    def test_no_branch_rule_in_strict_mode_stops_the_run(self, caplog):
        self.processor.strict = True
        with pytest.raises(SystemExit) as exit_info, caplog.at_level("CRITICAL"):
            self._run(
                _page([_rule("main", "10", None)]),
                {"avalon": {"protected": True, "squash_option": "always"}},
            )

        assert exit_info.value.code == EXIT_PROCESSING_ERROR

    def test_targeting_the_project_wide_pseudo_rule_is_refused(self, caplog):
        with pytest.raises(SystemExit) as exit_info, caplog.at_level("CRITICAL"):
            self._run(
                _page([_rule("All branches", "999", "Allow", gid_prefix=ALL_BRANCHES_GID)]),
                {"All branches": {"protected": True, "squash_option": "always"}},
            )

        assert exit_info.value.code == EXIT_INVALID_INPUT
        assert "project_settings.squash_option" in caplog.text

    def test_errors_in_the_mutation_payload_are_raised(self):
        self.processor.gl.graphql.execute.side_effect = [
            _page([_rule("avalon", "10", None)]),
            {"branchRuleSquashOptionCreate": {"errors": ["Squash option already exists"]}},
        ]

        with pytest.raises(GitlabUpdateError, match="Squash option already exists"):
            self.processor._process_configuration(
                "group/project", {"branches": {"avalon": {"protected": True, "squash_option": "always"}}}
            )

    def test_a_graphql_transport_error_is_raised_not_swallowed(self):
        self.processor.gl.graphql.execute.side_effect = [
            _page([_rule("avalon", "10", None)]),
            TransportQueryError("boom", errors=[{"message": "Squash option is not available"}]),
        ]

        with pytest.raises(GitlabUpdateError, match="Squash option is not available"):
            self.processor._process_configuration(
                "group/project", {"branches": {"avalon": {"protected": True, "squash_option": "always"}}}
            )

    def test_the_branch_rules_are_read_once_per_project(self):
        self._run(
            _page([_rule("avalon", "10", "Allow"), _rule("production", "11", "Allow")]),
            {
                "avalon": {"protected": True, "squash_option": "always"},
                "production": {"protected": True, "squash_option": "never"},
            },
        )
        reads = [call for call in self.processor.gl.graphql.execute.call_args_list if "branchRules" in call.args[0]]
        assert len(reads) == 1


class TestDryRunDiff:
    def setup_method(self):
        self.processor = BranchSquashOptionProcessor(MagicMock(), strict=False)
        self.processor.gl = MagicMock()

    def test_the_diff_is_labelled_after_squash_option_not_after_the_section(self, caplog):
        self.processor.gl.graphql.execute.return_value = _page([_rule("avalon", "10", "Allow")])

        with caplog.at_level("INFO"):
            self.processor._print_diff(
                "group/project",
                {"avalon": {"protected": True, "squash_option": "always"}},
                diff_only_changed=False,
            )

        assert "branches squash_option changes" in caplog.text
        assert '"allowed" => "always"' in caplog.text

    def test_a_branch_with_no_rule_says_so_in_the_diff(self, caplog):
        self.processor.gl.graphql.execute.return_value = _page([_rule("main", "10", None)])

        with caplog.at_level("INFO"):
            self.processor._print_diff(
                "group/project",
                {"avalon": {"protected": True, "squash_option": "always"}},
                diff_only_changed=False,
            )

        assert "(no branch rule)" in caplog.text

    def test_nothing_is_read_from_gitlab_when_no_branch_declares_the_key(self, caplog):
        with caplog.at_level("INFO"):
            self.processor._print_diff("group/project", {"main": {"protected": True}}, diff_only_changed=False)

        self.processor.gl.graphql.execute.assert_not_called()
        assert "branches squash_option changes" not in caplog.text

    def test_the_diff_refuses_an_ambiguous_project_too(self, caplog):
        self.processor.gl.graphql.execute.return_value = _page(
            [_rule("main", "1", "Require"), _rule("main", "2", "Allow")]
        )

        with pytest.raises(SystemExit), caplog.at_level("CRITICAL"):
            self.processor._print_diff(
                "group/project",
                {"main": {"protected": True, "squash_option": "always"}},
                diff_only_changed=False,
            )


class TestBranchesProcessorDoesNotShipSquashOptionToRest:
    def setup_method(self):
        self.processor = BranchesProcessor(MagicMock(), strict=False)
        self.processor.gl = MagicMock()
        self.processor.process_branch_protection = MagicMock()

    def test_squash_option_is_not_passed_to_the_protected_branches_api(self):
        configuration = {"branches": {"avalon": {"protected": True, "squash_option": "always"}}}

        self.processor._process_configuration("group/project", configuration)

        passed_config = self.processor.process_branch_protection.call_args.args[2]
        assert "squash_option" not in passed_config
        assert passed_config["protected"] is True

    def test_the_key_is_left_in_the_configuration_for_the_other_processor(self):
        configuration = {"branches": {"avalon": {"protected": True, "squash_option": "always"}}}

        self.processor._process_configuration("group/project", configuration)

        assert configuration["branches"]["avalon"]["squash_option"] == "always"
