# AI Portfolio Project — Claude Code Handoff

## 1. Why We Are Building This

I am transitioning toward practical AI/software engineering roles in Australia.

My current formal qualification is:

- Certificate IV in Game Design & Development

My existing hands-on experience includes:

- Godot / GDScript
- Software and game development
- Claude Code
- Codex
- Ollama / local LLMs
- MCP servers
- Multi-agent AI workflows
- GitHub
- AI-assisted software development

I have been researching Australian AI jobs that do not necessarily require an AI/Computer Science degree but instead value demonstrated experience building software with AI.

Relevant job categories include:

- Junior AI Engineer
- AI Solutions Engineer
- AI Automation Developer
- Applied AI Engineer
- AI Implementation Specialist
- AI Solutions Officer
- GenAI Developer
- AI Consultant

Several jobs I examined specifically mentioned skills such as:

- Python
- REST APIs
- SQL/databases
- LLM APIs
- RAG
- Agents
- MCP
- Claude Code / Codex
- Git/GitHub
- Docker
- Cloud
- AI evaluation
- Structured AI-assisted development

The purpose of this project is therefore NOT simply to learn RAG.

It needs to become a serious portfolio project demonstrating that I can build, test, evaluate, document and explain production-oriented AI systems.

---

# 2. Portfolio Strategy

Originally the portfolio was going to contain four independent projects:

1. Business RAG Assistant
2. AI Business Automation Agent
3. MCP Business Tools Server
4. AI Evaluation & Monitoring System

We decided that a stronger portfolio would connect these into one increasingly sophisticated system.

Long-term portfolio concept:

# Project Intelligence Platform

Conceptual architecture:

```text
                  PROJECT FILES
                       │
             ┌─────────┴─────────┐
             ▼                   ▼
        Documentation          Code
             │                   │
             └─────────┬─────────┘
                       ▼
               RAG KNOWLEDGE BASE
                       │
             ┌─────────┼─────────┐
             ▼         ▼         ▼
           Search     Agent     MCP
             │         │         │
             └─────────┼─────────┘
                       ▼
                  AI Assistant
                       │
       ┌───────────────┼───────────────┐
       ▼               ▼               ▼
   Answer Qs      Analyse project   Automate tasks
       │               │               │
       └───────────────┬───────────────┘
                       ▼
                 EVALUATION
                       │
                 Observability
```

This lets the portfolio demonstrate:

- RAG
- Embeddings
- Vector search
- Hybrid retrieval
- Reranking
- LLM APIs
- Agents
- MCP
- REST APIs
- Databases
- Python
- Docker
- Testing
- Evaluation
- Observability
- AI-assisted software development
- Production-oriented architecture

Do NOT treat these as four unrelated tutorial projects unless there is a compelling architectural reason.

---

# 3. Project 1 Has Been Renamed

Original name:

> Business RAG Assistant

New direction:

# Project Intelligence RAG

Portfolio tagline:

> A production-oriented AI knowledge system that understands technical documentation and source code, answers questions with verifiable citations, detects insufficient evidence, and measures its own retrieval and answer quality.

The existing Business RAG Assistant starter repository should be evolved into this project rather than discarded.

---

# 4. Existing Technical Foundation

The starter repository was designed around:

- Python
- FastAPI
- PostgreSQL
- pgvector
- SQLAlchemy
- Docker
- typed configuration
- automated tests

It already included the beginnings of:

- FastAPI service
- PostgreSQL + pgvector Docker environment
- SQLAlchemy document/chunk models
- vector embedding storage
- health endpoint
- tests
- README
- CLAUDE.md

Inspect the actual repository before making assumptions about what currently exists.

Do NOT unnecessarily rebuild working components.

---

# 5. Important Architecture Rule

Do NOT introduce LangChain or LlamaIndex during the initial implementation unless there is a strong technical reason and it is discussed first.

The purpose is to understand and demonstrate the underlying RAG architecture rather than hiding everything behind a framework.

I need to be capable of explaining this during an interview:

```text
Question
   ↓
Embedding Model
   ↓
Question Vector
   ↓
Retrieval
   ↓
Relevant chunks
   ↓
Prompt + evidence
   ↓
LLM
   ↓
Grounded answer
   ↓
Citations
```

Prefer transparent components and explicit code.

---

# 6. Personalized Use Case

Do NOT build another generic:

> "Upload PDF → Chat with PDF"

