# ROP-Bert

A starter repository structure for the ROP-Bert model.

## Project Knowledge Base

This section is the primary project context for LLM agents. Keep it short, current, and factual.

### Goal

Build ROP-Bert, a clinical language model project with clear boundaries between dataset curation, tokenization, model architecture, and pipeline orchestration.

### Tech Stack

- Python 3
- Standard library only in the current scaffold
- Future backend is TBD, with PyTorch and Hugging Face Transformers as likely candidates

### LLM Rules

- Update this knowledge base whenever the project goal, tech stack, or LLM operating rules change.
- Keep repo structure changes aligned with the `dataset/`, `tokenizer/`, `model/`, and `pipeline/` component boundaries.
- Leave implementation placeholders explicit with `# TODO` until the real implementation exists.
- Do not create package-level convenience imports, facade APIs, or generic abstractions unless the user asks for them or the codebase establishes the pattern.
- Do not commit real patient data, credentials, secrets, or generated cache artifacts.

## Structure

```text
dataset/
  __init__.py
  med_dataset.py
tokenizer/
  __init__.py
  med_tokenizer.py
model/
  __init__.py
  configuration.py
  med_bert.py
pipeline/
  __init__.py
  rop_bert_pipeline.py
```

Current files are lightweight placeholders and scope notes until the real implementation exists.
