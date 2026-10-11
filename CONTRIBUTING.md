# Contributing to Issuarr

## Pull Requests
- Make pull requests against the `trusselo` branch.
- You're probably going to get some comments or questions from us.  They will be to ensure consistency and maintainability
- Each PR should come from its own feature branch not the `trusselo` branch in your fork, with a meaningful name (what is being added/fixed).
- Make meaningful commits, squash them if necessary.
- Use [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) to format your commit messages - applications like [commitizen](https://commitizen-tools.github.io/commitizen/) can help you get in that habit.
- Try to keep it to one feature/bug fix per pull request to keep things clean and easy to understand.
- Ensure that you've enabled a docker image to be built on your own branch using our GitHub Actions workflows.
- Test your changes on a real Issuarr instance on real data.
- Rebase before submitting PRs.  If the `trusselo` branch has moved on since you started writing, don't expect reviewers to handle merging your code in case it conflicts.

## AI-assisted contributions
Issuarr itself is built with AI assistance, and AI-assisted contributions are welcome on the same terms as any other.

- **Say so.** Mention in the PR that AI helped and roughly how.
- **Own it.** You are responsible for every line you submit. Read it, understand why it works, and be ready to answer questions about it in your own words.
- **Test it for real.** Run the change on a real Issuarr instance with real data, not only the scenario you changed. Include what you tested in the PR.
- **Keep it small and accurate.** One fix or feature per PR. AI can help draft the description, but check that it says what the change actually does, and cut anything that doesn't help a reviewer.