portfolio project.

There are already thousands of these.

The system should instead understand SOFTWARE PROJECTS.

It should ingest things such as:

- README.md
- design documents
- game design documents
- technical specifications
- source code
- bug reports
- changelogs
- development plans
- meeting notes
- configuration files

My game-development projects can eventually be used as real demonstration datasets.

For example, a Godot tower-defense project could be indexed.

Example questions:

> How does the tower upgrade system work?

> Where is enemy health calculated?

> What features haven't been implemented?

> What does the design specification say about poison towers?

> Which files would probably need changing to add a new enemy type?

> Are there contradictions between the design documentation and implementation?

This makes the project relevant to my actual background rather than looking like a copied AI tutorial.

---

# 7. Required File Support

Initial priority:

- PDF
- TXT
- Markdown

Then expand toward:

- Python
- GDScript
- JSON
- YAML
- CSV
- DOCX

Later consider:

- Git repository ingestion
- GitHub repository ingestion

Architecture should make adding new parsers/loaders straightforward.

---

# 8. Initial API Direction

Likely endpoints include:

```text
POST   /documents
GET    /documents
GET    /documents/{id}
DELETE /documents/{id}

POST /search
POST /ask
```

Exact API structure can evolve if there is a better design.

---

# 9. Document Pipeline

Initial ingestion pipeline:

```text
Document
    ↓
File validation
    ↓
Text extraction
    ↓
Metadata extraction
    ↓
Chunking
    ↓
Embeddings
    ↓
PostgreSQL / pgvector
```

Chunks should preserve useful provenance.

Examples:

```text
document
filename
file type
section
page
line range
source path
chunk index
```

Not every format supports every metadata field, so represent provenance sensibly.

---

# 10. Citations Are a Core Requirement

Answers must be traceable to their evidence.

Example:

```text
The poison effect can stack up to three times.

Sources:
design/towers.md — Poison System
src/enemies/enemy.gd — lines 82–104
```

Citation support should be designed into the data model rather than bolted on at the end.

---

# 11. "I Don't Know" Behaviour

This is an important differentiator.

The system must NOT always answer.

If retrieval does not provide sufficient evidence, it should respond appropriately, for example:

```text
I couldn't find sufficient evidence in the indexed
project documentation to answer this reliably.
```

We should eventually measure this behaviour.

The goal is to reduce unsupported/hallucinated answers.

---

# 12. Retrieval Evolution

Do not stop permanently at basic vector similarity search.

Version 1 can use semantic vector retrieval.

The intended mature retrieval architecture is:

```text
                   QUESTION
                       │
                       ▼
                Query processing
                       │
             ┌─────────┴─────────┐
             ▼                   ▼
          Lexical              Vector
           search              search
             │                   │
             └─────────┬─────────┘
                       ▼
                  Result fusion
                       │
                       ▼
                    Reranker
                       │
                       ▼
              Best evidence chunks
                       │
                       ▼
               Evidence threshold
                  /           \
           sufficient       insufficient
               │                │
               ▼                ▼
              LLM          "I don't know"
               │
               ▼
        Grounded response
               │
               ▼
             CITATIONS
```

Long-term retrieval should therefore investigate:

- vector similarity search
- lexical/BM25/full-text retrieval
- hybrid search
- result fusion
- reranking
- metadata filtering
- retrieval thresholds

Implement these incrementally rather than all at once.

---

# 13. Evaluation Is Extremely Important

This should NOT become a project where quality is judged by manually asking five questions and deciding that the answers "look good."

We eventually need an evaluation dataset.

Example:

```text
QUESTION:
What is the maximum poison stack?

EXPECTED ANSWER:
3

EXPECTED SOURCE:
design/towers.md
```

Build a set of known questions and expected evidence.

Eventually measure things such as:

- retrieval Recall@K
- retrieval precision
- citation accuracy
- answer faithfulness
- answer correctness
- unsupported answer rate
- refusal/insufficient-evidence accuracy
- latency
- token usage
- estimated query cost

Potential README results might eventually look like:

```text
Retrieval Recall@5        XX%
Citation accuracy         XX%
Answer faithfulness       XX%
Unsupported answer rate   XX%

Median latency            X.X sec
p95 latency               X.X sec
Average query cost        $X.XXXX
```

NEVER invent performance numbers.

Only publish measurements generated by the actual evaluation system.

---

# 14. Observability

Later stages should record enough information to investigate failures.

