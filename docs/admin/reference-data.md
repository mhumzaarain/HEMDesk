# Departments & reference data

**Who:** Admins

Use this when you are setting up HEMDesk for the first time, when a new ward or
department opens, or when you are wondering where one of the drop-down lists in
the app comes from and how to change it.

## How much setup does HEMDesk need?

Less than you might expect. **Departments are the only list you have to create
yourself.** Everything else is either built into the app or gets created during
normal day-to-day work.

| What | Who creates it | Where |
| --- | --- | --- |
| **Departments** | Admin | Admin site — this page |
| **User accounts** | Admin | Admin site — see [Managing user accounts](user-accounts.md) |
| **Equipment** | Engineers & Admins | In the app: [Register equipment](../equipment/register.md) |
| **Accessory types** | Engineers & Admins | In the app: [Accessories & stock](../equipment/accessories.md) |
| **Fault categories** | Nobody — built in | Fixed list, see below |
| **Roles** | Nobody — built in | Fixed list: Staff, Biomedical Engineer, Admin |

So a realistic first-day setup is: create your departments, then create your
users. That's it — engineers can start registering equipment straight away.

## Creating a department

A department is a ward, unit, or area of the hospital that equipment belongs
to — ICU, Radiology, Emergency, and so on. Every device must belong to one, so
create these before registering equipment.

1. Open the admin site from the **Admin** link at the bottom of the sidebar
   (it takes you to `/admin/`). No link there? See
   [Two settings that look alike](#two-settings-that-look-alike-but-are-not) —
   you need Staff status, not just the Admin role.
2. Under **Equipment**, next to **Departments**, click **Add**.
3. Fill in:
    - **Name** — what people call it, e.g. `ICU`. This is what appears in
      drop-down lists and on reports, so use the name staff will recognise. It
      must be unique.
    - **Location** — optional, and free text. Somewhere to note where the
      department physically is, e.g. `Block A, Floor 2`.
4. Click **Save**.

The department is available immediately, with no restart or re-deploy needed.

!!! note
    Importing equipment from a spreadsheet can create departments for you.
    On the import screen there is a **Create missing departments** tick-box —
    with it ticked, any department named in your file that doesn't exist yet is
    created automatically. See [Import from Excel or CSV](../equipment/import.md).

### Renaming or removing a department

Open **Equipment → Departments**, click the one you want, edit it, and save.
Renaming is safe — equipment stays attached, because the link is not based on
the name.

Deleting is different. If any equipment or user still belongs to the
department, HEMDesk **refuses to delete it** and shows a protected-object
error. This is deliberate: it stops a device from silently losing its location.
To retire a department, first move its equipment elsewhere, then delete it.

## Fault categories are a fixed list

**You cannot create, rename, or remove fault categories.** They are not stored
in the database and there is nothing for them in the admin site. HEMDesk ships
with these eight, and every installation has exactly the same ones:

Electrical · Battery / Power · Display / Monitor · Mechanical · Calibration ·
Software · Accessory / Probe · Other

Nobody picks a category when *lodging* a complaint. It is chosen by the
**engineer**, at the end of the job, on the form that completes a work order —
see [Work orders](../complaints/work-orders.md). The category is what drives the
fault breakdown on the dashboard and in the monthly report, and it helps the AI
assistant find similar past repairs.

If a fault doesn't fit any of the eight, engineers should use **Other** and
describe it in the remarks.

!!! note
    Genuinely need a ninth category? That is a change to the software, not a
    setting — it needs a developer to edit the code and apply a database
    migration, then a re-deploy. It is not something an admin can do from the
    app, so plan it with whoever maintains your installation.

## Groups and permissions — you can ignore these

The admin site shows a **Groups** section, and each user's page has **Groups**
and **User permissions** boxes. These come as standard with Django, the
framework HEMDesk is built on, and they cannot be hidden.

**HEMDesk itself ignores them completely.** Everything you see in the app —
the sidebar links, the queue, the dashboard, who may close a work order — is
decided by one field, the person's **Role**. Groups and permissions are never
consulted anywhere in HEMDesk.

They are not entirely inert, though, and it is worth knowing the difference:

- **Inside the app** (equipment, complaints, work orders, dashboard, reports):
  groups and permissions do **nothing**. Only **Role** matters.
- **Inside the admin site only**: they work the way Django intends, and can
  narrow which sections of `/admin/` a non-superuser may open.

For a hospital running HEMDesk normally, you never need them. Leave both boxes
empty and set the person's Role instead.

!!! warning
    Never try to give someone access to part of the app by putting them in a
    group. It will look like you did something and will have no effect. If a
    person sees too much or too little of HEMDesk, change their **Role** — see
    [Managing user accounts](user-accounts.md).

### Two settings that look alike but are not

These trip people up, so it is worth stating plainly:

- **Role** decides what the person sees **inside HEMDesk**.
- **Staff status** is a single tick-box that decides whether they can open the
  **admin site** at all. It is also what makes the **Admin** link appear at the
  bottom of their sidebar.

They are independent. Someone whose Role is Admin but who does *not* have Staff
status gets the full app but no Admin link and no way into `/admin/`. Someone
with Staff status but the Staff role can open `/admin/` while still being
blocked from the dashboard and equipment screens. An admin who should manage
accounts and departments needs **both**.

## What you can and can't change in the admin site

The admin site deliberately locks down most records. Complaints, work orders,
and PPM visits are the hospital's maintenance history, so they are shown for
reference but cannot be added or edited by hand — they are only created by
people using the app properly, which keeps the history trustworthy.

| Section | You can | You cannot |
| --- | --- | --- |
| Departments | Add, edit, delete | — |
| Users | Add, edit, delete | — |
| Equipment | Add, edit | Delete (condemn it in the app instead) |
| Accessory types | Add, edit | Delete |
| Service manuals | Add, edit, delete | — |
| Risk scoring settings | Edit the single settings record | Add a second one, delete it |
| Complaints, work orders, PPM schedules | View only | Add, edit, or delete |
| PPM records, remarks, status events, accessory events, audit log | View only | Change anything |

!!! warning
    Even where the admin site lets you edit something, prefer the app's own
    screens. The app enforces the workflow rules — status changes, history
    entries, stock counts — and the admin site does not. A device added
    through the admin site gets no entry in its own status history and no line
    in the audit log, so it will look different from every other device in the
    registry. Register equipment at **Equipment → Register**, or by
    [importing a spreadsheet](../equipment/import.md), instead.

!!! warning "Do not upload service manuals through the admin site"
    The admin site lets you add a **Service manual**, but it only files the
    record — it never starts the reading-and-indexing step. The manual sits at
    "processing" forever and the AI assistant never finds anything in it, with
    no error to tell you. Always upload manuals from the app's own
    [Manuals page](../ai/manuals.md), which does start that step.

In fact only three things can ever be deleted here: departments, users, and
service manuals. Everything that forms part of the maintenance history —
equipment, complaints, work orders, remarks, PPM records, the audit log — is
permanent by design, and the app refuses to remove it however you try. If a
device should leave daily use, condemn it in the app rather than looking for a
delete button.

Even those three can refuse. A department or user that still has equipment,
complaints, or work orders attached cannot be deleted, so that nothing is left
pointing at a record that no longer exists.

**What happens next:** With your departments created, engineers can register
equipment against them, staff can lodge complaints, and the department filters
on the dashboard and reports start showing real data.
