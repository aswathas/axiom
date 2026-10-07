# Push to GitHub

This repo has no remote configured — the build environment had no GitHub
credentials, so the commit is made locally and you push it yourself.

```bash
cd AXIOM_Project

# 1. create an EMPTY repo on github.com (no README, no .gitignore — it would conflict)

# 2. point at it and push
git remote add origin https://github.com/<your-username>/<repo-name>.git
git branch -M main
git push -u origin main
```

You will be prompted for a GitHub username and a Personal Access Token
(not your account password). GitHub no longer accepts passwords over HTTPS.

To use SSH instead:

```bash
ssh-keygen -t ed25519 -C "you@example.com"
cat ~/.ssh/id_ed25519.pub          # paste into GitHub → Settings → SSH keys
git remote add origin git@github.com:<your-username>/<repo-name>.git
git push -u origin main
```
