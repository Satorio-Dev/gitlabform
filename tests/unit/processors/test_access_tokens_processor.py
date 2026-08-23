from datetime import date, timedelta
from unittest.mock import MagicMock, call, patch

import pytest

from gitlabform.constants import EXIT_INVALID_INPUT
from gitlabform.processors.group.group_access_tokens_processor import GroupAccessTokensProcessor
from gitlabform.processors.project.project_access_tokens_processor import ProjectAccessTokensProcessor
from gitlabform.processors.shared.access_tokens_processor import (
    AccessTokenAudit,
    AccessTokenDeliveryError,
)
from gitlabform.processors.util.decorators import SafeDict


def _token(
    name: str,
    token_id: int = 1,
    scopes=("api",),
    access_level: int = 40,
    description: str = "",
    active: bool = True,
    revoked: bool = False,
    expires_at=None,
    user_id: int = 100,
) -> MagicMock:
    token = MagicMock()
    token.name = name
    token.id = token_id
    token.get_id.return_value = token_id
    token.scopes = list(scopes)
    token.access_level = access_level
    token.description = description
    token.active = active
    token.revoked = revoked
    token.expires_at = expires_at
    token.user_id = user_id
    return token


def _variable(key: str, hidden: bool = True, environment_scope: str = "*") -> MagicMock:
    variable = MagicMock()
    variable.key = key
    variable.hidden = hidden
    variable.environment_scope = environment_scope
    return variable


def _entry(**overrides) -> dict:
    entry = {
        "name": "ci-bot",
        "scopes": ["read_api"],
        "access_level": 30,
        "deliver_to": {"ci_variable": "CI_BOT_TOKEN"},
    }
    entry.update(overrides)
    return entry


class _Fixture:
    """One project, its token list, its variable list and its members."""

    def __init__(self, processor_class, section: str, getter: str):
        self.section = section
        self.gitlab = MagicMock()
        with patch("gitlabform.processors.abstract_processor.GitlabWrapper"):
            self.processor = processor_class(self.gitlab)
        self.processor.gl = MagicMock()
        self.container = MagicMock()
        self.container.access_tokens.list.return_value = []
        self.container.variables.list.return_value = []
        self.container.members.list.return_value = []
        getattr(self.processor.gl, getter).return_value = self.container

    def tokens(self, *tokens):
        self.container.access_tokens.list.return_value = list(tokens)
        return self

    def variables(self, *variables):
        self.container.variables.list.return_value = list(variables)
        return self

    def members(self, *members):
        self.container.members.list.return_value = list(members)
        return self

    def config(self, **entries) -> SafeDict:
        return SafeDict({self.section: dict(entries)})

    def process(self, **entries):
        self.processor._process_configuration("some/path", self.config(**entries))


def _refused(fixture: "_Fixture", caplog, **entries) -> SystemExit:
    """Run the section and demand that it refused. The caller must then assert on
    the reason: a bare exit code also passes when some *other* gate fired, which
    would let the guard under test be removed unnoticed."""
    with caplog.at_level("CRITICAL"):
        with pytest.raises(SystemExit) as raised:
            fixture.process(**entries)
    return raised.value


@pytest.fixture
def project() -> _Fixture:
    return _Fixture(ProjectAccessTokensProcessor, "access_tokens", "get_project_by_path_cached")


@pytest.fixture
def group() -> _Fixture:
    return _Fixture(GroupAccessTokensProcessor, "group_access_tokens", "get_group_by_path_cached")


class TestSectionNames:
    def test_project_and_group_sections_are_registered_under_distinct_names(self, project, group):
        assert project.processor.configuration_name == "access_tokens"
        assert group.processor.configuration_name == "group_access_tokens"

    def test_group_processor_reads_the_group_not_the_project(self, group):
        group.process(bot=_entry(name="only-audited", deliver_to={"ci_variable": "X"}))
        group.processor.gl.get_group_by_path_cached.assert_called_with("some/path")
        group.processor.gl.get_project_by_path_cached.assert_not_called()


