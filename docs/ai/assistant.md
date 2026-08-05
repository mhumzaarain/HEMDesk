# Asking the assistant

**Who:** Engineers & Admins

The assistant is a repair-troubleshooting chat built into equipment detail pages and work order pages. It's not visible to other roles.

## Opening the assistant

On an equipment detail page or an open work order, click **Assistant** to expand the panel. Type your question — for example "no oxygen error — what should I check?" — and click **Ask**.

Chat history is per device and shared: any engineer opening that device's panel sees the same conversation and can continue it.

## What it reads before answering

Each answer is grounded in:

- The device's card — manufacturer, model, and other equipment details.
- If you're asking from a work order, that work order's complaints and remarks.
- The top matching excerpts from the device's [service manual](manuals.md), cited with page numbers.
- Up to 5 past completed repairs on the same model, with the most useful fixes surfaced first.

## Scoping with fault type

The dropdown next to the question box starts on **All fault types**. Pick one of the eight categories (Electrical, Battery / Power, Display / Monitor, Mechanical, Calibration, Software, Accessory / Probe, Other) to narrow the past-repair context to that kind of fault — for example, choose **Calibration** if you only want past calibration fixes considered, not every repair ever logged against the model.

!!! warning "Advisory only"
    The assistant's answers are a starting point, not a substitute for the manual — always verify against it before acting.

    If no manual is on file for the device's model, the model can still describe manual page citations that don't exist. Treat any page reference as unverified unless a manual is actually uploaded for that manufacturer/model.

    On CPU-only deployments, answers can take 1–2 minutes to generate — this is expected, not a hang.
