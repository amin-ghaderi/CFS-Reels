# ADR 0005: Provider-independent AI

## Context

Legacy semantic steps invoke Cursor. The product must also allow local models and other cloud vendors, and those vendors do not share one capability set.

## Decision

Tasks declare input schema, output schema, required capabilities, validation, and fallback. Adapters advertise capabilities (`GENERATE_TEXT`, `GENERATE_STRUCTURED`, `SCORE`, `CHOOSE`, `CLASSIFY`, and others). There is no single `LLMProvider` that pretends every backend can score, see, and call tools. Generative and decision roles stay distinct. Cursor may exist as a development adapter only.

## Consequences

- Adding a vendor is an adapter plus capability flags, not a new editorial pipeline.
- A task fails or follows its fallback when the selected adapter lacks the capability.
- Media stages do not take a provider argument.

## Status

Accepted
