from unittest.mock import MagicMock, patch

import pytest

from gitlabform.processors.shared.protected_environments_processor import (
    ProtectedEnvironmentsNotWritten,
    ProtectedEnvironmentsProcessor,
)
from gitlabform.processors.util.difference_logger import DifferenceLogger


def _diff(current: dict, desired: dict) -> str:
    return DifferenceLogger.log_diff("protected_environments changes", current, desired, only_changed=True, test=True)


class TestProtectedEnvironmentsProcessorDryRunDiff:
    def setup_method(self):
        self.gitlab = MagicMock()
        with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
            self.processor = ProtectedEnvironmentsProcessor(self.gitlab)

    @staticmethod
    def _gitlab_environment(access_level=40):
        return {
            "name": "production",
            "deploy_access_levels": [
                {
                    "id": 12,
                    "access_level": access_level,
                    "access_level_description": "Maintainers",
                    "user_id": None,
                    "group_id": None,
                    "group_inheritance_type": 0,
                }
            ],
            "required_approval_count": 0,
        }

    def test__differing_access_level_shows_in_diff(self):
        self.gitlab.list_protected_environments.return_value = [self._gitlab_environment(access_level=40)]
        config = {
            "production": {
                "name": "production",
                "deploy_access_levels": [
                    {"access_level": 30, "access_level_description": "Maintainers", "group_inheritance_type": 0}
                ],
                "required_approval_count": 0,
            }
        }

        text = _diff(
            self.processor._get_current_state("foo/bar"),
            self.processor._get_desired_state(config),
        )

        assert "production" in text
        assert "30" in text

    def test__matching_state_is_silent(self):
        self.gitlab.list_protected_environments.return_value = [self._gitlab_environment()]
        config = {
            "production": {
                "name": "production",
                "deploy_access_levels": [
                    {"access_level": 40, "access_level_description": "Maintainers", "group_inheritance_type": 0}
                ],
                "required_approval_count": 0,
            }
        }

        assert (
            _diff(
                self.processor._get_current_state("foo/bar"),
                self.processor._get_desired_state(config),
            )
            == ""
        )

    def test__empty_section_does_not_crash_and_reports_what_is_live(self, caplog):
        self.gitlab.list_protected_environments.return_value = [self._gitlab_environment()]

        with caplog.at_level("INFO"):
            self.processor.process(
                "foo/bar",
                {"protected_environments": None},
                True,
                True,
                MagicMock(),
            )

        diffs = [r for r in caplog.records if "protected_environments changes" in r.message]
        assert len(diffs) == 1
        assert "production" in diffs[0].message
        assert "(only in GitLab)" in diffs[0].message

    def test__empty_section_never_reaches_get_desired_state_as_none(self):
        assert self.processor._get_desired_state({}) == {}


