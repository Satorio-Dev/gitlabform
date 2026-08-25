from unittest.mock import MagicMock

import pytest

from gitlabform.configuration import Configuration
from gitlabform.configuration.transform import (
    UserTransformer,
    GroupTransformer,
)
from gitlabform.constants import EXIT_INVALID_INPUT
from gitlabform.gitlab import GitLab


def test__transform_for_merge_request_approvals() -> None:
    config_yaml = f"""
    projects_and_groups:

      "*":
        merge_requests_approval_rules:
          standard:
            approvals_required: 1
            name: "All eligible users"

      "foo/bar":
        merge_requests_approval_rules:
          dev-uat:
            groups:
              - some_group
            users:
              - a_user
    """

    configuration = Configuration(config_string=config_yaml)

    gitlab_mock = MagicMock(GitLab)
    gitlab_mock._get_group_id = MagicMock(side_effect=[1])
    gitlab_mock._get_user_id = MagicMock(side_effect=[2])

    ut = UserTransformer(gitlab_mock)
    ut.transform(configuration)

    gt = GroupTransformer(gitlab_mock)
    gt.transform(configuration, last=True)

    expected_transformed_config_yaml = f"""
    projects_and_groups:

      "*":
        merge_requests_approval_rules:
          standard:
            approvals_required: 1
            name: "All eligible users"

      "foo/bar":
        merge_requests_approval_rules:
          dev-uat:
            group_ids:
              - 1
            user_ids:
              - 2
    """

    expected_transformed_config = Configuration(config_string=expected_transformed_config_yaml)

    assert configuration.config == expected_transformed_config.config


def test__transform_for_protected_environment_approval_rules() -> None:
    config_yaml = f"""
    projects_and_groups:
      "foo/bar":
        protected_environments:
          production:
            deploy_access_levels:
              - user: presser
            approval_rules:
              - group: gates/signers
                required_approvals: 2
              - user: a_signer
    """

    configuration = Configuration(config_string=config_yaml)

    gitlab_mock = MagicMock(GitLab)
    gitlab_mock._get_group_id = MagicMock(side_effect=[7])
    gitlab_mock._get_user_id = MagicMock(side_effect=[3, 9])

    ut = UserTransformer(gitlab_mock)
    ut.transform(configuration)

    gt = GroupTransformer(gitlab_mock)
    gt.transform(configuration, last=True)

    expected_transformed_config_yaml = f"""
    projects_and_groups:
      "foo/bar":
        protected_environments:
          production:
            deploy_access_levels:
              - user_id: 3
            approval_rules:
              - group_id: 7
                required_approvals: 2
              - user_id: 9
    """

    expected_transformed_config = Configuration(config_string=expected_transformed_config_yaml)

    assert configuration.config == expected_transformed_config.config


def _rule_naming_approvers(**keys) -> Configuration:
    declared = "\n".join(f"            {key}:\n              - {value}" for key, value in keys.items())
    return Configuration(config_string=f"""
    projects_and_groups:
      "foo/bar":
        merge_requests_approval_rules:
          release:
            name: "Release Approve"
            approvals_required: 1
{declared}
    """)


def _gitlab_mock() -> MagicMock:
    gitlab_mock = MagicMock(GitLab)
    gitlab_mock._get_user_id = MagicMock(return_value=5)
    gitlab_mock._get_group_id = MagicMock(return_value=107572970)
    return gitlab_mock


def test__a_rule_naming_approvers_as_users_and_user_ids_stops_the_run(caplog) -> None:
    configuration = _rule_naming_approvers(users="alice", user_ids=999)

    with caplog.at_level("CRITICAL"), pytest.raises(SystemExit) as exit_info:
        UserTransformer(_gitlab_mock()).transform(configuration)

    assert exit_info.value.code == EXIT_INVALID_INPUT
    message = "\n".join(record.message for record in caplog.records)
    assert "Release Approve" in message
    assert "users" in message
    assert "user_ids" in message


def test__a_rule_naming_approvers_as_groups_and_group_ids_stops_the_run(caplog) -> None:
    configuration = _rule_naming_approvers(groups="some_group", group_ids=888)

    with caplog.at_level("CRITICAL"), pytest.raises(SystemExit) as exit_info:
        GroupTransformer(_gitlab_mock()).transform(configuration)

    assert exit_info.value.code == EXIT_INVALID_INPUT
    message = "\n".join(record.message for record in caplog.records)
    assert "groups" in message
    assert "group_ids" in message


def test__a_rule_naming_its_approvers_one_way_is_transformed() -> None:
    configuration = _rule_naming_approvers(users="alice", groups="some_group")
    gitlab_mock = _gitlab_mock()

    UserTransformer(gitlab_mock).transform(configuration)
    GroupTransformer(gitlab_mock).transform(configuration)

    rule = configuration.config["projects_and_groups"]["foo/bar"]["merge_requests_approval_rules"]["release"]
    assert rule["user_ids"] == [5]
    assert rule["group_ids"] == [107572970]


def test__a_rule_naming_its_approvers_only_by_id_is_left_alone() -> None:
    configuration = _rule_naming_approvers(user_ids=999, group_ids=888)
    gitlab_mock = _gitlab_mock()

    UserTransformer(gitlab_mock).transform(configuration)
    GroupTransformer(gitlab_mock).transform(configuration)

    rule = configuration.config["projects_and_groups"]["foo/bar"]["merge_requests_approval_rules"]["release"]
    assert rule["user_ids"] == [999]
    assert rule["group_ids"] == [888]
