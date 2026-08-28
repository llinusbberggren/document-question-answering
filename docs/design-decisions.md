# Design Decisions

This document records the important choices in the case solution. The scope is intentionally limited to a useful, explainable prototype that can be built and tested within approximately three hours.

## Preserve the original source files

**Decision:** Keep the supplied documents in `Data/` with their original filenames.

**Motivation:** Filenames are useful citation identifiers, and changing the source files would make it harder to compare extracted content with the case packet.

**Trade-off:** The source directory is less tidy than a renamed collection, but traceability is more valuable here.

## Keep control documents out of the answer index

**Decision:** `preprocessing.py` skips the case instructions and question document, identified by the `00 -` and `11 -` filename prefixes.

**Motivation:** These documents describe the assignment rather than providing evidence for answers. Excluding them reduces the chance that the assistant treats a question or instruction as factual source material.

**Trade-off:** This relies on the supplied numbering convention. It is simple and appropriate for this fixed case, but a larger system would use explicit configuration or document classification.

## Use page-level records for PDFs

**Decision:** Extract one JSONL record per PDF page with a page number.

**Motivation:** The PDFs are short, and page-level boundaries provide simple, reliable citations without requiring a complex chunking strategy.

**Trade-off:** A fact split across pages may need multiple retrieved records. That is preferable to losing page provenance; later retrieval can include neighboring pages.

## Preserve Excel sheets and row metadata

**Decision:** Extract one record per non-empty worksheet, retaining worksheet name, first and last populated row, row numbers, and cell coordinates.

**Motivation:** The spreadsheets contain tables where a value only makes sense alongside its row and column context. Labels such as `B: 12 kr` are more useful to retrieval than a flattened list of values.

**Trade-off:** A large worksheet would be a large retrieval unit. The supplied workbooks are small; splitting large sheets can be added if context limits become a problem.

## Use lightweight local parsers

**Decision:** Use `pypdf` for PDFs and `openpyxl` for `.xlsx` files.

**Motivation:** Both formats are directly supported, the libraries are small, and the extraction behavior is easy to inspect during an interview.

**Alternatives considered:** OCR, pandas, and document-processing platforms. OCR is unnecessary unless text extraction fails; pandas can discard workbook presentation details; external platforms add setup and credentials.

## Normalize to JSONL

**Decision:** Write records to `working/documents.jsonl` using a common schema: source filename, source type, location, and extracted text.

**Motivation:** JSONL is readable, rerunnable, diffable, and sufficient for twelve source documents. The common schema lets retrieval treat PDFs and Excel records uniformly.

**Trade-off:** JSONL is not a scalable search system. A database or vector index would be appropriate for a larger corpus, but would add complexity without helping this case.

## Make preprocessing deterministic and rerunnable

**Decision:** The script scans a directory, sorts filenames, writes a fresh output file, and reports extraction warnings to stderr.

**Motivation:** Reproducibility makes extraction bugs visible and allows the generated index to be regenerated after changing the source files.

**Trade-off:** The output is overwritten on each run. That is intentional for a derived artifact; source documents remain untouched.

## Defer OCR until evidence requires it

**Decision:** Log pages with empty extracted text rather than adding OCR immediately.

**Motivation:** OCR adds dependencies and can introduce transcription errors. The first check should establish whether the supplied PDFs already contain an accessible text layer.

**Trade-off:** Image-only PDFs would need a follow-up OCR implementation. The warning makes that limitation explicit instead of silently producing incomplete data.

## Use lexical retrieval first

**Decision:** `retrieval.py` normalizes wording, ranks records using token overlap, and applies a small boost for matches in source filenames.

**Motivation:** The corpus is only fifteen normalized records. Lexical retrieval is fast, deterministic, and easy to inspect when a result is wrong.

**Alternatives considered:** Embeddings/vector search and a hosted search service. Those approaches handle semantic wording better, but add dependencies, setup, cost, and less transparent failure modes.

The source-group rules are capped by `--limit`, so they do not create an unbounded prompt.

## Keep retrieval independent from the LLM

**Decision:** `retrieval.py` only loads and ranks local records; `agent.py` will own prompting and Azure calls.

**Motivation:** This separates evidence selection from answer generation. Retrieval can be tested without credentials or network access, and an interview discussion can distinguish a retrieval failure from a model failure.

**Trade-off:** There is a little more code than putting everything in `agent.py`, but the boundary improves debugging and keeps responsibilities clear.

## Use a small top-k context

**Decision:** Return a configurable number of highest-scoring records, defaulting to five, and omit zero-score records.

**Motivation:** Supplying only relevant evidence controls prompt size and reduces distractions while retaining support for questions that require multiple documents.

**Trade-off:** A strict top-k cutoff can omit a useful low-scoring record. The limit remains configurable, and evaluation can reveal whether it needs to be increased.

## Include neighboring PDF pages
**Motivation:** A fact may be split across pages, as with the recipe whose quantities are on page 1 and prices/method on page 2. Including the neighbor prevents a safe but incomplete answer caused by missing context.

