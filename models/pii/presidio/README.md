# Presidio models (placeholder)

`care.pii.providers.presidio_provider` wraps Microsoft Presidio
in `local_files_only=True` mode. Place spaCy / transformers models
under:

```
models/pii/presidio/<spacy_or_hf_model>/
```

The provider sets every Hugging Face offline env var before importing
`presidio_analyzer`, and it raises `ConfigError` if the model
directory is absent.

## License

Presidio is MIT. spaCy / Hugging Face models carry their own licenses;
verify each before deployment.
