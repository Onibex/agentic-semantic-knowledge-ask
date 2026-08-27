# Onibex ASK — Agentic Semantic Knowledge

A deterministic Text-to-SQL agent and the accompanying YAML specification for
AI-ready data products. The LLM maps questions to a curated semantic layer;
it never invents table or column names.

![ASK Chat answering a stock-coverage question: the written answer, the key figures, the results table, and the generated SQL joining two Gold Data Products](images/ask-chat-answer.gif)

The question above names no table. It spans two Data Products — open sales orders and
inventory position — and the SQL underneath is the join ASK computed between them.

- [Repository](https://github.com/Onibex/agentic-semantic-knowledge-ask)
- [ASK specification](https://github.com/Onibex/agentic-semantic-knowledge-ask/blob/main/definition/README.md)
- [Platform manual](https://github.com/Onibex/agentic-semantic-knowledge-ask/blob/main/platform/docs/README.md)
- [llms.txt](llms.txt) — machine-readable summary for AI agents

## Licensing

Source-available under [PolyForm Strict 1.0.0 / PolyForm Free Trial 1.0.0](https://github.com/Onibex/agentic-semantic-knowledge-ask/blob/main/LICENSE).
Production or any other commercial use requires a
[commercial license](https://github.com/Onibex/agentic-semantic-knowledge-ask/blob/main/COMMERCIAL-LICENSE.md)
— contact@onibex.com.

Copyright (c) 2026 Onibex, LLC. All rights reserved.
