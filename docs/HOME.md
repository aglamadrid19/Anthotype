# Where this repo lives

**Anthotype** — turn a design PNG into a code-native website.

> **Agent note:** the absolute paths below are the author's machine layout, not a
> contract. Treat them as illustrative: resolve the repo relative to wherever you
> are working, and never "fix" a path here to match your environment. Nothing in
> the pipeline depends on these paths — `qa/_env.py` resolves python/node/chrome
> by probing, with no hardcoded paths anywhere in the repo.

One canonical git repository (a bare mirror) and two working checkouts. The
checkouts are clones of the mirror, so neither can silently diverge.

```
/Volumes/CrucialX10/anthotype.git    <- bare mirror (local canonical)
/Volumes/CrucialX10/anthotype        <- working checkout (use this one)
/Volumes/CrucialX10/codex/2026-09-27/i-n/outputs/anthosting-coming-soon
                                     <- second checkout (same history)
```

Both checkouts have two remotes:

| remote | points at | use for |
|---|---|---|
| `origin` | `https://github.com/aglamadrid19/Anthotype.git` | the published repo |
| `mirror` | `/Volumes/CrucialX10/anthotype.git` | the local bare mirror |

## Normal use

Work in `/Volumes/CrucialX10/anthotype`:

```sh
cd /Volumes/CrucialX10/anthotype
./bootstrap.sh                 # once: venv + each site's node_modules
cd pipeline && ./build.sh      # build every design
              ./qa/verify.sh   # score each design (expect 2.71 / 2.76 / 2.99)
../preview/start-persistent.sh 4180    # http://127.0.0.1:4180/
```

## Committing and pushing

`git push-anthotype` (an alias set on both checkouts) pushes `main` to the
mirror *and* GitHub in one step:

```sh
git push-anthotype             # mirror + GitHub
```

Or manually:

```sh
git push mirror main           # local bare mirror
git push origin main           # GitHub
```

Then sync the other checkout:

```sh
git -C /Volumes/CrucialX10/codex/2026-09-27/i-n/outputs/anthosting-coming-soon \
    pull --ff-only origin main
```

## Adding a design

```sh
cd pipeline
python qa/newdesign.py <name> path/to/design.png   # config + ref + content + site
python qa/mkart.py <name> --out <name>.svg         # trace the artwork
node gen-page.mjs <name> && node to-astro.mjs <name>
(cd ../sites/variant-<name> && npm install && npm run build)
./qa/verify.sh <name>
```

## GitHub

Published at **https://github.com/aglamadrid19/Anthotype**.
