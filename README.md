# Repository Maintenance Guide

This repository contains two main folders:

```
.
├── FRONTEND/   # Client-side application
├── BACKEND/    # Server-side application
└── README.md
```

This guide explains how to keep the repository clean, consistent and up to date. **Every change, however small, must be made on a new branch.** Nobody commits directly to `main`.

---

## Table of Contents

1. [Golden Rules](#golden-rules)
2. [Branching Workflow](#branching-workflow)
3. [Branch Naming Conventions](#branch-naming-conventions)
4. [Commit Guidelines](#commit-guidelines)
5. [Keeping Your Branch Up to Date](#keeping-your-branch-up-to-date)
6. [Pull Requests](#pull-requests)
7. [Working in FRONTEND and BACKEND](#working-in-frontend-and-backend)
8. [Cleaning Up Branches](#cleaning-up-branches)
9. [Keeping the Repository Tidy](#keeping-the-repository-tidy)
10. [Quick Reference](#quick-reference)

---

## Golden Rules

- **Never commit directly to `main`.** Always create a new branch for every change.
- **One branch, one purpose.** Keep each branch focused on a single feature, fix or task.
- **Pull before you branch.** Always start from an up-to-date `main`.
- **Keep branches short-lived.** Merge small and often to reduce conflicts.
- **Delete branches after merging.** Stale branches create clutter and confusion.
- **Never commit secrets.** No API keys, passwords, tokens or `.env` files.

---

## Branching Workflow

Follow these steps every time you make a change.

### 1. Update your local `main`

```bash
git checkout main
git pull origin main
```

### 2. Create a new branch

```bash
git checkout -b <type>/<short-description>
```

Example:

```bash
git checkout -b feature/login-form
```

### 3. Make your changes

Work inside `FRONTEND/`, `BACKEND/`, or both, as needed. Commit regularly (see [Commit Guidelines](#commit-guidelines)).

### 4. Push your branch

```bash
git push -u origin <type>/<short-description>
```

### 5. Open a Pull Request

Open a pull request (PR) targeting `main`. See [Pull Requests](#pull-requests).

### 6. Merge and clean up

Once approved and merged, delete the branch (see [Cleaning Up Branches](#cleaning-up-branches)).

---

## Branch Naming Conventions

Use the format `<type>/<short-description>` in lowercase, with words separated by hyphens.

| Type        | Purpose                                   | Example                          |
|-------------|-------------------------------------------|----------------------------------|
| `feature/`  | New functionality                         | `feature/user-profile-page`      |
| `fix/`      | Bug fixes                                 | `fix/api-timeout-error`          |
| `hotfix/`   | Urgent production fixes                   | `hotfix/payment-crash`           |
| `refactor/` | Code restructuring without behaviour change | `refactor/auth-service`        |
| `docs/`     | Documentation changes                     | `docs/update-readme`             |
| `chore/`    | Maintenance, dependencies, config         | `chore/upgrade-dependencies`     |
| `test/`     | Adding or updating tests                  | `test/login-unit-tests`          |

### Scoping to FRONTEND or BACKEND (optional but recommended)

Include the area in the branch name so it is obvious where the change lives:

```
feature/frontend-navbar
fix/backend-session-expiry
chore/frontend-backend-update-deps
```

---

## Commit Guidelines

- Write clear, descriptive commit messages in the present tense.
- Keep the subject line under 72 characters.
- Make small, logical commits rather than one large commit.
- Use the following format:

```
<type>(<scope>): <short summary>

<optional longer description>
```

Examples:

```
feat(frontend): add password reset form
fix(backend): handle null user in auth middleware
docs: add setup steps to README
```

Where `<scope>` is `frontend`, `backend`, or omitted when the change spans both.

---

## Keeping Your Branch Up to Date

Long-running branches drift from `main`. Sync regularly, at least daily, and always before opening a PR.

### Option A: Rebase (preferred for a clean history)

```bash
git fetch origin
git rebase origin/main
```

If you have already pushed the branch, update it safely with:

```bash
git push --force-with-lease
```

### Option B: Merge

```bash
git fetch origin
git merge origin/main
```

### Resolving conflicts

1. Open the conflicted files and resolve the markers (`<<<<<<<`, `=======`, `>>>>>>>`).
2. Stage the resolved files: `git add <file>`
3. Continue: `git rebase --continue` (or `git commit` if merging).
4. Re-run tests for the affected folder before pushing.

---

## Pull Requests

Before opening a PR, check the following:

- [ ] Branch is up to date with `main`
- [ ] Code builds and runs locally
- [ ] Tests pass (see the checks below)
- [ ] Linting and formatting pass
- [ ] No debug code, commented-out blocks or stray files
- [ ] No secrets or credentials included
- [ ] Documentation updated where relevant

### PR title and description

- Use a clear title, matching the commit format, e.g. `feat(frontend): add password reset form`.
- Describe **what** changed and **why**.
- Link the related issue or ticket.
- Include screenshots for visible FRONTEND changes.
- Note any BACKEND API, schema or configuration changes.

### Review rules

- At least one reviewer must approve before merging.
- Address all review comments before merging.
- Prefer **squash and merge** to keep `main` history tidy.
- Do not merge your own PR without review, unless it is an agreed exception.

---

## Working in FRONTEND and BACKEND

### General

- Only change files in the folder relevant to your task.
- If a change needs both folders, keep them in the **same branch and PR** so they ship together.
- Each folder manages its own dependencies. Do not mix them.

### FRONTEND

```bash
cd FRONTEND
npm install        # install dependencies
npm run lint       # check code style
npm test           # run tests
npm run build      # confirm it builds
```

### BACKEND

```bash
cd BACKEND
# install dependencies (adjust to your stack)
npm install        # or: pip install -r requirements.txt
npm run lint       # or your linter of choice
npm test           # run tests
```

> Adjust the commands above to match the tools your project actually uses.

### Dependencies

- Commit lock files (`package-lock.json`, `yarn.lock`, `poetry.lock`, etc.).
- Update dependencies on a dedicated `chore/` branch, never mixed with feature work.
- Review dependency updates for breaking changes before merging.

---

## Cleaning Up Branches

### After a PR is merged

Delete the remote and local branches.

```bash
# Delete the remote branch
git push origin --delete <branch-name>

# Delete the local branch
git branch -d <branch-name>
```

> Most Git hosts can auto-delete branches on merge. Enable this in the repository settings.

### Periodic housekeeping

Run these regularly (for example, weekly):

```bash
# Remove references to branches deleted on the remote
git fetch --prune

# List local branches already merged into main
git branch --merged main

# Delete all local branches already merged (excluding main)
git branch --merged main | grep -v "main" | xargs git branch -d
```

### Stale branches

- Review branches with no activity for 30 days.
- Ask the owner whether the work is still needed.
- Delete abandoned branches after confirmation.

---

## Keeping the Repository Tidy

### Use `.gitignore`

Never commit generated or local files. Make sure each folder ignores items such as:

```
node_modules/
dist/
build/
.env
.env.*
*.log
.DS_Store
.idea/
.vscode/
__pycache__/
```

### Repository hygiene checklist

- [ ] No unused files, dead code or commented-out blocks
- [ ] No large binaries or build artefacts committed
- [ ] Consistent formatting enforced by a formatter (e.g. Prettier, Black)
- [ ] Linting enforced in CI
- [ ] README and documentation kept current
- [ ] Dependencies reviewed and updated regularly
- [ ] Secrets stored in environment variables or a secrets manager

### Protect `main`

Configure branch protection on `main` to:

- Require pull requests before merging
- Require at least one approving review
- Require status checks (build, lint, tests) to pass
- Block force pushes and deletions

### Tagging releases

Tag stable releases so they can be tracked and rolled back:

```bash
git tag -a v1.2.0 -m "Release 1.2.0"
git push origin v1.2.0
```

Follow [Semantic Versioning](https://semver.org): `MAJOR.MINOR.PATCH`.

---

## Quick Reference

| Task                          | Command                                         |
|-------------------------------|-------------------------------------------------|
| Update main                   | `git checkout main && git pull origin main`     |
| Create a branch               | `git checkout -b feature/my-change`             |
| Stage and commit              | `git add . && git commit -m "feat: message"`   |
| Push a new branch             | `git push -u origin feature/my-change`          |
| Sync with main (rebase)       | `git fetch origin && git rebase origin/main`    |
| Delete local branch           | `git branch -d feature/my-change`               |
| Delete remote branch          | `git push origin --delete feature/my-change`    |
| Prune deleted remote branches | `git fetch --prune`                             |
| See branch status             | `git status`                                    |
| View recent history           | `git log --oneline --graph --decorate -10`      |

---

## Questions?

If something in this guide is unclear or out of date, open a `docs/` branch and submit a PR to improve it.
