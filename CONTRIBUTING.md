# Contributing to Issuarr

## Branches
- `dev` is where development happens. Every change lands there first, and each push builds the `ghcr.io/issuarr/issuarr:dev` image.
- `main` holds releases. A release is a pull request from `dev` into `main`, merged with a merge commit (not squash or rebase) so the two branches keep the same history. Each push to `main` builds `ghcr.io/issuarr/issuarr:latest`, and a `vX.Y.Z` tag on `main` also builds `X.Y.Z` and `X.Y` image tags.
- Hotfixes that cannot wait for a release go to `main` and are then merged back into `dev`.

## Changelog
[CHANGELOG.md](CHANGELOG.md) lists every change in plain English, newest first, each line ending with the commit id that made it. It is also a page on the website, which is published from `main`, so it updates when a release is merged.

When preparing a release, on `dev` run `python3 .github/changelog.py` to list the commits since the last release that the changelog doesn't mention yet. Rewrite each line so a user understands it, merge related lines, and add them under **Unreleased (on dev)**. In the release PR, rename that heading to the version and date (for example `## 1.0.0 (2026-11-01)`) and start a new empty **Unreleased (on dev)** section above it.

## Pull Requests
- Make pull requests against the `dev` branch.
- You're probably going to get some comments or questions from us.  They will be to ensure consistency and maintainability
- Each PR should come from its own feature branch not the `dev` or `main` branch in your fork, with a meaningful name (what is being added/fixed).
- Make meaningful commits, squash them if necessary.
- Use [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) to format your commit messages - applications like [commitizen](https://commitizen-tools.github.io/commitizen/) can help you get in that habit.
- Try to keep it to one feature/bug fix per pull request to keep things clean and easy to understand.
- Ensure that you've enabled a docker image to be built on your own branch using our GitHub Actions workflows.
- Test your changes on a real Issuarr instance on real data.
- Rebase before submitting PRs.  If the `dev` branch has moved on since you started writing, don't expect reviewers to handle merging your code in case it conflicts.

## Publisher imprints
`data/imprints.json` maps publishers to their imprints and each imprint's publication run (`YYYY.MM - YYYY.MM`, end left blank if still running). Issuarr uses it to file imprint series under their parent publisher and to fill `$Imprint` in folder names. Installs fetch it from `main` once a day, so raise `version` whenever you change it.

## AI-assisted contributions
Issuarr itself is built with AI assistance, and AI-assisted contributions are welcome on the same terms as any other.

- **Say so.** Mention in the PR that AI helped and roughly how.
- **Own it.** You are responsible for every line you submit. Read it, understand why it works, and be ready to answer questions about it in your own words.
- **Test it for real.** Run the change on a real Issuarr instance with real data, not only the scenario you changed. Include what you tested in the PR.
- **Keep it small and accurate.** One fix or feature per PR. AI can help draft the description, but check that it says what the change actually does, and cut anything that doesn't help a reviewer.