Potential fields:

- query
- retrieved chunks
- retrieval scores
- reranking scores
- selected context
- model
- token usage
- latency
- cost
- answer
- citations
- evaluation results

Avoid logging sensitive document contents unnecessarily.

---

# 15. Source Code Understanding

A major differentiator should eventually be source-code-aware retrieval.

Naively splitting source code every N characters is not ideal.

Eventually investigate language-aware chunking.

Examples:

For Python:

```text
module
class
function
method
```

For GDScript:

```text
class
function
signal
exported property
```

Preserve:

- file path
- symbol name
- line ranges
- parent class/module where possible

This should allow answers such as:

> Where is enemy damage calculated?

with citations pointing directly to relevant source files and line ranges.

Do NOT overengineer this in the first milestone.

---

# 16. Potential Advanced Feature: Specification vs Implementation

An eventual standout feature could compare design documentation against source code.

Example:

```text
Question:
Does the poison implementation match the design specification?

Result:

Potential discrepancy detected.

Design specification:
Poison should stack up to 3 times.

Implementation evidence:
enemy.gd appears to replace the existing poison state.

Relevant sources:
...
```

This must be evidence-based.

The system should not pretend it can formally prove program behaviour from incomplete context.

Label uncertainty appropriately.

---

# 17. Future Agent Layer

After the RAG foundation is mature, add an AI agent.

Possible capabilities:

- search project knowledge
- inspect project status
- identify potentially relevant files
- summarize outstanding work
- generate reports
- identify documentation inconsistencies
- create structured tasks
- interact with approved external tools

Keep tool use explicit and auditable.

---

# 18. Future MCP Layer

The platform should eventually expose useful capabilities through MCP.

Possible tools:

```text
search_project
ask_project
get_document
search_source_code
find_symbol
get_project_status
find_design_requirement
generate_project_report
```

This would allow Claude or another MCP-compatible client to interact with the Project Intelligence Platform.

MCP should be a genuine interface into useful system functionality rather than being included merely as a portfolio buzzword.

---

# 19. Future Automation Layer

The original second portfolio project was an AI Business Automation Agent.

That capability can later demonstrate workflows such as:

```text
incoming request
      ↓
classification
      ↓
structured information extraction
      ↓
database/API lookup
      ↓
decision/workflow
      ↓
draft action
      ↓
human approval
      ↓
execution
```

Human approval should remain in place for consequential actions.

This layer does not need to be built yet.

---

# 20. Testing Requirements

Use automated tests throughout development.

At minimum, eventually cover:

- health/API behaviour
- document validation
- parsing
- chunking
- database operations
- retrieval
- citations
- unsupported queries
- deletion
- malformed uploads
- duplicate ingestion
- configuration failures

Where practical, separate:

```text
unit tests
integration tests
evaluation tests
```

Do not mock everything to the point that tests no longer exercise meaningful behaviour.

---

# 21. Security Considerations

Treat uploaded documents as untrusted input.

Eventually consider:

- upload size limits
- allowed file types
- filename sanitisation
- malicious document handling
- secrets management
- authentication
- API authorization
- prompt injection from retrieved documents
- data isolation
- logging/privacy
- rate limiting

Do not prematurely implement enterprise infrastructure, but document relevant risks.

---

# 22. Development Philosophy

This is a PORTFOLIO ENGINEERING PROJECT.

Prefer:

- simple architecture
- explicit interfaces
- typed Python
- understandable abstractions
- small modules
- tests
- good documentation
- reproducible development
- meaningful commits

Avoid:

- unnecessary frameworks
- architecture astronautics
- huge dependency graphs
- premature microservices
- copying tutorial architecture blindly
- introducing technology simply because it sounds impressive

Every significant technology should have an answer to:

> Why is this here?

---

# 23. AI-Assisted Development Is Part of the Portfolio

Claude Code is intentionally being used to build this project.

That is not something we need to hide.

However, generated code must be:

- reviewed
- understood
- tested
- maintainable

I should be able to explain major architectural decisions in an interview.

When implementing a significant subsystem, explain briefly:

1. what we are building;
2. why this approach was selected;
3. important alternatives;
4. important tradeoffs;
5. what I should understand for an interview.

Do not turn every implementation step into a huge tutorial, but help ensure I understand important concepts.

---

# 24. README Expectations

The final README should eventually communicate:

