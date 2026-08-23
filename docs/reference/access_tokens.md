# Access tokens

This section manages [group access tokens](https://docs.gitlab.com/api/group_access_tokens/)
and [project access tokens](https://docs.gitlab.com/api/project_access_tokens/).

Use `group_access_tokens` for a group and `access_tokens` for a project. The two behave
identically otherwise.

## What this section does, and what it deliberately does not

The GitLab API has **no update verb for access tokens**. It can create, list, rotate and
revoke them, and nothing else. There is therefore no attribute of an existing token that
could be brought in line with the config without minting a new secret.

That is why this section has exactly **one write verb: create a declared token that does
not exist yet**. Everything else is reported:

| Situation | What happens |
|---|---|
| declared, does not exist | **created**, and its value is delivered (see below) |
| declared, exists, matches | nothing |
| declared, exists, `scopes` / `access_level` / `description` differ | reported, run ends non-zero |
| declared, expires within `warn_before_days` | reported, run ends non-zero |
| declared, but two active tokens carry that name | reported, run ends non-zero, nothing created |
| declared name differs from a live one only by case or whitespace | reported, run ends non-zero, nothing created |
| exists, not declared | reported as a warning; **never revoked** |
| a revoked or expired token's bot user still holds membership | reported as a warning |

`enforce: true` is **rejected** with an error rather than supported. Enforcing would revoke
every token that is not declared - revoking is irreversible, the value of a revoked token
cannot be recovered, and every consumer of it breaks at that instant.

Rotation is not implemented. `rotate` immediately revokes the previous token, so an
automatic rotation breaks live consumers *at once*, while a create-if-absent that does not
run breaks nothing.

## Where the value goes

GitLab returns the value of a new token exactly once and never again. A token created
without a destination would be a live credential that nobody holds, so `deliver_to` is
**required**.

The value is written straight into a **masked and hidden** CI/CD variable in the same run.
It is never written to the config, never written to the effective-configuration file, and
never appears in the log or in an exception message.

Two consequences worth knowing before you use this:

* Because the variable is hidden, its content can never be read back. The processor can
  prove that the variable *exists and was written in this run*, not that it holds the right
  value.
* GitLab can only make a variable hidden **at creation time**. If the target variable
  already exists and is not hidden, the section refuses and creates no token at all - a
  token value in a readable variable is a secret you can fetch over the API.

If writing the variable fails, the token that was just created is revoked again and the run
fails. If that revoke also fails, the error says so in as many words and names the token id
to revoke by hand.

## Keys

Per token:

| Key | Required | Meaning |
|---|---|---|
| `name` | yes | matched against GitLab **byte for byte**, including leading and trailing whitespace |
| `scopes` | yes | list of scopes; order does not matter |
| `access_level` | no | level name or number; defaults to `40` (maintainer), the same default the API uses |
| `description` | no | an omitted description means *no description*, not *whatever is there* |
| `lifetime_days` | no | used **only** when creating; never compared, never triggers a rotation |
| `warn_before_days` | no | turns on the expiry watchdog for this token |
| `deliver_to` | yes | where the value of a newly created token goes |

Inside `deliver_to`:

| Key | Required | Meaning |
|---|---|---|
| `ci_variable` | yes | name of the CI/CD variable to write |
| `in_project` | no | write the variable in this project instead of the token's own container |
| `in_group` | no | write the variable in this group instead; mutually exclusive with `in_project` |
| `environment_scope` | no | defaults to `*` |
| `protected` | no | defaults to `false`; only applied when the variable is created |

Any other key is an error, not a key that is quietly ignored. In particular there is no
`delete` and no `enforce` here.

`name` has to be written out rather than taken from the YAML key on purpose: token names
are matched exactly, and trailing whitespace in a name - which does occur in the wild - is
invisible in a key but obvious in a quoted value.

## Example

```yaml
projects_and_groups:
  group_1/*:
    group_access_tokens:
      release_bot: # just a label
        name: release-pipeline-bot
        scopes:
          - read_api
          - write_repository
        access_level: maintainer
        description: Backs RELEASE_BOT_TOKEN for the release pipeline
        lifetime_days: 365
        warn_before_days: 30
        deliver_to:
          ci_variable: RELEASE_BOT_TOKEN

  group_1/project_1:
    access_tokens:
      composer:
        name: composer-ci
        scopes:
          - read_api
          - read_repository
        access_level: developer
        warn_before_days: 30
        deliver_to:
          ci_variable: COMPOSER_CI_TOKEN
          in_project: group_1/project_2 # the CI that uses it lives elsewhere
```

!!! warning

    Do not point `deliver_to` at a variable that is also covered by a
    [`variables` or `group_variables`](ci_cd_variables.md) section running with
    `enforce: true`. That section would delete the delivered variable, and the token itself
    cannot be read back to write it again.

## Dry run

`--noop` shows the difference for this section: the compared attributes of every active
token, and which declared tokens would be created. It writes nothing.

A run that compared **zero** tokens says so explicitly. An empty result here means *nothing
was looked at*, which is not the same as *everything matches*.
