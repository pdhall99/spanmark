# Contributing

A lightweight span-annotation widget for interactive Python environments.

Thank you for considering making a contribution.

## Prerequisites

- A GitHub account
- A development environment with:
  - Python 3.10 (the minimum version of Python supported)
  - `hatch>=1.17`
- Access to the internet for GitHub and installation of packages from PyPI

If `hatch` is not available in your development environment, install it by running

```shell
uv tool install "hatch>=1.17"
```

## Setup

The project uses Hatch to manage Python environments for development.
To set up your development environment, run

```shell
hatch run pre-commit:install
```

## Workflow

To make a code contribution:

1. Make a branch for your changes, either
    - in the repo if you have write access, or
    - in a fork of the repo if you do not have write access
2. Make and commit code changes on your branch until they meet the definition of done below
3. Make a pull request from your branch to the main branch in the repo

### During development

#### Testing

`hatch test` passes any arguments after its own flags through to `pytest`, so during development you can narrow to one file or test rather than running the full matrix each time:

```shell
hatch test tests/test_foo.py  # One file
hatch test tests/test_foo.py::test_bar  # One test
hatch test -k roundtrip  # Tests matching an expression
hatch test --python 3.10 tests/test_foo.py  # One file, one Python version
```

Use these commands for a fast iterative development loop.
Run the full `hatch test --all` matrix before opening a pull request.

#### Adding dependencies

Add dependencies in `pyproject.toml`
The core package is intentionally dependency-free; a new runtime dependency requires a design-level justification.

### Checks

Making a pull request normally triggers CI checks, which must pass before the pull request can be merged into main.

Run these same checks in your development environment and fix any problems before opening a pull request:

```shell
hatch check code --fix  # Check and fix linting and formatting using ruff - Note that this mutates files
hatch check types  # Check type annotations using pyrefly
hatch test --all  # Run tests using pytest for all locally available versions of python in the matrix
hatch run docs:build  # Build the Zensical documentation site
hatch run pre-commit:ci  # Run all pre-commit hooks
```

Some of these commands modify files in your working tree: `hatch check code --fix` applies lint and formatting fixes, and other pre-commit hooks may also modify files.
After running the commands, review and commit the resulting changes — otherwise CI will run against the unfixed version and fail.
A clean run that leaves no changes means there was nothing to fix.

### Definition of done

Code changes are ready for review when

- Relevant tests have been added or updated in the `tests/` directory
- Relevant documentation has been added to or updated in the `docs/` directory
- Relevant Google-style docstrings have been added or updated
- All applicable checks above pass
- Generated fixes from linting or formatting checks have been committed
