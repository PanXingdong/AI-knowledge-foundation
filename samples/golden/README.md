# Golden Samples

This directory contains public synthetic processed outputs for the Layer1 to Layer2 contract.

These samples are safe to commit because they do not contain supplier, customer, or internal confidential content. They are used to verify that a fresh checkout can validate processed documents, build a Context Pack, and trace evidence without requiring real engineering documents.

Run:

```powershell
python -m agent_knowledge_hub.cli validate-processed `
  --processed-dir ".\samples\golden" `
  --require-valid
```
