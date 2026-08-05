# Service manuals

**Who:** Engineers & Admins

A service manual sitting in a drawer helps whoever remembers it exists.
Upload it here and it becomes something better: a searchable knowledge
source the [AI assistant](assistant.md) reads for you — when an engineer
asks about a fault, the assistant pulls the relevant sections out of
hundreds of pages and cites them with page numbers. Upload a manual once
and every engineer, on every shift, effectively has it open to the right
page.

There's one manual per manufacturer + model. It covers every unit registered under that model, and uploading a new file for the same manufacturer/model replaces the old one — including its indexed text.

## Uploading a manual

1. Go to **Manuals**.
2. Fill in **Manufacturer**, **Model number**, and a **Manual title**.
3. Choose a `.pdf` file.
4. Click **Upload manual**.

The manual appears in the table with a status badge:

- **Processing** — the file was received and is being indexed.
- **Ready** — indexing finished; the assistant can search and cite it.
- **Failed** — indexing could not complete. Check the status note next to the badge for why.

!!! note
    Only text-based PDFs can be indexed. Scanned or image-only manuals fail with no OCR fallback — if a manual comes from a scanner, run it through OCR software first and re-upload the searchable PDF.

### "embeddings unavailable — keyword search only"

This note means the manual indexed successfully, but the embedding backend wasn't reachable at the time — so it fell back to plain keyword search. The manual is still searchable and the assistant can still use it; it just won't catch synonyms (e.g. a search for "battery" won't also match "power cell").

Once the embedding backend is back up, an admin can fix already-uploaded manuals by running:

```
manage.py reembed_manuals
```

This re-indexes every manual currently in that state so future searches get synonym matching too.

## Finding a manual from equipment

Each equipment detail page links to the manual matching its manufacturer and model, if one has been uploaded — no need to hunt through the Manuals list.