class TestProtectedEnvironmentsProcessorReadBack:
    def setup_method(self):
        self.gitlab = MagicMock()
        with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
            self.processor = ProtectedEnvironmentsProcessor(self.gitlab)

    @staticmethod
    def _config(**environments) -> dict:
        return {"protected_environments": environments}

    @staticmethod
    def _asked_with_a_user_rule(name="production") -> dict:
        return {
            "name": name,
            "deploy_access_levels": [{"access_level": 40}],
            "approval_rules": [{"user_id": 15, "required_approvals": 1}],
        }

    @staticmethod
    def _stored(name="production", approval_rules=None) -> dict:
        return {
            "id": 7,
            "name": name,
            "deploy_access_levels": [
                {
                    "id": 12,
                    "access_level": 40,
                    "access_level_description": "Maintainers",
                    "user_id": None,
                    "group_id": None,
                }
            ],
            "approval_rules": [] if approval_rules is None else approval_rules,
        }

    def test__an_approval_rule_gitlab_accepted_and_dropped_fails_the_node(self, caplog):
        self.gitlab.list_protected_environments.side_effect = [[], [self._stored()]]

        with caplog.at_level("ERROR"):
            with pytest.raises(ProtectedEnvironmentsNotWritten) as failure:
                self.processor._process_configuration(
                    "foo/bar", self._config(production=self._asked_with_a_user_rule())
                )

        assert self.gitlab.protect_a_repository_environment.call_count == 1
        assert "'user_id': 15" in str(failure.value)
        assert "production" in str(failure.value)
        errors = [record.message for record in caplog.records if record.levelname == "ERROR"]
        assert len(errors) == 1
        assert "approval_rules" in errors[0]
        assert "'user_id': 15" in errors[0]

    def test__a_write_gitlab_kept_whole_is_silent(self, caplog):
        kept = [{"id": 3, "user_id": 15, "group_id": None, "access_level": None, "required_approvals": 1}]
        self.gitlab.list_protected_environments.side_effect = [[], [self._stored(approval_rules=kept)]]

        with caplog.at_level("WARNING"):
            self.processor._process_configuration("foo/bar", self._config(production=self._asked_with_a_user_rule()))

        assert self.gitlab.protect_a_repository_environment.call_count == 1
        assert [record.message for record in caplog.records if record.levelname in ("ERROR", "WARNING")] == []

    def test__an_environment_gitlab_did_not_store_at_all_fails_the_node(self):
        self.gitlab.list_protected_environments.side_effect = [[], []]

        with pytest.raises(ProtectedEnvironmentsNotWritten) as failure:
            self.processor._process_configuration("foo/bar", self._config(production=self._asked_with_a_user_rule()))

        assert "the environment itself" in str(failure.value)

    def test__a_key_gitlab_does_not_report_back_is_called_unverified_not_lost(self, caplog):
        without_the_key = self._stored()
        del without_the_key["approval_rules"]
        self.gitlab.list_protected_environments.side_effect = [[], [without_the_key]]

        with caplog.at_level("WARNING"):
            self.processor._process_configuration("foo/bar", self._config(production=self._asked_with_a_user_rule()))

        warnings = [record.message for record in caplog.records if record.levelname == "WARNING"]
        assert len(warnings) == 1
        assert "approval_rules" in warnings[0]
        assert "NOT verified" in warnings[0]
        assert [record.message for record in caplog.records if record.levelname == "ERROR"] == []

    def test__every_environment_that_lost_something_is_named_in_one_run(self):
        self.gitlab.list_protected_environments.side_effect = [
            [],
            [self._stored(name="production")],
            [self._stored(name="production"), self._stored(name="staging")],
        ]

        with pytest.raises(ProtectedEnvironmentsNotWritten) as failure:
            self.processor._process_configuration(
                "foo/bar",
                self._config(
                    production=self._asked_with_a_user_rule("production"),
                    staging=self._asked_with_a_user_rule("staging"),
                ),
            )

        assert self.gitlab.protect_a_repository_environment.call_count == 2
        assert "production" in str(failure.value)
        assert "staging" in str(failure.value)

    def test__an_update_of_an_existing_environment_is_read_back_too(self):
        live = self._stored()
        live["deploy_access_levels"][0]["access_level"] = 30
        self.gitlab.list_protected_environments.side_effect = [[live], [self._stored()]]

        with pytest.raises(ProtectedEnvironmentsNotWritten):
            self.processor._process_configuration("foo/bar", self._config(production=self._asked_with_a_user_rule()))

        assert self.gitlab.update_a_repository_environment.call_count == 1
        assert self.gitlab.unprotect_environment.call_count == 0
        assert self.gitlab.protect_a_repository_environment.call_count == 0

    def test__what_one_node_lost_is_not_carried_into_the_next(self):
        self.gitlab.list_protected_environments.side_effect = [[], [self._stored()]]
        with pytest.raises(ProtectedEnvironmentsNotWritten):
            self.processor._process_configuration("foo/bar", self._config(production=self._asked_with_a_user_rule()))

        kept = [{"id": 3, "user_id": 15, "required_approvals": 1}]
        self.gitlab.list_protected_environments.side_effect = [[], [self._stored(approval_rules=kept)]]
        self.processor._process_configuration("foo/baz", self._config(production=self._asked_with_a_user_rule()))


