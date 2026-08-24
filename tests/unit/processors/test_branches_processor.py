from unittest.mock import MagicMock

import pytest
from gitlab import GitlabDeleteError, GitlabGetError, GitlabOperationError

from gitlabform.gitlab import AccessLevel
from gitlabform.processors.project.branches_processor import BranchesProcessor
from gitlabform.processors.util.branch_protection import BranchProtection
from gitlabform.processors.util.failed_writes import SomeWritesFailed


class TestBranchesProcessor:
    def setup_method(self):
        self.gitlab = MagicMock()
        self.strict = False
        self.processor = BranchesProcessor(self.gitlab, self.strict)

    def test_is_branch_name_wildcard(self):
        # Test cases with wildcards
        assert BranchesProcessor.branch_name_contains_supported_wildcard("branch*") is True
        assert BranchesProcessor.branch_name_contains_supported_wildcard("*branch") is True
        assert BranchesProcessor.branch_name_contains_supported_wildcard("br*nch") is True

        # Test cases with unsupported wildcards
        assert BranchesProcessor.branch_name_contains_supported_wildcard("branch?") is False
        assert BranchesProcessor.branch_name_contains_supported_wildcard("?branch") is False
        assert BranchesProcessor.branch_name_contains_supported_wildcard("br?nch") is False

        # Test cases without wildcards
        assert BranchesProcessor.branch_name_contains_supported_wildcard("branch") is False
        assert BranchesProcessor.branch_name_contains_supported_wildcard("main") is False
        assert BranchesProcessor.branch_name_contains_supported_wildcard("feature-123") is False

    def test_convert_user_and_group_names_to_ids(self):
        # Setup
        self.processor.gl = MagicMock()
        self.processor.gl.get_user_id_cached.return_value = 123
        self.processor.gl.get_group_id.return_value = 456

        # Test with user
        config_with_user = {"allowed_to_push": [{"user": "johndoe"}], "protected": True}
        result = self.processor.convert_user_and_group_names_to_ids(config_with_user)
        assert result["allowed_to_push"][0]["user_id"] == 123
        assert "user" not in result["allowed_to_push"][0]

        # Test with group
        config_with_group = {"allowed_to_merge": [{"group": "developers"}], "protected": True}
        result = self.processor.convert_user_and_group_names_to_ids(config_with_group)
        assert result["allowed_to_merge"][0]["group_id"] == 456
        assert "group" not in result["allowed_to_merge"][0]

    def test_naive_access_level_diff_analyzer(self):
        # Test with equal configurations
        cfg_in_gitlab = [{"access_level": 40, "user_id": None, "group_id": None}]
        local_cfg = [{"access_level": 40, "user_id": None, "group_id": None}]
        assert BranchProtection.naive_access_level_diff_analyzer("test_key", cfg_in_gitlab, local_cfg) is False

        # Test with different access levels
        cfg_in_gitlab = [{"access_level": 30, "user_id": None, "group_id": None}]
        local_cfg = [{"access_level": 40, "user_id": None, "group_id": None}]
        assert BranchProtection.naive_access_level_diff_analyzer("test_key", cfg_in_gitlab, local_cfg) is True

        # Test with different user_ids
        cfg_in_gitlab = [{"access_level": None, "user_id": 30, "group_id": None}]
        local_cfg = [{"access_level": None, "user_id": 40, "group_id": None}]
        assert BranchProtection.naive_access_level_diff_analyzer("test_key", cfg_in_gitlab, local_cfg) is True

        # Test with different group_ids
        cfg_in_gitlab = [{"access_level": None, "user_id": None, "group_id": 30}]
        local_cfg = [{"access_level": None, "user_id": None, "group_id": 40}]
        assert BranchProtection.naive_access_level_diff_analyzer("test_key", cfg_in_gitlab, local_cfg) is True

        # Test with different lengths
        cfg_in_gitlab = [{"access_level": None, "user_id": 40, "group_id": None}]
        local_cfg = [
            {"access_level": None, "user_id": 40, "group_id": None},
            {"access_level": None, "user_id": 30, "group_id": None},
        ]
        assert BranchProtection.naive_access_level_diff_analyzer("test_key", cfg_in_gitlab, local_cfg) is True

    def test_transform_branch_config_access_levels(self):
        our_branch_config_access_level = {
            "merge_access_level": 40,
            "push_access_level": 30,
            "unprotect_access_level": 20,
            "protected": True,
        }
        our_branch_config_allowed_to = {
            "allowed_to_merge": [{"access_level": 50}, {"user_id": 123}],
            "allowed_to_push": [{"group_id": 456}],
            "allowed_to_unprotect": [{"access_level": 60}, {"user_id": 789}],
            "protected": True,
        }
        result_access_level = BranchProtection.map_config_to_protected_branch_get_data(our_branch_config_access_level)
        result_allowed_to = BranchProtection.map_config_to_protected_branch_get_data(our_branch_config_allowed_to)

        expected_result_access_level = {
            "merge_access_levels": [
                {"id": None, "access_level": 40, "user_id": None, "group_id": None, "deploy_key_id": None}
            ],
            "push_access_levels": [
                {"id": None, "access_level": 30, "user_id": None, "group_id": None, "deploy_key_id": None}
            ],
            "unprotect_access_levels": [
                {"id": None, "access_level": 20, "user_id": None, "group_id": None, "deploy_key_id": None}
            ],
        }

        expected_result_allowed_to = {
            "merge_access_levels": [
                {"id": None, "access_level": 50, "user_id": None, "group_id": None, "deploy_key_id": None},
                {"id": None, "access_level": None, "user_id": 123, "group_id": None, "deploy_key_id": None},
            ],
            "push_access_levels": [
                {"id": None, "access_level": None, "user_id": None, "group_id": 456, "deploy_key_id": None}
            ],
            "unprotect_access_levels": [
                {"id": None, "access_level": 60, "user_id": None, "group_id": None, "deploy_key_id": None},
                {"id": None, "access_level": None, "user_id": 789, "group_id": None, "deploy_key_id": None},
            ],
        }

        assert result_access_level == expected_result_access_level
        assert result_allowed_to == expected_result_allowed_to

    def test_build_patch_request_data_returns_nothing_if_no_config_defined_and_gitlab_has_maintainer_access_already(
        self,
    ):
        transformed_access_levels = None
        existing_records = tuple(
            [
                {
                    "access_level": AccessLevel.MAINTAINER.value,
                }
            ]
        )

        result = BranchProtection.build_patch_request_data(transformed_access_levels, existing_records)
        assert result == []

    def test_build_patch_request_data_returns_nothing_when_config_access_level_matches_gitlab_access_level(self):
        transformed_access_levels = [
            {
                "access_level": AccessLevel.MAINTAINER.value,
            }
        ]
        existing_records = tuple(
            [
                {
                    "access_level": AccessLevel.MAINTAINER.value,
                }
            ]
        )

        result = BranchProtection.build_patch_request_data(transformed_access_levels, existing_records)
        assert result == []

    def test_build_patch_request_data_when_config_has_additional_data_to_gitlab(self):
        transformed_access_levels = [
            {
                "access_level": AccessLevel.MAINTAINER.value,
            },
            {"user_id": 23},
            {
                "group_id": 54,
            },
        ]
        existing_records = tuple([{"access_level": AccessLevel.MAINTAINER.value, "id": 17}])

        result = BranchProtection.build_patch_request_data(transformed_access_levels, existing_records)
        assert result == [
            {
                "user_id": 23,
            },
            {
                "group_id": 54,
            },
        ]

    def test_build_patch_request_data_when_config_has_different_access_level_to_gitlab(self):
        transformed_access_levels = [
            {
                "access_level": AccessLevel.NO_ACCESS.value,
            }
        ]
        existing_records = tuple([{"access_level": AccessLevel.MAINTAINER.value, "id": 17}])

        result = BranchProtection.build_patch_request_data(transformed_access_levels, existing_records)
        assert result == [
            {
                "access_level": AccessLevel.NO_ACCESS.value,
            },
            {
                "id": 17,
                "_destroy": True,
            },
        ]

    def test_build_patch_request_data_when_config_is_remove_user_access_to_gitlab(self):
        transformed_access_levels = [
            {
                "access_level": AccessLevel.MAINTAINER.value,
            }
        ]
        existing_records = tuple(
            [
                {"access_level": AccessLevel.MAINTAINER.value, "id": 17},
                {
                    "user_id": 23,
                    "id": 18,
                },
            ]
        )

        result = BranchProtection.build_patch_request_data(transformed_access_levels, existing_records)
        assert result == [{"id": 18, "_destroy": True}]

    def test_build_patch_request_data_keeps_the_omitted_user_when_the_branch_is_additive(self):
        transformed_access_levels = [
            {
                "access_level": AccessLevel.MAINTAINER.value,
            }
        ]
        existing_records = tuple(
            [
                {"access_level": AccessLevel.MAINTAINER.value, "id": 17},
                {
                    "user_id": 23,
                    "id": 18,
                },
            ]
        )

        result = BranchProtection.build_patch_request_data(transformed_access_levels, existing_records, additive=True)
        assert result == []