**Trade-off:** This can add a small amount of unrelated text and may return more than the nominal top-k count. The supplied documents are short, so recall is more valuable than strict context minimization.

## Retrieve the complete transport chain for itinerary questions

**Decision:** For questions containing clear itinerary terms such as `train`, `boat`, `return`, or `journey`, include the ferry timetable, mainland railway timetable, island railway timetable, and meeting invitation.

**Motivation:** A route answer requires several linked schedules. Pure top-k lexical ranking can select the Stockholm timetable while dropping the ferry or Visby-Roma timetable, producing an incorrectly cautious answer.

**Trade-off:** It is a small domain-specific rule and may omit non-transport travel information for a broad question. With this fixed, tiny corpus, focused route context and better recall outweigh that cost. A larger system would use metadata filters or a classifier.

## Keep arithmetic in a small calculation module

**Decision:** Put repeatable arithmetic in `calculations.py`, using pure functions that receive values extracted from the documents.

**Motivation:** Arithmetic such as recipe scaling, price rebates, freight tiers, and budget limits is easier to verify in Python than in a language-model response. Pure functions also make assumptions visible and testable.

**Alternatives considered:** Ask the LLM to perform all calculations, or build a general-purpose expression parser. The first risks arithmetic errors; the second is unnecessary complexity for this fixed case.
For weekly production, the model extracts the individual customer order quantities and Python sums them. This handles blank or absent spreadsheet total rows without asking the model to perform arithmetic.

The calculation boundary also normalizes numeric strings such as `1,000 buns` and `2.2 kg`. The extraction prompt asks for JSON numbers, but accepting harmless unit labels makes the system resilient to model formatting without moving arithmetic into the LLM.

For ambiguous travel-cost questions, Python validates the published train and ferry fares directly from the retrieved context and computes both train-class alternatives. This prevents an LLM from substituting malformed values such as rounded fares or train-only totals.

For freight questions, Python derives the current 180 kg weekly sugar need, treats a full month as four weeks, and applies the tariff's per-shipment minimums, weight tiers, and fixed handling fee. This keeps the comparison between four weekly shipments and one 720 kg shipment reproducible.

For sugar-budget questions without a specified contract, Python reports spot, six-month, and twelve-month alternatives. This makes the missing contract choice explicit while still answering with all document-supported outcomes.

The budget amount is extracted from the user's question rather than hard-coded, so the same path can answer other budget scenarios. Calculation inputs are validated at the boundary, including rejecting zero prices and invalid price tiers, to turn bad model output into a clear error instead of an arithmetic exception.

For Roma sightseeing questions, retrieval includes the traveller's guidebook, meeting invitation, and local railway timetable. The guidebook is the authoritative source for attractions; the timetable is included only to support timing and station access, avoiding a false conclusion from the branch-line text mentioning Romakloster.

The answering layer distinguishes sightseeing before and after the Roma-to-Visby return. For post-return questions, it uses the 16:00 train and checks closing times after the station-to-harbor walk, rather than incorrectly reusing the 13:00 train from the earlier Roma free-period question.

Ingredient scaling uses a generic `ingredient_kg_for_buns` function rather than a cinnamon-only formula. This supports similar questions about recipe ingredients while keeping the implementation small.

## Use Azure for interpretation, Python for arithmetic

**Decision:** `agent.py` makes one Azure call to extract a structured calculation request, runs that request through `calculations.py`, and makes a second Azure call only to explain the verified result.

**Motivation:** The model is good at identifying relevant values and interpreting the question, but Python is deterministic for arithmetic. The second call can present the result without allowing the model to replace it.

**Alternatives considered:** Let the model calculate directly, or implement Azure tool-calling. Direct calculation is simpler but less reliable; tool-calling is elegant but adds API and schema complexity for a three-hour prototype.

**Trade-off:** Two model calls increase latency and cost, and malformed extraction must be handled. The explicit JSON schema and Python validation make the calculation path inspectable.

## Use environment variables for Azure configuration

**Decision:** Read endpoint, API key, and deployment name from environment variables. Keep the supplied API version available as case metadata, but do not append it to the OpenAI-compatible `/openai/v1` endpoint.

**Motivation:** Credentials must not be committed, and environment variables work both locally and in a later deployment.

**Trade-off:** A user must configure the endpoint, key, and deployment before running the agent. The case supplies an API version, but sending it as an `api-version` query parameter produces an unsupported-version error for this v1 endpoint. Failing clearly at startup is safer than silently using incomplete configuration.

For local testing, these values are supplied as shell environment variables. The API key is intentionally never stored in project files or documentation. The supplied endpoint is an OpenAI-compatible `/openai/v1/responses` endpoint, so `agent.py` uses the `OpenAI` client and does not send the separate API-version value.

## Enumerate ambiguous travel prices

**Decision:** If the ferry cabin is specified but the train class is not, calculate and report one total for each available train class.

**Motivation:** The documents provide both train fares, so declaring the answer unknowable would discard useful evidence. Reporting both values makes the ambiguity explicit and avoids silently choosing a class.

**Trade-off:** The answer is slightly longer and does not select one personal total. A later user clarification can select the applicable option.