class TestProtectedEnvironmentsProcessorUpdateInPlace:
    def setup_method(self):
        self.gitlab = MagicMock()
        with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
            self.processor = ProtectedEnvironmentsProcessor(self.gitlab)

    @staticmethod
    def _config(**environments) -> dict:
        return {"protected_environments": environments}

    @staticmethod
    def _live(deploy_access_levels: list, **rest) -> dict:
        return {"id": 7, "name": "production", "deploy_access_levels": deploy_access_levels, **rest}

    def _run(self, live: dict, wanted: dict, read_back: dict) -> None:
        self.gitlab.list_protected_environments.side_effect = [[live], [read_back]]
        self.processor._process_configuration("foo/bar", self._config(production=wanted))

    def _payload(self) -> dict:
        return self.gitlab.update_a_repository_environment.call_args.args[2]

    def test__an_update_goes_through_the_update_endpoint_and_never_unprotects(self):
        live = self._live([{"id": 12, "access_level": 30, "user_id": None, "group_id": None}])
        wanted = {"name": "production", "deploy_access_levels": [{"access_level": 40}]}
        read_back = self._live([{"id": 13, "access_level": 40, "user_id": None, "group_id": None}])

        self._run(live, wanted, read_back)

        assert self.gitlab.unprotect_environment.call_count == 0
        assert self.gitlab.protect_a_repository_environment.call_count == 0
        assert self.gitlab.update_a_repository_environment.call_args.args[:2] == ("foo/bar", "production")

    def test__an_entry_that_already_has_a_counterpart_is_left_out_of_the_update(self):
        kept = {"id": 12, "access_level": 40, "user_id": None, "group_id": None}
        dropped = {"id": 13, "access_level": 30, "user_id": None, "group_id": None}
        live = self._live([kept, dropped])
        wanted = {
            "name": "production",
            "deploy_access_levels": [{"access_level": 40}, {"user_id": 15}],
        }
        read_back = self._live([kept, {"id": 14, "access_level": None, "user_id": 15, "group_id": None}])

        self._run(live, wanted, read_back)

        assert self._payload()["deploy_access_levels"] == [{"user_id": 15}, {"id": 13, "_destroy": True}]

    def test__a_rule_no_entry_claims_is_deleted_in_the_same_request(self):
        live = self._live(
            [
                {"id": 12, "access_level": 40, "user_id": None, "group_id": None},
                {"id": 13, "access_level": None, "user_id": 15, "group_id": None},
            ]
        )
        wanted = {"name": "production", "deploy_access_levels": [{"access_level": 40}]}
        read_back = self._live([{"id": 12, "access_level": 40, "user_id": None, "group_id": None}])

        self._run(live, wanted, read_back)

        assert self.gitlab.update_a_repository_environment.call_count == 1
        assert self.gitlab.unprotect_environment.call_count == 0
        assert self._payload()["deploy_access_levels"] == [{"id": 13, "_destroy": True}]

    def test__a_key_the_config_does_not_declare_is_not_touched_by_the_update(self):
        live = self._live(
            [{"id": 12, "access_level": 30, "user_id": None, "group_id": None}],
            approval_rules=[{"id": 3, "user_id": 15}],
        )
        wanted = {"name": "production", "deploy_access_levels": [{"access_level": 40}]}
        read_back = self._live(
            [{"id": 13, "access_level": 40, "user_id": None, "group_id": None}],
            approval_rules=[{"id": 3, "user_id": 15}],
        )

        self._run(live, wanted, read_back)

        assert "approval_rules" in live
        assert "approval_rules" not in self._payload()

    def test__a_key_the_update_endpoint_does_not_carry_deletes_and_protects_anew_out_loud(self, caplog):
        live = self._live(
            [{"id": 12, "access_level": 40, "user_id": None, "group_id": None}],
            required_approval_count=0,
        )
        wanted = {
            "name": "production",
            "deploy_access_levels": [{"access_level": 40}],
            "required_approval_count": 2,
        }
        read_back = self._live(
            [{"id": 13, "access_level": 40, "user_id": None, "group_id": None}],
            required_approval_count=2,
        )

        with caplog.at_level("WARNING"):
            self._run(live, wanted, read_back)

        assert self.gitlab.update_a_repository_environment.call_count == 0
        assert self.gitlab.unprotect_environment.call_count == 1
        assert self.gitlab.protect_a_repository_environment.call_count == 1
        warnings = [record.message for record in caplog.records if record.levelname == "WARNING"]
        assert len(warnings) == 1
        assert "required_approval_count" in warnings[0]
        assert "unprotected" in warnings[0]

    def test__an_entry_gitlab_reports_without_an_id_cannot_be_deleted_and_says_so(self, caplog):
        live = self._live([{"access_level": 30, "user_id": None, "group_id": None}])
        wanted = {"name": "production", "deploy_access_levels": [{"access_level": 40}]}
        read_back = self._live([{"id": 13, "access_level": 40, "user_id": None, "group_id": None}])

        with caplog.at_level("WARNING"):
            self._run(live, wanted, read_back)

        assert self._payload()["deploy_access_levels"] == [{"access_level": 40}]
        warnings = [record.message for record in caplog.records if record.levelname == "WARNING"]
        assert len(warnings) == 1
        assert "without an id" in warnings[0]

    def test__an_update_gitlab_kept_whole_is_silent(self, caplog):
        live = self._live([{"id": 12, "access_level": 30, "user_id": None, "group_id": None}])
        wanted = {"name": "production", "deploy_access_levels": [{"access_level": 40}]}
        read_back = self._live([{"id": 13, "access_level": 40, "user_id": None, "group_id": None}])

        with caplog.at_level("WARNING"):
            self._run(live, wanted, read_back)

        assert [record.message for record in caplog.records if record.levelname in ("ERROR", "WARNING")] == []

    def test__what_the_update_lost_fails_the_node(self):
        live = self._live([{"id": 12, "access_level": 30, "user_id": None, "group_id": None}])
        wanted = {"name": "production", "deploy_access_levels": [{"access_level": 40}]}
        read_back = self._live([{"id": 12, "access_level": 30, "user_id": None, "group_id": None}])

        self.gitlab.list_protected_environments.side_effect = [[live], [read_back]]

        with pytest.raises(ProtectedEnvironmentsNotWritten) as failure:
            self.processor._process_configuration("foo/bar", self._config(production=wanted))

        assert "deploy_access_levels" in str(failure.value)


