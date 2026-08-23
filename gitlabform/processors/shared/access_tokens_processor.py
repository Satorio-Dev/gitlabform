import abc
import sys
from datetime import date, timedelta
from logging import critical, debug, info, warning
from typing import Any, Dict, List, NoReturn, Optional, Tuple, Union

from gitlab.v4.objects import Group, Project

from gitlabform.constants import EXIT_INVALID_INPUT
from gitlabform.gitlab import AccessLevel, GitLab
from gitlabform.processors.abstract_processor import AbstractProcessor

DEFAULT_ACCESS_LEVEL: int = AccessLevel.MAINTAINER.value

TOKEN_KEYS = frozenset(
    {
        "name",
        "scopes",
        "access_level",
        "description",
        "lifetime_days",
        "warn_before_days",
        "deliver_to",
    }
)

DELIVERY_KEYS = frozenset({"ci_variable", "in_project", "in_group", "environment_scope", "protected"})

COMPARED_ATTRIBUTES: Tuple[str, ...] = ("scopes", "access_level", "description")


class AccessTokenAudit(Exception):
    """Raised at the end of a section when the audit found a difference that
    this processor deliberately refuses to repair on its own."""


class AccessTokenDeliveryError(Exception):
    """Raised when the value of a freshly created token could not be delivered."""


class _Report:
    """What one container's audit found. Plain lists so that the log can name
    every case instead of collapsing them into a single verdict."""

    def __init__(self) -> None:
        self.declared: int = 0
        self.live_active: int = 0
        self.live_inactive: int = 0
        self.compared: List[str] = []
        self.matching: List[str] = []
        self.missing: List[str] = []
        self.drifted: List[str] = []
        self.expiring: List[str] = []
        self.ambiguous: List[str] = []
        self.near_miss: List[str] = []
        self.undeclared: List[str] = []
        self.dead_bots: List[str] = []
        self.not_measured: List[str] = []

    @property
    def failures(self) -> List[str]:
        """Findings that must make the run go red. Undeclared tokens and dead
        bot memberships are *not* here on purpose: they are true, useful and
        unactionable-by-this-run, and a permanently red healthy project is worse
        than no watchdog at all."""
        return self.ambiguous + self.near_miss + self.drifted + self.expiring


