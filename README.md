# Document Question Answering

A small command-line document question-answering prototype for the AI Engineer case. It answers questions using the supplied PDFs and Excel workbooks, cites the source pages or sheets, and uses Python for deterministic calculations.

## Project layout

The case documents must be available locally in a folder named `Data/`:

```text
document-qa/
├── Data/                  # required local input folder; not committed to Git
│   ├── 01 - ...xlsx
│   ├── 02 - ...xlsx
│   ├── 03 - ...pdf
│   └── ...
├── agent.py
├── calculations.py
├── preprocessing.py
├── retrieval.py
├── requirements.txt
└── docs/design-decisions.md
```

The evaluator must place the supplied candidate documents in `Data/` before running the application. The documents are intentionally not part of this Git repository. The preprocessing script expects the original filenames and numbering from the case packet.

## Requirements

- Python 3.9 or newer
- Access to the Azure OpenAI endpoint and deployment supplied for the case

## Setup

Install the dependencies:

```bash
python3 -m pip install -r requirements.txt
```

Configure Azure locally in the same terminal used to run the agent:


The supplied endpoint is an OpenAI-compatible `/openai/v1/responses` endpoint, so no separate API-version query parameter is needed.

## Run

**1.** Confirm that the `Data/` directory contains the case documents.

**2.** Create the local searchable index:

```bash
python3 preprocessing.py
```

This creates `working/documents.jsonl`. The `working/` folder is generated locally and ignored by Git. Run preprocessing again whenever documents in `Data/` change.

**3.** Re-run the preprocessing step whenever files in `Data/` change.
**4.** Ask the assistant a question:

```bash
python3 agent.py "How much sugar does the bakery use per week?"
```

## How it works

```text
Data/ documents
    -> preprocessing.py
working/documents.jsonl
    -> retrieval.py
relevant source records
    -> agent.py
Azure interpretation and explanation
    -> calculations.py
verified calculation result
```

- `preprocessing.py` extracts PDF and Excel content while preserving source locations.
- `retrieval.py` performs local lexical retrieval and includes related records for multi-document case questions.
- `calculations.py` handles recipe scaling, price tiers, freight, travel fares, and budget arithmetic.
- `agent.py` orchestrates retrieval, Azure Responses API calls, Python calculations, and cited output.

For numeric questions, Azure identifies values from the retrieved evidence and Python performs the arithmetic. For ambiguous cases, the agent reports supported alternatives rather than silently choosing one.


```bash
git status --short
git diff --cached --name-only
```
