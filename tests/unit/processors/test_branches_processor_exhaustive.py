"""
A declared access list is the whole of that list: what GitLab holds and the
configuration does not name is removed, so that reading the configuration is enough to
know who may push to, merge into or unprotect a branch. A branch carrying
"additive: true" keeps the older behaviour, where such a rule is left where it is.

A list the configuration does not declare at all is a different matter and is not
touched, in either regime.
"""

from unittest.mock import MagicMock, patch

import pytest
from gitlab import GitlabGetError

from gitlabform.gitlab import AccessLevel
from gitlabform.processors.project.branches_processor import BranchesProcessor
from gitlabform.processors.util.branch_protection import BranchProtection


def _role(access_level: int, entry_id: int) -> dict:
    return {
        "id": entry_id,
        "access_level": access_level,
        "user_id": None,
        "group_id": None,
        "deploy_key_id": None,
    }


def _user(user_id: int, entry_id: int) -> dict:
    return {"id": entry_id, "access_level": 40, "user_id": user_id, "group_id": None, "deploy_key_id": None}


def _group(group_id: int, entry_id: int) -> dict:
    return {"id": entry_id, "access_level": 40, "user_id": None, "group_id": group_id, "deploy_key_id": None}


def _maintainer_rule() -> list[dict]:
    return [
        {
            "id": None,
            "access_level": AccessLevel.MAINTAINER.value,
            "user_id": None,
            "group_id": None,
            "deploy_key_id": None,
        }
    ]


class TestExhaustiveAccessLists:
    def test_a_role_rule_gitlab_has_and_the_config_does_not_is_destroyed(self):
        patch_data = BranchProtection.build_patch_request_data(
            transformed_access_levels=_maintainer_rule(),
            existing_records=(_role(AccessLevel.MAINTAINER.value, 17), _role(AccessLevel.DEVELOPER.value, 18)),
        )

        assert patch_data == [{"id": 18, "_destroy": True}]

    def test_a_user_rule_gitlab_has_and_the_config_does_not_is_destroyed(self):
        patch_data = BranchProtection.build_patch_request_data(
            transformed_access_levels=_maintainer_rule(),
            existing_records=(_role(AccessLevel.MAINTAINER.value, 17), _user(23, 18)),
        )

        assert patch_data == [{"id": 18, "_destroy": True}]

    def test_a_group_rule_gitlab_has_and_the_config_does_not_is_destroyed(self):
        patch_data = BranchProtection.build_patch_request_data(
            transformed_access_levels=_maintainer_rule(),
            existing_records=(_role(AccessLevel.MAINTAINER.value, 17), _group(54, 18)),
        )

        assert patch_data == [{"id": 18, "_destroy": True}]

    @pytest.mark.parametrize(
        "undeclared",
        [
            pytest.param(_role(AccessLevel.DEVELOPER.value, 18), id="role"),
            pytest.param(_user(23, 18), id="user"),
            pytest.param(_group(54, 18), id="group"),
        ],
    )
    def test_an_additive_branch_keeps_every_rule_it_does_not_name(self, undeclared):
        patch_data = BranchProtection.build_patch_request_data(
            transformed_access_levels=_maintainer_rule(),
            existing_records=(_role(AccessLevel.MAINTAINER.value, 17), undeclared),
            additive=True,
        )

        assert patch_data == []

    def test_a_rule_gitlab_returned_without_an_id_is_not_destroyed_and_says_so(self, caplog):
        with caplog.at_level("WARNING"):
            patch_data = BranchProtection.build_patch_request_data(
                transformed_access_levels=_maintainer_rule(),
                existing_records=({"access_level": AccessLevel.DEVELOPER.value, "user_id": None, "group_id": None},),
            )

        assert patch_data == [{"access_level": AccessLevel.MAINTAINER.value}]
        assert "without an id" in caplog.text

    def test_the_live_branch_of_the_400_sends_no_creation_at_all(self):
        """
        The 2026-08-24 payload GitLab refused carried a group it already held. Under the
        exhaustive regime the branch still has rules to lose, so the payload is not
        empty - but every entry in it is a deletion, and the group is not sent again.
        """
        merchanto_leads = 140444807
        existing_records = (
            _group(merchanto_leads, 332747900),
            _role(AccessLevel.DEVELOPER.value, 251317784),
            _role(AccessLevel.MAINTAINER.value, 332150660),
            _user(10843916, 332150661),
        )
        configured = [
            {
                "id": None,
                "access_level": AccessLevel.MAINTAINER.value,
                "user_id": None,
                "group_id": None,
                "deploy_key_id": None,
            },
            {"id": None, "access_level": None, "user_id": None, "group_id": merchanto_leads, "deploy_key_id": None},
        ]

        patch_data = BranchProtection.build_patch_request_data(
            transformed_access_levels=configured,
            existing_records=existing_records,
        )

        assert all(entry.get("_destroy") for entry in patch_data)
        assert patch_data == [{"id": 251317784, "_destroy": True}, {"id": 332150661, "_destroy": True}]


def _processor(enterprise: bool = True, version_below_15_6: bool = False) -> BranchesProcessor:
    gitlab = MagicMock()
    gitlab.enterprise = enterprise
    gitlab.is_version_less_than.return_value = version_below_15_6
    with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
        processor = BranchesProcessor(gitlab, strict=False)
    processor.gl = MagicMock()
    return processor


