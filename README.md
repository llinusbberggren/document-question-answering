# Document Question Answering

A small command-line document question-answering prototype for the AI Engineer case. It answers questions using the supplied PDFs and Excel workbooks, cites the source pages or sheets, and uses Python for deterministic calculations.

## Solution Overview

A lightweight, command-line RAG (Retrieval-Augmented Generation) agent to handle the math-heavy questions in this case study using the provided PDF and Excel files. Instead of relying on a complex database, the app locally processes these files into a simple JSONL index and uses a custom text-based search to quickly find the right context. Because LLMs can struggle with math, I split the workload: the LLM handles reading and extracting information, while standard Python functions crunch the actual numbers to guarantee accuracy.

## Key Technical Decisions

#### Lightweight Local Retrieval: 
Instead of over-engineering with a heavy vector database, I built a custom, local text search that scores word overlap and groups related files. This keeps the app incredibly fast and requires zero extra setup.

#### Contextual Page Adjacency: 
To prevent information from getting cut off at page breaks, the search logic automatically pulls in the pages immediately before and after any highly relevant PDF page so the LLM gets the full, unbroken context.

#### Delegating Arithmetic to Python: 
Because LLMs are notoriously bad at multi-step math, I restricted the AI strictly to data extraction. Deterministic Python functions then take over to crunch the actual numbers, guaranteeing accurate math.

## Possible Improvements

#### Upgrading to Semantic Search: 
The current search relies on basic token overlap and hardcoded synonyms. For a production system, replacing this with a lightweight vector-based semantic search would make retrieval much more resilient to natural variations in how users phrase their questions.

#### Smarter Document Chunking: 
The preprocessing script currently extracts entire PDF pages or full Excel sheets as single chunks. Moving to a chunking strategy that respects document structure—like keeping table headers tied to specific rows—would feed the LLM tighter, more relevant context, which lowers token costs and improves accuracy.

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

This creates `working/documents.jsonl`. The `working/` folder is generated locally and ignored by Git. 
Run preprocessing again whenever documents in `Data/` change.

**3.** Ask the assistant a question:

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



