"""
Reproduction of a live GitLab 400 seen on a retry apply (tenant leadprom, 2026-08-24):

    Merge access levels group has already been taken

on ~35 protected branches. The PATCH carried a group entry that GitLab already had,
because `build_patch_request_data` failed to recognise the existing group record as a
match for the group rule in the config.

Both sides below are real:

* the existing records are a verbatim GET of a live protected branch, group id and all;
* the config is put through the same two production transformations the apply path uses
  (`convert_user_and_group_names_to_ids` -> `map_config_to_protected_branch_get_data`).

Both configured rules are already present in GitLab, so the PATCH payload must be empty.
The first two tests failed before the matcher was taught to read the identity of the
GitLab record as well as that of the config rule; the rest hold on either side of it and
say that neither list was malformed - only the order they were walked in decided it.

`LIVE_PROTECTED_BRANCH_GET` below is that verbatim GET. Note its first
`merge_access_levels` entry: a group record carries BOTH a `group_id` AND an
`access_level` of 40, and that dual identity is what the matcher tripped over.
`LIVE_ALLOWED_TO_MERGE` is the branch's actual configuration:

    allowed_to_merge:
      - access_level: 40
      - group: leadprom/process/teams/merchanto-leads

The question here is identity - which record a rule is the same rule as - and not what
becomes of a record no rule claims. So the tests that put a rule against the whole live
snapshot, which holds records this configuration never mentions, ask for `additive=True`:
that was the regime in force when the 400 was observed, and it leaves the payload empty
when every configured rule is already there. What the default regime does with the rest
of that snapshot is test_branches_processor_exhaustive.py's subject.
"""

import json
from unittest.mock import MagicMock

import pytest

from gitlabform.gitlab import AccessLevel
from gitlabform.processors.project.branches_processor import BranchesProcessor
from gitlabform.processors.util.branch_protection import BranchProtection

LIVE_PROTECTED_BRANCH_GET = json.loads("""
{"id":232033920,"name":"staging",
 "push_access_levels":[{"id":288805357,"access_level":40,"access_level_description":"Maintainers","deploy_key_id":null,"user_id":null,"group_id":null}],
 "merge_access_levels":[
   {"id":332747900,"access_level":40,"access_level_description":"merchanto-leads","user_id":null,"group_id":140444807},
   {"id":251317784,"access_level":30,"access_level_description":"Developers + Maintainers","user_id":null,"group_id":null},
   {"id":332150660,"access_level":40,"access_level_description":"Maintainers","user_id":null,"group_id":null},
   {"id":332150661,"access_level":40,"access_level_description":"Vitalii Kyktov","user_id":10843916,"group_id":null},
   {"id":332150662,"access_level":40,"access_level_description":"Oleksii Donetskyi","user_id":28262808,"group_id":null},
   {"id":332150663,"access_level":40,"access_level_description":"Serhii Malyshev","user_id":33231013,"group_id":null}],
 "allow_force_push":false,
 "unprotect_access_levels":[{"id":162033197,"access_level":40,"access_level_description":"Maintainers","user_id":null,"group_id":null}],
 "code_owner_approval_required":true,"inherited":false}
""")

MERCHANTO_LEADS_PATH = "leadprom/process/teams/merchanto-leads"
MERCHANTO_LEADS_ID = 140444807


def transform_config(allowed_to_merge: list[dict]) -> list[dict]:
    """Run the config through the production transformation chain the apply path uses."""
    processor = BranchesProcessor(MagicMock(), False)
    processor.gl = MagicMock()
    processor.gl.get_group_id.return_value = MERCHANTO_LEADS_ID

    branch_config = {"protected": True, "allowed_to_merge": allowed_to_merge}
    resolved = processor.convert_user_and_group_names_to_ids(branch_config)
    return BranchProtection.map_config_to_protected_branch_get_data(resolved)["merge_access_levels"]


LIVE_ALLOWED_TO_MERGE = [
    {"access_level": AccessLevel.MAINTAINER.value},
    {"group": MERCHANTO_LEADS_PATH},
]


def test_group_name_is_resolved_onto_the_group_id_key():
    """Rules out a key-name mismatch: the transformed group rule does carry `group_id`."""
    transformed = transform_config(LIVE_ALLOWED_TO_MERGE)

    assert transformed[1]["group_id"] == MERCHANTO_LEADS_ID
    assert "group" not in transformed[1]
    # ... and it carries no access_level of its own, unlike the GitLab record it must match.
    assert transformed[1]["access_level"] is None


