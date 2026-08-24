from unittest.mock import MagicMock, patch

from gitlabform.processors.project.branches_processor import BranchesProcessor


def _access_levels(*entries) -> list:
    defaults = {"id": 99, "access_level_description": "whoever", "user_id": None, "group_id": None}
    return [{**defaults, **entry} for entry in entries]


PROTECTED_MAIN = {
    "id": 1,
    "name": "main",
    "push_access_levels": _access_levels({"access_level": 40, "access_level_description": "Maintainers"}),
    "merge_access_levels": _access_levels({"access_level": 40, "access_level_description": "Maintainers"}),
    "unprotect_access_levels": _access_levels({"access_level": 40, "access_level_description": "Maintainers"}),
    "allow_force_push": False,
    "code_owner_approval_required": True,
}

MAIN_CONFIG = {
    "protected": True,
    "push_access_level": 40,
    "merge_access_level": 40,
    "unprotect_access_level": 40,
    "allow_force_push": False,
    "code_owner_approval_required": True,
}


def _make_processor(protected_branches: list) -> BranchesProcessor:
    with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
        processor = BranchesProcessor(MagicMock(), strict=False)

    branches = []
    for attributes in protected_branches:
        branch = MagicMock()
        branch.attributes = attributes
        branches.append(branch)

    processor.gl = MagicMock()
    processor.gl.get_project_by_path_cached.return_value.protectedbranches.list.return_value = branches
    return processor


def _diff(processor: BranchesProcessor, config: dict, caplog) -> str:
    with caplog.at_level("INFO"):
        processor._print_diff("group/project", config, diff_only_changed=True)
    return "\n".join(r.message for r in caplog.records if "branches changes" in r.message)


class TestBranchesDiff:
    def test_matching_state_is_silent(self, caplog):
        processor = _make_processor([PROTECTED_MAIN])

        assert _diff(processor, {"main": MAIN_CONFIG}, caplog) == ""

    def test_flipping_code_owner_approval_required_is_reported(self, caplog):
        processor = _make_processor([PROTECTED_MAIN])

        text = _diff(processor, {"main": {**MAIN_CONFIG, "code_owner_approval_required": False}}, caplog)

        assert "main" in text
        assert "code_owner_approval_required" in text

    def test_branch_not_protected_yet_is_reported(self, caplog):
        processor = _make_processor([])

        text = _diff(processor, {"main": MAIN_CONFIG}, caplog)

        assert "main" in text
        assert "false" in text

    def test_unprotecting_is_reported(self, caplog):
        processor = _make_processor([PROTECTED_MAIN])

        text = _diff(processor, {"main": {"protected": False}}, caplog)

        assert "main" in text

    def test_branch_neither_protected_nor_configured_to_be_is_silent(self, caplog):
        processor = _make_processor([])

        assert _diff(processor, {"main": {"protected": False}}, caplog) == ""

    def test_branch_only_protected_in_gitlab_is_reported_as_such(self, caplog):
        processor = _make_processor([PROTECTED_MAIN])

        text = _diff(processor, {"release": MAIN_CONFIG}, caplog)

        assert "main" in text
        assert "(only in GitLab)" in text

    def test_key_the_config_does_not_declare_is_not_a_difference(self, caplog):
        processor = _make_processor([PROTECTED_MAIN])

        assert _diff(processor, {"main": {"protected": True, "code_owner_approval_required": True}}, caplog) == ""

    def test_rule_gitlab_has_and_the_config_does_not_is_reported_as_going(self, caplog):
        live = dict(PROTECTED_MAIN)
        live["push_access_levels"] = _access_levels(
            {"access_level": 40, "access_level_description": "Maintainers"},
            {"access_level": None, "user_id": 967, "access_level_description": "John Doe"},
        )
        processor = _make_processor([live])

        text = _diff(processor, {"main": MAIN_CONFIG}, caplog)

        before, after = text.split("=>")
        assert "967" in before
        assert "967" not in after

    def test_rule_gitlab_has_and_an_additive_branch_does_not_stays_and_is_silent(self, caplog):
        live = dict(PROTECTED_MAIN)
        live["push_access_levels"] = _access_levels(
            {"access_level": 40, "access_level_description": "Maintainers"},
            {"access_level": None, "user_id": 967, "access_level_description": "John Doe"},
        )
        processor = _make_processor([live])

        assert _diff(processor, {"main": {**MAIN_CONFIG, "additive": True}}, caplog) == ""

    def test_the_additive_key_is_not_a_difference_of_its_own(self, caplog):
        processor = _make_processor([PROTECTED_MAIN])

        assert _diff(processor, {"main": {**MAIN_CONFIG, "additive": True}}, caplog) == ""

    def test_rule_the_config_adds_is_reported(self, caplog):
        processor = _make_processor([PROTECTED_MAIN])

        text = _diff(
            processor,
            {"main": {**MAIN_CONFIG, "allowed_to_push": [{"user_id": 967}]}},
            caplog,
        )

        assert "967" in text
        assert text.count("40") >= 2

    def test_user_name_is_resolved_to_an_id_like_the_apply_path_does(self, caplog):
        processor = _make_processor([PROTECTED_MAIN])
        processor.gl.get_user_id_cached.return_value = 967

        assert (
            _diff(
                processor,
                {"main": {"protected": True, "allowed_to_push": [{"user": "johndoe"}]}},
                caplog,
            )
            != ""
        )
        processor.gl.get_user_id_cached.assert_called_with("johndoe")

    def test_no_access_replaces_the_roles_it_is_exclusive_with(self, caplog):
        processor = _make_processor([PROTECTED_MAIN])

        text = _diff(processor, {"main": {**MAIN_CONFIG, "push_access_level": 0}}, caplog)

        assert "main" in text
        assert '"push_access_levels": [{"access_level": 0}]' in text

    def test_squash_option_is_not_part_of_this_diff(self, caplog):
        processor = _make_processor([PROTECTED_MAIN])

        assert "squash_option" not in _diff(processor, {"main": {**MAIN_CONFIG, "squash_option": "always"}}, caplog)

    def test_missing_mandatory_protected_key_is_named(self, caplog):
        processor = _make_processor([PROTECTED_MAIN])

        text = _diff(processor, {"main": {"allow_force_push": True}}, caplog)

        assert "'protected' is mandatory" in text

    def test_the_config_is_not_rewritten_by_the_diff(self, caplog):
        processor = _make_processor([PROTECTED_MAIN])
        processor.gl.get_user_id_cached.return_value = 967
        config = {"main": {"protected": True, "allowed_to_push": [{"user": "johndoe"}], "squash_option": "always"}}

        _diff(processor, config, caplog)

        assert config["main"] == {
            "protected": True,
            "allowed_to_push": [{"user": "johndoe"}],
            "squash_option": "always",
        }
