# Working on Issuarr

Full rules are in [CONTRIBUTING.md](CONTRIBUTING.md). The ones that matter most for Claude sessions:

- **Branch from `dev` and open pull requests against `dev`.** `dev` is the default branch; each push to it builds the `:dev` image.
- **Never push to `main` directly.** `main` only changes through a release PR from `dev`, merged with a merge commit (not squash or rebase), or a hotfix PR that is then merged back into `dev`.
- **Before a release**, run `python3 .github/changelog.py` on `dev` to list commits the changelog doesn't mention yet, then add plain-English lines for them under **Unreleased (on dev)** in [CHANGELOG.md](CHANGELOG.md).
- Use [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) and keep each PR to one fix or feature.