1. What problem the system solves
2. Why it exists
3. Architecture
4. Tech stack
5. How RAG works
6. Retrieval architecture
7. Citation strategy
8. Evaluation methodology
9. Actual benchmark results
10. Screenshots/demo
11. How to run locally
12. Docker instructions
13. API examples
14. Known limitations
15. Security considerations
16. Future improvements

It should read like an engineering portfolio project, not a classroom assignment.

---

# 25. Suggested Milestones

## Milestone 1 — Foundation

Existing starter repo.

Verify:

- FastAPI
- PostgreSQL
- pgvector
- SQLAlchemy
- Docker
- configuration
- tests
- health endpoint

Fix problems rather than blindly replacing the foundation.

---

## Milestone 2 — Document Ingestion

Implement:

- upload endpoint
- PDF extraction
- TXT extraction
- Markdown extraction
- validation
- metadata
- chunking
- persistence
- document listing
- document deletion
- tests

Do this next.

---

## Milestone 3 — Embeddings + Semantic Search

Implement:

- embedding provider abstraction
- document embeddings
- query embeddings
- pgvector similarity search
- top-K retrieval
- metadata/provenance
- search endpoint
- tests

Avoid unnecessary vendor lock-in.

---

## Milestone 4 — Grounded Q&A

Implement:

- `/ask`
- context construction
- LLM provider abstraction
- grounded prompting
- citations
- insufficient-evidence behaviour
- tests

---

## Milestone 5 — Technical Source Code

Add:

- Python ingestion
- GDScript ingestion
- JSON/YAML
- source paths
- line ranges
- symbol-aware metadata

Then investigate AST-aware chunking.

---

## Milestone 6 — Hybrid Retrieval

Add:

- lexical/full-text search
- vector search
- fusion
- reranking
- thresholds

Benchmark against vector-only retrieval.

---

## Milestone 7 — Evaluation

Create evaluation datasets and tooling.

Measure actual:

- retrieval
- answers
- citations
- hallucination/unsupported responses
- latency
- tokens
- cost

---

## Milestone 8 — UI

Build a professional but simple interface.

Potential areas:

```text
Projects
Documents
Ask
Search
Sources
Evaluation
System status
```

Functionality and demonstrability matter more than flashy visual design.

---

## Milestone 9 — MCP

Expose selected capabilities through MCP.

---

## Milestone 10 — Agent + Automation

Add controlled agent/tool workflows.

---

## Milestone 11 — Deployment

Containerise/deploy the complete application.

Potentially use Azure/AWS depending on portfolio value and cost.

Add:

- CI
- tests
- environment configuration
- deployment documentation
- monitoring

---

# 26. Immediate Task

START WITH MILESTONE 2.

First:

1. Inspect the entire existing repository.
2. Read the existing `CLAUDE.md`.
3. Read the README.
4. Inspect dependencies.
5. Inspect Docker configuration.
6. Inspect models.
7. Run existing tests.
8. Run/verify the existing application if possible.
9. Identify any problems in the starter.
10. Produce a concise implementation plan for Milestone 2.

Then implement:

### Document ingestion

Support initially:

- PDF
- `.txt`
- `.md`

Implement appropriate:

- file validation
- extraction
- metadata
- chunking
- database persistence
- API schemas
- upload endpoint
- list endpoint
- get endpoint
- delete endpoint
- tests

Preserve metadata required for future citations.

Do NOT implement the LLM/answer generation yet unless required for architecture.

Do NOT introduce LangChain/LlamaIndex.

Do NOT start MCP/agents yet.

Do NOT overengineer authentication/cloud infrastructure yet.

Keep the architecture extensible enough for later embedding/search/evaluation work.

---

# 27. Working Style

Before major implementation:

- inspect existing code;
- understand what already works;
- preserve useful architecture;
- make a short plan.

Then implement autonomously.

Run:

- formatting/linting if configured;
- type checking if configured;
- unit tests;
- relevant integration tests.

Fix failures before considering the milestone complete.

At completion, report:

### Implemented
What changed.

### Architecture
Important decisions and why.

### Tests
What was run and results.

### How to Test Manually
Exact commands/endpoints.

### What I Should Understand
The important concepts I should be able to explain during an AI engineering interview.

### Next Milestone
What should be built next, but do not automatically start a large new milestone unless instructed.

The goal is not simply to make the application work.

The goal is to produce a credible AI engineering portfolio project that demonstrates practical ability to employers.