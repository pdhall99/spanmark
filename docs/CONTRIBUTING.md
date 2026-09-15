# Contributing

Thank you for considering making a contribution.

Contributions can include:

- Reporting bugs
- Suggesting improvements or new features
- Improving documentation
- Adding or improving tests
- Making code changes

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

## Prerequisites

For code contributions you will need:

- A GitHub account
- A development environment with:

  - Python 3.10 (the minimum version of Python supported)
  - `hatch>=1.17`
- Access to the internet for GitHub and installation of packages from PyPI

If Hatch is not available in your development environment, see the [Hatch installation instructions](https://hatch.pypa.io/latest/install/).

## Setup

The project uses Hatch to manage Python environments for development.

To set up your development environment, run

```shell
hatch run pre-commit:install
```

## Workflow

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

Add dependencies in `pyproject.toml`.

The core package is intentionally dependency-free; a new runtime dependency requires a design-level justification.

### Checks

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

### Definition of done

Changes are ready for review when all applicable items below are complete:

- Relevant tests have been added or updated in the `tests/` directory
- Relevant documentation has been added to or updated in the `docs/` directory
- Relevant Google-style docstrings have been added or updated
- All applicable checks above pass
- Generated fixes from linting or formatting checks have been committed
