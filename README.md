# Document Question Answering

A small command-line document question-answering prototype for the AI Engineer case. It answers questions using the supplied PDFs and Excel workbooks, cites the source pages or sheets, and uses Python for deterministic calculations.

## Requirements

- Python 3.9 or newer
- Azure OpenAI access for the case endpoint and deployment

## Setup

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

Configure Azure locally in the same terminal used to run the agent


## Preprocess documents

The source documents are expected under `Data/`. Generate the local searchable index with:

```bash
python3 preprocessing.py
```

This creates `working/documents.jsonl`. The generated directory is ignored because it can be recreated at any time. PDFs are indexed page by page, and Excel workbooks are indexed by worksheet with row and cell metadata.

## Ask a question

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
Azure extracts values and explains the answer
    -> calculations.py
verified deterministic results
```

- `preprocessing.py` extracts PDF and Excel content while preserving source locations.
- `retrieval.py` performs local lexical retrieval and includes related records for multi-document case questions.
- `calculations.py` handles recipe scaling, price tiers, freight, travel fares, and budget arithmetic.
- `agent.py` orchestrates retrieval, Azure Responses API calls, Python calculations, and cited output.
