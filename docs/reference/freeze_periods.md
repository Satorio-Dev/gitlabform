# Deploy freezes (freeze periods)

This section manages the [deploy freezes](https://docs.gitlab.com/user/project/releases/#prevent-unintentional-releases-by-setting-a-deploy-freeze)
of a project, through the [Freeze Periods API](https://docs.gitlab.com/api/freeze_periods/).

All freeze periods are defined under the `freeze_periods` key of a project. The key
each period is written under is just a label for you - GitLab does not store it. Each
period takes the fields of the API: `freeze_start` and `freeze_end`, both required and
both in cron format, and the optional `cron_timezone`, which GitLab defaults to `UTC`.

If the key name is `enforce` and it is set to `true`, then only the freeze periods
defined here will remain in the project - all others will be deleted.

If a period's only non-required value is `delete: true`, then that period is removed.

```yaml
projects_and_groups:
  group_1/project_1:
    freeze_periods:
      weekend:
        freeze_start: "0 23 * * 5"
        freeze_end: "0 7 * * 1"
        cron_timezone: "Europe/Warsaw"
      release_review:
        freeze_start: "0 18 * * 4"
        freeze_end: "0 9 * * 5"
      last_years_holidays:
        freeze_start: "0 0 24 12 *"
        freeze_end: "0 0 2 1 *"
        delete: true
      enforce: true # optional
```

## What identifies a period

A freeze period has no name in GitLab, so the pair `(freeze_start, freeze_end)` is what
identifies it. Two periods declared under different labels but with the same pair of
cron expressions are one entity to GitLab; that configuration is refused, both labels
named, rather than one of them silently winning.

The same identity has a consequence when you edit: rewriting one of the two cron
expressions does not change a period, it declares a different one. The former period
shows on the removal side of the `--noop` diff - `(will be removed by enforce)` where
`enforce` is on, `(only in GitLab)` where it is not - and the new one is created. Only
`cron_timezone` is edited in place.