def _project_holding(protected_branch) -> MagicMock:
    project = MagicMock()
    project.protectedbranches.get.return_value = protected_branch
    return project


def _protected_branch(**access_level_lists) -> MagicMock:
    protected_branch = MagicMock()
    protected_branch.attributes = dict(access_level_lists)
    return protected_branch


class TestExhaustiveAccessListsOnTheApplyPath:
    def test_a_branch_gitlab_already_matches_is_not_patched_at_all(self):
        processor = _processor()
        project = _project_holding(
            _protected_branch(
                merge_access_levels=[_role(AccessLevel.MAINTAINER.value, 2), _user(23, 3)],
                push_access_levels=[_role(AccessLevel.NO_ACCESS.value, 1)],
            )
        )

        processor.process_branch_protection(
            project,
            "main",
            {
                "protected": True,
                "allowed_to_merge": [{"access_level": AccessLevel.MAINTAINER.value}, {"user_id": 23}],
                "push_access_level": AccessLevel.NO_ACCESS.value,
            },
        )

        project.protectedbranches.update.assert_not_called()
        project.protectedbranches.create.assert_not_called()

    def test_the_deletions_and_the_writes_of_one_list_ride_in_one_request(self):
        processor = _processor()
        project = _project_holding(
            _protected_branch(merge_access_levels=[_role(AccessLevel.MAINTAINER.value, 2), _user(23, 3)])
        )

        processor.process_branch_protection(
            project,
            "main",
            {
                "protected": True,
                "allowed_to_merge": [{"access_level": AccessLevel.MAINTAINER.value}, {"group_id": 54}],
            },
        )

        project.protectedbranches.update.assert_called_once()
        assert project.protectedbranches.update.call_args[0][1] == {
            "allowed_to_merge": [{"group_id": 54}, {"id": 3, "_destroy": True}]
        }

    def test_a_list_the_config_does_not_declare_is_left_alone(self):
        processor = _processor()
        project = _project_holding(
            _protected_branch(
                merge_access_levels=[_role(AccessLevel.MAINTAINER.value, 2)],
                push_access_levels=[_role(AccessLevel.MAINTAINER.value, 1), _user(23, 4)],
            )
        )

        processor.process_branch_protection(
            project,
            "main",
            {"protected": True, "allowed_to_merge": [{"user_id": 23}]},
        )

        assert "allowed_to_push" not in project.protectedbranches.update.call_args[0][1]

    def test_the_additive_key_is_never_sent_to_gitlab(self):
        processor = _processor()
        project = _project_holding(_protected_branch(merge_access_levels=[_role(AccessLevel.MAINTAINER.value, 2)]))

        processor.process_branch_protection(
            project,
            "main",
            {"protected": True, "additive": True, "allowed_to_merge": [{"user_id": 23}]},
        )

        assert project.protectedbranches.update.call_args[0][1] == {"allowed_to_merge": [{"user_id": 23}]}

    def test_the_additive_key_is_never_sent_when_the_branch_is_created_either(self):
        processor = _processor()
        project = MagicMock()
        project.protectedbranches.get.side_effect = GitlabGetError("not found", 404)

        processor.process_branch_protection(
            project,
            "main",
            {"protected": True, "additive": True, "push_access_level": AccessLevel.NO_ACCESS.value},
        )

        assert "additive" not in project.protectedbranches.create.call_args[0][0]

    def test_the_config_the_caller_passed_in_is_not_rewritten(self):
        processor = _processor()
        project = _project_holding(_protected_branch(merge_access_levels=[_role(AccessLevel.MAINTAINER.value, 2)]))
        branch_config = {"protected": True, "additive": True, "allowed_to_merge": [{"user_id": 23}]}

        processor.process_branch_protection(project, "main", branch_config)

        assert branch_config == {"protected": True, "additive": True, "allowed_to_merge": [{"user_id": 23}]}


class TestExhaustiveAccessListsWhereThereIsNoPatchEndpoint:
    """Under 15.6 and on CE the branch is unprotected and reprotected from scratch, so
    the rule to remove goes only if that path notices it has to run at all."""

    def test_a_rule_only_gitlab_has_makes_the_reprotect_happen(self):
        processor = _processor(version_below_15_6=True)
        protected_branch = _protected_branch(push_access_levels=[_role(AccessLevel.MAINTAINER.value, 1), _user(23, 4)])
        project = _project_holding(protected_branch)

        processor.process_branch_protection(
            project, "main", {"protected": True, "push_access_level": AccessLevel.MAINTAINER.value}
        )

        protected_branch.delete.assert_called_once()
        project.protectedbranches.create.assert_called_once()

    def test_the_same_rule_under_additive_leaves_the_branch_where_it_is(self):
        processor = _processor(version_below_15_6=True)
        protected_branch = _protected_branch(push_access_levels=[_role(AccessLevel.MAINTAINER.value, 1), _user(23, 4)])
        project = _project_holding(protected_branch)

        processor.process_branch_protection(
            project,
            "main",
            {"protected": True, "additive": True, "push_access_level": AccessLevel.MAINTAINER.value},
        )

        protected_branch.delete.assert_not_called()
        project.protectedbranches.create.assert_not_called()
