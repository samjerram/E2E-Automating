# Presentation checkpoint (locked baseline)

This repo has a **git tag** you can return to anytime.

| Item | Value |
|------|--------|
| **Tag** | `checkpoint/presentation-stable` |
| **Purpose** | Known-good UI + Flask wiring for **Regression Pack (demo2)** and **Bulk Order (demo3)** only |

## Restore this exact version

From repo root:

```bat
git fetch --tags
git checkout checkpoint/presentation-stable
```

Or hard-reset your branch to the tag (discards local changes — use only if you mean it):

```bat
git reset --hard checkpoint/presentation-stable
```

## Push the checkpoint to GitHub (optional)

After `git push`, also push tags:

```bat
git push origin main
git push origin checkpoint/presentation-stable
```

## One-time: set your Git name/email (Windows)

If commits fail with “Author identity unknown”:

```bat
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
```

## Note

If you also changed files that are **not** in the checkpoint commit (e.g. on another machine), run `git status` and commit those before relying only on this tag.