class TestBranchesProcessorFailedWrites:
    def setup_method(self):
        self.gitlab = MagicMock()
        self.processor = BranchesProcessor(self.gitlab, False)
        self.project = MagicMock()
        self.processor.gl = MagicMock()
        self.processor.gl.get_project_by_path_cached.return_value = self.project

    @staticmethod
    def _two_protected_branches() -> dict:
        return {"branches": {"develop": {"protected": True}, "main": {"protected": True}}}

    def test__a_branch_gitlab_refuses_fails_the_node_and_the_other_branches_are_still_written(self, caplog):
        self.project.protectedbranches.get.side_effect = GitlabGetError("not found", 404)
        self.project.protectedbranches.create.side_effect = [GitlabOperationError("no", 400), None]

        with caplog.at_level("ERROR"):
            with pytest.raises(SomeWritesFailed) as failure:
                self.processor._process_configuration("foo/bar", self._two_protected_branches())

        assert self.project.protectedbranches.create.call_count == 2
        assert "develop" in str(failure.value)
        assert "foo/bar" in str(failure.value)
        assert [record.message for record in caplog.records if record.levelname == "ERROR"] == [
            "Protecting branch 'develop' failed! Error 'no"
        ]

    def test__a_refusal_reaches_the_caller_that_counts_a_node_failed(self):
        self.project.protectedbranches.get.side_effect = GitlabGetError("not found", 404)
        self.project.protectedbranches.create.side_effect = GitlabOperationError("no", 400)

        with pytest.raises(SomeWritesFailed):
            self.processor.process(
                "foo/bar",
                {"branches": {"main": {"protected": True}}},
                False,
                False,
                MagicMock(),
            )

    def test__branches_gitlab_accepts_leave_the_node_green(self):
        self.project.protectedbranches.get.side_effect = GitlabGetError("not found", 404)

        self.processor._process_configuration("foo/bar", self._two_protected_branches())

        assert self.project.protectedbranches.create.call_count == 2

    def test__an_unprotect_gitlab_refuses_fails_the_node_too(self):
        protected_branch = MagicMock()
        protected_branch.name = "main"
        protected_branch.delete.side_effect = GitlabDeleteError("no", 400)
        self.project.protectedbranches.get.return_value = protected_branch

        with pytest.raises(SomeWritesFailed) as failure:
            self.processor._process_configuration("foo/bar", {"branches": {"main": {"protected": False}}})

        assert "could not be unprotected" in str(failure.value)

    def test__what_one_node_refused_is_not_carried_into_the_next(self):
        self.project.protectedbranches.get.side_effect = GitlabGetError("not found", 404)
        self.project.protectedbranches.create.side_effect = GitlabOperationError("no", 400)
        with pytest.raises(SomeWritesFailed):
            self.processor._process_configuration("foo/bar", {"branches": {"main": {"protected": True}}})

        self.project.protectedbranches.create.side_effect = None
        self.processor._process_configuration("foo/baz", {"branches": {"main": {"protected": True}}})