class TestIdempotency:
    def test_existing_token_with_the_same_name_is_not_created_again(self, project):
        project.tokens(_token("ci-bot", scopes=["read_api"], access_level=30))

        project.process(bot=_entry())

        project.container.access_tokens.create.assert_not_called()
        project.container.access_tokens.delete.assert_not_called()
        project.container.variables.create.assert_not_called()

    def test_scope_order_alone_is_not_a_difference(self, project):
        project.tokens(_token("ci-bot", scopes=["read_repository", "read_api"], access_level=30))

        project.process(bot=_entry(scopes=["read_api", "read_repository"]))

        project.container.access_tokens.create.assert_not_called()

    def test_revoked_token_with_the_same_name_does_not_count_as_present(self, project):
        project.tokens(_token("ci-bot", revoked=True, active=False))
        project.variables()

        project.process(bot=_entry())

        project.container.access_tokens.create.assert_called_once()

    def test_expired_token_with_the_same_name_does_not_count_as_present(self, project):
        project.tokens(_token("ci-bot", active=False))

        project.process(bot=_entry())

        project.container.access_tokens.create.assert_called_once()

    def test_tokens_are_listed_without_a_state_filter(self, project):
        project.process()
        project.container.access_tokens.list.assert_called_once_with(get_all=True)


class TestCreateAndDeliver:
    def _created(self, project, value: str = "glpat-secret-value"):
        created = _token("ci-bot", token_id=77)
        created.token = value
        created._attrs = {"token": value}
        project.container.access_tokens.create.return_value = created
        return created

    def test_creates_the_missing_token_and_delivers_the_value_hidden(self, project):
        self._created(project)

        project.process(bot=_entry())

        project.container.access_tokens.create.assert_called_once_with(
            {"name": "ci-bot", "scopes": ["read_api"], "access_level": 30}
        )
        (payload,), _ = project.container.variables.create.call_args
        assert payload["key"] == "CI_BOT_TOKEN"
        assert payload["value"] == "glpat-secret-value"
        assert payload["masked"] is True
        assert payload["masked_and_hidden"] is True

    def test_lifetime_days_is_turned_into_an_expiry_date_only_at_creation(self, project):
        self._created(project)

        project.process(bot=_entry(lifetime_days=30))

        (payload,), _ = project.container.access_tokens.create.call_args
        assert payload["expires_at"] == (date.today() + timedelta(days=30)).isoformat()

    def test_existing_hidden_variable_is_updated_instead_of_created(self, project):
        self._created(project)
        project.variables(_variable("CI_BOT_TOKEN", hidden=True))

        project.process(bot=_entry())

        project.container.variables.create.assert_not_called()
        project.container.variables.update.assert_called_once_with(
            "CI_BOT_TOKEN",
            {"key": "CI_BOT_TOKEN", "value": "glpat-secret-value"},
            filter={"environment_scope": "*"},
        )

    def test_readable_variable_blocks_the_creation_before_a_secret_exists(self, project):
        self._created(project)
        project.variables(_variable("CI_BOT_TOKEN", hidden=False))

        with pytest.raises(AccessTokenDeliveryError, match="is not hidden"):
            project.process(bot=_entry())

        project.container.access_tokens.create.assert_not_called()

    def test_failed_delivery_revokes_the_token_it_just_created(self, project):
        self._created(project)
        project.container.variables.create.side_effect = Exception("boom")

        with pytest.raises(AccessTokenDeliveryError) as raised:
            project.process(bot=_entry())

        project.container.access_tokens.delete.assert_called_once_with(77)
        assert "was revoked again" in str(raised.value)

    def test_failed_revoke_after_failed_delivery_screams_about_the_live_secret(self, project):
        self._created(project)
        project.container.variables.create.side_effect = Exception("boom")
        project.container.access_tokens.delete.side_effect = Exception("also boom")

        with pytest.raises(AccessTokenDeliveryError) as raised:
            project.process(bot=_entry())

        assert "REVOKING IT AGAIN ALSO FAILED" in str(raised.value)
        assert "Revoke it by hand now" in str(raised.value)

    def test_the_value_never_reaches_the_log(self, project, caplog):
        self._created(project, value="glpat-DO-NOT-LOG-ME")

        with caplog.at_level("DEBUG"):
            project.process(bot=_entry())

        assert "glpat-DO-NOT-LOG-ME" not in caplog.text

    def test_the_value_never_reaches_the_exception_message(self, project):
        self._created(project, value="glpat-DO-NOT-LOG-ME")
        project.container.variables.create.side_effect = Exception("server said: glpat-DO-NOT-LOG-ME")

        with pytest.raises(AccessTokenDeliveryError) as raised:
            project.process(bot=_entry())

        assert "glpat-DO-NOT-LOG-ME" not in str(raised.value)
        assert raised.value.__cause__ is None
        assert raised.value.__context__ is None

    def test_the_value_is_taken_off_the_returned_object(self, project):
        created = self._created(project)

        project.process(bot=_entry())

        assert "token" not in created._attrs

    def test_delivery_can_target_another_project(self, project):
        self._created(project)
        elsewhere = MagicMock()
        elsewhere.variables.list.return_value = []
        project.processor.gl.get_project_by_path_cached.side_effect = lambda path, *args: (
            elsewhere if path == "other/project" else project.container
        )

        project.process(bot=_entry(deliver_to={"ci_variable": "CI_BOT_TOKEN", "in_project": "other/project"}))

        elsewhere.variables.create.assert_called_once()
        project.container.variables.create.assert_not_called()


