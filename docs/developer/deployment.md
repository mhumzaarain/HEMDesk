# Deployment

HEMDesk ships with a small `cli.py` wrapper around Docker
Compose and Docker Swarm — one place for the dev and operator workflows. Run
`uv run cli.py --help` for the full command list.

| | Development | Production |
| --- | --- | --- |
| Web server | Django `runserver`, hot-reloading | nginx :8080 → gunicorn |
| Orchestrator | `docker compose` (`uv run cli.py compose-up`) | Docker Swarm, single node (`uv run cli.py stack-deploy`) |
| App port | `:8000` | `:8080` |
| Database port | published on `:5432` (dev override) | not published |

## Development

Terminal 1 — start the stack and leave it running:

```bash
uv run cli.py init-workspace   # one time: creates .env with generated secrets
uv run cli.py compose-up       # -d to run detached instead
```

Terminal 2 — create the accounts, once:

```bash
uv run cli.py manage seed_demo
```

This starts `db`, `ollama` (+ a one-shot `ollama-init` that pulls the chat and
embedding models), and `runserver` on hot-reloading `:8000`.

### Logging in for the first time

Starting the stack applies migrations but **creates no accounts**, so nothing
can log in until you run `seed_demo`. After that, sign in at
<http://127.0.0.1:8000> as **`admin`** — **the password is the
`DEMO_PASSWORD` line in your `.env` file**, which `init-workspace` filled with
a generated value. The demo users `engineer1`–`engineer3` and
`staff1`–`staff10` use that same password; the full list is in
[Setup & contributing](setup.md#the-demo-accounts).

### Restarting the worker

The `worker` service (Procrastinate) does **not** autoreload — after changing
background-task code, restart it:

```bash
uv run cli.py restart worker
```

`compose-down` stops the stack. Running Django directly on the host (against
a Dockerized Postgres) is still a valid alternative — see
[Setup & contributing](setup.md).

## Production (single node)

Production runs on Docker Swarm rather than plain Compose, so the same
compose files describe both a local dev stack and a deployable stack. One
node is all the current setup supports.

**One-time setup:**

```bash
docker swarm init
```

Set `ENVIRONMENT=production` in `.env` (this is what makes `cli.py` refuse
`compose-up`/`compose-down` and require Swarm instead).

Also set `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` in `.env` for the
hostname users will actually browse to. `CSRF_TRUSTED_ORIGINS` needs the
scheme and port, e.g. `http://cmms.hospital.local:8080` — the localhost
defaults only work for local testing.

**Deploy:**

```bash
uv run cli.py compose-build   # build the production images
uv run cli.py stack-deploy    # deploy to the swarm
```

`stack-deploy` refuses to run unless `ENVIRONMENT=production`, checks that no
`.env` value is quoted (Swarm passes env values to containers verbatim,
quotes included, so a quoted value would end up literally in the app), and
checks that Swarm is active on the node before deploying.

### Which image production runs

Every release is published as one image, used by both `web` and `worker`:

```
ghcr.io/mhumzaarain/hemdesk
```

The `IMAGE_TAG` line in `.env` chooses which release this node runs:

```bash
IMAGE_TAG=1.2.0     # this release, until you change the line
IMAGE_TAG=latest    # whichever release is newest at deploy time
```

There is no leading `v`. The release tagged `v1.2.0` in git publishes the image
tag `1.2.0`. Writing `v1.2.0` here fails the pull with `manifest unknown`.

The published images are built for `amd64` (x86-64) only. They will not run on
an ARM server. An ARM node has to build its own image instead:

```bash
uv run cli.py compose-build
```

That is also the answer for a server with no access to `ghcr.io`.

**The running containers never read `.env`.** This surprises people, so it is
worth being precise. When you run `stack-deploy`, Swarm reads `.env` once,
takes a *copy* of the values, and hands that copy to the containers it starts.
The containers keep using their copy for as long as they run. Editing `.env`
afterwards changes the file on disk and nothing else — the app carries on with
the old values.

So whenever you change anything in `.env`, the order is always:

1. Edit `.env`.
2. Run `uv run cli.py stack-deploy` — this is what actually delivers the new
   values to the containers.
3. Only then run whatever command depends on the new value.

Skipping step 2 is the most common cause of "I changed it but nothing
happened".

**Upgrades:**

1. `git pull` — the server still needs the repository, because `cli.py`, the
   compose files, and `nginx.conf` live there.
2. Set `IMAGE_TAG` in `.env` to the release you want to run.
3. `uv run cli.py stack-deploy` — Swarm pulls the image and restarts the
   services.

```bash
git pull
uv run cli.py stack-deploy    # after editing IMAGE_TAG in .env
```

Rolling back is the same three steps with the previous release. Nothing is
rebuilt, because every published release stays in the registry.

One thing to watch: if `IMAGE_TAG=latest` and someone has run `compose-build`
on this node, the local build shadows the published `latest`, and Swarm keeps
using the local one. Pin a release and this cannot happen.

> Swarm configs are immutable — if `nginx.conf` changed since the last
> deploy, `stack-deploy` will fail to update it in place. Run
> `uv run cli.py stack-rm` first, then `stack-deploy`.

If any manuals show keyword search only, run the backfill once:

```bash
uv run cli.py manage reembed_manuals
```

### Create the first admin account

A brand-new deployment has an empty database: no users at all. If you open the
app now, the login page will reject every password, because there is nothing
to log in as. So before anyone can use HEMDesk, you create one administrator
account from the command line. That account then creates everyone else's from
inside the app.

Do **not** use `seed_demo` for this. That command is for development: it
invents fake equipment and fake staff, and its password is written in this
repository for anyone to read.

**Step 1 — choose your password.** Open the `.env` file on the server. It
already contains these four lines, copied from `.env.example`:

```bash
SUPERUSER_USERNAME=admin
SUPERUSER_PASSWORD=changeme-in-production
SUPERUSER_EMAIL=admin@hospital.example
SUPERUSER_EMPLOYEE_ID=ADMIN-0001
```

Replace `changeme-in-production` with a real password of your own. You can
change the username and email too, but you don't have to. Whatever you put on
these lines *is* your login — there is nothing else to look up.

!!! danger
    The placeholder password is public. Anyone who has seen this project knows
    it. If you leave it unchanged on a server that other people can reach, they
    can sign in as an administrator and read or alter every equipment and
    complaint record. Change it before the server goes live.

**Step 2 — deliver the new password to the app.** Do not skip this, even
though you just deployed. The containers do not read `.env` while they run;
they use the copy of the values Swarm gave them at the last deploy. Your new
password is only in the file so far:

```bash
uv run cli.py stack-deploy
```

If you skip this step, the next command still runs and still reports that it
created the account — but it creates it with the password from your *previous*
deploy, which is the public placeholder. You then cannot log in with the
password you chose, and it looks like the command is broken when it is not.
(See [the note on `.env` values above](#production-single-node).)

**Step 3 — create the account:**

```bash
uv run cli.py manage create_superuser
```

This reads the four `SUPERUSER_` lines from `.env` and inserts one user into
the database with that username and password, already set to the **Admin**
role so the full app is available immediately. It prints what it did.

**Step 4 — log in** at your server's address with the username and password
from step 1.

#### When `create_superuser` does nothing

The command is careful: before it creates anything, it checks three things,
and if any one of them is true it stops and creates no account. This is why it
is safe to run again and again, and safe to leave in a deploy script.

**1. The username or the password is empty.** It cannot make an account
without both, so it stops immediately and prints
`SUPERUSER_USERNAME or SUPERUSER_PASSWORD not set; skipping superuser creation.`
An empty `SUPERUSER_EMAIL` is fine — email is not part of this check.

**2. Someone already has that username.** It will not quietly overwrite a real
person's account, so it leaves it untouched and tells you the user already
exists. `--force` (below) is the one way to override this.

**3. An administrator already exists**, under any username. The job this
command exists to do is already done, so it stops rather than adding a second
administrator you did not ask for.

In all three cases the command changes nothing at all, prints one line telling
you which of the three it hit, and finishes normally — it is not an error, so a
deploy script will carry on.

If you forget the password later, change `SUPERUSER_PASSWORD` in `.env`,
re-run `stack-deploy` (see step 2 above — without it the old password is still
what the app has), then:

```bash
uv run cli.py manage create_superuser --force
```

`--force` is the one case where it *does* overwrite: it resets the existing
account's password to the new value.

#### Alternative: type the password instead of storing it

Some operators would rather not have a real password sitting in `.env` at all.
Django's built-in command asks for the details on the terminal instead — you
type them in, one question at a time (username, employee ID, password), and
nothing is written to any file:

```bash
uv run cli.py manage createsuperuser
```

Note the name: `createsuperuser` is Django's built-in interactive command,
while `create_superuser` (with the underscore) is this project's command that
reads `.env` instead of asking. If you use the interactive one, there is one
extra step afterwards: the account it makes has its in-app **Role** set to
Staff, so the sidebar looks nearly empty. Open `/admin/`, find your own user,
and change Role to **Admin**.

Once you can sign in, create everyone else's account inside the app at
`/admin/` — see [Managing user accounts](../admin/user-accounts.md).

**Operating the stack:**

```bash
uv run cli.py logs web          # tail a service's logs (default: web)
uv run cli.py shell             # Django shell in the running web container
uv run cli.py manage <args>     # any manage.py command, e.g. createsuperuser
uv run cli.py db-backup         # pg_dump to backups/hemdesk-<date>.dump
uv run cli.py db-restore FILE --yes   # DESTRUCTIVE — replaces current data
uv run cli.py stack-rm          # remove the stack
```

The production database port is deliberately not published — the dev
override (`docker-compose.dev.yml`) adds `5432:5432` for local tooling; the
base file, which production deploys unmodified, does not expose it.

TLS termination is the operator's responsibility; nginx serves plain HTTP on `:8080`.
