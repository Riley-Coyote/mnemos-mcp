"""The local model loads and works without printing at the person.

A stranger's `mnemos embeddings download` printed a torch notice about a
feature Mnemos never uses, a "Loading weights" bar, and the Hub's "Please set
a HF_TOKEN" (Mnemos needs no account). `mnemos doctor` printed transformers'
"BertModel LOAD REPORT ... UNEXPECTED" for a harmless unused weight, and a
server logging at INFO drew a "Batches" bar for every capture and recall
(found 2026-10-16). Loads now run quiet and put the libraries' settings back,
and the encoder's bar is off.
"""

import logging
import sys
import types

import pytest

from mnemos.store import embedding_index as ei


def test_a_load_is_quiet_and_puts_everything_back(monkeypatch):
    hf_logging = pytest.importorskip("transformers.utils.logging")
    hub_logging = pytest.importorskip("huggingface_hub.utils.logging")
    seen = []
    module = types.ModuleType("sentence_transformers")

    class SentenceTransformer:
        def __init__(self, name, **kwargs):
            seen.append((hf_logging.get_verbosity(), hf_logging.is_progress_bar_enabled(),
                         hub_logging.get_verbosity()))

    module.SentenceTransformer = SentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)
    hf_logging.set_verbosity_warning()
    hf_logging.enable_progress_bar()
    hub_logging.set_verbosity_warning()

    ei._load_cached_model("all-MiniLM-L6-v2")

    assert seen and all(entry == (logging.ERROR, False, logging.ERROR) for entry in seen)
    assert hf_logging.get_verbosity() == logging.WARNING
    assert hf_logging.is_progress_bar_enabled()
    assert hub_logging.get_verbosity() == logging.WARNING


def test_the_download_runs_quiet_too(monkeypatch):
    hf_logging = pytest.importorskip("transformers.utils.logging")
    seen = []
    module = types.ModuleType("sentence_transformers")

    class SentenceTransformer:
        def __init__(self, name, **kwargs):
            seen.append(hf_logging.get_verbosity())

    module.SentenceTransformer = SentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)
    monkeypatch.setattr(ei, "_check_local_deps", lambda: True)

    assert ei.download_local_model("all-MiniLM-L6-v2") == "all-MiniLM-L6-v2"
    assert seen == [logging.ERROR]


def test_the_encoder_draws_no_bar_and_torch_says_nothing():
    ei._hush()

    assert logging.getLogger("sentence_transformers.sentence_transformer.model").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger(ei._TORCH_NOTICE).getEffectiveLevel() >= logging.ERROR