def test_role_and_group_rules_that_both_exist_produce_an_empty_patch():
    """
    Both configured rules are already in GitLab:
      - access_level 40 -> existing record 332150660 (role, Maintainers)
      - group 140444807 -> existing record 332747900 (group, merchanto-leads)

    Nothing has to change, so the PATCH payload must be empty. It used to come back as
    [{'group_id': 140444807}], which GitLab rejected with 400.
    """
    patch_data = BranchProtection.build_patch_request_data(
        transformed_access_levels=transform_config(LIVE_ALLOWED_TO_MERGE),
        existing_records=tuple(LIVE_PROTECTED_BRANCH_GET["merge_access_levels"]),
        additive=True,
    )

    assert patch_data == []


def test_group_record_listed_before_the_role_record_still_matches_both_rules():
    """
    The same defect minimised to the two records that decide it: a group record and a
    role record, both at access_level 40, with the group record listed first.
    """
    existing_records = (
        {"id": 332747900, "access_level": 40, "user_id": None, "group_id": MERCHANTO_LEADS_ID},
        {"id": 332150660, "access_level": 40, "user_id": None, "group_id": None},
    )

    patch_data = BranchProtection.build_patch_request_data(
        transformed_access_levels=transform_config(LIVE_ALLOWED_TO_MERGE),
        existing_records=existing_records,
    )

    assert patch_data == []


def test_a_group_record_is_not_the_role_it_carries_an_access_level_for():
    """
    The other half of the same identity. A group record GitLab returns carries an
    access_level of its own, but it is not the role rule: with nothing else on the
    branch, the configured role has to be created rather than read off the group.
    """
    existing_records = ({"id": 332747900, "access_level": 40, "user_id": None, "group_id": MERCHANTO_LEADS_ID},)

    patch_data = BranchProtection.build_patch_request_data(
        transformed_access_levels=transform_config([{"access_level": AccessLevel.MAINTAINER.value}]),
        existing_records=existing_records,
        additive=True,
    )

    assert patch_data == [{"access_level": AccessLevel.MAINTAINER.value}]


def test_a_user_record_is_not_the_role_it_carries_an_access_level_for():
    """The same for a user record, which carries an access_level just as a group does."""
    existing_records = ({"id": 332150661, "access_level": 40, "user_id": 10843916, "group_id": None},)

    patch_data = BranchProtection.build_patch_request_data(
        transformed_access_levels=transform_config([{"access_level": AccessLevel.MAINTAINER.value}]),
        existing_records=existing_records,
        additive=True,
    )

    assert patch_data == [{"access_level": AccessLevel.MAINTAINER.value}]


def test_role_record_listed_before_the_group_record_matches_both_rules():
    """
    What made the defect an ordering defect: the very same two rules against the very
    same two records, with the role record listed first, always matched cleanly.
    """
    existing_records = (
        {"id": 332150660, "access_level": 40, "user_id": None, "group_id": None},
        {"id": 332747900, "access_level": 40, "user_id": None, "group_id": MERCHANTO_LEADS_ID},
    )

    patch_data = BranchProtection.build_patch_request_data(
        transformed_access_levels=transform_config(LIVE_ALLOWED_TO_MERGE),
        existing_records=existing_records,
    )

    assert patch_data == []


def test_group_rule_listed_before_the_role_rule_in_config_matches_both_rules():
    """
    Reordering the *config* instead of the GitLab records also made it match, so neither
    side is malformed - only the order in which the two were walked decided it.
    """
    patch_data = BranchProtection.build_patch_request_data(
        transformed_access_levels=transform_config(list(reversed(LIVE_ALLOWED_TO_MERGE))),
        existing_records=tuple(LIVE_PROTECTED_BRANCH_GET["merge_access_levels"]),
        additive=True,
    )

    assert patch_data == []


@pytest.mark.parametrize(
    "allowed_to_merge",
    [
        pytest.param([{"access_level": AccessLevel.MAINTAINER.value}], id="role_rule_only"),
        pytest.param([{"group": MERCHANTO_LEADS_PATH}], id="group_rule_only"),
    ],
)
def test_either_rule_on_its_own_matches_the_live_records(allowed_to_merge):
    """Each rule matches the live snapshot on its own; only the pair used to fail."""
    patch_data = BranchProtection.build_patch_request_data(
        transformed_access_levels=transform_config(allowed_to_merge),
        existing_records=tuple(LIVE_PROTECTED_BRANCH_GET["merge_access_levels"]),
        additive=True,
    )

    assert patch_data == []
