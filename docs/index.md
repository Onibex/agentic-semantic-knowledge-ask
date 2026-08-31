![Onibex ASK, Agentic Semantic Knowledge. Plain-language questions in, governed deterministic SQL out](images/ask-banner.png)

# Onibex Agentic Semantic Knowledge (ASK)

Ask your enterprise data a question in plain language. Get governed, deterministic SQL
back, compiled from a business-vocabulary semantic layer and never guessed from raw
schema.

![ASK Chat answering a stock-coverage question: the written answer, the key figures, the results table, and the generated SQL joining two Gold Data Products](images/ask-chat-answer.gif)

The question above names no table. It spans two Data Products, open sales orders and
inventory position, and the SQL underneath is the join ASK computed between them. The
model never sees a table or column name: it chooses among Data Products an author
declared, and the join path is computed from a declared relationship graph rather than
written.

## Two tracks

- [**The ASK specification**](https://github.com/Onibex/agentic-semantic-knowledge-ask/blob/main/definition/README.md).
  A vendor-neutral YAML contract for describing AI-ready data products across Bronze,
  Silver and Gold. Runtime-neutral, so any vendor can adopt it.
- [**The Onibex Agentic Semantic Knowledge Platform**](https://github.com/Onibex/agentic-semantic-knowledge-ask/blob/main/platform/README.md).
  The product that implements the contract end to end, from authoring a semantic layer
  to querying it in plain language.

## Where to go

- [Repository](https://github.com/Onibex/agentic-semantic-knowledge-ask)
- [Getting Started](https://github.com/Onibex/agentic-semantic-knowledge-ask/blob/main/platform/docs/GETTING_STARTED.md).
  An empty machine to a real answer, in about 45 minutes
- [The manual](https://github.com/Onibex/agentic-semantic-knowledge-ask/blob/main/platform/docs/README.md).
  Every page, grouped by what you are trying to do
- [llms.txt](llms.txt). Machine-readable summary for AI agents

## Licensing

Source-available under [PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0](https://github.com/Onibex/agentic-semantic-knowledge-ask/blob/main/LICENSE).
Production or any other commercial use requires a
[commercial license](https://github.com/Onibex/agentic-semantic-knowledge-ask/blob/main/COMMERCIAL-LICENSE.md).
Contact contact@onibex.com.

Copyright (c) 2026 Onibex, LLC. All rights reserved.
