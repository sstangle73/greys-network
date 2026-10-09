# Security

## Reporting a vulnerability

Please report a security problem privately, not in a public issue. This project
lives on [GitLab](https://gitlab.com/sstangle73/greys-network) and is mirrored
to GitHub, and either route works:
- **[Report a vulnerability](https://github.com/sstangle73/greys-network/security/advisories/new)**
  on the GitHub mirror's *Security* tab, or
- a [GitLab issue](https://gitlab.com/sstangle73/greys-network/-/issues/new)
  marked **confidential**.

Only you and the maintainer see either one. Say what you can of:
- what's affected: the chart page, the report relay or the build;
- how to reproduce it, or a proof of concept;
- what someone could do with it.

## What happens next

- You'll hear back within 7 days.
- Once it's confirmed, it gets fixed, and a GitHub security advisory is
  published that credits you, unless you'd rather not be named. A CVE is
  requested through GitHub when the problem warrants one.
- Please keep it private until a fix is out, or for 90 days after your report,
  whichever comes first.

This is a one-person project with no bug bounty.

## Supported versions

Only the live chart and `main` get fixes.

## What's in scope

The chart page, the report relay in [`relay/`](relay/) and the build scripts.
These matter most:
- **Script injection into the chart page,** through a shared link's view in the
  URL or a field in the datasets.
- **The report relay:** anything that gets it to do more than file one labelled
  issue in this project, or that exposes its token.
- **The build:** anything that lets a contributed data row run code in CI.

Out of scope: spoilers and wrong data (they're bugs: use **Report a problem**
in the chart's credits), and denial of service by sheer volume.