class TestRefusals:
    def test_enforce_is_refused(self, project, caplog):
        with caplog.at_level("CRITICAL"):
            with pytest.raises(SystemExit) as raised:
                project.processor._process_configuration(
                    "some/path", SafeDict({"access_tokens": {"enforce": True, "bot": _entry()}})
                )

        assert raised.value.code == EXIT_INVALID_INPUT
        assert "sets 'enforce', which is not supported here" in caplog.text
        assert "Undeclared tokens are reported by this section instead" in caplog.text

    def test_unsupported_keys_are_refused_not_ignored(self, project, caplog):
        raised = _refused(project, caplog, bot=_entry(delete=True))
        assert raised.code == EXIT_INVALID_INPUT
        assert "has unsupported keys: delete" in caplog.text

    def test_missing_name_is_refused(self, project, caplog):
        entry = _entry()
        del entry["name"]
        _refused(project, caplog, bot=entry)
        assert "has no 'name'" in caplog.text

    def test_missing_deliver_to_is_refused(self, project, caplog):
        entry = _entry()
        del entry["deliver_to"]
        _refused(project, caplog, bot=entry)
        assert "has no 'deliver_to'" in caplog.text
        assert "exactly once and never again" in caplog.text

    def test_two_entries_with_the_same_token_name_are_refused(self, project, caplog):
        _refused(project, caplog, one=_entry(), two=_entry(description="other"))
        assert "is already declared by another" in caplog.text

    def test_both_in_project_and_in_group_are_refused(self, project, caplog):
        _refused(
            project,
            caplog,
            bot=_entry(deliver_to={"ci_variable": "X", "in_project": "a/b", "in_group": "c"}),
        )
        assert "names both 'in_project' and 'in_group'" in caplog.text

    def test_unknown_access_level_name_is_refused(self, project, caplog):
        _refused(project, caplog, bot=_entry(access_level="archduke"))
        assert "is not one of the valid access levels" in caplog.text

    def test_access_level_name_is_accepted(self, project):
        project.tokens(_token("ci-bot", scopes=["read_api"], access_level=30))
        project.process(bot=_entry(access_level="developer"))
        project.container.access_tokens.create.assert_not_called()


