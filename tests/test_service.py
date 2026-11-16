from app.answer import NO_RESULTS, PLACEHOLDER
from support import FAQ, POLICY, FakeChat, make_kb


def run(kb, question, history=None, doc_ids=None):
    return list(kb.answer(question, history or [], doc_ids))


def names(events):
    return [name for name, _ in events]


def test_answer_with_a_model_streams_and_cites(tmp_path):
    chat = FakeChat(pieces=["Northwind connects to HubSpot, ", "Salesforce and Pipedrive [1]."])
    kb = make_kb(tmp_path, chat_model=chat)
    kb.ingest_file(FAQ, FAQ.name)
    events = run(kb, "Which tools does Northwind connect to?")
    assert names(events)[:3] == ["status", "sources", "status"]
    assert names(events).count("delta") == 2
    final = events[-1][1]
    assert events[-1][0] == "final"
    assert final["mode"] == "llm"
    assert final["markdown"].endswith(f"Pipedrive{PLACEHOLDER.format(1)}.")
    assert final["citations"][0]["quotes"]
    prompt = chat.calls[0][1][-1]["content"]
    assert prompt.startswith("Sources:\n\n[1] Northwind Analytics Product FAQ")
    assert kb.store.stats()["questions"] == 1


def test_model_failure_falls_back_to_quotes(tmp_path):
    chat = FakeChat(pieces=["Partial ", "answer"], fail_after=1)
    kb = make_kb(tmp_path, chat_model=chat)
    kb.ingest_file(FAQ, FAQ.name)
    events = run(kb, "How long is the free trial?")
    assert "reset" in names(events) and "notice" in names(events)
    final = events[-1][1]
    assert final["mode"] == "quotes"
    assert "14 day free trial" in final["markdown"]


def test_without_a_model_the_answer_quotes_the_documents(tmp_path):
    kb = make_kb(tmp_path)
    kb.ingest_file(POLICY, POLICY.name)
    final = run(kb, "How long must passwords be?")[-1][1]
    assert final["mode"] == "quotes"
    assert "at least 14 characters" in final["markdown"]
    assert final["citations"][0]["heading"] == "2. Passwords and sign-in"


def test_no_documents_selected_means_no_results(tmp_path):
    kb = make_kb(tmp_path, chat_model=FakeChat(pieces=["should not be used"]))
    kb.ingest_file(FAQ, FAQ.name)
    final = run(kb, "Which tools does Northwind connect to?", doc_ids=[])[-1][1]
    assert final["mode"] == "none" and final["markdown"] == NO_RESULTS


def test_follow_up_questions_are_rewritten_with_the_model(tmp_path):
    chat = FakeChat(pieces=["Yes [1]."], rewrite="Does the Team plan include single sign-on?")
    kb = make_kb(tmp_path, chat_model=chat)
    kb.ingest_file(FAQ, FAQ.name)
    history = [
        {"role": "user", "content": "What does the Team plan cost?"},
        {"role": "assistant", "content": "It costs 59 pounds per user per month [1]."},
    ]
    events = run(kb, "Does it include SSO?", history)
    sources_event = dict(events)["sources"]
    assert sources_event["query"] == "Does the Team plan include single sign-on?"
    assert chat.calls[0][0] == "complete"
    stream_messages = chat.calls[1][1]
    assert [m["role"] for m in stream_messages] == ["system", "user", "assistant", "user"]


def test_samples_load_once(tmp_path):
    kb = make_kb(tmp_path)
    first = kb.load_samples()
    assert first >= 2  # the PDF needs pypdf; Markdown and Word always load
    assert kb.load_samples() == 0
    assert kb.health()["samples_loaded"] is True


class FakeVector(list):
    def astype(self, _dtype):
        return self

    def tobytes(self):
        return bytes(len(self))


class FakeEmbedder:
    def __init__(self, name, fail=False):
        self.name = name
        self.fail = fail
        self.calls = 0

    def embed_passages(self, texts):
        self.calls += 1
        if self.fail:
            raise RuntimeError("model missing")
        return [FakeVector([0, 0, 0, 0]) for _ in texts]


def test_embeddings_are_rebuilt_when_the_model_changes(tmp_path):
    kb = make_kb(tmp_path)
    kb.ingest_file(FAQ, FAQ.name)  # indexed without vectors
    chunks = kb.store.stats()["chunks"]

    kb.embedder = FakeEmbedder("fake:a")
    kb.sync_embeddings()
    assert len(kb.store.load_embeddings()) == chunks
    assert kb.store.get_meta("embedding_model") == "fake:a"

    kb.embedder = FakeEmbedder("fake:a")
    kb.sync_embeddings()
    assert kb.embedder.calls == 0  # nothing to do for the same model

    kb.embedder = FakeEmbedder("fake:b", fail=True)
    kb.sync_embeddings()
    assert kb.store.load_embeddings() == []  # old vectors are never mixed with a new model
    assert "no vectors" in kb.embedder_problem
