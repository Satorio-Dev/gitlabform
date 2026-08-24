# GitLabForm — Satorio series

A fork of [gitlabform/gitlabform](https://github.com/gitlabform/gitlabform),
branched at upstream `9ab386c` (*refactor(processors): centralize dry-run diff in
AbstractProcessor*, #1353). Twenty-four commits on `satorio-series`. The upstream
README is kept below, unchanged.

## About this fork

`gitlabform --noop` is the one thing that stands between a YAML file and a live
GitLab tenant. At the base commit it told you almost nothing: of the 32
registered config sections, **4** produced a real dry-run diff and the other 28
printed `Diffing for section 'x' is not supported yet`. A human pressed apply
without having seen what would change.

This series carries the diff contract from #1353 to the end, and then makes what
it says true.

* **Every remaining section speaks.** Processors producing a dry-run diff:
  **7 → 32** of 35 registered slots, measured by which of them override
  `_get_current_state` or `_print_diff`. Both counts are taken on a tree that
  already carries this fork's own three new sections; at upstream `9ab386c` it is
  4 of 32. Three slots stay silent and are named rather than glossed:
  `group_protected_branches`, `group_saml_links`, `application_settings`.
* **The diff shows removals.** The loop walked the desired side only, so an
  entity deleted from the configuration appeared nowhere in the dry run — and was
  then removed for real, silently, by `enforce`. The one operation a dry run
  exists to warn about was the one it could not show. There is now a removal
  side, `(will be removed by enforce)` / `(only in GitLab)`, and `delete: true`
  is one mechanism on `AbstractProcessor` instead of six per-section answers.
* **The diff stops lying.** Six structural sources of false differences — ones
  the apply path would never reconcile, reported on every run forever — are each
  fixed at their cause. On one live tenant that removed 19 phantom
  `merge_requests_approval_rules changes:` lines from a single run with zero real
  changes in that section.
* **`access_tokens` and `group_access_tokens`** as a config section: exactly one
  write verb (create a declared token that does not exist), `enforce` refused by
  design, a mandatory delivery sink so a created secret is never left unheld.
* **Per-branch `squash_option`** via GraphQL, for tenants where squash must
  differ between branches of one repository.
* **A one-line YAML fix.** `ruamel.yaml` with no explicit width wrapped long
  values around column 80, and the break collapsed into a space on the way back:
  `\)` became `\ )`, silently, with nothing in the log. Measured on a live
  tenant: `commit_message_regex` 207 → 209 characters without the fix, 207 → 207
  with it.

### Hardened by dogfooding

Nine further commits come straight from running this fork against a live
70-node tenant, each fixing something the run itself exposed:

* access-level lists compare as sets, not by index — a reordered list no longer
  triggers a doomed update (`400: user has already been taken` on every apply);
* an entity diff reads **every** key before declaring "no change" — one matching
  key no longer hides a differing one behind set-iteration order;
* protected environments are read back after writing, and anything GitLab
  silently dropped (an approval rule whose user lacks the role) fails the node
  loudly instead of reporting success;
* a branch protection or remote mirror write GitLab refused now fails the node —
  no more green runs over red writes;
* protected environment updates go through `PUT` in place, closing the window
  where `DELETE`+`POST` left the environment unprotected;
* an unchanged environment with approval rules no longer writes on every run;
* a run ends with `GITLABFORM_SUMMARY:` — one line of JSON a program can parse,
  because long project names wrapped by the console log break every scraper;
* approval rules accept `user:`/`group:` names, resolved to ids the same way
  `deploy_access_levels` always did.

Unit tests **509 → 568**; black and mypy clean throughout; the diff-engine
fixes were each proven by perturbation (reordered list stays idle, changed
membership updates, five hash seeds agree).

### Evidence

Unit tests **244 → 509**. Each of the thirteen steps was checked with the
project's own gates at that point, with the versions pinned in `pyproject.toml`
(`black==26.5.1`, `mypy==2.3.0`): mypy Success, black clean, tests green on every
step. Every step was re-run in a virtualenv built from this checkout, one commit
at a time: 249, 284, 325, 369, 386, 403, 417, 429, 437, 463, 482, 497, 509, 509
tests green, black clean at each one.

None of that is offered as proof on its own. Guards were proven by
**perturbation** — broken deliberately, watched to go loud, restored: 11 guards
of the token section one at a time, 7 live perturbations plus 2 control runs
against the 32 processors that now diff, and 2 perturbations of the series gate
itself. One control run — not a perturbation — is what found the inherited-labels
defect.

The end state, measured live: a clean dry run over 57 projects and 13 groups,
exit 0, **not one diff line**, repeated independently. Hearing intact on the same
tree: one injected fake label produced `labels changes:`, one flipped
`keep_bots` produced two `(will be removed by enforce)`.

### What is *not* measured, said plainly

* **The apply path was never exercised.** Every live run was `--noop`. This
  series proves the dry-run diff *says* the right thing; it does not prove the
  apply path *does* it — including `enforce` deletions and `delete: true`.
* **No access token was ever created against a real GitLab.** Project and group
  access tokens require Premium/Ultimate; a live attempt returned
  `400 User does not have permission to create project access token`. That path
  rests on unit tests and perturbation.
* **The `variables` section is outside the evidence entirely** — excluded from
  every live run.
* **Perturbation was point-wise, not exhaustive.** Everything else rests on unit
  tests.
* **Upstream acceptance tests were not run** — they need a live GitLab with
  sufficient permissions.
* **The minimum GitLab tier for per-branch `squash_option` is unknown to us.**
  The live introspected schema does not state one. That is a question for a
  maintainer, not a claim of ours.

### Install

```bash
pip install "gitlabform @ git+https://gitlab.com/satorio/public/gitlabform@satorio-series-2026.08.24"
```

`gitlabform --version` still prints `6.2.1` — that is upstream's static version
string at the base commit and this series does not bump it. The tag, not the
version string, is what tells this build apart.

### Status

**Patches pending upstream review — nothing here has been sent yet.** The work is
also cut into three themed branches, stacked in the order they would be
submitted: `coverage` (every remaining section gets a diff) against `main`,
`removals` (show what `enforce` and `delete: true` will remove) against
`coverage`, and `truthfulness` (stop announcing what apply never does) against
`removals`. They stack rather than stand apart because the dependency between
them is circular, not because the cut was not attempted.

Licensed MIT, as upstream. Copyright of the original work stays with Greg
Dubicki and contributors; the changes in this fork are offered under the same
licence.

*— Satorio*

---

[![version](https://badge.fury.io/gh/gitlabform%2Fgitlabform.svg)](https://badge.fury.io/gh/gitlabform%2Fgitlabform)
![release date](https://img.shields.io/github/release-date/gitlabform/gitlabform)
[![Downloads](https://static.pepy.tech/badge/gitlabform/month)](https://pepy.tech/project/gitlabform)
[![code style](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![codecov](https://codecov.io/gh/gitlabform/gitlabform/branch/main/graph/badge.svg?token=NOMttkpB2A)](https://codecov.io/gh/gitlabform/gitlabform)
[![snyk](https://snyk.io/test/github/gitlabform/gitlabform/badge.svg)](https://security.snyk.io/package/pip/gitlabform)

<img src="https://raw.githubusercontent.com/gitlabform/gitlabform/main/docs/images/gitlabform-logo.png" width="600px" alt="logo">

🏗 GitLabForm is a specialized configuration as a code tool for GitLab:

* application settings,
* groups,
* projects,

...and more using hierarchical configuration written in YAML.

Please see <a href="https://gitlabform.github.io/gitlabform/">the project site</a> for more information.
