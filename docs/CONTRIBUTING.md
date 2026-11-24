# Contributing

Thank you for considering making a contribution.

Contributions can include:

- Reporting bugs
- Suggesting improvements or new features
- Improving documentation
- Adding or improving tests
- Making code changes

This guide covers:

- [Raising issues](#raising-issues)
  - [Reporting bugs](#reporting-bugs)
  - [Suggesting changes](#suggesting-changes)
- [Making changes](#making-changes)
  - [Setting up your environment](#setting-up-your-environment)
  - [Working on a branch](#working-on-a-branch)
  - [Changing documentation](#changing-documentation)
  - [Changing code](#changing-code)
  - [Checking your changes](#checking-your-changes)
  - [Opening a pull request](#opening-a-pull-request)
- [Maintaining the project](#maintaining-the-project)
  - [Releasing a version](#releasing-a-version)
  - [Updating from the template](#updating-from-the-template)
- [Running commands](#running-commands)

## Raising issues

Use GitHub issues to report bugs or suggest changes.

Before raising an issue, search the existing open and closed issues to see whether it has already been reported or discussed.

### Reporting bugs

A useful bug report should include enough information for someone else to reproduce and investigate the problem.

Where relevant, include:

- A clear description of the problem
- The behaviour you expected
- The behaviour you observed
- A minimal example that reproduces the problem
- The version of the library you are using
- Your Python version
- Any relevant error messages or tracebacks

Please use code blocks for code, output, and tracebacks.

If possible, reduce examples to the smallest case that still demonstrates the problem.
This makes it easier to determine whether the behaviour is a bug and to identify its cause.

### Suggesting changes

Feature requests and other suggestions are also welcome.

Describe the problem or use case you would like to address rather than only the proposed implementation.
Where useful, include:

- The behaviour you would like
- Why it would be useful
- Examples of how it might be used
- Alternatives you have considered

For substantial changes, please raise an issue before starting implementation, so that any decisions can be made before significant work is done.

## Making changes

### Setting up your environment

For code contributions you will need:

- A GitHub account
- A development environment with:

  - Python 3.11 (the minimum version of Python supported)
  - `hatch>=1.18`
- Access to the internet for GitHub and installation of packages from PyPI

If Hatch is not available in your development environment, see the [Hatch installation instructions](https://hatch.pypa.io/latest/install/).

The project uses Hatch to manage Python environments for development.

To set up your development environment, run

```shell
hatch run pre-commit:install
```

### Working on a branch

To make a contribution:

1. Make a branch for your changes, either

   - in the repo if you have write access, or
   - in a fork of the repo if you do not have write access
2. Make and commit changes on your branch until they meet the definition of done below
3. Make a pull request from your branch to the main branch in the repo

Keep pull requests focused on a single change where practical.
Unrelated changes are easier to review when submitted separately.

Documentation-only and other non-code contributions can use the same workflow.
Only the checks and definition-of-done items relevant to the change need to apply.

### Changing documentation

#### Writing Markdown

Write Markdown prose with one sentence per source line.

### Changing code

#### Running tests

`hatch test` passes any arguments after its own flags through to `pytest`, so during development you can narrow to one file or test rather than running the full matrix each time:

```shell
hatch test tests/test_foo.py  # One file
hatch test tests/test_foo.py::test_bar  # One test
hatch test -k roundtrip  # Tests matching an expression
hatch test --python 3.11 tests/test_foo.py  # One file, one Python version
```

Use these commands for a fast iterative development loop.

Run the full `hatch test --all` matrix before opening a pull request.

The `tests/` directory should mirror the package structure under `src/spanmark/`.
Test modules are named `test_*.py`; name helper modules in `tests/` with a leading underscore, such as `_helpers.py`.

#### Adding dependencies

Add dependencies in `pyproject.toml`.

#### Writing docstrings

Use concise Google-style docstrings.
Let annotations carry types and signatures carry ordinary defaults.
Avoid boilerplate documentation that merely repeats the signature.

### Checking your changes

Pull requests must pass checks in CI before they can be merged into main.

Run the same checks in your development environment and fix any problems before opening a pull request:

```shell
hatch check code --fix  # Check and fix linting and formatting using ruff - Note that this mutates files
hatch check types  # Check type annotations using pyrefly
hatch test --all  # Run tests using pytest for all locally available versions of Python in the matrix
hatch run pre-commit:ci  # Run all pre-commit hooks
```

Some of these commands modify files in your working tree: `hatch check code --fix` applies lint and formatting fixes, and other pre-commit hooks may also modify files.

After running the commands, review and commit the resulting changes — otherwise CI will run against the unfixed version and fail.

A clean run that leaves no changes means there was nothing to fix.

### Opening a pull request

Pull requests are squash-merged, with the pull request title as the commit message.
Write the title as a short summary of the change in the imperative, such as "Add support for X".

Changes are ready for review when all applicable items below are complete:

- Relevant tests have been added or updated in the `tests/` directory
- Relevant documentation has been added to or updated in the `docs/` directory
- Relevant Google-style docstrings have been added or updated
- User-facing changes are recorded under `## [Unreleased]` in `docs/CHANGELOG.md`
- All applicable checks above pass
- Generated fixes from linting or formatting checks have been committed

Record changes in `docs/CHANGELOG.md` under the [Keep a Changelog](https://keepachangelog.com/) headings `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed` and `Security`.
Record only changes that affect users of the package, including changes to the supported Python versions.

## Maintaining the project

### Releasing a version

Maintainers make releases by pushing a version tag to `main`.
CI does the rest: nothing is built or uploaded by hand.

1. Choose the version number, `X.Y.Z`, following [Semantic Versioning](https://semver.org/).
2. In a pull request, move the unreleased changes in `docs/CHANGELOG.md` into a section for the release, and merge it:

   - Rename `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD`, and add a new, empty `## [Unreleased]` above it
   - Update the links at the end of the file, for example for a first release:

     ```markdown
     [Unreleased]: https://github.com/pdhall99/spanmark/compare/0.1.0...HEAD
     [0.1.0]: https://github.com/pdhall99/spanmark/releases/tag/0.1.0
     ```

     For later releases, compare `[Unreleased]` with the new version, and the new version with the previous one:

     ```markdown
     [Unreleased]: https://github.com/pdhall99/spanmark/compare/0.2.0...HEAD
     [0.2.0]: https://github.com/pdhall99/spanmark/compare/0.1.0...0.2.0
     ```
3. Tag the merged commit on `main`, and push the tag:

   ```shell
   git switch main
   git pull
   git tag X.Y.Z
   git push origin X.Y.Z
   ```

   Tags are plain `X.Y.Z`, without a `v` prefix: the package version comes from the tag.
4. Follow the tag's CI run.
   It checks the tag is `X.Y.Z` and on `main`, runs the checks and tests, builds the package, and checks the wheel's version matches the tag.
5. If the `pypi` environment requires approval, approve the deployment in the run (**Review deployments**).
   CI then publishes to PyPI, and creates a GitHub release with the changelog section as its notes and the built package attached.

If the run fails before publishing, for example because `docs/CHANGELOG.md` has no section for the tag, fix the problem through a pull request, then move the tag to the fixed commit:

```shell
git push --delete origin X.Y.Z
git switch main
git pull
git tag --force X.Y.Z
git push origin X.Y.Z
```

Once a version is on PyPI it cannot be uploaded again, so release any fix as a new version.

### Updating from the template

This project was generated from a [Copier](https://copier.readthedocs.io/) template, recorded with your answers to its questions in `.copier-answers.yml`.

To apply a newer version of the template, run

```shell
uvx copier update --defaults
```

Review the changes and resolve any conflicts, where the project has changed the same lines as the template, then commit them through a pull request.

A template update can change the supported Python versions; record any change to them in `docs/CHANGELOG.md`.

## Running commands

Run every development command through Hatch, which manages the environments for the project: don't install packages with `pip` or run tools such as `pytest` or `ruff` directly.

- Don't skip pre-commit hooks or checks, for example with `git commit --no-verify`
- Don't edit `src/spanmark/_version.py`: it is generated from the git tag
- Commit any changes the checks make, as described in [checking your changes](#checking-your-changes)

```shell
hatch run pre-commit:install  # Set up the pre-commit hooks
hatch test  # Run the tests on the default version of Python
hatch test --all  # Run the tests on every version of Python in the matrix
hatch check code --fix  # Check and fix linting and formatting
hatch check types  # Check type annotations
hatch run pre-commit:ci  # Run all pre-commit hooks
hatch build  # Build the package
```
