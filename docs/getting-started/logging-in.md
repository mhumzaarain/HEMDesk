# Logging in & roles

**Who:** Everyone

You do this the first time you use HEMDesk, or any time you need a refresher on what your role can see.

## Getting an account

There is no self-registration. An admin creates your account for you, and it comes with two things that matter throughout the app:

- An **employee ID** (for example `EMP-101`), shown next to your name once you're signed in.
- A **role**: Staff, Biomedical Engineer, or Admin. Your role decides which sidebar links you see.

If you don't have credentials yet, ask an admin to create your account. (Admins: see [Managing user accounts](../admin/user-accounts.md).)

## Logging in

1. Open HEMDesk in your browser. If you're not signed in, you land on the login page.
2. Enter your username and password.
3. Submit the form.

## What happens next

You land on the home screen, greeted by name and your employee ID, with a set of cards for the things you do most often.

!!! note
    Demo installs only — these accounts exist purely for trying out the app and are not present in a real deployment. They appear only after someone runs `uv run cli.py manage seed_demo`; a freshly started app has no accounts at all.

    | Username | Role | Employee ID |
    | --- | --- | --- |
    | `admin` | Admin | `EMP-900` |
    | `engineer1`, `engineer2`, `engineer3` | Biomedical Engineer | `EMP-101`–`EMP-103` |
    | `staff1`–`staff10` | Staff | `EMP-001`–`EMP-009`, `EMP-0010` |

    All demo accounts share one password: the `DEMO_PASSWORD` line in the installation's `.env` file.

## What each role sees

| Sidebar link | Staff | Engineers & Admins | Admin |
| --- | --- | --- | --- |
| Equipment | ✓ | ✓ | ✓ |
| New Complaint | ✓ | ✓ | ✓ |
| My Complaints | ✓ | ✓ | ✓ |
| Accessories | | ✓ | ✓ |
| Queue | | ✓ | ✓ |
| Dashboard | | ✓ | ✓ |
| Reports | | ✓ | ✓ |
| Manuals | | ✓ | ✓ |
| Admin | | | ✓ |

Engineers and Admins have identical permissions everywhere in the app except the Admin link itself, which only Admin accounts get.

The Manuals link is covered in [AI Assistant](../ai/manuals.md).

## Changing your password

1. Open the sidebar footer, under your name.
2. Select **Change password**.
3. Enter your current password and a new one, then submit.

## Other footer options

The same sidebar footer also has the dark/light mode toggle and **Log out**.
