"""Pipeline scope documentation.

This Python script will be used to coordinate the dataset curation module,
tokenizer, and ROP-Bert model.

TODO: Create the pipeline or pretraining runner that takes demo OMOP data from
the dataset component, passes visits through the tokenizer, creates the
ROP-Bert model instance, and tests the full model flow.
"""

# Current integration point (tokenization only):
# - Fit `OMOPMeasurementTokenizer` on the training split measurement rows.
# - Save the tokenizer.
# - Load the tokenizer to transform validation/test rows deterministically.
