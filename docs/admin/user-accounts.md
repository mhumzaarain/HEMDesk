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

On a fresh install there are no accounts yet — nobody can log in, so the very first admin can't be created inside the app. Whoever deploys HEMDesk (typically the IT person or biomedical department lead setting up the server) creates it from the command line, either way:

- **Interactive:** `uv run python manage.py createsuperuser` — it prompts for username, employee ID, and password. The account can open `/admin/`, but its in-app **Role** defaults to Staff — open your own user in the admin and set Role to **Admin** to get the full sidebar.
- **Automated (deploys/containers):** set `SUPERUSER_USERNAME`, `SUPERUSER_PASSWORD` (and optionally `SUPERUSER_EMAIL`, `SUPERUSER_EMPLOYEE_ID`) in `.env` and run `python manage.py create_superuser`. It's idempotent and sets the role to Admin for you.

Every other account — staff, engineers, and further admins alike — is then created inside the app as described above.

## Can there be more than one admin?

Yes. Admin is just a role, not a single reserved account. Any existing admin can create more admins: register the user as usual and set their **Role** to Admin, and tick **Staff status** if they should also manage accounts in the admin site. Having at least two admins is a good idea — if one is unavailable or locked out, the other can still reset passwords and manage accounts.

## What else lives in the admin site

Beyond users, the admin site also manages **departments** (create one before assigning equipment to it) and gives raw access to equipment, accessories, complaints, work orders, and PPM records. For day-to-day work, prefer the app's own pages — they enforce the workflow rules; the admin site does not.

**What happens next:** The new user logs in with the credentials you gave them, lands on the home screen for their role, and changes their password from the sidebar footer.
