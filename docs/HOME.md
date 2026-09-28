# Where this repo lives

This project has **one canonical git repository** (a bare mirror) and two working
checkouts. Nothing here is a *second* tree to sync from — the working checkouts
are clones of the mirror, and the mirror is the source of truth.

```
/Volumes/CrucialX10/design-to-site.git     <- bare mirror, CANONICAL
/Volumes/CrucialX10/design-to-site         <- working checkout (recommended)
/Volumes/CrucialX10/codex/2026-09-27/i-n/outputs/anthosting-coming-soon
                                           <- original working checkout
```

## Normal use

Work in `/Volumes/CrucialX10/design-to-site`:

```sh
cd /Volumes/CrucialX10/design-to-site
./bootstrap.sh                 # once: venv + each site's node_modules
cd pipeline && ./build.sh      # build every design
              ./qa/verify.sh   # score each design (expect a 2.71 / 2.76 / 2.99)
../preview/start-persistent.sh 4180    # http://127.0.0.1:4180/
```

Commit in a checkout, then push to the mirror:

```sh
git push origin main           # origin = /Volumes/CrucialX10/design-to-site.git
```

From the other checkout, `git pull --ff-only` to pick it up. Both checkouts and
the mirror share history, so the two can never silently diverge.

## Adding a design

```sh
cd pipeline
python qa/newdesign.py <name> path/to/design.png   # config + ref + content + site
python qa/mkart.py <name> --out <name>.svg         # trace the artwork
node gen-page.mjs <name> && node to-astro.mjs <name>
(cd ../sites/variant-<name> && npm install && npm run build)
./qa/verify.sh <name>
```

## Publishing to GitHub

The mirror has **no remote configured** and `gh` is not installed, so this is a
manual step:

```sh
cd /Volumes/CrucialX10/design-to-site
git remote add github git@github.com:<you>/design-to-site.git
git push github main
```

To push from the bare mirror directly:

```sh
git --git-dir=/Volumes/CrucialX10/design-to-site.git push git@github.com:<you>/design-to-site.git main
```