class TestProtectedEnvironmentsProcessorIdleState:
    def setup_method(self):
        self.gitlab = MagicMock()
        with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
            self.processor = ProtectedEnvironmentsProcessor(self.gitlab)

    def test__an_unchanged_environment_with_approval_rules_is_not_written_at_all(self):
        self.gitlab.list_protected_environments.return_value = [
            {
                "id": 7,
                "name": "production",
                "deploy_access_levels": [
                    {"id": 12, "access_level": 40, "user_id": None, "group_id": None},
                    {"id": 13, "access_level": None, "user_id": 15, "group_id": None},
                ],
                "approval_rules": [
                    {"id": 3, "user_id": 15, "access_level": None, "required_approvals": 1, "group_id": None},
                    {"id": 4, "access_level": 40, "user_id": None, "required_approvals": 2, "group_id": None},
                ],
            }
        ]
        wanted = {
            "name": "production",
            "deploy_access_levels": [{"user_id": 15}, {"access_level": 40}],
            "approval_rules": [
                {"access_level": 40, "required_approvals": 2},
                {"user_id": 15, "required_approvals": 1},
            ],
        }

        self.processor._process_configuration("foo/bar", {"protected_environments": {"production": wanted}})

        assert self.gitlab.update_a_repository_environment.call_count == 0
        assert self.gitlab.protect_a_repository_environment.call_count == 0
        assert self.gitlab.unprotect_environment.call_count == 0

    def test__a_changed_approval_rule_still_reaches_the_update_endpoint(self):
        live = {
            "id": 7,
            "name": "production",
            "deploy_access_levels": [{"id": 12, "access_level": 40, "user_id": None, "group_id": None}],
            "approval_rules": [{"id": 3, "user_id": 15, "access_level": None, "required_approvals": 1}],
        }
        read_back = {
            "id": 7,
            "name": "production",
            "deploy_access_levels": [{"id": 12, "access_level": 40, "user_id": None, "group_id": None}],
            "approval_rules": [{"id": 5, "user_id": 16, "access_level": None, "required_approvals": 1}],
        }
        self.gitlab.list_protected_environments.side_effect = [[live], [read_back]]
        wanted = {
            "name": "production",
            "deploy_access_levels": [{"access_level": 40}],
            "approval_rules": [{"user_id": 16, "required_approvals": 1}],
        }

        self.processor._process_configuration("foo/bar", {"protected_environments": {"production": wanted}})

        assert self.gitlab.update_a_repository_environment.call_count == 1
        assert self.gitlab.update_a_repository_environment.call_args.args[2]["approval_rules"] == [
            {"user_id": 16, "required_approvals": 1},
            {"id": 3, "_destroy": True},
        ]
