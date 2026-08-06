# Managing user accounts

**Who:** Admins

There is no self-registration in HEMDesk — every account is created by an admin. You do this when someone new joins, when a person's role changes, or when they've forgotten their password.

User accounts are managed in the Django admin site. Open it from the **Admin** link at the bottom of the sidebar (it takes you to `/admin/`).

## Registering a new user

1. In the admin site, under **Accounts**, next to **Users**, click **Add**.
2. Enter a **Username** and the initial **Password** (twice).
3. In the **CMMS** box, fill in:
    - **Employee ID** — unique per person, e.g. `EMP-101`. It's shown next to the person's name throughout the app.
    - **Role** — Staff, Biomedical Engineer, or Admin. This decides which parts of the app they see — see [what each role sees](../getting-started/logging-in.md#what-each-role-sees).
4. Click **Save**. You land on the user's full edit page, where you can optionally add their first name, last name, and email address.
5. Give the person their username and initial password, and ask them to change it after their first login (**Change password** in the sidebar footer).

!!! note
    The **Role** field controls what the person sees *inside the app*. Access to the admin site itself is separate: it comes from Django's **Staff status** checkbox (under Permissions on the user's edit page). Tick it only for people who should manage users and other records — a superuser has it automatically.

## Changing a role or details later

Open **Accounts → Users**, click the person, edit the **Role** (or name, email, employee ID), and save. The change takes effect on their next page load.

## Resetting a forgotten password

1. Open **Accounts → Users** and click the person.
2. In the **Password** field, follow the "**this form**" link.
3. Enter the new password twice and save, then hand it to the person and ask them to change it.

People who simply want a new password can do it themselves via **Change password** in the sidebar footer — no admin needed.

## The first admin account

On a fresh install there are no accounts yet — nobody can log in, so the very first admin can't be created inside the app. Whoever deploys HEMDesk (typically the IT person or biomedical department lead setting up the server) creates it from the command line.

You pick the username and password yourself — there is no built-in account waiting for you.

Open the `.env` file on the server. It already has these four lines:

```bash
SUPERUSER_USERNAME=admin
SUPERUSER_PASSWORD=changeme-in-production
SUPERUSER_EMAIL=admin@hospital.example
SUPERUSER_EMPLOYEE_ID=ADMIN-0001
```

Replace `changeme-in-production` with a password of your own — the placeholder is public, so leaving it would let anyone sign in as an administrator. Then run:

```bash
uv run cli.py manage create_superuser
```

That reads those lines and creates the account. The username and password you just wrote are now your login, and the account already has the **Admin** role, so the whole app is available the moment you sign in.

Running it again later does nothing, which makes it safe to leave in a deploy script. Before creating anything it checks three things, and stops without changing a thing if any of them is true: the username or password line is empty, someone already has that username, or an administrator already exists. It prints one line saying which of the three it hit. So if it reports "skipping" and you got no account, one of those three is the reason — the full explanation is in [Deployment](../developer/deployment.md#when-create_superuser-does-nothing).

If you forget the password, change it in `.env` and re-run the command with `--force`, which is the one thing that overrides the "username already exists" check and resets that account's password.

!!! warning "Editing `.env` is not enough on its own"
    On a server deployment, the running app never re-reads `.env`. It uses a copy of the values that was handed to it the last time the stack was deployed. So after changing `SUPERUSER_PASSWORD` — or anything else in `.env` — run `uv run cli.py stack-deploy` first, and only then `create_superuser`. Skip that and the command uses the *old* password, so the one you just typed won't let you in.

**Would you rather not keep a real password in a file?** Django's own command asks you for the details on the terminal instead — it prints a question, you type the answer, and nothing is saved to `.env`:

```bash
uv run cli.py manage createsuperuser
```

The names are confusingly similar: `createsuperuser` (no underscore) is Django's built-in that asks you questions; `create_superuser` (with the underscore) is this project's command that reads `.env`. Either one gets you an account. With the interactive one there's a single follow-up step: it leaves the new account's **Role** set to Staff, so the sidebar looks almost empty until you open the admin site, find your own user, and change Role to **Admin**.

!!! note
    Running Django directly on your machine rather than in a container? Use `uv run python manage.py <command>` in place of `uv run cli.py manage <command>` — they are otherwise identical.

On a development machine you don't need any of this: `uv run cli.py manage seed_demo` creates a ready-made `admin` account along with demo data. Never run it on a real deployment — its password is public, and it fills the database with invented equipment and staff.

Every other account — staff, engineers, and further admins alike — is then created inside the app as described above.

## Can there be more than one admin?

Yes. Admin is just a role, not a single reserved account. Any existing admin can create more admins: register the user as usual and set their **Role** to Admin, and tick **Staff status** if they should also manage accounts in the admin site. Having at least two admins is a good idea — if one is unavailable or locked out, the other can still reset passwords and manage accounts.

## What else lives in the admin site

Beyond users, the admin site is where you create **departments**, and it gives raw access to equipment, accessories, complaints, work orders, and PPM records. It also shows a **Groups** section that HEMDesk does not use at all — a person's access comes from their **Role**, never from a group.

[Departments & reference data](reference-data.md) covers all of that: creating departments, why fault categories can't be added, why groups do nothing, and exactly which records you can and can't edit.

**What happens next:** The new user logs in with the credentials you gave them, lands on the home screen for their role, and changes their password from the sidebar footer.