class TestAudit:
    def test_scope_drift_is_reported_and_never_repaired(self, project):
        project.tokens(_token("ci-bot", scopes=["api"], access_level=30))

        with pytest.raises(AccessTokenAudit):
            project.process(bot=_entry(scopes=["read_api"]))

        project.container.access_tokens.create.assert_not_called()
        project.container.access_tokens.delete.assert_not_called()

    def test_access_level_drift_is_reported(self, project):
        project.tokens(_token("ci-bot", scopes=["read_api"], access_level=40))

        with pytest.raises(AccessTokenAudit):
            project.process(bot=_entry(access_level=30))

    def test_two_active_tokens_with_one_name_make_the_run_refuse(self, project):
        project.tokens(
            _token("ci-bot", token_id=1, scopes=["read_api"], access_level=30),
            _token("ci-bot", token_id=2, scopes=["read_api"], access_level=30),
        )

        with pytest.raises(AccessTokenAudit):
            project.process(bot=_entry())

        project.container.access_tokens.create.assert_not_called()

    def test_a_name_differing_only_by_whitespace_is_refused_not_duplicated(self, project, caplog):
        project.tokens(_token("Claude Slack ", scopes=["api"], access_level=40))

        with caplog.at_level("WARNING"):
            with pytest.raises(AccessTokenAudit):
                project.process(bot=_entry(name="Claude Slack", scopes=["api"], access_level=40))

        project.container.access_tokens.create.assert_not_called()
        assert "only in case or surrounding whitespace" in caplog.text

    def test_expiry_inside_the_declared_window_makes_the_run_red(self, project):
        soon = (date.today() + timedelta(days=5)).isoformat()
        project.tokens(_token("ci-bot", scopes=["read_api"], access_level=30, expires_at=soon))

        with pytest.raises(AccessTokenAudit):
            project.process(bot=_entry(warn_before_days=30))

    def test_expiry_outside_the_declared_window_is_quiet(self, project):
        later = (date.today() + timedelta(days=200)).isoformat()
        project.tokens(_token("ci-bot", scopes=["read_api"], access_level=30, expires_at=later))

        project.process(bot=_entry(warn_before_days=30))

    def test_undeclared_live_token_is_reported_but_never_revoked(self, project, caplog):
        project.tokens(_token("someone-elses", scopes=["api"]))

        with caplog.at_level("WARNING"):
            project.process()

        project.container.access_tokens.delete.assert_not_called()
        assert "are not declared" in caplog.text
        assert "someone-elses" in caplog.text

    def test_zero_compared_objects_is_logged_as_nothing_was_looked_at(self, project, caplog):
        with caplog.at_level("WARNING"):
            project.process()

        assert "0 tokens were compared" in caplog.text
        assert "not 'everything matches'" in caplog.text

    def test_bot_of_a_dead_token_still_holding_access_is_reported(self, project, caplog):
        project.tokens(_token("gone", active=False, revoked=True, user_id=4242))
        member = MagicMock()
        member.id = 4242
        member.username = "project_4_bot"
        member.access_level = 30
        project.members(member)

        with caplog.at_level("WARNING"):
            project.process()

        assert "leftover access" in caplog.text
        assert "4242" in caplog.text

    def test_bot_that_also_owns_a_live_token_is_not_reported_as_leftover(self, project, caplog):
        project.tokens(
            _token("old", token_id=1, active=False, revoked=True, user_id=4242),
            _token("new", token_id=2, user_id=4242),
        )
        member = MagicMock()
        member.id = 4242
        member.username = "project_4_bot"
        member.access_level = 30
        project.members(member)

        with caplog.at_level("WARNING"):
            project.process()

        assert "leftover access" not in caplog.text

    def test_unreadable_members_are_reported_as_not_measured_not_as_clean(self, project, caplog):
        project.tokens(_token("gone", active=False, revoked=True, user_id=4242))
        project.container.members.list.side_effect = Exception("403")

        with caplog.at_level("WARNING"):
            project.process()

        assert "not measured" in caplog.text


class TestDryRunDiff:
    def test_current_state_holds_only_active_tokens_normalized(self, project):
        project.tokens(
            _token("live", scopes=["read_repository", "api"], access_level=30, description="d"),
            _token("dead", token_id=2, active=False, revoked=True),
        )

        assert project.processor._get_current_state("some/path") == {
            "live": {"scopes": ["api", "read_repository"], "access_level": 30, "description": "d"}
        }

    def test_current_state_names_an_ambiguity_instead_of_picking_one(self, project):
        project.tokens(_token("twin", token_id=1), _token("twin", token_id=2))

        assert "AMBIGUOUS" in project.processor._get_current_state("some/path")["twin"]

    def test_desired_state_lines_up_with_the_current_state(self, project):
        assert project.processor._get_desired_state({"bot": _entry()}) == {
            "ci-bot": {"scopes": ["read_api"], "access_level": 30, "description": ""}
        }

    def test_dry_run_validates_the_config_too(self, project):
        with pytest.raises(SystemExit) as raised:
            project.processor._print_diff("some/path", {"enforce": True}, diff_only_changed=False)
        assert raised.value.code == EXIT_INVALID_INPUT

    def test_dry_run_says_what_would_be_created_and_writes_nothing(self, project, caplog):
        with caplog.at_level("INFO"):
            project.processor._print_diff("some/path", {"bot": _entry()}, diff_only_changed=False)

        assert "would be created" in caplog.text
        project.container.access_tokens.create.assert_not_called()
        project.container.variables.create.assert_not_called()