class AccessTokensProcessor(AbstractProcessor, metaclass=abc.ABCMeta):
    def __init__(self, configuration_name: str, gitlab: GitLab):
        super().__init__(configuration_name, gitlab)
        self._tokens_cache: Dict[str, list] = {}

    @abc.abstractmethod
    def _get_container(self, project_or_group: str) -> Union[Group, Project]:
        """Return the group or project object that owns the tokens."""

    def _list_tokens(self, project_or_group: str) -> list:
        """Every token of the container, in every state, listed once per run.

        Revoked and expired ones are kept: their bot users keep the membership,
        and its permissions, after the token itself died.
        """
        if project_or_group not in self._tokens_cache:
            container = self._get_container(project_or_group)
            self._tokens_cache[project_or_group] = list(container.access_tokens.list(get_all=True))
        return self._tokens_cache[project_or_group]

    def _validate(self, project_or_group: str, section: Any) -> Dict[str, dict]:
        """Turn the section into {token name: entry}, refusing loudly instead of
        guessing. Returns the entries keyed by their GitLab-side name."""

        if not isinstance(section, dict):
            self._invalid(f"Section '{self.configuration_name}' for {project_or_group} must be a map of token entries.")

        if "enforce" in section:
            self._invalid(
                f"Section '{self.configuration_name}' for {project_or_group} sets 'enforce', which is not"
                f" supported here. Enforcing would revoke every token that is not declared. Revoking is"
                f" irreversible, the value of a revoked token cannot be recovered, and each of its consumers"
                f" breaks at that instant. Undeclared tokens are reported by this section instead; revoke the"
                f" unwanted ones deliberately."
            )

        declared: Dict[str, dict] = {}

        for alias, entry in section.items():
            where = f"'{alias}' in section '{self.configuration_name}' for {project_or_group}"

            if not isinstance(entry, dict):
                self._invalid(f"Entry {where} must be a map.")

            unknown = sorted(set(entry.keys()) - TOKEN_KEYS)
            if unknown:
                self._invalid(
                    f"Entry {where} has unsupported keys: {', '.join(unknown)}."
                    f" Supported keys are: {', '.join(sorted(TOKEN_KEYS))}."
                    f" Note that neither 'delete' nor rotation is supported by this section."
                )

            name = entry.get("name")
            if not isinstance(name, str) or not name:
                self._invalid(
                    f"Entry {where} has no 'name'. It is required and must be written out explicitly:"
                    f" it is matched against GitLab byte for byte, including any leading or trailing"
                    f" whitespace, and a YAML key would hide exactly that."
                )

            scopes = entry.get("scopes")
            if not isinstance(scopes, list) or not scopes or not all(isinstance(s, str) for s in scopes):
                self._invalid(f"Entry {where} needs a non-empty list of 'scopes'.")

            self._access_level(entry, where)

            for numeric in ("lifetime_days", "warn_before_days"):
                value = entry.get(numeric)
                if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value <= 0):
                    self._invalid(
                        f"Entry {where} has '{numeric}: {value}'; it must be a positive whole number of days."
                    )

            self._validate_delivery(entry.get("deliver_to"), where)

            if name in declared:
                self._invalid(
                    f"Entry {where} declares the token name '{name}', which is already declared by another"
                    f" entry in the same section. A token is identified by its name inside its container."
                )

            declared[name] = entry

        return declared

    def _validate_delivery(self, deliver_to: Any, where: str) -> None:
        if deliver_to is None:
            self._invalid(
                f"Entry {where} has no 'deliver_to'. GitLab returns the value of a token exactly once and"
                f" never again, so a token created without a declared destination would be a live credential"
                f" that nobody holds. Declare where its value goes."
            )

        if not isinstance(deliver_to, dict):
            self._invalid(f"'deliver_to' in {where} must be a map.")

        unknown = sorted(set(deliver_to.keys()) - DELIVERY_KEYS)
        if unknown:
            self._invalid(
                f"'deliver_to' in {where} has unsupported keys: {', '.join(unknown)}."
                f" Supported keys are: {', '.join(sorted(DELIVERY_KEYS))}."
            )

        if not isinstance(deliver_to.get("ci_variable"), str) or not deliver_to.get("ci_variable"):
            self._invalid(f"'deliver_to' in {where} needs 'ci_variable' - the name of the CI/CD variable to write.")

        if deliver_to.get("in_project") and deliver_to.get("in_group"):
            self._invalid(
                f"'deliver_to' in {where} names both 'in_project' and 'in_group'. Name at most one;"
                f" without either, the variable is written in the same container the token belongs to."
            )

    def _access_level(self, entry: dict, where: str) -> int:
        """Access levels are normally turned into numbers by
        AccessLevelsTransformer before a processor ever sees them; this stays
        tolerant so that the section behaves the same when it is used directly."""
        raw = entry.get("access_level", DEFAULT_ACCESS_LEVEL)
        if isinstance(raw, bool):
            self._invalid(f"'access_level' in {where} must be a level name or number.")
        if isinstance(raw, int):
            return raw
        try:
            return AccessLevel.get_value(str(raw))
        except KeyError:
            self._invalid(
                f"'access_level: {raw}' in {where} is not one of the valid access levels:"
                f" {', '.join(AccessLevel.get_canonical_names())}."
            )

    @staticmethod
    def _invalid(message: str) -> NoReturn:
        critical(message)
        sys.exit(EXIT_INVALID_INPUT)

    @staticmethod
    def _is_active(token: Any) -> bool:
        return bool(getattr(token, "active", False)) and not bool(getattr(token, "revoked", False))

    @staticmethod
    def _observed(token: Any) -> Dict[str, Any]:
        return {
            "scopes": sorted(getattr(token, "scopes", None) or []),
            "access_level": getattr(token, "access_level", None),
            "description": getattr(token, "description", None) or "",
        }

    def _desired(self, entry: dict) -> Dict[str, Any]:
        return {
            "scopes": sorted(entry["scopes"]),
            "access_level": self._access_level(entry, "the config"),
            "description": entry.get("description") or "",
        }

    def _get_current_state(self, project_or_project_and_group: str) -> Dict[str, Dict[str, Any]]:
        state: Dict[str, Dict[str, Any]] = {}
        seen: Dict[str, list] = {}

        for token in self._list_tokens(project_or_project_and_group):
            if not self._is_active(token):
                continue
            seen.setdefault(token.name, []).append(token)

        for name, tokens in seen.items():
            if len(tokens) > 1:
                state[name] = {"AMBIGUOUS": f"{len(tokens)} active tokens share this name: ids {self._ids(tokens)}"}
            else:
                state[name] = self._observed(tokens[0])

        return state

    def _get_desired_state(self, entity_config: dict) -> Dict[str, Dict[str, Any]]:
        return {entry["name"]: self._desired(entry) for entry in entity_config.values() if isinstance(entry, dict)}

    def _print_diff(self, project_or_project_and_group: str, entity_config, diff_only_changed: bool) -> None:
        declared = self._validate(project_or_project_and_group, entity_config)

        super()._print_diff(project_or_project_and_group, entity_config, diff_only_changed)

        report = self._audit(project_or_project_and_group, declared)
        self._log_report(project_or_project_and_group, report, dry_run=True)

    def _audit(self, project_or_group: str, declared: Dict[str, dict]) -> _Report:
        report = _Report()
        report.declared = len(declared)

        live = self._list_tokens(project_or_group)
        active = [token for token in live if self._is_active(token)]
        inactive = [token for token in live if not self._is_active(token)]
        report.live_active = len(active)
        report.live_inactive = len(inactive)

        by_name: Dict[str, list] = {}
        for token in active:
            by_name.setdefault(token.name, []).append(token)

        today = date.today()

        for name, entry in declared.items():
            tokens = by_name.get(name, [])

            if len(tokens) > 1:
                report.ambiguous.append(
                    f"'{name}': {len(tokens)} active tokens in {project_or_group} share this name"
                    f" (ids {self._ids(tokens)}). GitLab does not require token names to be unique, so this"
                    f" section refuses to guess which one the declaration means. Revoke the extra ones."
                )
                continue

            if not tokens:
                near = self._near_misses(name, by_name.keys())
                if near:
                    report.near_miss.append(
                        f"'{name}' has no exact match in {project_or_group}, but these active tokens differ"
                        f" from it only in case or surrounding whitespace: {near}. Creating a second token"
                        f" here is far more likely to be a typo than an intent, so nothing was created."
                    )
                else:
                    report.missing.append(name)
                continue

            token = tokens[0]
            report.compared.append(name)

            observed = self._observed(token)
            desired = self._desired(entry)
            differing = [key for key in COMPARED_ATTRIBUTES if observed.get(key) != desired.get(key)]

            if differing:
                details = ", ".join(
                    f"{key}: {observed.get(key)!r} in GitLab != {desired.get(key)!r} in config" for key in differing
                )
                report.drifted.append(
                    f"'{name}' (id {token.get_id()}) differs: {details}. None of these can be edited -"
                    f" the GitLab API has no update verb for access tokens - so fixing it means creating a"
                    f" replacement token and revoking this one. This section will not do that on its own."
                )
            else:
                report.matching.append(name)

            warn_before = entry.get("warn_before_days")
            expires_at = getattr(token, "expires_at", None)
            if warn_before and expires_at:
                days_left = (date.fromisoformat(str(expires_at)) - today).days
                if days_left <= int(warn_before):
                    report.expiring.append(
                        f"'{name}' (id {token.get_id()}) expires on {expires_at}, in {days_left} day(s),"
                        f" which is within its declared warn_before_days of {warn_before}."
                    )
            elif warn_before and not expires_at:
                report.not_measured.append(
                    f"'{name}' declares warn_before_days but GitLab reports no expiry date for it,"
                    f" so its remaining lifetime was not measured."
                )

        for name in sorted(by_name.keys() - declared.keys()):
            report.undeclared.append(f"'{name}' (ids {self._ids(by_name[name])})")

        self._audit_dead_bots(project_or_group, active, inactive, report)

        return report

    def _audit_dead_bots(self, project_or_group: str, active: list, inactive: list, report: _Report) -> None:
        """Revoking or expiring a token does not remove the bot user it belongs
        to from the container's members, so its access level survives the token.
        Only something that reads tokens can tell such a member from a live one."""
        if not inactive:
            return

        alive_bots = {getattr(token, "user_id", None) for token in active}
        dead_bots = {getattr(token, "user_id", None) for token in inactive} - alive_bots
        dead_bots.discard(None)
        if not dead_bots:
            return

        try:
            container = self._get_container(project_or_group)
            members = list(container.members.list(get_all=True))
        except Exception as error:
            report.not_measured.append(
                f"Could not list the members of {project_or_group}, so it is not known whether the bot users"
                f" of its {len(inactive)} dead token(s) still hold access: {error}"
            )
            return

        for member in members:
            if member.id in dead_bots:
                report.dead_bots.append(
                    f"user {member.id} ('{getattr(member, 'username', '?')}') still holds access level"
                    f" {getattr(member, 'access_level', '?')} in {project_or_group}, although the only token(s)"
                    f" it owns here are revoked or expired."
                )

    @staticmethod
    def _near_misses(name: str, live_names) -> str:
        needle = name.strip().casefold()
        matches = [f"'{other}'" for other in live_names if other != name and other.strip().casefold() == needle]
        return ", ".join(sorted(matches))

    @staticmethod
    def _ids(tokens: list) -> str:
        return ", ".join(str(token.get_id()) for token in tokens)

    def _log_report(self, project_or_group: str, report: _Report, dry_run: bool) -> None:
        info(
            f"'{self.configuration_name}' in {project_or_group}: {report.declared} declared,"
            f" {report.live_active} active and {report.live_inactive} inactive token(s) in GitLab;"
            f" {len(report.compared)} compared on {', '.join(COMPARED_ATTRIBUTES)}."
        )

        if not report.compared:
            warning(
                f"'{self.configuration_name}' in {project_or_group}: 0 tokens were compared."
                f" Nothing was verified here - this is 'nothing was looked at', not 'everything matches'."
            )

        for name in report.matching:
            debug(f" * access token '{name}' in {project_or_group} matches its declaration.")

        for name in report.missing:
            if dry_run:
                info(f" * access token '{name}' in {project_or_group} does not exist and would be created.")
            else:
                info(f" * access token '{name}' in {project_or_group} was created.")

        for line in report.ambiguous + report.near_miss + report.drifted + report.expiring:
            warning(f" ! {line}")

        for line in report.not_measured:
            warning(f" ? not measured: {line}")

        if report.undeclared:
            warning(
                f" ~ {len(report.undeclared)} active token(s) in {project_or_group} are not declared:"
                f" {'; '.join(report.undeclared)}. They are reported only and are never revoked by this section."
            )

        for line in report.dead_bots:
            warning(f" ~ leftover access: {line}")

    def _process_configuration(self, project_or_group: str, configuration: dict) -> None:
        declared = self._validate(project_or_group, configuration[self.configuration_name])
        report = self._audit(project_or_group, declared)

        for name in report.missing:
            self._create_and_deliver(project_or_group, declared[name])

        self._log_report(project_or_group, report, dry_run=False)

        if report.failures:
            raise AccessTokenAudit(
                f"Section '{self.configuration_name}' for {project_or_group} found"
                f" {len(report.failures)} difference(s) that it deliberately does not repair by itself."
                f" See the warnings above."
            )

    def _create_and_deliver(self, project_or_group: str, entry: dict) -> None:
        name = entry["name"]

        sink = self._preflight_sink(project_or_group, entry["deliver_to"], name)

        payload: Dict[str, Any] = {
            "name": name,
            "scopes": sorted(entry["scopes"]),
            "access_level": self._access_level(entry, f"'{name}'"),
        }
        if entry.get("description"):
            payload["description"] = entry["description"]
        if entry.get("lifetime_days"):
            payload["expires_at"] = (date.today() + timedelta(days=int(entry["lifetime_days"]))).isoformat()

        info(
            f"Creating access token '{name}' in {project_or_group}"
            f" (scopes: {', '.join(payload['scopes'])}; access_level: {payload['access_level']})."
        )

        container = self._get_container(project_or_group)
        token = container.access_tokens.create(payload)
        token_id = token.get_id()
        secret = ""
        failure: Optional[AccessTokenDeliveryError] = None

        try:
            secret = self._take_secret(token, name)
            self._store(sink, secret, name)
        except Exception as error:
            revoked = self._revoke(container, token_id)
            failure = AccessTokenDeliveryError(
                self._delivery_failure_message(name, token_id, project_or_group, sink, revoked, error, secret)
            )

        if failure is not None:
            raise failure

        info(
            f"Access token '{name}' in {project_or_group} was created and its value was written to the"
            f" masked and hidden CI/CD variable '{sink['key']}' (scope '{sink['scope']}') in {sink['where']}."
            f" The value is not printed, not stored in the config and cannot be read back from GitLab."
        )

    def _preflight_sink(self, project_or_group: str, deliver_to: dict, token_name: str) -> Dict[str, Any]:
        """Resolve and check the CI/CD variable the value will be written to.

        Called before the token is created: an unusable destination found
        afterwards would mean a live token nobody holds.
        """
        key = deliver_to["ci_variable"]
        scope = deliver_to.get("environment_scope", "*")

        if deliver_to.get("in_project"):
            where = deliver_to["in_project"]
            container: Union[Group, Project] = self.gl.get_project_by_path_cached(where)
        elif deliver_to.get("in_group"):
            where = deliver_to["in_group"]
            container = self.gl.get_group_by_path_cached(where)
        else:
            where = project_or_group
            container = self._get_container(project_or_group)

        existing = None
        for variable in container.variables.list(get_all=True):
            if variable.key == key and getattr(variable, "environment_scope", "*") == scope:
                existing = variable
                break

        if existing is not None and not bool(getattr(existing, "hidden", False)):
            raise AccessTokenDeliveryError(
                f"CI/CD variable '{key}' (scope '{scope}') already exists in {where} and is not hidden."
                f" GitLab can only make a variable hidden when it is created, so writing the value of token"
                f" '{token_name}' there would leave the secret readable through the API. No token was created."
                f" Delete that variable yourself, or point 'deliver_to' at another name."
            )

        return {
            "container": container,
            "where": where,
            "key": key,
            "scope": scope,
            "existing": existing,
            "protected": bool(deliver_to.get("protected", False)),
        }

    @staticmethod
    def _take_secret(token: Any, name: str) -> str:
        """Move the value off the token object and return it as the only copy.

        RESTObject renders every attribute it holds, so leaving the value there
        would let any f-string on the object downstream print the secret.
        """
        secret = getattr(token, "token", None)
        if not secret:
            raise AccessTokenDeliveryError(f"GitLab did not return a value for the token '{name}' it just created.")
        try:
            token._attrs.pop("token", None)
        except Exception:
            pass
        return str(secret)

    @staticmethod
    def _store(sink: Dict[str, Any], secret: str, token_name: str) -> None:
        container = sink["container"]

        if sink["existing"] is None:
            container.variables.create(
                {
                    "key": sink["key"],
                    "value": secret,
                    "environment_scope": sink["scope"],
                    "masked": True,
                    "masked_and_hidden": True,
                    "protected": sink["protected"],
                    "variable_type": "env_var",
                    "description": f"Value of the '{token_name}' access token. Written by GitLabForm.",
                }
            )
        else:
            container.variables.update(
                sink["key"],
                {"key": sink["key"], "value": secret},
                filter={"environment_scope": sink["scope"]},
            )

    @staticmethod
    def _revoke(container: Union[Group, Project], token_id: Any) -> bool:
        try:
            container.access_tokens.delete(token_id)
            return True
        except Exception as error:
            debug(f"Could not revoke access token id {token_id}: {error}")
            return False

    @staticmethod
    def _delivery_failure_message(
        name: str,
        token_id: Any,
        project_or_group: str,
        sink: Dict[str, Any],
        revoked: bool,
        error: Exception,
        secret: str,
    ) -> str:
        reason = str(error)
        if secret:
            reason = reason.replace(secret, "<the token value>")

        if revoked:
            tail = f" The token was revoked again, so nothing was left behind, but nothing was created either."
        else:
            tail = (
                f" REVOKING IT AGAIN ALSO FAILED. Access token id {token_id} in {project_or_group} is LIVE and"
                f" nobody holds its value. Revoke it by hand now."
            )

        return (
            f"The value of the access token '{name}' (id {token_id}) that was just created in"
            f" {project_or_group} could not be written to the CI/CD variable '{sink['key']}'"
            f" (scope '{sink['scope']}') in {sink['where']}: {reason}.{tail}"
        )
